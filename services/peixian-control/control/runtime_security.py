"""Account-scoped safety intent and expiring permits, independent of host jobs."""
import asyncio
from contextlib import suppress
import hmac
import json
import re
import time

import httpx
from fastapi import Depends, HTTPException, Request

from .concurrency import blocking_endpoint
from .store import ident, now
from shared.orchestration_config import from_environment


IDENTITY = re.compile(r"^[A-Za-z0-9_:.-]{1,160}$")


def block_runtime(store, db, uid, *, reason="authorization_revoked"):
    if reason not in ("authorization_revoked", "account_disabled", "connection_restricted", "plugin_disabled", "model_disabled"):
        raise ValueError("invalid_security_reason")
    row = db.execute("SELECT id FROM runtimes WHERE uid=?", (uid,)).fetchone()
    if not row:
        return
    db.execute("UPDATE runtimes SET security_blocked=1,security_intent_id=?,authorization_version=authorization_version+1,"
               "gate_epoch=gate_epoch+1,state_version=state_version+1,gate_policy='closed',stop_reason=?,"
               "cancel_requested_at=?,security_confirmed_at=NULL,cancellation_confirmed=0,updated=? WHERE uid=?",
               (ident(), reason, now(), now(), uid))
    db.execute("UPDATE jobs SET cancel_requested=1 WHERE uid=? AND status='running'", (uid,))


def owner(db, runtime):
    if runtime["security_blocked"]:
        return "security:" + (runtime["security_intent_id"] or runtime["id"])
    if runtime["stop_reason"] == "operator_cancel" and runtime["drain_intent_id"]:
        return "drain:" + runtime["drain_intent_id"]
    if runtime["drain_job_id"]:
        job = db.execute("SELECT attempts FROM jobs WHERE id=? AND uid=?", (runtime["drain_job_id"], runtime["uid"])).fetchone()
        if job:
            return f"job:{runtime['drain_job_id']}:{job['attempts']}"
    return "runtime:" + runtime["id"]


def permit(store, data, credential, config):
    fields = {"protocol_version", "runtime_id", "gateway_boot_id", "relay_boot_id", "nonce"}
    optional = {"needs_reconcile", "needs_reconcile_epoch"}
    if (not isinstance(data, dict) or not fields <= set(data) or set(data) - fields - optional or data["protocol_version"] != 2
            or any(not isinstance(data[k], str) or not IDENTITY.fullmatch(data[k])
                   for k in fields - {"protocol_version"})):
        raise HTTPException(422, "运行环境协议不匹配")
    needs = data.get("needs_reconcile", False)
    if type(needs) is not bool or (needs and (type(data.get("needs_reconcile_epoch")) is not int or data["needs_reconcile_epoch"] < 0)):
        raise HTTPException(422, "运行环境观测不完整")
    with store.tx() as db:
        row = db.execute("SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.id=?", (data["runtime_id"],)).fetchone()
        if not row or not isinstance(credential, str) or not hmac.compare_digest(
                credential, store.decrypt(row["spec"]).get("runtime_key", "")) or len(credential) < 32:
            raise HTTPException(403, "运行环境身份无效")
        gateway_changed = row["gateway_boot_id"] != data["gateway_boot_id"]
        relay_changed = row["relay_boot_id"] != data["relay_boot_id"]
        lost_permit = (needs and row["gate_policy"] == "open" and row["status"] == "ready"
                       and not row["recovery_required"] and data["needs_reconcile_epoch"] == row["gate_epoch"])
        if gateway_changed or relay_changed or lost_permit:
            unexpected = row["status"] == "ready" and bool(row["gateway_boot_id"] or row["relay_boot_id"])
            db.execute("UPDATE runtimes SET gateway_boot_id=?,relay_boot_id=?,gate_epoch=gate_epoch+1,"
                       "state_version=state_version+1,gate_policy='closed',recovery_required=MAX(recovery_required,?),updated=? WHERE uid=?",
                       (data["gateway_boot_id"], data["relay_boot_id"], int(unexpected or lost_permit), now(), row["uid"]))
            row = db.execute("SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=?", (row["uid"],)).fetchone()
        mode = store.maintenance_status(db)["maintenance_mode"]
        permitted = bool(row["active"] and not row["security_blocked"] and not row["recovery_required"])
        intake = permitted and mode == "normal" and row["status"] == "ready" and row["gate_policy"] in ("open", "reopen_check", "open_pending")
        # Draining keeps egress for existing generation/confirmation only. The
        # local intake gate still rejects a new generation or plugin test.
        egress = permitted and mode in ("normal", "frozen") and row["status"] in ("ready", "draining") and row["gate_policy"] != "closed_all"
        return {**data, "gate_epoch": row["gate_epoch"], "state_version": row["state_version"],
                "authorization_version": row["authorization_version"], "owner": owner(db, row),
                "intake": bool(intake), "egress": bool(egress), "revision": row["revision"],
                "ttl_seconds": config["security_permit_ttl_seconds"]}


def control_started(store):
    """A real Control restart requires fresh verification before intake reopens.

    Preserve unfinished worker attempts: their own leases and frozen snapshots
    govern recovery. This only marks previously usable runtimes for reconciliation.
    """
    with store.tx() as db:
        db.execute("UPDATE runtimes SET recovery_required=1,gate_policy='closed',gate_epoch=gate_epoch+1,"
                   "state_version=state_version+1,updated=? WHERE reserved=1 AND status='ready' AND security_blocked=0", (now(),))


def register_runtime_security(app):
    @app.post("/internal/runtime/permit", include_in_schema=False)
    @blocking_endpoint(app, json_body=True)
    def runtime_permit(request: Request):
        return permit(app.state.store, request.state.json_body, request.headers.get("x-runtime-key", ""), app.state.orchestration_settings)


class SafetyCoordinator:
    """Bounded safety I/O, never queued behind a Docker invocation."""
    def __init__(self, app):
        self.app = app
        self.config = app.state.orchestration_settings
        self.http = httpx.AsyncClient(trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(self.config["security_request_seconds"]),
            limits=httpx.Limits(max_connections=self.config["security_connections"], max_keepalive_connections=self.config["security_connections"]))
        self.slots = asyncio.Semaphore(self.config["security_connections"])
        self.inflight = {}
        self.closing = False
        self.task = None
        self.failures = 0

    def candidates(self):
        return self.app.state.store.rows(
            "SELECT uid FROM runtimes WHERE reserved=1 AND ((security_blocked=1 AND cancellation_confirmed=0) "
            "OR gate_policy IN ('reopen_check','open_pending','cancel_pending')) ORDER BY updated,uid LIMIT 64")

    def command(self, uid):
        store = self.app.state.store
        with store.tx() as db:
            row = db.execute("SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=?", (uid,)).fetchone()
            if not row or not row["reserved"] or not row["gateway_boot_id"]:
                return None
            cancelling = row["security_blocked"] or row["gate_policy"] == "cancel_pending"
            if cancelling:
                action = "close"
            else:
                mode = store.maintenance_status(db)["maintenance_mode"]
                if row["status"] != "ready" or row["recovery_required"] or not row["active"] or mode != "normal":
                    return None
                if row["gate_policy"] == "reopen_check":
                    db.execute("UPDATE runtimes SET gate_policy='open_pending',gate_epoch=gate_epoch+1,state_version=state_version+1 WHERE uid=?", (uid,))
                    row = db.execute("SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=?", (uid,)).fetchone()
                if row["gate_policy"] != "open_pending":
                    return None
                action = "open"
            operation = f"gate-{row['id']}-{row['gate_epoch']}-{action}"
            return {"uid": uid, "epoch": row["gate_epoch"], "state_version": row["state_version"],
                "security": bool(row["security_blocked"]), "cancelling": bool(cancelling), "since": row["cancel_requested_at"],
                "url": f"http://px-{row['id']}-gateway:8080", "key": store.decrypt(row["spec"])["gateway_key"],
                "body": {"protocol_version": 2, "runtime_id": row["id"], "boot_id": row["gateway_boot_id"],
                    "gate_epoch": row["gate_epoch"], "state_version": row["state_version"], "owner": owner(db, row),
                    "operation_id": operation, "action": action, "reason": "security" if row["security_blocked"] else "operator_cancel" if cancelling else "verified_release",
                    "revision": row["revision"]}}

    def record(self, command, state, cancellation=None):
        store = self.app.state.store
        with store.tx() as db:
            row = db.execute("SELECT * FROM runtimes WHERE uid=? AND gate_epoch=? AND state_version=?",
                             (command["uid"], command["epoch"], command["state_version"])).fetchone()
            if not row or not isinstance(state, dict):
                return
            relay = state.get("relay") or {}
            current_owner = owner(db, row)
            for component, boot in ((state, row["gateway_boot_id"]), (relay, row["relay_boot_id"])):
                if (component.get("protocol_version") != 2 or component.get("runtime_id") != row["id"]
                        or component.get("boot_id") != boot or component.get("gate_epoch") != row["gate_epoch"]
                        or component.get("state_version") != row["state_version"]
                        or component.get("revision") != row["revision"] or component.get("owner") != current_owner):
                    return
            if not command["cancelling"]:
                if (state.get("gate") == relay.get("gate") == "open"
                        and state.get("permit_scopes", {}).get("intake") is True
                        and relay.get("permit_scopes", {}).get("egress") is True
                        and state.get("authorization_version") == relay.get("authorization_version") == row["authorization_version"]
                        and row["gate_policy"] == "open_pending" and not row["security_blocked"]):
                    db.execute("UPDATE runtimes SET gate_policy='open',updated=? WHERE uid=?", (now(), command["uid"]))
                return
            if state.get("gate") != "closed" or relay.get("gate") != "closed":
                return
            activity = state.get("activity") or {}
            relay_activity = relay.get("activity") or {}
            confirmed = (activity.get("complete") is True and activity.get("idle") is True
                         and relay_activity.get("complete") is True and relay_activity.get("idle") is True)
            db.execute("UPDATE runtimes SET security_confirmed_at=COALESCE(security_confirmed_at,?),"
                       "cancellation_confirmed=? WHERE uid=?", (now(), int(confirmed), command["uid"]))
            if confirmed and not command["security"]:
                db.execute("UPDATE runtimes SET gate_policy='closed' WHERE uid=? AND gate_policy='cancel_pending'", (command["uid"],))
            if command["security"] and not confirmed and command["since"] and now() - command["since"] >= self.config["cancel_observe_seconds"]:
                if not db.execute("SELECT 1 FROM jobs WHERE uid=? AND action='pause' AND status IN ('queued','running')", (command["uid"],)).fetchone():
                    store.queue_in_transaction(db, command["uid"], "pause", reason="security", bump_desired=False)

    def fallback(self, command):
        if not command["security"] or not command["since"] or now() - command["since"] < self.config["cancel_observe_seconds"]:
            return
        store = self.app.state.store
        with store.tx() as db:
            row = db.execute("SELECT * FROM runtimes WHERE uid=?", (command["uid"],)).fetchone()
            if row and row["security_blocked"] and row["reserved"] and not db.execute(
                    "SELECT 1 FROM jobs WHERE uid=? AND action='pause' AND status IN ('queued','running')", (command["uid"],)).fetchone():
                store.queue_in_transaction(db, command["uid"], "pause", reason="security", bump_desired=False)

    async def sync(self, uid):
        async with self.slots:
            command = await self.app.state.db_work.run(self.command, uid)
            if command is None:
                return
            headers = {"X-Peixian-Key": command["key"]}
            try:
                response = await self.http.post(command["url"] + "/internal/runtime/gate", headers=headers, json=command["body"])
                response.raise_for_status()
                if command["cancelling"]:
                    cancel = {k: v for k, v in command["body"].items() if k not in ("action", "reason", "revision", "state_version")}
                    cancel["operation_id"] += "-cancel"
                    await self.http.post(command["url"] + "/internal/runtime/cancel", headers=headers, json=cancel)
                response = await self.http.get(command["url"] + "/internal/runtime/state", headers=headers)
                response.raise_for_status()
                await self.app.state.db_work.run(self.record, command, response.json())
            except (httpx.HTTPError, ValueError, HTTPException):
                self.failures += 1
                # No URLs, credentials or upstream response bodies in diagnostics.
                await self.app.state.db_work.run(self.fallback, command)

    async def run(self):
        while not self.closing:
            try:
                users = await self.app.state.db_work.run(self.candidates)
                for row in users:
                    uid = row["uid"]
                    if uid not in self.inflight and len(self.inflight) < self.config["security_connections"]:
                        task = asyncio.create_task(self.sync(uid))
                        self.inflight[uid] = task
                        task.add_done_callback(lambda finished, account=uid: self.finished(account, finished))
            except (HTTPException, RuntimeError):
                self.failures += 1
            await asyncio.sleep(0.25)

    def finished(self, uid, task):
        self.inflight.pop(uid, None)
        if not task.cancelled() and task.exception() is not None:
            self.failures += 1

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def close(self):
        self.closing = True
        tasks = [*self.inflight.values(), *([self.task] if self.task else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.http.aclose()
