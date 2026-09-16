import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import HTTPException

from control.concurrency import DEFAULTS
from control.event_hub import AccountEventHubs, RESYNC
from control.live_text import LiveTextCache
from control.streams import StreamRegistry


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
            self.closed = True
    def transport(request):
        stream = Stream()
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
