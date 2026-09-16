import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest

from gateway.app import create_app
from gateway.model_relay import Model, create_app as create_relay
from gateway.settings import Settings, RelaySettings
from test_admission import command


class Bytes(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value

    async def __aiter__(self):
        yield self.value


@asynccontextmanager
async def cluster(tmp_path, store=None):
    runtime_id, uid = "runtime", "synthetic"
    private = {"gateway_key": "gateway-secret", "runtime_key": "runtime-secret", "relay_management_key": "relay-secret"}
    if store:
        user, _ = store.create_user("synthetic-r2", "synthetic-password-for-tests-123")
        uid = user["id"]
        runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
        runtime_id, private = runtime["id"], store.decrypt(runtime["spec"])
    for folder in ("workspace", "files", "managed"):
        (tmp_path / folder).mkdir()
    (tmp_path / "managed" / "revision.json").write_text(json.dumps({"uid": uid, "runtime_id": runtime_id, "revision": 1}))
    config = Settings(tmp_path / "workspace", tmp_path / "files", tmp_path / "managed", private["gateway_key"], "agent-secret",
                      require_linux=False, runtime_protocol=True, runtime_id=runtime_id, runtime_key=private["runtime_key"],
                      relay_management_key=private["relay_management_key"], relay_url="http://relay", opencode_url="http://agent", control_url="http://control")
    relay_config = RelaySettings(runtime_id, 1, private["relay_management_key"], gateway_url="http://gateway")
    policy = {"epoch": 1, "allow": True, "control_available": True, "relay_available": True, "entries": [], "native_available": True, "hide_entries": False}
    apps = {}
    policy["uid"] = uid

    async def dispatch(request):
        if request.url.host == "control":
            if not policy["control_available"]:
                raise httpx.ConnectError("synthetic control unavailable")
            assert request.headers["x-runtime-key"] == config.runtime_key
            payload = json.loads(request.content)
            assert payload["protocol_version"] == 2
            if store:
                from control.runtime_security import permit
                from shared.orchestration_config import from_environment
                return httpx.Response(200, json=permit(store, payload, config.runtime_key, from_environment()))
            return httpx.Response(200, json={**payload, "gate_epoch": policy["epoch"], "state_version": policy["epoch"],
                "authorization_version": policy["epoch"], "owner": "job:synthetic:1", "revision": 1,
                "ttl_seconds": 4, "intake": policy["allow"], "egress": policy["allow"]})
        if request.url.host == "agent":
            if not policy["native_available"]:
                return httpx.Response(503)
            if request.url.path == "/internal/peixian/activity":
                entries = [] if policy["hide_entries"] else policy["entries"]
                running = [entry for entry in entries if entry["state"] == "running"]
                return httpx.Response(200, json={"protocol_version": 2, "boot_id": "native-boot", "complete": True,
                    "counts": {"native_running": len(running)}, "sessions": [entry["session_id"] for entry in running], "entries": entries})
            if request.url.path.endswith("/prompt_async"):
                policy["entries"].append({"id": request.headers["x-peixian-activity-id"], "session_id": "synthetic", "state": "running"})
                return httpx.Response(204, stream=Bytes(b""))
            if request.url.path.endswith("/abort"):
                for entry in policy["entries"]:
                    entry["state"] = "finished"
                return httpx.Response(200, stream=Bytes(b"true"), headers={"content-type": "application/json"})
            return httpx.Response(200, stream=Bytes(b'{"ok":true}'), headers={"content-type": "application/json"})
        if request.url.host == "relay" and not policy["relay_available"]:
            raise httpx.ConnectError("synthetic relay unavailable")
        if request.url.host == "upstream":
            return httpx.Response(200, stream=policy["upstream_stream"], headers={"content-type": "text/event-stream"})
        target = "gateway" if request.url.host.startswith("px-") else request.url.host
        return await httpx.ASGITransport(app=apps[target]).handle_async_request(request)

    transport = httpx.MockTransport(dispatch)
    gateway = create_app(config, transport=transport, management_transport=transport)
    model = Model("synthetic", "synthetic", "http://upstream/v1", "", uid)
    relay = create_relay(models={model.id: model}, connections={}, runtime_settings=relay_config, management_transport=transport, transport=transport)
    apps.update(gateway=gateway, relay=relay)
    policy["transport"] = transport
    policy["relay_app"] = relay
    async with relay.router.lifespan_context(relay), gateway.router.lifespan_context(gateway):
        gm, rm = gateway.state.runtime_management, relay.state.runtime_management
        try:
            await gm.renew_once()
        except ValueError:
            if not store:
                raise
        await rm.renew_once()
        await gm.observe_once()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://gateway", headers={"X-Peixian-Key": config.token}) as client:
            yield gm, rm, client, policy


def test_closed_boot_requires_explicit_open_and_double_close_confirmation(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            assert gm.state()["gate"] == rm.state()["gate"] == "closed"
            assert (await client.post("/files/abc/parse")).status_code == 409
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/global/health")).status_code == 200
            opened = await client.post("/internal/runtime/gate", json=command(gm.gate, 1))
            assert opened.status_code == 200, opened.text
            assert gm.state()["gate"] == rm.state()["gate"] == "open"
            result = await client.post("/internal/runtime/gate", json=command(gm.gate, 2, "drain"))
            assert result.status_code == 200
            assert gm.state()["gate"] == "draining" and rm.state()["gate"] == "open"
            result = await client.post("/internal/runtime/gate", json=command(gm.gate, 3, "close"))
            assert result.status_code == 200
            assert result.json()["gate"] == result.json()["relay"]["gate"] == "closed"
    asyncio.run(scenario())


def test_pending_start_survives_204_until_native_correlated_snapshot(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            await gm.command(command(gm.gate, 1))
            policy["hide_entries"] = True
            sent = await client.post("/session/synthetic/prompt_async", json={"parts": []})
            assert sent.status_code == 204
            assert gm.state()["activity"]["counts"]["pending_start"] == 1
            policy["hide_entries"] = False
            await gm.observe_once()
            assert gm.state()["activity"]["counts"]["native_running"] == 1
            assert "pending_start" not in gm.state()["activity"]["counts"]
            policy["native_available"] = False
            await gm.observe_once()
            assert gm.state()["activity"]["unknown"]
            policy["native_available"] = True
            policy["entries"][0]["state"] = "finished"
            await gm.observe_once()
            assert gm.state()["activity"]["idle"]
    asyncio.run(scenario())


def test_relay_failure_keeps_gateway_closed_and_unknown(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            await gm.command(command(gm.gate, 1))
            policy["relay_available"] = False
            response = await client.post("/internal/runtime/gate", json=command(gm.gate, 2, "close"))
            assert response.status_code == 503
            assert gm.gate.mode == "closed"
            await gm.observe_once()
            assert gm.state()["activity"]["unknown"]
    asyncio.run(scenario())


def test_old_gateway_boot_command_cannot_change_relay(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            response = await client.post("/internal/runtime/gate", json=command(gm.gate, 1, boot_id="old-boot"))
            assert response.status_code == 409
            assert rm.gate.mode == "closed" and rm.gate.epoch == 0
    asyncio.run(scenario())


def test_drain_keeps_history_and_confirmations_but_blocks_new_work(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            await gm.command(command(gm.gate, 1))
            await gm.command(command(gm.gate, 2, "drain"))
            assert (await client.get("/session/synthetic/message")).status_code == 200
            assert (await client.post("/session/synthetic/abort")).status_code == 200
            assert (await client.post("/question/synthetic/reply", json={"answers": []})).status_code == 200
            assert (await client.post("/session/synthetic/prompt_async", json={"parts": []})).status_code == 409
            assert (await client.post("/files/synthetic/parse")).status_code == 409
            await gm.command(command(gm.gate, 3, "close"))
            assert (await client.get("/session/synthetic/message")).status_code == 409
            assert (await client.post("/session/synthetic/abort")).status_code == 409
    asyncio.run(scenario())


def test_management_credentials_cannot_be_substituted_with_agent_or_other_component_keys(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            assert (await client.get("/internal/runtime/state", headers={"X-Peixian-Key": "agent-secret"})).status_code == 401
            response = await client.post("/internal/runtime/relay-permit", json={"protocol_version": 2,
                "runtime_id": "runtime", "relay_boot_id": rm.gate.boot_id, "nonce": "synthetic"})
            assert response.status_code == 401
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=policy["relay_app"]), base_url="http://relay") as relay:
                assert (await relay.get("/internal/runtime/state", headers={"X-Peixian-Key": "gateway-secret"})).status_code == 403
                assert (await relay.post("/internal/runtime/gate", json=command(rm.gate, 1))).status_code == 403
    asyncio.run(scenario())


def test_relay_permit_does_not_receive_a_fresh_full_lifetime(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            gm.gate.clock = lambda: 100
            gm.gate.deadline = 101
            response = await client.post("/internal/runtime/relay-permit", json={"protocol_version": 2,
                "runtime_id": "runtime", "relay_boot_id": rm.gate.boot_id, "nonce": "relay-nonce"},
                headers={"X-Relay-Management-Key": "relay-secret"})
            assert response.status_code == 200
            assert response.json()["remaining_seconds"] == 1
            gm.gate.deadline = 99
            response = await client.post("/internal/runtime/relay-permit", json={"protocol_version": 2,
                "runtime_id": "runtime", "relay_boot_id": rm.gate.boot_id, "nonce": "relay-nonce"},
                headers={"X-Relay-Management-Key": "relay-secret"})
            assert response.json()["remaining_seconds"] == 0
            assert response.json()["egress"] is False
    asyncio.run(scenario())


def test_security_close_starts_native_cancellation_without_a_worker(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            await gm.command(command(gm.gate, 1))
            await client.post("/session/synthetic/prompt_async", json={"parts": []})
            await gm.observe_once()
            closed = command(gm.gate, 2, "close")
            assert (await client.post("/internal/runtime/gate", json=closed)).status_code == 200
            response = await client.post("/internal/runtime/cancel", json={**closed, "operation_id": "cancel-2"})
            assert response.status_code == 200
            await gm.cancel_task
            assert policy["entries"][0]["state"] == "finished"
            assert gm.state()["external_outcome"] == "not_reversible_by_local_cancellation"
    asyncio.run(scenario())


class SlowStream(httpx.AsyncByteStream):
    def __init__(self):
        self.entered, self.release, self.closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def __aiter__(self):
        self.entered.set()
        await self.release.wait()
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed.set()


def test_normal_drain_keeps_an_admitted_relay_stream_until_it_finishes(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            await gm.command(command(gm.gate, 1))
            stream = policy["upstream_stream"] = SlowStream()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=policy["relay_app"]), base_url="http://relay") as relay:
                task = asyncio.create_task(relay.post("/v1/chat/completions", json={"model": "synthetic", "stream": True}))
                await asyncio.wait_for(stream.entered.wait(), 1)
                await gm.command(command(gm.gate, 2, "drain"))
                policy["epoch"] = 2
                await gm.renew_once()
                await rm.renew_once()
                await gm.observe_once()
                assert gm.state()["activity"]["counts"]["relay_http"] == 1
                assert rm.gate.mode == "open" and not task.done() and not stream.closed.is_set()
                stream.release.set()
                assert (await task).status_code == 200
                await gm.observe_once()
                assert gm.state()["activity"]["idle"]
    asyncio.run(scenario())


def test_expired_authority_cancels_relay_http_without_control_or_worker(tmp_path):
    async def scenario():
        async with cluster(tmp_path) as (gm, rm, client, policy):
            await gm.command(command(gm.gate, 1))
            stream = policy["upstream_stream"] = SlowStream()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=policy["relay_app"]), base_url="http://relay") as relay:
                task = asyncio.create_task(relay.post("/v1/chat/completions", json={"model": "synthetic", "stream": True}))
                await asyncio.wait_for(stream.entered.wait(), 1)
                policy["control_available"] = False
                gm.gate.clock = rm.gate.clock = lambda: max(gm.gate.deadline, rm.gate.deadline) + 1
                await asyncio.wait_for(stream.closed.wait(), 1)
                await asyncio.gather(task, return_exceptions=True)
                assert rm.gate.snapshot()["activity"]["idle"]
                assert (await relay.post("/v1/chat/completions", json={"model": "synthetic"})).status_code == 409
    asyncio.run(scenario())
