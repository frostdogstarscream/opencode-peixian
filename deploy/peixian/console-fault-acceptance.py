"""Opt-in process-crash recovery acceptance for the isolated console-fault account.

Default invocation is a plan. Execution creates one account, retains its data,
and finishes with that account paused. It never modifies another runtime.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx


ROOT = Path(__file__).resolve().parent
loaded = importlib.util.spec_from_file_location("fault_worker", ROOT / "console-worker.py")
worker = importlib.util.module_from_spec(loaded)
loaded.loader.exec_module(worker)
runtime = worker.runtime
PREFIX = "/api/console/v1"
CRASH_EXIT = 73
USERNAME = "console-fault"


def read_credential(path, minimum=16):
    value = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    if len(value) < minimum or any(char in value for char in "\r\n\0"):
        raise runtime.RuntimeFailure("fault_credential_invalid")
    return value


def request(api, method, path, **kwargs):
    response = api.request(method, path, **kwargs)
    if response.status_code not in (200, 202):
        raise runtime.RuntimeFailure("fault_control_request_failed")
    return response.json()


def jobs(admin):
    return request(admin, "GET", PREFIX + "/admin/jobs")["items"]


def require_quiet_queue(admin, uid=None):
    if any(item["status"] in ("queued", "running") and item["uid"] != uid for item in jobs(admin)):
        raise runtime.RuntimeFailure("other_jobs_pending_no_runtime_changed")


def account(admin, uid):
    values = request(admin, "GET", PREFIX + "/admin/users")
    for item in values["items"]:
        if item["id"] == uid and item["username"] == USERNAME:
            return item, values["capacity"]
    raise runtime.RuntimeFailure("fault_account_identity_mismatch")


class ScopedRuntime(runtime.RuntimeManager):
    def __init__(self, root, *, journal, interrupt=False):
        super().__init__(root)
        self.journal = Path(journal)
        self.target = json.loads(self.journal.read_text(encoding="utf-8"))
        runtime.check_id(self.target["uid"])
        runtime.check_id(self.target["runtime_id"])
        self.interrupt = interrupt

    def reconcile(self):
        # This acceptance driver must not reconnect or operate any other account.
        return []

    def apply(self, job, spec, download, heartbeat):
        if job["uid"] != self.target["uid"] or spec["runtime_id"] != self.target["runtime_id"]:
            raise runtime.RuntimeFailure("fault_runtime_scope_mismatch")
        return super().apply(job, spec, download, heartbeat)

    def docker_run(self, *args, **kwargs):
        interrupt = getattr(self, "interrupt", False) and args[:2] == ("volume", "create")
        if interrupt:
            expected = "px-" + self.target["runtime_id"] + "-"
            if args[-1] not in {expected + name for name in ("home", "workspace", "files")}:
                raise runtime.RuntimeFailure("fault_volume_scope_mismatch")
        result = super().docker_run(*args, **kwargs)
        if interrupt:
            value = json.loads(self.journal.read_text(encoding="utf-8"))
            value.update(first_volume=args[-1], interrupted_at=time.time(), phase="interrupted_after_volume_create")
            runtime.write_json(self.journal, value)
            # Deliberately bypass finally blocks, stop the heartbeat thread and
            # leave the successful volume creation and running lease untouched.
            os._exit(CRASH_EXIT)
        return result


class ScopedWorker(worker.Worker):
    def __init__(self, api, manager, journal, expected_job):
        super().__init__(api, manager)
        self.journal, self.expected_job = Path(journal), expected_job

    def request(self, method, path, **kwargs):
        response = super().request(method, path, **kwargs)
        if path != "/internal/worker/claim":
            return response
        payload = response.json()
        job = payload.get("job")
        if job is None:
            return response
        value = json.loads(self.journal.read_text(encoding="utf-8"))
        if job["uid"] != value["uid"] or job["id"] != self.expected_job:
            # A UI update can race the read-only preflight. Return its lease
            # immediately; never call RuntimeManager.apply for another job.
            super().request("POST", "/internal/worker/jobs/" + job["id"] + "/complete",
                            json={"lease": job["lease"], "ok": False, "deferred": True})
            raise runtime.RuntimeFailure("other_job_claimed_and_deferred_without_execution")
        claim = {"job_id": job["id"], "runtime_id": payload["spec"]["runtime_id"],
                 "lease_sha256": hashlib.sha256(job["lease"].encode()).hexdigest(), "claimed_at": time.time()}
        value.setdefault("claims", []).append(claim)
        runtime.write_json(self.journal, value)
        return response


def volume_records(manager, identity):
    names = manager.docker_run("volume", "ls", "--filter", "label=peixian.runtime_id=" + identity,
                               "--format", "{{.Name}}").split()
    if not names:
        return {}
    result = {}
    for item in json.loads(manager.docker_run("volume", "inspect", *names)):
        if (item.get("Labels") or {}).get("peixian.runtime_id") != identity:
            raise runtime.RuntimeFailure("fault_volume_owner_mismatch")
        result[item["Name"]] = {"created_at": item.get("CreatedAt"), "driver": item["Driver"]}
    return result


def target_job(admin, job_id):
    return next((item for item in jobs(admin) if item["id"] == job_id), None)


def child(args):
    journal = args.state_root / "fault-acceptance/state.json"
    value = json.loads(journal.read_text(encoding="utf-8"))
    manager = ScopedRuntime(args.state_root, journal=journal, interrupt=True)
    key = read_credential(args.worker_key, 32)
    with worker.host_lock(manager.root), httpx.Client(base_url=args.control_url,
        headers={"X-Worker-Key": key}, timeout=60, trust_env=False, follow_redirects=False) as api:
        ScopedWorker(api, manager, journal, value["provision_job_id"]).once()
    raise runtime.RuntimeFailure("fault_hook_did_not_interrupt")


def run(args):
    manager = runtime.RuntimeManager(args.state_root)
    directory = manager.root / "fault-acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / "state.json"
    previous = {}
    if args.resume and args.report.is_file():
        previous = json.loads(args.report.read_text(encoding="utf-8"))
        if not journal.is_file() or previous.get("runtime_id") != json.loads(journal.read_text(encoding="utf-8"))["runtime_id"]:
            raise runtime.RuntimeFailure("fault_resume_evidence_identity_mismatch")
        if previous.get("status") == "passed" and json.loads(journal.read_text(encoding="utf-8")).get("phase") == "completed":
            print(json.dumps({"status": "already_completed", "passed": previous.get("passed"), "failed": previous.get("failed")}))
            return
    report = {"status": "running", "username": USERNAME,
              "checks": [item for item in previous.get("checks", []) if item.get("pass") is True],
              "started_at": previous.get("started_at", datetime.now(timezone.utc).isoformat()), "model_requests": 0}
    if previous:
        report["resumed_after"] = previous.get("status")

    def check(name, passed):
        report["checks"].append({"name": name, "pass": bool(passed)})
        runtime.write_json(args.report, report)
        if not passed:
            raise runtime.RuntimeFailure("fault_acceptance_check_failed")

    runtime.write_json(args.report, report)
    admin_password = read_credential(args.admin_password)
    worker_key = read_credential(args.worker_key, 32)
    with httpx.Client(base_url=args.control_url, headers={"Origin": args.control_url.rstrip("/")},
        timeout=60, trust_env=False, follow_redirects=False) as admin, httpx.Client(
        base_url=args.control_url, headers={"X-Worker-Key": worker_key}, timeout=60,
        trust_env=False, follow_redirects=False) as api:
        login = request(admin, "POST", PREFIX + "/auth/login", json={"username": "admin", "password": admin_password})
        admin.headers["X-CSRF-Token"] = login["csrf_token"]
        if login["user"].get("must_change_password"):
            raise runtime.RuntimeFailure("administrator_password_change_required")
        if args.resume:
            if not journal.is_file():
                raise runtime.RuntimeFailure("fault_resume_state_missing")
            value = json.loads(journal.read_text(encoding="utf-8"))
            account(admin, value["uid"])
        else:
            if journal.exists():
                raise runtime.RuntimeFailure("fault_state_exists_use_resume_after_review")
            with worker.host_lock(manager.root):
                require_quiet_queue(admin)
                users = request(admin, "GET", PREFIX + "/admin/users")
                if any(item["username"] == USERNAME for item in users["items"]):
                    raise runtime.RuntimeFailure("fault_account_already_exists")
                check("runtime_slot_available", users["capacity"]["reserved"] < users["capacity"]["maximum"])
                manager.capacity("0" * 32)
                password_file = ROOT / ".secrets/console-fault.password"
                if password_file.exists():
                    raise runtime.RuntimeFailure("fault_password_file_already_exists")
                runtime.write_secret(password_file, secrets.token_urlsafe(24))
                created = request(admin, "POST", PREFIX + "/admin/users", json={"username": USERNAME,
                    "password": read_credential(password_file), "model_ids": [], "plugin_ids": []})
                value = {"uid": runtime.check_id(created["user"]["id"]),
                         "runtime_id": runtime.check_id(created["user"]["runtime"]["id"]),
                         "provision_job_id": runtime.check_id(created["job"]["id"]), "phase": "created",
                         "baseline_reserved": users["capacity"]["reserved"], "claims": []}
                runtime.write_json(journal, value)
                check("new_runtime_has_no_volumes", volume_records(manager, value["runtime_id"]) == {})

        value = json.loads(journal.read_text(encoding="utf-8"))
        report.update(uid=value["uid"], runtime_id=value["runtime_id"], job_id=value["provision_job_id"])
        if value["phase"] == "created":
            # The child obtains the same host lock. There is no ordinary worker
            # running concurrently; an unexpected one makes this fail closed.
            command = [sys.executable, str(Path(__file__).resolve()), "--execute", "--child-interrupt",
                       "--state-root", str(manager.root), "--control-url", args.control_url,
                       "--worker-key", str(args.worker_key), "--admin-password", str(args.admin_password)]
            result = subprocess.run(command, capture_output=True, timeout=240,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            check("executor_exited_at_real_crash_hook", result.returncode == CRASH_EXIT)

        with worker.host_lock(manager.root):
            value = json.loads(journal.read_text(encoding="utf-8"))
            identity = value["runtime_id"]
            if value["phase"] == "interrupted_after_volume_create":
                initial = volume_records(manager, identity)
                check("exactly_first_created_volume_survived", set(initial) == {value["first_volume"]})
                check("no_runtime_container_started_before_crash", not manager.running(identity))
                active = target_job(admin, value["provision_job_id"])
                check("crashed_job_still_running_before_reclaim", active is not None and active["status"] == "running")
                value["first_volume_record"] = initial[value["first_volume"]]
                runtime.write_json(journal, value)
                # No heartbeat/complete/database update shortens this interval.
                # Hold the host lock to prevent another local worker from claiming.
                while time.time() - value["interrupted_at"] < 95:
                    remaining = 95 - (time.time() - value["interrupted_at"])
                    time.sleep(min(5, max(0.1, remaining)))
                check("lease_expired_naturally_at_least_95_seconds", time.time() - value["interrupted_at"] >= 95)
                require_quiet_queue(admin, value["uid"])
                scoped = ScopedRuntime(manager.root, journal=journal)
                done = ScopedWorker(api, scoped, journal, value["provision_job_id"]).once()
                check("restarted_executor_processed_target_job", done)
                latest = json.loads(journal.read_text(encoding="utf-8"))
                claims = [item for item in latest["claims"] if item["job_id"] == value["provision_job_id"]]
                check("same_job_and_runtime_after_restart", len(claims) >= 2 and
                      all(item["runtime_id"] == identity for item in claims))
                check("reclaimed_job_has_a_new_lease", claims[0]["lease_sha256"] != claims[-1]["lease_sha256"])
                updated, capacity = account(admin, value["uid"])
                check("restarted_runtime_ready", updated["runtime"]["status"] == "ready")
                check("same_provision_job_succeeded", target_job(admin, value["provision_job_id"])["status"] == "succeeded")
                final = volume_records(manager, identity)
                expected = {"px-" + identity + "-" + name for name in ("home", "workspace", "files")}
                check("exactly_three_unique_owned_volumes", set(final) == expected)
                check("first_volume_was_reused_not_recreated", final[value["first_volume"]] == value["first_volume_record"])
                latest.update(phase="ready", ready_volumes=final)
                runtime.write_json(journal, latest)

            value = json.loads(journal.read_text(encoding="utf-8"))
            if value["phase"] == "ready":
                require_quiet_queue(admin, value["uid"])
                agent = "px-" + identity + "-agent-1"
                marker = value.setdefault("sentinel_value", "CONSOLE-FAULT-RETAINED-" + secrets.token_hex(8))
                value["sentinel_sha256"] = hashlib.sha256(marker.encode()).hexdigest()
                runtime.write_json(journal, value)
                code = ("import json,sys;from pathlib import Path;v=json.load(sys.stdin);"
                        "p=Path('/workspace/.console-fault-sentinel');"
                        "p.write_text(v['value']) if not p.exists() else None;"
                        "assert p.read_text()==v['value']")
                manager.docker_run("exec", "-i", agent, "python3", "-c", code, data=runtime.json_bytes({"value": marker}))
                value["agent_image_id"] = json.loads(manager.docker_run("inspect", "--format", "{{json .Image}}", agent))
                _, before_pause = account(admin, value["uid"])
                existing = [item for item in jobs(admin) if item["uid"] == value["uid"] and item["action"] == "pause"
                            and item["status"] in ("queued", "running")]
                if len(existing) > 1:
                    raise runtime.RuntimeFailure("fault_pause_job_ambiguous")
                paused = {"job": existing[0]} if existing else request(
                    admin, "POST", PREFIX + "/admin/users/" + value["uid"] + "/runtime/pause", json={})
                value.update(phase="pause_queued", pause_job_id=runtime.check_id(paused["job"]["id"]),
                             reserved_before_pause=before_pause["reserved"])
                runtime.write_json(journal, value)

            value = json.loads(journal.read_text(encoding="utf-8"))
            if value["phase"] == "pause_queued":
                require_quiet_queue(admin, value["uid"])
                scoped = ScopedRuntime(manager.root, journal=journal)
                ScopedWorker(api, scoped, journal, value["pause_job_id"]).once()
                updated, capacity = account(admin, value["uid"])
                check("synthetic_account_paused", updated["runtime"]["status"] == "paused")
                check("runtime_slot_released", capacity["reserved"] == value["reserved_before_pause"] - 1)
                check("only_target_runtime_is_stopped", manager.running(identity) == [])
                check("all_owned_volumes_retained", volume_records(manager, identity) == value["ready_volumes"])
                volume = "px-" + identity + "-workspace"
                output = manager.docker_run("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                    "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                    "--memory", "64m", "--cpus", "0.5", "--pids-limit", "32",
                    "--mount", "type=volume,source=" + volume + ",target=/data,readonly", "--entrypoint", "python3",
                    value["agent_image_id"], "-c", "import hashlib,json;print(json.dumps({'sha256':hashlib.sha256(open('/data/.console-fault-sentinel','rb').read()).hexdigest()}))")
                check("synthetic_workspace_data_retained_after_pause", json.loads(output)["sha256"] == value["sentinel_sha256"])
                value.update(phase="completed")
                runtime.write_json(journal, value)
            check("fault_acceptance_completed", json.loads(journal.read_text())["phase"] == "completed")
            required = {"executor_exited_at_real_crash_hook", "exactly_first_created_volume_survived",
                        "lease_expired_naturally_at_least_95_seconds", "same_job_and_runtime_after_restart",
                        "reclaimed_job_has_a_new_lease", "restarted_runtime_ready", "same_provision_job_succeeded",
                        "exactly_three_unique_owned_volumes", "first_volume_was_reused_not_recreated",
                        "synthetic_account_paused", "runtime_slot_released", "all_owned_volumes_retained",
                        "synthetic_workspace_data_retained_after_pause"}
            check("all_recovery_and_retention_evidence_present", required.issubset(
                {item["name"] for item in report["checks"] if item["pass"]}))
            report["data_retained"] = True
            report["lease_wait_seconds_minimum"] = 95
            report["passed"] = sum(item["pass"] for item in report["checks"])
            report["failed"] = len(report["checks"]) - report["passed"]
            report["status"] = "passed" if not report["failed"] else "failed"
            runtime.write_json(args.report, report)
            print(json.dumps({"status": report["status"], "passed": report["passed"], "failed": report["failed"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--child-interrupt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--control-url", default="http://127.0.0.1:14090")
    parser.add_argument("--state-root", type=Path, default=ROOT / ".runtime/console")
    parser.add_argument("--admin-password", type=Path, default=ROOT / ".secrets/console-admin-current.password")
    parser.add_argument("--worker-key", type=Path, default=ROOT / ".secrets/console-worker.key")
    parser.add_argument("--report", type=Path, default=ROOT / ".runtime/console-fault-acceptance.json")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "plan", "account": USERNAME, "natural_lease_wait_seconds": 95,
                          "final_state": "paused with volumes and synthetic sentinel retained", "requires": "--execute"}))
        return
    address = urlsplit(args.control_url)
    if (address.scheme not in ("http", "https") or address.hostname not in ("127.0.0.1", "localhost", "::1") or
            address.username or address.password or address.query or address.fragment or address.path not in ("", "/")):
        raise runtime.RuntimeFailure("fault_control_must_be_local")
    if args.child_interrupt:
        child(args)
        return
    try:
        run(args)
    except Exception as error:
        report = json.loads(args.report.read_text()) if args.report.is_file() else {"checks": []}
        code = error.code if isinstance(error, runtime.RuntimeFailure) else "fault_acceptance_operation_failed"
        report.update(status="failed", error_code=code, data_retained=True)
        report["checks"].append({"name": "fault_acceptance_finished_without_error", "pass": False})
        report["passed"] = sum(item["pass"] for item in report["checks"])
        report["failed"] = len(report["checks"]) - report["passed"]
        runtime.write_json(args.report, report)
        print(json.dumps({"status": "failed", "passed": report["passed"], "failed": report["failed"], "code": code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
