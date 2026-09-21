import copy,json,uuid,sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from test_control import context,P,create_user,login_user
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from test_clarifications import data,ticket,choose,v6
from test_task_context import current,complete_data
from control import task_context,business_runs as runs
from control.agents.registry import require

@pytest.mark.parametrize('layer',['control','gateway'])
@pytest.mark.parametrize('tamper',['plan_target','scene_subject','scene_filter'])
def test_runtime_target_tampering_rejected(multi,layer,tamper):
    from control.agents.runtime import validate_execution
    from shared.developer_plan import validate
    data(multi);cid,view=ticket(multi);assert choose(multi,cid,view)[0].status_code==200
    request,task=prepare(multi,'theft-assistant','继续');_,row,snap=submit(multi,request,task)
    broken=copy.deepcopy(snap);plan=broken['facts_plan']
    if tamper=='plan_target':plan['task_target']['target_refs']=['未选择车辆']
    if tamper=='scene_subject':plan['scenario']['subject_ref']='未选择车辆'
    if tamper=='scene_filter':plan['scenario']['target_filter']['ref']='未选择车辆'
    if layer=='control':
        with pytest.raises(HTTPException):validate_execution(broken)
    else:
        with pytest.raises(ValueError):validate(plan)

@pytest.mark.parametrize('version',[4,6])
def test_migration_chain_tampering_rejected(multi,version):
    from control.schema import validate
    s=multi[0]
    with s.tx() as db:db.execute("UPDATE schema_migrations SET script_digest='wrong' WHERE to_version=?",(version,))
    with s.read() as db:
        with pytest.raises(ValueError):validate(db)

@pytest.mark.parametrize('text',['他','这个人','这两个人','那辆车','这个账户'])
def test_bare_pronoun_is_local_clarification(multi,text):
    request,task=prepare(multi,'theft-assistant',text);_,row,snap=submit(multi,request,task)
    assert row['status']=='completed' and snap.get('task_response')
    assert not multi[0].one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))


def test_stage_workflows_are_scoped():
    root=Path(__file__).resolve().parents[3]
    for p in (root/'.github/workflows').glob('peixian-stage2*.yml'):
        text=p.read_text()
        assert "github.event_name != 'pull_request'" in text and 'github.head_ref ==' in text,p.name

@pytest.fixture
def legacy(tmp_path,monkeypatch):
    monkeypatch.setenv('PX_BACKEND_V6','0');monkeypatch.delenv('PX_TASK_CONTEXT_V1',raising=False);monkeypatch.delenv('PX_TASK_CLARIFICATION_V1',raising=False)
    yield from context.__wrapped__(tmp_path,monkeypatch)

def test_legacy_source_endpoint_is_404(legacy):
    create_user(legacy[2],'legacy-person');client=login_user(legacy[1],'legacy-person')
    try:assert client.get(P+'/sessions/unknown/runs/unknown/source').status_code==404
    finally:client.__exit__(None,None,None)


@pytest.mark.parametrize('kind',['capabilities','rules'])
def test_disabled_registry_preserves_history_but_blocks_new(multi,monkeypatch,kind):
    from control.developer_registry import registry
    rid=complete_data(multi)
    docs=registry.REGISTRY.documents()
    for entry in docs[kind]:entry['state']='disabled'
    monkeypatch.setattr(registry,'REGISTRY',registry.Registry(**docs))
    request,task=prepare(multi,'gambling-assistant','解释上一条结果')
    assert task['historical_projection']['source_data_run_id']==rid and task['local'] is None
    _,row,snapshot=submit(multi,request,task)
    assert not snapshot.get('facts_plan') and snapshot['allowed_tools']==[]
    runs.set_state(multi[0],row['id'],'completed','completed')
    request,task=prepare(multi,'gambling-assistant','看看资金')
    assert task['local']['code']==('capability_not_ready' if kind=='capabilities' else 'rule_not_ready')
    _,row,_=submit(multi,request,task)
    assert row['status']=='completed' and not multi[0].one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))


def test_revoked_resolved_vehicle_not_queried(multi):
    data(multi);cid,view=ticket(multi);assert choose(multi,cid,view)[0].status_code==200
    with multi[0].tx() as db:db.execute("DELETE FROM grants WHERE uid=? AND kind='plugin' AND resource='peixian-records-vehicle'",(multi[4]['uid'],))
    with pytest.raises(HTTPException):
        request,task=prepare(multi,'theft-assistant','继续');submit(multi,request,task)
    assert not multi[0].one("SELECT 1 FROM business_runs WHERE status='queued'")


def test_control_rejects_snapshot_target_disagreement(multi):
    from control.agents.runtime import validate_execution
    request,task=prepare(multi,'gambling-assistant','看看资金');_,_,snap=submit(multi,request,task)
    validate_execution(snap)
    snap['task_target']['target_refs']=['未确认对象']
    with pytest.raises(HTTPException):validate_execution(snap)


@pytest.mark.parametrize('state',['contract_only','disabled'])
def test_unadapted_calls_is_explicitly_unavailable(multi,monkeypatch,state):
    from control.developer_registry import registry
    docs=registry.REGISTRY.documents()
    next(x for x in docs['capabilities'] if x['id']=='records.calls')['state']=state
    monkeypatch.setattr(registry,'REGISTRY',registry.Registry(**docs))
    request,task=prepare(multi,'gambling-assistant','查询话单')
    assert task['local']['code']=='capability_not_ready'
    _,row,snap=submit(multi,request,task)
    assert row['status']=='completed' and not snap.get('facts_plan')
    assert not multi[0].one('SELECT 1 FROM run_deliveries WHERE run_id=?',(row['id'],))
