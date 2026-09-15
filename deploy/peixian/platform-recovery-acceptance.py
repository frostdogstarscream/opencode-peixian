"""Capture/pause/resume/compare synthetic recovery fixtures; never deletes resources."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location("acceptance", ROOT / "platform-acceptance.py")
h = importlib.util.module_from_spec(s)
s.loader.exec_module(h)
BASELINE = h.TEST / "recovery-baseline.json"

def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()

def snapshot(c):
    sessions = h.checked(c.get("/sessions"))["items"]
    if any(x.get("status") != "idle" for x in sessions):
        raise RuntimeError("synthetic_sessions_must_be_idle")
    files = h.checked(c.get("/files"))["items"]
    return {
        "sessions": {x["id"]: {"title": x["title"], "messages": digest(h.checked(c.get(f"/sessions/{x['id']}/messages"))["items"])} for x in sessions},
        "files": {x["id"]: digest(c.get(f"/files/{x['id']}/download").raise_for_status().content) for x in files},
        "skills": digest(h.checked(c.get("/skills"))["items"]),
        "plugins": digest([{k: x["installed"][k] for k in ("version", "config", "enabled")} for x in h.checked(c.get("/plugins"))["items"] if x.get("installed")]),
        "models": digest(h.checked(c.get("/models"))["items"]),
    }

def capture(state):
    if BASELINE.exists():
        raise RuntimeError("existing_baseline_preserved")
    result = {}
    for name in ("platform-a", "platform-b"):
        with closing(h.login(name, state[name]["password"])) as c:
            result[name] = snapshot(c)
            result[name]["old_token"] = h.checked(c.post("/tokens", json={"name": "恢复撤销验收"}))["token"]
    BASELINE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("synthetic_baseline_captured")

def pause(state):
    with closing(h.admin()) as c:
        for name in ("platform-a", "platform-b"):
            h.checked(c.post(f"/admin/users/{state[name]['id']}/runtime/pause", json={}))
            for _ in range(120):
                value = next(x for x in h.checked(c.get("/admin/users"))["items"] if x["id"] == state[name]["id"])
                if value["runtime"]["status"] == "paused":
                    break
                time.sleep(1)
            else:
                raise RuntimeError("pause_timeout")
    print("synthetic_runtimes_paused")

def resume(state):
    with closing(h.admin()) as c:
        for name in ("platform-a", "platform-b"):
            h.checked(c.post(f"/admin/users/{state[name]['id']}/runtime/resume", json={}))
            h.ready(c, state[name]["id"])
    print("restored_runtimes_ready")

def compare(state):
    before = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = {"checks": []}
    def need(name, value):
        report["checks"].append({"name": name, "passed": bool(value)})
        if not value:
            raise RuntimeError(name)
        print("pass:" + name, flush=True)
    for name in ("platform-a", "platform-b"):
        with h.client() as old:
            old.headers["Authorization"] = "Bearer " + before[name]["old_token"]
            need(name + "_old_token_revoked", old.get("/me").status_code == 401)
        with closing(h.login(name, state[name]["password"])) as c:
            need(name + "_same_password_and_account", h.checked(c.get("/me"))["user"]["id"] == state[name]["id"])
            after = snapshot(c)
            for kind, value in after.items():
                need(name + "_restored_" + kind, before[name][kind] == value)
            need(name + "_plugin_connection_after_restore", h.checked(c.post("/plugins/sample-records/test", json={}))["ok"])
    report.update(status="passed", session_count=sum(len(before[x]["sessions"]) for x in before), file_count=sum(len(before[x]["files"]) for x in before))
    (ROOT / "output/platform-recovery-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("capture", "pause", "resume", "compare"):
            raise RuntimeError("choose_capture_pause_resume_compare")
        globals()[sys.argv[1]](h.load())
    except Exception as e:
        print(str(e) if isinstance(e, RuntimeError) else "recovery_acceptance_failed:" + type(e).__name__)
        raise SystemExit(1)
