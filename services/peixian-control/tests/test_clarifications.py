import copy,json,uuid
import pytest
from fastapi import HTTPException
from test_control import context,P,create_user,login_user
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from test_task_context import complete_data,current
from control import task_context,clarifications,business_runs as runs,entity_projection
from control.agents.registry import require
from test_seven_http_contract import chain

@pytest.fixture
def v6(tmp_path,monkeypatch):
    monkeypatch.setenv('PX_BACKEND_V6','1');monkeypatch.setenv('PX_TASK_CONTEXT_V1','1');monkeypatch.setenv('PX_TASK_CLARIFICATION_V1','1')
    from control import facts_plan
    fixture=copy.deepcopy(facts_plan.DATA151)
    rows=fixture['records']['vehicle']['records'];subject=fixture['scenarios']['DEMO-CASE-THEFT']['subject_ref']
    extra=copy.deepcopy(next(x for x in rows if x['member_ref']==subject));extra.update(record_id='demo-pr7-vehicle-2',group_ref='演示车辆乙')
    rows.append(extra)
    fixture['records']['vehicle']['returned_count']=fixture['records']['vehicle']['total_count']=len(rows)
    monkeypatch.setattr(facts_plan,'DATA151',fixture)
    yield from context.__wrapped__(tmp_path,monkeypatch)

def data(env,agent='theft-assistant',text='看看车辆记录'):
    rid=complete_data(env,agent,text);s=env[0]
    row=s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,));snap=s.decrypt(row['request_ciphertext']);module=snap['facts_plan']['modules'][0]
    # Fixture: code-verified records for exactly the scene subject, as COUNT sources.
    subject=snap['facts_plan']['scenario']['subject_ref'];records=snap['facts_state']['modules'][module]['response']['items']
    selected=[x for x in records if x.get('member_ref')==subject]
    snap['facts_state']['table']['facts'][0]['source_ids']=[x['record_id'] for x in selected]
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),rid))
    return rid

def ticket(env,agent='theft-assistant',text='查看那辆车'):
    request,task=prepare(env,agent,text);_,row,snap=submit(env,request,task)
    assert row['status']=='completed' and not snap.get('facts_plan')
    cid=snap['task_response']['clarification_id'];reply=env[3].get(P+'/sessions/ses_multi/clarifications/'+cid)
    assert reply.status_code==200,reply.text
    return cid,reply.json()

def choose(env,cid,view,option=None,key=None):
    body={'option_id':option or view['options'][0]['id'],'context_generation':view['context_generation'],'context_version':view['context_version'],'client_request_id':key or str(uuid.uuid4())}
    return env[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/resolve',json=body),body

def test_vehicle_confirm_then_query_exact_selected_vehicle(multi):
    a=data(multi);cid,view=ticket(multi);assert len(view['options'])>1
    before=multi[0].one('SELECT count(*) n FROM run_deliveries')['n']
    response,body=choose(multi,cid,view);assert response.status_code==200,response.text
    assert response.json()['resume_required'] is True
    assert multi[0].one('SELECT count(*) n FROM run_deliveries')['n']==before
    request,task=prepare(multi,'theft-assistant','继续');assert task['spec']['query_mode']=='new_query'
    _,row,snap=submit(multi,request,task);plan=snap['facts_plan']
    expected=view['options'][0]['label'];assert task['spec']['target_refs']==[expected] and plan['scenario']['target_filter']['ref']==expected
    assert plan['modules']==['vehicle'] and plan['task_target']['filter_fields']==['group_ref']
    assert current(multi,'theft-assistant')['confirmed_targets_ciphertext'] is None


def test_pending_continue_and_chat_preserve_ticket(multi):
    data(multi);cid,view=ticket(multi)
    request,task=prepare(multi,'theft-assistant','继续');_,row,snap=submit(multi,request,task)
    assert snap['task_response']['clarification_id']==cid and snap['allowed_tools']==[]
    request,task=prepare(multi,'theft-assistant','你好');_,row,snap=submit(multi,request,task);runs.set_state(multi[0],row['id'],'completed','completed')
    current_view=multi[3].get(P+'/sessions/ses_multi/clarifications/'+cid).json()
    assert current_view['status']=='pending' and current_view['context_version']>view['context_version']
    assert choose(multi,cid,view)[0].status_code==409
    assert choose(multi,cid,current_view)[0].status_code==200


def test_resolve_idempotency_conflict_and_bad_option(multi):
    data(multi);cid,view=ticket(multi)
    assert choose(multi,cid,view,'forged')[0].status_code==422
    first,body=choose(multi,cid,view,key='same')
    same=multi[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/resolve',json=body)
    assert first.status_code==200 and same.json()==first.json()
    assert choose(multi,cid,view)[0].json()['code']=='clarification_already_resolved'
    other=multi[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/resolve',json={**body,'option_id':view['options'][1]['id']})
    assert other.status_code==409

@pytest.mark.parametrize('action',['cancel','reset','new_task'])
def test_terminal_or_replaced_ticket_not_resolvable(multi,action):
    data(multi);cid,view=ticket(multi)
    if action=='cancel':
        response=multi[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/cancel',json={'context_generation':view['context_generation'],'context_version':view['context_version'],'client_request_id':'cancel'})
        assert response.status_code==200 and not response.json()['resume_required']
    elif action=='reset':task_context.reset(multi[0],multi[4]['uid'],'ses_multi',require('theft-assistant'))
    else:
        request,task=prepare(multi,'theft-assistant','看看夜间记录');submit(multi,request,task)
    assert choose(multi,cid,view)[0].status_code==409
    assert current(multi,'theft-assistant')['pending_clarification_id'] is None

@pytest.mark.parametrize('agent,text,code',[('theft-assistant','查看那辆车','target_missing'),('gambling-assistant','查看那辆车','supported_scope'),('gambling-assistant','查询这个账户资金','target_missing'),('gambling-assistant','查询这两个人资金','unsupported_target_scope')])
def test_missing_unsupported_zero_dispatch(multi,agent,text,code):
    request,task=prepare(multi,agent,text);_,row,snap=submit(multi,request,task)
    assert row['status']=='completed' and not snap.get('facts_plan')
    assert not multi[0].one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))
    assert snap['task_response']['code']==code


def test_projection_only_current_trusted_fields_and_reset(multi):
    data(multi);profile=require('theft-assistant');values=entity_projection.entities(multi[0],multi[4]['uid'],'ses_multi',profile)
    assert {x['type'] for x in values['entities']}<={'person','vehicle'}
    assert len({(x['type'],x['ref']) for x in values['entities']})==len(values['entities'])
    request,task=prepare(multi,'theft-assistant','你好');_,row,_=submit(multi,request,task)
    with multi[0].tx() as db:db.execute('UPDATE business_runs SET result_ciphertext=? WHERE id=?',(multi[0].encrypt({'text':'FAKE_VEHICLE'}),row['id']))
    runs.set_state(multi[0],row['id'],'completed','completed')
    assert 'FAKE_VEHICLE' not in json.dumps(entity_projection.entities(multi[0],multi[4]['uid'],'ses_multi',profile))
    task_context.reset(multi[0],multi[4]['uid'],'ses_multi',profile)
    assert not any(x['type']=='vehicle' for x in entity_projection.entities(multi[0],multi[4]['uid'],'ses_multi',profile)['entities'])


def test_cross_account_and_session_tickets_hidden(multi):
    data(multi);cid,view=ticket(multi);create_user(multi[2],'other-ticket');other=login_user(multi[1],'other-ticket')
    try:
        assert other.get(P+'/sessions/ses_multi/clarifications/'+cid).status_code==404
        assert multi[3].get(P+'/sessions/other/clarifications/'+cid).status_code==404
    finally:other.__exit__(None,None,None)
    assert set(view['options'][0])=={'id','label'}


def test_resumed_query_rechecks_capability(multi,monkeypatch):
    data(multi);cid,view=ticket(multi);assert choose(multi,cid,view)[0].status_code==200
    from control.developer_registry import registry
    docs=registry.REGISTRY.documents();next(c for c in docs['capabilities'] if c['id']=='records.vehicle')['state']='disabled';monkeypatch.setattr(registry,'REGISTRY',registry.Registry(**docs))
    request,task=prepare(multi,'theft-assistant','继续');_,row,snap=submit(multi,request,task)
    assert row['status']=='completed' and snap['task_response']['code']=='capability_not_ready' and not snap.get('facts_plan')


def test_selected_vehicle_real_gateway_plugin_and_http(multi,chain,tmp_path):
    from test_multi_agent_execution import test_theft_profile_real_plugin_http_and_control as execute
    data(multi);cid,view=ticket(multi)
    assert choose(multi,cid,view,view['options'][1]['id'])[0].status_code==200
    request,task=prepare(multi,'theft-assistant','继续');prepared=submit(multi,request,task)
    payload=copy.deepcopy(prepared[2]['facts_plan']['records']['vehicle'])
    payload['returned_count']=payload['total_count']=len(payload['records']);chain[0]['vehicle']=payload
    execute(multi,chain,tmp_path,'vehicles','继续',['vehicle'],False,prepared)


def test_resolve_concurrent_only_one_wins(multi):
    from concurrent.futures import ThreadPoolExecutor
    data(multi);cid,view=ticket(multi)
    def resolve(index):
        body={'option_id':view['options'][index]['id'],'context_generation':view['context_generation'],'context_version':view['context_version'],'client_request_id':'parallel-'+str(index)}
        try:return clarifications.change(multi[0],multi[4],'ses_multi',cid,body)
        except HTTPException as exc:return exc.detail['code']
    with ThreadPoolExecutor(2) as pool:values=list(pool.map(resolve,[0,1]))
    assert sum(isinstance(v,dict) for v in values)==1 and 'clarification_already_resolved' in values

@pytest.mark.parametrize('extra',[{'target_refs':['forged']},{'source_data_run_id':'foreign'},{'agent_id':'gambling-assistant'}])
def test_client_cannot_supply_authoritative_entities(multi,extra):
    data(multi);cid,view=ticket(multi)
    body={'option_id':view['options'][0]['id'],'context_generation':view['context_generation'],'context_version':view['context_version'],'client_request_id':'forged',**extra}
    result=multi[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/resolve',json=body)
    assert result.status_code==422 and current(multi,'theft-assistant')['pending_clarification_id']==cid


def test_account_does_not_become_person_and_unknown_name_not_default(multi):
    data(multi,'gambling-assistant','看看资金')
    for text in ('查询这个账户资金','查询林晓舟和某陌生人的资金','查询他最近30天的资金'):
        request,task=prepare(multi,'gambling-assistant',text);_,row,snap=submit(multi,request,task)
        assert row['status']=='completed' and not snap.get('facts_plan')


def test_cancel_idempotent_and_profile_change_refused(multi,monkeypatch):
    from dataclasses import replace
    from control.agents import registry
    data(multi);cid,view=ticket(multi)
    profile=registry.require('theft-assistant')
    monkeypatch.setattr(registry,'PROFILES',{**registry.PROFILES,'theft-assistant':replace(profile,prompt=profile.prompt+'\nversion-test')})
    response,_=choose(multi,cid,view);assert response.status_code==409
    monkeypatch.setattr(registry,'PROFILES',{**registry.PROFILES,'theft-assistant':profile})
    body={'context_generation':view['context_generation'],'context_version':view['context_version'],'client_request_id':'cancel-replay'}
    one=multi[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/cancel',json=body)
    two=multi[3].post(P+'/sessions/ses_multi/clarifications/'+cid+'/cancel',json=body)
    assert one.status_code==200 and one.json()==two.json()


CASES=[json.loads(x) for x in (__import__('pathlib').Path(__file__).resolve().parents[3]/'specs/stage2-pr7-clarification-cases.jsonl').read_text().splitlines()]
@pytest.mark.parametrize('case',CASES,ids=lambda x:x['id'])
def test_clarification_corpus(multi,case):
    if case['seed']:data(multi,case['agent_id'],case['seed'])
    if case['reset']:task_context.reset(multi[0],multi[4]['uid'],'ses_multi',require(case['agent_id']))
    request,task=prepare(multi,case['agent_id'],case['text']);_,row,snap=submit(multi,request,task)
    assert row['status']=='completed' and not snap.get('facts_plan')
    assert snap['task_response']['code']==case['expected']
    assert not multi[0].one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))


def test_clarification_responses_match_openapi(multi):
    from control.openapi import build_openapi
    from test_openapi import validator
    data(multi);cid,view=ticket(multi);document=build_openapi(multi[1])
    validator(document,'TaskClarification').validate(view)
    result,body=choose(multi,cid,view)
    validator(document,'ClarificationResolveBody').validate(body)
    validator(document,'ClarificationChange').validate(result.json())
