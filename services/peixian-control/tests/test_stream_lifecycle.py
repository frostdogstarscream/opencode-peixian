"""ASGI lifecycle checks use synthetic byte streams, never live accounts or services."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
from types import SimpleNamespace

from fastapi import HTTPException
import httpx
import pytest
from starlette.requests import Request

from control.concurrency import DEFAULTS, WorkPool
from control.live_text import LiveTextCache
from control.streams import StreamRegistry, OwnedStreamResponse, event_response, download_response, change_notice, _events


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, chunks=(), quiet=False):
        self.chunks, self.quiet = chunks, quiet
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.quiet:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def scope(app):
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "app": app, "method": "GET", "path": "/api/console/v1/events", "raw_path": b"/api/console/v1/events",
            "query_string": b"", "headers": [], "scheme": "http", "server": ("test", 80),
            "client": ("synthetic", 1), "http_version": "1.1"}


async def receive():
    await asyncio.Event().wait()


@asynccontextmanager
async def fixture(monkeypatch, *, chunks=(), quiet=True, status=200, prepare_ttl=5, max_owners=64):
    import control.app as app_module
    state = SimpleNamespace(limits={**DEFAULTS, "auth_recheck_seconds": .02, "sse_renew_seconds": .03,
                                    "sse_heartbeat_seconds": .05}, valid=True, auth_calls=0)
    app = SimpleNamespace(state=state)
    request = Request(scope(app))
    user = {"uid": "synthetic-account"}
    state.live_text = LiveTextCache(max_owners=max_owners, owner_ttl_seconds=.2)
    state.db_work = WorkPool(2, 2, .1, "stream-test")
    created = []

    async def principal(request):
        state.auth_calls += 1
        if not state.valid:
            raise HTTPException(401, "synthetic revoked")
        return user

    monkeypatch.setattr(app_module, "principal", principal)
    monkeypatch.setattr(app_module, "runtime", lambda *args, **kwargs: ("http://synthetic-upstream", {"X-Fixture": "synthetic"}))

    def transport(request):
        stream = BytesStream(chunks, quiet)
        created.append(stream)
        return httpx.Response(status, stream=stream)

    state.stream_http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    state.download_http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    from control.event_hub import AccountEventHubs
    state.limits.update(hub_idle_seconds=0, hub_retention_seconds=0)
    async def binding(uid):
        if not state.valid:
            raise HTTPException(401, "synthetic revoked")
        return {"base": "http://synthetic-upstream", "headers": {}, "identity": uid}
    async def active(value):
        return False
    # The dynamic client allows cancellation/timeout tests to replace it.
    class Client:
        def build_request(self, *args, **kwargs):
            return state.stream_http.build_request(*args, **kwargs)
        async def send(self, *args, **kwargs):
            return await state.stream_http.send(*args, **kwargs)
    state.event_hubs = AccountEventHubs(Client(), state.live_text, state.limits, binding, active, maximum=max_owners)
    state.stream_registry = StreamRegistry(state.live_text, prepare_ttl=prepare_ttl, hubs=state.event_hubs)
    state.stream_registry.start()
    try:
        yield app, request, user, created
    finally:
        await state.stream_registry.close()
        await state.stream_http.aclose()
        await state.download_http.aclose()
        await state.db_work.close()


def test_viewer_and_owner_admission_are_distinct_and_bounded():
    async def run():
        cache = LiveTextCache(max_owners=64)
        registry = StreamRegistry(cache)
        items = [registry.reserve("account-" + str(i // 4), "events") for i in range(128)]
        assert registry.stats()["viewers"] == 128
        assert cache.stats()["owners"] == 32
        with pytest.raises(HTTPException) as error:
            registry.reserve("account-0", "events")
        assert error.value.status_code == 429
        with pytest.raises(HTTPException) as error:
            registry.reserve("another-account", "events")
        assert error.value.status_code == 503
        for item in items:
            await item.close()
            await item.close()
        assert registry.stats()["released"] == 128
        assert registry.stats()["viewers"] == cache.stats()["owners"] == 0
        registry = StreamRegistry(LiveTextCache(max_owners=1))
        owner = registry.reserve("first", "events")
        follower = registry.reserve("first", "events")
        with pytest.raises(HTTPException) as error:
            registry.reserve("second", "events")
        assert error.value.status_code == 503
        assert registry.stats()["viewers"] == 2
        await registry.close()
    asyncio.run(run())


def test_downloads_have_separate_admission_budget():
    async def run():
        registry = StreamRegistry(LiveTextCache())
        downloads = [registry.reserve("account", "download") for _ in range(8)]
        with pytest.raises(HTTPException) as error:
            registry.reserve("account", "download")
        assert error.value.status_code == 503
        event = registry.reserve("account", "events")
        assert registry.stats()["viewers"] == 1
        assert registry.stats()["downloads"] == 8
        await registry.close()
        assert registry.stats()["viewers"] == registry.stats()["downloads"] == 0
    asyncio.run(run())


def test_shared_reader_does_not_keep_revoked_viewer_alive(monkeypatch):
    async def run():
        import control.app as app_module
        async with fixture(monkeypatch) as (app, first, user, created):
            second = Request(scope(app))
            revoked = False
            async def principal(request):
                if request is first and revoked:
                    raise HTTPException(401, "synthetic revoked")
                return user
            monkeypatch.setattr(app_module, "principal", principal)
            responses = [await event_response(first, user), await event_response(second, user)]
            async def send(message):
                pass
            tasks = [asyncio.create_task(response(request.scope, receive, send))
                     for response, request in zip(responses, (first, second))]
            try:
                await asyncio.sleep(.05)
                assert len(created) == 1
                revoked = True
                await asyncio.wait_for(tasks[0], .5)
                assert not tasks[1].done() and not created[0].closed
                assert app.state.event_hubs.stats()["subscribers"] == 1
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(run())


def test_never_started_response_expires_closes_upstream_and_rejects_late_start(monkeypatch):
    async def run():
        async with fixture(monkeypatch, prepare_ttl=.04) as (app, request, user, created):
            response = await event_response(request, user)
            assert app.state.stream_registry.stats()["prepared"] == 1
            await asyncio.sleep(.09)
            assert app.state.stream_registry.stats()["viewers"] == 0
            assert created[0].closed
            messages = []
            async def send(message):
                messages.append(message)
            await response(request.scope, receive, send)
            assert messages[0]["status"] == 503
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["construction", "response_start"])
def test_response_construction_or_start_failure_releases_every_reservation(monkeypatch, failure):
    async def run():
        import control.streams as streams_module
        async with fixture(monkeypatch) as (app, request, user, created):
            if failure == "construction":
                def broken(*args, **kwargs):
                    raise RuntimeError("synthetic construction")
                monkeypatch.setattr(streams_module, "OwnedStreamResponse", broken)
                with pytest.raises(RuntimeError, match="construction"):
                    await event_response(request, user)
            else:
                response = await event_response(request, user)
                async def send(message):
                    raise RuntimeError("synthetic response start")
                with pytest.raises(RuntimeError, match="response start"):
                    await response(request.scope, receive, send)
            assert created[0].closed
            assert app.state.stream_registry.stats()["viewers"] == 0
            assert app.state.live_text.stats()["owners"] == 0
    asyncio.run(run())


def test_cancel_before_generator_enters_releases_response_resources(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as (app, request, user, created):
            response = await event_response(request, user)
            started = asyncio.Event()
            async def send(message):
                if message["type"] == "http.response.start":
                    started.set()
                    await asyncio.Event().wait()
            task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(started.wait(), .5)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert created[0].closed
            assert app.state.stream_registry.stats()["viewers"] == 0
            assert app.state.live_text.stats()["owners"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["events", "download"])
def test_revocation_stops_a_slow_downstream_independently_of_yield(monkeypatch, kind):
    async def run():
        async with fixture(monkeypatch, chunks=(b"synthetic file bytes",)) as (app, request, user, created):
            response = await event_response(request, user) if kind == "events" else await download_response(request, user, "/files/synthetic/download")
            blocked = asyncio.Event()
            async def send(message):
                if message["type"] == "http.response.body":
                    blocked.set()
                    await asyncio.Event().wait()
            task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(blocked.wait(), .5)
            app.state.valid = False
            await asyncio.wait_for(task, .5)
            assert created[0].closed
            assert app.state.stream_registry.stats()["viewers"] == 0
            assert app.state.stream_registry.stats()["downloads"] == 0
    asyncio.run(run())


def test_active_response_survives_prepared_ttl_and_releases_on_cancel(monkeypatch):
    async def run():
        async with fixture(monkeypatch, prepare_ttl=.03) as (app, request, user, created):
            response = await event_response(request, user)
            messages = []
            async def send(message):
                messages.append(message)
            task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.sleep(.09)
            assert app.state.stream_registry.stats()["viewers"] == 1
            assert app.state.stream_registry.stats()["prepared"] == 0
            assert any(b"heartbeat" in item.get("body", b"") for item in messages)
            assert app.state.auth_calls >= 3
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert created[0].closed
            assert app.state.stream_registry.stats()["viewers"] == 0
    asyncio.run(run())


def test_upstream_status_failure_releases_before_returning_http_error(monkeypatch):
    async def run():
        async with fixture(monkeypatch, status=503) as (app, request, user, created):
            with pytest.raises(HTTPException) as error:
                await event_response(request, user)
            assert error.value.status_code == 503
            assert created[0].closed
            assert app.state.stream_registry.stats()["viewers"] == 0
    asyncio.run(run())


def test_header_connection_cancel_releases_even_without_an_upstream_response(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as (app, request, user, created):
            waiting = asyncio.Event()
            async def blocked(request):
                waiting.set()
                await asyncio.Event().wait()
            async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
                app.state.stream_http = client
                task = asyncio.create_task(event_response(request, user))
                await asyncio.wait_for(waiting.wait(), .5)
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                assert app.state.stream_registry.stats()["viewers"] == 0
                assert app.state.live_text.stats()["owners"] == 0
    asyncio.run(run())


def test_header_wait_has_total_timeout_not_just_a_connect_timeout(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as (app, request, user, created):
            async def blocked(request):
                await asyncio.Event().wait()
            async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
                app.state.stream_http = client
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(event_response(request, user), 4.8)
                assert error.value.status_code == 503
                assert app.state.stream_registry.stats()["viewers"] == 0
    asyncio.run(run())


def test_native_frames_are_bounded_support_split_utf8_and_do_not_expose_private_fields():
    async def run():
        envelope = {"directory": "/workspace", "payload": {"type": "message.part.delta", "properties": {
            "sessionID": "synthetic-session", "delta": "中文正文", "private": "synthetic-credential"}}}
        encoded = ("data: " + json.dumps(envelope, ensure_ascii=False) + "\r\n\r\n").encode()
        response = httpx.Response(200, stream=BytesStream([encoded[i:i + 7] for i in range(0, len(encoded), 7)]))
        events = [event async for event in _events(response)]
        assert events == [envelope]
        notice = change_notice(events[0])
        assert notice == {"type": "updated", "resources": ["messages"], "session_id": "synthetic-session"}
        assert "synthetic-credential" not in json.dumps(notice)
        assert change_notice({**envelope, "directory": "/other"}) is None
        bad = httpx.Response(200, stream=BytesStream([b"data: ", b"x" * (1024 * 1024)]))
        with pytest.raises(ValueError, match="budget"):
            async for item in _events(bad):
                pytest.fail("Oversize unfinished frames must not be dispatched")
    asyncio.run(run())


def test_cache_acquire_result_classifies_follower_and_owner_capacity():
    cache = LiveTextCache(max_owners=1)
    assert cache.acquire_result("account", "first") == "acquired"
    assert cache.acquire_result("account", "first") == "renewed"
    assert cache.acquire_result("account", "second") == "already_owned"
    assert cache.acquire_result("other", "owner") == "owner_capacity_exceeded"
    assert cache.acquire_result("../account", "owner") == "invalid_identity"
    assert cache.acquire("account", "first") is True
    assert cache.acquire("account", "second") is False


@pytest.mark.parametrize("shutdown", [False, True])
def test_cancel_during_send_closes_body_generator_before_return(monkeypatch, shutdown):
    async def run():
        async with fixture(monkeypatch) as (app, request, user, created):
            ended = asyncio.Event()
            blocked = asyncio.Event()
            async def body():
                try:
                    yield b"synthetic body"
                    await asyncio.Event().wait()
                finally:
                    ended.set()
            item = app.state.stream_registry.reserve(user["uid"], "download")
            response = OwnedStreamResponse(body(), request=request, reservation=item)
            async def send(message):
                if message["type"] == "http.response.body":
                    blocked.set()
                    await asyncio.Event().wait()
            task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(blocked.wait(), .5)
            if shutdown:
                await app.state.stream_registry.close()
            else:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert ended.is_set()
            assert app.state.stream_registry.stats()["downloads"] == 0
    asyncio.run(run())


def test_cancel_after_upstream_headers_cannot_orphan_the_response(monkeypatch):
    async def run():
        import control.streams as streams_module
        original = streams_module._open_response
        headers_ready = asyncio.Event()
        async def paused(client, upstream_request, item):
            response = await original(client, upstream_request, item)
            headers_ready.set()
            await asyncio.Event().wait()
            return response
        monkeypatch.setattr(streams_module, "_open_response", paused)
        async with fixture(monkeypatch) as (app, request, user, created):
            task = asyncio.create_task(event_response(request, user))
            await asyncio.wait_for(headers_ready.wait(), .5)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert created[0].closed
            assert app.state.stream_registry.stats()["viewers"] == 0
            assert app.state.live_text.stats()["owners"] == 0
    asyncio.run(run())


def test_first_auth_recheck_is_spread_across_the_configured_interval(monkeypatch):
    async def run():
        from control.streams import Reservation, _guard
        import time
        delays = []
        async def capture_sleep(delay):
            delays.append(delay)
            raise asyncio.CancelledError()
        monkeypatch.setattr(asyncio, "sleep", capture_sleep)
        registry = StreamRegistry(LiveTextCache())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(limits=DEFAULTS)))
        for prefix in ("00000000", "80000000", "ffffffff"):
            item = Reservation(registry, "account", "events")
            item.id = prefix + "0" * 24
            item.auth_checked = time.monotonic()
            with pytest.raises(asyncio.CancelledError):
                await _guard(request, item)
        assert delays[0] == 0
        assert .98 < delays[1] <= 1
        assert 1.98 < delays[2] < 2
    asyncio.run(run())


def test_delayed_response_checks_auth_before_sending_any_body(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as (app, request, user, created):
            response = await download_response(request, user, "/files/synthetic/download")
            response.reservation.auth_checked -= 1
            app.state.valid = False
            messages = []
            async def send(message):
                messages.append(message)
            await response(request.scope, receive, send)
            assert messages[0]["status"] == 401
            assert not any(b"synthetic file" in item.get("body", b"") for item in messages)
            assert created[0].closed
            assert app.state.stream_registry.stats()["downloads"] == 0
    asyncio.run(run())



def test_registry_hub_failure_still_closes_reservations_and_reaper(monkeypatch):
    from control.shutdown import ShutdownError
    async def run():
        async with fixture(monkeypatch) as (app, request, user, created):
            registry = app.state.stream_registry
            item = registry.reserve("another", "download")
            item.response = httpx.Response(200, stream=BytesStream())
            original = registry.hubs.close
            async def fail():
                raise TimeoutError()
            registry.hubs.close = fail
            with pytest.raises(ShutdownError):
                await registry.close()
            assert registry.closed and registry.reaper is None
            assert item.closed and item.response.is_closed
            assert registry.released == 1
            assert registry.shutdown.report["stages"][0]["errors"] == ["timeout"]
            with pytest.raises(HTTPException):
                registry.reserve("another", "download")
            # Fixture cleanup may observe the same error; explicitly reset only test wrapper.
            registry.hubs.close = original
            async def completed():
                return None
            registry.shutdown_task = asyncio.create_task(completed())
    asyncio.run(run())


def test_one_reservation_failure_does_not_skip_other_account_cleanup():
    from control.shutdown import ShutdownError
    async def run():
        registry = StreamRegistry(LiveTextCache())
        registry.start()
        first = registry.reserve("a", "download")
        second = registry.reserve("b", "download")
        class Broken:
            async def aclose(self):
                raise ValueError("private transport failure")
        first.response = Broken()
        second.response = httpx.Response(200, stream=BytesStream())
        with pytest.raises(ShutdownError):
            await registry.close()
        assert second.response.is_closed
        assert registry.released == 2 and registry.reaper is None
        assert "private transport" not in str(registry.shutdown.report)
    asyncio.run(run())
