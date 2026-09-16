"""Single-loop, account-scoped readers. Queues contain notices, never text copies."""
import asyncio
from contextlib import suppress
import json
import random
import time

import httpx
from fastapi import HTTPException

from .store import ident


RESYNC = {"type": "resync_required"}


class Subscriber:
    def __init__(self, hub, reservation, authorize):
        self.hub, self.reservation, self.authorize = hub, reservation, authorize
        self.queue = asyncio.Queue(hub.manager.config["hub_queue"])
        self.pending = set()
        self.closed = False

    def put(self, notice):
        if self.closed:
            return
        # Equal pending notifications can be merged without losing a resource.
        key = json.dumps(notice, sort_keys=True)
        if key in self.pending:
            return
        if self.queue.full():
            while not self.queue.empty():
                self.queue.get_nowait()
            self.pending.clear()
            self.hub.manager.overflow += 1
            self.queue.put_nowait(RESYNC)
            self.pending.add(json.dumps(RESYNC, sort_keys=True))
            return
        self.queue.put_nowait(notice)
        self.pending.add(key)

    async def close(self, retain=False):
        if self.closed:
            return
        self.closed = True
        self.hub.subscribers.pop(self.reservation.id, None)
        while not self.queue.empty():
            self.queue.get_nowait()
        self.pending.clear()
        self.queue.put_nowait(None)
        if not self.hub.subscribers:
            self.hub.absent_since = time.monotonic()
            retain = retain and self.hub.manager.config["hub_retention_seconds"] > 0
            self.hub.retainer = self.authorize if retain else None
            if not retain:
                await self.hub.close("last_subscription_closed")

    async def body(self):
        yield b'event: change\ndata: {"type":"connected"}\n\n'
        while not self.closed:
            try:
                notice = await asyncio.wait_for(self.queue.get(), self.hub.manager.config["sse_heartbeat_seconds"])
            except TimeoutError:
                yield b": heartbeat\n\n"
                continue
            if notice is None:
                return
            self.pending.discard(json.dumps(notice, sort_keys=True))
            yield ("event: change\ndata: " + json.dumps(notice, separators=(",", ":")) + "\n\n").encode()


class AccountHub:
    def __init__(self, manager, uid):
        self.manager, self.uid = manager, uid
        self.id = ident()
        self.subscribers = {}
        self.response = None
        self.task = None
        self.ready = asyncio.get_running_loop().create_future()
        self.closed = False
        self.absent_since = None
        self.retainer = None
        self.identity = None

    def publish(self, notice):
        for subscriber in tuple(self.subscribers.values()):
            subscriber.put(notice)

    async def close(self, reason):
        if self.closed:
            return
        self.closed = True
        if not self.ready.done():
            self.ready.set_result(False)
        if self.task is not None and self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for subscriber in tuple(self.subscribers.values()):
            await subscriber.close()
            runner = subscriber.reservation.runner
            if runner is not None and runner is not asyncio.current_task():
                runner.cancel()
        self.manager.cache.release(self.uid, self.id)
        if self.manager.hubs.get(self.uid) is self:
            self.manager.hubs.pop(self.uid)
        self.manager.closed_count += 1
        self.manager.reasons[reason] = self.manager.reasons.get(reason, 0) + 1

    async def run(self):
        from .streams import _events, change_notice, _open_response
        attempt = 0
        try:
            while not self.closed:
                binding = await self.manager.binding(self.uid)
                if self.manager.cache.acquire_result(self.uid, self.id) not in ("acquired", "renewed"):
                    break
                pending = None
                iterator = None
                try:
                    request = self.manager.client.build_request("GET", binding["base"] + "/global/event",
                        headers=binding["headers"], timeout=httpx.Timeout(None, connect=4, write=4, pool=1))
                    self.response = await asyncio.wait_for(_open_response(self.manager.client, request, self), 4)
                    if self.response.status_code != 200:
                        raise httpx.RemoteProtocolError("Event upstream unavailable")
                    self.identity = binding["identity"]
                    if not self.ready.done():
                        self.ready.set_result(True)
                    else:
                        self.publish(RESYNC)
                    iterator = _events(self.response).__aiter__()
                    pending = asyncio.create_task(iterator.__anext__())
                    checked = time.monotonic()
                    renewed = checked
                    opened = checked
                    while not self.closed:
                        done, _ = await asyncio.wait((pending,), timeout=min(.25, self.manager.config["auth_recheck_seconds"]))
                        current = time.monotonic()
                        if self.manager.cache.take_resync(self.uid, self.id):
                            self.publish(RESYNC)
                        if current - checked >= self.manager.config["auth_recheck_seconds"]:
                            fresh = await self.manager.binding(self.uid)
                            if fresh["identity"] != self.identity:
                                self.publish(RESYNC)
                                break
                            checked = current
                            if not self.subscribers:
                                if self.retainer is None:
                                    return
                                await asyncio.wait_for(self.retainer(), 2)
                                absent = current - self.absent_since
                                if absent >= self.manager.config["hub_retention_seconds"]:
                                    return
                                if absent >= self.manager.config["hub_idle_seconds"] and not await self.manager.active(binding):
                                    return
                        if current - renewed >= self.manager.config["sse_renew_seconds"]:
                            ownership = self.manager.cache.acquire_result(self.uid, self.id)
                            if ownership not in ("acquired", "renewed"):
                                return
                            if ownership == "acquired":
                                self.publish(RESYNC)
                            renewed = current
                        if not done:
                            continue
                        try:
                            envelope = pending.result()
                        except StopAsyncIteration:
                            break
                        pending = asyncio.create_task(iterator.__anext__())
                        self.manager.cache.observe(self.uid, envelope, self.id)
                        notice = change_notice(envelope)
                        if notice is not None:
                            self.publish(notice)
                        if current - opened > 30:
                            attempt = 0
                except (httpx.HTTPError, ValueError, TimeoutError):
                    if not self.ready.done():
                        self.ready.set_result(False)
                        return
                finally:
                    if pending is not None:
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
                    if iterator is not None:
                        await iterator.aclose()
                    if self.response is not None:
                        with suppress(Exception):
                            await asyncio.wait_for(self.response.aclose(), 1)
                        self.response = None
                    # An unobserved interval cannot be spliced into the old text.
                    self.manager.cache.release(self.uid, self.id)
                self.publish(RESYNC)
                self.manager.reconnects += 1
                await asyncio.sleep(min(2 ** min(attempt, 5), self.manager.config["hub_reconnect_seconds"]) + random.random() * .2)
                attempt += 1
        except (HTTPException, TimeoutError):
            pass  # Revocation, maintenance, or unknown binding fails closed.
        finally:
            await self.close("reader_closed")


class AccountEventHubs:
    def __init__(self, client, cache, config, binding, active, *, maximum):
        self.client, self.cache, self.config = client, cache, config
        self.binding, self.active = binding, active
        self.maximum = min(maximum, config["sse_owners"], config["sse_viewers"])
        self.hubs = {}
        self.stopped = False
        self.created = self.closed_count = self.reconnects = self.overflow = 0
        self.reasons = {}

    async def subscribe(self, reservation, authorize):
        uid = reservation.uid
        if self.stopped:
            raise HTTPException(503, "实时服务正在关闭", headers={"Retry-After": "2"})
        hub = self.hubs.get(uid)
        if hub is None:
            # No awaits between capacity check and insertion: single-loop atomic.
            if len(self.hubs) >= self.maximum:
                idle = next((value for value in self.hubs.values() if not value.subscribers), None)
                if idle is None:
                    raise HTTPException(503, "实时连接暂时繁忙", headers={"Retry-After": "2"})
                await idle.close("capacity_pressure")
                return await self.subscribe(reservation, authorize)
            hub = AccountHub(self, uid)
            self.hubs[uid] = hub
            self.created += 1
        subscriber = Subscriber(hub, reservation, authorize)
        reservation.subscription = subscriber
        hub.subscribers[reservation.id] = subscriber
        hub.absent_since = None
        if hub.task is None:
            hub.task = asyncio.create_task(hub.run())
        try:
            ready = await asyncio.wait_for(asyncio.shield(hub.ready), 4.2)
            if not ready or hub.closed or reservation.closed:
                raise HTTPException(503, "实时连接暂时不可用，请稍后重试", headers={"Retry-After": "2"})
            return subscriber
        except BaseException:
            await subscriber.close()
            raise

    async def close(self):
        self.stopped = True
        await asyncio.wait_for(asyncio.gather(*(hub.close("shutdown") for hub in tuple(self.hubs.values()))),
                               self.config["hub_shutdown_seconds"])

    def stats(self):
        return {"hubs": len(self.hubs), "upstreams": sum(h.response is not None for h in self.hubs.values()),
            "subscribers": sum(len(h.subscribers) for h in self.hubs.values()),
            "retained": sum(not h.subscribers for h in self.hubs.values()), "created": self.created,
            "closed": self.closed_count, "reconnects": self.reconnects, "overflows": self.overflow,
            "close_reasons": dict(self.reasons)}


def runtime_binding(app, uid):
    store = app.state.store
    with store.read(snapshot=True) as db:
        row = db.execute("SELECT r.*,u.active,u.must_change,u.auth_version FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=?", (uid,)).fetchone()
        mode = db.execute("SELECT maintenance_mode FROM platform_state WHERE id=1").fetchone()[0]
        if (row is None or not row["active"] or row["must_change"] or row["security_blocked"]
                or row["recovery_required"] or row["status"] not in ("ready", "updating", "draining") or mode != "normal"):
            raise HTTPException(409, "环境暂时受限，请稍后重试")
        return {"base": f"http://px-{row['id']}-gateway:8080",
            "headers": {"X-Peixian-Key": store.decrypt(row["spec"])["gateway_key"]},
            "identity": (row["id"], row["gateway_boot_id"], row["relay_boot_id"], row["revision"], row["authorization_version"], row["auth_version"])}


def create_hubs(app, maximum):
    async def binding(uid):
        return await asyncio.wait_for(app.state.db_work.run(runtime_binding, app, uid), 2)
    async def active(value):
        try:
            response = await app.state.http.get(value["base"] + "/internal/runtime/state", headers=value["headers"], timeout=1)
            response.raise_for_status()
            state = response.json()
            activity = state.get("activity") or {}
            relay = (state.get("relay") or {}).get("activity") or {}
            return not (activity.get("complete") is True and activity.get("idle") is True
                        and relay.get("complete") is True and relay.get("idle") is True)
        except (httpx.HTTPError, ValueError):
            return True  # Unknown may retain briefly, never beyond the hard TTL.
    return AccountEventHubs(app.state.stream_http, app.state.live_text, app.state.limits, binding, active, maximum=maximum)
