"""Opt-in Control-only load evidence over a real loopback Uvicorn socket.

The SQLite/auth/SSE/offload paths are real. Per-account Gateway responses and
model generation are synthetic MockTransport fixtures: no Docker or LLM runs.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import platform
import random
import secrets
import socket
import sys
import tempfile
import time

import httpx
import uvicorn
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control.app import create_app
from control.store import Store, digest, ident, now

PREFIX = "/api/console/v1"
METRICS = ("health", "me", "messages", "sessions", "models", "files", "skills", "plugins")


@dataclass
class Account:
    uid: str
    runtime_id: str
    token: str

    @property
    def sid(self):
        return "ses_" + self.uid

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.token}


class Samples:
    """Bound long-run memory; quantiles describe a deterministic reservoir."""
    def __init__(self):
        self.values = []
        self.status = Counter()
        self.count = 0
        self.maximum = 0.0
        self.random = random.Random(1701)

    def add(self, milliseconds, status):
        self.count += 1
        self.status[str(status)] += 1
        self.maximum = max(self.maximum, milliseconds)
        if len(self.values) < 50000:
            self.values.append(milliseconds)
        else:
            index = self.random.randrange(self.count)
            if index < len(self.values):
                self.values[index] = milliseconds

    def summary(self):
        values = sorted(self.values)
        quantile = lambda fraction: round(values[min(len(values) - 1, max(0, math.ceil(len(values) * fraction) - 1))], 2) if values else None
        return {"count": self.count, "sample_count": len(values), "status_counts": dict(self.status),
                "p95_ms": quantile(.95), "p99_ms": quantile(.99), "maximum_ms": round(self.maximum, 2)}


class NativeEvents(httpx.AsyncByteStream):
    def __init__(self, fixture, account):
        self.fixture, self.account = fixture, account
        self.closed = False

    async def __aiter__(self):
        account = self.account
        base = {"sessionID": account.sid}
        info = {"id": "msg_" + account.uid, "sessionID": account.sid, "role": "assistant", "time": {"created": 1}}
        part = {"id": "part_" + account.uid, "sessionID": account.sid, "messageID": info["id"], "type": "text", "text": ""}
        events = [("message.updated", {**base, "info": info}), ("message.part.updated", {**base, "part": part})]
        sequence = 0
        while not self.closed:
            if events:
                kind, properties = events.pop(0)
            else:
                await asyncio.sleep(self.fixture.event_interval)
                kind = "message.part.delta"
                properties = {**base, "messageID": info["id"], "partID": part["id"], "field": "text", "delta": "synthetic "}
            envelope = {"directory": "/workspace", "payload": {"id": "evt_" + account.uid + "_" + str(sequence),
                        "type": kind, "properties": properties}}
            sequence += 1
            yield ("data: " + json.dumps(envelope) + "\n\n").encode()

    async def aclose(self):
        self.closed = True


class GatewayFixture:
    def __init__(self, accounts, delay, event_interval):
        self.by_host = {"px-" + account.runtime_id + "-gateway": account for account in accounts}
        self.delay, self.event_interval = delay, event_interval
        self.generating = set()
        self.peak_generating = 0
        self.requests = 0

    async def handle(self, request):
        self.requests += 1
        account = self.by_host.get(request.url.host)
        if account is None:
            return httpx.Response(404, json={"message": "Unknown synthetic account"})
        path = request.url.path
        if path == "/global/event":
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=NativeEvents(self, account))
        await asyncio.sleep(self.delay)
        session = {"id": account.sid, "directory": "/workspace", "title": "Synthetic load session", "time": {"created": 1, "updated": 1}}
        if path == "/session":
            return httpx.Response(200, json=[session] if request.method == "GET" else session)
        if path in ("/files", "/results"):
            return httpx.Response(200, json={"items": []})
        if path in ("/permission", "/question", "/skill"):
            return httpx.Response(200, json=[])
        if path == "/session/status":
            return httpx.Response(200, json={account.sid: {"type": "busy" if account.uid in self.generating else "idle"}})
        if path == "/session/" + account.sid:
            return httpx.Response(200, json=session)
        if path == "/session/" + account.sid + "/message":
            return httpx.Response(200, json=[{
                "info": {"id": "msg_" + account.uid, "sessionID": account.sid, "role": "assistant", "time": {"created": 1}},
                "parts": [{"id": "part_" + account.uid, "sessionID": account.sid, "messageID": "msg_" + account.uid, "type": "text", "text": "Synthetic fixture reply"}],
            }])
        if path == "/session/" + account.sid + "/prompt_async":
            self.generating.add(account.uid)
            self.peak_generating = max(self.peak_generating, len(self.generating))
            return httpx.Response(204)
        if path == "/session/" + account.sid + "/abort":
            self.generating.discard(account.uid)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"message": "Not in this synthetic account"})


def seed(root, count):
    password = "Synthetic-load-" + secrets.token_urlsafe(20)
    for name, value in (("key", Fernet.generate_key()), ("worker", secrets.token_urlsafe(48).encode()), ("admin", password.encode())):
        (root / name).write_bytes(value)
    store = Store(root / "data", root / "key", root / "worker", root / "admin")
    accounts = [Account(ident(), ident(), "px_" + secrets.token_urlsafe(48)) for _ in range(count)]
    password_hash = store.one("SELECT password FROM users WHERE role='super_admin'")["password"]
    # Fixture provisioning is deliberately outside measurement; there is no Docker Worker.
    with store.tx() as db:
        db.execute("INSERT INTO models VALUES('synthetic-model','Synthetic model','Control-only fixture','http://unused.invalid/v1','fixture',?,1,1)", (store.encrypt("synthetic-unused-model-key"),))
        for index, account in enumerate(accounts):
            db.execute("INSERT INTO users VALUES(?,?,?,'user',1,0,1,?)", (account.uid, "load-user-" + str(index), password_hash, now()))
            db.execute("INSERT INTO auth VALUES(?,?,'token','load fixture',NULL,?,1,?)", (digest(account.token), account.uid, now() + 86400, now()))
            spec = store.encrypt({"gateway_key": secrets.token_urlsafe(48), "agent_password": secrets.token_urlsafe(48), "legacy": None})
            db.execute("INSERT INTO runtimes VALUES(?,?,'ready',1,1,1,NULL,?,?)", (account.uid, account.runtime_id, spec, now()))
            db.execute("INSERT INTO grants VALUES(?,'model','synthetic-model')", (account.uid,))
    return store, accounts, password


async def execute(args, root):
    store, accounts, bootstrap = seed(root, max(args.stages))
    fixture = GatewayFixture(accounts, args.gateway_delay_ms / 1000, args.event_interval_ms / 1000)
    if args.serve_only:
        static = Path(__file__).resolve().parents[3] / "packages" / "peixian-console" / "dist"
        if not (static / "index.html").is_file():
            raise RuntimeError("Build the console frontend before serve-only")
        os.environ["CONSOLE_STATIC"] = str(static)
    app = create_app(store)
    normal_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fixture_lifespan(application):
        async with normal_lifespan(application):
            for name in ("http", "stream_http", "download_http"):
                await getattr(application.state, name).aclose()
                setattr(application.state, name, httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle), trust_env=False))
            yield

    app.router.lifespan_context = fixture_lifespan
    listener = socket.socket()
    listener.bind(("127.0.0.1", args.port if args.serve_only else 0))
    listener.listen(128)
    base_url = "http://127.0.0.1:" + str(listener.getsockname()[1])
    os.environ["CONSOLE_ORIGINS"] = base_url
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, log_level="critical", access_log=False,
                                          timeout_graceful_shutdown=5, lifespan="on"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    subscribers, subscriber_tasks = [], []
    load_tasks = []
    stop_monitor = asyncio.Event()
    peak = {"viewers": 0, "upstreams": 0, "owners": 0, "client_requests_in_flight": 0, "db_outstanding": 0}
    in_flight = 0
    monitoring = None
    stage_reports = []
    outcomes = {}
    started = time.monotonic()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if serving.done():
                await serving
                raise RuntimeError("Synthetic Control failed to start")
            if time.monotonic() > deadline:
                raise RuntimeError("Synthetic Control startup timed out")
            await asyncio.sleep(.02)
        async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=httpx.Timeout(10),
                                     limits=httpx.Limits(max_connections=128, max_keepalive_connections=64)) as http, \
                   httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=httpx.Timeout(None, connect=5, pool=5),
                                     limits=httpx.Limits(max_connections=max(args.stages) * 2 + 5)) as streaming:
            # Real password verification/hash and Cookie/CSRF path, once, outside timings.
            login = await http.post(PREFIX + "/auth/login", json={"username": "admin", "password": bootstrap}, headers={"Origin": base_url})
            if login.status_code != 200:
                raise RuntimeError("Synthetic bootstrap login failed")
            changed = await http.post(PREFIX + "/me/password", json={"current_password": bootstrap, "password": bootstrap + "-changed"},
                                      headers={"Origin": base_url, "X-CSRF-Token": login.json()["csrf_token"]})
            if changed.status_code != 200:
                raise RuntimeError("Synthetic bootstrap password change failed")
            http.cookies.clear()
            if args.serve_only:
                with args.credentials_file.open("x", encoding="utf-8") as handle:
                    json.dump({"base_url": base_url,
                               "admin": {"username": "admin", "password": bootstrap + "-changed"},
                               "users": [{"username": "load-user-" + str(index), "password": bootstrap} for index in range(len(accounts))]}, handle)
                print(json.dumps({"fixture_ready": True, "base_url": base_url, "synthetic_accounts": len(accounts),
                                  "model_is_mocked": True, "credential_file_written": True}), file=sys.stderr, flush=True)
                await asyncio.sleep(args.serve_seconds)
                return {"profile": "synthetic-browser-fixture-only", "control_fixture_passed": True, "load_test_executed": False}

            async def monitor():
                while not stop_monitor.is_set():
                    stats = app.state.stream_registry.stats()
                    for name in ("viewers", "upstreams", "owners"):
                        peak[name] = max(peak[name], stats[name])
                    peak["db_outstanding"] = max(peak["db_outstanding"], app.state.db_work.outstanding)
                    await asyncio.sleep(.02)

            monitoring = asyncio.create_task(monitor())

            async def subscribe(account, record):
                try:
                    async with streaming.stream("GET", PREFIX + "/events", headers=account.headers) as response:
                        record["status"] = response.status_code
                        if response.status_code != 200:
                            record["ready"].set()
                            return
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                try:
                                    payload = json.loads(line[5:])
                                except ValueError:
                                    record["invalid_events"] += 1
                                    continue
                                if payload.get("type") == "connected":
                                    record["ready"].set()
                                elif payload.get("type") == "updated":
                                    record["events"] += 1
                                    if payload.get("session_id") not in (None, account.sid):
                                        record["foreign_events"] += 1
                except asyncio.CancelledError:
                    raise
                except httpx.HTTPError:
                    record["transport_error"] = True
                finally:
                    record["ready"].set()
                    record["closed_at"] = time.monotonic()
                    record["closed"].set()

            async def measured(http, path, account, bucket):
                nonlocal in_flight
                in_flight += 1
                peak["client_requests_in_flight"] = max(peak["client_requests_in_flight"], in_flight)
                before = time.perf_counter()
                try:
                    response = await http.get(path, headers=account.headers)
                    status = response.status_code
                    if status == 200 and path.endswith("/messages"):
                        for message in response.json().get("items", []):
                            if message.get("info", {}).get("sessionID") != account.sid:
                                outcomes["foreign_message"] = True
                    return response
                except httpx.HTTPError:
                    status = "transport_error"
                finally:
                    bucket.add((time.perf_counter() - before) * 1000, status)
                    in_flight -= 1

            for count in args.stages:
                for account in accounts[len(subscribers) // 2:count]:
                    for _ in range(2):
                        record = {"ready": asyncio.Event(), "closed": asyncio.Event(), "events": 0, "foreign_events": 0, "invalid_events": 0}
                        subscribers.append(record)
                        subscriber_tasks.append(asyncio.create_task(subscribe(account, record)))
                    await asyncio.sleep(.01)
                await asyncio.wait_for(asyncio.gather(*(record["ready"].wait() for record in subscribers)), timeout=15)
                if any(record.get("status") != 200 or record["closed"].is_set() for record in subscribers):
                    raise RuntimeError("Synthetic SSE admission or connection failed")
                for account in accounts[:count]:
                    if account.uid not in fixture.generating:
                        response = await http.post(PREFIX + "/sessions/" + account.sid + "/messages", headers=account.headers,
                                                   json={"text": "Synthetic Control load only", "model_id": "synthetic-model"})
                        if response.status_code != 202:
                            raise RuntimeError("Synthetic prompt admission failed")
                metrics = {name: Samples() for name in METRICS}
                stop = asyncio.Event()

                async def traffic(account):
                    routes = [("health", "/health", 5), ("me", PREFIX + "/me", 5),
                              ("messages", PREFIX + "/sessions/" + account.sid + "/messages", args.request_pause_ms / 1000),
                              ("sessions", PREFIX + "/sessions", 2),
                              *[(name, PREFIX + "/" + name, 30) for name in ("models", "files", "skills", "plugins")]]
                    # Independent browser timers have phases; do not manufacture a synchronized herd.
                    phase = accounts.index(account) / len(accounts)
                    due = {name: time.monotonic() + phase * interval for name, _, interval in routes}
                    while not stop.is_set():
                        name, path, interval = min(routes, key=lambda item: due[item[0]])
                        delay = due[name] - time.monotonic()
                        if delay > 0:
                            try:
                                await asyncio.wait_for(stop.wait(), timeout=delay)
                                return
                            except asyncio.TimeoutError:
                                pass
                        if stop.is_set():
                            return
                        await measured(http, path, account, metrics[name])
                        due[name] = max(due[name] + interval, time.monotonic() + .001)

                before = time.monotonic()
                load_tasks = [asyncio.create_task(traffic(account)) for account in accounts[:count]]
                await asyncio.sleep(args.stage_seconds)
                stop.set()
                await asyncio.gather(*load_tasks)
                load_tasks = []
                stage_reports.append({"accounts": count, "target_sse": count * 2, "duration_seconds": round(time.monotonic() - before, 2),
                                      "active_synthetic_generations": len(fixture.generating), "streams": app.state.stream_registry.stats(),
                                      "early_stream_closures": sum(record["closed"].is_set() for record in subscribers),
                                      "metrics": {name: value.summary() for name, value in metrics.items()}})
                print(json.dumps({"stage_accounts": count, "sse": app.state.stream_registry.stats()["viewers"], "completed": True}), file=sys.stderr, flush=True)

            if any(record["closed"].is_set() for record in subscribers):
                raise RuntimeError("A synthetic SSE stream closed before the revocation scenario")
            # Keep other accounts reading while the token and its two streams are revoked.
            metrics = {name: Samples() for name in METRICS}
            stop = asyncio.Event()
            load_tasks = [asyncio.create_task(traffic(account)) for account in accounts[1:]]
            await asyncio.sleep(.05)
            revocation_start = time.monotonic()
            revoke = await http.delete(PREFIX + "/tokens/" + digest(accounts[0].token), headers=accounts[0].headers)
            await asyncio.wait_for(asyncio.gather(*(record["closed"].wait() for record in subscribers[:2])), timeout=5)
            revocation_seconds = max(record["closed_at"] for record in subscribers[:2]) - revocation_start
            outcomes["revocation"] = {"delete_status": revoke.status_code, "stream_close_seconds": round(revocation_seconds, 3),
                                       "new_request_status": (await http.get(PREFIX + "/me", headers=accounts[0].headers)).status_code}
            stop.set()
            await asyncio.gather(*load_tasks)
            load_tasks = []
            outcomes["revocation_background_accounts"] = len(accounts) - 1
            outcomes["revocation_background_metrics"] = {name: value.summary() for name, value in metrics.items()}
            if len(accounts) > 1:
                cross = await http.get(PREFIX + "/sessions/" + accounts[0].sid + "/messages", headers=accounts[-1].headers)
                outcomes["cross_account_status"] = cross.status_code
            for task in subscriber_tasks:
                task.cancel()
            await asyncio.gather(*subscriber_tasks, return_exceptions=True)
            for _ in range(100):
                if app.state.stream_registry.stats()["viewers"] == 0:
                    break
                await asyncio.sleep(.02)
            final_streams = app.state.stream_registry.stats()
            stop_monitor.set()
            await monitoring
            report = {
                "profile": "L2-control-only-real-loopback-http-with-mocked-gateways",
                "evidence_boundary": {"real": ["single Uvicorn process", "loopback TCP HTTP/SSE", "SQLite WAL", "auth and token revocation", "password verification", "Control resource pools and cache"],
                                      "synthetic": ["pre-seeded account provisioning", "Gateway HTTP transport", "native event and message payloads", "model generation"],
                                      "not_executed": ["50 Agent environments / 150 containers", "real model inference or tools", "Gateway network connection-pool capacity", "production host capacity", "remote load generator"]},
                "host": {"system": platform.system(), "python": platform.python_version(), "logical_cpus": os.cpu_count()},
                "parameters": {"stages": args.stages, "stage_seconds": args.stage_seconds, "request_pause_ms": args.request_pause_ms,
                               "gateway_delay_ms": args.gateway_delay_ms, "event_interval_ms": args.event_interval_ms,
                               "request_cadence_ms": {"messages": args.request_pause_ms, "sessions": 2000, "me": 5000, "health": 5000,
                                                      "models": 30000, "files": 30000, "skills": 30000, "plugins": 30000}},
                "latency_thresholds_ms": {"p95": args.p95_ms, "p99": args.p99_ms},
                "latency_scope": "Client end-to-end HTTP response including the complete body, not only headers",
                "limits": app.state.limits, "total_seconds": round(time.monotonic() - started, 2), "stages": stage_reports,
                "peak": peak, "peak_synthetic_generations": fixture.peak_generating, "synthetic_gateway_requests": fixture.requests,
                "events_received": sum(record["events"] for record in subscribers),
                "foreign_events": sum(record["foreign_events"] for record in subscribers),
                "invalid_events": sum(record["invalid_events"] for record in subscribers), "final_streams": final_streams,
                "checks": outcomes,
            }
            report["control_fixture_passed"] = (
                peak["viewers"] == max(args.stages) * 2 and fixture.peak_generating == max(args.stages)
                and final_streams["viewers"] == 0 and report["foreign_events"] == 0 and report["invalid_events"] == 0
                and not outcomes.get("foreign_message") and outcomes["revocation"]["delete_status"] == 200
                and outcomes["revocation"]["new_request_status"] == 401 and 0 <= revocation_seconds <= 5
                and outcomes.get("cross_account_status") == 404
                and all(stage["streams"]["viewers"] == stage["target_sse"] and stage["early_stream_closures"] == 0 for stage in stage_reports)
                and all(metric["count"] == 0 or (set(metric["status_counts"]) == {"200"}
                        and metric["p95_ms"] <= args.p95_ms and metric["p99_ms"] <= args.p99_ms)
                        for stage in stage_reports for metric in stage["metrics"].values())
            )
            return report
    except (RuntimeError, asyncio.TimeoutError) as error:
        return {"profile": "L2-control-only-real-loopback-http-with-mocked-gateways", "control_fixture_passed": False,
                "failure": str(error) if isinstance(error, RuntimeError) else "Synthetic test timed out",
                "parameters": {"stages": args.stages, "stage_seconds": args.stage_seconds, "request_pause_ms": args.request_pause_ms,
                               "gateway_delay_ms": args.gateway_delay_ms, "event_interval_ms": args.event_interval_ms,
                               "request_cadence_ms": {"messages": args.request_pause_ms, "sessions": 2000, "me": 5000, "health": 5000,
                                                      "models": 30000, "files": 30000, "skills": 30000, "plugins": 30000}},
                "stages": stage_reports, "peak": peak, "limits": getattr(app.state, "limits", {}),
                "db_rejected": getattr(getattr(app.state, "db_work", None), "rejected", None),
                "streams": app.state.stream_registry.stats() if hasattr(app.state, "stream_registry") else {},
                "checks": outcomes, "peak_synthetic_generations": fixture.peak_generating,
                "evidence_boundary": "Real Control/socket/SQLite/auth; synthetic Gateway/LLM. No real account containers or production capacity acceptance."}
    finally:
        stop_monitor.set()
        if monitoring is not None:
            await asyncio.gather(monitoring, return_exceptions=True)
        for task in [*load_tasks, *subscriber_tasks]:
            task.cancel()
        await asyncio.gather(*load_tasks, *subscriber_tasks, return_exceptions=True)
        server.should_exit = True
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(serving, timeout=8)
        listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stages", default="10,20,35,50")
    parser.add_argument("--stage-seconds", type=float, default=10)
    parser.add_argument("--request-pause-ms", type=float, default=500)
    parser.add_argument("--gateway-delay-ms", type=float, default=10)
    parser.add_argument("--event-interval-ms", type=float, default=250)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--p95-ms", type=float, default=500)
    parser.add_argument("--p99-ms", type=float, default=1500)
    parser.add_argument("--serve-only", action="store_true", help="Serve only the synthetic browser fixture and built console")
    parser.add_argument("--port", type=int, default=19490)
    parser.add_argument("--serve-seconds", type=float, default=900)
    parser.add_argument("--credentials-file", type=Path, help="New local private file for synthetic browser logins")
    args = parser.parse_args()
    try:
        args.stages = [int(value) for value in args.stages.split(",")]
    except ValueError:
        parser.error("stages must be comma-separated integers")
    if not args.stages or args.stages != sorted(set(args.stages)) or not 2 <= min(args.stages) <= max(args.stages) <= 50:
        parser.error("stages must be increasing unique account counts between 2 and 50")
    if not 1 <= args.stage_seconds <= 14400 or not 1 <= args.event_interval_ms <= 60000 or not 50 <= args.request_pause_ms <= 60000 or not 0 <= args.gateway_delay_ms <= 1000:
        parser.error("load parameters are outside the supported bounds")
    if not 1 <= args.p95_ms <= args.p99_ms <= 60000:
        parser.error("latency thresholds must be positive and p99 >= p95")
    if args.serve_only and (not args.credentials_file or args.credentials_file.exists()):
        parser.error("serve-only requires a new --credentials-file path")
    if not 1024 <= args.port <= 65535 or not 1 <= args.serve_seconds <= 14400:
        parser.error("invalid fixture port or lifetime")
    if args.output and args.output.exists():
        parser.error("output already exists; choose a new report name")
    with tempfile.TemporaryDirectory(prefix="peixian-control-load-") as temporary:
        report = asyncio.run(execute(args, Path(temporary)))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    else:
        print(rendered)
    return 0 if report["control_fixture_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
