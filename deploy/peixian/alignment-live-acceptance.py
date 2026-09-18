"""Small real-runtime acceptance for a new, isolated alignment deployment.
Credentials stay in root/private.json; reports contain only synthetic checks.
No automatic retry of model messages. Not a concurrency benchmark.
"""
import argparse
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import secrets
import ssl
import time
import uuid
import zipfile
import httpx

REPO = Path(__file__).resolve().parents[2]
PREFIX = "/api/console/v1"

class Acceptance:
    def __init__(self, root):
        self.root = root.resolve()
        self.cfg = json.loads((self.root / "platform.json").read_text())
        assert self.cfg["deployment_id"] == "peixian-alignment-20260917", "isolated deployment required"
        self.path = self.root / "private.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"accounts": {}}
        self.report_path = self.root / "live-report.json"
        self.report = json.loads(self.report_path.read_text()) if self.report_path.exists() else {"scope": "small_real_runtime", "checks": [], "model_requests": []}
        self.clients = ExitStack()

    def save(self):
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2)); self.path.chmod(0o600)

    def record(self, name, **values):
        self.report["checks"].append({"name": name, "status": "passed", **values})
        self.report_path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2))
        print(name, flush=True)

    def client(self):
        # The host cannot hairpin its public NAT address. TLS still verifies the loopback SAN;
        # Origin uses the configured public browser origin, without relaxing server policy.
        return self.clients.enter_context(httpx.Client(base_url="https://127.0.0.1:" + str(self.cfg["https_port"]) + PREFIX,
            headers={"Origin": self.cfg["public_url"]}, verify=ssl.create_default_context(cafile=self.cfg["tls"]["certificate"]),
            timeout=httpx.Timeout(190, connect=10), trust_env=False, follow_redirects=False))

    def request(self, client, method, path, **kwargs):
        if method != "GET": kwargs.setdefault("headers", {})["Idempotency-Key"] = uuid.uuid4().hex
        response = client.request(method, path, **kwargs)
        if not response.is_success:
            raise RuntimeError("http_" + str(response.status_code) + ":" + path)
        return response.json() if response.content else {}

    def login(self, name):
        account = self.state["accounts"][name]
        c = self.client()
        response = c.post("/auth/login", json={"username": name, "password": account["password"]})
        if response.status_code == 401 and account.get("initial_password"):
            response = c.post("/auth/login", json={"username": name, "password": account["initial_password"]})
        if not response.is_success: raise RuntimeError("login_failed:" + name)
        data = response.json(); c.headers["X-CSRF-Token"] = data["csrf_token"]
        if data["user"]["must_change_password"]:
            old = account.get("initial_password", account["password"])
            if "initial_password" not in account:
                account["initial_password"] = old; account["password"] = secrets.token_urlsafe(24); self.save()
            self.request(c, "POST", "/me/password", json={"current_password": old, "password": account["password"]})
            data = self.request(c, "POST", "/auth/login", json={"username": name, "password": account["password"]})
            c.headers["X-CSRF-Token"] = data["csrf_token"]
            account.pop("initial_password", None); self.save()
        return c

    def package(self, version):
        folder = REPO / "deploy/peixian/examples/records-plugin"
        manifest = json.loads((folder / "manifest.json").read_text()); manifest["version"] = version
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            z.writestr("entry.mjs", (folder / "entry.mjs").read_text().replace('const VERSION = "1.0.0";', 'const VERSION = "' + version + '";'))
        return buffer.getvalue()

    def ready(self, c, seconds=300):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = self.request(c, "GET", "/me/runtime")
            if state.get("ready") and state.get("revision") == state.get("desired"):
                return state
            if state.get("status") == "failed": raise RuntimeError("runtime_failed")
            time.sleep(2)
        raise RuntimeError("runtime_ready_timeout")

    def prepare(self, model_key):
        if "admin" not in self.state["accounts"]:
            self.state["accounts"]["admin"] = {"password": (self.root / "runtime/secrets/console-admin.password").read_text().strip()}; self.save()
        su = self.login("admin")
        if "model" not in self.state:
            self.state["model"] = self.request(su, "POST", "/admin/models", json={"name": "DeepSeek Flash", "description": "少量合成联调", "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-flash", "api_key": model_key.read_text().strip(), "enabled": True, "is_default": True})["id"]; self.save()
        for version in ["1.0.0", "1.1.0"]:
            if not any(p["id"] == "sample-records" and p["version"] == version for p in self.request(su, "GET", "/admin/plugins")["items"]):
                self.request(su, "POST", "/admin/plugins", files={"file": ("synthetic.zip", self.package(version), "application/zip")})
        if "connection" not in self.state:
            self.state["connection"] = self.request(su, "POST", "/admin/connections", json={"name": "合成资料服务", "base_url": "http://172.17.0.1:19461", "auth_type": "bearer", "secret": (self.root / "sample-service.key").read_text().strip(), "allowed_methods": ["GET"], "allowed_paths": ["/health", "/records"], "timeout_seconds": 10, "max_response_bytes": 1048576, "enabled": True})["id"]; self.save()
        for version in ["1.0.0", "1.1.0"]:
            self.request(su, "PUT", "/admin/plugins/sample-records/" + version + "/connections", json={"bindings": {"records": self.state["connection"]}})
        for name, role in [("alignment-manager", "admin"), ("alignment-a", "user"), ("alignment-b", "user")]:
            if name not in self.state["accounts"]:
                password = secrets.token_urlsafe(24)
                data = {"username": name, "password": password, "role": role}
                if role == "user": data.update(model_ids=[self.state["model"]], plugin_ids=["sample-records"])
                result = self.request(su, "POST", "/admin/users", json=data)
                self.state["accounts"][name] = {"password": password, "id": result["user"]["id"]}; self.save()
            c = self.login(name)
            if role == "admin":
                assert not self.request(c,"GET","/me")["user"].get("runtime")
                continue
            if name not in self.state.get("configured", []):
                self.request(c,"PUT","/plugins/sample-records",json={"version":"1.0.0","enabled":True,"config":{"query":"甲" if name.endswith("a") else "乙","limit":5}})
                skill = self.request(c,"POST","/skills",json={"name":"合成资料整理","description":"只使用当前账号资料与授权工具","content":"用户要求查询示例资料时必须调用 platform_sample_records 工具，依据真实结果回复。用户引用文件时核对文件中的标记并注明来源，不读取其他账号资料。","enabled":True})
                self.state["accounts"][name]["skill"] = skill["id"]
                self.state.setdefault("configured",[]).append(name); self.save()
            state = self.request(c,"GET","/me/runtime")
            if not state.get("ready") and "start" in state.get("allowed_actions",[]):
                self.request(c,"POST","/me/runtime/start",json={})
            state=self.ready(c)
            self.state["accounts"][name]["runtime"] = state.get("runtime_id"); self.save()
            self.record(name+"_real_runtime_ready",revision=state["revision"])
        self.record("four_accounts_prepared_two_real_runtimes")

    def basic(self):
        a = self
        ca=a.login("alignment-a");cb=a.login("alignment-b");cm=a.login("alignment-manager")
        for name,c in [("alignment-a",ca),("alignment-b",cb)]:
         a.ready(c)
         result=a.request(c,"POST","/plugins/sample-records/test",json={})
         print("plugin_result",name,result,flush=True)
         assert result.get("ok") is True
         a.record(name+"_plugin_connection_passed")
         assert a.request(c,"POST","/skills/"+a.state["accounts"][name]["skill"]+"/test",json={})["ok"]
         a.record(name+"_skill_loaded")
        for path in ["/admin/plugins","/admin/connections","/admin/templates"]:
         assert cm.get(path).status_code==403
        a.record("manager_platform_governance_denied")
        f=a.request(ca,"POST","/files",files={"file":("synthetic.txt","合成验收标记：ALIGNMENT-A-20260917。测试数值：42。".encode(),"text/plain")})
        print("upload_shape",list(f),flush=True)
        fid=f["id"];a.state["acceptance_file"]=fid;a.save()
        for _ in range(30):
         r=ca.get("/files/"+fid+"/preview")
         if r.is_success and "ALIGNMENT-A-20260917" in r.text:break
         time.sleep(1)
        else:raise RuntimeError("file_preview_not_ready")
        assert cb.get("/files/"+fid+"/preview").status_code==404
        a.record("real_upload_parse_and_cross_account_denial")
        session=a.request(ca,"POST","/sessions",json={"title":"独立部署真实联调"})
        sid=session["id"];a.state["acceptance_session"]=sid;a.save()
        assert cb.get("/sessions/"+sid+"/messages").status_code==404
        a.record("real_session_cross_account_denial")

    def model(self):
        a = self
        c=a.login("alignment-a")
        for kind,text,files in [("file_answer","请读取所附合成文本，只回答标记和测试数值，50字以内。",[a.state["acceptance_file"]]),("plugin_call","请实际调用示例资料查询插件，返回查到的资料标题和数量，80字以内。",[])]:
         if kind in a.state.get("model_attempts",{}):raise RuntimeError("already_attempted:"+kind)
         sid=a.request(c,"POST","/sessions",json={"title":"真实模型验收-"+kind})["id"]
         a.state.setdefault("model_attempts",{})[kind]={"session":sid,"status":"submitting"};a.save()
         start=time.monotonic()
         a.request(c,"POST","/sessions/"+sid+"/messages",json={"text":text,"model_id":a.state["model"],"skill_ids":[a.state["accounts"]["alignment-a"]["skill"]],"file_ids":files})
         while time.monotonic()-start<180:
          items=a.request(c,"GET","/sessions/"+sid+"/messages")["items"]
          answers=[x for x in items if x["info"]["role"]=="assistant"]
          if any(x["info"].get("error") for x in answers):raise RuntimeError("model_error:"+kind)
          if answers and answers[-1]["info"].get("time",{}).get("completed") and answers[-1]["info"].get("finish") in ["stop","end_turn"]:break
          time.sleep(2)
         else:raise RuntimeError("model_result_unknown:"+kind)
         texts="".join(p.get("text","") for x in answers for p in x["parts"])
         toolparts=[p for x in answers for p in x["parts"] if p["type"]=="tool"]
         if kind=="file_answer":assert "ALIGNMENT-A-20260917" in texts and "42" in texts
         else:assert any(p.get("state",{}).get("status")=="completed" and p.get("details",{}).get("outputs",{}).get("version")=="1.0.0" for p in toolparts),toolparts
         a.state["model_attempts"][kind]["status"]="passed";a.save()
         a.record("real_deepseek_"+kind,seconds=round(time.monotonic()-start,2),tool_count=len(toolparts))

    def lifecycle(self):
        a = self
        ca=a.login("alignment-a");cb=a.login("alignment-b")
        def wait():
         start=time.monotonic();checks=0
         while time.monotonic()-start<300:
          assert cb.get("/sessions").status_code==200;checks+=1
          state=a.request(ca,"GET","/me/runtime")
          if state.get("ready") and state["revision"]==state["desired"]:return checks
          if state.get("status")=="failed":raise RuntimeError("runtime_failed")
          time.sleep(2)
         raise RuntimeError("runtime_wait_timeout")
        a.request(ca,"PUT","/plugins/sample-records",json={"version":"1.1.0","enabled":True,"config":{"query":"甲","limit":5}})
        checks=wait()
        assert a.request(ca,"GET","/plugins")["items"][0]["installed"]["version"]=="1.1.0"
        assert a.request(ca,"POST","/plugins/sample-records/test",json={})["ok"]
        a.record("plugin_upgrade_applied_B_remained_available",b_checks=checks)
        a.request(ca,"POST","/plugins/sample-records/rollback",json={});checks=wait()
        assert a.request(ca,"GET","/plugins")["items"][0]["installed"]["version"]=="1.0.0"
        assert a.request(ca,"POST","/plugins/sample-records/test",json={})["ok"]
        a.record("plugin_rollback_applied_B_remained_available",b_checks=checks)
        state=a.request(ca,"GET","/me/runtime")
        a.request(ca,"POST","/me/runtime/stop",json={"expected_state_version":state["state_version"]})
        for _ in range(100):
         state=a.request(ca,"GET","/me/runtime")
         assert cb.get("/sessions").status_code==200
         if "start" in state.get("allowed_actions",[]):break
         time.sleep(2)
        else:raise RuntimeError("stop_not_complete")
        a.request(ca,"POST","/me/runtime/start",json={});wait()
        assert ca.get("/sessions/"+a.state["acceptance_session"]+"/messages").status_code==200
        assert "ALIGNMENT-A-20260917" in ca.get("/files/"+a.state["acceptance_file"]+"/preview").text
        a.record("A_stop_start_persistence_B_available")

    def token(self):
        a = self
        c=a.login("alignment-b");token=a.request(c,"POST","/tokens",json={"name":"synthetic-live-acceptance"})
        t=a.client();t.headers["Authorization"]="Bearer "+token["token"]
        assert t.get("/sessions").status_code==200
        with t.stream("GET","/events",timeout=15) as stream:
         assert stream.status_code==200
         a.request(c,"DELETE","/tokens/"+token["item"]["id"])
         start=time.monotonic()
         for line in stream.iter_lines():
          if time.monotonic()-start>6:raise RuntimeError("revoked_stream_not_closed")
         elapsed=time.monotonic()-start
        assert elapsed<=5
        assert t.get("/sessions").status_code==401
        a.record("python_token_and_SSE_revocation",seconds=round(elapsed,2))

if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,required=True);parser.add_argument("--phase",choices=["prepare", "basic", "model", "lifecycle", "token"],required=True);parser.add_argument("--model-key-file",type=Path)
    args=parser.parse_args();a=Acceptance(args.root)
    try:
        if args.phase == "prepare": a.prepare(args.model_key_file)
        else: getattr(a, args.phase)()
    finally: a.clients.close()
