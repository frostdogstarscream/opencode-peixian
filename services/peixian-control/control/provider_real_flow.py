"""Encrypted preview tickets for explicit v2 queries; never a network client."""
import copy
import time

from .backend_contract import error
from .scenario_context import current
from . import provider_contracts
from shared import theft_provider_v2 as adapter


def preview(store,uid,sid,body,applied,revision):
    from .theft_provider_flow import signature
    if set(body)-{'kind','query','contract_version','person_identity','analysis_task_id','context_version','step_request_id','source_refs','analysis_direction','direct_parent_run_id'}:
        error('provider_query_invalid','查询字段无效。',422)
    kind=body.get('kind');query=copy.deepcopy(body.get('query'))
    if not isinstance(query,dict):error('provider_query_invalid','查询条件必须为对象。',422)
    identities={}
    metadata=None
    if 'analysis_task_id' in body:
        from . import analysis_tasks
        metadata=analysis_tasks.freeze_step(store,uid,sid,body['analysis_task_id'],body.get('context_version'),request_key=body.get('step_request_id'),source_refs=body.get('source_refs',[]),direction=body.get('analysis_direction','single_query'),parent=body.get('direct_parent_run_id'))
    elif set(body)&{'context_version','step_request_id','source_refs','analysis_direction','direct_parent_run_id'}:
        error('analysis_task_required','来源与步骤参数必须绑定业务任务。',422)
    if metadata and metadata['source_refs']:
        if 'person_identity' in body:error('source_value_override','选定来源后不能替换人员。',422)
        query,identities,fields=analysis_tasks.derive(store,uid,sid,metadata,kind,query)
        metadata['fields_used']=fields
    elif kind in adapter.PERSON:
        try:
            identity=adapter.person_id(body.get('person_identity'))
            ref=adapter.person_ref(identity,store.worker_key.encode(),uid+'/'+sid)
        except adapter.ContractError:error('single_identity_required','请提供一个明确的人员身份号码。',422)
        if 'person_ref' in query:error('provider_query_invalid','此入口的人员引用由服务端生成。',422)
        query['person_ref']=ref;identities[ref]=identity
    elif 'person_identity' in body:error('provider_query_invalid','此查询不接受人员条件。',422)
    frozen=provider_contracts.freeze(store,uid,kind,query,identities,applied)
    ticket={'uid':uid,'sid':sid,'revision':revision,'generation':current(store,uid,sid)['generation'],'expires':int(time.time())+600,'frozen':frozen}
    if metadata:ticket['analysis_task']=metadata
    plan={'version':adapter.VERSION,'token':store.encrypt(ticket)}
    return {'plan':plan,'confirmation':signature(store,uid,sid,plan),'summary':adapter.CATALOG[kind][0]+'；'+adapter.LIMITATIONS[kind],'data_environment':'acceptance_real','contract_version':adapter.VERSION}


def resolve(store,uid,sid,data,applied,plan):
    from .agents.runtime import select,session
    if set(plan)!={'version','token'}:error('provider_confirmation_invalid','查询确认无效。',409)
    try:ticket=store.decrypt(plan['token'])
    except Exception:error('provider_confirmation_invalid','查询确认无法读取。',409)
    runtime=store.one('SELECT revision FROM runtimes WHERE uid=?',(uid,))
    context=current(store,uid,sid)
    if (ticket.get('uid')!=uid or ticket.get('sid')!=sid or ticket.get('expires',0)<int(time.time()) or not runtime or ticket.get('revision')!=runtime['revision'] or ticket.get('generation')!=context['generation']):
        error('provider_confirmation_expired','查询确认已过期或配置已变化。',409)
    frozen=ticket['frozen'];provider_contracts.validate(store,uid,frozen,applied)
    metadata=ticket.get('analysis_task')
    if metadata:
        from .analysis_tasks import validate_context
        validate_context(store,uid,sid,metadata)
        if metadata['step_request_id']!=data['client_request_id']:error('step_request_mismatch','步骤请求标识不一致。',409)
    profile=select(uid,data);session(store,uid,sid,profile)
    context.update(scenario_id=None,effective_skill_ids=[])
    kind=frozen['kind']
    targets=[frozen['query']['person_ref']] if kind in adapter.PERSON else ['selected-coordinate']
    spec={'schema_version':'task-spec-v4','router_version':adapter.VERSION,'domain':'theft','query_mode':'new_query','intent':'provider_'+kind,'scenario_id':None,'target_refs':targets,'target_mode':'provider_query','methods':[kind],'official_skill_ids':[],'output_types':['summary','evidence'],'direct_parent_run_id':None,'source_data_run_id':None,'context_generation':context['generation'],'agent_id':profile.id,'agent_version':profile.data['version'],'agent_profile_sha256':profile.profile_sha256}
    if metadata:spec.update(analysis_task_id=metadata['analysis_task_id'],direct_parent_run_id=metadata['direct_parent_run_id'],source_data_run_id=metadata['source_refs'][0]['run_id'] if len(metadata['source_refs'])==1 else None)
    task={'agent_profile':profile.snapshot(),'candidate':{'router_version':adapter.VERSION},'spec':spec,'context':context,'target':None,'local':None,'provider_plan':frozen}
    if metadata:
        task['analysis_task']=metadata
        from .analysis_tasks import owned
        state=store.decrypt(owned(store,uid,sid,metadata['analysis_task_id'])['payload_ciphertext'])
        call=next((x for x in state['planning_calls'] if x['request_key']==data['client_request_id']),None)
        if call:
            choice=call.get('decision',{})
            method=next((m for m in call['skills'] if m['method_id']==choice.get('skill_id')),None)
            if call['state']!='completed' or choice.get('action')!='query' or not method:error('planner_skill_unavailable','规划方法未核对。',409)
            actual=next((x for x in applied.get('skills',[]) if x['id']==method['skill_id']),None)
            current_skill=store.one('SELECT content,version FROM skills WHERE id=? AND uid=? AND enabled=1',(method['skill_id'],uid))
            import hashlib
            if not actual or not current_skill or actual.get('version')!=method['version'] or current_skill['version']!=method['version'] or actual['content']!=current_skill['content'] or hashlib.sha256(actual['content'].encode()).hexdigest()!=method['sha256']:
                error('planner_skill_unavailable','官方方法已变更或停用，请重新规划。',409)
            context['effective_skill_ids']=[method['skill_id']]
            spec['official_skill_ids']=[method['method_id']]
            metadata['planning_method']={k:method[k] for k in ('method_id','skill_id','version','method_version','sha256')}
            metadata['planning_call_id']=call['id']
            if call.get('continuation_of'):
                previous=next(x for x in state['planning_calls'] if x['id']==call['continuation_of'])
                spec['direct_parent_run_id']=previous['receipt']['run_id']
                metadata['direct_parent_run_id']=previous['receipt']['run_id']
    return task
