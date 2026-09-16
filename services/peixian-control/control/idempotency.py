"""Atomic receipts for platform mutations; never a retry policy for model execution."""
import hashlib
import hmac
import json
import re

from fastapi import HTTPException

from .store import now


KEY = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
MUTATIONS = re.compile(
    r"^/api/console/v1/(?:admin/(?:users(?:/[^/]+(?:/runtime/[^/]+|/reset-password)?)?"
    r"|models(?:/[^/]+)?|plugins(?:/[^/]+/[^/]+(?:/connections)?)?"
    r"|connections(?:/[^/]+)?|templates(?:/[^/]+)?|maintenance|recovery/[^/]+)"
    r"|skills(?:/[^/]+(?:/rollback)?)?|plugins/[^/]+(?:/rollback)?|templates/[^/]+/copy)$"
)


def required(request):
    return request.method not in ("GET", "HEAD", "OPTIONS") and bool(MUTATIONS.fullmatch(request.url.path))


def key(request):
    value = request.headers.get("idempotency-key", "")
    if not KEY.fullmatch(value):
        raise HTTPException(422, "此操作需要有效的 Idempotency-Key，请更新客户端后重试")
    return value


def request_hash(store, request):
    payload = getattr(request.state, "json_body", None)
    uploaded = getattr(request.state, "upload_body", None)
    if uploaded is not None:
        payload = {"upload_sha256": hashlib.sha256(uploaded).hexdigest()}
    canonical = json.dumps({"method": request.method, "path": request.url.path, "body": payload},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    # Passwords/configuration are not persisted as plain hashes susceptible to
    # offline dictionary guessing. The matching platform secret is in backups.
    return hmac.new(store.worker_key.encode(), canonical, hashlib.sha256).hexdigest()


def execute(request, user, operation):
    from .app import current_authority
    store = request.app.state.store
    request_key = key(request)
    action = request.method + " " + request.url.path
    fingerprint = request_hash(store, request)
    with store.atomic_request() as db:
        current_authority(db, user)
        receipt = db.execute(
            "SELECT * FROM request_idempotency WHERE uid=? AND action=? AND request_key=?",
            (user["uid"], action, request_key)).fetchone()
        if receipt and (receipt["expires"] >= now() or _unclosed(db, receipt["response_ref"])):
            if not hmac.compare_digest(receipt["request_hash"], fingerprint):
                raise HTTPException(409, "相同操作标识对应的内容不同，请检查后重新操作")
            request.state.idempotency_replayed = True
            return store.decrypt(receipt["response_ciphertext"])
        if receipt:
            db.execute("DELETE FROM request_idempotency WHERE uid=? AND action=? AND request_key=?",
                       (user["uid"], action, request_key))
        # Bound cleanup cost and retain receipts that still identify unfinished
        # configuration/recovery work, even when their minimum retention ended.
        for old in db.execute("SELECT rowid,response_ref FROM request_idempotency WHERE expires<? ORDER BY expires LIMIT 32", (now(),)).fetchall():
            if not _unclosed(db, old["response_ref"]):
                db.execute("DELETE FROM request_idempotency WHERE rowid=?", (old["rowid"],))
        maintenance = store.maintenance_status(db)
        mode = maintenance.get("mode", maintenance.get("maintenance_mode", "normal"))
        repair = request.url.path.endswith("/admin/maintenance") or "/admin/recovery/" in request.url.path
        if mode != "normal" and not repair:
            raise HTTPException(503, "平台正在维护，此操作暂不可提交", headers={"Retry-After": "5"})
        result = operation()
        if not isinstance(result, (dict, list)):
            raise TypeError("Idempotent platform operations must return JSON values")
        retention = getattr(request.app.state, "orchestration_settings", {}).get("receipt_retention_seconds", 604800)
        db.execute("INSERT INTO request_idempotency(uid,action,request_key,request_hash,response_ref,response_ciphertext,created,expires) VALUES(?,?,?,?,?,?,?,?)",
                   (user["uid"], action, request_key, fingerprint, json.dumps(_job_ids(result)), store.encrypt(result), now(), now() + retention))
        return result


def _job_ids(result):
    if not isinstance(result, dict):
        return []
    values = result.get("jobs", []) + ([result["job"]] if result.get("job") else [])
    if result.get("job_id"):
        values.append({"id": result["job_id"]})
    return sorted({value["id"] for value in values if isinstance(value, dict) and isinstance(value.get("id"), str)})


def _unclosed(db, reference):
    if not reference:
        return False
    for jid in json.loads(reference):
        if db.execute("SELECT 1 FROM jobs WHERE id=? AND (status IN ('queued','running') OR recovery_required=1)", (jid,)).fetchone():
            return True
        if db.execute("SELECT 1 FROM job_attempts WHERE job_id=? AND outcome IS NULL", (jid,)).fetchone():
            return True
    return False
