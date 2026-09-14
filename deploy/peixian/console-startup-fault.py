"""Opt-in bad-entrypoint acceptance, restricted to the paused console-fault account."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import uuid
import httpx

ROOT = Path(__file__).resolve().parent
loader = importlib.util.spec_from_file_location("startup_fault_helpers", ROOT / "console-fault-acceptance.py")
fault = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fault)
runtime, worker = fault.runtime, fault.worker


class ScopedRuntime(fault.ScopedRuntime):
    def __init__(self, root, journal, image):
        super().__init__(root, journal=journal)
        self.agent_image = image


def sentinel(manager, volume, image):
    code = "import hashlib,json;print(json.dumps({'sha256':hashlib.sha256(open('/data/.console-fault-sentinel','rb').read()).hexdigest()}))"
    value = manager.docker_run("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
        "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--memory", "64m", "--cpus", "0.5", "--pids-limit", "32",
        "--mount", "type=volume,source=" + volume + ",target=/data,readonly", "--entrypoint", "python3", image, "-c", code)
    return json.loads(value)["sha256"]


def run(args):
    state = ROOT / ".runtime/console"
    original = json.loads((state / "fault-acceptance/state.json").read_text(encoding="utf-8"))
    if original.get("phase") != "completed":
        raise runtime.RuntimeFailure("startup_fault_requires_completed_crash_acceptance")
    identity, uid = runtime.check_id(original["runtime_id"]), runtime.check_id(original["uid"])
    folder = state / "startup-fault"
    folder.mkdir(parents=True, exist_ok=True)
    journal = folder / "state.json"
    if journal.exists():
        raise runtime.RuntimeFailure("startup_fault_state_exists_review_before_retry")
    runtime.write_json(journal, {"uid": uid, "runtime_id": identity, "claims": []})
    manager = runtime.RuntimeManager(state)
    report = {"status": "running", "checks": [], "uid": uid, "runtime_id": identity,
              "started_at": datetime.now(timezone.utc).isoformat(), "model_requests": 0}
    def check(name, passed):
        report["checks"].append({"name": name, "pass": bool(passed)})
        runtime.write_json(args.report, report)
        if not passed:
            raise runtime.RuntimeFailure("startup_fault_check_failed")
    runtime.write_json(args.report, report)
    key = fault.read_credential(ROOT / ".secrets/console-worker.key", 32)
    password = fault.read_credential(ROOT / ".secrets/console-admin-current.password")
    with worker.host_lock(state), httpx.Client(base_url=args.control_url, headers={"Origin": args.control_url},
            timeout=60, trust_env=False, follow_redirects=False) as admin, httpx.Client(base_url=args.control_url,
            headers={"X-Worker-Key": key}, timeout=60, trust_env=False, follow_redirects=False) as api:
        login = fault.request(admin, "POST", fault.PREFIX + "/auth/login", json={"username": "admin", "password": password})
        admin.headers["X-CSRF-Token"] = login["csrf_token"]
        fault.require_quiet_queue(admin)
        user, baseline = fault.account(admin, uid)
        check("target_is_paused_fault_account_without_models", user["runtime"]["status"] == "paused" and not user["model_ids"])
        check("target_has_no_running_container", manager.running(identity) == [])
        before = fault.volume_records(manager, identity)
        check("exactly_three_existing_volumes", set(before) == {"px-" + identity + "-" + name for name in ("home", "workspace", "files")})
        good = json.loads(manager.docker_run("image", "inspect", manager.agent_image))[0]
        check("base_image_is_local_linux_amd64", good["Os"] == "linux" and good["Architecture"] == "amd64")
        unique = uuid.uuid4().hex[:12]
        base_tag, bad_tag = "peixian-opencode:startup-base-" + unique, "peixian-opencode:startup-fault-" + unique
        manager.docker_run("tag", good["Id"], base_tag)
        check("test_base_tag_pins_observed_image_id", json.loads(manager.docker_run("image", "inspect", base_tag))[0]["Id"] == good["Id"])
        context = folder / unique
        context.mkdir()
        (context / "Dockerfile").write_text("FROM " + base_tag + '\nENTRYPOINT ["/bin/false"]\nCMD []\n', encoding="utf-8")
        manager.docker_run("build", "--network", "none", "--pull=false", "-t", bad_tag, str(context), timeout=180)
        bad = json.loads(manager.docker_run("image", "inspect", bad_tag))[0]
        check("isolated_bad_image_has_false_entrypoint", bad["Config"]["Entrypoint"] == ["/bin/false"] and bad["Id"] != good["Id"])
        report.update(base_image_id=good["Id"], bad_image_id=bad["Id"], base_tag=base_tag, bad_tag=bad_tag)
        workspace = "px-" + identity + "-workspace"
        check("baseline_synthetic_data_matches", sentinel(manager, workspace, base_tag) == original["sentinel_sha256"])

        def queue(action):
            fault.require_quiet_queue(admin, uid)
            return fault.request(admin, "POST", fault.PREFIX + "/admin/users/" + uid + "/runtime/" + action, json={})["job"]

        def execute(job, image):
            scoped = ScopedRuntime(state, journal, image)
            return fault.ScopedWorker(api, scoped, journal, runtime.check_id(job["id"])).once()

        try:
            deferred = queue("apply")
            check("paused_revision_change_does_not_start_environment", deferred["status"] == "deferred")
            bad_job = queue("resume")
            report["bad_job_id"] = bad_job["id"]
            runtime.write_json(args.report, report)
            print('{"phase":"testing_bad_image_start"}', flush=True)
            check("bad_image_job_processed", execute(bad_job, bad_tag))
            user, capacity = fault.account(admin, uid)
            check("bad_image_start_failed", user["runtime"]["status"] == "failed")
            check("bad_image_job_record_failed", fault.target_job(admin, bad_job["id"])["status"] == "failed")
            check("failed_start_containers_confirmed_stopped", manager.running(identity) == [])
            check("failed_start_released_runtime_slot", capacity["reserved"] == baseline["reserved"])
            check("failed_start_retains_original_volumes", fault.volume_records(manager, identity) == before)
            check("failed_start_retains_synthetic_data", sentinel(manager, workspace, base_tag) == original["sentinel_sha256"])
        finally:
            # Only this account is repaired; no source volumes are removed or restored.
            fault.require_quiet_queue(admin, uid)
            active = [job for job in fault.jobs(admin) if job["uid"] == uid and job["status"] in ("queued", "running")]
            if active:
                raise runtime.RuntimeFailure("startup_fault_pending_job_requires_review")
            user, _ = fault.account(admin, uid)
            if user["runtime"]["status"] == "failed":
                check("recovery_revision_is_deferred_while_unreserved", queue("apply")["status"] == "deferred")
                restore = queue("resume")
                print('{"phase":"restoring_good_image"}', flush=True)
                check("good_image_recovery_job_processed", execute(restore, base_tag))
                user, _ = fault.account(admin, uid)
                check("good_image_recovered_ready", user["runtime"]["status"] == "ready")
            if user["runtime"]["status"] == "ready":
                pause = queue("pause")
                check("recovered_account_pause_job_processed", execute(pause, base_tag))
            user, capacity = fault.account(admin, uid)
            check("target_final_state_paused", user["runtime"]["status"] == "paused")
            check("target_final_containers_stopped", manager.running(identity) == [])
            check("target_final_slot_released", capacity["reserved"] == baseline["reserved"])
            check("target_final_volumes_unchanged", fault.volume_records(manager, identity) == before)
            check("target_final_synthetic_data_retained", sentinel(manager, workspace, base_tag) == original["sentinel_sha256"])
        report.update(status="passed", passed=len(report["checks"]), failed=0, data_retained=True)
        runtime.write_json(args.report, report)
        print(json.dumps({"status": "passed", "passed": report["passed"], "failed": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--control-url", default="http://127.0.0.1:14090", choices=("http://127.0.0.1:14090",))
    parser.add_argument("--report", type=Path, default=ROOT / ".runtime/console-startup-fault.json")
    args = parser.parse_args()
    if not args.execute:
        print('{"status":"plan","account":"console-fault","requires":"--execute"}')
        return
    try:
        run(args)
    except Exception as error:
        report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {"checks": []}
        code = error.code if isinstance(error, runtime.RuntimeFailure) else "startup_fault_operation_failed"
        report["checks"].append({"name": "startup_fault_finished_without_error", "pass": False})
        report.update(status="failed", error_code=code, passed=sum(item["pass"] for item in report["checks"]),
                      failed=sum(not item["pass"] for item in report["checks"]))
        runtime.write_json(args.report, report)
        print(json.dumps({"status": "failed", "passed": report["passed"], "failed": report["failed"], "code": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
