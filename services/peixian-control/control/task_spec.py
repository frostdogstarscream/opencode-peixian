"""Server-side PR-5 admission; no model classifier or client-authoritative TaskSpec."""
import os
import copy
import jsonschema
from . import task_router
from .backend_contract import error
from .scenario_context import current, explicit, skill_scenario, NAMES
from .official_methods import identify

SPEC_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': [
    'schema_version', 'router_version', 'domain', 'query_mode', 'intent', 'scenario_id',
    'target_refs', 'target_mode', 'methods', 'official_skill_ids', 'output_types',
    'direct_parent_run_id', 'source_data_run_id', 'missing_fields', 'context_generation'],
    'properties': {
        'schema_version': {'const': 'task-spec-v1'}, 'router_version': {'const': task_router.VERSION},
        'domain': {'enum': ['gambling', 'theft', None]},
        'query_mode': {'enum': ['new_query', 'explain_existing', 'clarify']},
        'intent': {'enum': list(task_router.METHODS) + ['integrated_analysis', 'explain_result', 'clarification']},
        'scenario_id': {'enum': list(NAMES) + [None]},
        'target_mode': {'enum': ['scenario_subject', 'record_filter', None]},
        'methods': {'type': 'array', 'uniqueItems': True, 'items': {'enum': ['night', 'companions', 'funds', 'relations', 'vehicles']}},
        **{k: {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string'}} for k in ('target_refs', 'official_skill_ids', 'output_types', 'missing_fields')},
        **{k: {'type': 'null'} for k in ('direct_parent_run_id', 'source_data_run_id')},
        'context_generation': {'type': ['string', 'null']},
    }}

SPEC_SCHEMA['properties']['target_refs']['maxItems']=1
SPEC_SCHEMA['properties']['official_skill_ids']['maxItems']=5
SPEC_SCHEMA['properties']['output_types']['items']={'enum':['summary','evidence']}
SPEC_SCHEMA['allOf']=[{'if':{'properties':{'query_mode':{'const':'new_query'}}},
    'then':{'properties':{'methods':{'minItems':1},'official_skill_ids':{'minItems':1},'target_refs':{'minItems':1},
                          'target_mode':{'enum':['scenario_subject','record_filter']},'scenario_id':{'enum':list(NAMES)}}},
    'else':{'properties':{'methods':{'maxItems':0},'official_skill_ids':{'maxItems':0},'target_mode':{'type':'null'}}}}]

CANDIDATE_SCHEMA={'type':'object','additionalProperties':False,'properties':{
    'schema_version':{'const':'task-candidate-v1'},'router_version':{'const':task_router.VERSION},
    **{k:{'type':'boolean'} for k in ('data_related','unsupported_scope','untrusted_directive')},
    'query_mode_candidate':{'enum':['new_query','explain_existing','clarify',None]},
    'intent_candidate':{'enum':list(task_router.METHODS)+['integrated_analysis','explain_result','clarification',None]},
    **{k:{'type':'array','items':{'type':'string'}} for k in ('target_mentions','history_terms','refresh_terms','no_refresh_terms','matched_patterns','conflicts')}}}
CANDIDATE_SCHEMA['required']=list(CANDIDATE_SCHEMA['properties'])

SPEC_V2_SCHEMA=copy.deepcopy(SPEC_SCHEMA)
SPEC_V2_SCHEMA['properties']['schema_version']={'const':'task-spec-v2'}
SPEC_V2_SCHEMA['properties']['router_version']={'const':task_router.MULTI_VERSION}
SPEC_V2_SCHEMA['properties']['intent']['enum'].append('vehicle_activity')
SPEC_V2_SCHEMA['properties'].update(agent_id={'type':'string'},agent_version={'type':'string'},agent_profile_sha256={'type':'string','pattern':'^[0-9a-f]{64}$'})
SPEC_V2_SCHEMA['required']+=['agent_id','agent_version','agent_profile_sha256']



SPEC_V3_SCHEMA=copy.deepcopy(SPEC_V2_SCHEMA)
SPEC_V3_SCHEMA['properties']['schema_version']={'const':'task-spec-v3'}
SPEC_V3_SCHEMA['properties']['context_generation']={'type':'integer','minimum':1}
for field in ('direct_parent_run_id','source_data_run_id'):
    SPEC_V3_SCHEMA['properties'][field]={'type':['string','null']}

def resolve(store,uid,sid,data,applied):
    from . import task_context
    if 'context_version' in data and not task_context.enabled(store,uid):error('task_context_not_enabled','当前账号尚未启用多轮上下文。',409)
    from . import clarifications
    routing,confirmed,selection=data,None,None
    if clarifications.enabled(store,uid):routing,confirmed,selection=clarifications.prepare(store,uid,sid,data)
    task=resolve_legacy(store,uid,sid,routing,applied,confirmed)
    if clarifications.enabled(store,uid):task=clarifications.decorate(task,routing,selection)
    if task_context.enabled(store,uid) and task.get('agent_profile'):
        from .agents.registry import require
        task=task_context.enrich(store,uid,sid,data,require(task['agent_profile']['id']),task)
        if task['spec']:jsonschema.validate(task['spec'],SPEC_V3_SCHEMA)
    return task


def candidate_schema(profile):
    result=copy.deepcopy(CANDIDATE_SCHEMA)
    if profile:
        result['properties']['router_version']={'const':task_router.MULTI_VERSION}
        result['properties']['intent_candidate']['enum']=list(profile.data['intents'])+['explain_result','clarification',None]
    return result



def enabled(uid):
    return uid in {x.strip() for x in os.getenv('PX_TASKSPEC_V1_UIDS', '').split(',') if x.strip()}


def resolve_legacy(store, uid, sid, data, applied, confirmed=None):
    from .agents import runtime as agents
    profile=agents.select(uid,data) if agents.enabled(uid) else None
    if profile:agents.session(store,uid,sid,profile)
    chosen = [x for x in applied.get('skills', []) if x['id'] in data['skill_ids']]
    if profile and any(identify(x['content']) and identify(x['content'])['id'] not in profile.data['official_method_ids'] for x in chosen):
        error('agent_method_not_allowed','所选技能不属于当前助手，请使用对应助手的新会话。',409)
    route_text=data['text']
    if profile and store.schema_version()>=8:
        for alias in ('那辆车','这辆车','该车','哪辆车'):route_text=route_text.replace(alias,'车辆')
    candidate = task_router.parse(route_text, bool(data['skill_ids']),profile)
    jsonschema.validate(candidate,candidate_schema(profile))
    inherited = current(store, uid, sid)
    # No models or old prose are inspected. The PR-5 context is just the existing
    # scene/reset boundary; richer multi-turn targets belong to PR-6/7.
    direct = explicit(data['text'])
    selected_scenes = {skill_scenario(x) for x in chosen} - {None}
    scenes = direct | selected_scenes
    if profile:
        if scenes-set(profile.data['scenario_ids']):error('agent_scenario_mismatch','所选场景不属于当前助手，请新建对应助手会话。',409)
        scenes.add(profile.data['default_scenario_id'])
    elif data.get('agent_id') == 'gambling-assistant':
        scenes.add('DEMO-CASE-GAMBLING')
    scene = next(iter(scenes), inherited['scenario_id']) if len(scenes) <= 1 else None
    context = {'scenario_id': scene, 'source': 'explicit' if direct else 'selected_skill' if selected_scenes else inherited['source'],
               'generation': inherited['generation'], 'effective_skill_ids': []}
    if not candidate['data_related']:
        # Still disable every tool in ordinary help/chat under this rollout.
        return {'agent_profile':profile.snapshot() if profile else None, 'candidate': candidate, 'spec': None, 'context': {**context, 'scenario_id': None}, 'target': None, 'local': None}
    mode, intent = candidate['query_mode_candidate'], candidate['intent_candidate']
    missing = candidate['conflicts'][:]
    if len(scenes) > 1:
        mode, intent, missing = 'clarify', 'clarification', ['scenario_id']
    if candidate['unsupported_scope'] or candidate['untrusted_directive']:
        missing.append('supported_scope')
    methods, resolved, target = [], [], None
    if mode == 'new_query':
        if not scene:
            mode, intent, missing = 'clarify', 'clarification', ['scenario_id']
        else:
            from .official_methods import BY_ID
            from .task_targets import resolve as resolve_targets
            from .task_methods import resolve as resolve_methods
            flow = 'gambling' if scene == 'DEMO-CASE-GAMBLING' else 'theft'
            wanted = ([profile.data['intents'][intent]['official_method']] if intent in profile.data['intents'] else []) if profile else ([flow] if intent == 'integrated_analysis' else task_router.METHODS.get(intent, []))
            # A selected identity may fill an otherwise missing intent; it never
            # decides query_mode. Live ownership/dependencies are checked below.
            if not wanted and chosen:
                identities=[identify(x['content']) for x in chosen]
                names={x['method'] for x in identities if x}
                if all(identities) and len(names)==1:
                    name=next(iter(names))
                    intent='integrated_analysis' if name in ('gambling','theft') else next((k for k,v in task_router.METHODS.items() if v==[name]),None)
                    if profile and name not in ('gambling','theft'):intent=next((k for k,v in profile.data['intents'].items() if v['methods']==[name]),None)
                    wanted=[name] if intent else []
            if not wanted:
                mode,intent,missing='clarify','clarification',['intent']
            else:
                methods=profile.data['intents'][intent]['methods'] if profile else list(dict.fromkeys(m for name in wanted for m in BY_ID['peixian.method.'+name]['methods']))
                target=resolve_targets(store,uid,sid,scene,data['text'],methods,profile,confirmed)
                if target['status']!='resolved':
                    mode,intent,missing='clarify','clarification',[target['reason']]
                else:
                    from .developer_registry.registry import REGISTRY
                    unavailable=REGISTRY.readiness(profile.id if profile else flow+'-assistant',methods)
                    if unavailable:
                        mode,intent,missing='clarify','clarification',[unavailable]
                        methods=[]
                    else:
                        resolved=resolve_methods(store,uid,applied,data['skill_ids'],wanted,profile)
                    allowed={m for _,identity in resolved for m in identity['methods']}
                    if not unavailable and (not set(methods)<=allowed or any(identity['method'] not in ('gambling','theft') and not set(methods)<=set(identity['methods']) for _,identity in resolved)):
                        mode,intent,missing='clarify','clarification',['method_conflict']
                    elif not set(methods)<=set(BY_ID['peixian.method.'+flow]['methods']):
                        error('official_method_outside_scenario','当前场景不支持所选方法。',409)
    if mode != 'new_query':
        methods, resolved = [], []
    context['effective_skill_ids'] = [sid for sid, _ in resolved]
    spec = {'schema_version': 'task-spec-v1', 'router_version': task_router.VERSION,
            'domain': 'gambling' if scene == 'DEMO-CASE-GAMBLING' else 'theft' if scene else None,
            'query_mode': mode, 'intent': intent or 'clarification', 'scenario_id': scene,
            'target_refs': target['target_refs'] if mode=='new_query' and target else [],
            'target_mode': target.get('target_mode') if mode == 'new_query' and target else None,
            'methods': methods, 'official_skill_ids': context['effective_skill_ids'],
            'output_types': ['summary', 'evidence'], 'direct_parent_run_id': None, 'source_data_run_id': None,
            'missing_fields': list(dict.fromkeys(missing)), 'context_generation': inherited['generation']}
    if profile:
        spec.update(schema_version='task-spec-v2',router_version=task_router.MULTI_VERSION,agent_id=profile.id,agent_version=profile.data['version'],agent_profile_sha256=profile.profile_sha256,domain=profile.data['domain'])
    jsonschema.validate(spec, SPEC_V2_SCHEMA if profile else SPEC_SCHEMA)
    local = None
    if mode == 'explain_existing':
        local = {'code': 'history_explanation_pending_pr6', 'message': '已识别为解释已有结果，本轮没有重新查询资料。完整历史结果解释将在下一阶段提供；请先查看原执行的已核验结果。'}
    elif mode == 'clarify':
        messages = {'target_missing':'当前可信结果中没有可供确认的对象，本轮未查询。','target_candidates_exceed_limit':'候选对象过多，请明确对象后再查询。','capability_not_ready':'所需资料能力尚未发布或已停用，本轮未查询资料。','rule_not_ready':'所需整理规则尚未发布或已停用，本轮未查询资料。','scenario_id': '请确认处理涉赌资料还是盗窃时空资料。', 'query_mode': '请确认使用已有结果说明，还是重新查询资料。',
                    'method_conflict': '所选专项技能与问题不一致，请调整技能或明确所需方法。',
                    'unsupported_target_scope': '当前方法不支持该对象或对象组合，尚未查询；不会用场景主对象替代。',
                    'target_confirmation_required': '本阶段无法唯一确认所指对象，请明确当前资料范围内的对象。',
                    'supported_scope': '当前仅支持已接入场景、对象和固定方法，尚未查询资料。'}
        local = {'code': missing[0] if missing else 'intent_required', 'message': messages.get(missing[0] if missing else '', ('请说明需要整理夜间、同行共现，还是车辆资料。' if profile and profile.data['domain']=='theft' else '请说明需要整理资金、夜间活动、同行共现，还是已有关系。'))}
    return {'agent_profile':profile.snapshot() if profile else None, 'candidate': candidate, 'spec': spec, 'context': context, 'target': target, 'local': local}


def bind(snapshot, payload, task):
    snapshot.update(task_candidate=copy.deepcopy(task['candidate']), task_spec=copy.deepcopy(task['spec']),
                    task_context_snapshot=copy.deepcopy(task['context']), task_router_version=task['candidate']['router_version'])
    if task['target']:
        snapshot['task_target'] = copy.deepcopy(task['target'])
    if not task['spec'] or task['spec']['query_mode'] != 'new_query':
        payload['tools'] = {'*': False, **{name: False for p in snapshot['plugins'] for name in p.get('tools', [])}}
        from .facts_plan import HELPERS
        payload['tools'].update({name: False for name in HELPERS})
        snapshot['allowed_capabilities'], snapshot['allowed_tools'] = [], []
    if task['local']:
        snapshot['task_response'] = task['local']
    from .task_context import freeze
    freeze(snapshot,payload,task)


def admission_selection(data, task, effective_skill_ids):
    """Admission-only selection; preserve the original request for audit/replay."""
    query = (task.get('spec') or {}).get('query_mode') == 'new_query'
    return {**data, 'skill_ids': list(effective_skill_ids) if query else [],
            'plugin_ids': list(data.get('plugin_ids', [])) if query else []}
