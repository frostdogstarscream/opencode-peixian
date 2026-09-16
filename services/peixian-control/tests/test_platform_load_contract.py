import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).parents[1] / "benchmarks/platform_load.py"
spec = importlib.util.spec_from_file_location("platform_load_contract", path)
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


def manifest():
    return {"base_url": "http://synthetic", "deployment_id": "loadtest-r1",
            "users": [{"username": f"loadtest-{index}", "token": f"px_synthetic-{index}"} for index in range(50)]}


@pytest.mark.parametrize("invalid", ["normal-user", "duplicate-user", "duplicate-token", "too-few"])
def test_real_runner_refuses_non_synthetic_or_duplicate_identities(tmp_path, invalid):
    value = manifest()
    if invalid == "normal-user":
        value["users"][0]["username"] = "client-a"
    if invalid == "duplicate-user":
        value["users"][1]["username"] = value["users"][0]["username"]
    if invalid == "duplicate-token":
        value["users"][1]["token"] = value["users"][0]["token"]
    if invalid == "too-few":
        value["users"].pop()
    source = tmp_path / "synthetic.json"
    source.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load.load_manifest(source)


@pytest.mark.parametrize("tool_generation", [False, True])
def test_completed_workflows_or_old_tool_history_do_not_prove_concurrent_tools(monkeypatch, tool_generation):
    prior = {"info": {"id": "old-answer"}, "parts": [{"type": "tool", "tool": "调用已启用的插件", "state": {"status": "completed"}}]}
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def me(self): return {"username": "loadtest-0", "role": "user", "must_change_password": False, "runtime": {"status": "ready"}}
        async def create_session(self, *_): return {"id": "session"}
        async def models(self): return []
        async def sessions(self): return [{"id": "session", "status": "idle"}]
        async def messages(self, *_): return [prior]
        async def run_message(self, *args, **kwargs):
            await asyncio.sleep(.01)
            return [prior, {"info": {"id": "new-answer"}, "parts": []}]
    monkeypatch.setattr(load, "ConsoleClient", FakeClient)
    args = SimpleNamespace(plugin_id="synthetic", model_id="synthetic", tool_generation=tool_generation, task_timeout=1)
    result = asyncio.run(load.stage(manifest(), 1, "answers", .005, args))
    assert result["capacity_status"] == "not_verified"
    assert result["status"] == ("failed" if tool_generation else "not_verified")
    assert result["completed_plugin_tools"] == 0
