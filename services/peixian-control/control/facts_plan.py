"""Server-owned fixed method plans; client plugin_ids remain preferences."""
import copy
import hashlib
from .facts_runtime import VERSION, METHODS, MODULES, capability, tool, reject
from .scenario_versions import DATA151

HELPERS = ("peixian_get_scenario_context", "peixian_prepare_scenario_facts", "peixian_check_scenario_summary")

def build(applied, context, data, task=None):
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
    if task:
        from .task_spec import SPEC_SCHEMA, SPEC_V2_SCHEMA, SPEC_V3_SCHEMA
        import jsonschema
        v2=task['spec'].get('schema_version') in ('task-spec-v2','task-spec-v3')
        jsonschema.validate(task['spec'],SPEC_V3_SCHEMA if task['spec'].get('schema_version')=='task-spec-v3' else SPEC_V2_SCHEMA if v2 else SPEC_SCHEMA)
        approved=task['spec']
        from .task_router import METHODS as INTENT_METHODS
        expected=INTENT_METHODS.get(approved['intent'])
        if approved['intent']=='integrated_analysis':expected=['night','companions','funds','relations'] if scene['scenario_id']=='DEMO-CASE-GAMBLING' else ['night','companions','vehicles']
        if v2:
            from .agents.registry import require
            profile=require(approved['agent_id'])
            if task.get('agent_profile')!=profile.snapshot() or approved['agent_version']!=profile.data['version'] or approved['agent_profile_sha256']!=profile.profile_sha256:reject('agent_profile_changed')
            if approved['domain']!=profile.data['domain'] or scene['scenario_id'] not in profile.data['scenario_ids']:reject('agent_scenario_mismatch')
            if any(identify(s['content'])['id'] not in profile.data['official_method_ids'] for s in selected):reject('agent_method_not_allowed')
            expected=profile.data['intents'].get(approved['intent'],{}).get('methods')
            if not task.get('target') or task['target'].get('agent_target_profile')!=profile.data['target_contract_profile']:reject('agent_task_mismatch')
        if approved['methods']!=expected:reject('task_intent_mismatch')
        if approved['query_mode']!='new_query' or approved['scenario_id']!=scene['scenario_id'] or approved['official_skill_ids']!=context['effective_skill_ids']:reject('task_plan_mismatch')
        if not approved['methods'] or not set(approved['methods']) <= set(methods):reject('task_method_expansion')
        methods=approved['methods'][:]
        target=task['target']
        from .task_targets import CONTRACTS, VERSION as TARGET_VERSION
        if (not target or target.get('status')!='resolved' or target.get('contract_version')!=TARGET_VERSION
            or target.get('target_refs')!=approved['target_refs'] or target.get('target_mode')!=approved['target_mode']
            or len(approved['target_refs'])!=1 or any(approved['target_mode'] not in CONTRACTS[m]['supported_target_modes'] for m in methods)):
            reject('task_target_mismatch')
        if approved['target_mode']=='scenario_subject' and approved['target_refs']!=[scene['subject_ref']]:reject('task_target_mismatch')
        if target.get('filter_fields')!=(['member_ref'] if approved['target_mode']=='record_filter' else []):reject('task_target_mismatch')
        if approved['target_mode']=='record_filter':
            scene['subject_ref']=approved['target_refs'][0]
            scene['facts']=[]
    if not set(methods) <= scenario_methods:
        reject("facts_method_outside_scenario")
    modules = list(dict.fromkeys(m for method in methods for m in METHODS[method]))
    if not modules or not set(modules) <= permitted: reject("facts_method_outside_scenario")
    from .developer_registry.registry import REGISTRY
    agent=task['agent_profile']['id'] if task and task.get('agent_profile') else ('gambling-assistant' if scene['scenario_id']=='DEMO-CASE-GAMBLING' else 'theft-assistant')
    try: registry=REGISTRY.freeze(agent,methods,plugins)
    except ValueError as exc: reject(str(exc))
    from .developer_registry.registry import rule_bindings
    scene["rule_bindings"]=rule_bindings(registry)
    scene["required_modules"] = modules
    return {**({"agent_profile":copy.deepcopy(task["agent_profile"]),"agent_task":copy.deepcopy(task["spec"])} if task and task.get("agent_profile") else {}),"registry":registry,"plan_version": "fixed-method-plan-v1", "coordinator_version": VERSION,
            "task_target": copy.deepcopy(task["target"]) if task else None,
            "facts_rule_version": "deterministic-facts-v1", "methods": methods, "modules": modules,
            "allowed_capabilities": [capability(m) for m in modules], "allowed_tools": [tool(m) for m in modules],
            "scenario": scene, "records": {m: copy.deepcopy(DATA151["records"][m]) for m in modules},
            "steps": [{"step_id":"prepare-"+m,"capability_id":capability(m),"tool_id":tool(m)} for m in modules]}

def bind_payload(payload, plan, applied):
    allowed = set(plan["allowed_tools"]) | set(HELPERS)
    payload["tools"] = {**payload.get("tools", {}), **{t: t in allowed for p in applied.get("plugins", []) for t in p.get("manifest", {}).get("tools", [])},
        **{name: False for name in ("bash","pty","read","write","edit","apply_patch","glob","grep","skill","task","webfetch","websearch")}}
    if plan.get('task_target'):
        payload['system']=payload.get('system','')+'\n本轮目标：'+ '、'.join(plan['task_target']['target_refs'])+'；仅筛选当前固定快照，不能声称全库或最新资料查询。'
    payload["system"] = payload.get("system", "") + "\n本轮平台固定方法：" + "、".join(plan["methods"]) + "。只使用当前计划的资料能力；事实整理使用已冻结方法，摘要核对不重新取数。未知或失败不得重试，不将缺失当作零。"
