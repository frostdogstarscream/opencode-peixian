"""Synthetic acceptance against the isolated HTTPS deployment only; never prints secrets."""
from pathlib import Path
from contextlib import closing
import argparse
import json
import secrets
import ssl
import time
import httpx

ROOT = Path(__file__).resolve().parent
TEST = ROOT / ".runtime/platform-v1-test"
STATE = TEST / "acceptance-private.json"
BASE = "https://127.0.0.1:18443"
PREFIX = "/api/console/v1"
REPORT = ROOT / "output/platform-acceptance.json"

def checked(response):
    if response.status_code not in (200, 201, 202, 204):
        raise RuntimeError(f"http_{response.status_code}:{response.request.url.path}")
    return response.json() if response.content else {}

def client():
    return httpx.Client(base_url=BASE + PREFIX, verify=ssl.create_default_context(cafile=str(TEST / "tls/certificate.pem")),
                        headers={"Origin": BASE}, timeout=90, trust_env=False)

def login(name, password, replacement=None):
    c = client()
    value = checked(c.post("/auth/login", json={"username": name, "password": password}))
    c.headers["X-CSRF-Token"] = value["csrf_token"]
    if value["user"]["must_change_password"]:
        checked(c.post("/me/password", json={"current_password": password, "password": replacement or password}))
        c.close()
        return login(name, replacement or password)
    return c

def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def admin():
    current = TEST / "secrets/admin-current.password"
    if not current.exists():
        current.write_text((TEST / "secrets/console-admin.password").read_text().strip(), encoding="utf-8")
    return login("admin", current.read_text().strip())

def load():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

def ready(c, uid, seconds=240):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = next(v for v in checked(c.get("/admin/users"))["items"] if v["id"] == uid)
        r = value.get("runtime") or {}
        if r.get("status") == "ready" and r.get("revision") == r.get("desired"):
            return value
        if r.get("status") == "failed":
            raise RuntimeError("runtime_failed:" + uid)
        time.sleep(2)
    raise RuntimeError("runtime_ready_timeout:" + uid)

def package(version):
    import io, zipfile
    buffer = io.BytesIO()
    folder = ROOT / "examples/records-plugin"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        z.writestr("entry.mjs", (folder / "entry.mjs").read_text(encoding="utf-8").replace('const VERSION = "1.0.0";', 'const VERSION = "' + version + '";'))
    return buffer.getvalue()

def prepare():
    state = load()
    with closing(admin()) as c:
        if "model" not in state:
            state["model"] = checked(c.post("/admin/models", json={"name": "DeepSeek V4.1 Flash", "description": "合成验收", "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-flash", "api_key": (ROOT / ".secrets/client-a.deepseek-key").read_text().strip(), "enabled": True, "is_default": True}))["id"]
            save(state)
        for version in ("1.0.0", "1.1.0"):
            existing = checked(c.get("/admin/plugins"))["items"]
            if not any(x["id"] == "sample-records" and x["version"] == version for x in existing):
                checked(c.post("/admin/plugins", files={"file": ("sample.zip", package(version), "application/zip")}))
        if "connection" not in state:
            state["connection"] = checked(c.post("/admin/connections", json={"name": "合成资料服务", "base_url": "http://host.docker.internal:18094", "auth_type": "bearer", "secret": (TEST / "sample.key").read_text().strip(), "allowed_methods": ["GET"], "allowed_paths": ["/health", "/records"], "timeout_seconds": 10, "max_response_bytes": 1048576, "enabled": True}))["id"]
            save(state)
        for version in ("1.0.0", "1.1.0"):
            checked(c.put(f"/admin/plugins/sample-records/{version}/connections", json={"bindings": {"records": state["connection"]}}))
        result = checked(c.post(f"/admin/connections/{state['connection']}/test", json={"method": "GET", "path": "/health"}))
        if not result["ok"]:
            raise RuntimeError("synthetic_service_connection_failed")
        for name, role in (("platform-a", "user"), ("platform-b", "user"), ("platform-manager", "admin")):
            if name not in state:
                password = secrets.token_urlsafe(24)
                fields = {"username": name, "password": password, "role": role}
                if role == "user":
                    fields.update(model_ids=[state["model"]], plugin_ids=["sample-records"])
                value = checked(c.post("/admin/users", json=fields))
                state[name] = {"id": value["user"]["id"], "password": password}
                save(state)
        print("synthetic_accounts_created", flush=True)
        for name in ("platform-a", "platform-b"):
            value = ready(c, state[name]["id"])
            state[name]["runtime"] = value["runtime"]["id"]
            save(state)
            print(name + "_runtime_ready", flush=True)
        for name in ("platform-a", "platform-b", "platform-manager"):
            with closing(login(name, state[name]["password"])):
                pass
        print("synthetic_https_preparation_passed", flush=True)

def run():
    state = load()
    report = {"checks": [], "scope": "isolated_https_synthetic"}
    def need(name, value):
        report["checks"].append({"name": name, "passed": bool(value)})
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not value:
            raise RuntimeError(name)
        print("pass:" + name, flush=True)
    with closing(admin()) as su, closing(login("platform-a", state["platform-a"]["password"])) as a, closing(login("platform-b", state["platform-b"]["password"])) as b, closing(login("platform-manager", state["platform-manager"]["password"])) as m:
        need("https_ca_validated", checked(su.get(BASE + "/health"))["schema_version"] == 3)
        need("secure_httponly_cookie", all(c.secure and c.has_nonstandard_attr("HttpOnly") for c in a.cookies.jar))
        need("public_generic_product", checked(su.get("/platform"))["name"] == "Agent 工作台")
        need("https_internal_worker_blocked", su.get(BASE + "/internal/worker/jobs/claim").status_code == 404)
        need("wrong_origin_rejected", a.post("/sessions", json={"title": "reject"}, headers={"Origin": "https://wrong.invalid"}).status_code == 403)
        need("manager_connections_denied", m.get("/admin/connections").status_code == 403)
        need("manager_plugins_denied", m.get("/admin/plugins").status_code == 403)
        need("user_connections_denied", a.get("/admin/connections").status_code == 403)
        need("manager_no_runtime", not checked(m.get("/me"))["user"].get("runtime"))
        need("model_id_real_service_confirmed", checked(su.post(f"/admin/models/{state['model']}/test", json={}))["ok"])
        for name, c, q in (("platform-a", a, "甲"), ("platform-b", b, "乙")):
            checked(c.put("/plugins/sample-records", json={"version": "1.0.0", "enabled": True, "config": {"query": q, "limit": 5}}))
            ready(su, state[name]["id"])
            result = checked(c.post("/plugins/sample-records/test", json={}))
            need(name + "_actual_relay_connection_test", result["ok"] and result.get("supported"))
        need("private_plugin_parameters_separate", checked(a.get("/plugins"))["items"][0]["installed"]["config"]["query"] != checked(b.get("/plugins"))["items"][0]["installed"]["config"]["query"])
        sid = checked(a.post("/sessions", json={"title": "通用平台合成验收"}))["id"]
        state["session"] = sid
        need("session_id_cross_account_denied", b.get(f"/sessions/{sid}/messages").status_code == 404)
        need("admin_cannot_read_personal_session", su.get(f"/sessions/{sid}/messages").status_code == 403)
        skill = checked(a.post("/skills", json={"name": "合成资料整理", "description": "示例插件调用方法", "content": "用户要求查询示例资料时，先调用 platform_sample_records 获取资料，依据真实结果汇总。返回 count 和 version；不要编造。", "enabled": True}))
        state["skill"] = skill["id"]
        ready(su, state["platform-a"]["id"])
        need("personal_skill_loaded", checked(a.post(f"/skills/{state['skill']}/test", json={}))['ok'])
        need("personal_skill_cross_account_denied", b.patch(f"/skills/{state['skill']}", json={"name": "越权"}).status_code == 404)
        f = checked(a.post("/files", files={"file": ("合成资料.csv", "项目,数值\n合成甲,17\n".encode(), "text/csv")}))
        state["file"] = f["id"]
        for _ in range(60):
            parsed = checked(a.get(f"/files/{f['id']}/text"))
            if parsed["status"] in ("ready", "partial", "failed"):
                break
            time.sleep(.5)
        need("csv_file_parsed", parsed["status"] == "ready" and "合成甲" in parsed["text"])
        need("private_file_cross_account_denied", b.get(f"/files/{f['id']}/download").status_code == 404)
        t = checked(a.post("/tokens", json={"name": "合成 Python 验收"}))
        with client() as py:
            py.headers["Authorization"] = "Bearer " + t["token"]
            need("python_token_access", py.get("/sessions").status_code == 200)
            checked(a.delete("/tokens/" + t["item"]["id"]))
            need("revoked_python_token_denied", py.get("/sessions").status_code == 401)
        save(state)
        need("untrusted_model_id_denied", a.post(f"/sessions/{sid}/messages", json={"text": "合成", "model_id": "not-authorized"}).status_code == 403)
    report["status"] = "passed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("prepare", "run"))
    try:
        globals()[p.parse_args().action]()
    except Exception as e:
        print(str(e) if isinstance(e, RuntimeError) else "acceptance_failed:" + type(e).__name__)
        raise SystemExit(1)
