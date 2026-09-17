"""PR-7A: real isolated SQLite, no Docker or existing deployment access."""
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest

from control.store import Store
from control.runtime_pool import start, stop, public_status
from control.schema import validate


@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_RUNTIMES", "2")
    for name, value in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-credential-123456789"), ("admin", b"synthetic-administrator-password")):
        (tmp_path / name).write_bytes(value)
    args = (tmp_path / "db", tmp_path / "key", tmp_path / "worker", tmp_path / "admin")
    return Store(*args, runtime_mode="on_demand"), args


def account(s, name="synthetic"):
    user, job = s.create_user(name, "synthetic-user-password-123")
    assert job is None
    return user["id"]


def begin(s, uid, **kwargs):
    with s.tx() as db:
        return start(s, db, uid, **kwargs)


def test_five_accounts_two_slots_and_duplicate_starts(pool):
    s, _ = pool
    users = [account(s, str(i)) for i in range(5)]
    assert s.one("SELECT sum(reserved) AS n FROM runtimes")["n"] == 0
    assert not s.rows("SELECT * FROM jobs")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: begin(s, users[0]), range(2)))
    assert results[0]["job"]["id"] == results[1]["job"]["id"]
    begin(s, users[1])
    with pytest.raises(HTTPException) as error:
        begin(s, users[2])
    assert error.value.detail["code"] == "runtime_capacity_full"
    assert s.one("SELECT count(*) AS n FROM jobs")["n"] == 2


def test_cancel_unclaimed_and_stale_stop(pool):
    s, _ = pool
    uid = account(s)
    result = begin(s, uid)
    with s.tx() as db:
        stopped = stop(s, db, uid, expected_state_version=result["runtime"]["state_version"], start_job_id=result["job"]["id"])
    assert not stopped["accepted"]
    assert s.one("SELECT reserved FROM runtimes WHERE uid=?", (uid,))["reserved"] == 0
    newer = begin(s, uid)
    with pytest.raises(HTTPException):
        with s.tx() as db:
            stop(s, db, uid, expected_state_version=result["runtime"]["state_version"])
    assert s.one("SELECT status FROM jobs WHERE id=?", (newer["job"]["id"],))["status"] == "queued"


def test_manual_pause_survives_disable_enable_and_config(pool):
    s, _ = pool
    uid = account(s)
    s.queue(uid, "pause", reason="admin")
    s.update_user(uid, {"active": False})
    s.update_user(uid, {"active": True})
    s.queue(uid, "apply")
    row = s.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert row["manual_stop_reason"] == "admin" and row["reserved"] == 0 and row["desired"] == 2
    assert not s.rows("SELECT * FROM jobs")
    with pytest.raises(HTTPException):
        begin(s, uid)
    assert begin(s, uid, admin=True)["accepted"]


def test_policy_persistence_and_fingerprint(pool):
    s, args = pool
    assert s.schema_version() == 5
    with s.read() as db:
        validate(db)
    assert Store(*args).on_demand()
    with pytest.raises(ValueError, match="differs"):
        Store(*args, runtime_mode="eager")
    with s.tx() as db:
        db.execute("DROP INDEX jobs_capacity_v5")
    with pytest.raises(ValueError):
        Store(*args)


def test_migration_requires_offline_freeze(pool, tmp_path, monkeypatch):
    _, args = pool
    legacy_args = (tmp_path / "legacy", *args[1:])
    s = Store(*legacy_args)
    assert s.schema_version() == 4
    with pytest.raises(ValueError, match="offline"):
        Store(*legacy_args, runtime_mode="on_demand")
    monkeypatch.setenv("PX_ALLOW_V5_MIGRATION", "1")
    with pytest.raises(ValueError, match="frozen"):
        Store(*legacy_args, runtime_mode="on_demand")
    with s.tx() as db:
        db.execute("UPDATE platform_state SET maintenance_mode='frozen'")
    upgraded = Store(*legacy_args, runtime_mode="on_demand")
    assert upgraded.schema_version() == 5
    with upgraded.read() as db:
        validate(db)
    assert Store(*legacy_args).schema_version() == 5


def test_http_ownership_idempotency_and_worker_capability(pool, monkeypatch):
    from client_helpers import TestClient
    from control.app import create_app
    from control.store import digest, now
    s, _ = pool
    uid = account(s)
    other = account(s, "other")
    with s.tx() as db:
        db.execute("UPDATE users SET must_change=0 WHERE id=?", (uid,))
        db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)", (digest("synthetic-token"), uid, "token", "test", None, now()+600, 1, now()))
    with TestClient(create_app(s)) as client:
        client.headers["Authorization"] = "Bearer synthetic-token"
        prefix = "/api/console/v1/me/runtime"
        assert client.get(prefix).json()["status"] == "unprovisioned"
        assert client.post(prefix + "/start", json={}, headers={"Idempotency-Key": ""}).status_code == 422
        bad = client.post(prefix + "/start", json={"uid": other})
        assert bad.status_code == 400
        headers = {"Idempotency-Key": "synthetic-start-once"}
        first = client.post(prefix + "/start", json={}, headers=headers)
        assert first.status_code == 202, first.text
        repeated = client.post(prefix + "/start", json={}, headers=headers)
        assert repeated.status_code == 202 and repeated.json() == first.json()
        assert client.post(prefix + "/start", json={}).json()["job"]["id"] == first.json()["job"]["id"]
        assert s.one("SELECT reserved FROM runtimes WHERE uid=?", (other,))["reserved"] == 0
        worker = {"X-Worker-Key": s.worker_key, "X-Peixian-Protocol": "2"}
        assert client.post("/internal/worker/claim", headers=worker).status_code == 409
        assert s.one("SELECT count(*) AS n FROM job_attempts")["n"] == 0
        worker["X-Peixian-Capabilities"] = "runtime_pool_v1"
        assert client.post("/internal/worker/claim", headers=worker).status_code == 409
        worker["X-Peixian-Runtime-Mode"] = "on_demand"
        claimed = client.post("/internal/worker/claim", headers=worker)
        assert claimed.status_code == 200 and claimed.json()["job"]
        latest = client.get(prefix).json()
        stop_headers = {"Idempotency-Key": "synthetic-stop-once"}
        stopped = client.post(prefix + "/stop", json={"expected_state_version": latest["state_version"]}, headers=stop_headers)
        assert stopped.status_code == 202
        assert client.post(prefix + "/stop", json={"expected_state_version": latest["state_version"]}, headers=stop_headers).json() == stopped.json()
        assert client.post(prefix + "/stop", json={"expected_state_version": latest["state_version"] + 1}, headers=stop_headers).status_code == 409
        assert s.one("SELECT reserved FROM runtimes WHERE uid=?", (uid,))["reserved"] == 1


def test_metadata_edit_during_unhealthy_capacity_does_not_start(pool):
    s, _ = pool
    with s.tx() as db:
        db.execute("UPDATE platform_state SET capacity_healthy=0")
    uid = account(s)
    s.queue(uid)
    assert s.one("SELECT desired,reserved FROM runtimes WHERE uid=?", (uid,)) == {"desired": 2, "reserved": 0}
    with pytest.raises(HTTPException):
        begin(s, uid)


def test_reserved_failure_is_not_assumed_absent(pool):
    from control.orchestration import Orchestration
    from control.worker_api import runtime_spec
    s, _ = pool
    uid = account(s)
    begin(s, uid)
    job = Orchestration(s).claim(runtime_spec)["job"]
    assert job
    with s.tx() as db:
        db.execute("UPDATE runtimes SET status='failed' WHERE uid=?", (uid,))
        result = stop(s, db, uid)
    assert result["accepted"]
    assert s.one("SELECT reserved FROM runtimes WHERE uid=?", (uid,))["reserved"] == 1


@pytest.mark.parametrize("admin_pause", [False, True])
def test_security_repair_retains_slot_or_respects_admin_pause(pool, admin_pause):
    from control.orchestration import Orchestration
    from control.worker_api import runtime_spec
    from control.runtime_security import block_runtime
    from control.store import ident
    from test_r2_orchestration import applying, observation, complete
    s, _ = pool
    uid = account(s)
    begin(s, uid)
    engine = Orchestration(s)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    engine.boot(job["id"], {"lease": job["lease"], "attempt": job["attempt"], "operation_id": ident(),
        "runtime_id": job["runtime_id"], "gateway_boot_id": "synthetic-gateway", "relay_boot_id": "synthetic-relay"})
    complete(engine, job, ok=True, observation_id=observation(engine, job, running=True, boot="synthetic-gateway"))
    assert s.one("SELECT provisioned_at FROM runtimes WHERE uid=?", (uid,))["provisioned_at"]
    with s.tx() as db:
        block_runtime(s, db, uid)
    s.queue(uid, "pause", reason="security")
    if admin_pause:
        s.queue(uid, "pause", reason="admin")
    pause = engine.claim(runtime_spec)["job"]
    assert pause["action"] == "pause"
    applying(engine, pause)
    complete(engine, pause, ok=True, observation_id=observation(engine, pause))
    row = s.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert row["reserved"] == (0 if admin_pause else 1)
    assert s.one("SELECT count(*) AS n FROM capacity_release_receipts")["n"] == (1 if admin_pause else 0)
    if admin_pause:
        assert row["manual_stop_reason"] == "admin"
        assert engine.claim(runtime_spec)["job"] is None
        with pytest.raises(HTTPException):
            begin(s, uid)
    else:
        repair = engine.claim(runtime_spec)["job"]
        assert repair["reason"] == "security_repair"


@pytest.mark.parametrize("running", [True, False])
def test_metadata_accounts_do_not_consume_reconcile_window_and_drift_freezes(pool, running):
    from control.runtime_pool import inventory_targets, record_inventory
    from control.orchestration import Orchestration
    from control.store import now
    s, _ = pool
    hashed = s.passwords.hash("synthetic-shared-test-password")
    users = [s.create_user_prehashed("metadata-" + str(i), hashed)[0] for i in range(80)]
    engine = Orchestration(s)
    assert engine.reconcile_candidates()["items"] == []
    with s.tx() as db:
        db.execute("UPDATE platform_state SET capacity_healthy=0,freeze_reason='runtime_observation_unknown'")
        snapshot = inventory_targets(db)
    result = record_inventory(s, {"host_boot_id": "synthetic-host", "observed_at": now(), "registry_digest": snapshot["registry_digest"], "complete": True, "resources": []})
    assert result["capacity_healthy"]
    uid = users[0]["id"]
    rid = s.one("SELECT id FROM runtimes WHERE uid=?", (uid,))["id"]
    result = record_inventory(s, {"host_boot_id": "synthetic-host", "observed_at": now(), "registry_digest": snapshot["registry_digest"], "complete": True,
        "resources": [{"uid": uid, "runtime_id": rid, "running": running, "mutation_state": "idle"}]})
    assert not result["capacity_healthy"]
    row = s.one("SELECT reserved,recovery_required,manual_stop_reason FROM runtimes WHERE uid=?", (uid,))
    assert row == {"reserved": 1, "recovery_required": 1, "manual_stop_reason": "admin_review"}
    assert [r["uid"] for r in engine.reconcile_candidates()["items"]] == [uid]


def test_stale_inventory_and_old_schema_validator_rejected(pool):
    from control.runtime_pool import inventory_targets, record_inventory
    from control.migrations_v4 import validate as legacy_validate
    from control.store import now
    s, _ = pool
    with s.read() as db:
        old = inventory_targets(db)
        with pytest.raises(ValueError):
            legacy_validate(db)
    account(s)
    with pytest.raises(HTTPException):
        record_inventory(s, {"host_boot_id": "synthetic-host", "observed_at": now(), "registry_digest": old["registry_digest"], "complete": True, "resources": []})


def test_ordinary_pause_retains_existing_task_egress(pool):
    from control.runtime_security import permit
    from shared.orchestration_config import DEFAULTS
    s, _ = pool
    uid = account(s)
    with s.tx() as db:
        db.execute("UPDATE runtimes SET status='draining',reserved=1,gate_policy='closed',manual_stop_reason='admin',stop_reason='admin',gateway_boot_id='gateway',relay_boot_id='relay' WHERE uid=?", (uid,))
    row = s.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    data = {"protocol_version": 2, "runtime_id": row["id"], "gateway_boot_id": "gateway", "relay_boot_id": "relay", "nonce": "synthetic"}
    result = permit(s, data, s.decrypt(row["spec"])["runtime_key"], DEFAULTS)
    assert not result["intake"] and result["egress"]


def test_stopping_unused_metadata_is_a_noop(pool):
    s, _ = pool
    uid = account(s)
    with s.tx() as db:
        before = public_status(s, db, uid)
        result = stop(s, db, uid, expected_state_version=before["state_version"])
    assert not result["accepted"] and result["runtime"] == before
