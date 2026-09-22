import copy,json
import pytest
from fastapi import HTTPException
from test_control import context,P,create_user,login_user
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from test_seven_http_contract import chain
from control import business_runs as runs,trusted_results as results
from control.trusted_narrative import review
from control.store import Store

@pytest.fixture
def v6(tmp_path,monkeypatch):
    for flag in ('PX_BACKEND_V6','PX_TASK_CONTEXT_V1','PX_TASK_CLARIFICATION_V1','PX_TRUSTED_RESULT_V2'):monkeypatch.setenv(flag,'1')
    yield from context.__wrapped__(tmp_path,monkeypatch)

@pytest.fixture
def enabled(multi,monkeypatch):
    monkeypatch.setenv('PX_TRUSTED_RESULT_V2_UIDS',multi[4]['uid'])
    return multi


def finish(env,text='你好'):
    request,task=prepare(env,'gambling-assistant',text);_,row,snap=submit(env,request,task)
    runs.set_state(env[0],row['id'],'completed','completed')
    row=runs.owned(env[0],env[4]['uid'],'ses_multi',row['id'])
    return row,env[0].decrypt(row['request_ciphertext'])


def test_no_query_persisted_stable_and_cross_account(enabled,tmp_path):
    s,app,admin,client,user,*_=enabled
    row,snap=finish(enabled);rid=row['id'];path=P+'/sessions/ses_multi/runs/'+rid
    first=client.get(path+'/result');assert first.status_code==200,first.text
    value=first.json();assert value['data_usage']['status']=='not_started'
    assert value['data_usage']['queried'] is False and value['data_usage']['new_call_count']==0
    assert all(c['type']=='gap' for c in value['claims'])
    saved=s.one('SELECT * FROM run_results WHERE run_id=?',(rid,));assert saved['result_digest']==results.digest(value)
    with s.tx() as db:results.finalize(s,db,rid)
    assert client.get(path+'/result').json()==value
    Store(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    create_user(admin,'result-other');other=login_user(app,'result-other')
    try:
        for suffix in ('result','claims','data-usage'):
            assert other.get(path+'/'+suffix).status_code==404
            assert client.get(path.replace('ses_multi','other')+'/'+suffix).status_code==404
    finally:other.__exit__(None,None,None)
    from control.openapi import build_openapi
    from test_openapi import validator
    doc=build_openapi(app)
    validator(doc,'TrustedResultResponse').validate(value)
    validator(doc,'RunClaims').validate(client.get(path+'/claims').json())
    validator(doc,'RunDataUsage').validate(client.get(path+'/data-usage').json())


def test_old_run_remains_legacy(multi):
    row,_=finish(multi)
    result=results.read(multi[0],multi[4]['uid'],'ses_multi',row['id'])
    assert result['version']=='legacy' and multi[0].one('SELECT count(*) n FROM run_results')['n']==0


def test_terminal_result_conflict_rejects_overwrite(enabled):
    row,snap=finish(enabled);s=enabled[0]
    saved=s.one('SELECT * FROM run_results WHERE run_id=?',(row['id'],))
    snap['model_narrative']='new narrative'
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),row['id']))
    with pytest.raises(HTTPException) as exc:
        with s.tx() as db:results.finalize(s,db,row['id'])
    assert exc.value.detail['code']=='result_digest_conflict'
    assert s.one('SELECT * FROM run_results WHERE run_id=?',(row['id'],))==saved


def test_ciphertext_tamper_fails_closed(enabled):
    row,_=finish(enabled);s=enabled[0]
    value=results.read(s,enabled[4]['uid'],'ses_multi',row['id']);value['data_usage']['queried']=True
    with s.tx() as db:db.execute('UPDATE run_results SET result_ciphertext=? WHERE run_id=?',(s.encrypt(value),row['id']))
    with pytest.raises(HTTPException) as exc:results.read(s,enabled[4]['uid'],'ses_multi',row['id'])
    assert exc.value.detail['code']=='result_integrity_failed'


@pytest.mark.parametrize('state,expected',[('pending','in_flight'),('unknown','unknown'),('rejected','rejected'),('cancelled','unknown')])
def test_status_from_actual_attempts_not_query_mode(state,expected):
    row={'status':'running','phase':'running'};snap={'task_spec':{'query_mode':'data_query'},'facts_plan':{'modules':['funds']},'facts_state':{'modules':{'funds':{'status':state}}}}
    event={'event_key':'facts.funds','step_type':'plugin','started':1,'completed':None,'status':state,'capability_id':'peixian-records-funds'}
    value=results.usage(row,snap,[event]);assert value['status']==expected and value['queried'] is None
    assert results.usage(row,{'task_spec':{'query_mode':'data_query'}},[])['status']=='not_started'
    row['status']='cancelled';assert results.usage(row,snap,[event])['status']=='cancelled'


@pytest.mark.parametrize('text,status',[('', 'not_generated'),('以下为辅助说明。','verified'),('这部分还需要进一步说明。','unverified'),('共出现42次。','conflicted'),('未知等于0','conflicted'),('同框证明同行','conflicted'),('已经实施盗窃','conflicted')])
def test_narrative_coverage(text,status):assert review(text,[])['status']==status


@pytest.mark.parametrize('restart',[False,True])
def test_real_gateway_plugin_compiler_result(enabled,chain,tmp_path,restart):
    from test_multi_agent_execution import test_theft_profile_real_plugin_http_and_control
    test_theft_profile_real_plugin_http_and_control(enabled,chain,tmp_path,'theft','综合核对盗窃时空资料',['night','portrait','vehicle'],restart)
    s=enabled[0];row=s.one('SELECT * FROM business_runs ORDER BY created DESC LIMIT 1');snap=s.decrypt(row['request_ciphertext'])
    runs.set_state(s,row['id'],'completed','completed')
    value=results.read(s,enabled[4]['uid'],'ses_multi',row['id'])
    assert value['data_usage']['status']==('partial' if restart else 'rejected'),(value['data_usage'],value['missing'])
    assert value['data_usage']['queried'] is True
    assert any(c['type']=='computed' for c in value['claims']),value
    assert {r['module'] for r in value['records']}==({'portrait','vehicle'} if restart else {'night','portrait','vehicle'})
    assert all(c['source_run_id']==row['id'] for c in value['claims'])
    assert not any('same_frame'==c['protected_fields'].get('kind') and c['protected_fields'].get('observation')=='same_trip' for c in value['claims'])
    # A copied response without the persisted call events cannot confirm collection.
    projected=results.build(runs.owned(s,enabled[4]['uid'],'ses_multi',row['id']),snap,[])
    assert projected['data_usage']['queried'] is False and not projected['records']
    assert not any(c['type']!='gap' for c in projected['claims'])


def test_historical_reuse_is_not_new_query(enabled,chain,tmp_path):
    from test_multi_agent_execution import test_theft_profile_real_plugin_http_and_control
    from control.task_context import ensure
    from control.agents.registry import require
    test_theft_profile_real_plugin_http_and_control(enabled,chain,tmp_path,'vehicles','看看车辆记录',['vehicle'],False)
    s=enabled[0];row=s.one('SELECT * FROM business_runs ORDER BY created DESC LIMIT 1')
    runs.set_state(s,row['id'],'completed','completed')
    original=results.read(s,enabled[4]['uid'],'ses_multi',row['id'])
    with s.tx() as db:db.execute('INSERT INTO grants(uid,kind,resource) VALUES(?,?,?)',(enabled[4]['uid'],'model',enabled[6]['model']['modelID']))
    request,task=prepare(enabled,'theft-assistant','解释上一条结果',context_version=ensure(s,enabled[4]['uid'],'ses_multi',require('theft-assistant'))['version'])
    _,nextrow,snap=submit(enabled,request,task)
    assert snap['historical_projection']['source_data_run_id']==row['id']
    runs.set_state(s,nextrow['id'],'completed','completed')
    reused=results.read(s,enabled[4]['uid'],'ses_multi',nextrow['id'])
    assert reused['data_usage']['status']=='historical_evidence'
    assert reused['data_usage']['queried'] is False and reused['data_usage']['new_call_count']==0
    assert reused['claims']==original['claims'] and reused['records']==original['records']


def test_checked_claims_and_computation_have_different_authority(enabled,chain,tmp_path):
    from test_multi_agent_execution import test_theft_profile_real_plugin_http_and_control
    test_theft_profile_real_plugin_http_and_control(enabled,chain,tmp_path,'vehicles','看看车辆记录',['vehicle'],False)
    s=enabled[0];row=s.one('SELECT * FROM business_runs ORDER BY created DESC LIMIT 1');snap=s.decrypt(row['request_ciphertext']);events=s.rows('SELECT * FROM run_events WHERE run_id=?',(row['id'],))
    snap['facts_state']['checked']['approved']=[]
    # Without either independent record verification or checked summary claims,
    # records cannot acquire fact authority. The new code-owned vehicle proof is
    # covered separately, and old snapshots still require summary approval.
    snap.pop('record_check_version',None)
    value=results.build(row,snap,events)
    assert not any(c['type']=='fact' for c in value['claims'])
    assert any(c['type']=='computed' for c in value['claims'])
    snap['facts_state']['table']['summary'][0]['count']+=999
    value=results.build(row,snap,events)
    assert not any(c['type']=='computed' for c in value['claims'])
    assert any('不一致' in gap for gap in value['missing'])
    snap['facts_state']['modules']['vehicle']['response']['snapshot_id']='FORGED'
    value=results.build(row,snap,events)
    assert value['data_usage']['status']=='rejected' and not value['records']


@pytest.mark.parametrize('agent,text',[
    ('gambling-assistant','看看资金'),('gambling-assistant','看看夜间活动'),('gambling-assistant','核对同行'),
    ('gambling-assistant','查询已有关系'),('theft-assistant','看看车辆记录'),('theft-assistant','整理夜间活动')])
def test_compiled_facts_roundtrip(enabled,agent,text):
    import os,subprocess
    from pathlib import Path
    from control.facts_runtime import FactsState
    request,task=prepare(enabled,agent,text);_,row,snap=submit(enabled,request,task)
    s=enabled[0];uid=enabled[4]['uid'];plan=snap['facts_plan'];state=FactsState(s,'result-test-boot');op=state.begin(uid,row['id'],1)
    for module in plan['modules']:
        raw=copy.deepcopy(plan['records'][module]);raw['items']=raw.pop('records')
        assert state.reserve(uid,row['id'],1,op,module)
        assert state.complete(uid,row['id'],1,op,module,'completed',raw)=='completed'
    engine=Path(__file__).resolve().parents[3]/'deploy/peixian/platform-facts/engine.mjs'
    script='import {compile} from '+json.dumps(engine.as_uri())+';const p=JSON.parse(await Bun.stdin.text());console.log(JSON.stringify(compile({...p.scenario,required_modules:p.modules},p.records)));'
    process=subprocess.run([os.environ['BUN_EXECUTABLE'],'--eval',script],input=json.dumps(plan),capture_output=True,text=True)
    assert process.returncode==0,process.stderr
    table=json.loads(process.stdout);state.save_table(uid,row['id'],1,op,table)
    claims=[{k:f[k] for k in ('fact_id','statement','source_ids')} for f in table['facts'][:40]]
    state.check_claims(uid,row['id'],1,op,claims);state.finish(uid,row['id'],1,op)
    runs.set_state(s,row['id'],'completed','completed')
    value=results.read(s,uid,'ses_multi',row['id'])
    assert value['data_usage']['status']=='confirmed',value['missing']
    assert value['agent']['id']==agent
    assert any(c['type']=='computed' for c in value['claims'])
    assert any(c['type']=='fact' for c in value['claims']),value['missing']
    known={x['record_id'] for x in value['records']}|{f['source_document'] for f in plan['scenario']['facts'] if f.get('source_document')}
    assert all(set(c['source_ids'])<=known for c in value['claims'])
    for claim in value['claims']:
        if 'amount_minor' in claim['protected_fields']:assert type(claim['protected_fields']['amount_minor']) is int
    changed=copy.deepcopy(s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext']))
    changed['agent_profile']['id']='forged-agent'
    blocked=results.build(row,changed,s.rows('SELECT * FROM run_events WHERE run_id=?',(row['id'],)))
    assert not any(c['type'] in ('fact','computed') for c in blocked['claims'])


def test_v9_result_backup_restores_identical_digest(enabled,tmp_path):
    import sqlite3
    row,_=finish(enabled);s=enabled[0];before=s.one('SELECT * FROM run_results WHERE run_id=?',(row['id'],))
    target=tmp_path/'result-restore';target.mkdir()
    with sqlite3.connect(s.path) as source,sqlite3.connect(target/'control.sqlite3') as dest:source.backup(dest)
    restored=Store(target,tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    assert restored.schema_version()==9
    assert restored.one('SELECT * FROM run_results WHERE run_id=?',(row['id'],))==before
    value=results.read(restored,enabled[4]['uid'],'ses_multi',row['id'])
    assert results.digest(value)==before['result_digest']


def test_active_run_never_persists_final_result(enabled):
    request,task=prepare(enabled,'gambling-assistant','看看资金');_,row,_=submit(enabled,request,task)
    value=results.read(enabled[0],enabled[4]['uid'],'ses_multi',row['id'])
    assert value['status']=='pending' and value['data_usage']['status']=='not_started'
    assert not enabled[0].one('SELECT * FROM run_results WHERE run_id=?',(row['id'],))
