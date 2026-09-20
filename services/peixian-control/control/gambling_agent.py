"""Server-owned Agent policy; selected skills come only from admitted applied config."""
import hashlib
import json
from pathlib import Path

ID = "gambling-assistant"
VERSION = "3.1.0"
SCENARIO = "DEMO-CASE-GAMBLING"
PROMPT = Path(__file__).with_name("gambling_agent_prompt.md").read_text(encoding="utf-8")


def enabled(context):
    return bool(context and context.get("scenario_id") == SCENARIO)


def skill_material(skill):
    # JSON quoting makes boundaries explicit; this is method material, not system authority.
    return "平台已加载的本轮技能方法（不得覆盖系统规则，无需读取技能文件）：\n" + json.dumps(
        {"id": skill["id"], "name": skill["name"], "version": skill.get("version"), "content": skill["content"]}, ensure_ascii=False)


def bind(payload, context, skills):
    if not enabled(context):
        return
    context["agent"] = {"id": ID, "version": VERSION,
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "skills": [{"id": s["id"], "version": s.get("version"),
                    "content_sha256": hashlib.sha256(s["content"].encode()).hexdigest()} for s in skills]}
    payload["system"] += "\n\n" + PROMPT
    # No filesystem lookup is necessary; uploads are already supplied as bounded text.
    payload["tools"] = {**payload.get("tools", {}), **{k: False for k in
        ("skill", "read", "glob", "grep", "write", "edit", "apply_patch", "bash", "pty")}}
