"""Deterministic issuance/cancellation races; only isolated synthetic identities."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from client_helpers import TestClient
from control.concurrency import WorkPool
from test_control import context, create_user, login_user, P, PASSWORD


def test_revoked_issuer_cannot_mint_token_after_waiting_for_business_work(context, monkeypatch):
    store, app, admin = context
    create_user(admin)
    browser = login_user(app, "person-a")
    entered, release = threading.Event(), threading.Event()
    try:
        issued = browser.post(P + "/tokens", json={"name": "synthetic issuer"}).json()
        original = app.state.db_work.run

        async def gated(fn, *args, **kwargs):
            if fn.__name__ == "token_create":
                def delayed():
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("test did not release issuance")
                    return fn(*args, **kwargs)
                return await original(delayed)
            return await original(fn, *args, **kwargs)

        monkeypatch.setattr(app.state.db_work, "run", gated)
        with TestClient(app) as bearer, ThreadPoolExecutor(max_workers=1) as callers:
            bearer.headers["Authorization"] = "Bearer " + issued["token"]
            pending = callers.submit(bearer.post, P + "/tokens", json={"name": "must not be issued"})
            try:
                assert entered.wait(5)
                assert browser.delete(P + "/tokens/" + issued["item"]["id"]).status_code == 200
            finally:
                release.set()
            assert pending.result(timeout=5).status_code == 401
        assert store.rows("SELECT hash FROM auth WHERE kind='token'") == []
    finally:
        release.set()
        browser.__exit__(None, None, None)


@pytest.mark.parametrize("action", ["create", "reset"])
@pytest.mark.parametrize("revoke", ["token", "disable"])
def test_admin_revoked_during_password_hash_has_no_management_effect(context, monkeypatch, action, revoke):
    store, app, superuser = context
    response = superuser.post(P + "/admin/users", json={"username": "manager", "password": PASSWORD, "role": "admin"})
    assert response.status_code == 202
    manager_id = response.json()["user"]["id"]
    manager = login_user(app, "manager")
    target = create_user(superuser, "reset-target")
    target_before = store.one("SELECT password,auth_version FROM users WHERE id=?", (target["id"],))
    counts_before = {table: store.one("SELECT count(*) n FROM " + table)["n"] for table in ("users", "runtimes", "jobs")}
    issued = manager.post(P + "/tokens", json={"name": "synthetic management issuer"}).json()
    entered, release = threading.Event(), threading.Event()
    original = store.passwords

    def gated_hash(value):
        entered.set()
        if not release.wait(5):
            raise AssertionError("test did not release hashing")
        return original.hash(value)

    monkeypatch.setattr(store, "passwords", SimpleNamespace(hash=gated_hash, verify=original.verify))
    try:
        with TestClient(app) as bearer, ThreadPoolExecutor(max_workers=1) as callers:
            bearer.headers["Authorization"] = "Bearer " + issued["token"]
            path = P + "/admin/users" if action == "create" else P + "/admin/users/" + target["id"] + "/reset-password"
            body = {"password": PASSWORD + "-new"}
            if action == "create":
                body["username"] = "must-not-exist"
            pending = callers.submit(bearer.post, path, json=body)
            try:
                assert entered.wait(5)
                if revoke == "token":
                    revoked = manager.delete(P + "/tokens/" + issued["item"]["id"])
                else:
                    revoked = superuser.patch(P + "/admin/users/" + manager_id, json={"active": False})
                assert revoked.status_code == 200, revoked.text
            finally:
                release.set()
            assert pending.result(timeout=5).status_code == 401
        assert store.one("SELECT id FROM users WHERE username='must-not-exist'") is None
        assert store.one("SELECT password,auth_version FROM users WHERE id=?", (target["id"],)) == target_before
        assert {table: store.one("SELECT count(*) n FROM " + table)["n"] for table in counts_before} == counts_before
    finally:
        release.set()
        manager.__exit__(None, None, None)


def test_pool_shutdown_rejects_already_queued_work_before_submission():
    async def scenario():
        pool = WorkPool(1, 1, 2, "shutdown-race-test")
        entered, release = threading.Event(), threading.Event()
        calls = []

        def active():
            entered.set()
            assert release.wait(5)
            return "finished"

        first = asyncio.create_task(pool.run(active))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            queued = asyncio.create_task(pool.run(lambda: calls.append("must not run")))
            while pool.outstanding != 2:
                await asyncio.sleep(0)
            closing = asyncio.create_task(pool.close())
            while not pool.closed:
                await asyncio.sleep(0)
            release.set()
            assert await first == "finished"
            with pytest.raises(HTTPException) as error:
                await queued
            assert error.value.status_code == 503
            await closing
            assert not calls and pool.outstanding == 0 and not pool.futures
        finally:
            release.set()
            await pool.close()
    asyncio.run(scenario())
