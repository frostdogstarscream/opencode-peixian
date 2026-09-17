"""Transactional, single-host runtime scheduling and durable worker protocol v2."""
import hashlib
import hmac
import json
import re
import secrets

from fastapi import HTTPException

from shared.orchestration_config import from_environment
from shared.worker_errors import CODES
from .migrations_v4 import canonical
from .store import digest, ident, now

PROTOCOL_VERSION = 2
TERMINAL = ("succeeded", "failed", "cancelled")


def reject(message, status=409, *, code=None):
    error = HTTPException(status, message)
    error.worker_code = code or {422: "worker_invalid_request", 404: "worker_not_found"}.get(status, "worker_rejected")
    assert error.worker_code in CODES
    raise error


def opaque(value, name="identity"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,128}", value):
        reject("Invalid " + name, 422)
    return value


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum or value > 2**53 - 1:
        reject("Invalid " + name, 422)
    return value


def request_fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        reject("Invalid worker request fields", 422)


def hashed(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Orchestration:
    def __init__(self, store, *, clock=now, config=None):
        self.store, self.clock = store, clock
        self.config = from_environment() if config is None else config

    def _job(self, db, jid):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (opaque(jid, "job"),)).fetchone()
        if not row:
            reject("Job not found", 404)
        return row

    def _runtime(self, db, uid):
        row = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
        if row is None:
            reject("Runtime not found", 404)
        return row

    def _active(self, db, jid, data):
        job = self._job(db, jid)
        integer(data.get("attempt"), "attempt", 1)
        lease = opaque(data.get("lease"), "lease")
        if (job["status"] != "running" or job["attempts"] != data["attempt"]
                or not hmac.compare_digest(job["lease"] or "", lease)
                or job["heartbeat"] is None or job["heartbeat"] + self.config["worker_lease_seconds"] <= self.clock()):
            reject("Worker lease or attempt has expired", code="worker_lease_expired")
        attempt = db.execute("SELECT * FROM job_attempts WHERE job_id=? AND attempt=?", (jid, data["attempt"])).fetchone()
        if not attempt or attempt["outcome"] is not None:
            reject("Attempt is no longer active", code="worker_attempt_inactive")
        return job, attempt, self._runtime(db, job["uid"])

    def _existing(self, db, jid, data, kind):
        opaque(data.get("operation_id"), "operation")
        integer(data.get("attempt"), "attempt", 1)
        lease_hash = digest(opaque(data.get("lease"), "lease"))
        request_hash = hashed({"kind": kind, "body": {key: value for key, value in data.items() if key != "lease"}})
        row = db.execute("SELECT * FROM worker_operation_receipts WHERE job_id=? AND attempt=? AND operation_id=?",
                         (jid, data["attempt"], data["operation_id"])).fetchone()
        if row:
            if not hmac.compare_digest(row["lease_hash"], lease_hash) or row["request_hash"] != request_hash:
                reject("Operation identity conflicts with its recorded request", code="worker_receipt_conflict")
            return json.loads(row["response"]), request_hash
        return None, request_hash

    def _receipt(self, db, jid, data, request_hash, **extra):
        job = self._job(db, jid)
        runtime = self._runtime(db, job["uid"])
        result = {"receipt_status": "recorded", "protocol_version": 2, "job_id": jid, "request_hash": request_hash,
                  "attempt": data["attempt"], "operation_id": data["operation_id"],
                  "job_status_after_commit": job["status"], "phase_after_commit": job["phase"],
                  "state_version": runtime["state_version"], "gate_epoch": runtime["gate_epoch"],
                  "authorization_version": runtime["authorization_version"],
                  "gate_policy_after_commit": runtime["gate_policy"],
                  "gate_owner": self._owner(db, runtime),
                  "gate_action": "close" if runtime["security_blocked"] or job["phase"] in ("closing", "applying", "reconciling", "finished") else "drain", **extra}
        current = self.clock()
        db.execute("INSERT INTO worker_operation_receipts VALUES(?,?,?,?,?,?,?,?)",
                   (jid, data["attempt"], data["operation_id"], request_hash, digest(data["lease"]),
                    canonical(result), current, current + self.config["receipt_retention_seconds"]))
        return result

    def _expire(self, db):
        cutoff = self.clock() - self.config["worker_lease_seconds"]
        for job in db.execute("SELECT * FROM jobs WHERE status='running' AND (heartbeat IS NULL OR heartbeat<=?)", (cutoff,)).fetchall():
            recovery = job["phase"] in ("closing", "applying", "reconciling") or job["recovery_required"]
            db.execute("UPDATE jobs SET status='queued',phase=?,recovery_required=?,lease=NULL,heartbeat=NULL,updated=? WHERE id=?",
                       ("reconciling" if recovery else "queued", int(bool(recovery)), self.clock(), job["id"]))
            if recovery:
                db.execute("UPDATE runtimes SET recovery_required=1,gate_policy='closed',state_version=state_version+1 WHERE uid=?", (job["uid"],))
            else:
                db.execute("UPDATE job_attempts SET outcome=?,outcome_hash=?,phase='finished',updated=? WHERE job_id=? AND attempt=? AND outcome IS NULL",
                           (canonical({"result": "lease_expired_before_mutation"}), hashed({"result": "lease_expired_before_mutation"}), self.clock(), job["id"], job["attempts"]))
                if job["cancel_requested"] and job["action"] != "pause":
                    db.execute("UPDATE jobs SET status='cancelled',phase='finished' WHERE id=?", (job["id"],))
                    db.execute("UPDATE runtimes SET drain_job_id=NULL WHERE uid=? AND drain_job_id=?", (job["uid"], job["id"]))
                    self.store.ensure_apply_job(db, job["uid"])
            if recovery and job["cancel_requested"] and job["action"] != "pause":
                self.store.queue_in_transaction(db, job["uid"], "pause", reason="security", bump_desired=False)

    def claim(self, spec_builder):
        with self.store.tx() as db:
            self._expire(db)
            for row in db.execute("SELECT uid FROM runtimes WHERE recovery_required=1").fetchall():
                self.store.ensure_recovery_job(db, row["uid"])
            platform = self.store.maintenance_status(db)
            jobs = db.execute("SELECT j.* FROM jobs j JOIN runtimes r ON r.uid=j.uid WHERE j.status='queued' AND j.not_before<=? AND NOT EXISTS(SELECT 1 FROM jobs a WHERE a.uid=j.uid AND a.status='running') ORDER BY CASE WHEN j.action='pause' AND (j.reason='security' OR r.security_blocked=1) THEN 0 WHEN j.action='pause' THEN 1 ELSE 2 END,j.enqueue_seq", (self.clock(),)).fetchall()
            for job in jobs:
                runtime = self._runtime(db, job["uid"])
                if job['reason']=='idle_timeout' and not job['recovery_required'] and not platform.get('idle_pause_enabled'):
                    db.execute("UPDATE jobs SET status='cancelled',phase='finished',error='idle_policy_disabled',updated=? WHERE id=?",(self.clock(),job['id']))
                    db.execute("UPDATE runtimes SET stop_reason=CASE WHEN stop_reason='idle_timeout' THEN 'none' ELSE stop_reason END,state_version=state_version+1 WHERE uid=?",(job['uid'],))
                    continue
                if job['reason']=='idle_timeout' and not job['recovery_required'] and platform['maintenance_mode']!='normal':
                    continue
                user = db.execute("SELECT active FROM users WHERE id=?", (job["uid"],)).fetchone()
                stopping = job["action"] == "pause"
                if not stopping and self.store.on_demand(db) and runtime["manual_stop_reason"] != "none":
                    continue
                if (job["observation_deadline"] is not None and job["observation_deadline"] <= self.clock()
                        and not stopping and not job["recovery_required"]):
                    continue
                if runtime["gate_policy"] == "cancel_pending":
                    continue
                if platform["maintenance_mode"] != "normal" and not stopping and not (platform["maintenance_mode"] == "repair_only" and job["recovery_required"]):
                    continue
                security_repair = (runtime["security_blocked"] and runtime["cancellation_confirmed"] and runtime["stop_reason"] != "account_disabled" and user and user["active"])
                if not stopping and not job["recovery_required"] and (not platform["capacity_healthy"] or (runtime["security_blocked"] and not security_repair) or not user or not user["active"] or job["cancel_requested"]):
                    continue
                if runtime["drain_job_id"] and runtime["drain_job_id"] != job["id"] and not stopping:
                    continue
                if runtime["recovery_required"] and not job["recovery_required"] and not stopping:
                    continue
                previous = db.execute("SELECT * FROM job_attempts WHERE job_id=? ORDER BY attempt DESC LIMIT 1", (job["id"],)).fetchone()
                recovery_of = previous["attempt"] if job["recovery_required"] and previous else None
                if job["recovery_required"]:
                    if previous is None and job["reason"] == "runtime_reconcile":
                        previous = db.execute("SELECT a.* FROM job_attempts a JOIN jobs j ON j.id=a.job_id WHERE j.uid=? AND a.spec_digest=? AND a.revision=? ORDER BY a.created DESC,a.rowid DESC LIMIT 1",
                                              (job["uid"], runtime["applied_spec_digest"], runtime["revision"])).fetchone()
                    if previous is None or not previous["spec_ciphertext"]:
                        # Migrated attempts with unknown original configuration need an explicit stop/repair.
                        continue
                    spec = self.store.decrypt(previous["spec_ciphertext"])
                    revision, spec_digest = previous["revision"], previous["spec_digest"]
                    phase = "reconciling"
                else:
                    revision = runtime["desired"]
                    spec = spec_builder(self.store, job["uid"], revision, db=db)
                    spec_digest = hashed(spec)
                    phase = "claimed"
                attempt, lease = job["attempts"] + 1, secrets.token_urlsafe(32)
                current = self.clock()
                db.execute("UPDATE jobs SET status='running',phase=?,lease=?,heartbeat=?,attempts=?,revision=?,updated=? WHERE id=?",
                           (phase, lease, current, attempt, revision, current, job["id"]))
                db.execute("INSERT INTO job_attempts(job_id,attempt,lease_hash,phase,revision,authorization_version,spec_ciphertext,spec_digest,recovery_of_attempt,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (job["id"], attempt, digest(lease), phase, revision, previous["authorization_version"] if job["recovery_required"] else runtime["authorization_version"], self.store.encrypt(spec), spec_digest,
                            recovery_of, current, current))
                if job["recovery_required"]:
                    db.execute("UPDATE runtimes SET drain_job_id=?,gate_policy='closed',gate_epoch=gate_epoch+1,state_version=state_version+1 WHERE uid=?", (job["id"], job["uid"]))
                public = self._public_job(db, self._job(db, job["id"]))
                public.update(lease=lease, spec_digest=spec_digest,
                              recovery_of_attempt=recovery_of)
                return {"protocol_version": 2, "job": public, "spec": spec}
            return {"protocol_version": 2, "job": None}

    def _owner(self, db, runtime):
        if runtime["security_blocked"]:
            return "security:" + (runtime["security_intent_id"] or runtime["id"])
        if runtime["stop_reason"] == "operator_cancel" and runtime["drain_intent_id"]:
            return "drain:" + runtime["drain_intent_id"]
        if runtime["drain_job_id"]:
            job = db.execute("SELECT attempts FROM jobs WHERE id=? AND uid=?", (runtime["drain_job_id"], runtime["uid"])).fetchone()
            if job:
                return f"job:{runtime['drain_job_id']}:{job['attempts']}"
        return "runtime:" + runtime["id"]

    def _public_job(self, db, job):
        runtime = self._runtime(db, job["uid"])
        fields = ("id", "uid", "action", "status", "phase", "revision", "reason", "not_before", "defer_count", "cancel_requested", "recovery_required", "observation_deadline")
        idle = {key: job[key] for key in ('idle_activity_version','idle_gateway_boot_id','idle_observed_at')} if 'idle_activity_version' in job.keys() else {}
        return {**idle, **{key: job[key] for key in fields}, "attempt": job["attempts"], "runtime_id": runtime["id"],
                "state_version": runtime["state_version"], "gate_epoch": runtime["gate_epoch"],
                "authorization_version": runtime["authorization_version"],
                "gate_policy": runtime["gate_policy"], "security_blocked": bool(runtime["security_blocked"]),
                "stop_reason": runtime["stop_reason"], "desired": runtime["desired"], "applied_revision": runtime["revision"],
                "gateway_boot_id": runtime["gateway_boot_id"], "gate_owner": self._owner(db, runtime)}

    def heartbeat(self, jid, data):
        request_fields(data, ("lease", "attempt"), ("lease", "attempt"))
        with self.store.tx() as db:
            self._active(db, jid, data)
            db.execute("UPDATE jobs SET heartbeat=?,updated=? WHERE id=?", (self.clock(), self.clock(), jid))
            return {"ok": True, "protocol_version": 2, "lease_expires_at": self.clock() + self.config["worker_lease_seconds"]}

    def _observation(self, db, runtime, jid, attempt, observation_id):
        row = db.execute("SELECT * FROM runtime_observations WHERE observation_id=?", (opaque(observation_id, "observation"),)).fetchone()
        if row is None:
            reject("Runtime observation is missing", code="worker_observation_missing")
        if row["runtime_id"] != runtime["id"] or row["job_id"] != jid or row["attempt"] != attempt:
            reject("Runtime observation belongs to old responsibility", code="worker_observation_responsibility")
        if row["state_version"] != runtime["state_version"]:
            reject("Runtime observation state has changed", code="worker_state_changed")
        if row["gate_epoch"] != runtime["gate_epoch"]:
            reject("Runtime observation gate has changed", code="worker_gate_changed")
        if row["expires_at"] <= self.clock():
            reject("Runtime observation has expired", code="worker_observation_expired")
        if not row["complete"]:
            reject("Runtime observation is incomplete", code="worker_observation_incomplete")
        latest = db.execute("SELECT observation_id FROM runtime_observations WHERE runtime_id=? ORDER BY observed_at DESC,rowid DESC LIMIT 1", (runtime["id"],)).fetchone()
        if latest is None or latest[0] != observation_id:
            reject("Runtime observation has been superseded", code="worker_observation_superseded")
        return row

    def phase(self, jid, data):
        request_fields(data, ("lease", "attempt", "operation_id", "expected_phase", "phase", "observation_id"),
                       ("lease", "attempt", "operation_id", "expected_phase", "phase"))
        with self.store.tx() as db:
            result, request_hash = self._existing(db, jid, data, "phase")
            if result is not None:
                return result
            job, attempt, runtime = self._active(db, jid, data)
            target = data["phase"]
            if data["expected_phase"] != job["phase"] or (job["phase"], target) not in (("claimed", "draining"), ("draining", "closing"), ("reconciling", "closing"), ("closing", "applying")):
                reject("Invalid or stale attempt phase transition", code="worker_phase_conflict")
            if target in ("closing", "applying"):
                if job['reason']=='idle_timeout' and (runtime['activity_boot_id']!=job['idle_gateway_boot_id']
                        or runtime['activity_version']!=job['idle_activity_version']
                        or runtime['last_activity'] is None or self.clock()-runtime['last_activity']<self.store.pool_settings['idle_timeout_seconds']
                        or runtime['security_blocked'] or runtime['manual_stop_reason']!='none'
                        or runtime['stop_reason']!='idle_timeout' or runtime['desired']!=runtime['revision']
                        or self.store.maintenance_status(db)['maintenance_mode']!='normal'):
                    reject('Idle candidate changed', code='worker_gate_unverified')
                observed = self._observation(db, runtime, jid, data["attempt"], data.get("observation_id"))
                if observed["accepting"] or observed["activity_count"] != 0 or observed["mutation_state"] != "idle" or observed["classification"] == "unknown":
                    reject("Runtime is not confirmed closed and idle", code="worker_gate_unverified")
                if self.clock() - observed["observed_at"] > self.config["gate_observation_seconds"]:
                    reject("Gate close observation is no longer fresh", code="worker_observation_expired")
                if target == "applying" and not observed["egress_closed"]:
                    reject("Relay egress close has not been confirmed", code="worker_gate_unverified")
                mode = self.store.maintenance_status(db)["maintenance_mode"]
                if target == "applying" and job["action"] != "pause" and mode != "normal" and not (mode == "repair_only" and job["recovery_required"]):
                    reject("Maintenance forbids new ordinary host mutation", code="worker_maintenance_blocked")
                security_repair = (runtime["cancellation_confirmed"] and runtime["stop_reason"] != "account_disabled" and attempt["authorization_version"] == runtime["authorization_version"])
                if job["action"] != "pause" and ((runtime["security_blocked"] and not security_repair) or job["cancel_requested"]):
                    reject("Security or stop intent prevents this mutation", code="worker_security_blocked")
            current = self.clock()
            db.execute("UPDATE jobs SET phase=?,drain_started_at=COALESCE(drain_started_at,?),observation_deadline=COALESCE(observation_deadline,?),updated=? WHERE id=?", (target, current, current + self.config["drain_alert_seconds"], current, jid))
            db.execute("UPDATE job_attempts SET phase=?,updated=? WHERE job_id=? AND attempt=?", (target, current, jid, data["attempt"]))
            db.execute("UPDATE runtimes SET status=?,gate_policy='closed',drain_job_id=?,state_version=state_version+1,gate_epoch=gate_epoch+?,updated=? WHERE uid=?",
                       ("draining" if target == "draining" else "updating", jid, int(target in ("draining", "closing")), current, job["uid"]))
            return self._receipt(db, jid, data, request_hash)

    def observe(self, data):
        required = ("observation_id", "runtime_id", "job_id", "attempt", "lease", "state_version", "host_boot_id", "gateway_boot_id", "gate_epoch", "observed_at", "components", "mutation_state", "complete", "accepting", "egress_closed", "activity_count", "applied_revision", "spec_digest", "evidence_ref")
        request_fields(data, (*required, 'idle_proof'), required)
        for key in ("observation_id", "runtime_id", "host_boot_id", "gateway_boot_id", "evidence_ref"):
            opaque(data[key], key)
        for key in ("state_version", "gate_epoch", "observed_at", "applied_revision"):
            integer(data[key], key)
        if any(type(data[key]) is not bool for key in ("complete", "accepting", "egress_closed")):
            reject("Observation flags must be booleans", 422)
        if data["activity_count"] is not None:
            integer(data["activity_count"], "activity_count")
        if not isinstance(data["components"], dict) or set(data["components"]) != {"agent", "gateway", "relay"} or any(value not in ("running", "stopped", "unknown") for value in data["components"].values()):
            reject("Observation must cover all runtime components", 422)
        if data["mutation_state"] not in ("idle", "running", "unknown"):
            reject("Invalid mutation observation", 422)
        if data["spec_digest"] is not None and (not isinstance(data["spec_digest"], str) or not re.fullmatch("[0-9a-f]{64}", data["spec_digest"])):
            reject("Invalid spec digest", 422)
        if abs(self.clock() - data["observed_at"]) > 5:
            reject("Observation clock is stale or ahead", code="worker_observation_expired")
        request_hash = hashed({key: value for key, value in data.items() if key != "lease"})
        with self.store.tx() as db:
            job, attempt, runtime = self._active(db, data["job_id"], data)
            if runtime["id"] != data["runtime_id"] or runtime["state_version"] != data["state_version"] or runtime["gate_epoch"] != data["gate_epoch"]:
                reject("Observation belongs to stale runtime state", code="worker_state_changed")
            if (data["components"]["gateway"] == "running" and runtime["gateway_boot_id"] is not None
                    and runtime["gateway_boot_id"] != data["gateway_boot_id"]):
                reject("Gateway boot must be registered before observing a running runtime", code="worker_boot_unregistered")
            old = db.execute("SELECT * FROM runtime_observations WHERE observation_id=?", (data["observation_id"],)).fetchone()
            if old:
                if old["request_hash"] != request_hash:
                    reject("Observation ID conflicts", code="worker_observation_conflict")
                return {"observation_id": old["observation_id"], "state_version": old["state_version"], "expires_at": old["expires_at"], "classification": old["classification"]}
            statuses = tuple(data["components"].values())
            if job['reason']=='idle_timeout':
                from .idle_pool import final_valid
                proof=data.get('idle_proof')
                valid=final_valid(self.store,job,runtime,proof,data['gateway_boot_id'],data['complete'],data['activity_count'])
                db.execute('UPDATE runtimes SET activity_boot_id=?,activity_version=?,last_activity=? WHERE uid=?',
                           (data['gateway_boot_id'] if valid else None, proof['sequence'] if valid else runtime['activity_version'],
                            self.clock()-int(proof['idle_seconds']) if valid else self.clock(),job['uid']))
            classification = "unknown"
            if data["complete"] and data["mutation_state"] == "idle" and "unknown" not in statuses:
                if all(value == "stopped" for value in statuses):
                    classification = "stopped"
                elif all(value == "running" for value in statuses):
                    classification = "running"
            expires = self.clock() + self.config["observation_ttl_seconds"]
            db.execute("INSERT INTO runtime_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (data["observation_id"], data["runtime_id"], data["job_id"], data["attempt"], data["state_version"], data["host_boot_id"], data["gateway_boot_id"], data["gate_epoch"], data["observed_at"], expires,
                        int(data["complete"]), canonical(data["components"]), data["mutation_state"], int(data["accepting"]), int(data["egress_closed"]), data["activity_count"], data["applied_revision"], data["spec_digest"], data["evidence_ref"], classification, request_hash, self.clock()))
            if classification == "unknown" or (not runtime["reserved"] and classification != "stopped"):
                if not runtime["reserved"]:
                    db.execute("UPDATE runtimes SET reserved=1,recovery_required=1,gate_policy='closed' WHERE uid=?", (job["uid"],))
                db.execute("UPDATE platform_state SET capacity_healthy=0,freeze_reason='runtime_observation_unknown',state_version=state_version+1,updated=? WHERE id=1", (self.clock(),))
            return {"observation_id": data["observation_id"], "state_version": runtime["state_version"], "expires_at": expires, "classification": classification}

    def boot(self, jid, data):
        fields = ("lease", "attempt", "operation_id", "runtime_id", "gateway_boot_id", "relay_boot_id")
        request_fields(data, fields, fields)
        for key in ("runtime_id", "gateway_boot_id", "relay_boot_id"):
            opaque(data[key], key)
        with self.store.tx() as db:
            existing, request_hash = self._existing(db, jid, data, "boot")
            if existing is not None:
                return existing
            job, attempt, runtime = self._active(db, jid, data)
            if job["phase"] not in ("applying", "reconciling") or runtime["id"] != data["runtime_id"]:
                reject("Boot registration is outside current mutation responsibility", code="worker_phase_conflict")
            changed = runtime["gateway_boot_id"] != data["gateway_boot_id"] or runtime["relay_boot_id"] != data["relay_boot_id"]
            if changed:
                db.execute("UPDATE runtimes SET gateway_boot_id=?,relay_boot_id=?,gate_policy='closed',gate_epoch=gate_epoch+1,state_version=state_version+1,updated=? WHERE uid=?",
                           (data["gateway_boot_id"], data["relay_boot_id"], self.clock(), job["uid"]))
            return self._receipt(db, jid, data, request_hash, gateway_boot_id=data["gateway_boot_id"], relay_boot_id=data["relay_boot_id"], gate_action="close")

    def cancel_idle(self, jid, data):
        request_fields(data, ('lease','attempt','operation_id'), ('lease','attempt','operation_id'))
        with self.store.tx() as db:
            old, signature=self._existing(db,jid,data,'cancel-idle')
            if old is not None: return old
            job,attempt,runtime=self._active(db,jid,data)
            if job['reason']!='idle_timeout' or job['phase'] not in ('claimed','draining','closing') or job['recovery_required']:
                reject('Idle cancellation is not allowed after mutation or recovery')
            active=db.execute('SELECT active FROM users WHERE id=?',(job['uid'],)).fetchone()['active']
            safe=active and not runtime['security_blocked'] and runtime['manual_stop_reason']=='none' and runtime['stop_reason']=='idle_timeout'
            self._outcome(db,jid,data['attempt'],{'result':'cancelled','reason':'idle_candidate_changed'})
            db.execute("UPDATE jobs SET status='cancelled',phase='finished',lease=NULL,heartbeat=NULL,error='idle_candidate_changed',updated=? WHERE id=?",(self.clock(),jid))
            db.execute("UPDATE runtimes SET status=?,gate_policy=?,drain_job_id=NULL,stop_reason=CASE WHEN stop_reason='idle_timeout' THEN 'none' ELSE stop_reason END,state_version=state_version+1,last_activity=?,activity_boot_id=NULL WHERE uid=?",
                       ('ready' if safe else 'draining','reopen_check' if safe else 'closed',self.clock(),job['uid']))
            self.store.ensure_apply_job(db,job['uid'])
            return self._receipt(db,jid,data,signature)

    def complete(self, jid, data):
        allowed = ("lease", "attempt", "operation_id", "ok", "deferred", "defer_reason", "error", "rolled_back", "observation_id", "cleanup_confirmed")
        request_fields(data, allowed, ("lease", "attempt", "operation_id"))
        for key in ("ok", "deferred", "rolled_back", "cleanup_confirmed"):
            if key in data and type(data[key]) is not bool:
                reject("Completion flags must be booleans", 422)
        deferred = data.get("deferred") is True
        if deferred:
            if set(data) - {"lease", "attempt", "operation_id", "deferred", "defer_reason", "observation_id"} or data.get("defer_reason") != "runtime_busy":
                reject("Invalid deferred outcome", 422)
        elif "ok" not in data or "defer_reason" in data or "deferred" in data:
            reject("Completion requires exactly one outcome", 422)
        if data.get("ok") is True and ("error" in data or "rolled_back" in data):
            reject("Successful completion cannot also report failure", 422)
        if "error" in data:
            opaque(data["error"], "error code")
        with self.store.tx() as db:
            existing, request_hash = self._existing(db, jid, data, "complete")
            if existing is not None:
                return existing
            job, attempt, runtime = self._active(db, jid, data)
            current = self.clock()
            observed = self._observation(db, runtime, jid, data["attempt"], data["observation_id"]) if data.get("observation_id") else None
            if deferred:
                if job["phase"] != "draining" or observed is None or observed["classification"] == "unknown" or observed["accepting"] or observed["activity_count"] is None or observed["activity_count"] <= 0 or observed["mutation_state"] != "idle":
                    reject("Only confirmed busy before mutation can defer")
                if job["cancel_requested"] or (runtime["security_blocked"] and job["action"] != "pause"):
                    reject("Stop or safety intent superseded busy defer")
                reopen = (job["action"] == "apply" and not runtime["security_blocked"]
                          and runtime["stop_reason"] == "none" and current - job["drain_started_at"] < self.config["apply_defer_max_seconds"]
                          and self.store.maintenance_status(db)["maintenance_mode"] == "normal")
                not_before = current + self.config["defer_seconds"]
                db.execute("UPDATE jobs SET status='queued',phase='queued',defer_count=defer_count+1,not_before=?,lease=NULL,heartbeat=NULL,updated=? WHERE id=?", (not_before, current, jid))
                db.execute("UPDATE runtimes SET status=?,gate_policy=?,drain_job_id=?,state_version=state_version+1,updated=? WHERE uid=?",
                           ("ready" if reopen else "draining", "reopen_check" if reopen else "closed", None if reopen else jid, current, job["uid"]))
                self._outcome(db, jid, data["attempt"], {"result": "deferred", "reason": "runtime_busy"})
                return self._receipt(db, jid, data, request_hash, not_before=not_before, defer_count_after_commit=job["defer_count"] + 1)
            ok = data["ok"]
            recovery = False
            allocation_retained = False
            if ok and job["phase"] not in ("applying", "reconciling"):
                reject("Applying was not acknowledged", code="worker_phase_conflict")
            if ok and observed is None:
                reject("Completion requires verified runtime evidence", code="worker_observation_missing")
            if ok and (observed["accepting"] or not observed["egress_closed"] or observed["activity_count"] != 0):
                reject("Completion requires closed and quiescent runtime gates", code="worker_gate_unverified")
            if ok and job["action"] == "pause":
                if observed["classification"] != "stopped" or observed["mutation_state"] != "idle":
                    reject("Pause has not confirmed all resources stopped")
                db.execute("UPDATE jobs SET status='cancelled',phase='finished',cancel_requested=1,recovery_required=0,updated=? WHERE uid=? AND id<>? AND status='queued'", (current, job["uid"], jid))
                db.execute("UPDATE job_attempts SET outcome=?,outcome_hash=?,phase='finished',updated=? WHERE job_id IN (SELECT id FROM jobs WHERE uid=? AND id<>? AND status='cancelled') AND outcome IS NULL",
                           (canonical({"result": "stopped_by_repair"}), hashed({"result": "stopped_by_repair"}), current, job["uid"], jid))
                active = db.execute("SELECT active FROM users WHERE id=?", (job["uid"],)).fetchone()[0]
                repair = (runtime["security_blocked"] and runtime["stop_reason"] != "account_disabled"
                          and active and runtime["reserved"] and runtime["applied_spec_ciphertext"] and job["reason"] == "security"
                          and (not self.store.on_demand(db) or runtime["manual_stop_reason"] == "none"))
                if not repair:
                    self.release(db, job["uid"], expected_state_version=runtime["state_version"], job_id=jid,
                                 attempt=data["attempt"], observation_id=observed["observation_id"], operation_id=data["operation_id"])
                db.execute("UPDATE runtimes SET status='paused',recovery_required=0,drain_job_id=NULL,gate_policy='closed',updated=? WHERE uid=?", (current, job["uid"]))
                if self.store.on_demand(db) and not repair:
                    db.execute("UPDATE runtimes SET cancellation_confirmed=1,security_confirmed_at=?,security_blocked=? WHERE uid=?", (current, int(not active), job["uid"]))
                active = db.execute("SELECT active FROM users WHERE id=?", (job["uid"],)).fetchone()[0]
                if repair:
                    allocation_retained = True
                    # Full-stop proof retires old authority; the replacement freezes current grants at claim.
                    db.execute("UPDATE runtimes SET status='provisioning',cancellation_confirmed=1,security_confirmed_at=?,state_version=state_version+1 WHERE uid=?", (current, job["uid"]))
                    db.execute("INSERT INTO jobs(id,uid,action,status,revision,reason,created,updated) VALUES(?,?,'resume','queued',?,'security_repair',?,?)",
                               (ident(), job["uid"], runtime["desired"], current, current))
            elif ok:
                if observed["classification"] != "running" or observed["applied_revision"] != attempt["revision"] or observed["spec_digest"] != attempt["spec_digest"]:
                    reject("Applied version or configuration digest is not verified", code="worker_applied_unverified")
                active = db.execute("SELECT active FROM users WHERE id=?", (job["uid"],)).fetchone()[0]
                if (runtime["security_blocked"] and runtime["cancellation_confirmed"] and active
                        and runtime["stop_reason"] != "account_disabled" and not job["cancel_requested"]
                        and attempt["authorization_version"] == runtime["authorization_version"]):
                    db.execute("UPDATE runtimes SET security_blocked=0,stop_reason='none',security_confirmed_at=?,gate_epoch=gate_epoch+1 WHERE uid=?", (current, job["uid"]))
                    runtime = self._runtime(db, job["uid"])
                if runtime["stop_reason"] == "operator_cancel" and runtime["cancellation_confirmed"]:
                    db.execute("UPDATE runtimes SET stop_reason='none',drain_intent_id=NULL WHERE uid=?", (job["uid"],))
                    runtime = self._runtime(db, job["uid"])
                safe = (not runtime["security_blocked"] and not job["cancel_requested"] and runtime["stop_reason"] == "none"
                        and (not self.store.on_demand(db) or runtime["manual_stop_reason"] == "none")
                        and self.store.maintenance_status(db)["maintenance_mode"] == "normal")
                db.execute("UPDATE runtimes SET revision=?,applied_spec_ciphertext=?,applied_spec_digest=?,gateway_boot_id=?,status=?,gate_policy=?,reserved=1,recovery_required=0,drain_job_id=NULL,state_version=state_version+1,updated=? WHERE uid=?",
                           (attempt["revision"], attempt["spec_ciphertext"], attempt["spec_digest"], observed["gateway_boot_id"], "ready" if safe else "draining", "reopen_check" if safe else "closed", current, job["uid"]))
                if self.store.on_demand(db):
                    db.execute("UPDATE runtimes SET provisioned_at=COALESCE(provisioned_at,?),ready_since=? WHERE uid=?", (current, current if safe else None, job["uid"]))
            else:
                rollback = data.get("rolled_back") is True
                verified_rollback = (rollback and observed is not None and observed["classification"] == "running"
                                     and runtime["revision"] > 0 and observed["applied_revision"] == runtime["revision"]
                                     and runtime["applied_spec_digest"] is not None and observed["spec_digest"] == runtime["applied_spec_digest"])
                if rollback and not verified_rollback:
                    reject("Rollback requires verified original applied configuration")
                cleaned = observed is not None and observed["classification"] == "stopped"
                cancelled_before_mutation = job["cancel_requested"] and job["action"] != "pause" and job["phase"] in ("claimed", "draining")
                if cleaned and not cancelled_before_mutation:
                    self.release(db, job["uid"], expected_state_version=runtime["state_version"], job_id=jid,
                                 attempt=data["attempt"], observation_id=observed["observation_id"], operation_id=data["operation_id"])
                safe_rollback = verified_rollback and not runtime["security_blocked"] and runtime["stop_reason"] == "none"
                recovery = not cleaned and not verified_rollback and not cancelled_before_mutation
                db.execute("UPDATE runtimes SET status=?,gate_policy=?,recovery_required=?,drain_job_id=?,state_version=state_version+1,error='runtime_operation_failed',updated=? WHERE uid=?",
                           ("ready" if safe_rollback else "failed", "reopen_check" if safe_rollback else "closed", int(recovery), jid if recovery else None, current, job["uid"]))
            outcome = {"result": "succeeded" if ok else "failed", "error": data.get("error"), "recovery_required": recovery}
            if allocation_retained:
                outcome["allocation_retained_for_security_repair"] = True
            self._outcome(db, jid, data["attempt"], outcome)
            db.execute("UPDATE jobs SET status=?,phase=?,recovery_required=?,lease=NULL,heartbeat=NULL,updated=? WHERE id=?",
                       ("queued" if recovery else "succeeded" if ok else "failed", "reconciling" if recovery else "finished", int(recovery), current, jid))
            if not ok and recovery:
                if job["action"] != "pause" and (job["cancel_requested"] or runtime["security_blocked"]):
                    self.store.queue_in_transaction(db, job["uid"], "pause", reason="security", bump_desired=False)
                elif job["phase"] == "reconciling" or (job["action"] == "pause" and job["reason"] == "security"):
                    # One inconclusive recovery is retained for operator repair, never a blind retry loop.
                    db.execute("UPDATE jobs SET status='failed',phase='finished' WHERE id=?", (jid,))
            if not ok and job["cancel_requested"] and job["action"] != "pause" and job["phase"] in ("claimed", "draining"):
                db.execute("UPDATE jobs SET status='cancelled',phase='finished' WHERE id=?", (jid,))
                self.store.ensure_apply_job(db, job["uid"])
            if not recovery and attempt["recovery_of_attempt"] is not None:
                db.execute("UPDATE job_attempts SET outcome=?,outcome_hash=?,phase='finished',updated=? WHERE job_id=? AND outcome IS NULL AND attempt<?",
                           (canonical({"result": "reconciled", "by_attempt": data["attempt"]}), hashed({"result": "reconciled", "by_attempt": data["attempt"]}), current, jid, data["attempt"]))
            if ok and job["action"] != "pause":
                self.store.ensure_apply_job(db, job["uid"])
            from .runtime_pool import promote_waiters
            promote_waiters(self.store, db, timestamp=current)
            return self._receipt(db, jid, data, request_hash, applied_revision=self._runtime(db, job["uid"])["revision"])

    def _outcome(self, db, jid, attempt, value):
        if db.execute("UPDATE job_attempts SET outcome=?,outcome_hash=?,phase='finished',updated=? WHERE job_id=? AND attempt=? AND outcome IS NULL",
                      (canonical(value), hashed(value), self.clock(), jid, attempt)).rowcount != 1:
            reject("Attempt already has a different final outcome", code="worker_receipt_conflict")

    def query(self, jid, attempt=None, operation_id=None):
        if operation_id is not None and attempt is None:
            reject("Receipt lookup requires an explicit attempt", 422)
        with self.store.read(snapshot=True) as db:
            job = self._job(db, jid)
            selected = job["attempts"] if attempt is None else integer(attempt, "attempt", 1)
            record = db.execute("SELECT attempt,phase,revision,authorization_version,spec_digest,outcome,recovery_of_attempt FROM job_attempts WHERE job_id=? AND attempt=?", (jid, selected)).fetchone()
            receipt = None
            if operation_id is not None:
                row = db.execute("SELECT response FROM worker_operation_receipts WHERE job_id=? AND attempt=? AND operation_id=?", (jid, selected, opaque(operation_id, "operation"))).fetchone()
                receipt = json.loads(row[0]) if row else None
            public = dict(record) if record else None
            if public and public["outcome"]:
                public["outcome"] = json.loads(public["outcome"])
            return {"protocol_version": 2, "job": self._public_job(db, job), "attempt": public, "receipt": receipt}

    def release(self, db, uid, *, expected_state_version, job_id, attempt, observation_id, operation_id):
        runtime = self._runtime(db, uid)
        opaque(operation_id, "release operation")
        request_hash = hashed([runtime["id"], expected_state_version, job_id, attempt, observation_id])
        previous = db.execute("SELECT * FROM capacity_release_receipts WHERE operation_id=?", (operation_id,)).fetchone()
        if previous:
            if previous["runtime_id"] != runtime["id"] or previous["request_hash"] != request_hash:
                reject("Capacity release operation conflicts")
            return json.loads(previous["response"])
        if runtime["state_version"] != expected_state_version:
            reject("Capacity release state has changed", code="worker_state_changed")
        observed = self._observation(db, runtime, job_id, attempt, observation_id)
        if observed["classification"] != "stopped" or observed["mutation_state"] != "idle":
            reject("Capacity is not confirmed stopped")
        if db.execute("SELECT 1 FROM jobs WHERE uid=? AND (? IS NULL OR id<>?) AND (status='running' OR (status='queued' AND action IN ('provision','resume')))", (uid, job_id, job_id)).fetchone():
            reject("A newer runtime allocation owns capacity")
        db.execute("UPDATE runtimes SET reserved=0,state_version=state_version+1,gate_policy='closed',updated=? WHERE uid=?", (self.clock(), uid))
        result = {"released": bool(runtime["reserved"]), "runtime_id": runtime["id"], "state_version": expected_state_version + 1,
                  "promotion_enabled": False, "maintenance_mode": self.store.maintenance_status(db)["maintenance_mode"]}
        db.execute("INSERT INTO capacity_release_receipts VALUES(?,?,?,?,?)", (operation_id, runtime["id"], request_hash, canonical(result), self.clock()))
        return result

    def maintenance(self, mode, expected_state_version, actor):
        if mode not in ("normal", "frozen", "repair_only"):
            reject("Unknown maintenance mode", 422)
        integer(expected_state_version, "state_version")
        opaque(actor, "maintenance actor")
        with self.store.tx() as db:
            platform = self.store.maintenance_status(db)
            if platform["state_version"] != expected_state_version:
                reject("Maintenance state has changed")
            if mode == "normal" and (not platform["capacity_healthy"] or db.execute("SELECT 1 FROM runtimes WHERE recovery_required=1").fetchone()):
                reject("Reconciliation is required before normal scheduling")
            db.execute("UPDATE platform_state SET maintenance_mode=?,state_version=state_version+1,updated=? WHERE id=1", (mode, self.clock()))
            db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,'worker','maintenance.changed',?,'success',?)", (ident(), actor, mode, self.clock()))
            return self.store.maintenance_status(db)

    def cleanup_receipts(self):
        with self.store.tx() as db:
            # An unresolved attempt pins every associated operation, even beyond seven days.
            result = db.execute("DELETE FROM worker_operation_receipts WHERE rowid IN (SELECT w.rowid FROM worker_operation_receipts w WHERE w.expires<? AND EXISTS(SELECT 1 FROM jobs j JOIN job_attempts a ON a.job_id=j.id WHERE j.id=w.job_id AND a.attempt=w.attempt AND j.status IN ('succeeded','failed','cancelled') AND j.recovery_required=0 AND a.outcome IS NOT NULL AND a.updated+?<=?) LIMIT 100)",
                                (self.clock(), self.config["receipt_retention_seconds"], self.clock()))
            return {"deleted": result.rowcount}

    def resolve_drain(self, uid, action, actor):
        if action not in ("continue", "cancel"):
            reject("Unknown drain resolution", 422)
        opaque(actor, "actor")
        with self.store.tx() as db:
            runtime = self._runtime(db, uid)
            job = db.execute("SELECT * FROM jobs WHERE uid=? AND status='queued' AND action='apply' AND drain_started_at IS NOT NULL ORDER BY enqueue_seq LIMIT 1", (uid,)).fetchone()
            if not job or runtime["security_blocked"] or runtime["recovery_required"] or runtime["stop_reason"] not in ("none", "operator_cancel"):
                reject("Runtime has no resolvable ordinary drain")
            db.execute("UPDATE jobs SET observation_deadline=?,not_before=0,updated=? WHERE id=?", (self.clock() + self.config["drain_alert_seconds"], self.clock(), job["id"]))
            if action == "cancel":
                db.execute("UPDATE runtimes SET drain_intent_id=?,stop_reason='operator_cancel',cancellation_confirmed=0,cancel_requested_at=?,gate_policy='cancel_pending',gate_epoch=gate_epoch+1,state_version=state_version+1,drain_job_id=? WHERE uid=?",
                           (ident(), self.clock(), job["id"], uid))
            else:
                db.execute("UPDATE runtimes SET status='draining',gate_policy='closed',drain_job_id=?,state_version=state_version+1 WHERE uid=?", (job["id"], uid))
            db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,'super_admin',?,?,'success',?)", (ident(), actor, "runtime.drain." + action, uid, self.clock()))
            return {"accepted": True, "job": self._public_job(db, self._job(db, job["id"]))}

    def reconcile_candidates(self, limit=None):
        self.cleanup_receipts()
        limit = self.config["reconcile_batch"] if limit is None else integer(limit, "limit", 1)
        if limit > self.config["reconcile_batch"]:
            reject("Reconciliation batch exceeds configured bound", 422)
        with self.store.tx() as db:
            platform = self.store.maintenance_status(db)
            from .runtime_pool import RESPONSIBILITY
            scope = " WHERE " + RESPONSIBILITY if self.store.on_demand(db) else ""
            count = db.execute("SELECT count(*) FROM runtimes r" + scope).fetchone()[0]
            offset = platform["reconcile_generation"] % count if count else 0
            rows = db.execute("SELECT uid,id AS runtime_id,state_version,gate_epoch,revision,gateway_boot_id FROM runtimes r" + scope + " ORDER BY rowid LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            generation = platform["reconcile_generation"] + len(rows)
            db.execute("UPDATE platform_state SET reconcile_generation=? WHERE id=1", (generation,))
            return {"protocol_version": 2, "items": [dict(row) for row in rows], "generation": generation}

    def reconcile(self, data):
        fields = ("observation_id", "runtime_id", "state_version", "host_boot_id", "observed_at", "components", "mutation_state", "complete", "evidence_ref")
        request_fields(data, (*fields, "orphan_resources"), fields)
        for key in ("observation_id", "runtime_id", "host_boot_id", "evidence_ref"):
            opaque(data[key], key)
        integer(data["state_version"], "state_version")
        integer(data["observed_at"], "observed_at")
        if type(data["complete"]) is not bool or type(data.get("orphan_resources", False)) is not bool:
            reject("Observation flags must be booleans", 422)
        if (not isinstance(data["components"], dict) or set(data["components"]) != {"agent", "gateway", "relay"}
                or any(value not in ("running", "stopped", "unknown") for value in data["components"].values())
                or data["mutation_state"] not in ("idle", "running", "unknown")):
            reject("Reconciliation must cover every runtime component", 422)
        if abs(self.clock() - data["observed_at"]) > 5:
            reject("Reconciliation observation is stale", code="worker_observation_expired")
        with self.store.tx() as db:
            runtime = db.execute("SELECT * FROM runtimes WHERE id=?", (data["runtime_id"],)).fetchone()
            if not runtime or runtime["state_version"] != data["state_version"]:
                reject("Reconciliation runtime state changed", code="worker_state_changed")
            previous = db.execute("SELECT request_hash FROM runtime_observations WHERE observation_id=?", (data["observation_id"],)).fetchone()
            if previous:
                if previous[0] != hashed(data):
                    reject("Observation identity conflicts", code="worker_observation_conflict")
                return {"observation_id": data["observation_id"], "recorded": True}
            statuses = tuple(data["components"].values())
            complete = data["complete"] and not data.get("orphan_resources", False)
            classification = "unknown"
            if complete and data["mutation_state"] == "idle" and "unknown" not in statuses:
                if all(value == "stopped" for value in statuses):
                    classification = "stopped"
                elif all(value == "running" for value in statuses):
                    classification = "running"
            db.execute("INSERT INTO runtime_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (data["observation_id"], runtime["id"], None, None, runtime["state_version"], data["host_boot_id"], runtime["gateway_boot_id"] or "absent", runtime["gate_epoch"], data["observed_at"], self.clock() + self.config["observation_ttl_seconds"],
                        int(complete), canonical(data["components"]), data["mutation_state"], 0, 0, None, runtime["revision"], None, data["evidence_ref"], classification, hashed(data), self.clock()))
            released = False
            responsible = runtime["drain_job_id"] or runtime["recovery_required"] or db.execute("SELECT 1 FROM jobs WHERE uid=? AND (status IN ('queued','running') OR recovery_required=1)", (runtime["uid"],)).fetchone()
            if runtime["reserved"] and classification == "stopped" and not responsible:
                released = self.release(db, runtime["uid"], expected_state_version=runtime["state_version"], job_id=None, attempt=None, observation_id=data["observation_id"], operation_id="reconcile:" + data["observation_id"])["released"]
                db.execute("UPDATE runtimes SET status='paused',gate_policy='closed',stop_reason=CASE WHEN stop_reason='none' THEN 'admin_review' ELSE stop_reason END WHERE uid=?", (runtime["uid"],))
            drift = not runtime["reserved"] and classification != "stopped"
            if drift:
                db.execute("UPDATE runtimes SET reserved=1,recovery_required=1,gate_policy='closed',state_version=state_version+1 WHERE uid=?", (runtime["uid"],))
            if classification == "unknown" or drift:
                db.execute("UPDATE platform_state SET capacity_healthy=0,freeze_reason=?,state_version=state_version+1,updated=? WHERE id=1", ("orphan_resources" if data.get("orphan_resources") else "runtime_observation_unknown", self.clock()))
            elif self.store.on_demand(db):
                from .runtime_pool import restore_capacity
                restore_capacity(self.store, db, data["host_boot_id"])
            else:
                # Only a complete, fresh view of every known runtime can clear protection.
                unknown = db.execute("SELECT 1 FROM runtimes r WHERE r.recovery_required=1 OR NOT EXISTS(SELECT 1 FROM runtime_observations o WHERE o.runtime_id=r.id AND o.observation_id=(SELECT n.observation_id FROM runtime_observations n WHERE n.runtime_id=r.id ORDER BY n.observed_at DESC,n.rowid DESC LIMIT 1) AND o.complete=1 AND o.classification<>'unknown' AND o.expires_at>? AND o.host_boot_id=?) LIMIT 1", (self.clock(), data["host_boot_id"])).fetchone()
                if not unknown:
                    db.execute("UPDATE platform_state SET capacity_healthy=1,freeze_reason=NULL WHERE id=1 AND freeze_reason IS NOT 'orphan_resources'")
            from .runtime_pool import promote_waiters
            promote_waiters(self.store, db, timestamp=self.clock())
            return {"observation_id": data["observation_id"], "classification": classification, "released": released,
                    "capacity_healthy": bool(self.store.maintenance_status(db)["capacity_healthy"])}
