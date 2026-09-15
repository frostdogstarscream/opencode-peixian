import hmac
import json
from pathlib import Path
import secrets

from fastapi import Request, Depends
from fastapi.responses import FileResponse

from .store import now, ident, encode


def runtime_spec(s, uid, revision, *, db=None):
    # Claim passes its own transaction so desired, grants and all configuration
    # rows come from exactly the snapshot that is committed with the lease.
    if db is None:
        with s.tx() as snapshot:
            return runtime_spec(s, uid, revision, db=snapshot)

    def rows(query, args=()):
        return [dict(row) for row in db.execute(query, args)]

    runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
    if runtime is None or runtime["desired"] != revision:
        raise ValueError("Runtime revision changed before configuration was captured")
    private = s.decrypt(runtime["spec"])
    models = rows("SELECT m.* FROM models m JOIN grants g ON g.resource=m.id AND g.kind='model' WHERE g.uid=? AND m.enabled=1 ORDER BY m.is_default DESC,m.id", (uid,))
    model_config = {}
    relay = []
    for m in models:
        model_config[m["id"]] = {"name": m["name"], "limit": {"context": 32768, "output": 2048}, "attachment": False}
        if "api.deepseek.com" in m["base_url"]:
            model_config[m["id"]].update({"interleaved": {"field": "reasoning_content"}, "options": {"thinking": {"type": "disabled"}}, "variants": {"low": {"disabled": True}, "medium": {"disabled": True}, "high": {"disabled": True}}})
        relay.append({"id": m["id"], "upstream_model": m["model_id"], "base_url": m["base_url"], "api_key": s.decrypt(m["secret"]), "allowed_user": uid})
    config = {"enabled_providers": ["peixian"] if models else [], "share": "disabled", "autoupdate": False, "formatter": False, "lsp": False, "mcp": {}, "plugin": [], "skills": {"paths": ["/managed/skills"]}, "permission": {"*": "deny", "read": {"*": "allow", "../*": "deny", "../files/*": "allow", "/*": "deny"}, "edit": {"*": "allow", "../*": "deny", "/*": "deny"}, "glob": "allow", "grep": "allow", "skill": "allow", "question": "allow", "external_directory": {"*": "deny", "/files/*": "allow"}}}
    if models:
        selected = "peixian/" + models[0]["id"]
        config.update(model=selected, small_model=selected, provider={"peixian": {"name": "授权模型", "npm": "@ai-sdk/openai-compatible", "options": {"baseURL": "http://model-relay:8081/v1", "apiKey": "relay-injected"}, "models": model_config}})
        config["agent"] = {name: {"model": selected} for name in ("title", "summary", "compaction")}
    plugins = []
    for installed in rows("SELECT i.*,p.manifest,p.digest FROM installs i JOIN plugins p ON p.id=i.plugin AND p.version=i.version JOIN grants g ON g.uid=i.uid AND g.kind='plugin' AND g.resource=i.plugin WHERE i.uid=? AND i.enabled=1 AND p.enabled=1", (uid,)):
        manifest = json.loads(installed["manifest"])
        plugins.append({"id": installed["plugin"], "version": installed["version"], "manifest": manifest, "digest": installed["digest"], "options": s.decrypt(installed["config"])})
        config["plugin"].append("file:///managed/loaders/" + installed["plugin"] + ".mjs")
        for tool in manifest.get("tools", []):
            if isinstance(tool, str) and tool.replace("_", "").replace("-", "").isalnum() and tool not in ("bash", "pty", "webfetch", "websearch"):
                config["permission"][tool] = "allow"
    return {"uid": uid, "runtime_id": runtime["id"], "revision": revision, "private": private, "config": config, "models": relay, "plugins": plugins, "skills": rows("SELECT id,name,description,content FROM skills WHERE uid=? AND enabled=1", (uid,))}


def register_worker(app):
    from .app import fail, own_id, body_fields

    def worker(request: Request):
        if not hmac.compare_digest(request.headers.get("x-worker-key", ""), app.state.store.worker_key):
            fail("无权访问", 403)
        return True

    @app.get("/internal/worker/busy")
    async def busy(request: Request, authorized=Depends(worker)):
        return {"busy": bool(app.state.store.one("SELECT 1 FROM jobs WHERE status='running' LIMIT 1"))}

    @app.post("/internal/worker/claim")
    async def claim(request: Request, authorized=Depends(worker)):
        s = app.state.store
        with s.tx() as db:
            # A dead worker's lease can be taken over without creating a new job.
            db.execute("UPDATE jobs SET status='queued',lease=NULL WHERE status='running' AND heartbeat<?", (now() - 90,))
            row = db.execute("SELECT j.* FROM jobs j WHERE j.status='queued' AND NOT EXISTS(SELECT 1 FROM jobs active WHERE active.uid=j.uid AND active.status='running') ORDER BY j.created,j.rowid LIMIT 1").fetchone()
            if not row:
                return {"job": None}
            r = db.execute("SELECT desired FROM runtimes WHERE uid=?", (row["uid"],)).fetchone()
            lease = secrets.token_urlsafe(32)
            db.execute("UPDATE jobs SET status='running',lease=?,heartbeat=?,attempts=attempts+1,revision=?,updated=? WHERE id=?", (lease, now(), r["desired"], now(), row["id"]))
            job = dict(row)
            job.update(lease=lease, revision=r["desired"])
            spec = runtime_spec(s, job["uid"], job["revision"], db=db)
        return {"job": {k: job[k] for k in ("id", "uid", "action", "lease", "revision")}, "spec": spec}

    def leased(db, jid, lease):
        job = db.execute("SELECT * FROM jobs WHERE id=? AND status='running'", (own_id(jid),)).fetchone()
        if not job or not hmac.compare_digest(job["lease"] or "", str(lease)):
            fail("工作租约已失效", 409)
        return job

    @app.post("/internal/worker/jobs/{jid}/heartbeat")
    async def heartbeat(jid: str, request: Request, authorized=Depends(worker)):
        data = body_fields(await request.json(), ("lease",))
        with app.state.store.tx() as db:
            leased(db, jid, data.get("lease"))
            db.execute("UPDATE jobs SET heartbeat=?,updated=? WHERE id=?", (now(), now(), jid))
        return {"ok": True}

    @app.post("/internal/worker/jobs/{jid}/complete")
    async def complete(jid: str, request: Request, authorized=Depends(worker)):
        data = body_fields(await request.json(), ("lease", "ok", "deferred", "error", "rolled_back", "cleanup_confirmed"))
        s = app.state.store
        ok = data.get("ok") is True
        deferred = data.get("deferred") is True
        next_job = False
        with s.tx() as db:
            job = leased(db, jid, data.get("lease"))
            r = db.execute("SELECT * FROM runtimes WHERE uid=?", (job["uid"],)).fetchone()
            if deferred:
                db.execute("UPDATE jobs SET status='queued',lease=NULL,heartbeat=NULL,updated=? WHERE id=?", (now(), jid))
                return {"ok": True}
            error = None if ok else "环境操作未完成，请查看管理员操作记录后重试"
            db.execute("UPDATE jobs SET status=?,error=?,lease=NULL,updated=? WHERE id=?", ("succeeded" if ok else "failed", error, now(), jid))
            if ok:
                status = "paused" if job["action"] == "pause" else "ready"
                revision = r["revision"] if job["action"] == "pause" else job["revision"]
                db.execute("UPDATE runtimes SET status=?,revision=?,reserved=?,error=NULL,updated=? WHERE uid=?", (status, revision, status != "paused", now(), job["uid"]))
                next_job = status == "ready" and r["desired"] > job["revision"]
            else:
                rolled_back = data.get("rolled_back") is True and r["revision"] > 0
                db.execute("UPDATE runtimes SET status=?,reserved=?,error=?,updated=? WHERE uid=?", ("ready" if rolled_back else "failed", bool(rolled_back or data.get("cleanup_confirmed") is not True), error, now(), job["uid"]))
        if next_job:
            s.queue(job["uid"])
        return {"ok": True}


    legacy_volumes = {
        "client-a": {"home_volume": "peixian-opencode_client-a-home",
                     "workspace_volume": "peixian-opencode_client-a-workspace"},
        "client-b": {"home_volume": "peixian-opencode_client-b-home",
                     "workspace_volume": "peixian-opencode_client-b-workspace"},
    }

    def legacy_account(db, uid):
        row = db.execute("SELECT u.username,u.role,r.* FROM users u JOIN runtimes r ON r.uid=u.id WHERE u.id=?", (uid,)).fetchone()
        if not row or row["role"] != "user" or row["username"] not in legacy_volumes:
            fail("迁移账号不存在", 404)
        if app.state.store.decrypt(row["spec"]).get("legacy") != legacy_volumes[row["username"]]:
            fail("账号不属于允许的旧环境迁移", 409)
        return row

    def import_record(db, uid, snapshot_id=None):
        for row in db.execute("SELECT target FROM audit WHERE action='legacy.import' ORDER BY created,rowid"):
            value = json.loads(row["target"])
            if value.get("uid") == uid and (snapshot_id is None or value.get("snapshot", {}).get("id") == snapshot_id):
                return value
        fail("迁移快照记录不存在", 404)

    @app.post("/internal/worker/legacy-import", status_code=202)
    async def legacy_import(request: Request, authorized=Depends(worker)):
        import re
        from .app import password_valid
        data = body_fields(await request.json(), ("username", "password", "model_ids", "legacy", "snapshot"))
        username = data.get("username")
        if not isinstance(username, str) or username not in legacy_volumes or data.get("legacy") != legacy_volumes[username]:
            fail("仅支持已核实的 client-a/client-b 固定旧卷", 400)
        password = password_valid(data.get("password"))
        models = data.get("model_ids", [])
        if not isinstance(models, list) or len(models) > 100 or any(not isinstance(value, str) for value in models):
            fail("授权模型格式不正确")
        snapshot = data.get("snapshot")
        if (not isinstance(snapshot, dict) or set(snapshot) != {"id", "sha256"}
                or not isinstance(snapshot["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot["id"])
                or not isinstance(snapshot["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot["sha256"])):
            fail("迁移快照标识或校验值无效")
        s = app.state.store
        existing = s.one("SELECT id FROM users WHERE username=?", (username,))
        created = False
        if existing is None:
            try:
                user, _ = s.create_user(username, password, legacy=legacy_volumes[username], model_ids=models)
                uid = user["id"]
                created = True
            except ValueError as exc:
                # A retry can race the first successful import. It may reuse only
                # the identical fixed legacy mapping, never overwrite the account.
                existing = s.one("SELECT id FROM users WHERE username=?", (username,))
                if existing is None:
                    fail(str(exc), 409)
                uid = existing["id"]
        else:
            uid = existing["id"]
        with s.tx() as db:
            runtime = legacy_account(db, uid)
            record = {"uid": uid, "runtime_id": runtime["id"], "username": username, "snapshot": snapshot}
            serialized = encode(record)
            previous = db.execute("SELECT target FROM audit WHERE action='legacy.import' AND target=?", (serialized,)).fetchone()
            if not previous:
                db.execute("INSERT INTO audit(id,actor,action,target,created,actor_role) VALUES(?,?,?,?,?,'worker')", (ident(), "worker", "legacy.import", serialized, now()))
            result = {"uid": uid, "runtime_id": runtime["id"], "created": created,
                      "status": runtime["status"], "revision": runtime["revision"], "desired": runtime["desired"]}
        return result

    @app.get("/internal/worker/legacy-status/{uid}")
    async def legacy_status(uid: str, request: Request, authorized=Depends(worker)):
        with app.state.store.tx() as db:
            row = legacy_account(db, own_id(uid))
            import_record(db, uid)
            return {"uid": uid, "runtime_id": row["id"], "status": row["status"],
                    "revision": row["revision"], "desired": row["desired"], "reserved": bool(row["reserved"])}

    @app.post("/internal/worker/legacy-rollback")
    async def legacy_rollback(request: Request, authorized=Depends(worker)):
        data = body_fields(await request.json(), ("uid", "snapshot_id", "cleanup_confirmed"))
        if data.get("cleanup_confirmed") is not True:
            fail("执行器必须确认新环境已全部停止", 409)
        uid, snapshot_id = data.get("uid"), data.get("snapshot_id")
        if not isinstance(uid, str) or not isinstance(snapshot_id, str):
            fail("迁移标识无效")
        s = app.state.store
        with s.tx() as db:
            row = legacy_account(db, own_id(uid))
            record = import_record(db, uid, snapshot_id)
            db.execute("UPDATE users SET active=0,auth_version=auth_version+1 WHERE id=?", (uid,))
            db.execute("DELETE FROM auth WHERE uid=?", (uid,))
            db.execute("UPDATE jobs SET status='failed',lease=NULL,heartbeat=NULL,error=?,updated=? WHERE uid=? AND status IN ('queued','running')",
                       ("迁移已由执行器回退", now(), uid))
            db.execute("UPDATE runtimes SET status='failed',reserved=0,error=?,updated=? WHERE uid=?",
                       ("迁移未完成，旧数据保留，请检查后重试", now(), uid))
            db.execute("INSERT INTO audit(id,actor,action,target,created,actor_role) VALUES(?,?,?,?,?,'worker')",
                       (ident(), "worker", "legacy.rollback",
                        encode({"uid": uid, "runtime_id": row["id"], "snapshot": record["snapshot"], "cleanup_confirmed": True}), now()))
        return {"ok": True, "uid": uid, "runtime_id": row["id"], "status": "failed"}

    @app.post("/internal/worker/legacy-retry", status_code=202)
    async def legacy_retry(request: Request, authorized=Depends(worker)):
        data = body_fields(await request.json(), ("uid", "snapshot_id", "legacy_stopped"))
        if data.get("legacy_stopped") is not True:
            fail("执行器必须确认旧服务和所有数据卷写入者均已停止", 409)
        uid, snapshot_id = data.get("uid"), data.get("snapshot_id")
        if not isinstance(uid, str) or not isinstance(snapshot_id, str):
            fail("迁移标识无效")
        s = app.state.store
        with s.tx() as db:
            uid = own_id(uid)
            user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
            if (not user or not runtime or user["role"] != "user" or user["username"] not in legacy_volumes
                    or s.decrypt(runtime["spec"]).get("legacy") != legacy_volumes[user["username"]]):
                fail("迁移账号不存在", 404)
            imported = import_record(db, uid, snapshot_id)
            if imported["runtime_id"] != runtime["id"]:
                fail("迁移记录与运行环境不一致", 409)
            history = []
            for audit in db.execute("SELECT action,target FROM audit WHERE action IN ('legacy.retry','legacy.rollback') ORDER BY created,rowid"):
                value = json.loads(audit["target"])
                if value.get("uid") == uid and value.get("runtime_id") == runtime["id"]:
                    history.append((audit["action"], value))
            repeats = [value for action, value in history
                       if action == "legacy.retry" and value.get("snapshot") == imported["snapshot"]]
            if repeats:
                previous = repeats[-1]
                job = db.execute("SELECT * FROM jobs WHERE id=? AND uid=?", (previous.get("job_id"), uid)).fetchone()
                latest = db.execute("SELECT id FROM jobs WHERE uid=? ORDER BY created DESC,rowid DESC LIMIT 1", (uid,)).fetchone()
                if (not user["active"] or user["auth_version"] != previous.get("auth_version")
                        or not history or history[-1] != ("legacy.retry", previous)
                        or not job or not latest or latest["id"] != job["id"]
                        or job["status"] not in ("queued", "running", "succeeded")
                        or runtime["status"] not in ("provisioning", "ready")):
                    fail("该迁移重试已结束或账号状态已变更，请重新建立快照", 409)
            else:
                if not any(action == "legacy.rollback" and value.get("cleanup_confirmed") is True
                           for action, value in history):
                    fail("该账号没有可重试的迁移回退记录", 409)
                if (user["active"] or runtime["status"] != "failed" or runtime["reserved"]
                        or db.execute("SELECT 1 FROM jobs WHERE uid=? AND status IN ('queued','running')", (uid,)).fetchone()):
                    fail("当前环境状态不允许迁移重试", 409)
                try:
                    job = s.queue_in_transaction(db, uid, "resume")
                except ValueError as exc:
                    fail(str(exc), 409)
                db.execute("UPDATE users SET active=1,auth_version=auth_version+1 WHERE id=?", (uid,))
                db.execute("DELETE FROM auth WHERE uid=?", (uid,))
                db.execute("INSERT INTO audit(id,actor,action,target,created,actor_role) VALUES(?,?,?,?,?,'worker')",
                           (ident(), "worker", "legacy.retry",
                            encode({"uid": uid, "runtime_id": runtime["id"], "snapshot": imported["snapshot"],
                                    "job_id": job["id"], "auth_version": user["auth_version"] + 1,
                                    "legacy_stopped": True}), now()))
            current = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
            return {"uid": uid, "runtime_id": current["id"], "status": current["status"],
                    "revision": current["revision"], "desired": current["desired"], "job_id": job["id"]}

    @app.get("/internal/worker/packages/{sha}")
    async def package(sha: str, request: Request, authorized=Depends(worker)):
        import re
        if not re.fullmatch("[a-f0-9]{64}", sha):
            fail("包不存在", 404)
        path = app.state.store.root / "packages" / (sha + ".zip")
        if not path.is_file() or path.is_symlink():
            fail("包不存在", 404)
        return FileResponse(path, media_type="application/zip")
