import hashlib,json,uuid
import pytest
from fastapi import HTTPException
from test_task_spec import task_env,v6
from control import business_runs as runs,task_spec
from control.agents import registry,runtime


def test_profile_and_final_prompt_frozen(task_env,monkeypatch):
    s,app,c,client,user,data,payload,applied=task_env
    monkeypatch.setenv('PX_TASKSPEC_V1_UIDS',user['uid']);monkeypatch.setenv('PX_MULTI_AGENT_V1_UIDS',user['uid'])
    task=task_spec.resolve(s,user['uid'],'ses_profile',data,applied)
    receipt=runs.submit(s,user,'ses_profile',data,payload,applied,1,context=task['context'],task=task)
    row=runs.owned(s,user['uid'],'ses_profile',receipt['run_id']);before=row['request_ciphertext'];snap=s.decrypt(before)
    assert snap['agent_profile']==registry.require('gambling-assistant').snapshot()
    assert registry.require('gambling-assistant').prompt in snap['payload']['system']
    assert snap['effective_system_prompt_sha256']==hashlib.sha256(snap['payload']['system'].encode()).hexdigest()
    assert runs.replay(s,user['uid'],'ses_profile',data)==receipt
    assert runs.owned(s,user['uid'],'ses_profile',receipt['run_id'])['request_ciphertext']==before
    assert runtime.frozen_identity({'request':{}})=='gambling-assistant'
    assert runtime.frozen_identity({'request':{'agent_id':'unrecognised'}}) is None


def test_gambling_registry_api_and_legacy_snapshot_read(task_env):
    s,app,c,client,user,data,payload,applied=task_env
    assert client.get('/api/console/v1/agents').json()['items']==[registry.require('gambling-assistant').public()]
    assert client.get('/api/console/v1/agents/gambling-assistant').status_code==200
    assert client.get('/api/console/v1/agents/unknown').status_code==422
    receipt=runs.submit(s,user,'ses_legacy',data,payload,applied,1)
    row=runs.owned(s,user['uid'],'ses_legacy',receipt['run_id']);snapshot=s.decrypt(row['request_ciphertext']);snapshot.pop('agent_profile')
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snapshot),row['id']))
    before=runs.owned(s,user['uid'],'ses_legacy',row['id'])['request_ciphertext']
    runtime.session(s,user['uid'],'ses_legacy',registry.require('gambling-assistant'))
    assert client.get('/api/console/v1/sessions/ses_legacy/runs/'+row['id']+'/task').json()['agent_profile'] is None
    assert runs.owned(s,user['uid'],'ses_legacy',row['id'])['request_ciphertext']==before
