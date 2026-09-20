"""Synthetic catalog, migration, binding, and credential-boundary regression."""
import io
import json
import sqlite3
import zipfile

from client_helpers import TestClient
import httpx
import pytest

from control.store import Store, digest, encode, now
from control.worker_api import runtime_spec
from test_control import context, create_user, login_user, P, PASSWORD


def create_connection(admin, **extra):
    response = admin.post(P + "/admin/connections", json={"name": "Synthetic lookup", "base_url": "http://synthetic-service:8099/api",
        "auth_type": "bearer", "secret": "synthetic-private-service-key", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def publish(admin, version="1.0.0", declared=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"id": "service-fixture", "version": version, "entry": "entry.mjs", "name": "Synthetic service",
            "connections": {"records": {"description": "Lookup records"}} if declared is None else declared,
            "tools": ["fixture_lookup"], "config_schema": {"type": "object", "properties": {}, "additionalProperties": False}}))
        archive.writestr("entry.mjs", "export default async () => ({})")
    return admin.post(P + "/admin/plugins", files={"file": ("fixture.zip", output.getvalue())})


def install(context, *, version="1.0.0"):
    store, app, admin = context
    account = create_user(admin)
    assert admin.patch(P + "/admin/users/" + account["id"], json={"plugin_ids": ["service-fixture"]}).status_code == 200
    user = login_user(app, account["username"])
    response = user.put(P + "/plugins/service-fixture", json={"version": version, "config": {}})
    assert response.status_code == 200, response.text
    return account, user


def test_public_branding_and_super_only_cookie_and_bearer(context, monkeypatch):
    s, app, superuser = context
    monkeypatch.setenv("PLATFORM_NAME", "Fixture platform")
    with TestClient(app) as public:
        assert public.get(P + "/platform").json() == {"name": "Fixture platform", "short_name": "AI", "description": "你的智能助手与工具空间"}
        assert public.get(P + "/admin/connections").status_code == 401
    connection = create_connection(superuser)
    assert publish(superuser).status_code == 200
    manager = superuser.post(P + "/admin/users", json={"username": "manager-a", "password": PASSWORD, "role": "admin"}).json()["user"]
    person = create_user(superuser)
    for account in (manager, person):
        with login_user(app, account["username"]) as actor:
            for client in (actor, TestClient(app)):
                if client is not actor:
                    token = actor.post(P + "/tokens", json={"name": "synthetic"}).json()["token"]
                    client.headers["Authorization"] = "Bearer " + token
                assert client.get(P + "/admin/connections").status_code == 403
                assert client.post(P + "/admin/connections", json={"name": "attempt"}).status_code == 403
                assert client.patch(P + "/admin/connections/" + connection["id"], json={"enabled": False}).status_code == 403
                assert client.post(P + "/admin/connections/" + connection["id"] + "/test", json={"path": "/health"}).status_code == 403
                assert client.delete(P + "/admin/connections/" + connection["id"]).status_code == 403
                assert client.put(P + "/admin/plugins/service-fixture/1.0.0/connections", json={"bindings": {}}).status_code == 403
                assert client.get(P + "/admin/plugins/service-fixture/1.0.0/connections").status_code == 403
    audit = superuser.get(P + "/admin/audit", params={"action": "connection.update", "result": "denied"}).json()["items"]
    assert {row["actor_role"] for row in audit} == {"admin", "user"}
    assert all(row["target"] == connection["id"] for row in audit)
    assert "synthetic-private-service-key" not in json.dumps(superuser.get(P + "/admin/audit").json())


def test_connection_credentials_validation_and_atomic_fields(context):
    s, _, admin = context
    connection = create_connection(admin)
    assert connection["secret_configured"] is True
    assert "secret" not in connection and "synthetic-private-service-key" not in json.dumps(connection)
    row = s.one("SELECT * FROM connections WHERE id=?", (connection["id"],))
    assert "synthetic-private-service-key" not in row["secret"]
    assert s.decrypt(row["secret"]) == "synthetic-private-service-key"
    before = dict(row)
    response = admin.patch(P + "/admin/connections/" + connection["id"], json={"name": "changed", "role": "super_admin"})
    assert response.status_code == 400
    assert s.one("SELECT * FROM connections WHERE id=?", (connection["id"],)) == before
    assert admin.patch(P + "/admin/connections/" + connection["id"], json={"name": "retained", "secret": ""}).status_code == 200
    assert s.decrypt(s.one("SELECT secret FROM connections WHERE id=?", (connection["id"],))["secret"]) == "synthetic-private-service-key"
    assert admin.patch(P + "/admin/connections/" + connection["id"], json={"auth_type": "api_key"}).status_code == 400
    for fields in ({"base_url": "http://user:secret@host"}, {"base_url": "http://host/api/../else"}, {"allowed_paths": ["/%2e%2e/secret"]},
                   {"allowed_paths": ["/health?url=other"]}, {"timeout_seconds": True}, {"max_response_bytes": 100},
                   {"auth_type": "api_key", "header_name": "Host", "secret": "synthetic"}):
        assert admin.patch(P + "/admin/connections/" + connection["id"], json=fields).status_code == 400
    clear = admin.patch(P + "/admin/connections/" + connection["id"], json={"auth_type": "none"})
    assert clear.json()["connection"]["secret_configured"] is False
    assert admin.delete(P + "/admin/connections/" + connection["id"]).status_code == 200


def test_bindings_are_version_scoped_and_specs_split_credentials(context):
    s, app, admin = context
    connection = create_connection(admin)
    assert publish(admin).status_code == 200
    account, user = install(context)
    try:
        before = runtime_spec(s, account["id"], s.one("SELECT desired FROM runtimes WHERE uid=?", (account["id"],))["desired"])
        assert before["connections"] == [] and before["plugins"] == []
        assert user.get(P + "/plugins").json()["items"][0]["installed"]["state"] == "unconfigured"
        assert user.post(P + "/plugins/service-fixture/test").json()["connection_tested"] is False
        other = create_user(admin, "other-user")
        unrelated = s.one("SELECT desired FROM runtimes WHERE uid=?", (other["id"],))["desired"]
        result = admin.put(P + "/admin/plugins/service-fixture/1.0.0/connections", json={"bindings": {"records": connection["id"]}})
        assert result.status_code == 200
        revision = s.one("SELECT desired FROM runtimes WHERE uid=?", (account["id"],))["desired"]
        first = runtime_spec(s, account["id"], revision)
        assert first == runtime_spec(s, account["id"], revision)
        assert len(first["connections"]) == 1 and first["connections"][0]["allowed_user"] == account["id"]
        assert first["connections"][0]["headers"] == {"Authorization": "Bearer synthetic-private-service-key"}
        platform = first["plugins"][0]["platform_connections"]
        assert set(platform["records"]) == {"id", "token"}
        assert platform["records"]["token"] == first["connections"][0]["token"]
        for public in (first["plugins"], first["config"], first["skills"], user.get(P + "/plugins").json()):
            assert "synthetic-private-service-key" not in json.dumps(public) and "synthetic-service" not in json.dumps(public)
        assert admin.delete(P + "/admin/connections/" + connection["id"]).status_code == 409
        edit = admin.patch(P + "/admin/connections/" + connection["id"], json={"timeout_seconds": 20})
        assert {job["uid"] for job in edit.json()["jobs"]} == {account["id"]}
        current = s.one("SELECT desired FROM runtimes WHERE uid=?", (account["id"],))["desired"]
        assert runtime_spec(s, account["id"], current)["connections"][0]["token"] != first["connections"][0]["token"]
        assert s.one("SELECT desired FROM runtimes WHERE uid=?", (other["id"],))["desired"] == unrelated
        assert publish(admin, "2.0.0").status_code == 200
        assert admin.get(P + "/admin/plugins/service-fixture/2.0.0/connections").json()["bindings"] == {}
        bad = admin.put(P + "/admin/plugins/service-fixture/1.0.0/connections", json={"bindings": {"undeclared": connection["id"]}})
        assert bad.status_code == 400
        assert admin.get(P + "/admin/plugins/service-fixture/1.0.0/connections").json()["bindings"] == {"records": connection["id"]}
        assert admin.patch(P + "/admin/connections/" + connection["id"], json={"enabled": False}).status_code == 200
        last = s.one("SELECT desired FROM runtimes WHERE uid=?", (account["id"],))["desired"]
        assert runtime_spec(s, account["id"], last)["plugins"] == []
        assert user.get(P + "/plugins").json()["items"][0]["installed"]["state"] == "unconfigured"
    finally:
        user.__exit__(None, None, None)


def test_schema_two_upgrade_never_promotes_new_admin_or_revokes_auth(context, monkeypatch):
    s, _, admin = context
    manager = admin.post(P + "/admin/users", json={"username": "v2-manager", "password": PASSWORD, "role": "admin"}).json()["user"]
    from r2_helpers import strip_v4
    strip_v4(s)
    monkeypatch.setenv("PX_ALLOW_V4_MIGRATION", "1")
    with s.tx() as db:
        db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)", (digest("synthetic-manager-token"), manager["id"], "token", "fixture", None, now()+600, 1, now()))
        db.execute("DROP TABLE plugin_connections")
        db.execute("DROP TABLE connections")
        db.execute("DELETE FROM audit WHERE target='control.connections.v3'")
        db.execute("PRAGMA user_version=2")
    args = (s.root, s.root.parent / "key", s.root.parent / "worker", s.root.parent / "admin")
    for _ in range(2):
        reopened = Store(*args)
        assert reopened.schema_version() == 4
        assert reopened.user(manager["id"])["role"] == "admin"
        assert reopened.one("SELECT * FROM auth WHERE hash=?", (digest("synthetic-manager-token"),))
        assert reopened.one("SELECT count(*) AS n FROM audit WHERE target='control.connections.v3'")["n"] == 1


def test_schema_three_migration_rollback(context):
    s, _, _ = context
    with s.tx() as db:
        db.execute("DROP TABLE plugin_connections")
        db.execute("DROP TABLE connections")
        db.execute("PRAGMA user_version=2")
    class InterruptedStore(Store):
        def migrate_connections(self, db):
            super().migrate_connections(db)
            raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        InterruptedStore(s.root, s.root.parent / "key", s.root.parent / "worker", s.root.parent / "admin")
    with sqlite3.connect(s.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='connections'").fetchone() is None


def test_admin_connection_test_returns_no_upstream_body(context):
    _, app, admin = context
    connection = create_connection(admin)
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={"synthetic_private_data": "must not appear in test response"})
    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    try:
        result = admin.post(P + "/admin/connections/" + connection["id"] + "/test", json={"method": "GET", "path": "/health"})
        assert result.json() == {"ok": True, "message": "服务连接成功，已确认 JSON 响应", "status": 200}
        assert len(seen) == 1 and str(seen[0].url) == "http://synthetic-service:8099/api/health"
        assert seen[0].headers["Authorization"] == "Bearer synthetic-private-service-key"
        assert "must not appear" not in result.text
    finally:
        admin.portal.call(app.state.http.aclose)
        app.state.http = original


def test_fixed_request_rule_survives_runtime_spec(context):
    s,app,admin=context
    rules=[{'method':'GET','path':'/health'},{'method':'POST','path':'/v1/demo/records/query','json':{'module':'funds'}}]
    connection=create_connection(admin,allowed_methods=['GET','POST'],allowed_paths=['/health','/v1/demo/records/query'],request_rules=rules)
    assert connection['request_rules']==rules
    assert publish(admin).status_code==200
    response=admin.put(P+'/admin/plugins/service-fixture/1.0.0/connections',json={'bindings':{'records':connection['id']}})
    assert response.status_code==200,response.text
    account,user=install(context)
    try:
        runtime=s.one('SELECT desired FROM runtimes WHERE uid=?',(account['id'],))
        spec=runtime_spec(s,account['id'],runtime['desired'])
        assert spec['connections'][0]['request_rules']==rules
    finally:user.__exit__(None,None,None)
