"""Account activation must complete the managed stop/resume lifecycle atomically."""
import pytest

from test_control import context, create_user, P
from test_roles import manager, snapshot_account


def complete_next(client, store, uid, action):
    headers = {"X-Worker-Key": store.worker_key}
    response = client.post("/internal/worker/claim", json={}, headers=headers)
    assert response.status_code == 200
    job = response.json()["job"]
    assert job["uid"] == uid and job["action"] == action
    response = client.post("/internal/worker/jobs/" + job["id"] + "/complete",
                           json={"lease": job["lease"], "ok": True}, headers=headers)
    assert response.status_code == 200
    return job


def ready_user(context, manager):
    store, app, superuser = context
    _, administrator = manager
    uid = create_user(administrator)["id"]
    complete_next(superuser, store, uid, "provision")
    return uid


@pytest.mark.parametrize("change_grants", [False, True])
def test_admin_reenable_after_completed_pause_reserves_and_resumes(context, manager, change_grants):
    store, app, superuser = context
    _, administrator = manager
    uid = ready_user(context, manager)
    before = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert administrator.patch(P + "/admin/users/" + uid, json={"active": False}).status_code == 200
    complete_next(superuser, store, uid, "pause")
    paused = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert paused["status"] == "paused" and paused["reserved"] == 0
    body = {"active": True}
    if change_grants:
        model = administrator.post(P + "/admin/models", json={"name": "Fixture", "base_url": "http://synthetic.invalid/v1", "model_id": "fixture"})
        assert model.status_code == 200
        body["model_ids"] = [model.json()["id"]]
    response = administrator.patch(P + "/admin/users/" + uid, json=body)
    assert response.status_code == 200
    assert response.json()["user"]["active"] is True
    assert response.json()["user"]["runtime"] == {"status": "provisioning"}
    assert response.json()["job"] == {"status": "queued"}
    runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert runtime["id"] == before["id"] and runtime["spec"] == before["spec"]
    assert runtime["reserved"] == 1 and runtime["desired"] == paused["desired"] + int(change_grants)
    jobs = store.rows("SELECT * FROM jobs WHERE uid=? AND status='queued'", (uid,))
    assert len(jobs) == 1 and jobs[0]["action"] == "resume"
    complete_next(superuser, store, uid, "resume")
    assert store.user(uid)["runtime"]["status"] == "ready"
    assert administrator.post(P + "/admin/users/" + uid + "/runtime/resume", json={}).status_code == 403


@pytest.mark.parametrize("pause_status", ["queued", "running"])
def test_reenable_waits_for_in_flight_pause_without_any_partial_change(context, manager, pause_status):
    store, app, superuser = context
    _, administrator = manager
    uid = ready_user(context, manager)
    assert administrator.patch(P + "/admin/users/" + uid, json={"active": False}).status_code == 200
    if pause_status == "running":
        claimed = superuser.post("/internal/worker/claim", json={}, headers={"X-Worker-Key": store.worker_key})
        assert claimed.status_code == 200 and claimed.json()["job"]["action"] == "pause"
    before = snapshot_account(store, uid)
    response = administrator.patch(P + "/admin/users/" + uid, json={"active": True, "model_ids": []})
    assert response.status_code == 409 and "等待空间暂停" in response.json()["message"]
    assert snapshot_account(store, uid) == before


def test_full_capacity_rolls_back_activation_auth_revision_grants_and_job(context, manager, monkeypatch):
    store, app, superuser = context
    _, administrator = manager
    uid = ready_user(context, manager)
    assert administrator.patch(P + "/admin/users/" + uid, json={"active": False}).status_code == 200
    complete_next(superuser, store, uid, "pause")
    create_user(administrator, "occupying-last-slot")
    monkeypatch.setenv("MAX_RUNTIMES", "1")
    before = snapshot_account(store, uid)
    response = administrator.patch(P + "/admin/users/" + uid, json={"active": True, "model_ids": []})
    assert response.status_code == 409 and "名额已满" in response.json()["message"]
    assert snapshot_account(store, uid) == before
    assert not store.user(uid)["active"]


def test_already_active_manually_paused_user_is_not_resumed_by_admin_edit(context, manager):
    store, app, superuser = context
    _, administrator = manager
    uid = ready_user(context, manager)
    assert superuser.post(P + "/admin/users/" + uid + "/runtime/pause", json={}).status_code == 200
    complete_next(superuser, store, uid, "pause")
    assert store.user(uid)["active"]
    for body in ({"active": True}, {"model_ids": []}):
        response = administrator.patch(P + "/admin/users/" + uid, json=body)
        assert response.status_code == 200 and response.json()["job"] == {"status": "deferred"}
        runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
        assert runtime["status"] == "paused" and runtime["reserved"] == 0
        assert store.rows("SELECT * FROM jobs WHERE uid=? AND status IN ('queued','running')", (uid,)) == []
