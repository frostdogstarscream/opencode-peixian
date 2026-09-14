import json
import sqlite3

import pytest

from test_control import context, create_user, PASSWORD, P, plugin_zip
from control.store import now


def publish_resources(admin):
    model = admin.post(P + "/admin/models", json={"name": "Synthetic model", "base_url": "http://fixture:8000/v1",
                                                  "model_id": "fixture", "api_key": "synthetic"})
    assert model.status_code == 200
    plugin = admin.post(P + "/admin/plugins", files={"file": ("synthetic.zip", plugin_zip())})
    assert plugin.status_code == 200
    return model.json()["id"], plugin.json()["id"]


def test_provision_job_is_published_only_after_grants_exist(context):
    store, app, admin = context
    model_id, plugin_id = publish_resources(admin)
    # A database trigger observes the exact instant the worker-visible job is
    # inserted, so a separate post-commit grant transaction cannot pass.
    with store.tx() as db:
        db.execute("""
            CREATE TRIGGER require_atomic_grants BEFORE INSERT ON jobs
            WHEN NEW.action='provision' AND EXISTS(
                SELECT 1 FROM users WHERE id=NEW.uid AND username='atomic-user')
            BEGIN
                SELECT CASE WHEN
                    (SELECT count(*) FROM grants WHERE uid=NEW.uid) != 2
                    THEN RAISE(ABORT, 'grants were not atomic') END;
            END
        """)
    response = admin.post(P + "/admin/users", json={
        "username": "atomic-user", "password": PASSWORD, "model_ids": [model_id], "plugin_ids": [plugin_id],
    })
    assert response.status_code == 202, response.text
    uid = response.json()["user"]["id"]
    assert {row["resource"] for row in store.rows("SELECT resource FROM grants WHERE uid=?", (uid,))} == {model_id, plugin_id}


def test_invalid_initial_grants_roll_back_user_runtime_job_and_capacity(context):
    store, app, admin = context
    model_id, plugin_id = publish_resources(admin)
    response = admin.post(P + "/admin/users", json={
        "username": "invalid-grants", "password": PASSWORD,
        "model_ids": [model_id], "plugin_ids": ["missing-plugin"],
    })
    assert response.status_code == 409
    assert not store.one("SELECT id FROM users WHERE username='invalid-grants'")
    for table in ("runtimes", "jobs", "grants"):
        assert store.one(f"SELECT count(*) AS n FROM {table}")["n"] == 0
    response = admin.post(P + "/admin/users", json={"username": "oversize-grants", "password": PASSWORD,
                                                    "model_ids": [model_id] * 101})
    assert response.status_code == 409
    assert not store.one("SELECT id FROM users WHERE username='oversize-grants'")


def test_disable_is_atomic_with_pause_queued_behind_existing_work(context):
    store, app, admin = context
    uid = create_user(admin)["id"]
    original = store.one("SELECT * FROM jobs WHERE uid=?", (uid,))
    with store.tx() as db:
        db.execute("UPDATE jobs SET status='running',lease='synthetic-lease',heartbeat=? WHERE id=?", (now(), original["id"]))
        db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)", ("synthetic-hash", uid, "token", "test", None,
                                                              now() + 1000, 1, now()))
    response = admin.patch(P + "/admin/users/" + uid, json={"active": False})
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["action"] == "pause" and job["status"] == "queued"
    assert not store.user(uid)["active"]
    assert store.one("SELECT count(*) AS n FROM auth WHERE uid=?", (uid,))["n"] == 0
    assert store.one("SELECT reserved FROM runtimes WHERE uid=?", (uid,))["reserved"] == 1
    assert store.queue(uid, "pause")["id"] == job["id"]
    assert store.one("SELECT count(*) AS n FROM jobs WHERE uid=?", (uid,))["n"] == 2


def test_invalid_edit_rolls_back_grants_and_login_state(context):
    store, app, admin = context
    model_id, _ = publish_resources(admin)
    uid = create_user(admin)["id"]
    response = admin.patch(P + "/admin/users/" + uid, json={
        "model_ids": [model_id], "plugin_ids": ["missing"], "active": False,
    })
    assert response.status_code == 409
    assert store.user(uid)["active"]
    assert store.rows("SELECT * FROM grants WHERE uid=?", (uid,)) == []
    assert store.one("SELECT count(*) AS n FROM jobs WHERE uid=?", (uid,))["n"] == 1
    response = admin.patch(P + "/admin/users/" + uid, json={"active": "false"})
    assert response.status_code == 409
    assert store.user(uid)["active"]


def test_apply_does_not_restart_unreserved_paused_runtime(context):
    store, app, admin = context
    uid = create_user(admin)["id"]
    with store.tx() as db:
        db.execute("UPDATE jobs SET status='succeeded' WHERE uid=?", (uid,))
        db.execute("UPDATE runtimes SET status='paused',reserved=0,revision=1 WHERE uid=?", (uid,))
    job = store.queue(uid, "apply")
    assert job["id"] is None and job["status"] == "deferred"
    runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert runtime["desired"] == 2 and runtime["status"] == "paused" and runtime["reserved"] == 0
    assert store.rows("SELECT * FROM jobs WHERE uid=? AND status='queued'", (uid,)) == []
    resumed = store.queue(uid, "resume")
    assert resumed["status"] == "queued" and resumed["revision"] == 2
    assert store.one("SELECT reserved FROM runtimes WHERE uid=?", (uid,))["reserved"] == 1


def test_pending_pause_keeps_later_config_from_restarting_environment(context):
    store, app, admin = context
    uid = create_user(admin)["id"]
    pause = store.queue(uid, "pause")
    change = store.queue(uid, "apply")
    assert change["id"] == pause["id"]
    assert [row["action"] for row in store.rows("SELECT action FROM jobs WHERE uid=? ORDER BY rowid", (uid,))] == ["provision", "pause"]
    assert store.one("SELECT desired FROM runtimes WHERE uid=?", (uid,))["desired"] == 2
