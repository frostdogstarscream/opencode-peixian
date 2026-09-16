"""Explicitly interrupt only synthetic-r2-local Control; no remote or load test."""
import argparse
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import subprocess
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("n1_sdk", ROOT / "services/peixian-control/examples/console_client.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


async def docker(*args):
    result = await asyncio.to_thread(subprocess.run, ["docker", *args], capture_output=True, check=True, timeout=45)
    return result.stdout.decode("utf-8") + result.stderr.decode("utf-8")


async def run(args):
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert data["deployment_id"] == "synthetic-r2-local" and data["base_url"] == "https://127.0.0.1:19444"
    assert len(data["users"]) == 2 and all(u["username"].startswith("r2-local-") for u in data["users"])
    container = "synthetic-r2-local-console"
    labels = json.loads(await docker("inspect", "--format", "{{json .Config.Labels}}", container))
    assert labels["peixian.deployment"] == data["deployment_id"]
    report = {"status": "running", "scope": "windows_local_preliminary", "capacity_tested": False, "checks": []}
    tasks = []
    stopped = False
    async with AsyncExitStack() as stack:
        options = {"ca_file": args.manifest.parent / "tls/certificate.pem"}
        admin = await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], **options))
        await admin.login(data["admin"]["username"], data["admin"]["password"])
        a = await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], token=data["users"][0]["token"], **options))
        async def listen():
            ready = asyncio.Event()
            async def reader():
                try:
                    async with a.stream_http.stream("GET", sdk.PREFIX + "/events", headers=a.http.headers) as response:
                        a.check(response)
                        async for event in sdk.sse_events(response.aiter_lines()):
                            if json.loads(event["data"]).get("type") == "connected":
                                ready.set()
                except httpx.HTTPError:
                    pass
            task = asyncio.create_task(reader())
            tasks.append(task)
            await asyncio.wait_for(ready.wait(), 8)
            return task
        async def diagnostic():
            return (await admin.request("GET", "/admin/diagnostics/events"))["hub"]
        try:
            assert (await a.me())["runtime"]["gate_policy"] == "open"
            first = await listen()
            before = await diagnostic()
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await asyncio.sleep(.3)
            await listen()
            await asyncio.sleep(12)
            current = await diagnostic()
            assert current["created"] == before["created"] and current["subscribers"] == 1
            assert current["closing"] == 0 and current["upstreams"] == 1
            report["checks"].append({"name": "retention_reentry_keeps_reader", "passed": True})
            started = time.monotonic()
            stopped = True
            await docker("stop", "--time", "35", container)
            state = json.loads(await docker("inspect", "--format", "{{json .State}}", container))
            # Docker init may preserve SIGTERM as 143 after Uvicorn finishes cleanup.
            # Require the positive application evidence below; never accept SIGKILL/137.
            assert not state["Running"] and state["ExitCode"] in (0, 143) and not state["OOMKilled"]
            lines = (await docker("logs", "--tail", "100", container)).splitlines()
            assert any("Application shutdown complete." in line for line in lines)
            summary = json.loads(next(line.split("shutdown_summary ", 1)[1] for line in reversed(lines) if "shutdown_summary " in line))
            assert summary["unfinished"] == 0 and all(s["result"] == "done" for s in summary["stages"])
            report["checks"].append({"name": "control_stop_with_open_sse", "passed": True,
                "elapsed_seconds": round(time.monotonic() - started, 3), "exit_code": state["ExitCode"], "shutdown": summary})
            await docker("start", container)
            stopped = False
            async with asyncio.timeout(90):
                while True:
                    try:
                        value = (await a.me())["runtime"]
                        if value["status"] == "ready" and value["gate_policy"] == "open" and not value["recovery_required"]:
                            break
                    except (httpx.HTTPError, sdk.ConsoleError):
                        pass
                    await asyncio.sleep(.5)
            await listen()
            report["checks"].append({"name": "control_restart_reopens_after_verification", "passed": True})
            report["status"] = "passed"
        except Exception as error:
            report.update(status="failed", failure_code=type(error).__name__)
        finally:
            if stopped:
                await docker("start", container)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    raise SystemExit(asyncio.run(run(args)))
