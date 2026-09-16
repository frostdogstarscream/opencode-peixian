"""Real SQLite tests; all state and credentials are isolated synthetic fixtures."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest

from control.migrations_v4 import MIGRATION_ID, validate
from control.orchestration import Orchestration, hashed
from control.store import Store, now, ident
from control.worker_api import runtime_spec
from shared.orchestration_config import DEFAULTS


@pytest.fixture
def state(tmp_path):
    for name, value in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-credential-123456789"), ("admin", b"synthetic-administrator-password")):
        (tmp_path / name).write_bytes(value)
    args = (tmp_path / "db", tmp_path / "key", tmp_path / "worker", tmp_path / "admin")
    store = Store(*args)
    clock = [now()]
    engine = Orchestration(store, clock=lambda: clock[0], config=DEFAULTS)
    return store, engine, clock, args


def account(state, name="synthetic-user"):
    return state[0].create_user(name, "synthetic-user-password-123")[0]["id"]


def phase(engine, job, target, observation_id=None):
    current = engine.query(job["id"])["job"]
    data = {"lease": job["lease"], "attempt": job["attempt"], "operation_id": ident(),
            "expected_phase": current["phase"], "phase": target}
    if observation_id:
        data["observation_id"] = observation_id
    return engine.phase(job["id"], data)


def observation(engine, job, *, busy=0, running=False, egress=True, complete=True, mutation="idle", revision=None, boot=None):
    current = engine.query(job["id"])["job"]
    data = {"observation_id": ident(), "runtime_id": job["runtime_id"], "job_id": job["id"], "attempt": job["attempt"],
            "lease": job["lease"], "state_version": current["state_version"], "host_boot_id": "synthetic-host",
            "gateway_boot_id": boot or current["gateway_boot_id"] or "absent", "gate_epoch": current["gate_epoch"],
            "observed_at": engine.clock(), "components": dict.fromkeys(("agent", "gateway", "relay"), "running" if running else "stopped"),
            "mutation_state": mutation, "complete": complete, "accepting": False, "egress_closed": egress,
            "activity_count": busy, "applied_revision": job["revision"] if revision is None else revision,
            "spec_digest": job["spec_digest"] if running else None, "evidence_ref": ident()}
    engine.observe(data)
    return data["observation_id"]


def applying(engine, job):
    phase(engine, job, "draining")
    phase(engine, job, "closing", observation(engine, job))
    phase(engine, job, "applying", observation(engine, job))


def complete(engine, job, **kwargs):
    return engine.complete(job["id"], {"lease": job["lease"], "attempt": job["attempt"], "operation_id": ident(), **kwargs})


def test_running_observation_cannot_replace_registered_gateway_boot(state):
    store, engine, clock, args = state
    account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    engine.boot(job["id"], {"lease": job["lease"], "attempt": job["attempt"], "operation_id": ident(),
                          "runtime_id": job["runtime_id"], "gateway_boot_id": "registered", "relay_boot_id": "relay"})
    with pytest.raises(HTTPException, match="registered"):
        observation(engine, job, running=True, boot="different-boot")
    assert engine.query(job["id"])["job"]["gateway_boot_id"] == "registered"
    observation(engine, job, running=True, boot="registered")
    observation(engine, job, boot="absent")


def test_v4_identity_fingerprint_and_nested_atomicity(state):
    store, engine, clock, args = state
    assert store.schema_version() == 4
    with store.read() as db:
        validate(db)
        assert db.execute("SELECT migration_id FROM schema_migrations").fetchone()[0] == MIGRATION_ID
    with pytest.raises(RuntimeError):
        with store.atomic_request():
            user = store.create_user_prehashed("atomic-user", store.passwords.hash("synthetic-password"))[0]
            assert store.user(user["id"])
            raise RuntimeError("synthetic rollback")
    assert store.one("SELECT 1 FROM users WHERE username='atomic-user'") is None
    with store.tx() as db:
        db.execute("DROP INDEX jobs_sched_v4")
    with pytest.raises(ValueError, match="structure"):
        Store(*args)


def test_claim_is_atomic_and_stores_encrypted_frozen_attempt(state):
    store, engine, clock, args = state
    uid = account(state)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: engine.claim(runtime_spec), range(2)))
    claimed = [item for item in results if item["job"]]
    assert len(claimed) == 1
    value = claimed[0]
    attempt = store.one("SELECT * FROM job_attempts")
    assert attempt["spec_digest"] == hashed(value["spec"])
    assert store.decrypt(attempt["spec_ciphertext"]) == value["spec"]
    assert value["job"]["lease"] not in json.dumps(attempt)
    assert engine.query(value["job"]["id"])["attempt"]["revision"] == value["job"]["revision"]


def test_defer_is_fifo_due_and_receipt_replay_does_not_extend_delay(state):
    store, engine, clock, args = state
    first_uid = account(state)
    first = engine.claim(runtime_spec)["job"]
    phase(engine, first, "draining")
    obs = observation(engine, first, busy=1, running=True, egress=False)
    data = {"lease": first["lease"], "attempt": first["attempt"], "operation_id": "defer-one", "deferred": True, "defer_reason": "runtime_busy", "observation_id": obs}
    receipt = engine.complete(first["id"], data)
    assert receipt["not_before"] == clock[0] + 15
    second_uid = account(state, "second-user")
    assert engine.claim(runtime_spec)["job"]["uid"] == second_uid
    clock[0] += 16
    second_attempt = engine.claim(runtime_spec)["job"]
    assert second_attempt["uid"] == first_uid and second_attempt["attempt"] == 2
    assert engine.complete(first["id"], data) == receipt
    assert store.one("SELECT defer_count FROM jobs WHERE id=?", (first["id"],))["defer_count"] == 1
    with pytest.raises(HTTPException):
        engine.complete(first["id"], {**data, "observation_id": "different"})


def test_closing_requires_fresh_both_direction_gate_confirmation(state):
    store, engine, clock, args = state
    account(state)
    job = engine.claim(runtime_spec)["job"]
    phase(engine, job, "draining")
    obs = observation(engine, job)
    clock[0] += 4
    with pytest.raises(HTTPException, match="fresh"):
        phase(engine, job, "closing", obs)
    closing = phase(engine, job, "closing", observation(engine, job))
    assert closing["gate_action"] == "close"
    with pytest.raises(HTTPException, match="egress"):
        phase(engine, job, "applying", observation(engine, job, egress=False))
    phase(engine, job, "applying", observation(engine, job))
    assert engine.query(job["id"])["job"]["phase"] == "applying"


def test_applying_recovery_never_replaces_original_desired_snapshot(state):
    store, engine, clock, args = state
    uid = account(state)
    original = engine.claim(runtime_spec)
    applying(engine, original["job"])
    with store.tx() as db:
        db.execute("UPDATE runtimes SET desired=desired+1 WHERE uid=?", (uid,))
    clock[0] += 91
    recovered = engine.claim(runtime_spec)
    assert recovered["job"]["phase"] == "reconciling"
    assert recovered["job"]["recovery_of_attempt"] == 1
    assert recovered["spec"] == original["spec"]
    assert recovered["job"]["revision"] == 1
    with pytest.raises(HTTPException):
        engine.heartbeat(original["job"]["id"], {"lease": original["job"]["lease"], "attempt": 1})


def test_complete_saves_actual_revision_and_ensures_without_desired_increment(state):
    store, engine, clock, args = state
    uid = account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    with store.tx() as db:
        db.execute("UPDATE runtimes SET desired=3 WHERE uid=?", (uid,))
    result = complete(engine, job, ok=True, observation_id=observation(engine, job, running=True))
    row = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert row["revision"] == 1 and row["desired"] == 3
    assert row["gate_policy"] == "reopen_check"
    assert store.one("SELECT count(*) n FROM jobs WHERE status='queued'")["n"] == 1
    assert "spec" not in json.dumps(result)


def test_unexpected_restart_recovers_applied_snapshot_before_queued_desired(state):
    store, engine, clock, args = state
    uid = account(state)
    original = engine.claim(runtime_spec)
    applying(engine, original["job"])
    complete(engine, original["job"], ok=True, observation_id=observation(engine, original["job"], running=True))
    queued = store.queue(uid)
    with store.tx() as db:
        db.execute("UPDATE runtimes SET recovery_required=1,gate_policy='closed',gate_epoch=gate_epoch+1,state_version=state_version+1 WHERE uid=?", (uid,))
    recovered = engine.claim(runtime_spec)
    assert recovered["job"]["id"] != queued["id"]
    assert recovered["job"]["reason"] == "runtime_reconcile"
    assert recovered["job"]["phase"] == "reconciling"
    assert recovered["spec"] == original["spec"]
    assert recovered["job"]["revision"] == 1 and recovered["job"]["desired"] == 2
    complete(engine, recovered["job"], ok=True, observation_id=observation(engine, recovered["job"], running=True))
    next_job = engine.claim(runtime_spec)["job"]
    assert next_job["id"] == queued["id"] and next_job["revision"] == 2
    assert store.one("SELECT desired,recovery_required FROM runtimes WHERE uid=?", (uid,)) == {"desired": 2, "recovery_required": 0}


def test_permit_recovery_reopens_without_desired_bump(state):
    store, engine, clock, args = state
    uid = account(state)
    initial = engine.claim(runtime_spec)["job"]
    applying(engine, initial)
    complete(engine, initial, ok=True, observation_id=observation(engine, initial, running=True))
    before = store.one("SELECT desired,gate_epoch FROM runtimes WHERE uid=?", (uid,))
    with store.tx() as db:
        db.execute("UPDATE runtimes SET recovery_required=1,gate_policy='closed',gate_epoch=gate_epoch+1,state_version=state_version+1 WHERE uid=?", (uid,))
    recovered = engine.claim(runtime_spec)["job"]
    assert recovered["gate_epoch"] > before["gate_epoch"]
    complete(engine, recovered, ok=True, observation_id=observation(engine, recovered, running=True))
    row = store.one("SELECT desired,revision,recovery_required,gate_policy FROM runtimes WHERE uid=?", (uid,))
    assert row == {"desired": before["desired"], "revision": before["desired"], "recovery_required": 0, "gate_policy": "reopen_check"}
    assert engine.claim(runtime_spec)["job"] is None
    with pytest.raises(HTTPException, match="explicit attempt"):
        engine.query(initial["id"], operation_id="receipt-without-attempt")


@pytest.mark.parametrize("disabled,has_applied", [(False, True), (True, True), (False, False)])
def test_security_superseded_mutation_stops_before_fresh_authorized_restart(state, disabled, has_applied):
    from control.runtime_security import block_runtime
    store, engine, clock, args = state
    uid = account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    if has_applied:
        complete(engine, job, ok=True, observation_id=observation(engine, job, running=True))
        store.queue(uid)
        job = engine.claim(runtime_spec)["job"]
        applying(engine, job)
    with store.tx() as db:
        if disabled:
            db.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
        block_runtime(store, db, uid, reason="account_disabled" if disabled else "authorization_revoked")
        db.execute("UPDATE runtimes SET desired=desired+1 WHERE uid=?", (uid,))
    complete(engine, job, ok=False, error="synthetic_unknown_result")
    assert store.one("SELECT recovery_required FROM jobs WHERE id=?", (job["id"],))["recovery_required"] == 1
    stopping = engine.claim(runtime_spec)["job"]
    assert stopping["action"] == "pause" and stopping["reason"] == "security"
    applying(engine, stopping)
    complete(engine, stopping, ok=True, observation_id=observation(engine, stopping))
    assert store.one("SELECT status,recovery_required FROM jobs WHERE id=?", (job["id"],)) == {"status": "cancelled", "recovery_required": 0}
    replacement = engine.claim(runtime_spec)["job"]
    if disabled or not has_applied:
        assert replacement is None
        assert store.one("SELECT reserved,status FROM runtimes WHERE uid=?", (uid,)) == {"reserved": 0, "status": "paused"}
    else:
        assert replacement["action"] == "resume" and replacement["authorization_version"] == 2
        applying(engine, replacement)
        complete(engine, replacement, ok=True, observation_id=observation(engine, replacement, running=True))
        current = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
        assert current["security_blocked"] == 0 and current["revision"] == current["desired"]
        assert current["gate_policy"] == "reopen_check"


@pytest.mark.parametrize("expire", [False, True])
def test_security_cancel_before_mutation_requeues_without_fake_recovery(state, expire):
    from control.runtime_security import block_runtime
    store, engine, clock, args = state
    uid = account(state)
    job = engine.claim(runtime_spec)["job"]
    phase(engine, job, "draining")
    with store.tx() as db:
        block_runtime(store, db, uid)
        db.execute("UPDATE runtimes SET cancellation_confirmed=1,desired=2 WHERE uid=?", (uid,))
    if expire:
        clock[0] += 91
    else:
        complete(engine, job, ok=False, error="security_cancelled")
    replacement = engine.claim(runtime_spec)["job"]
    assert replacement["id"] != job["id"] and replacement["revision"] == 2
    assert replacement["phase"] == "claimed"
    assert store.one("SELECT status,recovery_required FROM jobs WHERE id=?", (job["id"],)) == {"status": "cancelled", "recovery_required": 0}


def test_inconclusive_recovery_is_retained_for_operator_instead_of_reclaimed(state):
    store, engine, clock, args = state
    account(state)
    original = engine.claim(runtime_spec)["job"]
    applying(engine, original)
    complete(engine, original, ok=False, error="first_unknown")
    recovery = engine.claim(runtime_spec)["job"]
    assert recovery["phase"] == "reconciling"
    complete(engine, recovery, ok=False, error="still_unknown")
    assert engine.claim(runtime_spec)["job"] is None
    row = store.one("SELECT status,recovery_required FROM jobs WHERE id=?", (original["id"],))
    assert row == {"status": "failed", "recovery_required": 1}


@pytest.mark.parametrize("case", ["no_evidence", "partial", "mutation_unknown"])
def test_failure_with_unknown_resources_preserves_slot_and_recovery(state, case):
    store, engine, clock, args = state
    uid = account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    kwargs = {}
    if case != "no_evidence":
        if case == "partial":
            # Incomplete observation cannot be used as completion proof at all.
            obs = observation(engine, job, complete=False)
            with pytest.raises(HTTPException):
                complete(engine, job, ok=False, observation_id=obs)
            return
        kwargs["observation_id"] = observation(engine, job, mutation="unknown")
    complete(engine, job, ok=False, **kwargs)
    assert store.one("SELECT reserved,recovery_required FROM runtimes WHERE uid=?", (uid,)) == {"reserved": 1, "recovery_required": 1}
    assert engine.query(job["id"])["job"]["phase"] == "reconciling"


def test_pause_releases_once_and_preserves_paused_data(state):
    store, engine, clock, args = state
    uid = account(state)
    with store.tx() as db:
        db.execute("UPDATE jobs SET action='pause' WHERE uid=?", (uid,))
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    obs = observation(engine, job)
    body = {"lease": job["lease"], "attempt": job["attempt"], "operation_id": "stop-once", "ok": True, "observation_id": obs}
    result = engine.complete(job["id"], body)
    assert engine.complete(job["id"], body) == result
    assert store.one("SELECT reserved,status FROM runtimes WHERE uid=?", (uid,)) == {"reserved": 0, "status": "paused"}
    assert store.one("SELECT count(*) n FROM capacity_release_receipts")["n"] == 1


def test_maintenance_persists_and_rejects_ordinary_claim_or_create(state):
    store, engine, clock, args = state
    account(state)
    engine.maintenance("frozen", 0, "synthetic-maintainer")
    assert engine.claim(runtime_spec)["job"] is None
    reopened = Store(*args)
    assert reopened.maintenance_status()["maintenance_mode"] == "frozen"
    with pytest.raises(ValueError):
        reopened.create_user("refused-user", "synthetic-password")


def test_unknown_reconciliation_freezes_capacity_and_never_releases(state):
    store, engine, clock, args = state
    account(state)
    item = engine.reconcile_candidates()["items"][0]
    data = {"observation_id": ident(), "runtime_id": item["runtime_id"], "state_version": item["state_version"], "host_boot_id": "synthetic-host", "observed_at": clock[0], "components": dict.fromkeys(("agent", "gateway", "relay"), "unknown"), "mutation_state": "unknown", "complete": False, "evidence_ref": ident()}
    response = engine.reconcile(data)
    assert not response["released"] and not response["capacity_healthy"]
    assert store.one("SELECT reserved FROM runtimes")["reserved"] == 1


def test_pending_start_without_containers_still_owns_reserved_slot(state):
    store, engine, clock, args = state
    account(state)
    item = engine.reconcile_candidates()["items"][0]
    data = {"observation_id": ident(), "runtime_id": item["runtime_id"], "state_version": item["state_version"], "host_boot_id": "synthetic-host", "observed_at": clock[0], "components": dict.fromkeys(("agent", "gateway", "relay"), "stopped"), "mutation_state": "idle", "complete": True, "evidence_ref": ident()}
    assert engine.reconcile(data)["released"] is False
    assert store.one("SELECT reserved FROM runtimes")["reserved"] == 1


def test_receipts_remain_pinned_until_recovery_is_closed(state):
    store, engine, clock, args = state
    account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    complete(engine, job, ok=False)
    before = store.one("SELECT count(*) n FROM worker_operation_receipts")["n"]
    clock[0] += DEFAULTS["receipt_retention_seconds"] + 1
    assert engine.cleanup_receipts()["deleted"] == 0
    assert store.one("SELECT count(*) n FROM worker_operation_receipts")["n"] == before


def test_boot_registration_deduplicates_and_query_never_exposes_private_snapshot(state):
    store, engine, clock, args = state
    account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    body = {"lease": job["lease"], "attempt": job["attempt"], "operation_id": "new-boot", "runtime_id": job["runtime_id"], "gateway_boot_id": "new-gateway", "relay_boot_id": "new-relay"}
    reply = engine.boot(job["id"], body)
    assert engine.boot(job["id"], body) == reply
    query = engine.query(job["id"], job["attempt"], "new-boot")
    assert query["receipt"] == reply and query["job"]["gateway_boot_id"] == "new-gateway"
    serialized = json.dumps(query)
    assert "spec_ciphertext" not in serialized and job["lease"] not in serialized


def test_unregistered_v4_identity_is_rejected_even_with_user_version_4(state):
    store, engine, clock, args = state
    with store.tx() as db:
        db.execute("DELETE FROM schema_migrations")
    with pytest.raises(ValueError, match="identity"):
        Store(*args)


def test_real_v3_migration_requires_window_and_maps_unknown_running_conservatively(state, monkeypatch):
    from r2_helpers import strip_v4
    store, engine, clock, args = state
    uid = account(state)
    strip_v4(store)
    with store.tx() as db:
        db.execute("UPDATE jobs SET status='running',lease='synthetic-old-lease',heartbeat=?", (clock[0],))
        db.execute("UPDATE runtimes SET status='failed',reserved=1")
    with pytest.raises(ValueError, match="offline"):
        Store(*args)
    assert store.schema_version() == 3
    monkeypatch.setenv("PX_ALLOW_V4_MIGRATION", "1")
    migrated = Store(*args)
    assert migrated.schema_version() == 4
    assert migrated.maintenance_status()["maintenance_mode"] == "frozen"
    runtime = migrated.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    assert runtime["reserved"] == runtime["recovery_required"] == 1
    assert migrated.one("SELECT phase FROM jobs")["phase"] == "reconciling"
    assert Orchestration(migrated).claim(runtime_spec)["job"] is None


def test_migration_interruption_rolls_back_schema_state_and_version(state, monkeypatch):
    from r2_helpers import strip_v4
    import control.migrations_v4 as migration
    store, engine, clock, args = state
    account(state)
    strip_v4(store)
    monkeypatch.setenv("PX_ALLOW_V4_MIGRATION", "1")
    original = migration.validate
    def interrupt(db):
        original(db)
        raise RuntimeError("synthetic migration interruption")
    monkeypatch.setattr(migration, "validate", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        Store(*args)
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='job_attempts'").fetchone() is None
        assert "phase" not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}


def test_security_change_cannot_be_cleared_by_old_attempt(state):
    from control.runtime_security import block_runtime
    store, engine, clock, args = state
    uid = account(state)
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    with store.tx() as db:
        block_runtime(store, db, uid, reason="authorization_revoked")
        db.execute("UPDATE runtimes SET cancellation_confirmed=1 WHERE uid=?", (uid,))
    complete(engine, job, ok=True, observation_id=observation(engine, job, running=True))
    assert store.one("SELECT security_blocked,gate_policy FROM runtimes")== {"security_blocked": 1, "gate_policy": "closed"}


def test_current_authorization_repair_clears_only_after_version_evidence(state):
    from control.runtime_security import block_runtime
    store, engine, clock, args = state
    uid = account(state)
    with store.tx() as db:
        block_runtime(store, db, uid, reason="authorization_revoked")
        db.execute("UPDATE runtimes SET cancellation_confirmed=1 WHERE uid=?", (uid,))
    job = engine.claim(runtime_spec)["job"]
    applying(engine, job)
    complete(engine, job, ok=True, observation_id=observation(engine, job, running=True))
    assert store.one("SELECT security_blocked,gate_policy FROM runtimes")== {"security_blocked": 0, "gate_policy": "reopen_check"}


def test_disable_before_initial_provision_cancels_unclaimed_start_and_pause_releases(state):
    store, engine, clock, args = state
    uid = account(state)
    store.update_user(uid, {"active": False})
    assert store.one("SELECT status FROM jobs WHERE action='provision'")["status"] == "cancelled"
    job = engine.claim(runtime_spec)["job"]
    assert job["action"] == "pause"
    applying(engine, job)
    complete(engine, job, ok=True, observation_id=observation(engine, job))
    assert store.one("SELECT reserved,status FROM runtimes") == {"reserved": 0, "status": "paused"}


def test_apply_deadline_requires_operator_resolution_and_never_resets_drain_age(state):
    store, engine, clock, args = state
    uid = account(state)
    with store.tx() as db:
        db.execute("UPDATE jobs SET action='apply'")
        db.execute("UPDATE runtimes SET status='ready',revision=1,desired=2")
    job = engine.claim(runtime_spec)["job"]
    phase(engine, job, "draining")
    first = clock[0]
    clock[0] += 301
    # Keep the leased worker alive while the fake clock advances.
    with store.tx() as db:
        db.execute("UPDATE jobs SET heartbeat=?", (clock[0],))
    complete(engine, job, deferred=True, defer_reason="runtime_busy", observation_id=observation(engine, job, busy=1, running=True))
    assert store.one("SELECT gate_policy,status FROM runtimes") == {"gate_policy": "closed", "status": "draining"}
    clock[0] = first + 901
    assert engine.claim(runtime_spec)["job"] is None
    engine.resolve_drain(uid, "continue", "synthetic-super-admin")
    current = store.one("SELECT drain_started_at,observation_deadline FROM jobs")
    assert current["drain_started_at"] == first and current["observation_deadline"] == clock[0] + 900
    assert engine.claim(runtime_spec)["job"] is not None


def test_security_stop_precedes_earlier_ordinary_job(state):
    store, engine, clock, args = state
    earlier = account(state, "earlier-ordinary")
    stopped = account(state, "later-security-stop")
    store.update_user(stopped, {"active": False})
    claim = engine.claim(runtime_spec)["job"]
    assert claim["uid"] == stopped and claim["action"] == "pause"
    assert engine.claim(runtime_spec)["job"]["uid"] == earlier


def test_frozen_refuses_recovery_but_repair_only_can_claim_original_snapshot(state):
    store, engine, clock, args = state
    account(state)
    original = engine.claim(runtime_spec)
    applying(engine, original["job"])
    engine.maintenance("frozen", 0, "synthetic-maintainer")
    clock[0] += 91
    assert engine.claim(runtime_spec)["job"] is None
    engine.maintenance("repair_only", store.maintenance_status()["state_version"], "synthetic-maintainer")
    recovered = engine.claim(runtime_spec)
    assert recovered["job"]["phase"] == "reconciling" and recovered["spec"] == original["spec"]
