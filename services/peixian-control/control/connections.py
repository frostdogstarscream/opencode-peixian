from .concurrency import blocking_endpoint
"""Super administrator service catalog and immutable plugin-alias declarations."""
import json
import re

from fastapi import Depends, Request

from shared.connection_policy import ConnectionFailure, HEADER, FORBIDDEN_HEADERS, exchange, policy
from .store import encode, ident

ALIAS = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
FIELDS = {"name", "base_url", "auth_type", "secret", "header_name", "allowed_methods", "allowed_paths",
          "timeout_seconds", "max_response_bytes", "enabled"}
DEFAULTS = {"auth_type": "none", "header_name": "", "allowed_methods": ["GET"], "allowed_paths": ["/health"],
            "timeout_seconds": 15, "max_response_bytes": 1048576, "enabled": True}


def aliases(manifest):
    values = manifest.get("connections", {})
    if not isinstance(values, dict) or len(values) > 20:
        raise ValueError("插件连接声明必须为有限的别名对象")
    for key, value in values.items():
        if (not ALIAS.fullmatch(key) or not isinstance(value, dict) or set(value) - {"description"}
                or not isinstance(value.get("description", ""), str) or len(value.get("description", "")) > 500):
            raise ValueError("插件连接别名或说明无效")
    return values


def connection_public(store, row):
    return {"id": row["id"], **json.loads(row["config"]), "revision": row["revision"],
            "secret_configured": bool(store.decrypt(row["secret"]))}


def connection_headers(store, row):
    value = json.loads(row["config"])
    secret = store.decrypt(row["secret"])
    if value["auth_type"] == "none":
        return {}
    return {"Authorization": "Bearer " + secret} if value["auth_type"] == "bearer" else {value["header_name"]: secret}


def resolved_bindings(db, plugin, version, manifest):
    declared = aliases(manifest)
    rows = {row["alias"]: dict(row) for row in db.execute(
        "SELECT b.alias,c.* FROM plugin_connections b JOIN connections c ON c.id=b.connection_id WHERE b.plugin=? AND b.version=?",
        (plugin, version))}
    missing = [alias for alias in declared if alias not in rows or not json.loads(rows[alias]["config"])["enabled"]]
    return rows, missing


def register_connections(app):
    from .app import PREFIX, body_fields, own_id, fail, require_capability

    permission = require_capability("connections.manage")

    def data(value, old=None):
        body_fields(value, FIELDS)
        base = json.loads(old["config"]) if old else DEFAULTS
        merged = {**base, **{k: v for k, v in value.items() if k != "secret"}}
        if not isinstance(merged.get("name"), str) or not 1 <= len(merged["name"].strip()) <= 100:
            fail("连接名称应为 1 至 100 个字符")
        merged["name"] = merged["name"].strip()
        if type(merged.get("enabled")) is not bool or merged.get("auth_type") not in ("none", "bearer", "api_key"):
            fail("连接启用状态或鉴权类型无效")
        if merged["auth_type"] == "api_key":
            header = merged.get("header_name") or "X-API-Key"
            if not isinstance(header, str) or not HEADER.fullmatch(header) or header.lower() in FORBIDDEN_HEADERS or header.lower() == "authorization":
                fail("API Key 请求头名称无效")
            merged["header_name"] = header
        else:
            merged["header_name"] = ""
        secret = value.get("secret")
        if secret is not None and (not isinstance(secret, str) or len(secret) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in secret)):
            fail("连接凭据格式无效")
        same_auth = old and all(base[k] == merged[k] for k in ("auth_type", "header_name"))
        if merged["auth_type"] == "none":
            secret = ""
        elif not secret:
            secret = app.state.store.decrypt(old["secret"]) if same_auth else ""
            if not secret:
                fail("请配置服务鉴权凭据")
        try:
            return policy(merged), app.state.store.encrypt(secret)
        except ConnectionFailure as exc:
            fail(str(exc))

    def affected(db, *, cid=None, plugin=None, version=None):
        condition, args = ("b.connection_id=?", (cid,)) if cid else ("i.plugin=? AND i.version=?", (plugin, version))
        return [row[0] for row in db.execute(
            "SELECT DISTINCT i.uid FROM installs i JOIN plugin_connections b ON b.plugin=i.plugin AND b.version=i.version "
            "JOIN plugins p ON p.id=i.plugin AND p.version=i.version JOIN grants g ON g.uid=i.uid AND g.kind='plugin' AND g.resource=i.plugin "
            "WHERE i.enabled=1 AND p.enabled=1 AND " + condition, args)]

    def queue(db, users):
        return [app.state.store.queue_in_transaction(db, uid) for uid in users]

    @app.get(PREFIX + "/admin/connections")
    @blocking_endpoint(app)
    def connections_list(request: Request, user=Depends(permission)):
        s = app.state.store
        return {"items": [connection_public(s, row) for row in s.rows("SELECT * FROM connections ORDER BY rowid DESC")]}

    @app.post(PREFIX + "/admin/connections")
    @blocking_endpoint(app, json_body=True)
    def connection_create(request: Request, user=Depends(permission)):
        s = app.state.store
        config, secret = data(request.state.json_body)
        cid = ident()
        with s.tx() as db:
            db.execute("INSERT INTO connections VALUES(?,?,?,1)", (cid, encode(config), secret))
        request.state.management_target = cid
        return connection_public(s, s.one("SELECT * FROM connections WHERE id=?", (cid,)))

    @app.patch(PREFIX + "/admin/connections/{cid}")
    @blocking_endpoint(app, json_body=True)
    def connection_edit(cid: str, request: Request, user=Depends(permission)):
        s = app.state.store
        raw = request.state.json_body
        with s.tx() as db:
            old = db.execute("SELECT * FROM connections WHERE id=?", (own_id(cid),)).fetchone()
            if not old:
                fail("服务连接不存在", 404)
            config, secret = data(raw, old)
            users = affected(db, cid=cid)
            db.execute("UPDATE connections SET config=?,secret=?,revision=revision+1 WHERE id=?", (encode(config), secret, cid))
            jobs = queue(db, users)
        return {"connection": connection_public(s, s.one("SELECT * FROM connections WHERE id=?", (cid,))), "jobs": jobs}

    @app.delete(PREFIX + "/admin/connections/{cid}")
    @blocking_endpoint(app)
    def connection_delete(cid: str, request: Request, user=Depends(permission)):
        with app.state.store.tx() as db:
            if db.execute("SELECT 1 FROM plugin_connections WHERE connection_id=?", (own_id(cid),)).fetchone():
                fail("此连接仍被插件版本引用，请先解除绑定或停用连接", 409)
            if not db.execute("DELETE FROM connections WHERE id=?", (cid,)).rowcount:
                fail("服务连接不存在", 404)
        return {"ok": True}

    @app.post(PREFIX + "/admin/connections/{cid}/test")
    async def connection_test(cid: str, request: Request, user=Depends(permission)):
        s = app.state.store
        row = await app.state.db_work.run(s.one, "SELECT * FROM connections WHERE id=?", (own_id(cid),))
        if not row:
            fail("服务连接不存在", 404)
        config = json.loads(row["config"])
        if not config["enabled"]:
            fail("此连接已停用", 409)
        try:
            headers = await app.state.db_work.run(connection_headers, s, row)
            result = await exchange(app.state.http, {**config, "headers": headers}, await request.json())
        except ConnectionFailure as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "服务连接成功，已确认 JSON 响应", "status": result["status"]}

    def plugin_version(db, pid, version):
        row = db.execute("SELECT manifest FROM plugins WHERE id=? AND version=?", (own_id(pid), version)).fetchone()
        if not row:
            fail("插件版本不存在", 404)
        return aliases(json.loads(row["manifest"]))

    @app.get(PREFIX + "/admin/plugins/{pid}/{version}/connections")
    @blocking_endpoint(app)
    def plugin_connections_get(pid: str, version: str, request: Request, user=Depends(permission)):
        with app.state.store.read(snapshot=True) as db:
            declared = plugin_version(db, pid, version)
            values = {row["alias"]: row["connection_id"] for row in db.execute("SELECT alias,connection_id FROM plugin_connections WHERE plugin=? AND version=?", (pid, version))}
        return {"aliases": declared, "bindings": values}

    @app.put(PREFIX + "/admin/plugins/{pid}/{version}/connections")
    @blocking_endpoint(app, json_body=True)
    def plugin_connections_put(pid: str, version: str, request: Request, user=Depends(permission)):
        raw = body_fields(request.state.json_body, ("bindings",))
        values = raw.get("bindings")
        if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
            fail("插件连接绑定格式不正确")
        s = app.state.store
        with s.tx() as db:
            declared = plugin_version(db, pid, version)
            if set(values) - set(declared):
                fail("绑定包含该版本未声明的连接别名")
            for cid in values.values():
                row = db.execute("SELECT config FROM connections WHERE id=?", (own_id(cid),)).fetchone()
                if not row or not json.loads(row["config"])["enabled"]:
                    fail("绑定目标不存在或已停用")
            # Snapshot affected users before replacing bindings, including first-time binding.
            users = [row[0] for row in db.execute("SELECT i.uid FROM installs i JOIN grants g ON g.uid=i.uid AND g.kind='plugin' AND g.resource=i.plugin WHERE i.plugin=? AND i.version=? AND i.enabled=1", (pid, version))]
            db.execute("DELETE FROM plugin_connections WHERE plugin=? AND version=?", (pid, version))
            db.executemany("INSERT INTO plugin_connections VALUES(?,?,?,?)", [(pid, version, alias, cid) for alias, cid in values.items()])
            jobs = queue(db, users)
        request.state.management_target = pid + "@" + version
        return {"aliases": declared, "bindings": values, "jobs": jobs}
