"""Encrypted preview tickets for explicit v2 queries; never a network client."""
import copy
import time

from .backend_contract import error
from .scenario_context import current
from . import provider_contracts
from shared import theft_provider_v2 as adapter


def preview(store,uid,sid,body,applied,revision):
    from .theft_provider_flow import signature
    if set(body)-{'kind','query','contract_version','person_identity'}:
        error('provider_query_invalid','查询字段无效。',422)
    kind=body.get('kind');query=copy.deepcopy(body.get('query'))
    if not isinstance(query,dict):error('provider_query_invalid','查询条件必须为对象。',422)
    identities={}
    if kind in adapter.PERSON:
        try:
            identity=adapter.person_id(body.get('person_identity'))
            ref=adapter.person_ref(identity,store.worker_key.encode(),uid+'/'+sid)
        except adapter.ContractError:error('single_identity_required','请提供一个明确的人员身份号码。',422)
        if 'person_ref' in query:error('provider_query_invalid','此入口的人员引用由服务端生成。',422)
        query['person_ref']=ref;identities[ref]=identity
    elif 'person_identity' in body:error('provider_query_invalid','此查询不接受人员条件。',422)
    frozen=provider_contracts.freeze(store,uid,kind,query,identities,applied)
    ticket={'uid':uid,'sid':sid,'revision':revision,'generation':current(store,uid,sid)['generation'],'expires':int(time.time())+600,'frozen':frozen}
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
    profile=select(uid,data);session(store,uid,sid,profile)
    context.update(scenario_id=None,effective_skill_ids=[])
    kind=frozen['kind']
    targets=[frozen['query']['person_ref']] if kind in adapter.PERSON else ['selected-coordinate']
    spec={'schema_version':'task-spec-v4','router_version':adapter.VERSION,'domain':'theft','query_mode':'new_query','intent':'provider_'+kind,'scenario_id':None,'target_refs':targets,'target_mode':'provider_query','methods':[kind],'official_skill_ids':[],'output_types':['summary','evidence'],'direct_parent_run_id':None,'source_data_run_id':None,'context_generation':context['generation'],'agent_id':profile.id,'agent_version':profile.data['version'],'agent_profile_sha256':profile.profile_sha256}
    return {'agent_profile':profile.snapshot(),'candidate':{'router_version':adapter.VERSION},'spec':spec,'context':context,'target':None,'local':None,'provider_plan':frozen}
