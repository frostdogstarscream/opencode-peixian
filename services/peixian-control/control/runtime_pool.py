"""Account-scoped admission transactions. Never performs host or network I/O."""
import os
import hashlib
import json

from fastapi import HTTPException

from .store import ident, now

# Never-started metadata is not a missing-Gateway failure. Stopped physical
# resources are covered by the separate deployment-wide host inventory.
RESPONSIBILITY = """(r.reserved=1 OR r.recovery_required=1 OR r.drain_job_id IS NOT NULL
 OR EXISTS(SELECT 1 FROM jobs j WHERE j.uid=r.uid AND (j.status='running' OR j.recovery_required=1))
 OR EXISTS(SELECT 1 FROM jobs j JOIN job_attempts a ON a.job_id=j.id WHERE j.uid=r.uid AND a.outcome IS NULL))"""


def inventory_targets(db):
    rows = [dict(row) for row in db.execute("SELECT uid,id AS runtime_id,state_version FROM runtimes ORDER BY id")]
    if len(rows) > 10000:
        reject("runtime_inventory_limit", "登记资源数量超过本版清单上限")
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"items": rows, "registry_digest": digest}


def record_inventory(store, data):
    fields = {"host_boot_id", "observed_at", "registry_digest", "complete", "resources"}
    if (not isinstance(data, dict) or set(data) != fields or type(data["complete"]) is not bool
            or type(data["observed_at"]) is not int or not 0 <= now()-data["observed_at"] <= 15
            or not isinstance(data["host_boot_id"], str) or not 1 <= len(data["host_boot_id"]) <= 128
            or not isinstance(data["resources"], list) or len(data["resources"]) > 10000):
        reject("runtime_inventory_invalid", "宿主清单不完整或已过期", 422)
    with store.tx() as db:
        if not store.on_demand(db):
            reject("runtime_mode_unsupported", "当前部署未启用按需模式")
        targets = inventory_targets(db)
        if targets["registry_digest"] != data["registry_digest"]:
            reject("runtime_inventory_changed", "登记资源已变化，请重新采集")
        known = {r["runtime_id"]: r["uid"] for r in targets["items"]}
        complete = data["complete"]
        seen = set()
        for resource in data["resources"]:
            if (not isinstance(resource, dict) or set(resource) != {"runtime_id", "uid", "running", "mutation_state"}
                    or type(resource["running"]) is not bool or resource["mutation_state"] not in ("idle", "running", "unknown")
                    or not isinstance(resource["runtime_id"], str) or not isinstance(resource["uid"], str)):
                reject("runtime_inventory_invalid", "宿主清单格式不正确", 422)
            rid = resource["runtime_id"]
            if rid in seen or known.get(rid) != resource["uid"]:
                complete = False
                continue
            seen.add(rid)
            runtime = current(db, resource["uid"])
            if resource["mutation_state"] == "unknown":
                complete = False
            if not runtime["reserved"] and (resource["running"] or resource["mutation_state"] != "idle" or never_executed(db, runtime)):
                db.execute("UPDATE runtimes SET reserved=1,recovery_required=1,gate_policy='closed',state_version=state_version+1,manual_stop_reason='admin_review' WHERE uid=?", (resource["uid"],))
                complete = False
        db.execute("INSERT INTO runtime_pool_inventory(id,host_boot_id,observed_at,expires_at,registry_digest,complete) VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET host_boot_id=excluded.host_boot_id,observed_at=excluded.observed_at,expires_at=excluded.expires_at,registry_digest=excluded.registry_digest,complete=excluded.complete",
                   (data["host_boot_id"], data["observed_at"], data["observed_at"]+120, data["registry_digest"], int(complete)))
        if not complete:
            db.execute("UPDATE platform_state SET capacity_healthy=0,freeze_reason='pool_inventory_incomplete',state_version=state_version+1 WHERE id=1")
        else:
            restore_capacity(store, db, data["host_boot_id"])
        return {"complete": complete, "capacity_healthy": bool(store.maintenance_status(db)["capacity_healthy"])}


def restore_capacity(store, db, host_boot_id):
    inventory = db.execute("SELECT * FROM runtime_pool_inventory WHERE id=1").fetchone()
    if (not inventory or not inventory["complete"] or inventory["expires_at"] <= now()
            or inventory["host_boot_id"] != host_boot_id
            or inventory["registry_digest"] != inventory_targets(db)["registry_digest"]):
        return
    unknown = db.execute("SELECT 1 FROM runtimes r WHERE " + RESPONSIBILITY + " AND (r.recovery_required=1 OR NOT EXISTS(SELECT 1 FROM runtime_observations o WHERE o.runtime_id=r.id AND o.observation_id=(SELECT n.observation_id FROM runtime_observations n WHERE n.runtime_id=r.id ORDER BY n.observed_at DESC,n.rowid DESC LIMIT 1) AND o.complete=1 AND o.classification<>'unknown' AND o.expires_at>? AND o.host_boot_id=?)) LIMIT 1", (now(), host_boot_id)).fetchone()
    if not unknown:
        db.execute("UPDATE platform_state SET capacity_healthy=1,freeze_reason=NULL WHERE id=1 AND freeze_reason IS NOT 'orphan_resources'")


def reject(code, message, status=409):
    raise HTTPException(status, {"code": code, "message": message})


def never_executed(db, runtime):
    # revision=0 alone cannot prove that a failed first provision left no resources.
    return (runtime["provisioned_at"] is None and runtime["revision"] == 0
            and not runtime["recovery_required"] and runtime["gateway_boot_id"] is None
            and runtime["relay_boot_id"] is None
            and not db.execute("SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id WHERE j.uid=?", (runtime["uid"],)).fetchone()
            and not db.execute("SELECT 1 FROM jobs WHERE uid=? AND (attempts>0 OR recovery_required=1 OR status='running')", (runtime["uid"],)).fetchone())


def current(db, uid):
    row = db.execute("SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=? AND u.role='user'", (uid,)).fetchone()
    if row is None:
        reject("runtime_not_found", "助手环境不存在", 404)
    return row


def confirmed_stopped(db, row):
    if never_executed(db, row):
        return True
    if row["reserved"] or row["status"] != "paused" or row["recovery_required"] or active_job(db, row["uid"]):
        return False
    if db.execute("SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id WHERE j.uid=? AND a.outcome IS NULL", (row["uid"],)).fetchone():
        return False
    proof = db.execute("SELECT classification,mutation_state FROM runtime_observations WHERE runtime_id=? ORDER BY observed_at DESC,rowid DESC LIMIT 1", (row["id"],)).fetchone()
    return bool(proof and proof["classification"] == "stopped" and proof["mutation_state"] == "idle")


def active_job(db, uid):
    return db.execute("SELECT id,action,status,phase,revision FROM jobs WHERE uid=? AND status IN ('waiting_capacity','queued','running') ORDER BY CASE WHEN status='running' THEN 0 ELSE 1 END,enqueue_seq LIMIT 1", (uid,)).fetchone()


def cancel_waiter(db, job, reason, timestamp):
    changed = db.execute("UPDATE jobs SET status='cancelled',phase='finished',error=?,cancel_requested=1,updated=? WHERE id=? AND status='waiting_capacity'", (reason, timestamp, job['id'])).rowcount
    if changed:
        db.execute("UPDATE runtimes SET state_version=state_version+1,updated=? WHERE uid=?", (timestamp, job['uid']))
    return changed


def promote_waiters(store, db, *, timestamp=None):
    """Bounded FIFO allocation; callers hold the same short write transaction."""
    timestamp = now() if timestamp is None else timestamp
    policy = store.maintenance_status(db)
    if not policy.get('capacity_wait_enabled'):
        return []
    batch = store.pool_settings['scheduler_batch']
    expired = db.execute("SELECT id,uid FROM jobs WHERE status='waiting_capacity' AND capacity_expires_at<=? ORDER BY enqueue_seq LIMIT ?", (timestamp, batch)).fetchall()
    for job in expired:
        cancel_waiter(db, job, 'capacity_wait_expired', timestamp)
    if policy['maintenance_mode'] != 'normal' or not policy['capacity_healthy']:
        return []
    available = max(0, int(os.getenv('MAX_RUNTIMES', '4')) - db.execute('SELECT count(*) FROM runtimes WHERE reserved=1').fetchone()[0])
    selected = db.execute("SELECT * FROM jobs WHERE status='waiting_capacity' AND not_before<=? ORDER BY enqueue_seq LIMIT ?", (timestamp, batch)).fetchall()
    promoted = []
    for job in selected:
        if job['capacity_expires_at'] <= timestamp:
            cancel_waiter(db, job, 'capacity_wait_expired', timestamp)
            continue
        r = current(db, job['uid'])
        if job['cancel_requested'] or not r['active'] or r['manual_stop_reason'] != 'none' or r['security_blocked']:
            cancel_waiter(db, job, 'capacity_wait_restricted', timestamp)
            continue
        conflict = (r['reserved'] or r['recovery_required'] or db.execute(
            "SELECT 1 FROM jobs WHERE uid=? AND id<>? AND (status IN ('queued','running') OR recovery_required=1) UNION ALL SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id WHERE j.uid=? AND a.outcome IS NULL",
            (job['uid'], job['id'], job['uid'])).fetchone())
        if conflict:
            cancel_waiter(db, job, 'capacity_wait_recovery_required', timestamp)
            continue
        if not available:
            break
        db.execute("UPDATE jobs SET status='queued',phase='queued',revision=?,capacity_reserved_at=?,updated=? WHERE id=? AND status='waiting_capacity'", (r['desired'], timestamp, timestamp, job['id']))
        db.execute("UPDATE runtimes SET reserved=1,status='provisioning',stop_reason='none',gate_policy='closed',error=NULL,state_version=state_version+1,updated=? WHERE uid=?", (timestamp, job['uid']))
        available -= 1
        promoted.append(job['id'])
    return promoted


def scheduler_tick(store):
    with store.tx() as db:
        return promote_waiters(store, db)


async def scheduler_loop(app):
    import asyncio
    import sqlite3
    app.state.pool_failures = 0
    while not app.state.pool_stop.is_set():
        try:
            await asyncio.wait_for(app.state.pool_stop.wait(), app.state.store.pool_settings['scheduler_tick_seconds'])
            return
        except TimeoutError:
            pass
        try:
            await app.state.db_work.run(scheduler_tick, app.state.store)
        except HTTPException as error:
            # No request is lost: its durable state is retried on the next tick.
            if error.status_code not in (429, 503):
                raise
            app.state.pool_failures += 1
            continue
        except sqlite3.OperationalError as error:
            if getattr(error, 'sqlite_errorcode', None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            app.state.pool_failures += 1


def public_status(store, db, uid):
    row = current(db, uid)
    job = active_job(db, uid)
    policy = store.maintenance_status(db)
    eligible = row["active"] and row["manual_stop_reason"] == "none" and not row["security_blocked"] and not row["recovery_required"]
    ready = row["status"] == "ready" and row["gate_policy"] == "open" and eligible
    actions = []
    if eligible and not job and not row["reserved"] and policy["maintenance_mode"] == "normal" and policy["capacity_healthy"]:
        actions.append("start")
    if row["active"] and (row["reserved"] or job) and not row["security_blocked"] and not row["recovery_required"]:
        actions.append("stop")
    waiting = None
    if job and job['status'] == 'waiting_capacity':
        queued = db.execute('SELECT enqueue_seq,capacity_expires_at FROM jobs WHERE id=?', (job['id'],)).fetchone()
        waiting = {'expires_at': queued['capacity_expires_at'], 'approximate_position': db.execute("SELECT count(*) FROM jobs WHERE status='waiting_capacity' AND enqueue_seq<=?", (queued['enqueue_seq'],)).fetchone()[0]}
    last = db.execute("SELECT error FROM jobs WHERE uid=? AND reason='explicit_start' ORDER BY enqueue_seq DESC LIMIT 1", (uid,)).fetchone()
    return {"runtime_mode": "on_demand", "status": row["status"], "ready": bool(ready), "waiting": waiting,
            "wait_result": last['error'] if last and last['error'] in ('capacity_wait_expired','capacity_wait_cancelled','capacity_wait_restricted','capacity_wait_recovery_required') else None,
            "state_version": row["state_version"], "desired": row["desired"], "revision": row["revision"],
            "stop_reason": row["stop_reason"], "manual_stop_reason": row["manual_stop_reason"],
            "allowed_actions": actions, "job": dict(job) if job else None}


def start(store, db, uid, *, admin=False):
    row = current(db, uid)
    platform = store.maintenance_status(db)
    if not row["active"]:
        reject("runtime_account_disabled", "请先启用账号")
    if row["manual_stop_reason"] != "none" and not admin:
        reject("runtime_admin_stopped", "管理员已暂停助手，请联系管理员恢复")
    if row["security_blocked"] or row["recovery_required"]:
        reject("runtime_recovery_required", "助手处于保护或恢复状态，请联系管理员")
    if platform["maintenance_mode"] != "normal" or not platform["capacity_healthy"]:
        reject("runtime_capacity_unverified", "平台正在维护或核对容量，请稍后重试")
    existing = active_job(db, uid)
    if existing:
        if existing["action"] in ("provision", "resume"):
            return {"accepted": True, "job": dict(existing), "runtime": public_status(store, db, uid)}
        reject("runtime_operation_pending", "助手正在处理其他操作")
    if row["reserved"]:
        if row["status"] == "ready" and row["gate_policy"] == "open" and row["manual_stop_reason"] == "none":
            return {"accepted": False, "job": None, "runtime": public_status(store, db, uid)}
        reject("runtime_recovery_required", "已有运行责任尚未完成核对")
    if db.execute("SELECT 1 FROM jobs WHERE uid=? AND recovery_required=1 UNION ALL SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id WHERE j.uid=? AND a.outcome IS NULL", (uid, uid)).fetchone():
        reject("runtime_recovery_required", "已有运行责任尚未完成核对")
    if platform.get('capacity_wait_enabled'):
        promote_waiters(store, db)
        if db.execute("SELECT count(*) FROM jobs WHERE status='waiting_capacity'").fetchone()[0] >= store.pool_settings['max_waiting_requests']:
            reject('runtime_wait_queue_full', '启动等待人数已达上限，请稍后重试', 429)
        jid = ident()
        action = 'provision' if never_executed(db, row) else 'resume'
        if admin:
            db.execute("UPDATE runtimes SET manual_stop_reason='none' WHERE uid=?", (uid,))
        db.execute("INSERT INTO jobs(id,uid,action,status,revision,reason,capacity_expires_at,created,updated) VALUES(?,?,?,'waiting_capacity',?,'explicit_start',?,?,?)", (jid,uid,action,row['desired'],now()+store.pool_settings['capacity_wait_ttl_seconds'],now(),now()))
        db.execute('UPDATE runtimes SET state_version=state_version+1,updated=? WHERE uid=?', (now(),uid))
        promote_waiters(store, db)
        return {'accepted': True, 'job': dict(active_job(db,uid)), 'runtime':public_status(store,db,uid)}
    if db.execute("SELECT count(*) FROM runtimes WHERE reserved=1").fetchone()[0] >= int(os.getenv("MAX_RUNTIMES", "4")):
        reject("runtime_capacity_full", "当前运行名额已满，请稍后手动启动")
    action = "provision" if never_executed(db, row) else "resume"
    jid = ident()
    db.execute("UPDATE runtimes SET reserved=1,status='provisioning',stop_reason='none',manual_stop_reason='none',gate_policy='closed',error=NULL,state_version=state_version+1,updated=? WHERE uid=?", (now(), uid))
    db.execute("INSERT INTO jobs(id,uid,action,status,revision,reason,capacity_reserved_at,created,updated) VALUES(?,?,?,'queued',?,'explicit_start',?,?,?)", (jid, uid, action, row["desired"], now(), now(), now()))
    return {"accepted": True, "job": {"id": jid, "status": "queued", "action": action}, "runtime": public_status(store, db, uid)}


def stop(store, db, uid, *, reason="user", expected_state_version=None, start_job_id=None):
    row = current(db, uid)
    if expected_state_version is not None and (type(expected_state_version) is not int or expected_state_version != row["state_version"]):
        reject("runtime_state_changed", "助手状态已变化，请刷新后重新操作")
    if start_job_id is not None and not db.execute("SELECT 1 FROM jobs WHERE id=? AND uid=? AND action IN ('provision','resume') AND status IN ('waiting_capacity','queued','running')", (start_job_id, uid)).fetchone():
        reject("runtime_start_changed", "启动申请已变化，请刷新后重试")
    if reason in ("normal", "admin"):
        db.execute("UPDATE runtimes SET manual_stop_reason='admin',state_version=state_version+1 WHERE uid=?", (uid,))
    waiting = db.execute("SELECT id,uid FROM jobs WHERE uid=? AND status='waiting_capacity'", (uid,)).fetchone()
    if waiting:
        cancel_waiter(db, waiting, 'capacity_wait_cancelled', now())
        promote_waiters(store, db)
        return {'accepted': False, 'job': None, 'runtime': public_status(store, db, uid)}
    pause = db.execute("SELECT id,action,status FROM jobs WHERE uid=? AND action='pause' AND status IN ('queued','running')", (uid,)).fetchone()
    if pause:
        return {"accepted": True, "job": dict(pause), "runtime": public_status(store, db, uid)}
    if never_executed(db, row):
        if reason == "user" and not row["reserved"] and active_job(db, uid) is None:
            return {"accepted": False, "job": None, "runtime": public_status(store, db, uid)}
        db.execute("UPDATE jobs SET status='cancelled',phase='finished',cancel_requested=1,updated=? WHERE uid=? AND status IN ('waiting_capacity','queued')", (now(), uid))
        db.execute("UPDATE runtimes SET reserved=0,status='unprovisioned',gate_policy='closed',stop_reason=CASE WHEN security_blocked=1 THEN stop_reason ELSE ? END,state_version=state_version+1,updated=? WHERE uid=?", ("admin" if reason in ("normal", "admin") else "user", now(), uid))
        promote_waiters(store, db)
        return {"accepted": False, "job": None, "runtime": public_status(store, db, uid)}
    if not row["reserved"] and row["status"] == "paused" and not row["recovery_required"]:
        return {"accepted": False, "job": None, "runtime": public_status(store, db, uid)}
    db.execute("UPDATE jobs SET status='cancelled',phase='finished',cancel_requested=1,updated=? WHERE uid=? AND status='queued' AND recovery_required=0", (now(), uid))
    db.execute("UPDATE jobs SET cancel_requested=1 WHERE uid=? AND status='running'", (uid,))
    jid = ident()
    db.execute("INSERT INTO jobs(id,uid,action,status,revision,reason,created,updated) VALUES(?,?,'pause','queued',?,?,?,?)", (jid, uid, row["desired"], reason, now(), now()))
    db.execute("UPDATE runtimes SET status='draining',gate_policy='closed',stop_reason=CASE WHEN security_blocked=1 THEN stop_reason ELSE ? END,state_version=state_version+1,updated=? WHERE uid=?", ("admin" if reason in ("normal", "admin") else reason, now(), uid))
    return {"accepted": True, "job": {"id": jid, "action": "pause", "status": "queued"}, "runtime": public_status(store, db, uid)}


def identity_updated(store, db, uid, data, active):
    row = current(db, uid)
    if active and not row["reserved"] and confirmed_stopped(db, row):
        # Re-enable the identity, not its runtime or an administrator's prohibition.
        db.execute("UPDATE runtimes SET security_blocked=0,security_intent_id=NULL,gate_policy='closed',state_version=state_version+1 WHERE uid=?", (uid,))
    if "model_ids" in data or "plugin_ids" in data:
        return store.queue_in_transaction(db, uid, "apply")
    if not active:
        return stop(store, db, uid, reason="security")["job"]
    return None
