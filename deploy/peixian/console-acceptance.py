"""Synthetic, local console acceptance. Never prints credentials or user content."""
from pathlib import Path
from contextlib import closing
import argparse
import io
import json
import secrets
import time
import zipfile

import httpx

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / ".secrets"
STATE = ROOT / ".runtime/console-acceptance.json"
BASE = "http://127.0.0.1:14090/api/console/v1"


def checked(response, expected=(200, 201, 202, 204)):
    if response.status_code not in expected:
        raise RuntimeError(f"Acceptance HTTP {response.status_code} on {response.request.url.path}")
    return response.json() if response.content else {}


def login(username, password_file):
    client = httpx.Client(base_url=BASE, trust_env=False, timeout=90, headers={"Origin": "http://127.0.0.1:14090"})
    password = password_file.read_text().strip()
    result = checked(client.post("/auth/login", json={"username": username, "password": password}))
    client.headers["X-CSRF-Token"] = result["csrf_token"]
    if result["user"]["must_change_password"]:
        replacement = secrets.token_urlsafe(24)
        checked(client.post("/me/password", json={"current_password": password, "password": replacement}))
        password_file.write_text(replacement + "\n", encoding="utf-8")
    return client


def admin():
    current = PRIVATE / "console-admin-current.password"
    if not current.exists():
        current.write_bytes((PRIVATE / "console-admin.password").read_bytes())
    return login("admin", current)


def prepare():
    with closing(admin()) as client:
        models = checked(client.get("/admin/models"))["items"]
        model = next((m for m in models if m["model_id"] == "deepseek-flash"), None)
        if not model:
            model = checked(client.post("/admin/models", json={"name": "DeepSeek V4.1 Flash", "description": "合成内容本机验收", "base_url": "https://api.deepseek.com/v1", "model_id": "deepseek-flash", "api_key": (PRIVATE / "client-a.deepseek-key").read_text().strip(), "is_default": True}))
        users = checked(client.get("/admin/users"))["items"]
        user = next((u for u in users if u["username"] == "console-test"), None)
        if not user:
            result = checked(client.post("/admin/users", json={"username": "console-test", "model_ids": [model["id"]]}))
            user = result["user"]
            (PRIVATE / "console-test.password").write_text(result["password"] + "\n", encoding="utf-8")
        STATE.write_text(json.dumps({"user_id": user["id"], "model_id": model["id"]}), encoding="utf-8")
    with closing(login("console-test", PRIVATE / "console-test.password")) as client:
        me = checked(client.get("/me"))
        print(json.dumps({"prepared": True, "username": me["user"]["username"], "runtime": me["user"].get("runtime")}, ensure_ascii=True))


def status():
    with closing(admin()) as client:
        result = checked(client.get("/admin/users"))
        print(json.dumps({"users": [{"username": u["username"], "runtime": u.get("runtime")} for u in result["items"]], "capacity": result["capacity"]}, ensure_ascii=True))
        print(json.dumps(checked(client.get("/admin/jobs")), ensure_ascii=True))


def chat():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    with closing(login("console-test", PRIVATE / "console-test.password")) as client:
        session = checked(client.post("/sessions", json={"title": "合成验收：模型连通性"}))
        sid = session["id"]
        checked(client.post(f"/sessions/{sid}/messages", json={"text": "这是合成连通性测试，不涉及业务数据。请仅回复：控制台连接成功。", "model_id": state["model_id"]}))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            messages = checked(client.get(f"/sessions/{sid}/messages"))["items"]
            answers = [m for m in messages if m["info"]["role"] == "assistant"]
            if any(m["info"].get("error") for m in answers):
                raise RuntimeError("Real model response reported a sanitized upstream error")
            if answers and answers[-1]["info"].get("time", {}).get("completed"):
                text = "".join(p.get("text", "") for m in answers for p in m["parts"] if p["type"] == "text")
                if "控制台连接成功" not in text:
                    raise RuntimeError("Real model synthetic response missing expected marker")
                state["chat_session"] = sid
                STATE.write_text(json.dumps(state), encoding="utf-8")
                print(json.dumps({"real_model_chat": "passed", "assistant_messages": len(answers), "response_characters": len(text)}))
                return
            time.sleep(1)
        raise RuntimeError("Real model response timed out")

def configure():
    state=json.loads(STATE.read_text(encoding="utf-8"))
    with closing(admin()) as client:
        catalog=checked(client.get("/admin/plugins"))["items"]
        for version in ("1.0.0","1.1.0"):
            if any(p["id"]=="synthetic-check" and p["version"]==version for p in catalog):
                continue
            manifest={"id":"synthetic-check","version":version,"name":"合成连通性插件","description":"仅用于验收，不访问真实业务数据","opencode_version":"1.18.30","entry":"entry.mjs","tools":["peixian_marker"],"display_fields":["marker","version"],"config_schema":{"type":"object","properties":{"marker":{"type":"string","title":"合成标记"},"secret":{"type":"string","title":"测试凭据","writeOnly":True,"format":"password"}},"required":["marker","secret"],"additionalProperties":False}}
            module='export default async (context,options)=>({tool:{peixian_marker:{description:"Return the configured synthetic acceptance marker and plugin version. Call when the user asks to verify the synthetic plugin.",args:{},async execute(){return JSON.stringify({marker:options.marker,version:"'+version+'"})}}}});\nexport async function test(options){return {ok:typeof options.marker==="string"&&!!options.secret,message:"synthetic probe"}};'
            output=io.BytesIO()
            with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False))
                archive.writestr("entry.mjs",module)
            checked(client.post("/admin/plugins",files={"file":("synthetic-check-"+version+".zip",output.getvalue(),"application/zip")}))
        checked(client.patch("/admin/users/"+state["user_id"],json={"plugin_ids":["synthetic-check"]}))
    with closing(login("console-test",PRIVATE/"console-test.password")) as client:
        checked(client.put("/plugins/synthetic-check",json={"version":"1.0.0","enabled":True,"config":{"marker":"PEIXIAN_SYNTHETIC_1701","secret":"synthetic-private-value"}}))
        skills=checked(client.get("/skills"))["items"]
        skill=next((s for s in skills if s["name"]=="合成验收技能"),None)
        if not skill:
            skill=checked(client.post("/skills",json={"name":"合成验收技能","description":"使用合成插件核查返回值","content":"需要验收时调用 peixian_marker 工具，并在答复中展示其 marker 和 version。不要编造工具结果。","enabled":True}))
        state["skill_id"]=skill["id"]
        public=checked(client.get("/plugins"))
        if "synthetic-private-value" in json.dumps(public):
            raise RuntimeError("Plugin credential appeared in public response")
    STATE.write_text(json.dumps(state),encoding="utf-8")
    print(json.dumps({"synthetic_plugin_published":True,"skill_saved":True,"credentials_redacted":True}))


def tools():
    state=json.loads(STATE.read_text(encoding="utf-8"))
    with closing(login("console-test",PRIVATE/"console-test.password")) as client:
        if not checked(client.post("/plugins/synthetic-check/test",json={}))["ok"]:
            raise RuntimeError("Plugin probe failed")
        if not checked(client.post("/skills/"+state["skill_id"]+"/test",json={}))["ok"]:
            raise RuntimeError("Skill was not loaded")
        sid=checked(client.post("/sessions",json={"title":"合成验收：技能及插件调用"}))["id"]
        checked(client.post(f"/sessions/{sid}/messages",json={"text":"请先实际调用 skill 工具加载合成验收技能，再实际调用 peixian_marker 工具，返回配置的 marker 和 version。不要猜测或省略技能加载。","model_id":state["model_id"],"skill_ids":[state["skill_id"]]}))
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            messages=checked(client.get(f"/sessions/{sid}/messages"))["items"]
            answers=[m for m in messages if m["info"]["role"]=="assistant"]
            if any(m["info"].get("error") for m in answers):
                raise RuntimeError("Real tool interaction reported upstream error")
            text="".join(p.get("text","") for m in answers for p in m["parts"])
            completed_tools=[p for m in answers for p in m["parts"] if p["type"]=="tool" and p.get("state",{}).get("status")=="completed"]
            if answers and answers[-1]["info"].get("time",{}).get("completed") and "PEIXIAN_SYNTHETIC_1701" in text and state.get("expected_version","1.0.0") in text and completed_tools and any(p.get("tool")=="使用技能" for p in completed_tools):
                state["tool_session"]=sid
                STATE.write_text(json.dumps(state),encoding="utf-8")
                print(json.dumps({"real_model_tool_call":"passed","completed_tools":len(completed_tools),"plugin_probe":"passed","skill_loaded":True}))
                return
            time.sleep(1)
        raise RuntimeError("Real model tool interaction timed out")

def upgrade():
    version_change(False)


def rollback():
    version_change(True)


def version_change(back):
    state=json.loads(STATE.read_text(encoding="utf-8"))
    with closing(login("console-test",PRIVATE/"console-test.password")) as client:
        if back:
            checked(client.post("/plugins/synthetic-check/rollback",json={}))
            state["expected_version"]="1.0.0"
        else:
            checked(client.put("/plugins/synthetic-check",json={"version":"1.1.0","enabled":True,"config":{"marker":"PEIXIAN_SYNTHETIC_1701"}}))
            state["expected_version"]="1.1.0"
    STATE.write_text(json.dumps(state),encoding="utf-8")
    print(json.dumps({"plugin_version_requested":state["expected_version"]}))



def display():
    state=json.loads(STATE.read_text(encoding="utf-8"))
    version="1.2.0"
    with closing(admin()) as client:
        catalog=checked(client.get("/admin/plugins"))["items"]
        if not any(p["id"]=="synthetic-check" and p["version"]==version for p in catalog):
            manifest={"id":"synthetic-check","version":version,"name":"合成连通性插件","description":"仅用于验收，不访问真实业务数据","opencode_version":"1.18.30","entry":"entry.mjs","tools":["peixian_marker"],"display":{"input_fields":[],"output_fields":["marker","version"]},"config_schema":{"type":"object","properties":{"marker":{"type":"string","title":"合成标记"},"secret":{"type":"string","title":"测试凭据","writeOnly":True,"format":"password"}},"required":["marker","secret"],"additionalProperties":False}}
            module='export default async (context,options)=>({tool:{peixian_marker:{description:"Return the configured synthetic acceptance marker and plugin version.",args:{},async execute(){return JSON.stringify({marker:options.marker,version:"1.2.0"})}}}});\nexport async function test(options){return {ok:typeof options.marker==="string"&&!!options.secret,message:"synthetic probe"}};'
            output=io.BytesIO()
            with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False))
                archive.writestr("entry.mjs",module)
            checked(client.post("/admin/plugins",files={"file":("synthetic-check-1.2.0.zip",output.getvalue(),"application/zip")}))
    with closing(login("console-test",PRIVATE/"console-test.password")) as client:
        checked(client.put("/plugins/synthetic-check",json={"version":version,"enabled":True,"config":{"marker":"PEIXIAN_SYNTHETIC_1701"}}))
    state["expected_version"]=version
    STATE.write_text(json.dumps(state),encoding="utf-8")
    print(json.dumps({"business_detail_plugin_requested":version}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "status", "chat", "configure", "tools", "upgrade", "rollback", "display"])
    args = parser.parse_args()
    globals()[args.action]()
