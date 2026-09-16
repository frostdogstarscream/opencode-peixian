"""Real SQLite read-modify-write races with a barrier before BEGIN IMMEDIATE."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import threading

from test_control import context, create_user, login_user, plugin_zip, P


def together_at_transaction(store, monkeypatch, operations):
    """Both handlers reach their first write before either takes the write lock.

    Reading old state before tx would therefore make both handlers read the same
    stale row; reading inside tx sees the predecessor's committed update.
    """
    original = store.atomic_request
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    entrants = 0

    @contextmanager
    def synchronized():
        nonlocal entrants
        with lock:
            entrants += 1
            first_pair = entrants <= 2
        if first_pair:
            barrier.wait(timeout=5)
        with original() as db:
            yield db

    with monkeypatch.context() as patch:
        # Synchronize before the outer BEGIN that also commits the request receipt.
        patch.setattr(store, "atomic_request", synchronized)
        with ThreadPoolExecutor(max_workers=2) as callers:
            pending = [callers.submit(operation) for operation in operations]
            return [future.result(timeout=10) for future in pending]


def test_concurrent_skill_edits_keep_disjoint_fields_and_each_rollback_version(context, monkeypatch):
    store, app, admin = context
    account = create_user(admin)
    browser = login_user(app, "person-a")
    try:
        created = browser.post(P + "/skills", json={"name": "race-skill", "content": "original", "description": "original description"})
        assert created.status_code == 200
        sid = created.json()["id"]
        path = P + "/skills/" + sid
        responses = together_at_transaction(store, monkeypatch, [
            lambda: browser.patch(path, json={"content": "new content"}),
            lambda: browser.patch(path, json={"description": "new description"}),
        ])
        assert [response.status_code for response in responses] == [200, 200]
        row = store.one("SELECT * FROM skills WHERE id=? AND uid=?", (sid, account["id"]))
        assert (row["content"], row["description"], row["version"]) == ("new content", "new description", 3)
        history = json.loads(row["history"])
        assert [value["version"] for value in history] == [1, 2]
        assert history[0]["content"] == "original" and history[0]["description"] == "original description"
        assert (history[1]["content"], history[1]["description"]) in [
            ("original", "new description"), ("new content", "original description")]
        responses = together_at_transaction(store, monkeypatch, [
            lambda: browser.post(path + "/rollback"), lambda: browser.post(path + "/rollback"),
        ])
        assert [response.status_code for response in responses] == [200, 200]
        row = store.one("SELECT * FROM skills WHERE id=?", (sid,))
        assert (row["content"], row["description"], row["version"], json.loads(row["history"])) == ("original", "original description", 5, [])
    finally:
        browser.__exit__(None, None, None)


def test_concurrent_model_patch_does_not_revert_rotated_secret(context, monkeypatch):
    store, app, admin = context
    created = admin.post(P + "/admin/models", json={"name": "original", "base_url": "http://synthetic.invalid/v1", "model_id": "synthetic", "api_key": "synthetic-old", "is_default": True})
    assert created.status_code == 200
    mid = created.json()["id"]
    path = P + "/admin/models/" + mid
    responses = together_at_transaction(store, monkeypatch, [
        lambda: admin.patch(path, json={"name": "renamed"}),
        lambda: admin.patch(path, json={"api_key": "synthetic-new"}),
    ])
    assert [response.status_code for response in responses] == [200, 200]
    row = store.one("SELECT * FROM models WHERE id=?", (mid,))
    assert row["name"] == "renamed" and store.decrypt(row["secret"]) == "synthetic-new" and row["is_default"] == 1


def test_concurrent_template_patch_preserves_disjoint_fields(context, monkeypatch):
    store, app, admin = context
    created = admin.post(P + "/admin/templates", json={"name": "original", "content": "original", "description": "original"})
    assert created.status_code == 200
    tid = created.json()["id"]
    path = P + "/admin/templates/" + tid
    responses = together_at_transaction(store, monkeypatch, [
        lambda: admin.patch(path, json={"description": "new description"}),
        lambda: admin.patch(path, json={"content": "new content"}),
    ])
    assert [response.status_code for response in responses] == [200, 200]
    row = store.one("SELECT * FROM templates WHERE id=?", (tid,))
    assert (row["content"], row["description"]) == ("new content", "new description")


def test_concurrent_plugin_config_keeps_new_secret_and_immediate_previous_version(context, monkeypatch):
    store, app, admin = context
    account = create_user(admin)
    assert admin.post(P + "/admin/plugins", files={"file": ("plugin.zip", plugin_zip())}).status_code == 200
    assert admin.patch(P + "/admin/users/" + account["id"], json={"plugin_ids": ["synthetic-echo"]}).status_code == 200
    browser = login_user(app, "person-a")
    path = P + "/plugins/synthetic-echo"
    try:
        assert browser.put(path, json={"config": {"label": "initial", "token": "synthetic-old"}}).status_code == 200
        responses = together_at_transaction(store, monkeypatch, [
            lambda: browser.put(path, json={"config": {"label": "initial", "token": "synthetic-new"}}),
            lambda: browser.put(path, json={"config": {"label": "renamed", "token": ""}}),
        ])
        assert [response.status_code for response in responses] == [200, 200]
        row = store.one("SELECT * FROM installs WHERE uid=? AND plugin='synthetic-echo'", (account["id"],))
        current, previous = store.decrypt(row["config"]), store.decrypt(row["previous"])
        assert current["token"] == "synthetic-new"
        if current["label"] == "renamed":
            assert previous["config"] == {"label": "initial", "token": "synthetic-new"}
        else:
            assert current["label"] == "initial"
            assert previous["config"] == {"label": "renamed", "token": "synthetic-old"}
        responses = together_at_transaction(store, monkeypatch, [
            lambda: browser.post(path + "/rollback"), lambda: browser.post(path + "/rollback"),
        ])
        assert sorted(response.status_code for response in responses) == [200, 409]
        restored = store.one("SELECT * FROM installs WHERE uid=? AND plugin='synthetic-echo'", (account["id"],))
        assert store.decrypt(restored["config"]) == previous["config"] and restored["previous"] is None
    finally:
        browser.__exit__(None, None, None)
