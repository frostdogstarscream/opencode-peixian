"""Private runtime v2 protocol. Outbound management destinations are deployment-owned."""
import asyncio
import base64
import hmac
import json
import secrets
from contextlib import suppress

import httpx
from fastapi import HTTPException, Request

from shared.orchestration_config import from_environment
from .admission import AdmissionGate, PROTOCOL
from .http_utils import fixed_base


class RuntimeManagement:
    def __init__(self, app, config, *, relay=False, transport=None):
        self.app, self.config, self.relay = app, config, relay
        self.options = from_environment()
        self.gate = AdmissionGate(config.runtime_id, config.revision, component="relay" if relay else "gateway",
                                  journal=None if relay else config.activity_root / "pending.json",
                                  observation_seconds=self.options["gate_observation_seconds"])
        self.client = httpx.AsyncClient(transport=transport, trust_env=False,
            timeout=self.options["security_request_seconds"],
            limits=httpx.Limits(max_connections=self.options["security_connections"], max_keepalive_connections=self.options["security_connections"]))
        self.native_client = httpx.AsyncClient(transport=transport, trust_env=False,
            timeout=self.options["security_request_seconds"], limits=httpx.Limits(max_connections=2, max_keepalive_connections=2))
        self.tasks = set()
        self.relay_state = None
        self.native_state = None
        self.cancel_task = None
        if not relay:
            self.gate.source("native", {}, complete=False)

    def spawn(self, work):
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self):
        self.app.state.admission = self.gate
        self.spawn(self.renew_loop())
        self.spawn(self.watchdog())
        if not self.relay:
            self.spawn(self.observe_loop())

    async def stop(self):
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await self.client.aclose()
        await self.native_client.aclose()

    async def relay_request(self, method, path, *, body=None):
        response = await self.client.request(method, fixed_base(self.config.relay_url) + path,
            headers={"X-Relay-Management-Key": self.config.relay_management_key}, json=body)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("runtime_id") != self.config.runtime_id or result.get("protocol_version") != PROTOCOL:
            raise ValueError("relay_identity_mismatch")
        return result

    async def native_request(self, method, path, *, headers=None):
        authorization = base64.b64encode(("opencode:" + self.config.opencode_password).encode()).decode()
        response = await self.native_client.request(method, self.config.opencode_url + path,
            params={"directory": "/workspace"}, headers={"Authorization": "Basic " + authorization, **(headers or {})})
        response.raise_for_status()
        return response.json() if response.content else None

    async def renew_once(self):
        nonce = secrets.token_hex(16)
        started = self.gate.clock()
        if self.relay:
            identity = {"protocol_version": PROTOCOL, "runtime_id": self.config.runtime_id, "relay_boot_id": self.gate.boot_id}
            response = await self.client.post(fixed_base(self.config.gateway_url) + "/internal/runtime/relay-permit",
                headers={"X-Relay-Management-Key": self.config.relay_management_key}, json={**identity, "nonce": nonce})
        else:
            # Discover the current relay boot before requesting a boot-bound permit.
            relay = await self.relay_request("GET", "/internal/runtime/state")
            self.relay_state = relay
            identity = {"protocol_version": PROTOCOL, "runtime_id": self.config.runtime_id,
                        "gateway_boot_id": self.gate.boot_id, "relay_boot_id": relay["boot_id"]}
            await self.gate.expire()
            recovery = {}
            epochs = ([self.gate.needs_reconcile_epoch] if self.gate.needs_reconcile else [])
            if relay.get("needs_reconcile") is True:
                epochs.append(min(self.gate.epoch, relay["needs_reconcile_epoch"]))
            if epochs:
                recovery = {"needs_reconcile": True, "needs_reconcile_epoch": min(epochs)}
            started = self.gate.clock()
            response = await self.client.post(fixed_base(self.config.control_url) + "/internal/runtime/permit",
                headers={"X-Runtime-Key": self.config.runtime_key}, json={**identity, "nonce": nonce, **recovery})
        response.raise_for_status()
        value = response.json()
        await self.gate.permit(value, started=started, nonce=nonce, identity=identity)
        if self.relay:
            self.gate.sources.pop("startup", None)

    async def renew_loop(self):
        while True:
            try:
                await self.renew_once()
            except (httpx.HTTPError, ValueError, KeyError):
                # Never extend the previous permit on a failed or malformed renewal.
                pass
            await asyncio.sleep(self.options["security_renew_seconds"])

    async def observe_once(self):
        try:
            native = await self.native_request("GET", "/internal/peixian/activity")
            if not isinstance(native, dict) or native.get("protocol_version") != PROTOCOL or native.get("complete") is not True or not isinstance(native.get("boot_id"), str):
                raise ValueError("native_activity_unavailable")
            counts = native.get("counts")
            entries = native.get("entries")
            if not isinstance(counts, dict) or any(type(v) is not int or v < 0 for v in counts.values()) or not isinstance(entries, list):
                raise ValueError("native_activity_invalid")
            self.native_state = native
            for entry in entries:
                if isinstance(entry, dict) and entry.get("state") in ("running", "finished"):
                    self.gate.finish(entry.get("id"))
            sequence = native.get('activity_sequence')
            token = (native['boot_id'], sequence) if 'idle_activity_v1' in native.get('capabilities', []) and type(sequence) is int and sequence >= 0 else None
            self.gate.source("native", counts, token=token)
        except (httpx.HTTPError, ValueError, KeyError):
            self.gate.source("native", {}, complete=False)
        try:
            relay = await self.relay_request("GET", "/internal/runtime/state")
            self.relay_state = relay
            activity = relay["activity"]
            proof = relay.get('idle_proof', {})
            token = (relay['boot_id'], proof['sequence']) if proof.get('complete') is True and type(proof.get('sequence')) is int else None
            self.gate.source("relay", activity["counts"], complete=activity.get("complete") is True, token=token)
        except (httpx.HTTPError, ValueError, KeyError):
            self.gate.source("relay", {}, complete=False)

    async def observe_loop(self):
        while True:
            await self.observe_once()
            await asyncio.sleep(0.5)

    def begin_cancel(self):
        self.gate.cancel()
        if self.cancel_task is None or self.cancel_task.done():
            self.cancel_task = self.spawn(self.cancel_native())

    async def cancel_native(self):
        if self.relay:
            return
        async def cancel():
            queue = getattr(self.app.state, "queue", None)
            if queue:
                await queue.cancel()
            sessions = set()
            if self.native_state:
                sessions.update(self.native_state.get("sessions", []))
            sessions.update(a.resource for a in self.gate.activities.values() if a.kind == "pending_start")
            # Refresh independently; cached state may predate newly admitted work.
            try:
                native = await self.native_request("GET", "/internal/peixian/activity")
                sessions.update(native.get("sessions", []))
            except (httpx.HTTPError, ValueError, AttributeError):
                self.gate.source("native", {}, complete=False)
            for sid in sessions:
                if isinstance(sid, str) and sid and all(c.isalnum() or c in "_-" for c in sid):
                    with suppress(httpx.HTTPError, ValueError):
                        await self.native_request("POST", "/session/" + sid + "/abort")
            await self.observe_once()
        try:
            await asyncio.wait_for(cancel(), self.options["cancel_observe_seconds"])
        except TimeoutError:
            self.gate.source("native", {}, complete=False)

    async def watchdog(self):
        was_authorized = False
        observed_recovery_epoch = None
        while True:
            expired = await self.gate.expire()
            authorized = self.gate.valid("egress")
            recovery_epoch = self.gate.needs_reconcile_epoch if self.gate.needs_reconcile else None
            if (expired or recovery_epoch is not None and recovery_epoch != observed_recovery_epoch
                    or not authorized and (was_authorized or self.gate.activities)):
                self.begin_cancel()
            observed_recovery_epoch = recovery_epoch
            was_authorized = authorized
            await asyncio.sleep(self.options["security_watchdog_ms"] / 1000)

    def state(self):
        snapshot = self.gate.snapshot()
        cancellation = "not_requested" if self.cancel_task is None else "requested" if not self.cancel_task.done() else "local_completed" if snapshot["activity"]["idle"] else "unconfirmed"
        return {**snapshot, **({} if self.relay else {"relay": self.relay_state}),
                "cancellation": cancellation,
                "external_outcome": "not_reversible_by_local_cancellation"}

    async def command(self, data):
        await self.gate.check_command(data)
        if data["operation_id"] in self.gate.receipts and data["gate_epoch"] != self.gate.epoch:
            # Historical replays never issue a fresh command to a restarted peer.
            return self.state()
        # Close our own entry before making a potentially failing remote request.
        if self.relay:
            await self.gate.command(data)
            return self.state()
        if data.get("action") != "open":
            await self.gate.command(data)
        if data.get("action") in ("close", "open"):
            relay = await self.relay_request("GET", "/internal/runtime/state")
            self.relay_state = await self.relay_request("POST", "/internal/runtime/gate", body={**data, "boot_id": relay["boot_id"]})
            activity = self.relay_state["activity"]
            proof = self.relay_state.get('idle_proof', {})
            token = (self.relay_state['boot_id'], proof['sequence']) if proof.get('complete') is True and type(proof.get('sequence')) is int else None
            self.gate.source("relay", activity["counts"], complete=activity.get("complete") is True, token=token)
        if data.get("action") == "open":
            await self.gate.command(data)
        return self.state()


def register_management(app, *, relay=False):
    def manager(request):
        value = getattr(app.state, "runtime_management", None)
        if value is None:
            raise HTTPException(404, "Runtime protocol is not enabled")
        key = request.headers.get("x-relay-management-key" if relay else "x-peixian-key", "")
        expected = value.config.relay_management_key if relay else value.config.token
        if not hmac.compare_digest(key, expected):
            raise HTTPException(403, "Runtime management is not authorized")
        return value

    @app.get("/internal/runtime/state")
    async def state(request: Request):
        value = manager(request)
        if not value.relay:
            await value.observe_once()
        return value.state()

    @app.post("/internal/runtime/gate")
    async def command(request: Request):
        value = manager(request)
        try:
            return await value.command(await request.json())
        except (httpx.HTTPError, ValueError, KeyError):
            raise HTTPException(503, "Runtime gate synchronization is incomplete") from None

    @app.post("/internal/runtime/cancel")
    async def cancel(request: Request):
        value = manager(request)
        data = await request.json()
        if not isinstance(data, dict) or any(data.get(k) != v for k, v in {"protocol_version": PROTOCOL, "runtime_id": value.config.runtime_id,
                "boot_id": value.gate.boot_id, "gate_epoch": value.gate.epoch, "owner": value.gate.owner}.items()) or not isinstance(data.get("operation_id"), str):
            raise HTTPException(409, "Cancellation responsibility changed")
        if value.gate.mode != "closed":
            raise HTTPException(409, "Close the runtime before cancellation")
        value.begin_cancel()
        if not relay:
            async def cancel_relay():
                try:
                    current = await value.relay_request("GET", "/internal/runtime/state")
                    value.relay_state = await value.relay_request("POST", "/internal/runtime/cancel", body={**data, "boot_id": current["boot_id"]})
                except (httpx.HTTPError, ValueError, KeyError):
                    value.gate.source("relay", {}, complete=False)
            value.spawn(cancel_relay())
        return value.state()

    if relay:
        return

    @app.post("/internal/runtime/relay-permit")
    async def relay_permit(request: Request):
        value = getattr(app.state, "runtime_management", None)
        if value is None or not hmac.compare_digest(request.headers.get("x-relay-management-key", ""), value.config.relay_management_key):
            raise HTTPException(403, "Relay permit is not authorized")
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"protocol_version", "runtime_id", "relay_boot_id", "nonce"} or data["protocol_version"] != PROTOCOL or data["runtime_id"] != value.config.runtime_id or not isinstance(data["nonce"], str):
            raise HTTPException(422, "Invalid relay permit request")
        if not value.relay_state or data["relay_boot_id"] != value.relay_state["boot_id"]:
            raise HTTPException(409, "Relay boot identity is unknown")
        recovered_authority = (not value.gate.needs_reconcile
            or value.gate.authority["gate_epoch"] > value.gate.needs_reconcile_epoch)
        return {**data, **value.gate.authority, "revision": value.config.revision, "intake": False,
                "egress": value.gate.valid("egress") and recovered_authority,
                "remaining_seconds": max(0, value.gate.deadline - value.gate.clock())}
