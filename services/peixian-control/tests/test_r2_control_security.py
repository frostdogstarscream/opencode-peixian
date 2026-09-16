import json

import pytest
from fastapi import HTTPException

from control.runtime_security import block_runtime, permit
from control.store import now
from shared.orchestration_config import DEFAULTS
from test_control import context, create_user, login_user, P, PASSWORD


def test_missing_idempotency_key_is_rejected_before_creation(context):
    store, app, client = context
    response = client.post(P + "/admin/users", headers={"Idempotency-Key": ""},
                           json={"username": "missing-key", "password": PASSWORD})
    assert response.status_code == 422
    assert store.one("SELECT 1 FROM users WHERE username='missing-key'") is None


def test_account_creation_receipt_replays_once_and_is_encrypted(context):
    store, app, client = context
    headers = {"Idempotency-Key": "synthetic-create-operation"}
    data = {"username": "same-operation", "password": PASSWORD}
    first = client.post(P + "/admin/users", headers=headers, json=data)
    second = client.post(P + "/admin/users", headers=headers, json=data)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    uid = first.json()["user"]["id"]
    assert store.one("SELECT COUNT(*) AS n FROM jobs WHERE uid=?", (uid,))["n"] == 1
    receipt = store.one("SELECT * FROM request_idempotency WHERE request_key=?", (headers["Idempotency-Key"],))
    assert PASSWORD not in json.dumps(receipt)
    conflict = client.post(P + "/admin/users", headers=headers, json={**data, "username": "different-target"})
    assert conflict.status_code == 409
    assert store.one("SELECT 1 FROM users WHERE username='different-target'") is None


def test_failed_skill_enqueue_rolls_back_the_entire_mutation(context, monkeypatch):
    store, app, client = context
    create_user(client)
    account = login_user(app, "person-a")
    def failed(*args, **kwargs):
        raise ValueError("synthetic queue failure")
    monkeypatch.setattr(store, "queue", failed)
    try:
        response = account.post(P + "/skills", json={"name": "atomic-skill", "content": "synthetic"})
        assert response.status_code == 409
        assert store.one("SELECT 1 FROM skills WHERE name='atomic-skill'") is None
    finally:
        account.__exit__(None, None, None)


def test_permit_auth_and_revocation_share_current_state(context):
    store, app, client = context
    user = create_user(client)
    runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (user["id"],))
    credential = store.decrypt(runtime["spec"])["runtime_key"]
    data = {"protocol_version": 2, "runtime_id": runtime["id"], "gateway_boot_id": "gateway-synthetic",
            "relay_boot_id": "relay-synthetic", "nonce": "synthetic-nonce"}
    with pytest.raises(HTTPException) as rejected:
        permit(store, data, "incorrect-runtime-secret-000000000000", DEFAULTS)
    assert rejected.value.status_code == 403
    first = permit(store, data, credential, DEFAULTS)
    assert not first["intake"]
    with store.tx() as db:
        db.execute("UPDATE runtimes SET status='ready',gate_policy='open' WHERE uid=?", (user["id"],))
    assert permit(store, data, credential, DEFAULTS)["intake"]
    with store.tx() as db:
        block_runtime(store, db, user["id"])
    revoked = permit(store, data, credential, DEFAULTS)
    assert not revoked["intake"] and not revoked["egress"]
    assert revoked["authorization_version"] > first["authorization_version"]


def test_unexpected_boot_change_cannot_reopen_ready_runtime(context):
    store, app, client = context
    user = create_user(client)
    runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (user["id"],))
    credential = store.decrypt(runtime["spec"])["runtime_key"]
    data = {"protocol_version": 2, "runtime_id": runtime["id"], "gateway_boot_id": "boot-1",
            "relay_boot_id": "relay-1", "nonce": "nonce-1"}
    permit(store, data, credential, DEFAULTS)
    with store.tx() as db:
        db.execute("UPDATE runtimes SET status='ready',gate_policy='open' WHERE uid=?", (user["id"],))
    value = permit(store, {**data, "gateway_boot_id": "boot-2"}, credential, DEFAULTS)
    assert not value["intake"]
    assert store.one("SELECT recovery_required FROM runtimes WHERE uid=?", (user["id"],))["recovery_required"] == 1


def test_expired_permit_observation_triggers_one_recovery_and_ignores_old_epoch(context):
    store, app, client = context
    user = create_user(client)
    runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (user["id"],))
    credential = store.decrypt(runtime["spec"])["runtime_key"]
    data = {"protocol_version": 2, "runtime_id": runtime["id"], "gateway_boot_id": "boot-loss",
            "relay_boot_id": "relay-loss", "nonce": "nonce-loss"}
    initial = permit(store, data, credential, DEFAULTS)
    with store.tx() as db:
        db.execute("UPDATE runtimes SET status='ready',gate_policy='open' WHERE uid=?", (user["id"],))
    lost = {**data, "needs_reconcile": True, "needs_reconcile_epoch": initial["gate_epoch"]}
    blocked = permit(store, lost, credential, DEFAULTS)
    assert not blocked["intake"]
    assert blocked["gate_epoch"] > initial["gate_epoch"]
    with store.tx() as db:
        db.execute("UPDATE runtimes SET recovery_required=0,gate_policy='open_pending' WHERE uid=?", (user["id"],))
    assert permit(store, lost, credential, DEFAULTS)["intake"]
    with store.tx() as db:
        db.execute("UPDATE runtimes SET gate_policy='open' WHERE uid=?", (user["id"],))
    assert permit(store, lost, credential, DEFAULTS)["intake"]


def test_model_disable_atomically_blocks_granted_account(context):
    store, app, client = context
    user = create_user(client)
    model = client.post(P + "/admin/models", json={"name": "Synthetic", "base_url": "http://model-fixture/v1",
                                                   "model_id": "synthetic"}).json()
    assert client.patch(P + "/admin/users/" + user["id"], json={"model_ids": [model["id"]]}).status_code == 200
    assert client.patch(P + "/admin/models/" + model["id"], json={"enabled": False}).status_code == 200
    assert store.one("SELECT security_blocked FROM runtimes WHERE uid=?", (user["id"],))["security_blocked"] == 1


def test_frozen_mode_survives_and_blocks_business_writes(context):
    store, app, client = context
    user = create_user(client)
    account = login_user(app, "person-a")
    try:
        state = client.get(P + "/admin/maintenance").json()
        response = client.post(P + "/admin/maintenance", json={"mode": "frozen", "state_version": state["state_version"]})
        assert response.status_code == 200, response.text
        assert account.post(P + "/skills", json={"name": "while-frozen", "content": "synthetic"}).status_code == 503
        assert client.post(P + "/admin/users", json={"username": "while-frozen", "password": PASSWORD}).status_code == 503
        assert store.maintenance_status()["maintenance_mode"] == "frozen"
        assert account.get(P + "/admin/maintenance").status_code == 403
    finally:
        account.__exit__(None, None, None)


def test_expired_idempotency_receipt_is_pinned_by_unfinished_job(context):
    store, app, client = context
    headers = {"Idempotency-Key": "unfinished-create-operation"}
    data = {"username": "unfinished-operation", "password": PASSWORD}
    first = client.post(P + "/admin/users", headers=headers, json=data)
    assert first.status_code == 202
    with store.tx() as db:
        db.execute("UPDATE request_idempotency SET expires=0 WHERE request_key=?", (headers["Idempotency-Key"],))
    replay = client.post(P + "/admin/users", headers=headers, json=data)
    assert replay.status_code == 202 and replay.json() == first.json()
    assert store.one("SELECT COUNT(*) AS n FROM jobs WHERE uid=?", (first.json()["user"]["id"],))["n"] == 1


def test_display_uses_applied_manifest_and_redacts_both_credential_versions(context):
    from control.app import tool_displays
    store, app, client = context
    account = create_user(client)
    pid = "synthetic-display"
    schema = {"type": "object", "properties": {"credential": {"type": "string", "format": "password"}}}
    old = {"plugins": [{"id": pid, "options": {"credential": "synthetic-old-secret"}, "manifest": {
        "config_schema": schema, "tools": ["old_tool"], "display": {"name": "旧版本", "outputs": ["count"]}}}]}
    latest = {"config_schema": schema, "tools": ["new_tool"], "display": {"name": "新版本"}}
    with store.tx() as db:
        db.execute("UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?", (store.encrypt(old), account["id"]))
        db.execute("INSERT INTO grants VALUES(?,?,?)", (account["id"], "plugin", pid))
        db.execute("INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)", (pid,"2.0.0","Synthetic","",json.dumps(latest),"unused","0"*64))
        db.execute("INSERT INTO installs(uid,plugin,version,enabled,config,previous) VALUES(?,?,?,1,?,NULL)",
                   (account["id"],pid,"2.0.0",store.encrypt({"credential":"synthetic-new-secret"})))
    displays = tool_displays(store, account["id"])
    assert "old_tool" in displays and "new_tool" not in displays
    assert set(displays["_redaction"]["_secrets"]) >= {"synthetic-old-secret", "synthetic-new-secret"}
