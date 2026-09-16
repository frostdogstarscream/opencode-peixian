"""Atomic v3 -> v4 migration. Existing databases require an explicit offline window."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

MIGRATION_ID = "control.runtime-orchestration.v4.1"
JOBS = {
    "not_before": "INTEGER NOT NULL DEFAULT 0", "phase": "TEXT NOT NULL DEFAULT 'queued'",
    "defer_count": "INTEGER NOT NULL DEFAULT 0", "drain_started_at": "INTEGER",
    "reason": "TEXT NOT NULL DEFAULT 'normal'", "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
    "recovery_required": "INTEGER NOT NULL DEFAULT 0", "previous_status": "TEXT",
    "enqueue_seq": "INTEGER NOT NULL DEFAULT 0",
    "observation_deadline": "INTEGER",
}
RUNTIMES = {
    "state_version": "INTEGER NOT NULL DEFAULT 0", "gate_epoch": "INTEGER NOT NULL DEFAULT 0",
    "drain_job_id": "TEXT", "recovery_required": "INTEGER NOT NULL DEFAULT 0",
    "stop_reason": "TEXT NOT NULL DEFAULT 'none'", "security_blocked": "INTEGER NOT NULL DEFAULT 0",
    "gate_policy": "TEXT NOT NULL DEFAULT 'closed'", "gateway_boot_id": "TEXT", "relay_boot_id": "TEXT",
    "applied_spec_ciphertext": "TEXT", "applied_spec_digest": "TEXT",
    "authorization_version": "INTEGER NOT NULL DEFAULT 1", "security_intent_id": "TEXT",
    "cancel_requested_at": "INTEGER", "security_confirmed_at": "INTEGER",
    "cancellation_confirmed": "INTEGER NOT NULL DEFAULT 0",
    "drain_intent_id": "TEXT",
}
DDL = [
    "CREATE TABLE job_attempts(job_id TEXT NOT NULL REFERENCES jobs(id),attempt INTEGER NOT NULL CHECK(attempt>0),lease_hash TEXT NOT NULL,phase TEXT NOT NULL,revision INTEGER NOT NULL,authorization_version INTEGER NOT NULL,spec_ciphertext TEXT,spec_digest TEXT,recovery_of_attempt INTEGER,outcome TEXT,outcome_hash TEXT,created INTEGER NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(job_id,attempt))",
    "CREATE TABLE request_idempotency(uid TEXT NOT NULL,action TEXT NOT NULL,request_key TEXT NOT NULL,request_hash TEXT NOT NULL,resource_id TEXT,response_ref TEXT,response_ciphertext TEXT,created INTEGER NOT NULL,expires INTEGER NOT NULL,PRIMARY KEY(uid,action,request_key))",
    "CREATE TABLE worker_operation_receipts(job_id TEXT NOT NULL,attempt INTEGER NOT NULL,operation_id TEXT NOT NULL,request_hash TEXT NOT NULL,lease_hash TEXT NOT NULL,response TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER NOT NULL,PRIMARY KEY(job_id,attempt,operation_id),FOREIGN KEY(job_id,attempt) REFERENCES job_attempts(job_id,attempt))",
    "CREATE TABLE platform_state(id INTEGER PRIMARY KEY CHECK(id=1),maintenance_mode TEXT NOT NULL CHECK(maintenance_mode IN ('normal','frozen','repair_only')),state_version INTEGER NOT NULL DEFAULT 0,capacity_healthy INTEGER NOT NULL DEFAULT 1,freeze_reason TEXT,reconcile_generation INTEGER NOT NULL DEFAULT 0,enqueue_seq INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL)",
    "CREATE TABLE runtime_observations(observation_id TEXT PRIMARY KEY,runtime_id TEXT NOT NULL,job_id TEXT,attempt INTEGER,state_version INTEGER NOT NULL,host_boot_id TEXT NOT NULL,gateway_boot_id TEXT NOT NULL,gate_epoch INTEGER NOT NULL,observed_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,complete INTEGER NOT NULL,components TEXT NOT NULL,mutation_state TEXT NOT NULL,accepting INTEGER NOT NULL,egress_closed INTEGER NOT NULL,activity_count INTEGER,applied_revision INTEGER NOT NULL,spec_digest TEXT,evidence_ref TEXT NOT NULL,classification TEXT NOT NULL,request_hash TEXT NOT NULL,created INTEGER NOT NULL)",
    "CREATE TABLE capacity_release_receipts(operation_id TEXT PRIMARY KEY,runtime_id TEXT NOT NULL,request_hash TEXT NOT NULL,response TEXT NOT NULL,created INTEGER NOT NULL)",
    "CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY,from_version INTEGER NOT NULL,to_version INTEGER NOT NULL,script_digest TEXT NOT NULL,structure_digest TEXT NOT NULL,created INTEGER NOT NULL)",
    "CREATE INDEX jobs_sched_v4 ON jobs(status,not_before,enqueue_seq)",
    "CREATE UNIQUE INDEX jobs_one_running_v4 ON jobs(uid) WHERE status='running'",
    "CREATE UNIQUE INDEX jobs_enqueue_seq_v4 ON jobs(enqueue_seq) WHERE enqueue_seq>0",
    "CREATE INDEX observations_runtime_v4 ON runtime_observations(runtime_id,observed_at)",
    "CREATE INDEX receipts_expiry_v4 ON worker_operation_receipts(expires)",
    "CREATE INDEX request_idempotency_expiry_v4 ON request_idempotency(expires)",
    "CREATE TRIGGER jobs_enqueue_v4 AFTER INSERT ON jobs WHEN NEW.enqueue_seq=0 BEGIN UPDATE platform_state SET enqueue_seq=enqueue_seq+1 WHERE id=1; UPDATE jobs SET enqueue_seq=(SELECT enqueue_seq FROM platform_state WHERE id=1) WHERE id=NEW.id; END",
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


SCRIPT_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def structure_digest(db):
    rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    return hashlib.sha256(canonical([tuple(row) for row in rows]).encode()).hexdigest()


def validate(db):
    try:
        row = db.execute("SELECT * FROM schema_migrations WHERE migration_id=?", (MIGRATION_ID,)).fetchone()
        if not row or row["from_version"] != 3 or row["to_version"] != 4 or row["script_digest"] != SCRIPT_DIGEST:
            raise ValueError("v4 migration identity is incomplete")
        for table, fields in (("jobs", JOBS), ("runtimes", RUNTIMES)):
            columns = {item["name"] for item in db.execute(f"PRAGMA table_info({table})")}
            if not fields.keys() <= columns:
                raise ValueError("v4 structure is incomplete")
        for sql in DDL:
            name = re.search(r"CREATE (?:UNIQUE )?(?:TABLE|INDEX|TRIGGER) (\w+)", sql).group(1)
            actual = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if not actual or " ".join(actual[0].split()) != " ".join(sql.split()):
                raise ValueError("v4 migration structure mismatch")
        if row["structure_digest"] != structure_digest(db):
            raise ValueError("v4 schema fingerprint mismatch")
        if db.execute("SELECT count(*) FROM platform_state WHERE id=1").fetchone()[0] != 1:
            raise ValueError("v4 maintenance state missing")
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("v4 migration metadata unavailable") from None


def migrate(store, db, *, fresh, timestamp):
    if not fresh and os.getenv("PX_ALLOW_V4_MIGRATION") != "1":
        raise ValueError("v3 requires an approved offline v4 migration window (PX_ALLOW_V4_MIGRATION=1)")
    if db.execute("SELECT uid FROM jobs WHERE status='running' GROUP BY uid HAVING count(*)>1").fetchone():
        raise ValueError("v4 preflight: multiple running jobs for one runtime")
    if db.execute("SELECT 1 FROM jobs j LEFT JOIN runtimes r ON r.uid=j.uid WHERE r.uid IS NULL").fetchone():
        raise ValueError("v4 preflight: orphan job")
    if db.execute("SELECT 1 FROM runtimes r LEFT JOIN users u ON u.id=r.uid WHERE u.id IS NULL").fetchone():
        raise ValueError("v4 preflight: orphan runtime")
    if db.execute("SELECT 1 FROM jobs WHERE status NOT IN ('queued','running','succeeded','failed') OR action NOT IN ('apply','provision','resume','pause')").fetchone():
        raise ValueError("v4 preflight: unknown job state")
    if db.execute("SELECT 1 FROM runtimes WHERE status NOT IN ('pending','provisioning','ready','updating','paused','failed') OR reserved NOT IN (0,1)").fetchone():
        raise ValueError("v4 preflight: unknown runtime state")
    for table, fields in (("jobs", JOBS), ("runtimes", RUNTIMES)):
        for name, definition in fields.items():
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    for sql in DDL:
        db.execute(sql)
    db.execute("INSERT INTO platform_state(id,maintenance_mode,updated) VALUES(1,?,?)", ("normal" if fresh else "frozen", timestamp))
    jobs = db.execute("SELECT id FROM jobs ORDER BY created,rowid").fetchall()
    for sequence, job in enumerate(jobs, 1):
        db.execute("UPDATE jobs SET enqueue_seq=? WHERE id=?", (sequence, job[0]))
    db.execute("UPDATE platform_state SET enqueue_seq=? WHERE id=1", (len(jobs),))
    db.execute("UPDATE jobs SET previous_status=status,recovery_required=1,phase='reconciling',status='queued',lease=NULL,heartbeat=NULL WHERE status='running'")
    db.execute("UPDATE jobs SET phase='finished' WHERE status IN ('succeeded','failed')")
    db.execute("UPDATE runtimes SET stop_reason='admin_review' WHERE status='paused'")
    db.execute("UPDATE runtimes SET recovery_required=1,gate_policy='closed' WHERE (status='failed' AND reserved=1) OR uid IN (SELECT uid FROM jobs WHERE recovery_required=1)")
    for row in db.execute("SELECT uid,spec FROM runtimes").fetchall():
        spec = store.decrypt(row["spec"])
        spec.setdefault("runtime_key", secrets.token_urlsafe(48))
        spec.setdefault("relay_management_key", secrets.token_urlsafe(48))
        db.execute("UPDATE runtimes SET spec=? WHERE uid=?", (store.encrypt(spec), row["uid"]))
    db.execute("INSERT INTO schema_migrations VALUES(?,3,4,?,?,?)", (MIGRATION_ID, SCRIPT_DIGEST, structure_digest(db), timestamp))
    validate(db)
    db.execute("PRAGMA user_version=4")
