import asyncio
from threading import Event

import httpx
import pytest
from fastapi import HTTPException

from control.concurrency import DEFAULTS, LoginLimiter, WorkPool, settings


def test_cancelled_running_work_retains_capacity_until_thread_finishes():
    async def run():
        pool = WorkPool(1, 1, .1, "test")
        started, release = Event(), Event()
        def blocking():
            started.set()
            release.wait(3)
        task = asyncio.create_task(pool.run(blocking))
        while not started.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.outstanding == 1
        queued = asyncio.create_task(pool.run(lambda: 2))
        await asyncio.sleep(.01)
        with pytest.raises(HTTPException) as error:
            await pool.run(lambda: 3)
        assert error.value.status_code == 503
        assert error.value.headers["Retry-After"] == "1"
        assert pool.stats() == {"outstanding": 2, "running": 1, "queued": 1,
                                "capacity": 2, "rejected": 1, "closed": False}
        with pytest.raises(HTTPException):
            await queued
        assert pool.outstanding == 1
        release.set()
        for _ in range(100):
            if pool.outstanding == 0:
                break
            await asyncio.sleep(.01)
        assert pool.outstanding == 0
        assert pool.stats()["queued"] == pool.stats()["running"] == 0
        assert await pool.run(lambda: 4) == 4
        await pool.close()
    asyncio.run(run())


def test_queued_cancellation_and_operation_exception_release_capacity():
    async def run():
        pool = WorkPool(1, 1, 1, "test")
        release = Event()
        active = asyncio.create_task(pool.run(release.wait, 3))
        await asyncio.sleep(.01)
        queued = asyncio.create_task(pool.run(lambda: 1))
        await asyncio.sleep(.01)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert pool.outstanding == 1
        release.set()
        await active
        def broken():
            raise ValueError("synthetic")
        with pytest.raises(ValueError):
            await pool.run(broken)
        assert pool.outstanding == 0
        await pool.close()
        with pytest.raises(HTTPException):
            await pool.run(lambda: 1)
    asyncio.run(run())


def test_login_state_is_bounded_and_expires_without_evicting_active_bans():
    clock = [0]
    limits = {**DEFAULTS, "login_capacity": 2, "login_burst": 100, "login_source_burst": 100}
    limiter = LoginLimiter(limits, clock=lambda: clock[0])
    for _ in range(10):
        limiter.check("source", "user-a")
    with pytest.raises(HTTPException) as error:
        limiter.check("source", "user-a")
    assert error.value.status_code == 429
    limiter.check("source", "user-b")
    with pytest.raises(HTTPException) as error:
        limiter.check("source", "user-c")
    assert error.value.status_code == 503
    assert len(limiter.attempts) == 2
    clock[0] = 301
    limiter.check("source", "user-c")
    assert list(limiter.attempts) == [("source", "user-c")]


def test_fifty_normal_users_behind_one_source_are_not_blanket_banned():
    limiter = LoginLimiter(DEFAULTS, clock=lambda: 0)
    for index in range(50):
        limiter.check("shared-intranet-proxy", f"user-{index}")
        limiter.success("shared-intranet-proxy", f"user-{index}")
    assert not limiter.attempts
    assert len(limiter.sources) == 1
    with pytest.raises(HTTPException) as error:
        limiter.check("shared-intranet-proxy", "user-51")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "1"


def test_settings_reject_busy_wait_and_revocation_budget_drift(monkeypatch):
    monkeypatch.setenv("PX_DB_BUSY_MS", "1001")
    with pytest.raises(ValueError):
        settings()
    monkeypatch.setenv("PX_DB_BUSY_MS", "1000")
    monkeypatch.setenv("PX_AUTH_RECHECK_SECONDS", "3")
    with pytest.raises(ValueError):
        settings()


def test_authentication_remains_responsive_and_rechecks_after_password_work(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from control.store import Store
    from control.app import create_app, PREFIX
    password = "synthetic-password-123456"
    for filename, content in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-12345678901234567890"), ("admin", password.encode())):
        (tmp_path / filename).write_bytes(content)
    store = Store(tmp_path / "db", tmp_path / "key", tmp_path / "worker", tmp_path / "admin")
    started, release = Event(), Event()
    def blocked_verify(*_):
        started.set()
        release.wait(3)
        return True
    # Replace the helper, not the immutable argon2 extension method.
    class Passwords:
        verify = staticmethod(blocked_verify)
    store.passwords = Passwords()
    async def run():
        app = create_app(store)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                login = asyncio.create_task(client.post(PREFIX + "/auth/login", json={"username": "admin", "password": password}))
                while not started.is_set():
                    await asyncio.sleep(.001)
                response = await asyncio.wait_for(client.get("/health"), .5)
                assert response.status_code == 200
                def disable():
                    with store.tx() as db:
                        db.execute("UPDATE users SET active=0,auth_version=auth_version+1 WHERE username='admin'")
                await app.state.db_work.run(disable)
                release.set()
                assert (await login).status_code == 401
                assert store.one("SELECT count(*) n FROM auth")["n"] == 0
    asyncio.run(run())
