#!/usr/bin/env python3
"""Run a new two-user Agent acceptance using temporary copies of the template.

The original acceptance record remains immutable.  This variation verifies the
intended template-assisted workflow and removes its two temporary personal
Skills on exit, without touching pre-existing Skills.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

from agent_acceptance_evidence import current_turn
from fixture_profiles import load_profile


CASES = (
    ("alignment-a", "funds", "资金碰撞"),
    ("alignment-a", "calls", "话单碰撞"),
    ("alignment-a", "portrait", "人像事件"),
    ("alignment-a", "composite", "综合碰撞"),
    ("alignment-b", "night", "夜间活动"),
    ("alignment-b", "vehicle", "驾乘车辆"),
    ("alignment-b", "lookup", "关联互查"),
)
STATE_KEY = "synthetic_records_tool_acceptance_with_template"
TEMPLATE_NAME = "沛县七项合成资料研判（合成演示）"


def acceptance_class(deployment_root: Path):
    source = deployment_root / "source" / "deploy" / "peixian" / "alignment-live-acceptance.py"
    if not source.is_file():
        source = Path("/root/PeiXianDB/frontend-alignment/deploy/peixian/alignment-live-acceptance.py")
    spec = importlib.util.spec_from_file_location("peixian_acceptance", source)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load the deployment acceptance helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Acceptance


def wait_for_answer(api, client, session_id: str, *, seconds: int = 180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        messages = api.request(client, "GET", f"/sessions/{session_id}/messages")["items"]
        answers = current_turn(messages)
        if any(answer.get("info", {}).get("error") for answer in answers):
            raise RuntimeError("model_request_failed")
        if answers:
            answer = answers[-1]
            timing = answer.get("info", {}).get("time", {})
            if timing.get("completed") and answer.get("info", {}).get("finish") in ("stop", "end_turn"):
                return answers
        time.sleep(2)
    raise RuntimeError("model_result_unknown")


def safe_evidence(answers, expected_module: str, fixture_profile="legacy"):
    # OpenCode emits tools in earlier assistant messages, before its final answer.
    if any(answer.get("info", {}).get("error") or any(part.get("type") == "tool" and part.get("state", {}).get("status") != "completed" for part in answer.get("parts", [])) for answer in answers):
        raise RuntimeError("agent_tool_chain_not_completed")
    completed = [part for answer in answers for part in answer.get("parts", [])
                 if part.get("type") == "tool" and part.get("state", {}).get("status") == "completed"]
    matching = [part.get("details", {}).get("outputs", {}) for part in completed
                if part.get("details", {}).get("outputs", {}).get("module") == expected_module]
    unrelated = [part for part in completed if part.get("tool") != "使用技能"
                 and part.get("details", {}).get("outputs", {}).get("module") != expected_module]
    text = "".join(part.get("text", "") for part in answers[-1].get("parts", []) if part.get("type") == "text") if answers else ""
    if len(matching) != 1 or unrelated or sum(part.get("tool") == "使用技能" for part in completed) > 1:
        raise RuntimeError("agent_response_did_not_meet_tool_chain")
    selected = matching[0]
    expected = load_profile(fixture_profile)[0][expected_module]
    if selected.get("synthetic") is not True or selected.get("data_status") != "complete" or selected.get("snapshot_id") != expected["snapshot_id"]:
        raise RuntimeError("agent_tool_source_mismatch")
    if not all(marker in text for marker in ("合成", expected["snapshot_id"], "complete", "DEMO-")):
        raise RuntimeError("agent_answer_source_markers_missing")
    return {key: selected.get(key) for key in ("module", "data_status", "snapshot_id", "synthetic", "returned_count")}



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-root", type=Path, required=True)
    parser.add_argument("--fixture-profile", choices=["legacy", "enhanced"], required=True)
    arguments = parser.parse_args()
    api = acceptance_class(arguments.deployment_root.resolve())(arguments.deployment_root.resolve())
    clients, temporary_skills = {}, {}
    try:
        if STATE_KEY in api.state:
            raise RuntimeError("template-assisted acceptance already started; do not retry automatically")
        model_id = api.state.get("model")
        if not isinstance(model_id, str) or not model_id:
            raise RuntimeError("an approved test model is required")
        api.state[STATE_KEY] = {"sessions": {}, "cases": {}, "temporary_skills": {}}
        api.save()
        for account, _, _ in CASES:
            if account not in clients:
                clients[account] = api.login(account)
        for account, client in clients.items():
            templates = api.request(client, "GET", "/templates")["items"]
            matches = [item for item in templates if item.get("name") == TEMPLATE_NAME]
            if len(matches) != 1:
                raise RuntimeError("the expected global Skill template is not available exactly once")
            copied = api.request(client, "POST", f"/templates/{matches[0]['id']}/copy", json={})
            temporary_skills[account] = copied["id"]
            api.state[STATE_KEY]["temporary_skills"][account] = "created"
            api.save()
            api.ready(client, seconds=300)
            if api.request(client, "POST", f"/skills/{copied['id']}/test", json={}).get("ok") is not True:
                raise RuntimeError("temporary Skill did not load")
            api.state[STATE_KEY]["temporary_skills"][account] = "loaded"
            api.save()
            session = api.request(client, "POST", "/sessions", json={"title": "七项合成资料插件验收"})
            api.state[STATE_KEY]["sessions"][account] = session["id"]
            api.save()
        for account, module, label in CASES:
            case = f"{account}:{module}"
            api.state[STATE_KEY]["cases"][case] = {"status": "submitting", "module": module}
            api.save()
            prompt = (
                f"请查询{label}模块的合成演示资料。请使用已授权工具完成本次查询，且不要调用不相关资料工具。"
                "回答必须明确这是合成演示资料，报告 snapshot_id 与 data_status，并引用至少一个 record_id。"
                "不得生成风险等级、综合评分、真实身份、真实案件事实或自动扩线结论。"
            )
            session_id = api.request(clients[account], "POST", "/sessions", json={"title": "七项单请求验收-" + module})["id"]
            api.state[STATE_KEY]["cases"][case]["session_id"] = session_id
            api.save()
            api.request(clients[account], "POST", f"/sessions/{session_id}/messages", json={
                "text": prompt, "model_id": model_id, "skill_ids": [temporary_skills[account]],
            })
            try:
                result = safe_evidence(wait_for_answer(api, clients[account], session_id), module, arguments.fixture_profile)
                api.state[STATE_KEY]["cases"][case] = {"status": "passed", **result}
                api.save()
                print(json.dumps({"case": case, "status": "passed", **result}, ensure_ascii=False, sort_keys=True), flush=True)
            except Exception as exc:
                api.state[STATE_KEY]["cases"][case] = {"status": "failed", "module": module, "reason": str(exc)}
                api.save()
                raise
    finally:
        for account, skill_id in temporary_skills.items():
            try:
                api.request(clients[account], "DELETE", f"/skills/{skill_id}")
                api.ready(clients[account], seconds=300)
                api.state.get(STATE_KEY, {}).get("temporary_skills", {})[account] = "deleted"
            except Exception:
                api.state.get(STATE_KEY, {}).get("temporary_skills", {})[account] = "cleanup_failed"
            api.save()
        api.clients.close()


if __name__ == "__main__":
    main()
