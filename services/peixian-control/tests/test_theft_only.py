import pytest
from fastapi import HTTPException
from test_multi_agent import multi, prepare, submit
from test_task_spec import task_env, v6
from control import task_spec, business_runs
from control.agents import runtime
from test_control import P


def test_catalog_default_and_retired_direct_endpoint(multi, monkeypatch):
    monkeypatch.setenv('PX_AGENT_MODE','theft_only')
    client=multi[3]; uid=multi[4]['uid']
    assert [x['id'] for x in client.get(P+'/agents').json()['items']]==['theft-assistant']
    assert client.get(P+'/agents/gambling-assistant').status_code==422
    assert client.get(P+'/agents/theft-assistant').status_code==200
    assert runtime.select(uid,{}).id=='theft-assistant'
    with pytest.raises(HTTPException) as e:runtime.select(uid,{'agent_id':'gambling-assistant'})
    assert e.value.detail['code']=='agent_retired'
    monkeypatch.delenv('PX_MULTI_AGENT_V1_UIDS')
    assert client.get(P+'/agents').json()['items']==[]
    with pytest.raises(HTTPException):runtime.select(uid,{})


def test_missing_id_freezes_theft_prompt_and_replays(multi,monkeypatch):
    monkeypatch.setenv('PX_AGENT_MODE','theft_only')
    request,task=prepare(multi,text='你能帮我做什么')
    request.pop('agent_id')
    task=task_spec.resolve(multi[0],multi[4]['uid'],'ses_multi',request,multi[7])
    receipt,row,snapshot=submit(multi,request,task)
    assert snapshot['agent_profile']['id']=='theft-assistant'
    assert '盗窃' in snapshot['payload']['system']
    assert '你是“涉赌案件资料助手”' not in snapshot['payload']['system']
    assert business_runs.replay(multi[0],multi[4]['uid'],'ses_multi',request)==receipt


def test_old_session_readable_not_relabelled(multi,monkeypatch):
    request,task=prepare(multi,'gambling-assistant','你好')
    receipt,row,snapshot=submit(multi,request,task)
    before=multi[0].one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext']
    monkeypatch.setenv('PX_AGENT_MODE','theft_only')
    with pytest.raises(HTTPException) as e:prepare(multi,'theft-assistant','你好')
    assert e.value.detail['code']=='session_agent_mismatch'
    response=multi[3].get(P+'/sessions/ses_multi/runs/'+row['id']+'/task')
    assert response.status_code==200
    assert response.json()['agent_profile']['id']=='gambling-assistant'
    assert multi[0].one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext']==before
    assert runtime.frozen_identity({'request':{}})=='gambling-assistant'


def test_invalid_policy_does_not_reopen_gambling(multi,monkeypatch):
    monkeypatch.setenv('PX_AGENT_MODE','typo')
    with pytest.raises(HTTPException) as e:runtime.select(multi[4]['uid'],{})
    assert e.value.status_code==503
