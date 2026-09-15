"""Few real-model calls with synthetic inputs, isolated HTTPS instance only."""
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import threading
import time
import httpx

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("acceptance", ROOT / "platform-acceptance.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
report = {"scope": "real_deepseek_synthetic_only", "checks": []}

def need(name, value):
    report["checks"].append({"name": name, "passed": bool(value)})
    (ROOT / "output/platform-model-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not value:
        raise RuntimeError(name)
    print("pass:" + name, flush=True)

def messages(c, sid):
    return h.checked(c.get(f"/sessions/{sid}/messages"))["items"]

def text(items):
    return "".join(p.get("text", "") for m in items if m["info"]["role"] == "assistant" for p in m["parts"] if p["type"] == "text")

def status(c, sid):
    return next(i["status"] for i in h.checked(c.get("/sessions"))["items"] if i["id"] == sid)

def wait(c, sid):
    for _ in range(240):
        values = messages(c, sid)
        answers = [m for m in values if m["info"]["role"] == "assistant"]
        if any(m["info"].get("error") for m in answers):
            raise RuntimeError("model_returned_error")
        if answers and answers[-1]["info"].get("time", {}).get("completed") and status(c, sid) == "idle":
            return values
        time.sleep(.5)
    h.checked(c.post(f"/sessions/{sid}/abort", json={}))
    raise RuntimeError("model_timeout")

def call_plugin(c, state, expected):
    sid = h.checked(c.post("/sessions", json={"title": "合成插件调用 " + expected}))["id"]
    h.checked(c.post(f"/sessions/{sid}/messages", json={"text": "这是合成验收。请实际调用 platform_sample_records 工具查询示例资料，再用中文给出资料名、条数 count 和插件版本 version。不要编造结果，不调用其他工具。", "model_id": state["model"], "skill_ids": [state["skill"]]}))
    values = wait(c, sid)
    parts = [p for m in values for p in m["parts"] if p["type"] == "tool"]
    need("actual_plugin_tool_" + expected, any(p.get("state", {}).get("status") == "completed" and p.get("details", {}).get("outputs", {}).get("version") == expected for p in parts))
    need("synthetic_data_answer_" + expected, "资料甲" in text(values) and "资料乙" not in text(values))
    state["last_model_session"] = sid
    h.save(state)

def run():
    state = h.load()
    with closing(h.admin()) as su, closing(h.login("platform-a", state["platform-a"]["password"])) as a, closing(h.login("platform-b", state["platform-b"]["password"])) as b:
        call_plugin(a, state, "1.0.0")
        for target in ("upgrade", "rollback"):
            if target == "upgrade":
                h.checked(a.put("/plugins/sample-records", json={"version": "1.1.0", "enabled": True, "config": {"query": "甲", "limit": 5}}))
            else:
                h.checked(a.post("/plugins/sample-records/rollback", json={}))
            need("other_account_usable_during_" + target, b.get("/sessions").status_code == 200 and h.checked(b.post("/plugins/sample-records/test", json={}))["ok"])
            h.ready(su, state["platform-a"]["id"])
            call_plugin(a, state, "1.1.0" if target == "upgrade" else "1.0.0")
        sid = h.checked(a.post("/sessions", json={"title": "合成流式与停止"}))["id"]
        observer = {"connected": False, "changes": 0}
        stop = threading.Event()
        def listen():
            try:
                with h.client() as c:
                    c.cookies.update(a.cookies)
                    with c.stream("GET", "/events", timeout=10) as response:
                        observer["connected"] = response.status_code == 200
                        for line in response.iter_lines():
                            if line.startswith("event: change"):
                                observer["changes"] += 1
                            if stop.is_set():
                                break
            except httpx.HTTPError:
                pass
        t = threading.Thread(target=listen, daemon=True)
        t.start()
        for _ in range(50):
            if observer["connected"]:
                break
            time.sleep(.1)
        need("https_sse_connected", observer["connected"])
        h.checked(a.post(f"/sessions/{sid}/messages", json={"text": "合成流式输出测试：不用工具，逐行输出1至300的编号，每行写一句不同的办公效率小技巧。不要省略。", "model_id": state["model"]}))
        sizes = []
        for _ in range(180):
            sizes.append(len(text(messages(a, sid))))
            if len(set(v for v in sizes if v)) >= 3 and sizes[-1] > 120:
                break
            time.sleep(.3)
        need("incremental_answer_before_completion", len(set(v for v in sizes if v)) >= 3 and status(a, sid) != "idle")
        h.checked(a.post(f"/sessions/{sid}/abort", json={}))
        for _ in range(40):
            if status(a, sid) == "idle":
                break
            time.sleep(.5)
        need("abort_preserves_partial_answer", status(a, sid) == "idle" and len(text(messages(a, sid))) > 0)
        stop.set()
        t.join(timeout=10)
        need("sse_not_buffered", observer["changes"] > 1)
        report["sse_changes"] = observer["changes"]
    report["status"] = "passed"
    (ROOT / "output/platform-model-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(str(e) if isinstance(e, RuntimeError) else "model_acceptance_failed:" + type(e).__name__)
        raise SystemExit(1)
