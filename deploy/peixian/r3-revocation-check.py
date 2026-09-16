"""Sequential local account-disable check; re-enables only its synthetic account."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sdk", ROOT / "services/peixian-control/examples/console_client.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


async def run(args):
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert data["deployment_id"] == "synthetic-r2-local" and data["base_url"] == "https://127.0.0.1:19444"
    assert len(data["users"]) == 2 and data["users"][1]["username"] == "r2-local-b"
    account = data["users"][1]
    options = {"ca_file": args.manifest.parent / "tls/certificate.pem"}
    report = {"scope": "windows_local_preliminary", "capacity_tested": False, "checks": [], "status": "running"}
    async with sdk.ConsoleClient(data["base_url"], **options) as admin, sdk.ConsoleClient(data["base_url"], token=account["token"], **options) as old:
        await admin.login(data["admin"]["username"], data["admin"]["password"])
        ready = asyncio.Event()
        async def reader():
            try:
                async with old.stream_http.stream("GET", sdk.PREFIX + "/events", headers=old.http.headers) as response:
                    old.check(response)
                    async for event in sdk.sse_events(response.aiter_lines()):
                        if json.loads(event["data"]).get("type") == "connected":
                            ready.set()
            except httpx.HTTPError:
                pass
        task = asyncio.create_task(reader())
        disabled = False
        try:
            await asyncio.wait_for(ready.wait(), 8)
            started = time.monotonic()
            await admin.request("PATCH", "/admin/users/" + account["uid"], json={"active": False})
            disabled = True
            await asyncio.wait_for(task, max(.1, 5 - (time.monotonic() - started)))
            elapsed = time.monotonic() - started
            assert (await old.http.get(sdk.PREFIX + "/me")).status_code == 401
            report["checks"].append({"name": "disabled_account_closes_old_stream_and_auth", "passed": True, "elapsed_seconds": round(elapsed, 3)})
        except Exception as error:
            report.update(status="failed", failure_code=type(error).__name__)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if disabled:
                # Re-enable only after the platform confirms its safety-stop job.
                async with asyncio.timeout(240):
                    while True:
                        items = (await admin.request("GET", "/admin/users"))["items"]
                        item = next(x for x in items if x["id"] == account["uid"])
                        if item["runtime"]["status"] == "paused" and item["runtime"]["phase"] is None:
                            break
                        await asyncio.sleep(.5)
                await admin.request("PATCH", "/admin/users/" + account["uid"], json={"active": True})
                async with sdk.ConsoleClient(data["base_url"], **options) as restored:
                    await restored.login(account["username"], account["password"])
                    token = await restored.request("POST", "/tokens", json={"name": "local-preliminary-test"})
                    account["token"] = token["token"]
                    # The caller-provided private manifest is the only credential output.
                    args.manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    async with asyncio.timeout(240):
                        while True:
                            runtime = (await restored.me())["runtime"]
                            if runtime["status"] == "ready" and runtime["gate_policy"] == "open":
                                break
                            await asyncio.sleep(.5)
                    report["checks"].append({"name": "explicit_reenable_restores_environment", "passed": True})
        if report["status"] == "running":
            report["status"] = "passed"
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "New report path required"
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        # Preserve failure evidence even when cleanup itself cannot complete.
        if not args.output.exists():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"scope": "windows_local_preliminary", "status": "failed",
                "failure_code": type(error).__name__, "recovery_requires_check": True}), encoding="utf-8")
        print(json.dumps({"status": "failed", "recovery_requires_check": True}))
        result = 1
    raise SystemExit(result)
