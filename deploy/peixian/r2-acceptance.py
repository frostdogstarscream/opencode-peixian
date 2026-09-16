"""Opt-in R2 acceptance against one isolated deployment and 3 or 4 synthetic users.

This tool never creates users, builds images, changes capacity or accesses another
deployment. The manifest contains credentials: keep it private and out of reports.
Only the deterministic fixture is permitted. Completion is never a 50-user claim.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack, suppress
import importlib.util
import json
import math
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


config = module("r2_acceptance_config", ROOT / "platform-config.py")
sdk = module("r2_acceptance_sdk", ROOT.parents[1] / "services/peixian-control/examples/console_client.py")
runtime = module("r2_acceptance_runtime", ROOT / "console-runtime.py")


class Failure(RuntimeError):
    """Only fixed, public codes are raised; no raw URLs, bodies or credentials."""


def require(condition, code):
    if not condition:
        raise Failure(code)


def local_url(value):
    parsed = urlsplit(value)
    return (parsed.scheme in ("http", "https") and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
            and parsed.path in ("", "/"))


def secret(path):
    value = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    require(len(value) >= 32 and not any(c in value for c in "\r\n\0"), "invalid_private_key")
    return value


def manifest(path):
    require(path.is_file() and path.stat().st_size <= 65536, "manifest_unavailable")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), "manifest_invalid")
    require(re.fullmatch(r"(?:loadtest|synthetic)-r2-[a-z0-9-]{1,40}", data.get("deployment_id", "")), "synthetic_deployment_required")
    cfg = config.load_config(Path(data["config_file"]))
    require(cfg.version == 3 and cfg.deployment_id == data["deployment_id"] and cfg.max_runtimes <= 4,
            "manifest_configuration_mismatch")
    require(data["base_url"].rstrip("/") == cfg.public_url.rstrip("/")
            and data["control_url"].rstrip("/") == cfg.control_url and local_url(data["control_url"])
            and local_url(data["fixture"]["url"]), "manifest_endpoint_mismatch")
    users = data.get("users")
    require(isinstance(users, list) and len(users) in (3, 4), "exactly_three_or_four_users_required")
    require({item.get("label") for item in users} == set("ABCD"[:len(users)]), "user_labels_invalid")
    for field in ("uid", "runtime_id", "username", "token"):
        require(len({item.get(field) for item in users}) == len(users), "duplicate_user_identity")
    for item in users:
        require(all(re.fullmatch(r"[a-f0-9]{32}", item.get(key, "")) for key in ("uid", "runtime_id")), "user_identity_invalid")
        require(isinstance(item.get("token"), str) and len(item["token"]) >= 32, "user_token_required")
    require(len(users) <= cfg.max_runtimes, "manifest_exceeds_capacity")
    return data, cfg


def docker(*args):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, check=True, timeout=30)
        return result.stdout
    except (subprocess.SubprocessError, OSError):
        raise Failure("isolated_docker_operation_failed") from None


def bound_inventory(data, cfg):
    control = json.loads(docker("inspect", cfg.control_container))[0]
    require((control.get("Config", {}).get("Labels") or {}).get("peixian.deployment") == cfg.deployment_id,
            "control_deployment_label_mismatch")
    labels = control["Config"]["Labels"]
    config.image_supports_orchestration(labels, "control", 3)
    ids = docker("ps", "-aq", "--filter", "label=peixian.deployment=" + cfg.deployment_id).split()
    records = json.loads(docker("inspect", *ids)) if ids else []
    allowed = {item["runtime_id"]: item["uid"] for item in data["users"]}
    runtimes = {}
    for record in records:
        labels = record.get("Config", {}).get("Labels") or {}
        rid = labels.get("peixian.runtime_id")
        if not rid:
            continue
        require(rid in allowed and labels.get("peixian.uid") == allowed[rid]
                and labels.get(runtime.MANAGED) == "true", "foreign_runtime_in_deployment")
        service = labels.get("com.docker.compose.service")
        require(service in ("agent", "gateway", "model-relay"), "unexpected_runtime_service")
        require(service not in runtimes.setdefault(rid, {}), "duplicate_runtime_service")
        runtimes[rid][service] = record["Id"]
    require(set(runtimes) == set(allowed)
            and all(set(items) == {"agent", "gateway", "model-relay"} for items in runtimes.values()),
            "three_bound_containers_per_user_required")
    return runtimes


def percentile(values, ratio):
    return sorted(values)[max(0, math.ceil(len(values) * ratio) - 1)] if values else None


class Harness:
    def __init__(self, data, cfg, args):
        self.data, self.cfg, self.args = data, cfg, args
        self.users = {item["label"]: item for item in data["users"]}
        self.clients, self.viewers, self.samples, self.events = {}, [], [], []
        self.running = {}
        self.started = time.monotonic()
        self.report = {"format_version": 1, "scenario": args.scenario, "synthetic": True,
                       "user_count": len(self.users), "sse_per_user": 2, "capacity_50_verified": False,
                       "status": "running", "checks": [], "limitations": [
                           "Results cover only the manifest-bound 3/4 users; never 50-user capacity.",
                           "No paid model calls; deterministic fixture only.",
                           "Stage crash/drop-response coverage requires separate fault-injection evidence.",
                           "CPU/memory/OOM/resource drift gates require the paired platform-sample report."]}

    def event(self, check, **fields):
        # Callers pass fixed codes, labels, counts and durations only.
        value = {"check": check, "elapsed_seconds": round(time.monotonic() - self.started, 3), **fields}
        self.events.append(value)
        print(json.dumps(value, ensure_ascii=False), flush=True)

    async def call(self, client, method, path, *, expected=(), **kwargs):
        start = time.monotonic()
        status = 200
        try:
            return await client.request(method, path, **kwargs)
        except sdk.ConsoleError as error:
            status = error.status or 0
            if status not in expected:
                raise Failure("console_result_unknown" if error.result_unknown else "console_request_failed") from None
            return {"expected_status": status}
        except httpx.HTTPError:
            status = 0
            raise Failure("console_transport_failed") from None
        finally:
            self.samples.append({"ms": (time.monotonic() - start) * 1000,
                                 "error": status == 0 or status >= 500, "expected": status in expected})

    async def worker(self, path):
        response = await self.control.get("/internal/worker/" + path)
        require(response.status_code == 200, "worker_observation_failed")
        return response.json()

    async def fixture(self, marker=None, **value):
        if marker:
            response = await self.model.post("/internal/fixture/modes/" + marker, json=value)
        else:
            response = await self.model.get("/internal/fixture/stats")
        require(response.status_code == 200 and response.json().get("fixture") is True, "deterministic_fixture_unavailable")
        return response.json()

    async def start(self, stack):
        self.inventory = await asyncio.to_thread(bound_inventory, self.data, self.cfg)
        self.admin = await stack.enter_async_context(sdk.ConsoleClient(self.data["base_url"], ca_file=self.args.ca_file))
        authority = await self.admin.login(self.data["admin"]["username"], self.data["admin"]["password"])
        require(authority.get("role") == "super_admin", "synthetic_super_admin_required")
        verify = ssl.create_default_context(cafile=self.args.ca_file) if self.args.ca_file else True
        self.control = await stack.enter_async_context(httpx.AsyncClient(base_url=self.data["control_url"],
            headers={"X-Worker-Key": secret(self.data["worker_key_file"]), "X-Peixian-Protocol": "2"},
            trust_env=False, timeout=5, verify=verify))
        self.model = await stack.enter_async_context(httpx.AsyncClient(base_url=self.data["fixture"]["url"],
            headers={"Authorization": "Bearer " + secret(self.data["fixture"]["key_file"])},
            trust_env=False, timeout=5, verify=verify))
        await self.fixture()
        users = (await self.call(self.admin, "GET", "/admin/users"))["items"]
        require({item["id"] for item in users if item["role"] == "user"} == {item["uid"] for item in self.users.values()},
                "unexpected_business_account")
        models = (await self.call(self.admin, "GET", "/admin/models"))["items"]
        model = next((item for item in models if item["id"] == self.data["model_id"]), {})
        require(model.get("model_id") == "synthetic-openai-compatible" and model.get("enabled"), "synthetic_model_required")
        for label, item in self.users.items():
            client = await stack.enter_async_context(sdk.ConsoleClient(self.data["base_url"], token=item["token"], ca_file=self.args.ca_file))
            self.clients[label] = client
            actual = (await self.call(client, "GET", "/me"))["user"]
            require(actual["id"] == item["uid"] and actual["username"] == item["username"], "account_binding_mismatch")
            require(actual.get("runtime", {}).get("id") == item["runtime_id"], "runtime_binding_mismatch")
            for _ in range(2):
                viewer = await stack.enter_async_context(sdk.ConsoleClient(self.data["base_url"], token=item["token"], ca_file=self.args.ca_file))
                ready = asyncio.Event()
                task = asyncio.create_task(self.listen(label, viewer, ready))
                self.viewers.append(task)
                await asyncio.wait_for(ready.wait(), 12)
                require(not task.done(), "sse_subscription_failed")
        self.event("preflight", passed=True)

    async def listen(self, label, client, ready):
        try:
            async for event in client.events():
                if event["event"] == "change":
                    ready.set()
        finally:
            ready.set()

    async def runtime(self, label):
        values = (await self.call(self.admin, "GET", "/admin/users"))["items"]
        value = next(item for item in values if item["id"] == self.users[label]["uid"])
        return value["runtime"]

    async def usable(self, label, timeout=150):
        async with asyncio.timeout(timeout):
            while True:
                state = await self.runtime(label)
                if (state["status"] == "ready" and state["revision"] == state["desired"]
                        and state.get("gate_policy") == "open" and not state.get("recovery_required")):
                    return state
                await asyncio.sleep(.25)

    async def job(self, jid):
        return (await self.worker("jobs/" + jid))["job"]

    async def finished(self, jid, timeout=150):
        async with asyncio.timeout(timeout):
            while True:
                current = await self.job(jid)
                if current["status"] in ("succeeded", "failed", "cancelled"):
                    require(current["status"] == "succeeded", "runtime_job_failed")
                    return current
                await asyncio.sleep(.2)

    async def action(self, label, action):
        result = await self.call(self.admin, "POST", "/admin/users/" + self.users[label]["uid"] + "/runtime/" + action)
        require(isinstance(result.get("job"), dict), "runtime_job_missing")
        return result["job"]["id"]

    async def configure(self, version):
        if not hasattr(self, "skill_id"):
            existing = (await self.call(self.clients["A"], "GET", "/skills"))["items"]
            item = next((value for value in existing if value["name"] == "Synthetic R2 acceptance"), None)
            if item:
                require(item["description"] == "Synthetic fixture only" and item["enabled"] is False,
                        "synthetic_skill_name_conflict")
                self.skill_id = item["id"]
        data = {"name": "Synthetic R2 acceptance", "description": "Synthetic fixture only",
                "content": "Synthetic revision " + str(version), "enabled": False}
        path = "/skills" + ("/" + self.skill_id if hasattr(self, "skill_id") else "")
        result = await self.call(self.clients["A"], "PATCH" if hasattr(self, "skill_id") else "POST", path, json=data)
        if "id" in result:
            self.skill_id = result["id"]
        require(isinstance(result.get("job"), dict), "configuration_job_missing")
        return result["job"]["id"]

    async def begin_answer(self, label, seconds=1):
        await self.usable(label)
        marker = "r2-" + uuid.uuid4().hex
        await self.fixture(marker, seconds=seconds)
        sid = (await self.call(self.clients[label], "POST", "/sessions", json={"title": "Synthetic R2 acceptance"}))["id"]
        before = (await self.fixture())["accepted"]
        result = await self.call(self.clients[label], "POST", "/sessions/" + sid + "/messages",
            json={"text": "Return deterministic synthetic text. " + marker,
                  "file_ids": [], "skill_ids": [], "model_id": self.data["model_id"]})
        require(result.get("accepted") is True, "message_not_accepted")
        self.running[label] = (sid, marker)
        async with asyncio.timeout(10):
            while (await self.fixture())["accepted"] <= before:
                await asyncio.sleep(.1)
        return sid, marker

    async def answer_done(self, label, sid, timeout=150):
        async with asyncio.timeout(timeout):
            while True:
                values = (await self.call(self.clients[label], "GET", "/sessions/" + sid + "/messages"))["items"]
                answers = [value["info"] for value in values if value["info"]["role"] == "assistant"]
                require(not any(value.get("error") for value in answers), "model_result_incomplete")
                if any(value.get("time", {}).get("completed") for value in answers):
                    self.running.pop(label, None)
                    return
                await asyncio.sleep(.25)

    async def smoke(self):
        for label in self.users:
            sid, _ = await self.begin_answer(label)
            await self.answer_done(label, sid)
            self.event("short_answer", label=label, passed=True)

    async def fairness(self, rounds):
        for number in range(1, rounds + 1):
            for label in ("B", "C"):
                await self.finished(await self.action(label, "pause"))
            sid, marker = await self.begin_answer("A", seconds=300)
            aid = await self.configure(number)
            bid = await self.action("B", "retry")  # Existing paused account: reprovision.
            cid = await self.action("C", "resume")
            started, claims, ended, defer = time.monotonic(), {}, {}, None
            async with asyncio.timeout(270):
                while len(ended) < 2 or defer is None:
                    for label, jid in (("A", aid), ("B", bid), ("C", cid)):
                        state = await self.job(jid)
                        now = time.monotonic()
                        if state.get("attempt", 0) > 0 or state["status"] == "running":
                            claims.setdefault(label, now)
                        if label == "A":
                            if state.get("defer_count", 0) > 0:
                                defer = defer or now
                            require(state["status"] != "succeeded", "busy_A_replaced_before_answer_complete")
                        elif state["status"] in ("succeeded", "failed", "cancelled"):
                            require(state["status"] == "succeeded", "fairness_job_failed")
                            ended.setdefault(label, now)
                    await asyncio.sleep(.1)
            # Polling bounds carry up to 0.3 seconds of observation uncertainty.
            require(set(claims) == {"A", "B", "C"}, "job_claim_evidence_missing")
            values = {"A_defer_seconds": max(0, defer - claims["A"]),
                      "B_claim_after_A_seconds": max(0, claims["B"] - claims["A"]),
                      "C_claim_after_B_seconds": max(0, claims["C"] - ended["B"]),
                      "B_execution_seconds": ended["B"] - claims["B"],
                      "C_execution_seconds": ended["C"] - claims["C"]}
            require(values["A_defer_seconds"] <= 5 and values["B_claim_after_A_seconds"] <= 10
                    and values["C_claim_after_B_seconds"] <= 5
                    and max(values["B_execution_seconds"], values["C_execution_seconds"]) <= 120,
                    "fairness_time_gate_failed")
            await self.fixture(marker, release=True)
            await self.answer_done("A", sid)
            await self.finished(aid)
            await self.usable("A")
            self.event("fairness_round", round=number, B_action="reprovision", passed=True,
                       **{key: round(value, 3) for key, value in values.items()})

    async def versions(self):
        sid, marker = await self.begin_answer("A", seconds=120)
        first = await self.configure(1)
        async with asyncio.timeout(15):
            while (await self.job(first)).get("defer_count", 0) == 0:
                await asyncio.sleep(.1)
        snapshot = await self.job(first)
        await self.configure(2)
        unchanged = await self.job(first)
        require(snapshot["revision"] == unchanged["revision"], "claimed_revision_mutated")
        desired = (await self.runtime("A"))["desired"]
        require(desired > snapshot["revision"], "second_revision_not_recorded")
        await self.fixture(marker, release=True)
        await self.answer_done("A", sid)
        state = await self.usable("A")
        require(state["revision"] == desired, "latest_revision_not_applied")
        self.event("claimed_snapshot_and_followup_revision", passed=True)

    async def security(self):
        # Token revocation is deliberately isolated from user/model revocation.
        client = self.clients["A"]
        created = await self.call(client, "POST", "/tokens", json={"name": "Synthetic R2 short-lived token"})
        async with sdk.ConsoleClient(self.data["base_url"], token=created["token"], ca_file=self.args.ca_file) as temporary:
            await self.call(temporary, "GET", "/me")
            await self.call(client, "DELETE", "/tokens/" + created["item"]["id"])
            started = time.monotonic()
            async with asyncio.timeout(5):
                while True:
                    result = await self.call(temporary, "GET", "/me", expected=(401,))
                    if result.get("expected_status") == 401:
                        break
                    await asyncio.sleep(.1)
            await self.call(client, "GET", "/admin/users", expected=(403,))
            self.event("token_revocation_and_role_denial", passed=True,
                       revocation_seconds=round(time.monotonic() - started, 3))
        self.report["limitations"].append("Token scenario does not certify model/account revoke cancellation or permit TTL.")

    async def restart(self):
        await self.usable("A")
        inventory = await asyncio.to_thread(bound_inventory, self.data, self.cfg)
        container = inventory[self.users["A"]["runtime_id"]]["gateway"]
        before = json.loads(await asyncio.to_thread(docker, "inspect", container))[0]["State"]["StartedAt"]
        await asyncio.to_thread(docker, "restart", "--time", "10", container)
        after = json.loads(await asyncio.to_thread(docker, "inspect", container))[0]["State"]["StartedAt"]
        require(before != after, "gateway_restart_not_observed")
        sid, _ = await self.begin_answer("A")
        await self.answer_done("A", sid)
        self.event("bound_gateway_restart_and_answer", passed=True)
        self.report["limitations"].append("Restart covers Gateway while idle; stage crash/Worker/Control recovery are separate checks.")

    async def soak(self):
        require(self.args.seconds >= 14400, "soak_requires_at_least_four_hours")
        deadline = time.monotonic() + self.args.seconds
        cycle = 0
        while time.monotonic() < deadline:
            for label in self.users:
                sid, _ = await self.begin_answer(label)
                await self.answer_done(label, sid)
            cycle += 1
            for _ in range(20):
                await asyncio.gather(*(self.call(client, "GET", "/sessions") for client in self.clients.values()))
                await asyncio.sleep(.25)
            require(not any(task.done() for task in self.viewers), "sse_viewer_stopped")
            if cycle % 5 == 0:
                self.event("soak_progress", cycles=cycle, remaining_seconds=max(0, round(deadline - time.monotonic())))

    async def close(self):
        # Release only confirmed accepted synthetic requests; never replay them.
        for sid, marker in tuple(self.running.values()):
            with suppress(Exception):
                await self.fixture(marker, release=True)
        for task in self.viewers:
            task.cancel()
        if self.viewers:
            await asyncio.gather(*self.viewers, return_exceptions=True)

    def finish(self):
        samples = [sample for sample in self.samples if not sample["expected"]]
        latency = [sample["ms"] for sample in samples]
        errors = sum(sample["error"] for sample in samples)
        p95, p99 = percentile(latency, .95), percentile(latency, .99)
        sufficient = len(samples) >= 1000
        self.report.update(elapsed_seconds=round(time.monotonic() - self.started, 3), checks=self.events,
            api={"samples": len(samples), "p95_ms": p95, "p99_ms": p99,
                 "unexpected_errors": errors, "error_rate": errors / len(samples) if samples else None,
                 "performance_sample_sufficient": sufficient,
                 "performance_gate_passed": sufficient and p95 <= 500 and p99 <= 1500 and errors / len(samples) <= .001})
        if self.args.scenario == "soak" and not self.report["api"]["performance_gate_passed"]:
            self.report.update(status="failed", failure_code="soak_api_gate_failed")
        return self.report


async def run(data, cfg, args):
    harness = Harness(data, cfg, args)
    async with AsyncExitStack() as stack:
        try:
            await harness.start(stack)
            if args.scenario == "fairness":
                await harness.fairness(args.rounds)
            else:
                await getattr(harness, args.scenario)()
            harness.report["status"] = "passed"
        except (Exception, asyncio.CancelledError) as error:
            harness.report.update(status="failed", failure_code=str(error) if isinstance(error, Failure)
                                  else "acceptance_" + type(error).__name__)
        finally:
            await harness.close()
    return harness.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--synthetic-deployment", action="store_true", required=True)
    parser.add_argument("--scenario", choices=("smoke", "fairness", "versions", "security", "restart", "soak"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=14400)
    parser.add_argument("--ca-file")
    args = parser.parse_args()
    require(1 <= args.rounds <= 30 and 1 <= args.seconds <= 28800, "invalid_acceptance_bounds")
    require(not args.output.exists() and not args.output.with_suffix(".md").exists(), "report_must_be_new")
    data, cfg = manifest(args.manifest)
    result = asyncio.run(run(data, cfg, args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    with args.output.with_suffix(".md").open("x", encoding="utf-8") as handle:
        handle.write("# R2 合成环境验收\n\n状态：" + result["status"] + "。场景：" + args.scenario
                     + "。账号：" + str(result["user_count"]) + "，每账号 2 SSE。\n\n")
        handle.write("此结果不证明 50 用户容量；资源、迁移与故障注入门槛需配套证据。\n\n```json\n"
                     + json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n")
    print(json.dumps({"status": result["status"], "scenario": args.scenario, "capacity_50_verified": False}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Failure, config.ConfigError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "failure_code": "acceptance_preflight_failed", "capacity_50_verified": False}))
        raise SystemExit(2)
