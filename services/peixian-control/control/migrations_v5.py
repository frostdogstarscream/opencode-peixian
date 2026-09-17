"""Complete pool storage contract. No queue promotion or idle scheduling in 7A."""
import hashlib
import os
import sqlite3
from pathlib import Path

from . import migrations_v4

MIGRATION_ID = "control.runtime-pool.v5.1"
SCRIPT_DIGEST = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
COLUMNS = {
    "runtimes": {
        "manual_stop_reason": "TEXT NOT NULL DEFAULT 'none'",
        "provisioned_at": "INTEGER",
        "last_activity": "INTEGER",
        "activity_version": "INTEGER NOT NULL DEFAULT 0",
        "ready_since": "INTEGER",
        "activity_boot_id": "TEXT",
    },
    "jobs": {
        "capacity_expires_at": "INTEGER",
        "capacity_reserved_at": "INTEGER",
        "idle_activity_version": "INTEGER",
        "idle_gateway_boot_id": "TEXT",
        "idle_observed_at": "INTEGER",
    },
    "platform_state": {
        "runtime_mode": "TEXT NOT NULL DEFAULT 'eager'",
        "capacity_wait_enabled": "INTEGER NOT NULL DEFAULT 0",
        "idle_pause_enabled": "INTEGER NOT NULL DEFAULT 0",
        "pool_policy_version": "INTEGER NOT NULL DEFAULT 1",
    },
}
DDL = {
    "runtime_pool_inventory": "CREATE TABLE runtime_pool_inventory(id INTEGER PRIMARY KEY CHECK(id=1),host_boot_id TEXT NOT NULL,observed_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,registry_digest TEXT NOT NULL,complete INTEGER NOT NULL)",
    "jobs_one_start_v5": "CREATE UNIQUE INDEX jobs_one_start_v5 ON jobs(uid) WHERE action IN ('provision','resume') AND status IN ('waiting_capacity','queued','running')",
    "jobs_capacity_v5": "CREATE INDEX jobs_capacity_v5 ON jobs(status,enqueue_seq,capacity_expires_at)",
}


def validate(db):
    try:
        old = db.execute("SELECT * FROM schema_migrations WHERE migration_id=?", (migrations_v4.MIGRATION_ID,)).fetchone()
        row = db.execute("SELECT * FROM schema_migrations WHERE migration_id=?", (MIGRATION_ID,)).fetchone()
        if (not old or old["from_version"] != 3 or old["to_version"] != 4
                or old["script_digest"] != migrations_v4.SCRIPT_DIGEST):
            raise ValueError("v5 historical migration identity mismatch")
        if not row or row["from_version"] != 4 or row["to_version"] != 5 or row["script_digest"] != SCRIPT_DIGEST:
            raise ValueError("v5 migration identity mismatch")
        for table, fields in COLUMNS.items():
            actual = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
            inherited = migrations_v4.JOBS if table == "jobs" else migrations_v4.RUNTIMES if table == "runtimes" else {}
            if not (fields.keys() | inherited.keys()) <= actual:
                raise ValueError("v5 structure incomplete")
        for name, sql in DDL.items():
            actual = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if not actual or actual[0] != sql:
                raise ValueError("v5 index contract mismatch")
        if row["structure_digest"] != migrations_v4.structure_digest(db):
            raise ValueError("v5 schema fingerprint mismatch")
        policy = db.execute("SELECT * FROM platform_state WHERE id=1").fetchone()
        if (not policy or policy["runtime_mode"] not in ("eager", "on_demand")
                or policy["pool_policy_version"] != 1 or policy["capacity_wait_enabled"] or policy["idle_pause_enabled"]):
            raise ValueError("Unsupported runtime pool policy (7B/7C disabled)")
    except (KeyError, TypeError, sqlite3.Error) as exc:
        raise ValueError("v5 migration metadata unavailable") from exc


def migrate(db, *, fresh, timestamp, mode):
    migrations_v4.validate(db)
    if not fresh:
        if os.getenv("PX_ALLOW_V5_MIGRATION") != "1":
            raise ValueError("v5 requires an approved offline migration window")
        platform = db.execute("SELECT * FROM platform_state WHERE id=1").fetchone()
        if platform["maintenance_mode"] != "frozen":
            raise ValueError("v5 migration requires frozen maintenance")
        if (db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone()
                or db.execute("SELECT 1 FROM job_attempts WHERE outcome IS NULL").fetchone()):
            raise ValueError("v5 migration requires resolved execution responsibilities")
    for table, fields in COLUMNS.items():
        for name, definition in fields.items():
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    for sql in DDL.values():
        db.execute(sql)
    db.execute("UPDATE runtimes SET manual_stop_reason=CASE WHEN stop_reason IN ('admin','admin_review') THEN stop_reason ELSE 'none' END,provisioned_at=CASE WHEN revision>0 THEN updated ELSE NULL END")
    db.execute("UPDATE platform_state SET runtime_mode=? WHERE id=1", (mode,))
    db.execute("INSERT INTO schema_migrations(migration_id,from_version,to_version,script_digest,structure_digest,created) VALUES(?,4,5,?,?,?)",
               (MIGRATION_ID, SCRIPT_DIGEST, migrations_v4.structure_digest(db), timestamp))
    validate(db)
    db.execute("PRAGMA user_version=5")
