"""Isolated OpenAI protocol fixture deployment and B-account live round-trip.

This never targets the original platform or its users. 'prepare' starts only a
synthetic fixture; 'run' temporarily switches isolated platform-b to that fixture,
checks one explicitly synthetic conversation, then restores prior model grants.
"""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parent
TEST = ROOT / ".runtime/platform-v1-test"
PRIVATE = TEST / "compatibility-private.json"
REPORT = ROOT / "output/platform-compatibility-acceptance.json"
NAME = "agent-v1-openai-fixture"
NETWORK = "agent-v1-openai-fixture-network"
LABEL = "agent-v1-openai-fixture"
IMAGE = "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"


def helper():
    spec = importlib.util.spec_from_file_location("isolated_platform_acceptance", ROOT / "platform-acceptance.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, encoding="utf-8", timeout=120)
    if check and result.returncode:
        raise RuntimeError("fixture_docker_operation_failed")
    return result.stdout.strip() if result.returncode == 0 else None


def safe_container():
    value = docker("inspect", NAME, check=False)
    if value is None:
        return None
    result = json.loads(value)[0]
    if result["Config"]["Labels"].get("peixian.deployment") != LABEL:
        raise RuntimeError("fixture_container_name_conflict")
    return result


def prepare():
    if not (TEST / "acceptance-private.json").is_file():
        raise RuntimeError("isolated_test_not_prepared")
    existing = safe_container()
    if existing:
        if not existing["State"]["Running"]:
            docker("start", NAME)
        return
    with socket.socket() as port:
        port.bind(("127.0.0.1", 18095))
    keyfile = TEST / "openai-fixture.key"
    if not keyfile.exists():
        keyfile.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    network = docker("network", "inspect", NETWORK, check=False)
    if network:
        if json.loads(network)[0]["Labels"].get("peixian.deployment") != LABEL:
            raise RuntimeError("fixture_network_name_conflict")
    else:
        ids = docker("network", "ls", "-q").split()
        occupied = [ipaddress.ip_network(item["Subnet"]) for value in json.loads(docker("network", "inspect", *ids))
                    for item in (value["IPAM"].get("Config") or []) if item.get("Subnet")]
        subnet = next((ipaddress.ip_network(f"10.253.{n}.0/28") for n in range(230, 250)
                       if not any(ipaddress.ip_network(f"10.253.{n}.0/28").overlaps(item) for item in occupied if item.version == 4)), None)
        if subnet is None:
            raise RuntimeError("fixture_network_subnet_unavailable")
        docker("network", "create", "--driver", "bridge", "--subnet", str(subnet), "--label", "peixian.deployment=" + LABEL, NETWORK)
    docker("image", "inspect", IMAGE)
    docker("run", "-d", "--name", NAME, "--network", NETWORK, "--label", "peixian.deployment=" + LABEL,
           "--publish", "127.0.0.1:18095:8080", "--user", "10001:10001", "--read-only", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges:true", "--cpus", "0.25", "--memory", "128m", "--pids-limit", "64",
           "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m", "--mount", "type=bind,source=" + str(ROOT / "examples/openai-fixture.py") + ",target=/app/fixture.py,readonly",
           "--mount", "type=bind,source=" + str(keyfile) + ",target=/run/secrets/fixture-key,readonly",
           "--env", "FIXTURE_KEY_FILE=/run/secrets/fixture-key", "--entrypoint", "python3", IMAGE, "/app/fixture.py")
    with httpx.Client(trust_env=False, timeout=5) as client:
        for _ in range(30):
            try:
                if client.get("http://127.0.0.1:18095/health").json().get("fixture") is True:
                    print("synthetic_openai_fixture_ready", flush=True)
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
    raise RuntimeError("synthetic_fixture_not_ready")


def run():
    h = helper()
    state = h.load()
    private = json.loads(PRIVATE.read_text(encoding="utf-8")) if PRIVATE.exists() else {}
    report = {"scope": "isolated_openai_compatible_fixture_not_real_vllm", "started_at": datetime.now(timezone.utc).isoformat(),
              "checks": [], "real_vllm_tested": False, "status": "running"}
    switched = False
    def save():
        report["passed"] = sum(v["passed"] for v in report["checks"])
        report["failed"] = len(report["checks"]) - report["passed"]
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def need(name, value):
        report["checks"].append({"name": name, "passed": bool(value)})
        save()
        if not value:
            raise RuntimeError(name)
        print("pass:" + name, flush=True)
    with closing(h.admin()) as admin:
        users = h.checked(admin.get("/admin/users"))["items"]
        b = next(v for v in users if v["id"] == state["platform-b"]["id"] and v["username"] == "platform-b")
        a = next(v for v in users if v["id"] == state["platform-a"]["id"] and v["username"] == "platform-a")
        original = b["model_ids"]
        if private.get("restore_pending"):
            original = private["original_models"]
        private["original_models"] = original
        before = hashlib.sha256(json.dumps(a["model_ids"], sort_keys=True).encode()).hexdigest()
        try:
            need("fixture_container_scope_confirmed", safe_container()["State"]["Running"] is True)
            if "model" not in private:
                private["model"] = h.checked(admin.post("/admin/models", json={"name": "OpenAI 协议测试桩（非真实模型）",
                    "description": "仅合成兼容接口验收；不是实际 vLLM", "base_url": "http://host.docker.internal:18095/v1",
                    "model_id": "synthetic-openai-compatible", "api_key": (TEST / "openai-fixture.key").read_text().strip(), "enabled": True, "is_default": False}))["id"]
            else:
                h.checked(admin.patch("/admin/models/" + private["model"], json={"enabled": True}))
            PRIVATE.write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding="utf-8")
            need("openai_models_endpoint_and_id_confirmed", h.checked(admin.post("/admin/models/" + private["model"] + "/test", json={}))['ok'])
            private["restore_pending"] = True
            PRIVATE.write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding="utf-8")
            h.checked(admin.patch("/admin/users/" + b["id"], json={"model_ids": [private["model"]]}))
            switched = True
            h.ready(admin, b["id"])
            with closing(h.login("platform-b", state["platform-b"]["password"])) as user:
                need("b_authorized_only_fixture_during_probe", [v["id"] for v in h.checked(user.get("/models"))["items"]] == [private["model"]])
                sid = h.checked(user.post("/sessions", json={"title": "OpenAI 兼容接口合成验收"}))["id"]
                accepted = user.post("/sessions/" + sid + "/messages", json={"text": "请返回合成协议测试标记。此次请求不是业务分析。", "model_id": private["model"]})
                need("explicit_fixture_message_accepted", accepted.status_code == 202 and accepted.json().get("accepted") is True)
                end = time.monotonic() + 90
                while time.monotonic() < end:
                    messages = h.checked(user.get("/sessions/" + sid + "/messages"))["items"]
                    text = "\n".join(part.get("text", "") for message in messages if message.get("info", {}).get("role") == "assistant" or message.get("role") == "assistant" for part in message.get("parts", []) if part.get("type") == "text")
                    if "OpenAI 兼容接口测试桩" in text:
                        break
                    time.sleep(1)
                need("opencode_stream_roundtrip_explicit_synthetic_marker", "OpenAI 兼容接口测试桩" in text and "不代表真实" in text)
                need("synthetic_message_persisted", any(message.get("parts") for message in messages))
                private["session"] = sid
            report["status"] = "passed"
        except Exception as exc:
            report["status"] = "failed"
            report["error"] = str(exc).split(":", 1)[0] if isinstance(exc, RuntimeError) else type(exc).__name__
        finally:
            try:
                if switched or private.get("restore_pending"):
                    h.checked(admin.patch("/admin/users/" + b["id"], json={"model_ids": original}))
                    h.ready(admin, b["id"])
                    private["restore_pending"] = False
                if private.get("model"):
                    h.checked(admin.patch("/admin/models/" + private["model"], json={"enabled": False}))
                users = h.checked(admin.get("/admin/users"))["items"]
                latest_b = next(v for v in users if v["id"] == b["id"])
                latest_a = next(v for v in users if v["id"] == a["id"])
                need("b_original_model_grants_restored", sorted(latest_b["model_ids"]) == sorted(original))
                need("a_model_grants_unchanged", hashlib.sha256(json.dumps(latest_a["model_ids"], sort_keys=True).encode()).hexdigest() == before)
            except Exception:
                report["status"] = "failed"
                report["cleanup_error"] = "fixture_model_restoration_requires_attention"
            PRIVATE.write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding="utf-8")
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            save()
    print(json.dumps({k: report[k] for k in ("status", "passed", "failed")}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "stop"))
    action = parser.parse_args().action
    try:
        if action == "prepare":
            prepare()
        elif action == "stop":
            if safe_container():
                docker("stop", NAME)
        else:
            raise SystemExit(run())
    except Exception as exc:
        print("compatibility_operation_failed_" + type(exc).__name__, flush=True)
        raise SystemExit(1)
