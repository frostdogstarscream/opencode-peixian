"""Sequential, synthetic local R2 checks; no capacity or sustained-load claim.

Supply the private manifest prepared for this test namespace. Existing user data
is never imported. Only manifest-bound synthetic accounts may be changed.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import uuid

import httpx
from evidence_contract import Run, tracked_run

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("local_sdk", ROOT.parents[1] / "services/peixian-control/examples/console_client.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


class CheckFailed(RuntimeError):
    pass


def check(condition, code):
    if not condition:
        raise CheckFailed(code)


async def run(args):
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    check(data["deployment_id"] == "synthetic-r2-local", "isolated_local_namespace_required")
    check(data["base_url"] == "https://127.0.0.1:19444", "local_entry_required")
    check(len(data["users"]) == 2 and all(item["username"].startswith("r2-local-") for item in data["users"]), "synthetic_accounts_required")
    options = {"ca_file": args.manifest.parent / "tls/certificate.pem"}
    report = {"status": "running", "scope": "local_preliminary", "real_runtimes": 2,
              "concurrency_tested": False, "paid_model_used": False, "checks": []}
    def record(name, **fields):
        report["checks"].append({"name": name, "passed": True, **fields})
        print(json.dumps(report["checks"][-1], ensure_ascii=False), flush=True)
    started = time.monotonic()
    async with AsyncExitStack() as stack:
        admin = await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], **options))
        await admin.login(data["admin"]["username"], data["admin"]["password"])
        clients = [await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], token=item["token"], **options)) for item in data["users"]]
        manager = await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], token=data["manager"]["token"], **options))
        fixture = await stack.enter_async_context(httpx.AsyncClient(base_url=data["fixture"]["url"], trust_env=False,
            headers={"Authorization": "Bearer " + Path(data["fixture"]["key_file"]).read_text().strip()}, timeout=5))
        async def usable(client, timeout=180):
            async with asyncio.timeout(timeout):
                while True:
                    value = (await client.me())["runtime"]
                    if (value["status"] == "ready" and value["revision"] == value["desired"] and value.get("gate_policy") == "open"
                            and not value.get("security_blocked") and not value.get("recovery_required")):
                        return value
                    await asyncio.sleep(.5)
        async def done(client, sid, timeout=90):
            async with asyncio.timeout(timeout):
                while True:
                    values = await client.messages(sid)
                    answers = [item for item in values if item["info"]["role"] == "assistant"]
                    check(not any(item["info"].get("error") for item in answers), "synthetic_answer_error")
                    if any(item["info"].get("time", {}).get("completed") for item in answers):
                        return values
                    await asyncio.sleep(.5)
        try:
            for client in clients:
                await usable(client)
            record("two_real_environments_open_after_verified_provision")
            check((await manager.me())["role"] == "admin", "admin_role")
            check((await manager.me())["runtime"] is None, "admin_has_no_agent")
            denied = await manager.http.get(sdk.PREFIX + "/admin/maintenance")
            check(denied.status_code == 403, "maintenance_is_super_admin_only")
            record("three_role_boundary")
            ids = []
            for label, client in zip(("A", "B"), clients):
                sid = (await client.create_session("Local synthetic " + label))["id"]
                ids.append(sid)
                result = await client.send_message(sid, "Return a short deterministic synthetic result.", model_id=data["model_id"])
                check(result.get("accepted") is True, "prompt_not_accepted")
                await done(client, sid)
                record("native_agent_synthetic_answer", account=label)
            denied = await clients[1].http.get(sdk.PREFIX + "/sessions/" + ids[0] + "/messages")
            check(denied.status_code == 404, "session_account_boundary")
            upload = await clients[0].request("POST", "/files", files={"file": ("local-synthetic.txt", b"local synthetic content", "text/plain")})
            parsed = await clients[0].wait_for_file(upload["id"])
            check("local synthetic content" in parsed["text"], "text_parse")
            denied = await clients[1].http.get(sdk.PREFIX + "/files/" + upload["id"] + "/download")
            check(denied.status_code == 404, "file_account_boundary")
            record("file_parse_and_account_isolation")
            initial = await usable(clients[0])
            marker = "r2-" + uuid.uuid4().hex
            response = await fixture.post("/internal/fixture/modes/" + marker, json={"seconds": 120})
            response.raise_for_status()
            before = (await fixture.get("/internal/fixture/stats")).json()["accepted"]
            sid = (await clients[0].create_session("Local update during answer"))["id"]
            await clients[0].send_message(sid, "Synthetic " + marker, model_id=data["model_id"])
            async with asyncio.timeout(15):
                while (await fixture.get("/internal/fixture/stats")).json()["accepted"] <= before:
                    await asyncio.sleep(.2)
            skill = await clients[0].request("POST", "/skills", json={"name": "local-r2-" + uuid.uuid4().hex[:8],
                "description": "Synthetic local smoke", "content": "Summarize synthetic input only.", "enabled": False})
            check(skill.get("job"), "skill_publish_job")
            if getattr(args, "run_manifest", None):
                Run(args.run_manifest).own(skill["job"]["id"], "busy_update", "recorded")
            # Pending desired alone does not prove the Worker observed busy.
            # Wait for the persisted defer receipt before releasing the fixture.
            try:
                async with asyncio.timeout(50):
                    while True:
                        jobs = (await admin.request("GET", "/admin/jobs"))["items"]
                        job = next((item for item in jobs if item["id"] == skill["job"]["id"]), None)
                        check(job is not None and job["status"] not in ("failed", "cancelled", "succeeded"), "busy_job_finished_before_defer")
                        if job["defer_count"] > 0:
                            break
                        await asyncio.sleep(.5)
            except BaseException:
                await fixture.post("/internal/fixture/modes/" + marker, json={"release": True})
                raise
            pending = (await clients[0].me())["runtime"]
            check(pending["revision"] == initial["revision"] and pending["desired"] == initial["desired"] + 1, "applied_changed_while_busy")
            check((await clients[1].me())["runtime"]["status"] == "ready", "other_account_unavailable")
            await fixture.post("/internal/fixture/modes/" + marker, json={"release": True})
            await done(clients[0], sid)
            published = await usable(clients[0])
            check(published["revision"] == initial["desired"] + 1, "configuration_version_incorrect")
            record("busy_update_defers_then_verifies_applied_without_extra_desired", persisted_defer_count=job["defer_count"])
            check("local synthetic content" in (await clients[0].text(upload["id"]))["text"], "update_lost_file")
            check(len(await clients[0].messages(ids[0])) >= 2, "update_lost_history")
            record("configuration_rebuild_preserves_history_and_files")
            await clients[0].delete_file(upload["id"])
            report["status"] = "passed"
        except Exception as error:
            report.update(status="failed", failure_code=str(error) if isinstance(error, CheckFailed) else type(error).__name__)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "concurrency_tested": False}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args()
    check(not args.output.exists(), "report_must_be_new")
    raise SystemExit(asyncio.run(tracked_run(run, args, "busy_update")))
