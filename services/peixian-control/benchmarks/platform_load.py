"""Opt-in acceptance against an independently provisioned SYNTHETIC deployment.

Never provisions accounts or changes resource limits. Private manifest:
{"base_url":"https://test.example:19443", "deployment_id":"loadtest-r1",
 "users":[{"username":"loadtest-001","token":"px_..."}, ...]}
The manifest and tokens must remain outside Git. No prompt, token, username or
server URL is copied to the report. At least 50 ready synthetic users are needed.
This measures console workflows and sampled busy states, not model-server GPU
concurrency. Run platform-sample separately for container OOM/restart evidence.
"""
import argparse
from collections import deque
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.console_client import ConsoleClient, ConsoleError


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] * 1000, 3) if values else None


def load_manifest(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or set(value) != {"base_url", "deployment_id", "users"}
            or not re.fullmatch(r"loadtest-[a-z0-9-]{1,40}", value.get("deployment_id", ""))):
        raise ValueError("synthetic_manifest_required")
    users = value["users"]
    if not isinstance(users, list) or not 50 <= len(users) <= 64:
        raise ValueError("fifty_to_sixty_four_synthetic_accounts_required")
    for item in users:
        if (not isinstance(item, dict) or set(item) != {"username", "token"}
                or not re.fullmatch(r"loadtest-[a-zA-Z0-9_.-]{1,30}", item.get("username", ""))
                or not isinstance(item.get("token"), str) or not item["token"].startswith("px_")):
            raise ValueError("synthetic_account_manifest_invalid")
    if len({item["username"] for item in users}) != len(users) or len({item["token"] for item in users}) != len(users):
        raise ValueError("distinct_account_credentials_required")
    return value


async def stage(manifest, count, kind, duration, args):
    clients, session_ids = [], []
    measured = {"accounts": count, "scenario": kind, "seconds_requested": duration,
                "evidence": "real_console_workflows", "workflows_completed": 0, "errors": [],
                "peak_subscriptions": 0, "peak_sampled_busy_accounts": 0,
                "peak_workflows_in_flight": 0, "completed_plugin_tools": 0}
    api_times, durations = deque(maxlen=50000), deque(maxlen=50000)
    active = viewers = 0
    tasks, watchers = [], []
    gate, stop = asyncio.Event(), asyncio.Event()
    run_label = "loadtest-" + uuid.uuid4().hex[:12]
    started = time.monotonic()

    def failure(error):
        if len(measured["errors"]) < 100:
            measured["errors"].append({"type": type(error).__name__, "status": getattr(error, "status", None)})

    async def viewer(item, connected):
        nonlocal viewers
        try:
            async with ConsoleClient(manifest["base_url"], token=item["token"]) as client:
                async for event in client.events():
                    if not connected.is_set() and event["event"] == "change":
                        connected.set()
                        viewers += 1
                        measured["peak_subscriptions"] = max(measured["peak_subscriptions"], viewers)
                    if stop.is_set():
                        break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure(error)
        finally:
            if connected.is_set():
                viewers -= 1

    async def monitor():
        while not stop.is_set():
            async def inspect(index, client):
                before = time.monotonic()
                try:
                    await client.models()
                    api_times.append(time.monotonic() - before)
                    values = await client.sessions()
                    return any(item["id"] == session_ids[index] and item.get("status") != "idle" for item in values)
                except Exception as error:
                    failure(error)
                    return False
            states = await asyncio.gather(*(inspect(index, client) for index, client in enumerate(clients)))
            measured["peak_sampled_busy_accounts"] = max(measured["peak_sampled_busy_accounts"], sum(states))
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), 1)

    async def work(index, client):
        nonlocal active
        await gate.wait()
        end = time.monotonic() + duration
        while time.monotonic() < end and not stop.is_set():
            before = time.monotonic()
            active += 1
            measured["peak_workflows_in_flight"] = max(measured["peak_workflows_in_flight"], active)
            try:
                plugin = kind == "plugins" or (kind == "mixed" and index >= math.ceil(count * .6))
                if plugin:
                    # Explicit plugin connection-test entry executes the published
                    # synthetic plugin, without giving this runner arbitrary URLs.
                    result = await client.request("POST", "/plugins/" + args.plugin_id + "/test", json={})
                    if result.get("ok") is not True:
                        raise ConsoleError("synthetic_plugin_test_failed")
                else:
                    prior_ids = {item["info"]["id"] for item in await client.messages(session_ids[index])}
                    prompt = "这是合成并发验收，不包含业务资料。请用中文列出五十项连续编号，每项一句简单说明。"
                    if args.tool_generation:
                        prompt = "这是合成并发验收。请调用已授权的合成资料查询插件查询 TEST-001，然后仅总结合成结果。"
                    values = await client.run_message(session_ids[index], prompt, model_id=args.model_id, timeout=args.task_timeout)
                    tools = [part for message in values if message.get("info", {}).get("id") not in prior_ids
                             for part in message.get("parts", [])
                             if part.get("type") == "tool" and part.get("tool") == "调用已启用的插件"
                             and part.get("state", {}).get("status") == "completed"]
                    if args.tool_generation and not tools:
                        raise ConsoleError("no_completed_plugin_tool_in_model_result")
                    measured["completed_plugin_tools"] += len(tools)
                measured["workflows_completed"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failure(error)
                break  # Never automatically repeat an unknown/failed submission.
            finally:
                active -= 1
                durations.append(time.monotonic() - before)
    try:
        for item in manifest["users"][:count]:
            client = await ConsoleClient(manifest["base_url"], token=item["token"]).__aenter__()
            clients.append(client)
            me = await client.me()
            if (me["username"] != item["username"] or me["role"] != "user" or me["must_change_password"]
                    or (me.get("runtime") or {}).get("status") != "ready"):
                raise ValueError("synthetic_user_not_ready")
            session_ids.append((await client.create_session(run_label))["id"])
        if kind == "double-sse":
            connected = [asyncio.Event() for _ in range(count * 2)]
            for index, event in enumerate(connected):
                watchers.append(asyncio.create_task(viewer(manifest["users"][index // 2], event)))
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in connected)), 30)
            watchers.append(asyncio.create_task(monitor()))
            await asyncio.sleep(duration)
        else:
            watchers.append(asyncio.create_task(monitor()))
            tasks = [asyncio.create_task(work(index, client)) for index, client in enumerate(clients)]
            gate.set()
            await asyncio.gather(*tasks)
    except Exception as error:
        failure(error)
    finally:
        stop.set()
        for task in tasks + watchers:
            task.cancel()
        await asyncio.gather(*tasks, *watchers, return_exceptions=True)
        for client in clients:
            await client.__aexit__(None, None, None)
    measured.update(elapsed_seconds=round(time.monotonic() - started, 3),
                    control_api_samples=len(api_times), control_api_p95_ms=percentile(api_times, .95),
                    control_api_p99_ms=percentile(api_times, .99), workflow_p95_ms=percentile(durations, .95))
    measured["control_latency_passed"] = bool(api_times) and measured["control_api_p95_ms"] <= 500 and measured["control_api_p99_ms"] <= 1500
    measured["workflow_status"] = "passed" if not measured["errors"] and measured["control_latency_passed"] else "failed"
    measured["quantile_window"] = "last_50000_samples"
    measured["capacity_status"] = "not_verified"
    measured["status"] = measured["workflow_status"]
    if kind == "answers":
        enough = measured["peak_sampled_busy_accounts"] >= count and measured["workflows_completed"] >= count
        measured["capacity_status"] = "sampled_overlap_only" if enough else "not_verified"
        if not enough and measured["status"] == "passed":
            measured["status"] = "not_verified"
    elif measured["status"] == "passed":
        measured["status"] = "subscriptions_passed" if kind == "double-sse" else "connection_test_workflows_passed"
    measured["limitations"] = "Busy-state overlap is sampled, not sustained model-server concurrency. Plugin test endpoint is not Agent tool execution. Combine runtime sampling, real-tool generation, isolation and fault evidence."
    return measured


async def execute(args):
    manifest = load_manifest(args.credentials)
    report = {"format": 1, "started_at": datetime.now(timezone.utc).isoformat(), "stages": [],
              "deployment_fingerprint": hashlib.sha256(manifest["deployment_id"].encode()).hexdigest()[:16],
              "real_agent_container_count": "verify_separately_with_resource_report",
              "target_50_end_to_end": "requires_combined_runtime_model_network_and_isolation_evidence",
              "four_hour_test": "not_run", "auth_revocation_and_fault_injection": "separate_checks_required"}
    for count in (10, 20, 35, 50):
        for kind in ("answers", "plugins", "mixed", "double-sse"):
            result = await stage(manifest, count, kind, args.seconds, args)
            report["stages"].append(result)
            if result["status"] not in ("passed", "subscriptions_passed", "connection_test_workflows_passed"):
                return report  # Capacity progression stops on any stage failure.
    if args.soak_seconds:
        report["stages"].append(await stage(manifest, 50, "mixed", args.soak_seconds, args))
        report["four_hour_test"] = report["stages"][-1]["status"] if args.soak_seconds >= 14400 else "short_soak_only"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--soak-seconds", type=int, default=0)
    parser.add_argument("--task-timeout", type=int, default=180)
    parser.add_argument("--tool-generation", action="store_true")
    parser.add_argument("--synthetic-deployment", action="store_true", required=True)
    args = parser.parse_args()
    if (not 1 <= args.seconds <= 3600 or not 0 <= args.soak_seconds <= 86400 or not 1 <= args.task_timeout <= 1800
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", args.model_id)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args.plugin_id)):
        parser.error("invalid bounded scenario configuration")
    # Exclusive creation checks the report destination before any remote mutation.
    with args.output.open("x", encoding="utf-8") as target:
        try:
            report = asyncio.run(execute(args))
        except (ValueError, OSError, httpx.HTTPError) as error:
            report = {"status": "failed", "type": type(error).__name__, "target_50_end_to_end": "not_verified"}
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print("Sanitized acceptance report written; inspect its evidence limits before declaring capacity.")
    return 1 if report.get("status") == "failed" or any(item["status"] in ("failed", "not_verified") for item in report.get("stages", [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
