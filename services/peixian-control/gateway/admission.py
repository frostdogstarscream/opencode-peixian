"""Per-process runtime admission and expiring authority. No business payloads live here."""
import asyncio
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

PROTOCOL = 2
PERMIT_TTL = 4.0
RENEW_SECONDS = 1.0
WATCHDOG_SECONDS = 0.1
MANAGEMENT_TIMEOUT = 1.0
CANCEL_SECONDS = 10.0


@dataclass
class Activity:
    kind: str
    task: object = None
    resource: str = ""
    unknown: bool = False


class AdmissionGate:
    def __init__(self, runtime_id, revision, *, clock=time.monotonic, component="gateway", journal=None, observation_seconds=3):
        self.runtime_id, self.revision, self.component = runtime_id, revision, component
        self.clock = clock
        self.boot_id = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self.epoch = 0
        self.state_version = 0
        self.authorization_version = 0
        self.authority = {"gate_epoch": 0, "state_version": 0, "authorization_version": 0, "owner": ""}
        self.owner = ""
        self.mode = "closed"
        self.needs_reconcile = False
        self.needs_reconcile_epoch = 0
        self.deadline = 0.0
        self.scopes = {"intake": False, "egress": False}
        self.activities = {}
        self.receipts = {}
        self.sources = {}
        self.activity_sequence = 0
        self.activity_at = self.clock()
        self.observation_seconds = observation_seconds
        self.journal = Path(journal) if journal else None
        if self.journal and self.journal.exists():
            try:
                for identity, resource in json.loads(self.journal.read_text()).items():
                    if not isinstance(identity, str) or not isinstance(resource, str):
                        raise ValueError()
                    self.activities[identity] = Activity("pending_start", resource=resource, unknown=True)
            except (OSError, ValueError, AttributeError):
                self.source("journal", {}, complete=False)

    def save_pending(self):
        if self.journal:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            stage = self.journal.with_suffix(".tmp")
            stage.write_text(json.dumps({key: value.resource for key, value in self.activities.items() if value.kind == "pending_start"}), encoding="utf-8")
            stage.replace(self.journal)

    def valid(self, scope):
        return self.clock() < self.deadline and self.scopes.get(scope) is True

    def require_egress(self):
        if self.mode != "open" or not self.valid("egress"):
            raise HTTPException(409, "Runtime egress is closed")

    def latch_expired(self):
        # Called inside the admission lock. An expired open lifecycle cannot be
        # revived by a later renewal, even if the watchdog has not run yet.
        if self.mode == "open" and self.scopes["egress"] and self.deadline > 0 and self.clock() >= self.deadline:
            self.mode = "closed"
            self.needs_reconcile = True
            self.needs_reconcile_epoch = self.epoch
            return True
        return False

    async def expire(self):
        async with self.lock:
            return self.latch_expired()

    async def permit(self, value, *, started, nonce, identity):
        async with self.lock:
            self.latch_expired()
            if not isinstance(value, dict) or type(value.get("protocol_version")) is not int or any(value.get(k) != v for k, v in identity.items()) or value.get("nonce") != nonce:
                raise ValueError("permit_identity_mismatch")
            ttl = value.get("ttl_seconds", value.get("remaining_seconds"))
            if type(ttl) not in (int, float) or not 0 <= ttl <= PERMIT_TTL:
                raise ValueError("invalid_permit_lifetime")
            if any(type(value.get(key)) is not int or value[key] < 0 for key in ("gate_epoch", "state_version", "authorization_version")):
                raise ValueError("invalid_permit_version")
            if (value["gate_epoch"] < max(self.epoch, self.authority["gate_epoch"])
                    or value["state_version"] < self.authority["state_version"]
                    or value["authorization_version"] < self.authorization_version):
                raise ValueError("stale_permit")
            if any(type(value.get(key)) is not bool for key in ("intake", "egress")):
                raise ValueError("invalid_permit_scope")
            if not isinstance(value.get("owner"), str) or value.get("revision") != self.revision:
                raise ValueError("permit_revision_mismatch")
            self.authorization_version = value["authorization_version"]
            self.authority = {key: value[key] for key in ("gate_epoch", "state_version", "authorization_version", "owner")}
            self.deadline = started + ttl
            self.scopes = {key: value[key] for key in ("intake", "egress")}
            # A renewal grants authority, never changes the lifecycle gate or its owner.
            return self.clock() < self.deadline

    def validate_command(self, data):
        fields = {"protocol_version", "runtime_id", "boot_id", "gate_epoch", "state_version", "owner", "operation_id", "action", "reason", "revision"}
        if not isinstance(data, dict) or set(data) != fields:
            raise HTTPException(422, "Invalid runtime command")
        if type(data["protocol_version"]) is not int or type(data["revision"]) is not int or data["protocol_version"] != PROTOCOL or data["runtime_id"] != self.runtime_id or data["boot_id"] != self.boot_id or data["revision"] != self.revision:
            raise HTTPException(409, "Runtime identity changed")
        if any(type(data[k]) is not int or data[k] < 0 for k in ("gate_epoch", "state_version")) or any(not isinstance(data[k], str) or not data[k] or len(data[k]) > 200 for k in ("owner", "operation_id", "reason")):
            raise HTTPException(422, "Invalid runtime command")
        if data["action"] not in ("open", "drain", "close"):
            raise HTTPException(422, "Invalid gate action")
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def check_command(self, data):
        signature = self.validate_command(data)
        async with self.lock:
            self.latch_expired()
            receipt = self.receipts.get(data["operation_id"])
            if receipt and receipt[0] == signature:
                return
            if receipt or data["gate_epoch"] <= self.epoch or data["state_version"] < self.state_version:
                raise HTTPException(409, "Gate responsibility changed")
            if data["action"] == "open" and (not self.valid("egress" if self.component == "relay" else "intake") or self.authority["gate_epoch"] < data["gate_epoch"] or self.authority["owner"] != data["owner"]):
                raise HTTPException(409, "Runtime permit is unavailable")

    async def command(self, data):
        signature = self.validate_command(data)
        async with self.lock:
            self.latch_expired()
            receipt = self.receipts.get(data["operation_id"])
            if receipt:
                if receipt[0] != signature:
                    raise HTTPException(409, "Operation conflicts with recorded command")
                return dict(receipt[1])
            if data["gate_epoch"] <= self.epoch or data["state_version"] < self.state_version:
                raise HTTPException(409, "Gate responsibility changed")
            if data["action"] == "open" and (not self.valid("egress" if self.component == "relay" else "intake") or self.authority["gate_epoch"] < data["gate_epoch"] or self.authority["owner"] != data["owner"]):
                raise HTTPException(409, "Runtime permit is unavailable")
            self.epoch, self.state_version, self.owner = data["gate_epoch"], data["state_version"], data["owner"]
            self.mode = {"open": "open", "drain": "draining", "close": "closed"}[data["action"]]
            if data["action"] == "open":
                self.needs_reconcile = False
                self.needs_reconcile_epoch = 0
            result = {"receipt_status": "recorded", "boot_id": self.boot_id, "gate_epoch": self.epoch, "gate": self.mode, "operation_id": data["operation_id"]}
            self.receipts[data["operation_id"]] = (signature, result)
            if len(self.receipts) > 2048:
                self.receipts.pop(next(iter(self.receipts)))
            return dict(result)

    async def admit(self, kind, *, continuation=False, resource="", task=None):
        async with self.lock:
            self.latch_expired()
            scope = "egress" if self.component == "relay" else "intake"
            allowed = self.mode == "open" or (continuation and self.mode == "draining")
            # Ordinary draining can continue existing native work with egress authority.
            authorized = self.valid("egress") if continuation else self.valid(scope)
            if not continuation and self.component == "gateway":
                authorized = authorized and self.authority["gate_epoch"] == self.epoch and self.authority["owner"] == self.owner
            if not allowed or not authorized:
                raise HTTPException(409, "Runtime admission is closed")
            return self.register(kind, resource=resource, task=task or asyncio.current_task())

    def register(self, kind, *, resource="", task=None, identity=None):
        identity = identity or uuid.uuid4().hex
        self.activities[identity] = Activity(kind, task, resource)
        if not kind.startswith("passive_"):
            self.touch()
        if kind == "pending_start":
            self.save_pending()
        return identity

    def finish(self, identity):
        previous = self.activities.pop(identity, None)
        if previous and not previous.kind.startswith("passive_"):
            self.touch()
        if previous and previous.kind == "pending_start":
            self.save_pending()

    def unknown(self, identity):
        if identity in self.activities:
            self.activities[identity].unknown = True
            self.activities[identity].task = None

    def touch(self):
        self.activity_sequence += 1
        self.activity_at = self.clock()

    def source(self, name, counts, *, complete=True, token=None):
        previous = self.sources.get(name)
        if (not complete or not previous or not previous['complete']
                or self.clock() - previous['at'] > self.observation_seconds
                or previous.get('token') != token or previous['counts'] != counts):
            self.touch()
        self.sources[name] = {"counts": counts, "complete": complete, "at": self.clock(), "token": token}

    def snapshot(self):
        counts = Counter(item.kind for item in self.activities.values() if not item.kind.startswith("passive_"))
        unknown = any(item.unknown for item in self.activities.values())
        for source in self.sources.values():
            unknown |= not source["complete"] or self.clock() - source["at"] > self.observation_seconds
            counts.update(source["counts"])
        total = sum(counts.values())
        idle_complete = not unknown and all(s.get('token') is not None for s in self.sources.values())
        if self.clock() < self.activity_at:
            self.touch()
            idle_complete = False
        return {"protocol_version": PROTOCOL, "runtime_id": self.runtime_id, "boot_id": self.boot_id,
                "capabilities": ["idle_activity_v1"],
                "idle_proof": {"complete": idle_complete, "sequence": self.activity_sequence,
                               "idle_seconds": max(0, self.clock() - self.activity_at) if idle_complete and total == 0 else 0},
                "gate_epoch": self.epoch, "state_version": self.state_version, "owner": self.owner,
                "gate": self.mode, "permit_valid": self.valid("intake") or self.valid("egress"),
                "permit_scopes": {key: self.valid(key) for key in ("intake", "egress")},
                "revision": self.revision, "authorization_version": self.authorization_version,
                "needs_reconcile": self.needs_reconcile, "needs_reconcile_epoch": self.needs_reconcile_epoch,
                "activity": {"complete": not unknown, "unknown": unknown, "counts": dict(counts), "total": total, "idle": not unknown and total == 0}}

    def cancel(self):
        current = asyncio.current_task()
        tasks = {item.task for item in self.activities.values() if item.task is not None and item.task is not current and not item.task.done() and not item.task.cancelling()}
        for task in tasks:
            task.cancel()
        return len(tasks)


class ActivityMiddleware:
    """Own reservations over the complete ASGI response, including before streaming starts."""
    def __init__(self, app, owner, *, relay=False):
        self.app, self.owner, self.relay = app, owner, relay

    async def __call__(self, scope, receive, send):
        gate = getattr(self.owner.state, "admission", None)
        if scope["type"] != "http" or gate is None:
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        if path.startswith("/internal/runtime/") or path in ("/health", "/global/health", "/skill", "/internal/facts/status"):
            return await self.app(scope, receive, send)
        if path == "/internal/facts/execute" and not self.relay:
            try:
                gate.require_egress()
                identity = gate.register("facts", task=asyncio.current_task())
            except HTTPException as error:
                from starlette.responses import JSONResponse
                return await JSONResponse({"detail": error.detail}, error.status_code)(scope, receive, send)
            try:
                return await self.app(scope, receive, send)
            finally:
                gate.finish(identity)
        continuation = path.endswith(("/abort", "/reply", "/reject"))
        kind = "relay_http" if self.relay else "receiving"
        if not self.relay:
            if method == "POST" and path == "/files":
                kind = "upload"
            elif path.endswith("/download"):
                kind = "download"
            elif path.startswith("/plugins/") and path.endswith("/test"):
                kind = "plugin_test"
            elif method == "GET":
                # Track cancellation ownership without making observers prevent a drain.
                if not gate.valid("egress") or gate.mode == "closed":
                    from starlette.responses import JSONResponse
                    return await JSONResponse({"detail": "Runtime admission is closed"}, 409)(scope, receive, send)
                identity = gate.register("passive_read", task=asyncio.current_task())
                try:
                    return await self.app(scope, receive, send)
                finally:
                    gate.finish(identity)
        try:
            identity = await gate.admit(kind, continuation=continuation)
        except HTTPException as error:
            from starlette.responses import JSONResponse
            return await JSONResponse({"detail": error.detail}, error.status_code)(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            gate.finish(identity)
