import copy,json,uuid
import pytest
from fastapi import HTTPException
from control import task_router,task_context,trusted_results as results,business_runs as runs
from control.agents.registry import require
from control.facts_runtime import FactsState
from control.developer_registry import registry
from control.trusted_narrative import review
from test_multi_agent import prepare,submit
from test_trusted_results import test_compiled_facts_roundtrip as compile_fixture
from test_task_context import complete_data,current
from test_control import P,create_user,login_user
from evaluation.conftest import OBSERVATIONS

def single(agent):return '看看资金' if agent=='gambling-assistant' else '看看车辆记录'
def module(agent):return 'funds' if agent=='gambling-assistant' else 'vehicle'
def denied(call):
    try:call();return False
    except (HTTPException,ValueError,KeyError):return True

def run_case(case,env,monkeypatch):
    agent=case['agent_id'];category=case['category']
    s=env[0] if env else None;uid=env[4]['uid'] if env else None
    if category=='routing':
        value=task_router.parse(case['text'],False,require(agent))
        _,resolved=prepare(env,agent,case['text']);spec=resolved.get('spec') or {}
        return {'query_mode_accuracy':spec.get('query_mode')==case['expected_mode'],'intent_accuracy':spec.get('intent')==case['expected_intent'],'method_exact_match':spec.get('methods',[])==case['expected_methods'],'candidate_mode_accuracy':value['query_mode_candidate']==case['expected_mode']}
    if category=='narrative':
        value=review(case['text'],[],{'status':'not_started'})
        return {'narrative_contract':value['status']==case['expected_status'],**({'covered_conflict_detection':value['status']=='conflicted'} if case['expected_status']=='conflicted' else {})}
    if category=='usage':
        name=module(agent);snap={'task_spec':{'query_mode':'new_query'},'facts_plan':{'modules':[name]},'facts_state':{'modules':{name:{'status':case['module_status']}}}}
        event={'event_key':'facts.'+name,'step_type':'plugin','started':1,'completed':None,'status':case['module_status'],'capability_id':'peixian-records-'+name}
        value=results.usage({'status':case['run_status'],'phase':'running'},snap,[event] if case['reserved'] else [])
        return {'data_usage_accuracy':value['status']==case['expected_status'],'unknown_not_zero':value['queried'] is (None if case['reserved'] else False)}
    if category=='claim':
        compile_fixture(env,agent,case['text']);row=s.one('SELECT * FROM business_runs ORDER BY created DESC LIMIT 1');snap=s.decrypt(row['request_ciphertext']);events=s.rows('SELECT * FROM run_events WHERE run_id=?',(row['id'],));change=case['change'];original=results.build(row,snap,events);name=snap['facts_plan']['modules'][0]
        if change=='target':snap['task_spec']['target_refs']=['DEMO-OTHER']
        if change=='agent':snap['task_spec']['agent_id']='forged-agent'
        if change=='snapshot':snap['facts_state']['modules'][name]['response']['snapshot_id']='DEMO-OTHER-SNAPSHOT'
        if change=='count':snap['facts_state']['table']['summary'][0]['count']+=41
        if change=='no_events':events=[]
        if change=='unknown':
            snap['facts_state']['modules'][name]={'status':'unknown'};snap['facts_state'].pop('table',None);snap['facts_state'].pop('checked',None)
        if change=='missing':snap['facts_state']['modules'].pop(name)
        if change=='narrative':snap['model_narrative']='此人已经实施盗窃，风险评分99。'
        value=results.build(row,snap,events);claims=value['claims'];ids={x['record_id'] for x in value['records']}|{f['source_document'] for f in snap['facts_plan']['scenario']['facts'] if f.get('source_document')}
        source_ok=all(set(c['source_ids'])<=ids for c in claims)
        raw={x['record_id']:x for x in value['records']};protected=True
        for c in claims:
            fields=c['protected_fields'];record=raw.get(fields.get('record_id'))
            if record:protected &= all(fields.get(k)==record.get(k) for k in ('member_ref','co_member_ref','occurred_at','amount_minor','direction') if k in fields)
        if change in ('target','agent','snapshot','no_events','unknown','missing'):protected &= not any(c['type']!='gap' for c in claims)
        if change=='count':protected &= not any(c['type']=='computed' for c in claims)
        relation=all(not (c['protected_fields'].get('kind')=='same_frame' and c['protected_fields'].get('observation')!='same_frame') for c in claims)
        out={'claim_source_coverage':source_ok,'protected_fields_integrity':bool(protected),'relationship_integrity':relation}
        if change=='unknown':out['unknown_not_zero']=not any(c['type']=='computed' for c in claims) and bool(value['missing'])
        if change=='narrative':out['covered_conflict_detection']=value['narrative']['status']=='conflicted'
        # Repeated rendering/read must not recompute old stored sources.
        stable=results.read(s,uid,'ses_multi',row['id']);out['result_stability']=results.digest(stable)==results.digest(original)
        return out
    if category=='security':
        request,task=prepare(env,agent,single(agent));_,row,snap=submit(env,request,task);name=module(agent)
        with s.tx() as db:FactsState(s).authorize(db,row,snap,name)
        change=case['change'];plan=snap['facts_plan']
        if change=='unplanned_module':name='vehicle' if agent=='gambling-assistant' else 'funds'
        if change=='tools':plan['allowed_tools']=['bash']
        if change=='registry_digest':plan['registry']['digest']='0'*64
        if change=='task_agent':snap['task_spec']['agent_id']='theft-assistant' if agent=='gambling-assistant' else 'gambling-assistant'
        if change=='task_domain':snap['task_spec']['domain']='other'
        if change=='task_methods':snap['task_spec']['methods']=['calls']
        if change=='task_scenario':snap['task_spec']['scenario_id']='DEMO-OTHER'
        if change=='task_target':snap['task_spec']['target_refs']=['DEMO-OTHER']
        if change=='task_version':snap['task_spec']['agent_version']='99.0.0'
        if change=='profile_hash':snap['task_spec']['agent_profile_sha256']='0'*64
        if change=='registry_version':plan['registry']['capabilities'][0]['plugin_version']='99.0.0'
        if change=='registry_rule':plan['registry']['rules'][0]['implementation']='other'
        if change=='target_filter':plan['task_target']['filter_fields']=['other']
        if change=='removed_registry':plan.pop('registry')
        if change=='response_snapshot':plan['records'][name]['snapshot_id']='DEMO-OTHER'
        with s.tx() as db:blocked=denied(lambda:FactsState(s).authorize(db,row,snap,name))
        return {'plan_escape_blocking':blocked,**({'agent_isolation':blocked} if change in ('task_agent','task_domain','profile_hash') else {})}
    op=case['operation']
    if op=='missing_history':
        request,task=prepare(env,agent,'继续');_,row,snap=submit(env,request,task)
        return {'history_zero_query':not snap.get('facts_plan') and not s.one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))}
    if op in ('disabled_capability','disabled_rule'):
        docs=registry.REGISTRY.documents();kind='capabilities' if op=='disabled_capability' else 'rules'
        for item in docs[kind]:item['state']='disabled'
        monkeypatch.setattr(registry,'REGISTRY',registry.Registry(**docs));request,task=prepare(env,agent,single(agent));_,row,snap=submit(env,request,task)
        return {'unpublished_zero_query':not snap.get('facts_plan') and not s.one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))}
    rid=complete_data(env,agent,single(agent));ctx=current(env,agent)
    if op in ('history','chain'):
        count=3 if op=='chain' else 1;safe=True
        for _ in range(count):
            request,task=prepare(env,agent,'继续');_,row,snap=submit(env,request,task)
            safe &= not snap.get('facts_plan') and snap['allowed_tools']==[] and snap['task_spec']['source_data_run_id']==rid
            runs.set_state(s,row['id'],'completed','completed')
        return {'history_zero_query':bool(safe)}
    if op=='reset':
        task_context.reset(s,uid,'ses_multi',require(agent));request,task=prepare(env,agent,'继续');_,row,snap=submit(env,request,task)
        return {'history_zero_query':not snap.get('facts_plan') and task['local']['code']=='source_evidence_unavailable'}
    if op=='cas':
        a=prepare(env,agent,'继续',context_version=ctx['version']);b=prepare(env,agent,'继续',context_version=ctx['version']);submit(env,*a)
        return {'context_cas':denied(lambda:submit(env,*b))}
    if op=='replay':
        pair=prepare(env,agent,'继续');first=submit(env,*pair)[0];second=submit(env,*pair)[0]
        return {'request_idempotency':first==second}
    if op in ('other_session','other_account'):
        if op=='other_account':
            create_user(env[2],'evaluation-other');client=login_user(env[1],'evaluation-other')
            try:status=client.get(P+'/sessions/ses_multi/runs/'+rid+'/result').status_code
            finally:client.__exit__(None,None,None)
        else:status=env[3].get(P+'/sessions/other/runs/'+rid+'/result').status_code
        return {'resource_isolation':status==404}
    if op in ('profile','generation'):
        row=s.one('SELECT * FROM business_runs WHERE id=?',(rid,));snap=s.decrypt(row['request_ciphertext'])
        if op=='profile':snap['agent_profile']['profile_sha256']='0'*64
        else:snap['session_task_context']['generation']=999
        with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),rid))
        return {'historical_scope':task_context.source(s,uid,'ses_multi',require(agent),ctx) is None}
    if op=='client_task':
        response=env[3].post(P+'/sessions/ses_multi/messages',json={**env[5],'text':'继续','agent_id':agent,'client_request_id':str(uuid.uuid4()),'task_spec':{'target_refs':['DEMO-OTHER']}})
        return {'client_forgery_blocking':response.status_code in (400,422)}
    text='查询这个账户资金' if op=='account_target' else ('查询林晓舟和某陌生人的资金' if agent=='gambling-assistant' else '查询DEMO-UNKNOWN的车辆')
    request,task=prepare(env,agent,text);_,row,snap=submit(env,request,task)
    return {'clarification_zero_query':not snap.get('facts_plan') and not s.one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))}

def test_evaluation_case(case,request,monkeypatch):
    env=request.getfixturevalue("enabled") if case["category"] not in ("narrative","usage") else None
    try:metrics=run_case(case,env,monkeypatch)
    except Exception:
        OBSERVATIONS[case['id']]={'split':case['split'],'category':case['category'],'metrics':{},'error':'evaluation_case_failed'}
        raise
    OBSERVATIONS[case['id']]={'split':case['split'],'category':case['category'],'metrics':metrics,'error':None}
    if case['category']!='routing':assert all(metrics.values()),metrics
