import copy,json,uuid
from concurrent.futures import ThreadPoolExecutor
import pytest,jsonschema
from fastapi import HTTPException
from test_control import context,P
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from control import task_context,task_spec,business_runs as runs
from control.agents.registry import require
from control.store import Store

@pytest.fixture
def v6(tmp_path,monkeypatch):
    monkeypatch.setenv('PX_BACKEND_V6','1');monkeypatch.setenv('PX_TASK_CONTEXT_V1','1')
    yield from context.__wrapped__(tmp_path,monkeypatch)

def complete_data(env,agent='gambling-assistant',text='看看资金',sid='ses_multi'):
    request,task=prepare(env,agent,text,sid);_,row,snap=submit(env,request,task,sid)
    plan=snap['facts_plan'];module=plan['modules'][0];raw=copy.deepcopy(plan['records'][module]);raw['items']=raw.pop('records');scene=plan['scenario']
    fact={'fact_id':raw['items'][0]['record_id'],'statement':'已核验原始记录','source_ids':[raw['items'][0]['record_id']],'time':'','kind':'record'}
    table={'schema_version':'facts-v1','scenario_id':scene['scenario_id'],'scenario_snapshot_id':scene['snapshot_id'],'records_snapshot_id':scene['records_snapshot_id'],'rule_version':plan['facts_rule_version'],'data_status':'complete','facts':[fact],'summary':[],'missing':[]}
    snap['facts_state']={'modules':{module:{'status':'completed','response':raw}},'table':table,'checked':None}
    with env[0].tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=?,evidence_ciphertext=? WHERE id=?',(env[0].encrypt(snap),env[0].encrypt({'status':'complete','cards':[]} ),row['id']))
    runs.set_state(env[0],row['id'],'completed','completed')
    return row['id']

def current(env,agent='gambling-assistant',sid='ses_multi'):
    return task_context.ensure(env[0],env[4]['uid'],sid,require(agent))

def test_abc_history_source_is_a_and_no_tool_dispatch(multi):
    a=complete_data(multi);ctx=current(multi);assert ctx['last_data_run_id']==a and ctx['version']==3
    b=None
    for text in ('解释上一条结果','继续'):
        request,task=prepare(multi,'gambling-assistant',text,context_version=current(multi)['version'])
        jsonschema.validate(task['spec'],task_spec.SPEC_V3_SCHEMA)
        assert task['spec']['source_data_run_id']==a
        assert task['spec']['direct_parent_run_id']==(b or a)
        _,row,snapshot=submit(multi,request,task)
        assert snapshot['run_kind']=='history_explanation' and snapshot['allowed_tools']==[] and snapshot['allowed_capabilities']==[]
        assert not snapshot.get('facts_plan')
        projection=snapshot['historical_projection'];assert projection['source_data_run_id']==a
        assert projection['digest']==task_context.digest({k:v for k,v in projection.items() if k!='digest'})
        assert 'rule-registry-v1' in json.dumps(projection)
        assert projection['digest'] in snapshot['payload']['system']
        with multi[0].tx() as db:db.execute('UPDATE business_runs SET result_ciphertext=? WHERE id=?',(multi[0].encrypt({'text':'MODEL_FABRICATED_FACT'}),row['id']))
        runs.set_state(multi[0],row['id'],'completed','completed');b=row['id']
        assert current(multi)['last_data_run_id']==a
        assert 'MODEL_FABRICATED_FACT' not in json.dumps(projection)
        assert multi[3].get(P+'/sessions/ses_multi/runs/'+row['id']+'/source').json()['source_data_run_id']==a
    assert current(multi)['last_completed_run_id']==b


def test_without_history_is_local_zero_model(multi):
    request,task=prepare(multi,'gambling-assistant','继续');_,row,snap=submit(multi,request,task)
    assert row['status']=='completed' and snap['task_response']['code']=='source_evidence_unavailable'
    assert not multi[0].one('SELECT * FROM run_deliveries WHERE run_id=?',(row['id'],))


def test_reset_blocks_late_completion_and_does_not_switch_agent(multi):
    a=complete_data(multi);request,task=prepare(multi,'gambling-assistant','看看资金');_,row,_=submit(multi,request,task)
    reset=task_context.reset(multi[0],multi[4]['uid'],'ses_multi',require('gambling-assistant'))
    runs.set_state(multi[0],row['id'],'completed','completed')
    assert current(multi)['last_data_run_id'] is None and current(multi)['last_completed_run_id'] is None
    assert reset['generation']==2
    with pytest.raises(HTTPException):prepare(multi,'theft-assistant','看看车辆')
    request,task=prepare(multi,'gambling-assistant','继续');assert task['local']['code']=='source_evidence_unavailable'
    assert runs.owned(multi[0],multi[4]['uid'],'ses_multi',a)['status']=='completed'


def test_context_cas_and_replay(multi):
    complete_data(multi);version=current(multi)['version']
    first,task1=prepare(multi,'gambling-assistant','继续',context_version=version)
    second,task2=prepare(multi,'gambling-assistant','继续',context_version=version)
    def send(pair):
        try:return submit(multi,*pair)[0]
        except HTTPException as exc:return exc.detail['code']
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(send,[(first,task1),(second,task2)]))
    assert sum(isinstance(x,dict) for x in results)==1 and 'task_context_changed' in results
    chosen=first if isinstance(results[0],dict) else second;oldtask=task1 if chosen is first else task2
    assert submit(multi,chosen,oldtask)[0]==next(x for x in results if isinstance(x,dict))

@pytest.mark.parametrize('change',['other_user','other_session','other_agent','profile','generation','failed','empty','text_only'])
def test_source_fail_closed(multi,change):
    rid=complete_data(multi);s=multi[0];ctx=current(multi);snap=s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))['request_ciphertext'])
    with s.tx() as db:
        if change=='other_user':db.execute('UPDATE session_task_contexts SET last_data_run_id=? WHERE uid=?',('unknown',multi[4]['uid']))
        elif change=='other_session':db.execute("UPDATE business_runs SET session_id='other' WHERE id=?",(rid,))
        elif change=='failed':db.execute("UPDATE business_runs SET status='failed' WHERE id=?",(rid,))
        else:
            if change=='other_agent':snap['agent_profile']['id']='theft-assistant'
            if change=='profile':snap['agent_profile']['profile_sha256']='0'*64
            if change=='generation':snap['session_task_context']['generation']=999
            if change=='empty':snap['facts_state']['table']['facts']=[]
            if change=='text_only':snap.pop('facts_state');snap['model_text']='has facts'
            db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),rid))
    assert task_context.source(s,multi[4]['uid'],'ses_multi',require('gambling-assistant'),current(multi)) is None


def test_apis_owned_and_reset_persist(multi,tmp_path):
    rid=complete_data(multi);client=multi[3]
    reply=client.get(P+'/sessions/ses_multi/task-context');assert reply.status_code==200,reply.text
    assert 'ciphertext' not in reply.text and 'registry' not in reply.text
    reset=client.delete(P+'/sessions/ses_multi/task-context');assert reset.status_code==200,reset.text
    s=Store(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    assert s.schema_version()==7 and task_context.ensure(s,multi[4]['uid'],'ses_multi',require('gambling-assistant'))['generation']==2
    assert client.get(P+'/sessions/not-owned/runs/'+rid+'/source').status_code==404


def test_disabled_capability_does_not_block_history(multi,monkeypatch):
    complete_data(multi)
    from control.developer_registry import registry
    d=registry.REGISTRY.documents()
    next(x for x in d['capabilities'] if x['id']=='records.funds')['state']='disabled'
    monkeypatch.setattr(registry,'REGISTRY',registry.Registry(**d))
    request,task=prepare(multi,'gambling-assistant','继续');assert task['local'] is None and task['historical_projection']
    _,row,_=submit(multi,request,task);runs.set_state(multi[0],row['id'],'completed','completed')
    request,task=prepare(multi,'gambling-assistant','看看资金');assert task['local']['code']=='capability_not_ready'


@pytest.mark.parametrize('agent,text',[('gambling-assistant','看看资金'),('theft-assistant','看看车辆记录')])
def test_history_dispatched_once_without_plugins_or_browser(multi,agent,text):
    import httpx
    from control.run_scheduler import Coordinator
    a=complete_data(multi,agent,text);request,task=prepare(multi,agent,'继续');_,row,snap=submit(multi,request,task)
    s,app,admin=multi[:3];posted=[];calls=[]
    def transport(req):
        calls.append((req.method,req.url.path))
        if req.method=='POST':
            assert req.url.path=='/session/ses_multi/prompt_async'
            body=json.loads(req.content);assert body['tools']['*'] is False and snap['historical_projection']['digest'] in body['system'];posted.append(body)
            return httpx.Response(204)
        if req.url.path.endswith('/message'):
            return httpx.Response(200,json=[{'info':{'id':row['message_id'],'role':'user','time':{'created':1000}},'parts':[]},{'info':{'id':'msg_history','role':'assistant','finish':'stop','time':{'created':1000,'completed':2000}},'parts':[{'type':'text','text':'MODEL_FABRICATED_FACT'},{'type':'analysis_result','data':{'fake':True}}]}])
        assert '/internal/runtime/runs/' in req.url.path
        return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':{'id':row['id'],'session_id':'ses_multi','message_id':row['message_id'],'state':'finished'} if posted else None})
    old=app.state.http;app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:admin.portal.call(Coordinator(app).step,row)
    finally:admin.portal.call(app.state.http.aclose);app.state.http=old
    result=s.one('SELECT * FROM business_runs WHERE id=?',(row['id'],));assert result['status']=='completed'
    assert len(posted)==1 and 'MODEL_FABRICATED_FACT' not in json.dumps(s.decrypt(result['evidence_ciphertext']))
    assert current(multi,agent)['last_data_run_id']==a
    report=multi[3].get(P+'/sessions/ses_multi/runs/'+row['id']+'/report');assert report.status_code==200 and a in report.text
    assert 'MODEL_FABRICATED_FACT' not in report.text
    assert not s.one("SELECT 1 FROM run_events WHERE run_id=? AND step_type='plugin'",(row['id'],))


def test_cross_account_context_and_source_hidden(multi):
    from test_control import create_user,login_user
    rid=complete_data(multi);request,task=prepare(multi,'gambling-assistant','继续');_,row,_=submit(multi,request,task)
    create_user(multi[2],'other-person');other=login_user(multi[1],'other-person')
    try:
        for path in ('/task-context','/runs/'+rid+'/source','/runs/'+row['id']+'/source'):
            assert other.get(P+'/sessions/ses_multi'+path).status_code==404
    finally:other.__exit__(None,None,None)


def test_reset_receipt_does_not_increment_twice(multi):
    complete_data(multi);client=multi[3];header={'Idempotency-Key':'reset-context-fixed'}
    first=client.delete(P+'/sessions/ses_multi/task-context',headers=header)
    second=client.delete(P+'/sessions/ses_multi/task-context',headers=header)
    assert first.status_code==200 and first.json()==second.json()
    assert current(multi)['generation']==2


def test_legacy_initialization_never_rewrites_history(multi):
    rid=complete_data(multi);s=multi[0]
    with s.tx() as db:
        row=db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,)).fetchone();snap=s.decrypt(row[0]);snap.pop('session_task_context');snap.pop('run_kind');snap['task_spec']['schema_version']='task-spec-v2';snap['task_spec']['context_generation']=None
        original=s.encrypt(snap);db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(original,rid));db.execute('DELETE FROM session_task_contexts')
    assert current(multi)['last_data_run_id']==rid
    assert s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))['request_ciphertext']==original


CASES=[json.loads(x) for x in (__import__('pathlib').Path(__file__).resolve().parents[3]/'specs/stage2-pr6-context-cases.jsonl').read_text().splitlines()]
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_context_corpus(multi,case):
    agent=case['agent_id'];source=None
    for text in case['turns']:
        if text=='RESET':task_context.reset(multi[0],multi[4]['uid'],'ses_multi',require(agent));continue
        if text.startswith('SWITCH '):
            with pytest.raises(HTTPException) as exc:prepare(multi,text.split(' ',1)[1],'你好')
            assert exc.value.detail['code']==case['expected'];continue
        if text in ('看看资金','看看车辆记录'):source=complete_data(multi,agent,text);continue
        request,task=prepare(multi,agent,text)
        if case['expected']=='original_source':assert task['spec']['source_data_run_id']==source and task['local'] is None
        else:assert task['local']['code']==case['expected']
        _,row,_=submit(multi,request,task);runs.set_state(multi[0],row['id'],'completed','completed')


def test_unmigrated_api_fails_closed(multi,monkeypatch):
    complete_data(multi)
    monkeypatch.setattr(multi[0],'schema_version',lambda:6)
    for method in ('get','delete'):
        response=getattr(multi[3],method)(P+'/sessions/ses_multi/task-context')
        assert response.status_code==409 and response.json()['code']=='task_context_not_enabled'
