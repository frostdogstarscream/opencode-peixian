"""Local-only acceptance guardrails and a real ephemeral fixture HTTP server."""
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import uuid

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


acceptance = load("test_acceptance", ROOT / "r2-acceptance.py")
fixture = load("test_r2_fixture", ROOT / "examples/openai-fixture.py")


def manifest(tmp_path, size=3):
    cfg = json.loads((ROOT / "server/platform.orchestration.example.json").read_text(encoding="utf-8"))
    config = tmp_path / "platform.json"
    config.write_text(json.dumps(cfg), encoding="utf-8")
    data = {"deployment_id": cfg["deployment_id"], "config_file": str(config),
            "base_url": cfg["public_url"], "control_url": "http://127.0.0.1:" + str(cfg["control_port"]),
            "fixture": {"url": "http://127.0.0.1:19999"},
            "users": [{"label": label, "uid": str(index + 1) * 32, "runtime_id": str(index + 5) * 32,
                       "username": "synthetic-" + label, "token": (label + "-synthetic-") * 5}
                      for index, label in enumerate("ABCD"[:size])]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def test_manifest_requires_exact_isolated_capacity_and_endpoints(tmp_path):
    path, data = manifest(tmp_path)
    parsed, cfg = acceptance.manifest(path)
    assert len(parsed["users"]) == 3 and cfg.capacity_policy["cpu_mode"] == "shared"
    for update in ({"control_url": "http://192.0.2.1:14096"}, {"deployment_id": "original-production"},
                   {"users": data["users"][:2]}):
        path.write_text(json.dumps({**data, **update}), encoding="utf-8")
        with pytest.raises(acceptance.Failure):
            acceptance.manifest(path)


def test_fixture_mode_bounds_and_real_http_release(tmp_path, monkeypatch):
    key = tmp_path / "fixture.key"
    key.write_text("synthetic-key-" * 4)
    monkeypatch.setenv("FIXTURE_KEY_FILE", str(key))
    for body in ({"seconds": 601}, {"seconds": True}, {"seconds": float("nan")}, {"release": "true"}):
        with pytest.raises(ValueError):
            fixture.configure("r2-" + uuid.uuid4().hex, body)
    server = fixture.ThreadingHTTPServer(("127.0.0.1", 0), fixture.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url="http://127.0.0.1:" + str(server.server_port), trust_env=False,
                          headers={"Authorization": "Bearer " + key.read_text()}, timeout=5) as client:
            marker = "r2-" + uuid.uuid4().hex
            assert client.post("/internal/fixture/modes/" + marker, json={"seconds": 30}).status_code == 200
            with client.stream("POST", "/v1/chat/completions", json={"model": fixture.MODEL,
                    "messages": [{"role": "user", "content": marker}], "stream": True}) as response:
                lines = response.iter_lines()
                assert next(lines).startswith("data: ")
                assert client.get("/internal/fixture/stats").json()["active"] == 1
                assert client.post("/internal/fixture/modes/" + marker, json={"release": True}).status_code == 200
                assert "data: [DONE]" in list(lines)
            stats = client.get("/internal/fixture/stats").json()
            assert stats["completed"] >= 1 and stats["active"] == 0
            marker = "r2-" + uuid.uuid4().hex
            assert client.post("/internal/fixture/modes/" + marker, json={"tool": True}).status_code == 200
            payload = {"model": fixture.MODEL, "messages": [{"role": "user", "content": marker}],
                       "stream": True, "tools": [{"type": "function", "function": {
                           "name": "platform_sample_records", "parameters": {"type": "object"}}}]}
            response = client.post("/v1/chat/completions", json=payload)
            chunks = [json.loads(line[6:]) for line in response.text.splitlines()
                      if line.startswith("data: {")]
            assert chunks[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "platform_sample_records"
            assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
            records = client.get("/records?limit=2").json()
            assert len(records["items"]) == 2
            payload["messages"].append({"role": "tool", "tool_call_id": "call_synthetic_records",
                                         "content": json.dumps(records)})
            response = client.post("/v1/chat/completions", json=payload)
            assert '"finish_reason": "stop"' in response.text
            assert '"tool_calls"' not in response.text
            stats = client.get("/internal/fixture/stats").json()
            assert stats["tool_calls"] >= 1 and stats["record_queries"] >= 1
            assert client.post("/v1/chat/completions", json={"model": fixture.MODEL,
                               "messages": ["invalid"]}).status_code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_summary_never_calls_insufficient_samples_or_three_users_fifty(tmp_path):
    path, data = manifest(tmp_path)
    data, cfg = acceptance.manifest(path)
    args = SimpleNamespace(scenario="soak")
    harness = acceptance.Harness(data, cfg, args)
    harness.samples = [{"ms": 1, "error": False, "expected": False}] * 20
    report = harness.finish()
    assert report["capacity_50_verified"] is False
    assert report["status"] == "failed" and not report["api"]["performance_sample_sufficient"]
    encoded = json.dumps(report)
    assert not any(item["token"] in encoded or item["uid"] in encoded for item in data["users"])


def test_bound_inventory_rejects_foreign_runtime_before_restart(tmp_path, monkeypatch):
    path, data = manifest(tmp_path)
    data, cfg = acceptance.manifest(path)
    control = {"Config": {"Labels": {"peixian.deployment": cfg.deployment_id,
        "org.peixian.runtime.protocol": "2", "org.peixian.worker.protocol": "2", "org.peixian.control.schema.max": "4"}}}
    def docker(*args):
        if args == ("inspect", cfg.control_container):
            return json.dumps([control])
        if args[0] == "ps":
            return "synthetic-container"
        return json.dumps([{"Config": {"Labels": {"peixian.runtime_id": "f" * 32}}}])
    monkeypatch.setattr(acceptance, "docker", docker)
    with pytest.raises(acceptance.Failure, match="foreign_runtime"):
        acceptance.bound_inventory(data, cfg)
