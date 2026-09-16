import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import HTTPException

from control.concurrency import DEFAULTS
from control.event_hub import AccountEventHubs, RESYNC
from control.live_text import LiveTextCache
from control.streams import StreamRegistry
from test_live_text import seed, delta_event


@asynccontextmanager
async def fixture(**settings):
    opened = []
    identity = {"value": 1, "allowed": True, "active": False}
    class Stream(httpx.AsyncByteStream):
        def __init__(self):
            self.queue = asyncio.Queue()
            self.closed = False
        async def __aiter__(self):
            while True:
                item = await self.queue.get()
                if item is None:
                    return
                yield item
        async def aclose(self):
            if identity.get("cleanup_entered") is not None:
                identity["cleanup_entered"].set()
                try:
                    await identity["cleanup_resume"].wait()
                except asyncio.CancelledError:
                    # Simulate an upstream which must finish asynchronous cleanup.
                    await identity["cleanup_resume"].wait()
            self.closed = True
    async def transport(request):
        identity["requests"] = identity.get("requests", 0) + 1
        if opened and identity.get("mode") == "connect":
            await asyncio.Event().wait()
        if opened and identity.get("mode") == "503":
            return httpx.Response(503)
        stream = Stream()
        if opened and identity.get("mode") == "eof":
            stream.queue.put_nowait(None)
        opened.append(stream)
        return httpx.Response(200, stream=stream)
    async def binding(uid):
        if not identity["allowed"]:
            raise HTTPException(409, "restricted")
        return {"base": "http://synthetic", "headers": {}, "identity": (uid, identity["value"])}
    async def active(value):
        return identity["active"]
    async def authorize():
        return {"uid": "synthetic"}
    cache = LiveTextCache()
    config = {**DEFAULTS, "auth_recheck_seconds": .02, "hub_idle_seconds": .04,
              "hub_retention_seconds": .12, "hub_reconnect_seconds": .01, **settings}
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        hubs = AccountEventHubs(client, cache, config, binding, active, maximum=2)
        registry = StreamRegistry(cache, hubs=hubs)
        async def subscribe(uid="a"):
            item = registry.reserve(uid, "events")
            sub = await hubs.subscribe(item, authorize)
            return item, sub
        try:
            yield hubs, registry, subscribe, opened, identity
        finally:
            await registry.close()


def test_atomic_shared_reader_and_independent_accounts():
    async def run():
        async with fixture() as (hubs, registry, subscribe, opened, identity):
            pairs = await asyncio.gather(*(subscribe() for _ in range(4)))
            assert len(opened) == 1
            assert hubs.stats()["subscribers"] == 4
            assert hubs.cache.stats()["owners"] == 1
            b, other = await subscribe("b")
            assert len(opened) == 2
            pairs[0][1].hub.publish({"type": "updated", "resources": ["messages"]})
            assert all(sub.queue.qsize() == 1 for _, sub in pairs)
            assert other.queue.empty()
            await pairs[0][0].close()
            assert not opened[0].closed
    asyncio.run(run())


def test_slow_queue_is_bounded_and_does_not_block_other_subscribers():
    async def run():
        async with fixture(hub_queue=2) as (hubs, registry, subscribe, opened, identity):
            _, slow = await subscribe()
            _, fast = await subscribe()
            body = fast.body()
            await anext(body)
            for i in range(5):
                fast.hub.publish({"type": "updated", "resources": ["messages"], "session_id": str(i)})
                assert b"updated" in await anext(body)
                assert slow.queue.qsize() <= 2
            assert hubs.stats()["overflows"] > 0
            assert RESYNC in list(slow.queue._queue)
            await body.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("active", [False, True])
def test_last_viewer_retention_is_bounded(active):
    async def run():
        async with fixture() as (hubs, registry, subscribe, opened, identity):
            identity["active"] = active
            item, sub = await subscribe()
            item.started = item.retain = True
            await item.close()
            assert not opened[0].closed
            await asyncio.sleep(.08)
            assert opened[0].closed is (not active)
            await asyncio.sleep(.09)
            assert opened[0].closed and hubs.stats()["hubs"] == 0
    asyncio.run(run())


def test_prepared_cancel_and_pressure_release_retained_reader():
    async def run():
        async with fixture() as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe()
            await item.close()
            assert opened[0].closed
            item, sub = await subscribe()
            item.started = item.retain = True
            await item.close()
            await subscribe("b")
            await subscribe("c")
            assert hubs.stats()["hubs"] == 2
            assert opened[1].closed
    asyncio.run(run())


def test_revoked_binding_closes_readers_and_releases_owners():
    async def run():
        async with fixture() as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe()
            identity["allowed"] = False
            async with asyncio.timeout(.5):
                while not sub.closed:
                    await asyncio.sleep(.01)
            assert sub.closed and opened[0].closed
            assert hubs.cache.stats()["owners"] == 0
    asyncio.run(run())


def test_boot_change_replaces_reader_and_requests_history_resync():
    async def run():
        async with fixture() as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe()
            identity["value"] = 2
            async with asyncio.timeout(1):
                while len(opened) != 2:
                    await asyncio.sleep(.01)
            assert opened[0].closed
            assert sub.hub.identity == ("a", 2)
            assert await sub.queue.get() == RESYNC
    asyncio.run(run())


def test_cache_eviction_resync_reaches_only_the_affected_account_without_next_event():
    async def run():
        async with fixture() as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe("a")
            _, other = await subscribe("b")
            hubs.cache.max_part_bytes = 4
            seed(hubs.cache, "a", sub.hub.id)
            envelope = delta_event(3, "large private synthetic text")
            await opened[0].queue.put(("data: " + json.dumps(envelope) + "\n\n").encode())
            async with asyncio.timeout(1):
                while await sub.queue.get() != RESYNC:
                    pass
            assert other.queue.empty()
            assert hubs.cache.stats()["resync_pending"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "inactive"])
def test_retention_result_cannot_close_a_new_subscription(outcome):
    async def run():
        async with fixture(hub_retention_seconds=5, hub_idle_seconds=0) as (hubs, registry, subscribe, opened, identity):
            entered, resume = asyncio.Event(), asyncio.Event()
            async def suspended():
                entered.set()
                await resume.wait()
                if outcome == "failure":
                    raise HTTPException(401, "expired")
                if outcome == "timeout":
                    raise TimeoutError()
                return False
            item, sub = await subscribe()
            if outcome == "inactive":
                hubs.active = lambda binding: suspended()
            else:
                sub.authorize = suspended
            item.started = item.retain = True
            await item.close()
            await asyncio.wait_for(entered.wait(), 1)
            _, new = await subscribe()
            resume.set()
            await asyncio.sleep(.08)
            assert not new.closed
            assert not new.hub.task.done()
            assert len(opened) == 1
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["503", "eof", "connect", "active", "backoff"])
def test_deadline_is_independent_of_upstream_and_activity(mode, monkeypatch):
    monkeypatch.setattr("control.event_hub.random.random", lambda: 0)
    async def run():
        async with fixture(hub_idle_seconds=0, hub_reconnect_seconds=10 if mode == "backoff" else .01) as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe()
            identity["active"] = True
            identity["mode"] = mode
            if mode == "active":
                async def active(binding):
                    await asyncio.Event().wait()
                hubs.active = active
            item.started = item.retain = True
            await item.close()
            if mode != "active":
                opened[0].queue.put_nowait(None)
            await asyncio.sleep(.35)
            assert sub.hub.closed
            assert sub.hub.task.done()
            assert hubs.stats()["hubs"] == 0
            if mode in ("503", "eof", "connect"):
                assert identity["requests"] >= 2
    asyncio.run(run())


@pytest.mark.parametrize("eof_first", [False, True])
def test_deadline_marks_closed_but_tracks_slow_cleanup_and_rejects_second_reader(eof_first):
    async def run():
        async with fixture(hub_idle_seconds=5) as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe()
            identity["cleanup_entered"] = asyncio.Event()
            identity["cleanup_resume"] = asyncio.Event()
            item.started = item.retain = True
            await item.close()
            if eof_first:
                opened[0].queue.put_nowait(None)
            await asyncio.wait_for(identity["cleanup_entered"].wait(), .5)
            await asyncio.sleep(.16)
            assert sub.hub.closed
            assert not sub.hub.task.done()
            assert hubs.stats()["closing"] == 1
            assert hubs.stats()["closed"] == 0
            try:
                with pytest.raises(HTTPException) as error:
                    await subscribe()
                assert error.value.status_code == 503
                assert len(opened) == 1
                first = asyncio.create_task(sub.hub.close("again"))
                second = asyncio.create_task(sub.hub.close("again"))
                await asyncio.sleep(0)
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
                assert not sub.hub.cleanup_task.done()
            finally:
                identity["cleanup_resume"].set()
            await asyncio.wait_for(second, 1)
            assert hubs.stats()["hubs"] == 0
            assert hubs.stats()["closed"] == 1
            assert sub.hub.task.done() and opened[0].closed
            assert hubs.cache.stats()["owners"] == 0
            _, new = await subscribe()
            assert new.hub is not sub.hub
    asyncio.run(run())


def test_new_subscription_invalidates_old_deadline_and_real_auth_timeout():
    async def run():
        async with fixture(hub_retention_seconds=3) as (hubs, registry, subscribe, opened, identity):
            entered = asyncio.Event()
            async def authorize():
                entered.set()
                await asyncio.Event().wait()
            item, sub = await subscribe()
            sub.authorize = authorize
            item.started = item.retain = True
            await item.close()
            await asyncio.wait_for(entered.wait(), 1)
            _, new = await subscribe()
            await asyncio.sleep(2.1)
            assert not new.closed and not new.hub.task.done()
            assert len(opened) == 1
    asyncio.run(run())


def test_reentry_then_exit_creates_new_deadline_not_old_timer():
    async def run():
        async with fixture(hub_idle_seconds=5, hub_retention_seconds=.3) as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe()
            item.started = item.retain = True
            await item.close()
            await asyncio.sleep(.2)
            second, new = await subscribe()
            second.started = second.retain = True
            await second.close()
            await asyncio.sleep(.15)
            assert not new.hub.closed
            await asyncio.sleep(.2)
            assert new.hub.closed and hubs.stats()["hubs"] == 0
    asyncio.run(run())


def test_shutdown_timeout_keeps_cleanup_tracked():
    async def run():
        async with fixture(hub_shutdown_seconds=.02) as (hubs, registry, subscribe, opened, identity):
            _, sub = await subscribe()
            identity["cleanup_entered"] = asyncio.Event()
            identity["cleanup_resume"] = asyncio.Event()
            try:
                with pytest.raises(TimeoutError):
                    await hubs.close()
                assert hubs.stats()["closing"] == 1
                assert not sub.hub.cleanup_task.done()
                assert not sub.hub.task.done()
            finally:
                identity["cleanup_resume"].set()
            await asyncio.wait_for(sub.hub.close("shutdown_again"), 1)
            assert hubs.stats()["closed"] == 1
            assert hubs.stats()["hubs"] == 0
    asyncio.run(run())



def test_capacity_pressure_has_bounded_wait_for_closing_hub():
    async def run():
        async with fixture(hub_shutdown_seconds=.05) as (hubs, registry, subscribe, opened, identity):
            item, sub = await subscribe("a")
            item.started = item.retain = True
            await item.close()
            await subscribe("b")
            identity["cleanup_entered"] = asyncio.Event()
            identity["cleanup_resume"] = asyncio.Event()
            try:
                async with asyncio.timeout(.3):
                    with pytest.raises(HTTPException) as error:
                        await subscribe("c")
                assert error.value.status_code == 503
                assert hubs.hubs["a"] is sub.hub
                assert not sub.hub.task.done()
                assert len(opened) == 2
            finally:
                identity["cleanup_resume"].set()
            await sub.hub.close("finish_test")
    asyncio.run(run())
