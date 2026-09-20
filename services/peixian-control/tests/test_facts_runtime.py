import copy
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from test_backend_v6 import v6
from test_business_runs import setup_run
from control import business_runs as runs
from control.facts_runtime import FactsState, VERSION, capability, tool
from control.store import Store
from control.scenario_versions import DATA151

@pytest.fixture
def facts(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    c.portal.call(app.state.run_coordinator.close)
    pid=capability('night')
    plugin={'id':pid,'version':'1.0.0','manifest':{'tools':[tool('night')]},'options':{}}
    applied['plugins']=[plugin]
    with s.tx() as db:
        db.execute("INSERT INTO plugins(id,version,name,description,manifest,path,digest,enabled) VALUES(?,?,?,?,?,?,?,1)",(pid,'1.0.0','Night','',json.dumps(plugin['manifest']),'not-used','0'*64))
        db.execute("INSERT INTO installs(uid,plugin,version,enabled,config) VALUES(?,?,?,1,?)",(user['uid'],pid,'1.0.0',s.encrypt({})))
        db.execute("INSERT INTO grants VALUES(?,'plugin',?)",(user['uid'],pid))
        db.execute("UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?",(s.encrypt(applied),user['uid']))
    rid=runs.submit(s,user,'ses_facts',data,payload,applied,1)['run_id']
    with s.tx() as db:
        row=db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,)).fetchone()
        snapshot=s.decrypt(row[0]);snapshot['facts_plan']={'coordinator_version':VERSION,'methods':['night'],'modules':['night'],'allowed_capabilities':[pid],'allowed_tools':[tool('night')],'records':{'night':copy.deepcopy(DATA151['records']['night'])}}
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snapshot),rid))
    yield s,user['uid'],rid,FactsState(s,'boot-one')
    client.__exit__(None,None,None)

def response():
    value=copy.deepcopy(DATA151['records']['night']);value['items']=value.pop('records');return value

def test_persistent_pending_is_unknown_after_reopen_and_never_reserved_again(facts,tmp_path):
    s,uid,rid,state=facts
    op=state.begin(uid,rid,1);assert state.reserve(uid,rid,1,op,'night')
    reopened=Store(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    resumed=FactsState(reopened,'boot-two');nextop=resumed.begin(uid,rid,1)
    assert resumed.read(uid,rid,1)['state']['modules']['night']['status']=='unknown'
    assert not resumed.reserve(uid,rid,1,nextop,'night')
    with pytest.raises(HTTPException):state.complete(uid,rid,1,op,'night','completed',response())
    assert s.one("SELECT status FROM run_events WHERE run_id=? AND event_key='facts.night'",(rid,))['status']=='unknown'

def test_completed_cached_replay_preserves_snapshot_and_audit(facts):
    s,uid,rid,state=facts;op=state.begin(uid,rid,1)
    state.reserve(uid,rid,1,op,'night');assert state.complete(uid,rid,1,op,'night','completed',response())=='completed'
    state.finish(uid,rid,1,op)
    again=state.begin(uid,rid,1);assert not state.reserve(uid,rid,1,again,'night')
    assert state.read(uid,rid,1)['state']['modules']['night']['response']==response()
    assert s.one("SELECT count(*) AS n FROM run_events WHERE run_id=?",(rid,))['n']==1
    assert json.loads(s.one('SELECT actual_plugins FROM invocations WHERE run_id=?',(rid,))['actual_plugins'])==[capability('night')]
    encrypted=s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))['request_ciphertext']
    assert response()['snapshot_id'] not in encrypted

def test_only_one_durable_operation_can_claim(facts):
    _,uid,rid,state=facts
    def begin(_):
        try:return state.begin(uid,rid,1)
        except HTTPException:return None
    with ThreadPoolExecutor(max_workers=6) as pool:values=list(pool.map(begin,range(6)))
    assert sum(v is not None for v in values)==1

@pytest.mark.parametrize('change',['cancel','grant','disabled','revision','unknown-module','cross-user'])
def test_pre_admission_denial_does_not_reserve(facts,change):
    s,uid,rid,state=facts;op=state.begin(uid,rid,1)
    with s.tx() as db:
        if change=='cancel':db.execute('UPDATE business_runs SET cancel_requested=1 WHERE id=?',(rid,))
        if change=='grant':db.execute('DELETE FROM grants WHERE uid=?',(uid,))
        if change=='disabled':db.execute('UPDATE users SET active=0 WHERE id=?',(uid,))
        if change=='revision':db.execute('UPDATE runtimes SET revision=2 WHERE uid=?',(uid,))
    with pytest.raises(HTTPException):state.reserve('other' if change=='cross-user' else uid,rid,1,op,'funds' if change=='unknown-module' else 'night')
    assert not state.read(uid,rid,1)['state']['modules']

def test_revoke_after_response_cannot_publish_facts(facts):
    s,uid,rid,state=facts;op=state.begin(uid,rid,1);state.reserve(uid,rid,1,op,'night')
    with s.tx() as db:db.execute('DELETE FROM grants WHERE uid=?',(uid,))
    assert state.complete(uid,rid,1,op,'night','completed',response())=='rejected'
    state.finish(uid,rid,1,op)
    value=state.read(uid,rid,1)['state']['modules']['night']
    assert value['status']=='rejected' and 'response' not in value and value['withheld_response']==response()

def test_invalid_snapshot_is_rejected_and_never_retried(facts):
    _,uid,rid,state=facts;op=state.begin(uid,rid,1);state.reserve(uid,rid,1,op,'night')
    value=response();value['snapshot_id']='wrong'
    assert state.complete(uid,rid,1,op,'night','completed',value)=='rejected'
    assert not state.reserve(uid,rid,1,op,'night')
    assert 'response' not in state.read(uid,rid,1)['state']['modules']['night']

def test_exact_claims_use_saved_table_and_keep_unknown_missing(facts):
    _,uid,rid,state=facts;op=state.begin(uid,rid,1)
    table={'scenario_id':'DEMO-CASE-GAMBLING','scenario_snapshot_id':'scene','records_snapshot_id':'records','data_status':'partial','facts':[{'fact_id':'gap','statement':'未取得资料，不能视为零','source_ids':[]}],'missing':['资料未取得']}
    state.save_table(uid,rid,1,op,table)
    approved=state.check_claims(uid,rid,1,op,table['facts'])
    assert len(approved['approved'])==1 and approved['data_status']=='partial'
    bad=state.check_claims(uid,rid,1,op,[{**table['facts'][0],'statement':'没有记录'}])
    assert not bad['approved'] and bad['rejected']


def test_cancel_terminal_preserves_unknown_and_never_invents_remote_undo(facts):
    s,uid,rid,state=facts;op=state.begin(uid,rid,1);state.reserve(uid,rid,1,op,'night')
    with s.tx() as db:db.execute('UPDATE business_runs SET cancel_requested=1 WHERE id=?',(rid,))
    state.terminate(uid,rid,1)
    assert state.read(uid,rid,1)['state']['modules']['night']['status']=='unknown'

def test_cancel_before_call_records_cancelled(facts):
    s,uid,rid,state=facts
    with s.tx() as db:db.execute('UPDATE business_runs SET cancel_requested=1 WHERE id=?',(rid,))
    state.terminate(uid,rid,1)
    assert state.read(uid,rid,1)['state']['modules']['night']['status']=='cancelled'

def test_tool_drift_is_audited_and_cannot_become_evidence(facts):
    from control.run_scheduler import track_messages
    s,uid,rid,_=facts;row=s.one('SELECT * FROM business_runs WHERE id=?',(rid,))
    values=[{'info':{'id':row['message_id'],'role':'user','time':{'created':1000}},'parts':[]},
      {'info':{'id':'msg_a','role':'assistant','time':{'created':1000,'completed':2000},'finish':'stop'},
       'parts':[{'id':'tool_bad','type':'tool','tool':'bash','state':{'status':'completed','time':{'start':1000,'end':2000}}}]}]
    assert track_messages(s,row,values,{})
    updated=s.one('SELECT * FROM business_runs WHERE id=?',(rid,))
    assert updated['status']=='failed' and updated['result_ciphertext'] is None
    assert s.decrypt(updated['evidence_ciphertext'])['cards']==[]
    assert s.one("SELECT status FROM run_events WHERE run_id=? AND event_key='plan-denied.tool_bad'",(rid,))['status']=='rejected'
