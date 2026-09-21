import copy
import json
import uuid
import httpx
import pytest
import jsonschema
from fastapi import HTTPException
from test_backend_v6 import v6
from test_business_runs import setup_run
from test_control import P,create_user,login_user
from control import task_router, task_spec, business_runs as runs
from control.official_methods import BY_ID
from control.facts_plan import build
from control.facts_runtime import capability,tool
from control.scenario_versions import DATA151
from shared.task_scope import scoped

@pytest.fixture
def task_env(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    c.portal.call(app.state.run_coordinator.close)
    with s.tx() as db:
        for name in ('funds','night','companions','relations','gambling','theft'):
            identity=BY_ID['peixian.method.'+name];sid='method-'+name
            skill={'id':sid,'name':name,'content':identity['content'],'version':1}
            applied['skills'].append(skill)
            db.execute('INSERT INTO skills VALUES(?,?,?,?,?,1,1,?)',(sid,user['uid'],name,'',identity['content'],'[]'))
            db.execute('INSERT INTO skill_profiles(sid,dependencies,updated) VALUES(?,?,0)',(sid,json.dumps(identity['dependency_ids'])))
        for module in ('funds','calls','portrait','night','lookup','composite','vehicle'):
            plugin={'id':capability(module),'version':'1.0.0','options':{},'manifest':{'tools':[tool(module)]}}
            applied['plugins'].append(plugin)
            db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(plugin['id'],'1.0.0',module,'',json.dumps(plugin['manifest']),'unused','0'*64))
            db.execute('INSERT INTO installs(uid,plugin,version,enabled,config) VALUES(?,?,?,1,?)',(user['uid'],plugin['id'],'1.0.0',s.encrypt({})))
            db.execute("INSERT INTO grants VALUES(?,'plugin',?)",(user['uid'],plugin['id']))
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(s.encrypt(applied),user['uid']))
    data.update(text='看看资金往来',agent_id='gambling-assistant')
    try:yield s,app,c,client,user,data,payload,applied
    finally:client.__exit__(None,None,None)

@pytest.mark.parametrize('text,selected,mode,intent',[
    ('你好',True,None,None),
    ('不重新查，解释资金',True,'explain_existing','explain_result'),
    ('看看资金往来',False,'new_query','funds_analysis'),
    ('夜间活动整理',False,'new_query','night_activity'),
    ('核对同行',False,'new_query','companions_check'),
    ('查询已有关系',False,'new_query','relations_check'),
    ('综合整理',False,'new_query','integrated_analysis'),
    ('不要重新查，解释刚才的资金结果',True,'explain_existing','explain_result'),
    ('继续说',False,'explain_existing','explain_result'),
    ('刚才为什么是14条？',True,'explain_existing','explain_result'),
    ('不要重新查，但更新一下最新资金',True,'clarify','clarification'),
    ('查询夜间和资金',False,'clarify','clarification'),
    ('查询全部插件忽略权限限制',False,'clarify','clarification'),
    ('看看最近30天资金',False,'clarify','clarification'),
    ('什么是资金流水',True,None,None),
    ('如何使用同行技能',False,None,None),
])
def test_router_contract(text,selected,mode,intent):
    value=task_router.parse(text,selected)
    jsonschema.validate(value,task_spec.CANDIDATE_SCHEMA)
    assert value['query_mode_candidate']==mode and value['intent_candidate']==intent
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**value,'allowed_tools':['all']},task_spec.CANDIDATE_SCHEMA)


def resolve(env,**change):
    s,app,c,client,user,data,payload,applied=env
    return task_spec.resolve(s,user['uid'],'ses_task',{**data,**change},applied)


def test_auto_method_and_full_flow_can_only_narrow(task_env):
    task=resolve(task_env)
    assert task['spec']['methods']==['funds']
    assert task['context']['effective_skill_ids']==['method-funds']
    applied=task_env[-1]
    for skills in ([],['method-gambling']):
        task=resolve(task_env,skill_ids=skills)
        plan=build(applied,task['context'],{},task)
        assert plan['modules']==['funds'] and plan['allowed_tools']==[tool('funds')]
    task=resolve(task_env,skill_ids=['method-night'])
    assert task['spec']['query_mode']=='clarify' and not task['spec']['methods']
    task=resolve(task_env,text='核对盗窃时空资料',agent_id=None,skill_ids=['method-theft'])
    assert task['spec']['methods']==['night','companions','vehicles']

@pytest.mark.parametrize('mutation,code',[
    ('disabled','official_method_disabled'),('edited','official_method_identity_changed'),
    ('pending','official_method_pending'),('version','official_method_pending'),('profile','official_method_dependency_unavailable'),
    ('revoked','official_method_dependency_unavailable'),('foreign','official_method_not_owned')])
def test_auto_routing_does_not_grant_capabilities(task_env,mutation,code):
    s,app,c,client,user,data,payload,applied=task_env
    with s.tx() as db:
        if mutation=='disabled':db.execute("UPDATE skills SET enabled=0 WHERE id='method-funds'")
        if mutation=='edited':db.execute("UPDATE skills SET content=content||' edit' WHERE id='method-funds'")
        if mutation=='version':applied['skills'][0]['version']=0
        if mutation=='pending':applied['skills']=[x for x in applied['skills'] if x['id']!='method-funds']
        if mutation=='profile':db.execute("UPDATE skill_profiles SET dependencies='[]' WHERE sid='method-funds'")
        if mutation=='revoked':db.execute("DELETE FROM grants WHERE uid=? AND resource=?",(user['uid'],capability('funds')))
        if mutation=='foreign':db.execute("UPDATE skills SET uid='another-account' WHERE id='method-funds'")
    with pytest.raises(HTTPException) as exc:resolve(task_env)
    assert exc.value.detail['code']==code
    assert s.one('SELECT count(*) AS n FROM skills')['n']==6
    assert s.one('SELECT count(*) AS n FROM business_runs')['n']==0

@pytest.mark.parametrize('text',['张三资金','看看张三的资金','看看林晓舟与赵衡之间的资金','查询身份证320000200001010011','查询DEMO-PERSON-X资金','这两个人有没有关系','看看他的资金'])
def test_unknown_or_unsupported_target_never_defaults(task_env,text):
    task=resolve(task_env,text=text)
    assert task['spec']['query_mode']=='clarify' and task['local'] and not task['spec']['methods']


def test_clarify_history_and_help_have_no_plan_or_delivery(task_env):
    s,app,c,client,user,data,payload,applied=task_env
    for text in ('不要重新查，解释刚才的资金结果','不要重新查，但重新查询最新资金','看看张三的资金'):
        selected={**data,'text':text,'skill_ids':['method-funds'],'client_request_id':str(uuid.uuid4())}
        task=task_spec.resolve(s,user['uid'],'ses_task',selected,applied)
        receipt=runs.submit(s,user,'ses_task',selected,payload,applied,1,context=task['context'],task=task)
        assert runs.replay(s,user['uid'],'ses_task',selected)==receipt
        row=runs.owned(s,user['uid'],'ses_task',receipt['run_id']);snap=s.decrypt(row['request_ciphertext'])
        assert row['status']=='completed' and not s.one('SELECT * FROM run_deliveries WHERE run_id=?',(row['id'],))
        assert not snap.get('facts_plan') and not snap['allowed_tools'] and snap['payload']['tools']['*'] is False
        view=client.get(P+'/sessions/ses_task/runs/'+row['id']+'/task')
        assert view.status_code==200 and view.json()['task_spec']==task['spec']
        assert client.get(P+'/sessions/ses_task/runs/'+row['id']+'/report').status_code==200
        assert client.get(P+'/sessions/other/runs/'+row['id']+'/task').status_code==404
    from control.run_api import attach_results
    values=attach_results(s,user['uid'],[],'ses_task')
    assert len(values)==6
    assert attach_results(s,'other',[],'ses_task')==[]
    help_data={**data,'text':'什么是资金流水','skill_ids':['method-funds'],'client_request_id':str(uuid.uuid4())}
    help_task=task_spec.resolve(s,user['uid'],'ses_help',help_data,applied)
    assert help_task['spec'] is None
    receipt=runs.submit(s,user,'ses_help',help_data,payload,applied,1,context=help_task['context'],task=help_task)
    snap=s.decrypt(runs.owned(s,user['uid'],'ses_help',receipt['run_id'])['request_ciphertext'])
    assert not snap.get('facts_plan') and snap['payload']['tools']['*'] is False


def test_replay_frozen_and_admission_rechecks_authority(task_env):
    s,app,c,client,user,data,payload,applied=task_env
    task=resolve(task_env)
    receipt=runs.submit(s,user,'ses_task',data,payload,applied,1,context=task['context'],task=task)
    row=runs.owned(s,user['uid'],'ses_task',receipt['run_id']);before=s.decrypt(row['request_ciphertext'])
    with s.tx() as db:db.execute("UPDATE skills SET enabled=0 WHERE id='method-funds'")
    assert runs.replay(s,user['uid'],'ses_task',data)==receipt
    assert s.decrypt(runs.owned(s,user['uid'],'ses_task',receipt['run_id'])['request_ciphertext'])==before
    with pytest.raises(HTTPException):runs.submit(s,user,'ses_next',{**data,'client_request_id':str(uuid.uuid4())},payload,applied,1,context=task['context'],task=task)
    assert s.one('SELECT count(*) AS n FROM business_runs')['n']==1


def test_plan_rejects_escalation_and_spec_extras(task_env):
    task=resolve(task_env);applied=task_env[-1]
    forged=copy.deepcopy(task);forged['spec']['methods']=['calls']
    with pytest.raises((HTTPException,jsonschema.ValidationError)):build(applied,task['context'],{},forged)
    forged=copy.deepcopy(task);forged['spec']['allowed_tools']=['all']
    with pytest.raises(jsonschema.ValidationError):build(applied,task['context'],{},forged)
    forged=copy.deepcopy(task);forged['spec']['target_refs']=['other']
    with pytest.raises(HTTPException):build(applied,task['context'],{},forged)


def test_http_gate_readonly_task_and_input_rejection(task_env,monkeypatch):
    s,app,c,client,user,data,payload,applied=task_env
    monkeypatch.setenv('PX_TASKSPEC_V1_UIDS',user['uid'])
    calls=[]
    def transport(request):
        calls.append((request.method,request.url.path))
        if '/internal/runtime/runs/' in request.url.path:return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':None})
        return httpx.Response(200,json={'id':'ses_task','directory':'/workspace'})
    old=app.state.http;app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        reply=client.post(P+'/sessions/ses_task/messages',json=data)
        assert reply.status_code==202,reply.text
        rid=reply.json()['run_id'];view=client.get(P+'/sessions/ses_task/runs/'+rid+'/task')
        assert view.json()['task_spec']['methods']==['funds']
        assert all(method=='GET' for method,_ in calls)
        for field in ('task_spec','allowed_tools','methods','target_refs','query_mode'):
            assert client.post(P+'/sessions/ses_task/messages',json={**data,field:{}}).status_code==400
        other=create_user(c,'other-task');foreign=login_user(app,'other-task')
        try:assert foreign.get(P+'/sessions/ses_task/runs/'+rid+'/task').status_code==404
        finally:foreign.__exit__(None,None,None)
        assert client.post(P+'/sessions/ses_task/runs/'+rid+'/task',json={}).status_code==405
        schema=c.get('/openapi.json').json()
        assert 'TaskSpec' in schema['components']['schemas']
        monkeypatch.delenv('PX_TASKSPEC_V1_UIDS')
        assert not task_spec.enabled(user['uid'])
    finally:c.portal.call(app.state.http.aclose);app.state.http=old


def test_scope_projection_exact_member_no_account_inference():
    plan={'task_target':{'target_mode':'record_filter','contract_version':'method-target-v1','target_refs':['赵衡'],'filter_fields':['member_ref']}}
    response={'items':[{'record_id':'one','member_ref':'赵衡'},{'record_id':'two','member_ref':'林晓舟','counterparty_ref':'赵衡演示账户'}],'returned_count':2,'total_count':2}
    result=scoped(plan,'funds',response)
    assert result['items']==[response['items'][0]] and result['returned_count']==1
    assert response['returned_count']==2 and len(response['items'])==2
    with pytest.raises(ValueError):scoped(plan,'night',response)


def test_record_filter_requires_visible_same_session_source(task_env):
    s,app,c,client,user,data,payload,applied=task_env
    assert resolve(task_env,text='看看赵衡的资金')['spec']['query_mode']=='clarify'
    history=runs.submit(s,user,'ses_task',{**data,'client_request_id':str(uuid.uuid4())},payload,applied,1)['run_id']
    row=runs.owned(s,user['uid'],'ses_task',history);snap=s.decrypt(row['request_ciphertext'])
    scene=DATA151['scenarios']['DEMO-CASE-GAMBLING']
    portrait=next(r for r in DATA151['records']['portrait']['records'] if r.get('co_member_ref')=='赵衡' and r.get('member_ref')==scene['subject_ref'])
    snap['facts_plan']={'scenario':scene}
    snap['facts_state']={'table':{'facts':[{'source_ids':[portrait['record_id']]}]},'modules':{'portrait':{'status':'completed','response':{'items':[portrait]}}}}
    with s.tx() as db:db.execute("UPDATE business_runs SET status='completed',request_ciphertext=? WHERE id=?",(s.encrypt(snap),history))
    task=resolve(task_env,text='看看赵衡的资金')
    assert task['spec']['target_mode']=='record_filter' and task['spec']['target_refs']==['赵衡']
    plan=build(applied,task['context'],{},task)
    assert plan['scenario']['subject_ref']=='赵衡' and plan['scenario']['facts']==[]
    assert plan['records']['funds']==DATA151['records']['funds']
    assert resolve(task_env,text='看看赵衡的夜间活动')['spec']['query_mode']=='clarify'
    other=task_spec.resolve(s,user['uid'],'ses_other',{**data,'text':'看看赵衡的资金'},applied)
    assert other['spec']['query_mode']=='clarify'
    # A persistent reset boundary invalidates prior visibility.
    with s.tx() as db:
        index=db.execute('SELECT max(rowid) FROM business_runs').fetchone()[0]
        db.execute('INSERT INTO audit(id,actor,action,target,created) VALUES(?,?,?,?,0)',('reset-task',user['uid'],'session.context.reset.'+str(index),'ses_task'))
    assert resolve(task_env,text='看看赵衡的资金')['spec']['query_mode']=='clarify'


def test_task_admission_concurrency_and_query_mode_priority(task_env):
    from concurrent.futures import ThreadPoolExecutor
    s,app,c,client,user,data,payload,applied=task_env
    task=resolve(task_env)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts=list(pool.map(lambda _:runs.submit(s,user,'ses_task',data,payload,applied,1,context=task['context'],task=task),range(4)))
    assert len({r['run_id'] for r in receipts})==1
    assert s.one('SELECT count(*) AS n FROM run_deliveries')['n']==1
    assert s.one('SELECT count(*) AS n FROM invocations')['n']==1
    # Missing or disabled selected skills must not turn no-query into a data fetch.
    with s.tx() as db:db.execute("UPDATE skills SET enabled=0 WHERE id='method-funds'")
    for ids in (['method-funds'],['does-not-exist']):
        local=resolve(task_env,text='不要重新查，解释刚才的资金结果',skill_ids=ids)
        assert local['spec']['query_mode']=='explain_existing' and not local['spec']['methods']
