import json
import pytest
from fastapi import HTTPException
from test_backend_v6 import v6
from test_business_runs import setup_run
from test_r2_orchestration import state,account,complete
from control.orchestration import Orchestration
from control.worker_api import runtime_spec
from control import business_runs as runs
from control.run_api import attach_results
from control.source_display import describe


def test_attachment_freeze_rename_delete_and_cross_account(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    try:
        data['file_ids']=['file-demo']
        receipt=runs.submit(s,user,'ses_demo',data,payload,applied,1,attachments=[{'id':'file-demo','name':'资料.txt'}])
        def read(uid=user['uid'],sid='ses_demo'):
            return attach_results(s,uid,[{'info':{'id':receipt['message_id'],'role':'user'},'parts':[]}],sid)[0]['attachments']
        assert read()==[{'id':'file-demo','name':'资料.txt','status':'available'}]
        with s.tx() as db:db.execute('UPDATE files SET metadata=? WHERE uid=?',(json.dumps({'name':'renamed.txt'}),user['uid']))
        assert read()[0]['name']=='资料.txt'
        assert read('other')==[] and read(sid='other-session')==[]
        with s.tx() as db:db.execute('DELETE FROM files WHERE uid=?',(user['uid'],))
        assert read()[0]['status']=='unavailable'
        assert runs.replay(s,user['uid'],'ses_demo',data)==receipt
    finally:client.__exit__(None,None,None)


def test_legacy_attachment_does_not_parse_hidden_prompt(v6):
    from control.message_attachments import project,filename
    s,app,c=v6
    assert project(s,'someone',{'request':{'file_ids':['unknown']},'payload':{'text':'文件 secret-name'}})==[]
    assert filename('C:/private/资料.txt')=='资料.txt'


def test_failed_recovery_retry_preserves_snapshot_and_safety(state):
    s,engine,clock,args=state;uid=account(state)
    initial=engine.claim(runtime_spec);job=initial['job']
    with s.tx() as db:
        db.execute("UPDATE jobs SET status='failed',phase='finished',recovery_required=1 WHERE id=?",(job['id'],))
        db.execute("UPDATE runtimes SET recovery_required=1,gate_policy='closed' WHERE uid=?",(uid,))
        db.execute("UPDATE platform_state SET maintenance_mode='repair_only'")
    version=s.one('SELECT state_version FROM runtimes WHERE uid=?',(uid,))['state_version']
    actor=s.one("SELECT id FROM users WHERE role='super_admin'")['id']
    assert engine.retry_recovery(uid,version,actor)['job']['id']==job['id']
    with pytest.raises(HTTPException):engine.retry_recovery(uid,version,actor)
    replacement=engine.claim(runtime_spec)
    assert replacement['spec']==initial['spec']
    assert replacement['job']['attempt']==job['attempt']+1
    assert replacement['job']['phase']=='reconciling'
    assert s.one('SELECT recovery_required,gate_policy FROM runtimes WHERE uid=?',(uid,))=={'recovery_required':1,'gate_policy':'closed'}


def test_rich_discoveries_only_describe_supplied_rows():
    rows=[{'record_id':'a','occurred_at':'2026-09-22T23:00:00+08:00','direction':'in'},
          {'record_id':'b','occurred_at':'2026-09-22T16:00:00Z','direction':'out'},
          {'record_id':'c','occurred_at':None}]
    value=describe('funds','资金流水','取得3条原始资金流水。',rows,'已确认时段',['不推断用途。'])
    assert value['headline']!=value['summary']
    assert len(value['discoveries'])==4
    assert '2 个北京时间自然日' in value['discoveries'][1]
    assert '收入 1 条、支出 1 条' in value['discoveries'][2]
    assert all(set(x['source_ids'])<={'a','b','c'} for x in value['discovery_details'])
    assert '1 条记录未提供' in value['summary']


def test_exit_repair_requires_fresh_applied_reconciliation(state):
    from test_r2_orchestration import applying, observation
    from control.store import ident
    s,engine,clock,args=state;uid=account(state)
    original=engine.claim(runtime_spec);job=original['job'];applying(engine,job)
    engine.boot(job['id'],{'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident(),'runtime_id':job['runtime_id'],'gateway_boot_id':'gateway','relay_boot_id':'relay'})
    with s.tx() as db:
        db.execute("UPDATE platform_state SET maintenance_mode='repair_only'")
        db.execute("UPDATE runtimes SET error='runtime_operation_failed' WHERE uid=?",(uid,))
    complete(engine,job,ok=True,observation_id=observation(engine,job,running=True,boot='gateway'))
    assert s.one('SELECT status,error FROM runtimes WHERE uid=?',(uid,))=={'status':'draining','error':None}
    actor=s.one("SELECT id FROM users WHERE role='super_admin'")['id']
    engine.maintenance('normal',s.maintenance_status()['state_version'],actor)
    row=s.one('SELECT gate_policy,recovery_required,desired,revision FROM runtimes WHERE uid=?',(uid,))
    assert row=={'gate_policy':'closed','recovery_required':1,'desired':job['revision'],'revision':job['revision']}
    recovery=engine.claim(runtime_spec)
    assert recovery['job']['phase']=='reconciling' and recovery['spec']==original['spec']


def test_credit_debit_are_explicit_directions():
    rows=[{'record_id':'credit-source','direction':'credit','amount_minor':12800,'occurred_at':'2026-09-14T20:14:00+08:00'},
          {'record_id':'debit-source','direction':'debit','amount_minor':12600,'occurred_at':'2026-09-14T20:17:00+08:00'}]
    value=describe('funds','资金流水','取得2条。',rows,'已确认时段',[])
    assert '收入 1 条、支出 1 条；方向未明确 0 条' in value['discoveries'][2]
