import asyncio
from types import SimpleNamespace

from cryptography.fernet import Fernet
import httpx
import pytest

from control.store import Store
from control.runtime_security import SafetyCoordinator, block_runtime
from control.concurrency import WorkPool
from shared.orchestration_config import from_environment
from test_runtime_protocol import cluster


def fresh_store(tmp_path):
    for name, content in (("encryption", Fernet.generate_key()), ("worker", b"synthetic-worker-key-for-offline-tests-123456789"),
                          ("admin", b"synthetic-password-for-tests-123")):
        (tmp_path / name).write_bytes(content)
    return Store(tmp_path / "control", tmp_path / "encryption", tmp_path / "worker", tmp_path / "admin")


async def coordinator(store, policy):
    pool = WorkPool(2, 4, 1, "gateway-integration")
    app = SimpleNamespace(state=SimpleNamespace(store=store, db_work=pool, orchestration_settings=from_environment()))
    result = SafetyCoordinator(app)
    await result.http.aclose()
    result.http = httpx.AsyncClient(transport=policy["transport"])
    return result, pool


async def finish_initial_publication(store, gm, rm, safety, uid):
    # Host verification is represented by this state transition; the remaining
    # startup/open protocol uses the real SQLite permit and safety coordinator.
    with store.tx() as db:
        db.execute("UPDATE jobs SET status='succeeded' WHERE uid=?", (uid,))
        db.execute("UPDATE runtimes SET revision=1,status='ready',gate_policy='reopen_check' WHERE uid=?", (uid,))
    assert safety.command(uid)["body"]["action"] == "open"
    await gm.renew_once()
    await rm.renew_once()
    await safety.sync(uid)
    assert store.one("SELECT gate_policy FROM runtimes WHERE uid=?", (uid,))["gate_policy"] == "open"
    assert gm.gate.mode == rm.gate.mode == "open"


def test_real_permit_first_provision_can_complete_while_default_closed(tmp_path):
    async def scenario():
        store = fresh_store(tmp_path)
        async with cluster(tmp_path, store) as (gm, rm, client, policy):
            safety, pool = await coordinator(store, policy)
            try:
                assert gm.gate.mode == rm.gate.mode == "closed"
                assert gm.state()["activity"]["idle"]
                assert not gm.gate.valid("intake")
                await finish_initial_publication(store, gm, rm, safety, policy["uid"])
            finally:
                await safety.close()
                await pool.close()
    asyncio.run(scenario())


def test_real_security_same_close_operation_recovers_after_relay_failure(tmp_path):
    async def scenario():
        store = fresh_store(tmp_path)
        async with cluster(tmp_path, store) as (gm, rm, client, policy):
            safety, pool = await coordinator(store, policy)
            uid = policy["uid"]
            try:
                await finish_initial_publication(store, gm, rm, safety, uid)
                with store.tx() as db:
                    block_runtime(store, db, uid)
                expected = safety.command(uid)["body"]
                policy["relay_available"] = False
                await safety.sync(uid)
                assert gm.gate.mode == "closed"
                assert gm.gate.epoch == expected["gate_epoch"]
                assert rm.gate.mode == "open"
                policy["relay_available"] = True
                assert safety.command(uid)["body"] == expected
                await safety.sync(uid)
                assert rm.gate.mode == "closed"
                assert store.one("SELECT security_confirmed_at FROM runtimes WHERE uid=?", (uid,))["security_confirmed_at"] is not None
            finally:
                await safety.close()
                await pool.close()
    asyncio.run(scenario())


def test_real_permit_unexpected_boot_cannot_reopen_runtime(tmp_path):
    async def scenario():
        store = fresh_store(tmp_path)
        async with cluster(tmp_path, store) as (gm, rm, client, policy):
            safety, pool = await coordinator(store, policy)
            try:
                await finish_initial_publication(store, gm, rm, safety, policy["uid"])
                gm.gate.boot_id = "replacement-boot"
                await gm.renew_once()
                assert not gm.gate.valid("intake") and not gm.gate.valid("egress")
                assert store.one("SELECT recovery_required FROM runtimes WHERE uid=?", (policy["uid"],))["recovery_required"] == 1
                assert safety.command(policy["uid"]) is None
            finally:
                await safety.close()
                await pool.close()
    asyncio.run(scenario())


def test_real_permit_loss_requires_reconciliation_and_a_new_open_epoch(tmp_path):
    async def scenario():
        store = fresh_store(tmp_path)
        async with cluster(tmp_path, store) as (gm, rm, client, policy):
            safety, pool = await coordinator(store, policy)
            uid = policy["uid"]
            try:
                await finish_initial_publication(store, gm, rm, safety, uid)
                old_epoch = gm.gate.epoch
                old_boots = (gm.gate.boot_id, rm.gate.boot_id)
                policy["control_available"] = False
                clock = [max(gm.gate.deadline, rm.gate.deadline) + 1]
                gm.gate.clock = rm.gate.clock = lambda: clock[0]
                async with asyncio.timeout(1):
                    while not gm.gate.needs_reconcile or not rm.gate.needs_reconcile:
                        await asyncio.sleep(.01)
                assert gm.gate.mode == rm.gate.mode == "closed"
                policy["control_available"] = True
                await gm.renew_once()
                await rm.renew_once()
                row = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
                assert row["recovery_required"] == 1 and row["gate_epoch"] > old_epoch
                assert not gm.gate.valid("intake") and not rm.gate.valid("egress")
                assert safety.command(uid) is None
                assert gm.gate.mode == rm.gate.mode == "closed"
                # Simulate the verified Worker's reconciliation result, keeping
                # the actual process boot identities unchanged.
                with store.tx() as db:
                    db.execute("UPDATE runtimes SET recovery_required=0,gate_policy='reopen_check' WHERE uid=?", (uid,))
                await finish_initial_publication(store, gm, rm, safety, uid)
                assert gm.gate.epoch > old_epoch
                assert not gm.gate.needs_reconcile and not rm.gate.needs_reconcile
                assert (gm.gate.boot_id, rm.gate.boot_id) == old_boots
            finally:
                await safety.close()
                await pool.close()
    asyncio.run(scenario())
