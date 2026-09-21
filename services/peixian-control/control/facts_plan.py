"""Server-owned fixed method plans; client plugin_ids remain preferences."""
import copy
import hashlib
from .facts_runtime import VERSION, METHODS, MODULES, capability, tool, reject
from .scenario_versions import DATA151

HELPERS = ("peixian_get_scenario_context", "peixian_prepare_scenario_facts", "peixian_check_scenario_summary")

def build(applied, context, data):
    plugins = applied.get("plugins", [])
    new = [p for p in plugins if p["id"] in {capability(m) for m in MODULES}]
    if not new or not context or not context.get("scenario_id"): return None
    if any(p["id"] == "peixian-synthetic-records" for p in plugins): reject("facts_ambiguous_plugin_chain")
    scene = copy.deepcopy(DATA151["scenarios"].get(context["scenario_id"]))
    if scene is None: reject("facts_unknown_scenario")
    scenario_methods = {
        "DEMO-CASE-GAMBLING": {"night", "companions", "funds", "relations"},
        "DEMO-CASE-THEFT": {"night", "companions", "vehicles"},
    }[scene["scenario_id"]]
    permitted = {module for method in scenario_methods for module in METHODS[method]}
    from .facts_skill_registry import METHODS_BY_HASH
    selected = [s for s in applied.get("skills", []) if s["id"] in context["effective_skill_ids"]]
    from .official_methods import identify
    if any(identify(s['content']) and identify(s['content'])['state']!='published' for s in selected):reject('facts_method_not_published')
    identities = [hashlib.sha256(s["content"].encode()).hexdigest() for s in selected]
    if (not identities or len(selected) != len(set(context["effective_skill_ids"]))
            or any(digest not in METHODS_BY_HASH for digest in identities)):
        reject("facts_method_identity_unavailable")
    methods = list(dict.fromkeys(method for digest in identities for method in METHODS_BY_HASH[digest]))
    if not set(methods) <= scenario_methods:
        reject("facts_method_outside_scenario")
    modules = list(dict.fromkeys(m for method in methods for m in METHODS[method]))
    if not modules or not set(modules) <= permitted: reject("facts_method_outside_scenario")
    for module in modules:
        matches = [p for p in plugins if tool(module) in p.get("manifest", {}).get("tools", [])]
        if len(matches) != 1 or matches[0]["id"] != capability(module) or matches[0].get("version") != "1.0.0" or matches[0].get("manifest", {}).get("tools") != [tool(module)]: reject("facts_dependency_unavailable")
    scene["required_modules"] = modules
    return {"plan_version": "fixed-method-plan-v1", "coordinator_version": VERSION,
            "facts_rule_version": "deterministic-facts-v1", "methods": methods, "modules": modules,
            "allowed_capabilities": [capability(m) for m in modules], "allowed_tools": [tool(m) for m in modules],
            "scenario": scene, "records": {m: copy.deepcopy(DATA151["records"][m]) for m in modules},
            "steps": [{"step_id":"prepare-"+m,"capability_id":capability(m),"tool_id":tool(m)} for m in modules]}

def bind_payload(payload, plan, applied):
    allowed = set(plan["allowed_tools"]) | set(HELPERS)
    payload["tools"] = {**payload.get("tools", {}), **{t: t in allowed for p in applied.get("plugins", []) for t in p.get("manifest", {}).get("tools", [])},
        **{name: False for name in ("bash","pty","read","write","edit","apply_patch","glob","grep","skill","task","webfetch","websearch")}}
    payload["system"] = payload.get("system", "") + "\n本轮平台固定方法：" + "、".join(plan["methods"]) + "。只使用当前计划的资料能力；事实整理使用已冻结方法，摘要核对不重新取数。未知或失败不得重试，不将缺失当作零。"
