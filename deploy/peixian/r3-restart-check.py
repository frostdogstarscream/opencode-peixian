"""One idle synthetic Gateway restart; not a crash matrix or capacity test."""
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
spec = importlib.util.spec_from_file_location("sdk", ROOT / "services/peixian-control/examples/console_client.py")
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


async def run(args):
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert data["deployment_id"] == "synthetic-r2-local" and data["base_url"] == "https://127.0.0.1:19444"
    assert len(data["users"]) == 2 and all(u["username"].startswith("r2-local-") for u in data["users"])
    report = {"scope": "windows_local_preliminary", "capacity_tested": False, "status": "running", "checks": []}
    task = None
    async with AsyncExitStack() as stack:
        clients = [await stack.enter_async_context(sdk.ConsoleClient(data["base_url"], token=u["token"],
            ca_file=args.manifest.parent / "tls/certificate.pem")) for u in data["users"]]
        a, b = clients
        try:
            states = [(await c.me())["runtime"] for c in clients]
            assert all(r["status"] == "ready" and r["gate_policy"] == "open" for r in states)
            rid = states[0]["id"]
            assert len(rid) == 32 and all(c in "0123456789abcdef" for c in rid)
            name = "px-" + rid + "-gateway-1"
            raw = await asyncio.to_thread(subprocess.run, ["docker", "inspect", name], capture_output=True, text=True, check=True)
            container = json.loads(raw.stdout)[0]
            labels = container["Config"]["Labels"]
            assert labels["peixian.deployment"] == data["deployment_id"] and labels["peixian.runtime_id"] == rid
            assert labels["peixian.uid"] == data["users"][0]["uid"] and labels["com.docker.compose.service"] == "gateway"
            sid = (await a.create_session("R3 restart synthetic history"))["id"]
            await a.run_message(sid, "One short synthetic result before restart.", model_id=data["model_id"], timeout=60)
            history_count = len(await a.messages(sid))
            ready, interrupted = asyncio.Event(), asyncio.Event()
            async def reader():
                try:
                    async with a.stream_http.stream("GET", sdk.PREFIX + "/events", headers=a.http.headers) as response:
                        a.check(response)
                        async for event in sdk.sse_events(response.aiter_lines()):
                            value = json.loads(event["data"])
                            if value.get("type") == "connected": ready.set()
                            if value.get("type") == "resync_required": interrupted.set()
                except httpx.HTTPError:
                    pass
                finally:
                    interrupted.set()
            task = asyncio.create_task(reader())
            await asyncio.wait_for(ready.wait(), 8)
            started = time.monotonic()
            await asyncio.to_thread(subprocess.run, ["docker", "restart", "--time", "5", container["Id"]], capture_output=True, check=True, timeout=30)
            await asyncio.wait_for(interrupted.wait(), 15)
            async with asyncio.timeout(180):
                while True:
                    other = (await b.me())["runtime"]
                    assert other["status"] == "ready" and other["gate_policy"] == "open"
                    runtime = (await a.me())["runtime"]
                    if runtime["status"] == "ready" and runtime["gate_policy"] == "open" and not runtime["recovery_required"]:
                        break
                    await asyncio.sleep(.5)
            assert runtime["revision"] == states[0]["revision"] and runtime["desired"] == states[0]["desired"]
            assert len(await a.messages(sid)) == history_count
            # Explicit new request after recovery, never an automatic replay of the old one.
            await a.run_message(sid, "One short synthetic result after recovery.", model_id=data["model_id"], timeout=60)
            report["checks"].append({"name": "gateway_restart_resync_recovery_history_and_other_account", "passed": True,
                "elapsed_seconds": round(time.monotonic() - started, 3)})
            report["status"] = "passed"
        except Exception as error:
            report.update(status="failed", failure_code=type(error).__name__)
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
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
    raise SystemExit(asyncio.run(run(args)))
