"""Synthetic HTTP acceptance of three roles. Requires an upgraded local console.

Creates isolated test accounts, never resets an existing human account, and
deactivates its test accounts on completion. Credentials stay in .secrets.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import argparse
import io
import json
from pathlib import Path
import re
import secrets
import time
import uuid
import zipfile

import httpx

ROOT = Path(__file__).resolve().parent
PREFIX = "/api/console/v1"


def route_name(path):
    """Report route templates, never account, session or credential identifiers."""
    path = path.removeprefix(PREFIX)
    static = {"/auth/login", "/me", "/me/password", "/tokens", "/sessions", "/files", "/skills",
              "/admin/users", "/admin/models", "/admin/plugins", "/admin/templates", "/admin/jobs", "/admin/audit"}
    if path in static:
        return path
    patterns = (
        (r"/admin/users/[^/]+(/reset-password|/runtime/(?:pause|resume|retry|apply))?", "/admin/users/{user_id}"),
        (r"/admin/models/[^/]+(/test)?", "/admin/models/{model_id}"),
        (r"/sessions/[^/]+(/messages)?", "/sessions/{session_id}"),
        (r"/skills/[^/]+(/rollback)?", "/skills/{skill_id}"),
        (r"/plugins/[^/]+", "/plugins/{plugin_id}"),
        (r"/tokens/[^/]+", "/tokens/{token_id}"),
    )
    for pattern, template in patterns:
        match = re.fullmatch(pattern, path)
        if match:
            return template + (match.group(1) or "" if match.lastindex else "")
    if re.fullmatch(r"/admin/plugins/[^/]+/[^/]+", path):
        return "/admin/plugins/{plugin_id}/{version}"
    return "/unrecognized-route"


def cleanup_created(session, accounts, model_id, plugin_id, plugin_published):
    """Attempt every cleanup independently; keep only categorical outcomes."""
    outcomes = {"accounts_deactivated": True, "model_disabled": True, "plugin_disabled": True}
    operations = [("accounts_deactivated", "/admin/users/" + uid, {"active": False}) for uid in accounts]
    if model_id:
        operations.append(("model_disabled", "/admin/models/" + model_id, {"enabled": False}))
    if plugin_published:
        operations.append(("plugin_disabled", "/admin/plugins/" + plugin_id + "/1.0.0", {"enabled": False}))
    for category, path, body in operations:
        try:
            passed = session is not None and session.patch(path, json=body).status_code == 200
        except Exception:
            passed = False
        outcomes[category] = outcomes[category] and passed
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:14090")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.base_url not in ("http://127.0.0.1:14090", "http://127.0.0.1:14093"):
        raise RuntimeError("Acceptance is restricted to the local console or local synthetic fixture")
    if not args.execute:
        print("Pass --execute to create synthetic test accounts and run local HTTP checks.")
        return
    stamp = uuid.uuid4().hex[:10]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "checks": [],
              "layer": "local_http", "model_inference": "not_executed"}
    credential_path = ROOT / ".secrets" / ("roles-acceptance-" + stamp + ".json")
    credential_path.parent.mkdir(exist_ok=True)
    private = {}

    def check(name, condition):
        report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise RuntimeError("role_acceptance_check_failed:" + name)

    def value(response, expected=(200, 201, 202)):
        check("http_" + response.request.method + "_" + route_name(response.request.url.path), response.status_code in expected)
        return response.json()

    def save_private():
        credential_path.write_text(json.dumps(private), encoding="utf-8")

    with ExitStack() as stack:
        def client():
            return stack.enter_context(httpx.Client(base_url=args.base_url + PREFIX, trust_env=False,
                headers={"Origin": args.base_url}, timeout=30))

        def login(name, password, *, synthetic=False):
            session = client()
            data = value(session.post("/auth/login", json={"username": name, "password": password}))
            session.headers["X-CSRF-Token"] = data["csrf_token"]
            if data["user"]["must_change_password"]:
                check("existing_super_admin_password_already_changed", synthetic and name in private)
                replacement = secrets.token_urlsafe(24)
                value(session.post("/me/password", json={"current_password": password, "password": replacement}))
                private[name] = replacement
                save_private()
            return session

        superuser = None
        accounts = []
        model_id = None
        plugin_id = "role-check-" + stamp
        plugin_published = False
        try:
            admin_file = ROOT / ".secrets/console-admin-current.password"
            superuser = login("admin", admin_file.read_text().rstrip("\r\n"))
            check("existing_admin_is_super_admin", value(superuser.get("/me"))["user"]["role"] == "super_admin")
            before = value(superuser.get("/admin/users"))["capacity"]
            check("runtime_capacity_available_before_test_creation", before["reserved"] < before["maximum"])
            name = "role-admin-" + stamp
            created = value(superuser.post("/admin/users", json={"username": name, "role": "admin"}))
            accounts.append(created["user"]["id"])
            private[name] = created["password"]
            save_private()
            check("admin_created_without_runtime_or_job", created["user"]["runtime"] is None and created.get("job") is None)
            check("admin_does_not_consume_runtime_capacity", value(superuser.get("/admin/users"))["capacity"] == before)
            administrator = login(name, private[name], synthetic=True)
            admin_me = value(administrator.get("/me"))
            check("admin_capabilities_limited", set(admin_me["capabilities"]) == {"users.manage", "models.manage", "audit.read"})
            token = value(administrator.post("/tokens", json={"name": "synthetic-role-check"}))
            bearer = client()
            bearer.headers["Authorization"] = "Bearer " + token["token"]
            check("bearer_identifies_admin", value(bearer.get("/me"))["user"]["role"] == "admin")
            for route in ("/admin/plugins", "/admin/templates", "/admin/jobs", "/sessions", "/files", "/skills"):
                check("admin_denied_" + route, administrator.get(route).status_code == 403)
                check("bearer_denied_" + route, bearer.get(route).status_code == 403)
            for route in ("/admin/plugins", "/admin/templates"):
                check("admin_publish_denied_" + route, administrator.post(route, json={}).status_code == 403)
            super_id = value(superuser.get("/me"))["user"]["id"]
            for uid in (accounts[0], super_id):
                check("admin_cannot_disable_management_account", administrator.patch("/admin/users/" + uid, json={"active": False}).status_code in (403, 404))
                check("admin_cannot_reset_management_account", administrator.post("/admin/users/" + uid + "/reset-password", json={}).status_code in (403, 404))
            for body in ({"role": "admin"}, {"role": "user"}, {"plugin_ids": []}):
                check("admin_rejects_forbidden_create_fields", administrator.post("/admin/users", json={"username": "role-forged-" + stamp, **body}).status_code == 403)

            ordinary_name = "role-user-" + stamp
            ordinary = value(administrator.post("/admin/users", json={"username": ordinary_name}))
            uid = ordinary["user"]["id"]
            accounts.insert(0, uid)
            private[ordinary_name] = ordinary["password"]
            save_private()
            check("ordinary_user_auto_provision_queued", bool(ordinary["job"]) and ordinary["user"]["runtime"] is not None)
            user = login(ordinary_name, private[ordinary_name], synthetic=True)
            check("ordinary_capability", value(user.get("/me"))["capabilities"] == ["business.use"])
            check("ordinary_management_denied", user.get("/admin/users").status_code == 403)
            check("admin_runtime_control_denied", administrator.post("/admin/users/" + uid + "/runtime/pause", json={}).status_code == 403)
            model = value(administrator.post("/admin/models", json={"name": "角色验收合成模型", "description": "仅测试配置权限，不执行推理", "base_url": "http://127.0.0.1:9/v1", "model_id": "synthetic-role-model", "enabled": True}))
            model_id = model["id"]
            check("model_connection_test_available", value(administrator.post("/admin/models/" + model_id + "/test", json={})) ["ok"] is False)
            manifest = {"id": plugin_id, "version": "1.0.0", "name": "角色权限合成插件", "entry": "entry.mjs", "tools": [],
                "config_schema": {"type": "object", "properties": {"marker": {"type": "string", "title": "合成标记"}}, "additionalProperties": False}}
            content = io.BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("entry.mjs", "export default async()=>({});export async function test(){return {ok:true,message:'synthetic'}}")
            value(superuser.post("/admin/plugins", files={"file": ("synthetic.zip", content.getvalue(), "application/zip")}))
            plugin_published = True
            value(superuser.patch("/admin/users/" + uid, json={"plugin_ids": [plugin_id]}))
            value(administrator.patch("/admin/users/" + uid, json={"model_ids": [model_id]}))
            records = value(superuser.get("/admin/users"))["items"]
            own = next(item for item in records if item["id"] == uid)
            check("model_grant_preserves_plugin_grant", own["plugin_ids"] == [plugin_id] and own["model_ids"] == [model_id])
            for body in ({"model_ids": [], "plugin_ids": []}, {"active": False, "role": "super_admin"}):
                check("mixed_request_rejected", administrator.patch("/admin/users/" + uid, json=body).status_code == 403)
            after = next(item for item in value(superuser.get("/admin/users"))["items"] if item["id"] == uid)
            check("mixed_request_has_no_partial_effect", after["active"] and after["model_ids"] == [model_id] and after["plugin_ids"] == [plugin_id])
            skill = value(user.post("/skills", json={"name": "角色验收技能", "description": "合成", "content": "仅处理合成验收资料"}))
            value(user.patch("/skills/" + skill["id"], json={"content": "更新合成验收指令"}))
            value(user.post("/skills/" + skill["id"] + "/rollback", json={}))
            value(user.put("/plugins/" + plugin_id, json={"version": "1.0.0", "enabled": True, "config": {"marker": "synthetic"}}))
            check("ordinary_personal_features_preserved", any(item["id"] == skill["id"] for item in value(user.get("/skills"))["items"]))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                state = value(user.get("/me"))["user"]["runtime"]["status"]
                if state == "ready":
                    break
                if state == "failed":
                    raise RuntimeError("synthetic_environment_failed")
                time.sleep(3)
            check("ordinary_environment_automatically_ready", state == "ready")
            session = value(user.post("/sessions", json={"title": "角色权限合成会话"}))
            check("ordinary_session_works", any(item["id"] == session["id"] for item in value(user.get("/sessions"))["items"]))
            for management in (superuser, administrator):
                check("management_private_session_denied", management.get("/sessions/" + session["id"] + "/messages").status_code == 403)
            user_token = value(user.post("/tokens", json={"name": "revocation-synthetic"}))
            old_token = client()
            old_token.headers["Authorization"] = "Bearer " + user_token["token"]
            reset = value(administrator.post("/admin/users/" + uid + "/reset-password", json={}))
            private[ordinary_name] = reset["password"]
            save_private()
            check("reset_revokes_cookie", user.get("/me").status_code == 401)
            check("reset_revokes_token", old_token.get("/me").status_code == 401)
            user = login(ordinary_name, private[ordinary_name], synthetic=True)
            value(administrator.patch("/admin/users/" + uid, json={"active": False}))
            check("deactivation_revokes_login", user.get("/me").status_code == 401)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                record = next(item for item in value(administrator.get("/admin/users"))["items"] if item["id"] == uid)
                if record["runtime"]["status"] == "paused":
                    break
                time.sleep(2)
            check("deactivation_stops_environment", record["runtime"]["status"] == "paused")
            value(administrator.patch("/admin/users/" + uid, json={"active": True}))
            user = login(ordinary_name, private[ordinary_name], synthetic=True)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                state = value(user.get("/me"))["user"]["runtime"]["status"]
                if state in ("ready", "failed"):
                    break
                time.sleep(3)
            check("admin_reactivation_resumes_environment", state == "ready")
            check("reactivation_preserves_session", any(item["id"] == session["id"] for item in value(user.get("/sessions"))["items"]))
            check("reactivation_preserves_skill", any(item["id"] == skill["id"] for item in value(user.get("/skills"))["items"]))
            audit = value(administrator.get("/admin/audit", params={"result": "denied"}))["items"]
            check("denied_operations_audited", bool(audit) and all(item["result"] == "denied" for item in audit))
            check("audit_has_actor_role", all("actor_role" in item and "created" in item for item in audit))
            serialized = json.dumps(audit)
            check("audit_excludes_credentials", not any(password in serialized for password in private.values()) and token["token"] not in serialized)
            value(administrator.delete("/tokens/" + token["item"]["id"]))
            check("administrator_token_revocation", bearer.get("/me").status_code == 401)
            report["status"] = "passed"
        except Exception as error:
            report["error"] = str(error) if isinstance(error, RuntimeError) else "role_acceptance_failed"
            raise
        finally:
            outcomes = cleanup_created(superuser, accounts, model_id, plugin_id, plugin_published)
            cleanup = all(outcomes.values())
            report["cleanup"] = outcomes
            report["synthetic_accounts_deactivated"] = outcomes["accounts_deactivated"]
            report["passed"] = sum(item["passed"] for item in report["checks"])
            report["failed"] = len(report["checks"]) - report["passed"]
            if not cleanup or "status" not in report:
                report["status"] = "failed"
            target = ROOT / "output/role-acceptance.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": report["status"], "passed": report["passed"], "failed": report["failed"], "cleanup": cleanup}))
        if report["status"] != "passed":
            raise RuntimeError("role_acceptance_cleanup_failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "code": str(error) if isinstance(error, RuntimeError) else "role_acceptance_failed"}))
        raise SystemExit(1) from None
