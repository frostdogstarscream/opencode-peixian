import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from control.worker_api import runtime_spec
from control.store import encode, now
from test_control import context, create_user, PASSWORD, P, plugin_zip


def test_claim_uses_one_snapshot_and_commits_matching_revision(context, monkeypatch):
    store, app, admin = context
    model = admin.post(P + "/admin/models", json={
        "name": "Before", "base_url": "http://before:8000/v1", "model_id": "before", "api_key": "synthetic-before",
    }).json()
    user, _ = store.create_user("snapshot-user", PASSWORD, model_ids=[model["id"]])
    uid = user["id"]
    reached = threading.Event()
    attempting = threading.Event()
    committed = threading.Event()
    original = store.decrypt
    blocked_once = False

    def observe(value):
        nonlocal blocked_once
        if not blocked_once:
            blocked_once = True
            reached.set()
            assert attempting.wait(2)
            assert not committed.wait(0.05), "Writer committed inside claim's configuration snapshot"
        return original(value)

    def writer():
        assert reached.wait(2)
        attempting.set()
        with store.tx() as db:
            db.execute("UPDATE models SET name='After',model_id='after' WHERE id=?", (model["id"],))
            db.execute("UPDATE runtimes SET desired=2 WHERE uid=?", (uid,))
        committed.set()

    monkeypatch.setattr(store, "decrypt", observe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        response = admin.post("/internal/worker/claim", headers={"X-Worker-Key": store.worker_key}, json={})
        future.result(timeout=5)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["job"]["revision"] == payload["spec"]["revision"] == 1
    assert payload["spec"]["models"][0]["upstream_model"] == "before"
    assert store.one("SELECT desired FROM runtimes WHERE uid=?", (uid,))["desired"] == 2
    assert store.one("SELECT revision FROM jobs WHERE uid=?", (uid,))["revision"] == 1
    monkeypatch.setattr(store, "decrypt", original)
    with pytest.raises(ValueError):
        runtime_spec(store, uid, 1)
    assert runtime_spec(store, uid, 2)["models"][0]["upstream_model"] == "after"


def test_claim_rolls_back_lease_when_spec_cannot_be_built(context, monkeypatch):
    import control.worker_api as worker_api
    store, app, admin = context
    uid = create_user(admin)["id"]
    def invalid(*args, **kwargs):
        raise ValueError("Synthetic invalid configuration")
    monkeypatch.setattr(worker_api, "runtime_spec", invalid)
    # Calling the handler directly keeps expected exceptions out of HTTP logs.
    route = next(route for route in app.routes if getattr(route, "path", "") == "/internal/worker/claim")
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(route.endpoint(None, True))
    job = store.one("SELECT * FROM jobs WHERE uid=?", (uid,))
    assert job["status"] == "queued" and job["lease"] is None and job["attempts"] == 0


def test_false_like_cleanup_value_cannot_release_capacity(context):
    store, app, admin = context
    create_user(admin)
    headers = {"X-Worker-Key": store.worker_key}
    job = admin.post("/internal/worker/claim", headers=headers, json={}).json()["job"]
    response = admin.post("/internal/worker/jobs/" + job["id"] + "/complete", headers=headers,
                          json={"lease": job["lease"], "ok": False, "cleanup_confirmed": "false"})
    assert response.status_code == 200
    assert store.one("SELECT reserved FROM runtimes")["reserved"] == 1


def test_zip_nul_filename_is_rejected_before_publication(context):
    store, app, admin = context
    original = io.BytesIO(plugin_zip())
    changed = io.BytesIO()
    # ZipInfo's reader truncates at NUL but preserves orig_filename. Alter both
    # local and central directory names to construct that ambiguous archive.
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(changed, "w") as output:
        for name in source.namelist():
            output.writestr(name, source.read(name))
        output.writestr("ambiguousQtail.mjs", "synthetic")
    data = changed.getvalue().replace(b"ambiguousQtail.mjs", b"ambiguous\0tail.mjs")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = archive.infolist()[-1]
        assert member.orig_filename != member.filename
    response = admin.post(P + "/admin/plugins", files={"file": ("ambiguous.zip", data)})
    assert response.status_code == 400
    assert store.rows("SELECT * FROM plugins") == []


def legacy_payload(name="client-a"):
    return {"username": name, "password": PASSWORD, "model_ids": [],
            "legacy": {"home_volume": f"peixian-opencode_{name}-home",
                       "workspace_volume": f"peixian-opencode_{name}-workspace"},
            "snapshot": {"id": "synthetic-snapshot-01", "sha256": "a" * 64}}


def test_legacy_import_fixed_volumes_idempotency_and_rollback(context):
    store, app, admin = context
    headers = {"X-Worker-Key": store.worker_key}
    payload = legacy_payload()
    assert admin.post("/internal/worker/legacy-import", json=payload).status_code == 403
    invalid = {**payload, "legacy": {**payload["legacy"], "home_volume": "unrelated-volume"}}
    assert admin.post("/internal/worker/legacy-import", headers=headers, json=invalid).status_code == 400
    response = admin.post("/internal/worker/legacy-import", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    first = response.json()
    assert first["created"]
    uid = first["uid"]
    original_password = store.one("SELECT password FROM users WHERE id=?", (uid,))["password"]
    repeat = admin.post("/internal/worker/legacy-import", headers=headers,
                        json={**payload, "password": "another-synthetic-password"}).json()
    assert not repeat["created"] and repeat["uid"] == uid and repeat["runtime_id"] == first["runtime_id"]
    assert store.one("SELECT password FROM users WHERE id=?", (uid,))["password"] == original_password
    assert store.one("SELECT count(*) AS n FROM jobs")["n"] == 1
    assert store.one("SELECT count(*) AS n FROM audit WHERE action='legacy.import'")["n"] == 1
    state = admin.get("/internal/worker/legacy-status/" + uid, headers=headers).json()
    assert state["status"] == "pending" and state["reserved"]
    rollback = {"uid": uid, "snapshot_id": payload["snapshot"]["id"], "cleanup_confirmed": "true"}
    assert admin.post("/internal/worker/legacy-rollback", headers=headers, json=rollback).status_code == 409
    assert admin.post("/internal/worker/legacy-rollback", headers=headers,
                      json={**rollback, "snapshot_id": "other", "cleanup_confirmed": True}).status_code == 404
    response = admin.post("/internal/worker/legacy-rollback", headers=headers,
                          json={**rollback, "cleanup_confirmed": True})
    assert response.status_code == 200
    assert not store.user(uid)["active"]
    assert store.one("SELECT status,reserved FROM runtimes WHERE uid=?", (uid,)) == {"status": "failed", "reserved": 0}
    assert store.one("SELECT status,lease FROM jobs WHERE uid=?", (uid,)) == {"status": "failed", "lease": None}


def test_legacy_import_never_rebinds_existing_nonlegacy_account(context):
    store, app, admin = context
    existing, _ = store.create_user("client-a", PASSWORD)
    response = admin.post("/internal/worker/legacy-import", headers={"X-Worker-Key": store.worker_key}, json=legacy_payload())
    assert response.status_code == 409
    spec = store.decrypt(store.one("SELECT spec FROM runtimes WHERE uid=?", (existing["id"],))["spec"])
    assert spec["legacy"] is None
    assert store.rows("SELECT * FROM audit WHERE action='legacy.import'") == []
