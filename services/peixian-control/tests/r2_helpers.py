"""Synthetic compatibility fixtures, never imported by deployment code."""
import re

from control.migrations_v4 import DDL, JOBS, RUNTIMES
from control.orchestration import Orchestration
from control.store import ident


def strip_v4(store):
    """Construct an actual old schema in an already-isolated test database."""
    with store.tx() as db:
        for sql in DDL:
            match = re.match(r"CREATE (?:UNIQUE )?(INDEX|TRIGGER) (\w+)", sql)
            if match:
                db.execute(f"DROP {match[1]} {match[2]}")
        tables = [re.match(r"CREATE TABLE (\w+)", sql)[1] for sql in DDL if sql.startswith("CREATE TABLE")]
        tables.remove("worker_operation_receipts")
        for table in ["worker_operation_receipts", *tables]:
            db.execute(f"DROP TABLE {table}")
        for table, fields in (("jobs", JOBS), ("runtimes", RUNTIMES)):
            for name in fields:
                db.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
        db.execute("PRAGMA user_version=3")


def observe(store, job, *, stopped=False):
    engine = Orchestration(store)
    current = engine.query(job["id"])["job"]
    observation_id = ident()
    engine.observe({"observation_id": observation_id, "runtime_id": job["runtime_id"], "job_id": job["id"],
                    "lease": job["lease"], "attempt": job["attempt"], "state_version": current["state_version"],
                    "host_boot_id": "synthetic-host", "gateway_boot_id": current["gateway_boot_id"] or "absent",
                    "gate_epoch": current["gate_epoch"], "observed_at": engine.clock(),
                    "components": dict.fromkeys(("agent", "gateway", "relay"), "stopped" if stopped else "running"),
                    "mutation_state": "idle", "complete": True, "accepting": False, "egress_closed": True,
                    "activity_count": 0, "applied_revision": job["revision"], "spec_digest": None if stopped else job["spec_digest"],
                    "evidence_ref": "synthetic-observation"})
    return observation_id


def finish(store, job):
    engine = Orchestration(store)
    for target in ("draining", "closing", "applying"):
        data = {"lease": job["lease"], "attempt": job["attempt"], "operation_id": ident(),
                "expected_phase": engine.query(job["id"])["job"]["phase"], "phase": target}
        if target != "draining":
            data["observation_id"] = observe(store, job, stopped=True)
        engine.phase(job["id"], data)
    return engine.complete(job["id"], {"lease": job["lease"], "attempt": job["attempt"], "operation_id": ident(),
                                      "ok": True, "observation_id": observe(store, job, stopped=job["action"] == "pause")})


def legacy_cleanup(store, uid):
    engine = Orchestration(store)
    runtime = store.one("SELECT * FROM runtimes WHERE uid=?", (uid,))
    observation_id = ident()
    engine.reconcile({"observation_id": observation_id, "runtime_id": runtime["id"], "state_version": runtime["state_version"],
                      "host_boot_id": "synthetic-host", "observed_at": engine.clock(),
                      "components": dict.fromkeys(("agent", "gateway", "relay"), "stopped"), "mutation_state": "idle",
                      "complete": True, "evidence_ref": "synthetic-legacy-cleanup"})
    return {"observation_id": observation_id, "expected_state_version": runtime["state_version"], "operation_id": ident()}
