"""Two-account sequential event checks. No capacity, paid model or remote test."""
import argparse
import asyncio
from contextlib import AsyncExitStack, suppress
import importlib.util
import json
from pathlib import Path
import time

import httpx
from evidence_contract import tracked_run

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("console_sdk", ROOT / "services/peixian-control/examples/console_client.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


async def run(args):
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert data["deployment_id"] == "synthetic-r2-local"
    assert data["base_url"] == "https://127.0.0.1:19444"
    assert len(data["users"]) == 2 and all(u["username"].startswith("r2-local-") for u in data["users"])
    report = {"scope": "windows_local_preliminary", "accounts": 2, "capacity_tested": False,
              "paid_model_used": False, "checks": [], "status": "running", "stage": "ready_precondition"}
    tasks = []
    tokens = []
    started = time.monotonic()
    async with AsyncExitStack() as stack:
        async def client(token=None):
            return await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], token=token,
                ca_file=args.manifest.parent / "tls/certificate.pem"))
        admin = await client()
        await admin.login(data["admin"]["username"], data["admin"]["password"])
        a, b = [await client(u["token"]) for u in data["users"]]
        async def diagnostic():
            return (await admin.request("GET", "/admin/diagnostics/events"))["hub"]
        async def wait_until(predicate, timeout=15):
            async with asyncio.timeout(timeout):
                while not await predicate():
                    await asyncio.sleep(.1)
        def record(name, **extra):
            result = {"name": name, "passed": True, **extra}
            report["checks"].append(result)
            print(json.dumps(result), flush=True)
        async def token(owner):
            value = await owner.request("POST", "/tokens", json={"name": "r3-synthetic-subscription"})
            tokens.append((owner, value["item"]["id"]))
            return value
        async def listen(c):
            ready = asyncio.Event()
            result = {"sessions": set(), "changes": 0}
            async def reader():
                try:
                    async with c.stream_http.stream("GET", sdk.PREFIX + "/events", headers=c.http.headers) as response:
                        c.check(response)
                        async for event in sdk.sse_events(response.aiter_lines()):
                            value = json.loads(event["data"])
                            if value.get("type") == "connected":
                                ready.set()
                            if value.get("type") == "updated":
                                result["changes"] += 1
                                if value.get("session_id"):
                                    result["sessions"].add(value["session_id"])
                except httpx.HTTPError:
                    # A terminated HTTP stream is closed, never automatically retried here.
                    return
            task = asyncio.create_task(reader())
            tasks.append(task)
            await asyncio.wait_for(ready.wait(), 8)
            return task, result
        try:
            for c in (a, b):
                value = (await c.me())["runtime"]
                assert value["status"] == "ready" and value["gate_policy"] == "open"
                denied = await c.http.get(sdk.PREFIX + "/admin/diagnostics/events")
                assert denied.status_code == 403
            report["stage"] = "shared_subscriptions"
            t1, t2 = await token(a), await token(a)
            first, second = await client(t1["token"]), await client(t2["token"])
            one, seen1 = await listen(first)
            two, seen2 = await listen(second)
            other, seenb = await listen(b)
            stats = await diagnostic()
            assert stats["hubs"] == stats["upstreams"] == 2 and stats["subscribers"] == 3
            record("two_account_readers_for_three_independent_subscriptions")
            report["stage"] = "answer_notification"
            sid = (await a.create_session("R3 synthetic shared stream"))["id"]
            await a.run_message(sid, "Give one short synthetic result.", model_id=data["model_id"], timeout=60)
            assert sid in seen1["sessions"] and sid in seen2["sessions"] and sid not in seenb["sessions"]
            record("shared_notifications_real_agent_answer_and_account_boundary")
            report["stage"] = "token_revocation"
            revoke_started = time.monotonic()
            await a.request("DELETE", "/tokens/" + t1["item"]["id"])
            await asyncio.wait_for(one, max(.1, 5 - (time.monotonic() - revoke_started)))
            elapsed = time.monotonic() - revoke_started
            assert not two.done() and not other.done()
            assert (await first.http.get(sdk.PREFIX + "/me")).status_code == 401
            record("one_token_revoked_without_closing_other_viewers", elapsed_seconds=round(elapsed, 3))
            report["stage"] = "last_viewer_cleanup"
            for task in (two, other):
                task.cancel()
            await asyncio.gather(two, other, return_exceptions=True)
            async def cleared():
                return (await diagnostic())["hubs"] == 0
            await wait_until(cleared, 65)
            record("last_viewer_cleanup_within_retention_budget")
            report["stage"] = "reopen_history"
            reopened, result = await listen(second)
            assert len(await second.messages(sid)) >= 2
            assert (await diagnostic())["upstreams"] == 1
            reopened.cancel()
            await asyncio.gather(reopened, return_exceptions=True)
            record("reopen_restores_persisted_history")
            report.update(status="passed", stage="finished")
        except Exception as error:
            report.update(status="failed", failure_code=type(error).__name__)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for owner, token_id in tokens:
                with suppress(Exception):
                    await owner.request("DELETE", "/tokens/" + token_id)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args()
    assert not args.output.exists(), "New report path required"
    raise SystemExit(asyncio.run(tracked_run(run, args, "event_subscriptions")))
