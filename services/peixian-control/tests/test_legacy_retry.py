"""Legacy retry uses synthetic TestClient/SQLite state, never Docker or live data."""
import json

import jsonschema
import pytest

from control.openapi import build_openapi
from control.store import digest, now
from test_control import context, P
from test_worker_snapshot import legacy_payload

RETRY = "/internal/worker/legacy-retry"


def imported(context, *, rollback=True):
    store, app, client = context
    headers = {"X-Worker-Key": store.worker_key}
    payload = legacy_payload()
    response = client.post("/internal/worker/legacy-import", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    record = response.json()
    body = {"uid": record["uid"], "snapshot_id": payload["snapshot"]["id"], "legacy_stopped": True}
    if rollback:
        response = client.post("/internal/worker/legacy-rollback", headers=headers,
                               json={"uid": body["uid"], "snapshot_id": body["snapshot_id"], "cleanup_confirmed": True})
        assert response.status_code == 200, response.text
    return store, client, headers, body, record


def snapshot(store, uid):
    return {"user": store.one("SELECT * FROM users WHERE id=?", (uid,)),
            "runtime": store.one("SELECT * FROM runtimes WHERE uid=?", (uid,)),
            "jobs": store.rows("SELECT * FROM jobs WHERE uid=? ORDER BY rowid", (uid,)),
            "auth": store.rows("SELECT * FROM auth WHERE uid=? ORDER BY hash", (uid,)),
            "retry_audit": store.rows("SELECT * FROM audit WHERE action='legacy.retry' ORDER BY rowid")}


def stale_auth(store, uid):
    with store.tx() as db:
        version = db.execute("SELECT auth_version FROM users WHERE id=?", (uid,)).fetchone()[0]
        for kind in ("cookie", "token"):
            db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)",
                       (digest("synthetic-stale-" + kind), uid, kind, "synthetic", "synthetic-csrf", now() + 600, version, now()))


def test_legacy_retry_resumes_same_runtime_and_revokes_auth_atomically(context):
    store, client, headers, body, record = imported(context)
    uid = body["uid"]
    stale_auth(store, uid)
    before = snapshot(store, uid)
    response = client.post(RETRY, headers=headers, json=body)
    assert response.status_code == 202, response.text
    value = response.json()
    assert set(value) == {"uid", "runtime_id", "status", "revision", "desired", "job_id"}
    assert value["uid"] == uid and value["runtime_id"] == record["runtime_id"]
    assert value["status"] == "provisioning"
    after = snapshot(store, uid)
    assert after["user"]["active"] == 1
    assert after["user"]["auth_version"] == before["user"]["auth_version"] + 1
    assert after["user"]["password"] == before["user"]["password"]
    assert after["auth"] == []
    assert after["runtime"]["reserved"] == 1
    assert after["runtime"]["spec"] == before["runtime"]["spec"]
    assert after["runtime"]["revision"] == before["runtime"]["revision"] == value["revision"]
    assert after["runtime"]["desired"] == before["runtime"]["desired"] == value["desired"]
    job = store.one("SELECT * FROM jobs WHERE id=?", (value["job_id"],))
    assert (job["uid"], job["action"], job["status"]) == (uid, "resume", "queued")
    assert len(after["jobs"]) == len(before["jobs"]) + 1
    assert len(after["retry_audit"]) == 1


@pytest.mark.parametrize("value", [None, False, "true", 1])
def test_retry_requires_explicit_boolean_stop_confirmation(context, value):
    store, client, headers, body, _ = imported(context)
    before = snapshot(store, body["uid"])
    request = {**body, "legacy_stopped": value}
    if value is None:
        request.pop("legacy_stopped")
    assert client.post(RETRY, headers=headers, json=request).status_code == 409
    assert snapshot(store, body["uid"]) == before


def test_retry_rejects_cookie_bearer_and_invalid_worker_key(context):
    store, client, headers, body, _ = imported(context)
    token = client.post(P + "/tokens", json={"name": "synthetic-retry-test"}).json()["token"]
    before = snapshot(store, body["uid"])
    for attempted in ({}, {"Authorization": "Bearer " + token}, {"X-Worker-Key": "invalid-synthetic"}):
        assert client.post(RETRY, headers=attempted, json=body).status_code == 403
    assert snapshot(store, body["uid"]) == before


def test_retry_requires_known_snapshot(context):
    store, client, headers, body, _ = imported(context)
    before = snapshot(store, body["uid"])
    assert client.post(RETRY, headers=headers, json={**body, "snapshot_id": "unknown-snapshot"}).status_code == 404
    assert snapshot(store, body["uid"]) == before


@pytest.mark.parametrize("mutation", ["no_rollback", "wrong_rollback_runtime", "wrong_legacy_mapping", "wrong_username"])
def test_retry_requires_exact_legacy_and_rollback_binding(context, mutation):
    store, client, headers, body, _ = imported(context)
    uid = body["uid"]
    with store.tx() as db:
        if mutation == "no_rollback":
            db.execute("DELETE FROM audit WHERE action='legacy.rollback'")
        elif mutation == "wrong_rollback_runtime":
            row = db.execute("SELECT id,target FROM audit WHERE action='legacy.rollback'").fetchone()
            target = json.loads(row["target"])
            target["runtime_id"] = "unrelated-synthetic-runtime"
            db.execute("UPDATE audit SET target=? WHERE id=?", (json.dumps(target), row["id"]))
        elif mutation == "wrong_legacy_mapping":
            row = db.execute("SELECT spec FROM runtimes WHERE uid=?", (uid,)).fetchone()
            spec = store.decrypt(row["spec"])
            spec["legacy"]["home_volume"] = "unrelated-synthetic-volume"
            db.execute("UPDATE runtimes SET spec=? WHERE uid=?", (store.encrypt(spec), uid))
        else:
            db.execute("UPDATE users SET username='ordinary-synthetic-user' WHERE id=?", (uid,))
    before = snapshot(store, uid)
    response = client.post(RETRY, headers=headers, json=body)
    if mutation in ("wrong_legacy_mapping", "wrong_username"):
        assert response.status_code == 404, response.text
    else:
        assert response.status_code in (404, 409), response.text
    assert snapshot(store, uid) == before

@pytest.mark.parametrize("mutation", ["active", "ready", "reserved", "queued", "running"])
def test_retry_refuses_invalid_runtime_or_active_job_without_partial_changes(context, mutation):
    store, client, headers, body, _ = imported(context)
    uid = body["uid"]
    with store.tx() as db:
        if mutation == "active":
            db.execute("UPDATE users SET active=1 WHERE id=?", (uid,))
        elif mutation == "ready":
            db.execute("UPDATE runtimes SET status='ready' WHERE uid=?", (uid,))
        elif mutation == "reserved":
            db.execute("UPDATE runtimes SET reserved=1 WHERE uid=?", (uid,))
        else:
            db.execute("UPDATE jobs SET status=? WHERE uid=?", (mutation, uid))
    before = snapshot(store, uid)
    assert client.post(RETRY, headers=headers, json=body).status_code == 409
    assert snapshot(store, uid) == before


def test_capacity_failure_rolls_back_activation_auth_and_job(context, monkeypatch):
    store, client, headers, body, _ = imported(context)
    uid = body["uid"]
    stale_auth(store, uid)
    monkeypatch.setenv("MAX_RUNTIMES", "0")
    before = snapshot(store, uid)
    assert client.post(RETRY, headers=headers, json=body).status_code == 409
    assert snapshot(store, uid) == before


@pytest.mark.parametrize("job_status,runtime_status", [("queued", "provisioning"), ("running", "provisioning"),
                                                       ("succeeded", "ready"), ("succeeded", "provisioning")])
def test_same_snapshot_retry_is_idempotent_for_current_active_attempt(context, job_status, runtime_status):
    store, client, headers, body, _ = imported(context)
    first = client.post(RETRY, headers=headers, json=body)
    assert first.status_code == 202, first.text
    with store.tx() as db:
        db.execute("UPDATE jobs SET status=? WHERE id=?", (job_status, first.json()["job_id"]))
        db.execute("UPDATE runtimes SET status=? WHERE uid=?", (runtime_status, body["uid"]))
    before = snapshot(store, body["uid"])
    repeat = client.post(RETRY, headers=headers, json=body)
    assert repeat.status_code == 202, repeat.text
    assert repeat.json()["job_id"] == first.json()["job_id"]
    assert repeat.json()["runtime_id"] == first.json()["runtime_id"]
    assert repeat.json()["status"] == runtime_status
    assert snapshot(store, body["uid"]) == before


@pytest.mark.parametrize("mutation", ["disabled", "auth_version", "later_rollback", "failed_job", "later_job"])
def test_retry_cannot_replay_after_revocation_or_superseded_attempt(context, mutation):
    store, client, headers, body, _ = imported(context)
    first = client.post(RETRY, headers=headers, json=body)
    assert first.status_code == 202, first.text
    uid = body["uid"]
    if mutation == "later_rollback":
        response = client.post("/internal/worker/legacy-rollback", headers=headers,
                               json={"uid": uid, "snapshot_id": body["snapshot_id"], "cleanup_confirmed": True})
        assert response.status_code == 200, response.text
    else:
        with store.tx() as db:
            if mutation == "disabled":
                db.execute("UPDATE users SET active=0,auth_version=auth_version+1 WHERE id=?", (uid,))
            elif mutation == "auth_version":
                db.execute("UPDATE users SET auth_version=auth_version+1 WHERE id=?", (uid,))
            elif mutation == "failed_job":
                db.execute("UPDATE jobs SET status='failed' WHERE id=?", (first.json()["job_id"],))
            else:
                db.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (first.json()["job_id"],))
                store.queue_in_transaction(db, uid, "apply")
    before = snapshot(store, uid)
    assert client.post(RETRY, headers=headers, json=body).status_code == 409
    assert snapshot(store, uid) == before


def test_legacy_retry_openapi_has_strict_internal_contract(context):
    _, app, _ = context
    document = build_openapi(app)
    operation = document["paths"][RETRY]["post"]
    assert operation["security"] == [{"WorkerKey": []}]
    assert operation["x-internal"] is True and operation["x-role"] == "worker"
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/LegacyRetryBody")
    assert operation["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("/LegacyRetryResult")
    assert {"403", "404", "409"}.issubset(operation["responses"])
    body = document["components"]["schemas"]["LegacyRetryBody"]
    assert set(body["properties"]) == set(body["required"]) == {"uid", "snapshot_id", "legacy_stopped"}
    assert body["additionalProperties"] is False
    validator = jsonschema.Draft202012Validator(body)
    valid = {"uid": "synthetic-uid", "snapshot_id": "synthetic-snapshot", "legacy_stopped": True}
    validator.validate(valid)
    for invalid in ({"uid": "synthetic-uid", "snapshot_id": "synthetic-snapshot"},
                    {**valid, "legacy_stopped": "true"}, {**valid, "legacy_stopped": 1},
                    {**valid, "legacy_stopped": False}, {**valid, "home_volume": "arbitrary"}):
        assert list(validator.iter_errors(invalid))
    output = document["components"]["schemas"]["LegacyRetryResult"]
    assert set(output["required"]) == {"uid", "runtime_id", "status", "revision", "desired", "job_id"}
