"""Bounded, account-scoped HTTP streams with ownership outside their generators."""
import asyncio
from contextlib import suppress
import json
import os
import time

import httpx
from fastapi import HTTPException
from starlette.responses import JSONResponse, StreamingResponse

from .live_text import valid_id
from .store import ident


class Reservation:
    def __init__(self, registry, uid, kind):
        self.registry, self.uid, self.kind = registry, uid, kind
        self.id = ident()
        self.created = registry.clock()
        self.auth_checked = time.monotonic()
        self.started = False
        self.closed = False
        self.response = None
        self.runner = None
        self.owner_task = None
        self.subscription = None
        self.retain = False

    def activate(self):
        if self.closed or self.registry.closed:
            return False
        self.started = True
        return True

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.registry.items.pop(self.id, None)
        if self.subscription is not None:
            await self.subscription.close(retain=self.retain and self.started)
        elif self.kind == "events":
            self.registry.cache.release(self.uid, self.id)
        self.registry.released += 1
        if self.response is not None:
            # Release bookkeeping first, even if a broken transport stalls close.
            with suppress(Exception):
                await asyncio.wait_for(self.response.aclose(), timeout=1)


class StreamRegistry:
    """Single-loop counters. Prepared responses expire even if ASGI never calls them."""
    def __init__(self, cache, *, max_viewers=128, max_per_account=4, max_downloads=8,
                 prepare_ttl=5, clock=time.monotonic, hubs=None):
        if min(max_viewers, max_per_account, max_downloads, prepare_ttl) <= 0:
            raise ValueError("Stream budgets must be positive")
        self.cache = cache
        self.hubs = hubs
        self.max_viewers, self.max_per_account = max_viewers, max_per_account
        self.max_downloads, self.prepare_ttl = max_downloads, prepare_ttl
        self.clock = clock
        self.items = {}
        self.closed = False
        self.reaper = None
        self.rejected = self.released = self.expired = 0

    def start(self):
        if self.reaper is None:
            self.reaper = asyncio.create_task(self._reap())

    def reserve(self, uid, kind):
        if self.closed or not valid_id(uid) or kind not in ("events", "download"):
            raise HTTPException(503, "服务暂时不可用，请稍后重试", headers={"Retry-After": "2"})
        selected = [item for item in self.items.values() if item.kind == kind]
        if kind == "events" and sum(item.uid == uid for item in selected) >= self.max_per_account:
            self.rejected += 1
            raise HTTPException(429, "同一账号打开的页面过多，请关闭部分页面后重试", headers={"Retry-After": "5"})
        maximum = self.max_viewers if kind == "events" else self.max_downloads
        if len(selected) >= maximum:
            self.rejected += 1
            raise HTTPException(503, "服务繁忙，请稍后重试", headers={"Retry-After": "2"})
        item = Reservation(self, uid, kind)
        if kind == "events" and self.hubs is None:
            result = self.cache.acquire_result(uid, item.id)
            if result not in ("acquired", "renewed", "already_owned"):
                self.rejected += 1
                raise HTTPException(503, "实时连接暂时繁忙，请稍后重试", headers={"Retry-After": "2"})
        self.items[item.id] = item
        return item

    async def _reap(self):
        try:
            while not self.closed:
                await asyncio.sleep(min(1, self.prepare_ttl / 2))
                current = self.clock()
                for item in tuple(self.items.values()):
                    if not item.started and current - item.created >= self.prepare_ttl:
                        self.expired += 1
                        await item.close()
        except asyncio.CancelledError:
            pass

    async def close(self):
        self.closed = True
        if self.hubs is not None:
            await self.hubs.close()
        if self.reaper is not None:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
            self.reaper = None
        items = tuple(self.items.values())
        tasks = {item.owner_task for item in items
                 if item.owner_task is not None and item.owner_task is not asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(item.close() for item in items), return_exceptions=True)

    def stats(self):
        return {"viewers": sum(item.kind == "events" for item in self.items.values()),
                "upstreams": self.hubs.stats()["upstreams"] if self.hubs else sum(item.kind == "events" and item.response is not None for item in self.items.values()),
                "owners": self.cache.stats()["owners"],
                "downloads": sum(item.kind == "download" for item in self.items.values()),
                "prepared": sum(not item.started for item in self.items.values()),
                "rejected": self.rejected, "released": self.released, "expired": self.expired}


async def initialize_streams(app):
    config = app.state.limits
    from .event_hub import create_hubs
    app.state.event_hubs = create_hubs(app, int(os.getenv("MAX_RUNTIMES", "4")))
    app.state.stream_registry = StreamRegistry(app.state.live_text, max_viewers=config["sse_viewers"],
                                               max_per_account=config["sse_per_account"],
                                               max_downloads=config["downloads"], hubs=app.state.event_hubs)
    app.state.stream_registry.start()


async def close_streams(app):
    await app.state.stream_registry.close()


async def _guard(request, reservation):
    from .app import principal
    config = request.app.state.limits
    renewed = time.monotonic()
    # UUID-derived phase avoids synchronized authentication waves after mass reconnects.
    phase = int(reservation.id[:8], 16) / 0x100000000 * config["auth_recheck_seconds"]
    try:
        await asyncio.sleep(max(0, reservation.auth_checked + phase - time.monotonic()))
        while not reservation.closed:
            await asyncio.wait_for(principal(request), timeout=2)
            current = time.monotonic()
            reservation.auth_checked = current
            if reservation.kind == "events" and reservation.subscription is None and current - renewed >= config["sse_renew_seconds"]:
                result = reservation.registry.cache.acquire_result(reservation.uid, reservation.id)
                if result not in ("acquired", "renewed", "already_owned"):
                    return
                renewed = current
            await asyncio.sleep(config["auth_recheck_seconds"])
    except Exception:
        # Expired auth and an unavailable auth store both fail closed.
        reservation.retain = False
        return


class OwnedStreamResponse(StreamingResponse):
    """The response, not generator iteration, owns reservation and auth-watch lifetime."""
    def __init__(self, content, *, request, reservation, **kwargs):
        super().__init__(content, **kwargs)
        self.request, self.reservation = request, reservation

    async def __call__(self, scope, receive, send):
        item = self.reservation
        # The upstream header wait or delayed ASGI start must not age authentication
        # past its deadline before sending even the first download byte.
        if not item.closed and time.monotonic() - item.auth_checked > 0.5:
            from .app import principal
            try:
                await asyncio.wait_for(principal(self.request), timeout=2)
                item.auth_checked = time.monotonic()
            except Exception as exc:
                await item.close()
                status = exc.status_code if isinstance(exc, HTTPException) else 503
                response = JSONResponse({"message": "连接验证已失效，请重新登录或稍后重试", "code": "stream_auth_failed"},
                                        status_code=status, headers={"Retry-After": "2"} if status == 503 else None)
                await response(scope, receive, send)
                return
            except BaseException:
                await item.close()
                raise
        if not item.activate():
            response = JSONResponse({"message": "连接准备已超时，请重试", "code": "stream_expired"},
                                    status_code=503, headers={"Retry-After": "1"})
            await response(scope, receive, send)
            return
        item.owner_task = asyncio.current_task()
        item.retain = True
        started = False
        finished = False

        async def tracked_send(message):
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        pump = asyncio.create_task(super().__call__(scope, receive, tracked_send))
        item.runner = pump
        guard = asyncio.create_task(_guard(self.request, item))
        try:
            done, _ = await asyncio.wait((pump, guard), return_when=asyncio.FIRST_COMPLETED)
            if pump in done:
                await pump
            else:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
                if started and not finished:
                    with suppress(Exception):
                        await asyncio.wait_for(send({"type": "http.response.body", "body": b"", "more_body": False}), 0.2)
        finally:
            pump.cancel()
            guard.cancel()
            await asyncio.gather(pump, guard, return_exceptions=True)
            # async-for does not close a generator paused at yield when send is cancelled.
            close_body = getattr(self.body_iterator, "aclose", None)
            if close_body is not None:
                with suppress(Exception):
                    await asyncio.wait_for(close_body(), timeout=1)
            await item.close()


def change_notice(envelope):
    if not isinstance(envelope, dict) or envelope.get("directory") != "/workspace":
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    properties = payload.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    resources = None
    if kind in ("message.updated", "message.removed", "message.part.updated", "message.part.removed", "message.part.delta"):
        resources = ["messages"]
    elif kind in ("session.created", "session.updated", "session.deleted", "session.status", "session.idle", "session.error"):
        resources = ["sessions"]
    elif kind in ("permission.asked", "permission.replied", "permission.updated"):
        resources = ["permissions"]
    elif kind in ("question.asked", "question.replied", "question.rejected"):
        resources = ["questions"]
    elif kind in ("file.edited", "file.watcher.updated"):
        resources = ["files"]
    if resources is None:
        return None
    notice = {"type": "updated", "resources": resources}
    sid = properties.get("sessionID")
    if sid is None:
        for field in ("info", "part"):
            value = properties.get(field)
            if isinstance(value, dict):
                sid = value.get("sessionID") or (value.get("id") if kind.startswith("session.") else None)
            if sid is not None:
                break
    if valid_id(sid):
        notice["session_id"] = sid
    return notice


async def _events(response):
    """Bound partial lines and complete data frames before parsing native JSON."""
    data, line = [], bytearray()
    size = 0
    async for chunk in response.aiter_bytes():
        start = 0
        while start < len(chunk):
            end = chunk.find(b"\n", start)
            end = len(chunk) if end < 0 else end
            if len(line) + end - start > 1024 * 1024:
                raise ValueError("Upstream event exceeds the stream budget")
            line.extend(memoryview(chunk)[start:end])
            start = end + 1
            if end == len(chunk):
                continue
            text = bytes(line).removesuffix(b"\r").decode("utf-8")
            line.clear()
            if not text:
                if data:
                    try:
                        value = json.loads("\n".join(data))
                    except (ValueError, TypeError):
                        value = None
                    if value is not None:
                        yield value
                data, size = [], 0
            elif text.startswith("data:"):
                value = text[5:].removeprefix(" ")
                size += len(value.encode("utf-8"))
                if size > 1024 * 1024:
                    raise ValueError("Upstream event exceeds the stream budget")
                data.append(value)


async def _event_body(request, response, item):
    yield b'event: change\ndata: {"type":"connected"}\n\n'
    iterator = _events(response).__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    heartbeat = request.app.state.limits["sse_heartbeat_seconds"]
    next_heartbeat = time.monotonic() + heartbeat
    try:
        while not item.closed:
            done, _ = await asyncio.wait((pending,), timeout=max(0, next_heartbeat - time.monotonic()))
            if time.monotonic() >= next_heartbeat:
                yield b": heartbeat\n\n"
                next_heartbeat = time.monotonic() + heartbeat
            if not done:
                continue
            try:
                envelope = pending.result()
            except StopAsyncIteration:
                return
            pending = asyncio.create_task(iterator.__anext__())
            item.registry.cache.observe(item.uid, envelope, item.id)
            notice = change_notice(envelope)
            if notice is not None:
                yield ("event: change\ndata: " + json.dumps(notice, separators=(",", ":")) + "\n\n").encode()
    except (httpx.HTTPError, ValueError):
        return
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await iterator.aclose()


async def _open_response(client, request, item):
    response = await client.send(request, stream=True)
    # Attach before this task completes, so cancellation of its waiter cannot orphan it.
    item.response = response
    if item.closed:
        await asyncio.wait_for(response.aclose(), timeout=1)
        raise HTTPException(503, "连接准备已超时，请重试", headers={"Retry-After": "1"})
    return response


async def event_response(request, user):
    from .app import principal, runtime
    await principal(request)
    authenticated = time.monotonic()
    base, headers = await request.app.state.db_work.run(runtime, request, user)
    item = request.app.state.stream_registry.reserve(user["uid"], "events")
    item.auth_checked = authenticated
    try:
        async def authorize():
            return await principal(request)
        subscriber = await request.app.state.event_hubs.subscribe(item, authorize)
        return OwnedStreamResponse(subscriber.body(), request=request, reservation=item,
                                   media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    except BaseException as exc:
        await item.close()
        if isinstance(exc, (httpx.HTTPError, TimeoutError)):
            raise HTTPException(503, "实时连接暂时不可用，请稍后重试", headers={"Retry-After": "2"}) from None
        raise


async def download_response(request, user, path):
    from .app import principal, runtime
    await principal(request)
    authenticated = time.monotonic()
    base, headers = await request.app.state.db_work.run(runtime, request, user)
    item = request.app.state.stream_registry.reserve(user["uid"], "download")
    item.auth_checked = authenticated
    try:
        client = request.app.state.download_http
        response = await asyncio.wait_for(_open_response(client, client.build_request("GET", base + path, headers=headers), item), timeout=4)
        if response.status_code != 200:
            raise HTTPException(404, "文件不存在或不可下载")
        return OwnedStreamResponse(response.aiter_bytes(), request=request, reservation=item,
                                   media_type="application/octet-stream",
                                   headers={"Content-Disposition": response.headers.get("Content-Disposition", "attachment")})
    except BaseException as exc:
        await item.close()
        if isinstance(exc, (httpx.HTTPError, TimeoutError)):
            raise HTTPException(503, "文件服务暂时无法连接", headers={"Retry-After": "2"}) from None
        raise
