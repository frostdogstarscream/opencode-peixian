import json
import uuid

import pytest
from fastapi import HTTPException
from test_provider_v2_execution import candidate
from test_provider_flow import provider,enabled,v6,task_env,multi
from test_provider_contract_v2 import response
from test_multi_agent import prepare,submit
from control import migrations_v10,migrations_v11,analysis_tasks as tasks,business_runs,trusted_results,schema
from control.theft_provider_flow import preview
from control.theft_provider_state import ProviderState
from control.store import now


@pytest.fixture
def task_provider(provider,monkeypatch):
    store=provider[0]
    with store.tx() as db:
        migrations_v10.migrate(db,fresh=True,timestamp=now())
        migrations_v11.migrate(db,fresh=True,timestamp=now())
    monkeypatch.setenv('PX_THEFT_TASK_LIMITS',json.dumps({'max_user_requests':40,'max_planning_calls':8,'max_rounds_per_task':8,'max_data_calls':10,'max_steps':10,'max_locations':3}))
    return provider


def original(env,monkeypatch):
    store=env[0];uid=env[4]['uid'];row,plan=candidate(env,monkeypatch,'incidents')
    state=ProviderState(store);op=state.begin(uid,row['id'],1)
    state.reserve(uid,row['id'],1,op,'incidents');state.dispatch(uid,row['id'],1,op,'incidents')
    state.complete(uid,row['id'],1,op,'incidents','completed',response('incidents'));state.finish(uid,row['id'],1,op)
    business_runs.set_state(store,row['id'],'completed','completed')
    result=trusted_results.read(store,uid,'ses_multi',row['id']);record=result['records'][0]
    return row,{'run_id':row['id'],'result_digest':trusted_results.digest(result),'record_id':record['record_id'],'snapshot_id':record['snapshot_id']}


def new_task(env):
    return tasks.create(env[0],env[4],'ses_multi',{'goal':'核对选定来源资料','client_request_id':str(uuid.uuid4()),'data_environment':'acceptance_real'})


def test_migration_is_incremental_and_rollback_safe(provider,monkeypatch):
    store=provider[0]
    with store.tx() as db:migrations_v10.migrate(db,fresh=True,timestamp=now())
    before=store.rows('SELECT id,username,password,role FROM users')
    monkeypatch.setenv('PX_ALLOW_V11_MIGRATION','1')
    with pytest.raises(ValueError,match='frozen'):
        with store.tx() as db:migrations_v11.migrate(db,fresh=False,timestamp=now())
    with pytest.raises(RuntimeError):
        with store.tx() as db:
            migrations_v11.migrate(db,fresh=True,timestamp=now());raise RuntimeError('interrupt before commit')
    assert store.schema_version()==10
    assert not store.one("SELECT name FROM sqlite_master WHERE name='analysis_tasks'")
    with store.tx() as db:migrations_v11.migrate(db,fresh=True,timestamp=now())
    assert store.rows('SELECT id,username,password,role FROM users')==before
    with store.read(snapshot=True) as db:schema.validate(db)
    with pytest.raises(ValueError):
        with store.tx() as db:migrations_v11.migrate(db,fresh=True,timestamp=now())
    assert store.schema_version()==11


def test_source_derived_step_cas_and_replay(task_provider,monkeypatch):
    env=task_provider;store=env[0];uid=env[4]['uid'];old,reference=original(env,monkeypatch);task=new_task(env)
    key=str(uuid.uuid4())
    data={'analysis_task_id':task['analysis_task_id'],'context_version':1,'step_request_id':key,'source_refs':[reference],'analysis_direction':'case_to_person','contract_version':'theft-provider-contract-v2','kind':'incidents','query':{'radius_m':500}}
    with pytest.raises(HTTPException) as exc:preview(store,uid,'ses_multi',data,env[-1],1)
    assert exc.value.detail['code']=='coordinate_contract_unconfirmed'
    config=json.loads(__import__('os').environ['PX_THEFT_REAL_CONFIG']);config['coordinate_compatibility']={'police:police':True};monkeypatch.setenv('PX_THEFT_REAL_CONFIG',json.dumps(config))
    signed=preview(store,uid,'ses_multi',data,env[-1],1)
    req,task_spec=prepare(env,'theft-assistant','查询选定位置',client_request_id=key,provider_query={k:signed[k] for k in ('plan','confirmation')})
    receipt,row,snap=submit(env,req,task_spec)
    assert snap['provider_plan']['query']['lon']=='116.1'
    assert business_runs.replay(store,uid,'ses_multi',req)==receipt
    current=tasks.view(store,uid,'ses_multi',task['analysis_task_id'])
    assert current['context_version']==2 and len(current['steps'])==1
    assert current['steps'][0]['source_refs']==[reference]
    assert current['steps'][0]['source_data_run_id']==old['id']
    assert current['budget']['user_requests']==1
    with pytest.raises(HTTPException):preview(store,uid,'ses_multi',data,env[-1],1)
    with pytest.raises(HTTPException) as exc:tasks.view(store,'other-account','ses_multi',task['analysis_task_id'])
    assert exc.value.status_code==404


def test_source_selection_no_overrides_and_bad_digest(task_provider,monkeypatch):
    env=task_provider;store=env[0];uid=env[4]['uid'];_,reference=original(env,monkeypatch);task=new_task(env)
    meta=tasks.freeze_step(store,uid,'ses_multi',task['analysis_task_id'],1,request_key=str(uuid.uuid4()),source_refs=[reference])
    with pytest.raises(HTTPException) as exc:tasks.derive(store,uid,'ses_multi',meta,'incidents',{'lon':'0','lat':'0','radius_m':1})
    assert exc.value.detail['code']=='source_value_override'
    with pytest.raises(HTTPException):tasks.freeze_step(store,uid,'ses_multi',task['analysis_task_id'],1,request_key=str(uuid.uuid4()),source_refs=[{**reference,'result_digest':'changed'}])
    with pytest.raises(HTTPException):tasks.freeze_step(store,uid,'ses_multi',task['analysis_task_id'],1,request_key=str(uuid.uuid4()),source_refs=[reference,reference])


def test_create_task_idempotency(task_provider):
    env=task_provider;body={'goal':'一个目标','client_request_id':str(uuid.uuid4()),'data_environment':'acceptance_real'}
    a=tasks.create(env[0],env[4],'ses_multi',body);b=tasks.create(env[0],env[4],'ses_multi',body)
    assert a==b and a['analysis_task_id']==a['scenario_id']
    with pytest.raises(HTTPException):tasks.create(env[0],env[4],'ses_multi',{**body,'goal':'另一个目标'})


def test_same_step_concurrent_admission_only_creates_one_run(task_provider,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    env=task_provider;store=env[0];uid=env[4]['uid'];original(env,monkeypatch);task=new_task(env)
    key=str(uuid.uuid4())
    body={'analysis_task_id':task['analysis_task_id'],'context_version':1,'step_request_id':key,'contract_version':'theft-provider-contract-v2','kind':'incidents','query':{'lon':'116.1','lat':'34.1','radius_m':500}}
    signed=preview(store,uid,'ses_multi',body,env[-1],1)
    req,spec=prepare(env,'theft-assistant','查询指定位置',client_request_id=key,provider_query={k:signed[k] for k in ('plan','confirmation')})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:submit(env,req,spec)[0],range(2)))
    assert results[0]==results[1]
    assert len(tasks.view(store,uid,'ses_multi',task['analysis_task_id'])['steps'])==1
    assert len(store.rows('SELECT * FROM run_deliveries WHERE run_id=?',(results[0]['run_id'],)))==1


def test_source_value_change_after_preview_is_rejected(task_provider,monkeypatch):
    env=task_provider;store=env[0];uid=env[4]['uid'];_,reference=original(env,monkeypatch);task=new_task(env)
    meta=tasks.freeze_step(store,uid,'ses_multi',task['analysis_task_id'],1,request_key=str(uuid.uuid4()),source_refs=[reference])
    with store.tx() as db:db.execute("UPDATE run_results SET result_digest='changed' WHERE run_id=?",(reference['run_id'],))
    with pytest.raises(HTTPException):tasks.validate_context(store,uid,'ses_multi',meta)


def test_v10_copy_upgrade_preserves_frozen_history(provider,monkeypatch,tmp_path):
    import sqlite3
    from control.store import Store
    store=provider[0];uid=provider[4]['uid'];row,_=original(provider,monkeypatch)
    with store.tx() as db:migrations_v10.migrate(db,fresh=True,timestamp=now())
    prior=trusted_results.read(store,uid,'ses_multi',row['id'])
    target=tmp_path/'upgrade-copy';target.mkdir()
    destination=sqlite3.connect(target/'control.sqlite3')
    with store.read() as db:db.backup(destination)
    destination.close()
    copied=Store(target,tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    with copied.tx() as db:
        db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
    monkeypatch.setenv('PX_ALLOW_V11_MIGRATION','1')
    with pytest.raises(ValueError,match='responsibilities'):
        with copied.tx() as db:migrations_v11.migrate(db,fresh=False,timestamp=now())
    # This synthetic fixture never ran a host Worker. Explicitly close only its
    # unclaimed queued setup jobs; the migration itself must not clear work.
    with copied.tx() as db:
        assert not db.execute("SELECT 1 FROM job_attempts WHERE outcome IS NULL").fetchone()
        assert not db.execute("SELECT 1 FROM jobs WHERE status='running' OR recovery_required=1").fetchone()
        db.execute("UPDATE jobs SET status='cancelled',phase='finished' WHERE status='queued' AND attempts=0")
    with copied.tx() as db:migrations_v11.migrate(db,fresh=False,timestamp=now())
    assert store.schema_version()==10 and copied.schema_version()==11
    assert trusted_results.read(copied,uid,'ses_multi',row['id'])==prior
    reopened=Store(target,tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    assert reopened.schema_version()==11
    monkeypatch.setattr('control.store.MAX_SCHEMA_VERSION',10)
    with pytest.raises(ValueError,match='newer'):
        Store(target,tmp_path/'key',tmp_path/'worker',tmp_path/'admin')


@pytest.mark.parametrize('chain',[['incidents','captures','community'],['captures','tracks','incidents']])
def test_nonempty_sources_link_multiple_frozen_steps(task_provider,monkeypatch,chain):
    from test_provider_flow import pid,tool
    env=task_provider;store=env[0];uid=env[4]['uid'];_,reference=original(env,monkeypatch)
    config=json.loads(__import__('os').environ['PX_THEFT_REAL_CONFIG']);config['coordinate_compatibility']={'police:police':True};monkeypatch.setenv('PX_THEFT_REAL_CONFIG',json.dumps(config))
    with store.tx() as db:
        for kind in ('captures','tracks','community'):
            manifest={'tools':[tool(kind)],'connections':{'provider':{'description':'isolated contract'}}}
            db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(pid(kind),'2.0.0',kind,'',json.dumps(manifest),'unused','0'*64))
            db.execute('INSERT OR REPLACE INTO installs(uid,plugin,version,enabled,config) VALUES(?,?,?,1,?)',(uid,pid(kind),'2.0.0',store.encrypt({})))
            db.execute("INSERT OR IGNORE INTO grants VALUES(?,'plugin',?)",(uid,pid(kind)))
            db.execute('INSERT INTO plugin_connections VALUES(?,?,?,?)',(pid(kind),'2.0.0','provider','warning-test' if kind=='community' else 'police-test'))
            env[-1]['plugins']=[p for p in env[-1]['plugins'] if p['id']!=pid(kind)]+[{'id':pid(kind),'version':'2.0.0','options':{},'manifest':manifest}]
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(store.encrypt(env[-1]),uid))
    task=new_task(env);parent=None
    for kind in chain:
        key=str(uuid.uuid4());current=tasks.view(store,uid,'ses_multi',task['analysis_task_id'])
        q={'radius_m':500} if kind in ('incidents','captures') else {}
        if kind in ('captures','tracks','community'):q.update(start='2026-09-20 22:13:14',end='2026-09-21 02:03:04')
        signed=preview(store,uid,'ses_multi',{'analysis_task_id':task['analysis_task_id'],'context_version':current['context_version'],'step_request_id':key,'source_refs':[reference],'direct_parent_run_id':parent,'contract_version':'theft-provider-contract-v2','kind':kind,'query':q},env[-1],1)
        request,spec=prepare(env,'theft-assistant','核对选定来源',client_request_id=key,provider_query={k:signed[k] for k in ('plan','confirmation')})
        _,row,_=submit(env,request,spec)
        state=ProviderState(store);op=state.begin(uid,row['id'],1)
        state.reserve(uid,row['id'],1,op,kind);state.dispatch(uid,row['id'],1,op,kind)
        state.complete(uid,row['id'],1,op,kind,'completed',response(kind));state.finish(uid,row['id'],1,op)
        business_runs.set_state(store,row['id'],'completed','completed')
        result=trusted_results.read(store,uid,'ses_multi',row['id']);record=result['records'][0]
        reference={'run_id':row['id'],'result_digest':trusted_results.digest(result),'record_id':record['record_id'],'snapshot_id':record['snapshot_id']};parent=row['id']
    current=tasks.view(store,uid,'ses_multi',task['analysis_task_id'])
    assert len(current['steps'])==3 and current['budget']['data_responses']==3
    assert current['steps'][2]['direct_parent_run_id']==current['steps'][1]['run_id']


def test_exhausted_budget_rolls_back_run_and_delivery(task_provider,monkeypatch):
    env=task_provider;store=env[0];uid=env[4]['uid'];original(env,monkeypatch);task=new_task(env)
    with store.tx() as db:
        row=tasks.owned(store,uid,'ses_multi',task['analysis_task_id']);payload=store.decrypt(row['payload_ciphertext'])
        payload['limits']['max_steps']=1
        db.execute('UPDATE analysis_tasks SET payload_ciphertext=? WHERE id=?',(store.encrypt(payload),row['id']))
    for index in range(2):
        current=tasks.view(store,uid,'ses_multi',task['analysis_task_id']);key=str(uuid.uuid4())
        signed=preview(store,uid,'ses_multi',{'analysis_task_id':task['analysis_task_id'],'context_version':current['context_version'],'step_request_id':key,'contract_version':'theft-provider-contract-v2','kind':'incidents','query':{'lon':'116.1','lat':'34.1','radius_m':500}},env[-1],1)
        req,spec=prepare(env,'theft-assistant','查询位置',client_request_id=key,provider_query={k:signed[k] for k in ('plan','confirmation')})
        if index==0:
            _,row,_=submit(env,req,spec);business_runs.set_state(store,row['id'],'failed','failed')
        else:
            before=len(store.rows('SELECT id FROM business_runs'))
            with pytest.raises(HTTPException) as exc:submit(env,req,spec)
            assert exc.value.detail['code']=='task_budget_exhausted'
            assert len(store.rows('SELECT id FROM business_runs'))==before
            assert not store.one('SELECT id FROM business_runs WHERE request_key=?',(key,))
