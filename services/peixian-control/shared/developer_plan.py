"""Pure Gateway validation of the Control-owned frozen release contract."""
import hashlib
import json
import re

METHODS={'night':['night'],'companions':['portrait'],'funds':['funds'],'relations':['lookup','composite'],'vehicles':['vehicle']}

def validate(plan):
    from .task_scope import validate_target
    validate_target(plan)
    frozen=plan.get('registry')
    if frozen is None:return # Existing immutable pre-registry runs.
    if not isinstance(frozen,dict) or set(frozen)!={'capability_registry_version','rule_registry_version','method_dependency_version','agent_id','methods','capabilities','rules','digest'}:raise ValueError('invalid_registry_snapshot')
    value={k:v for k,v in frozen.items() if k!='digest'}
    digest=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if digest!=frozen['digest'] or frozen['methods']!=plan['methods']:raise ValueError('registry_digest_mismatch')
    if (frozen['capability_registry_version'],frozen['rule_registry_version'],frozen['method_dependency_version'])!=('capability-registry-v1','rule-registry-v1','method-dependency-v1'):raise ValueError('registry_version_unknown')
    modules=list(dict.fromkeys(m for method in plan['methods'] for m in METHODS[method]))
    if modules!=plan['modules'] or [c['id'] for c in frozen['capabilities']]!=['records.'+m for m in modules]:raise ValueError('registry_modules_mismatch')
    if [c['plugin_id'] for c in frozen['capabilities']]!=plan['allowed_capabilities'] or [t for c in frozen['capabilities'] for t in c['tool_ids']]!=plan['allowed_tools']:raise ValueError('registry_tools_mismatch')
    bindings=[]
    for rule,method in zip(frozen['rules'],plan['methods'],strict=True):
        if rule['state']!='published' or rule['version']!='1.0.0' or rule['implementation']!=method+'_summary_v1' or rule['supported_methods']!=[method] or frozen['agent_id'] not in rule['supported_agents']:raise ValueError('invalid_rule_binding')
        bindings.extend({'module':m,'rule_id':rule['id'],'version':rule['version'],'implementation':rule['implementation']} for m in METHODS[method])
    if plan['scenario'].get('rule_bindings')!=bindings:raise ValueError('rule_binding_mismatch')
    for c,m in zip(frozen['capabilities'],modules,strict=True):
        if c['state']!='published' or frozen['agent_id'] not in c['supported_agents'] or c['plugin_id']!='peixian-records-'+m or c['tool_ids']!=['peixian_get_'+m+'_records'] or c['output_schema']!=m+'-records-v1':raise ValueError('invalid_capability_binding')
        if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',c['plugin_version']):raise ValueError('invalid_plugin_version')
