"""Current v5 validator. Historical migration bytes and digests remain immutable."""
import sqlite3
from . import migrations_v4
from .migrations_v5 import MIGRATION_ID, SCRIPT_DIGEST, COLUMNS, DDL


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
                or (policy["pool_policy_version"], policy["capacity_wait_enabled"]) not in ((1, 0), (2, 0), (2, 1)) or policy["idle_pause_enabled"]):
            raise ValueError("Unsupported runtime pool policy (idle scheduling disabled)")
    except (KeyError, TypeError, sqlite3.Error) as exc:
        raise ValueError("v5 migration metadata unavailable") from exc

