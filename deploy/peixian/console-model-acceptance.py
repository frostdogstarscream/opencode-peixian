"""Small real DeepSeek checks against synthetic console-test data only.
Uses existing private acceptance credentials; prints and stores counts/booleans only.
"""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time
import uuid
import httpx

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("console_acceptance", ROOT / "console-acceptance.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
report = {"layer": "real_model_synthetic_only", "checks": []}

def need(name, value):
    report["checks"].append({"name": name, "passed": bool(value)})
    if not value:
        raise RuntimeError(name)

def messages(client, sid):
    return helper.checked(client.get(f"/sessions/{sid}/messages"))["items"]

def status(client, sid):
    return next(item["status"] for item in helper.checked(client.get("/sessions"))["items"] if item["id"] == sid)

def text(items):
    return "".join(part.get("text", "") for item in items if item["info"]["role"] == "assistant" for part in item["parts"] if part["type"] == "text")

def wait_done(client, sid, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        values = messages(client, sid)
        answers = [item for item in values if item["info"]["role"] == "assistant"]
        if any(item["info"].get("error") for item in answers):
            raise RuntimeError("real_model_no_upstream_error")
        if answers and answers[-1]["info"].get("time", {}).get("completed") and status(client, sid) == "idle":
            return values
        time.sleep(0.5)
    helper.checked(client.post(f"/sessions/{sid}/abort", json={}))
    raise RuntimeError("real_model_completed_within_budget")

def run():
    state = json.loads(helper.STATE.read_text(encoding="utf-8"))
    token = uuid.uuid4().hex[:10]
    marker = "PEIXIAN_FILE_" + token
    result_name = "synthetic-result-" + token + ".md"
    with closing(helper.login("console-test", helper.PRIVATE / "console-test.password")) as client:
        content = ("item,amount,marker\nsynthetic,17," + marker + "\n").encode()
        uploaded = helper.checked(client.post("/files", files={"file": ("synthetic-input-" + token + ".csv", content, "text/csv")}))
        fid = uploaded["id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            preview = helper.checked(client.get(f"/files/{fid}/text"))
            if preview["status"] in ("ready", "partial"):
                break
            time.sleep(0.5)
        need("uploaded_csv_parsed_with_sources", preview["status"] == "ready" and marker in preview["text"] and bool(preview["chunks"]))
        sid = helper.checked(client.post("/sessions", json={"title": "合成验收：文件引用与结果下载"}))["id"]
        prompt = ("这是合成文件验收。请读取本次附带的 CSV 资料，使用 write 工具在当前工作区创建文件 "
                  + result_name + "，写入一段 Markdown，其中必须包含资料中的 marker 原值和 amount 数值。"
                  "请实际调用写入工具，不要只给出示例代码；完成后回复来源文件名、数据行号和结果文件名即可。")
        helper.checked(client.post(f"/sessions/{sid}/messages", json={"text": prompt, "model_id": state["model_id"], "file_ids": [fid]}))
        values = wait_done(client, sid)
        tools = [part for item in values for part in item["parts"] if part["type"] == "tool"]
        need("real_native_write_tool_completed", any(part.get("tool") == "保存结果" and part.get("state", {}).get("status") == "completed" for part in tools))
        results = helper.checked(client.get("/results"))["items"]
        result = next((item for item in results if item["name"] == result_name), None)
        need("result_registered_for_own_workspace", result is not None)
        download = client.get("/results/" + result["id"] + "/download")
        need("generated_result_download_contains_source_marker", download.status_code == 200 and marker in download.text and "17" in download.text)
        need("ordinary_result_has_no_absolute_path", not result.get("relative_path", "").startswith(("/", "\\")))
        with closing(helper.login("console-other", helper.PRIVATE / "console-other.password")) as other:
            need("other_account_cannot_download_generated_result", other.get("/results/" + result["id"] + "/download").status_code == 404)
        # A new stream observes business invalidations while text accumulates in history.
        stopped = threading.Event()
        streaming = {"connected": False, "changes": 0}
        cookie = httpx.Cookies(client.cookies)
        def observe():
            try:
                with httpx.Client(base_url=helper.BASE, cookies=cookie, trust_env=False, timeout=5) as events:
                    with events.stream("GET", "/events") as response:
                        streaming["connected"] = response.status_code == 200
                        for line in response.iter_lines():
                            if line.startswith("event: change"):
                                streaming["changes"] += 1
                            if stopped.is_set():
                                break
            except httpx.HTTPError:
                pass
        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not streaming["connected"]:
            time.sleep(0.05)
        need("sse_connected_before_send", streaming["connected"])
        abort_sid = state.get("live_observe_session") or helper.checked(client.post("/sessions", json={"title": "合成验收：流式回答与停止"}))["id"]
        helper.checked(client.post(f"/sessions/{abort_sid}/messages", json={
            "text": "这是纯合成输出测试。不要调用工具。请逐行输出从1到500的编号，每行附一句不同的中文办公系统易用性说明。直接开始逐行输出，不要省略。",
            "model_id": state["model_id"]}))
        deadline = time.monotonic() + 75
        sizes = []
        visible_since = None
        while time.monotonic() < deadline:
            before = messages(client, abort_sid)
            sizes.append(len(text(before)))
            if len(set(size for size in sizes if size > 0)) >= 2 and sizes[-1] >= 150 and status(client, abort_sid) != "idle":
                visible_since = visible_since or time.monotonic()
                if time.monotonic() - visible_since >= 8:
                    break
            time.sleep(0.3)
        need("real_answer_visible_before_completion", len(set(size for size in sizes if size > 0)) >= 2 and status(client, abort_sid) != "idle")
        helper.checked(client.post(f"/sessions/{abort_sid}/abort", json={}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and status(client, abort_sid) != "idle":
            time.sleep(0.5)
        need("abort_returns_session_to_idle", status(client, abort_sid) == "idle")
        after = messages(client, abort_sid)
        need("abort_preserves_partial_answer", bool(text(after)))
        need("history_refresh_has_unique_message_ids", len(after) == len({item["info"]["id"] for item in after}))
        stopped.set()
        thread.join(timeout=6)
        need("sse_delivered_changes_during_generation", streaming["connected"] and streaming["changes"] > 1)
        state["file_session"] = sid
        state["abort_session"] = abort_sid
        state["generated_result"] = result["id"]
        helper.STATE.write_text(json.dumps(state), encoding="utf-8")
        report["result_sha256"] = hashlib.sha256(download.content).hexdigest()
        report["assistant_partial_characters"] = len(text(after))
        report["sse_notifications"] = streaming["changes"]
        # Keep only these synthetic fixtures for final browser verification.
        report["retained_synthetic_uploads"] = 1
        report["retained_synthetic_results"] = 1

if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        report["failure_code"] = str(error) if isinstance(error, RuntimeError) else "acceptance_operation_failed"
    report["passed"] = sum(item["passed"] for item in report["checks"])
    report["failed"] = sum(not item["passed"] for item in report["checks"])
    report["status"] = "passed" if "failure_code" not in report and report["failed"] == 0 else "failed"
    path = ROOT / "output/console-real-model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    raise SystemExit(0 if report["status"] == "passed" else 1)
