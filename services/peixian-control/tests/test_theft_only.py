import pytest
import httpx
import uuid
from fastapi import HTTPException
from test_multi_agent import multi, prepare, submit
from test_task_spec import task_env, v6
from control import task_spec, business_runs
from control import task_router, run_api
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
    assert '涉赌' not in snapshot['payload']['system']
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


def test_scope_prompt_has_no_retired_scene_options(monkeypatch):
    from control.scenario_context import instruction
    monkeypatch.setenv('PX_AGENT_MODE','theft_only')
    value=instruction({'scenario_id':None})
    assert '当前平台仅开放盗窃资料助手' in value
    assert '请只询问涉赌资料或盗窃' not in value
    assert '只询问盗窃资料查询所需信息' in value


def test_unset_policy_defaults_to_theft_without_dual_prompt(monkeypatch):
    from control.scenario_context import instruction
    monkeypatch.delenv('PX_AGENT_MODE', raising=False)
    assert runtime.active_ids()==('theft-assistant',)
    value=instruction({'scenario_id':None})
    assert '盗窃资料助手' in value
    assert '涉赌' not in value
    assert '选择' in value
    from control.agents.registry import require
    assert '涉赌' not in require('theft-assistant').prompt


def test_explicit_theft_profile_never_asks_for_two_scenes(monkeypatch):
    from control.scenario_context import instruction
    from control.agents.registry import require
    monkeypatch.setenv('PX_AGENT_MODE','dual')
    value=instruction({'scenario_id':None},require('theft-assistant'))
    assert '盗窃资料助手' in value
    assert '涉赌' not in value


@pytest.mark.parametrize('prompt', ['你好', '您好！', '你能帮我做什么？', '你是谁？'])
def test_intro_is_persisted_locally_without_model_or_old_assistant(multi, monkeypatch, prompt):
    monkeypatch.setenv('PX_AGENT_MODE', 'theft_only')
    request, task = prepare(multi, text=prompt)
    assert task_router.introduction(prompt)
    assert task['spec'] is None
    assert task['local']['code'] == 'assistant_introduction'
    assert '盗窃资料助手' in task['local']['message']
    assert '涉赌' not in task['local']['message']
    receipt, row, snapshot = submit(multi, request, task)
    assert row['status'] == 'completed' and row['phase'] == 'introduction'
    assert snapshot['task_response'] == task['local']
    assert multi[0].one('SELECT * FROM run_deliveries WHERE run_id=?', (receipt['run_id'],)) is None
    messages = run_api.attach_results(multi[0], multi[4]['uid'], [], 'ses_multi')
    assert [m['parts'][0]['text'] for m in messages if m['info']['role'] == 'assistant'] == [task['local']['message']]


def test_intro_does_not_intercept_query(multi, monkeypatch):
    monkeypatch.setenv('PX_AGENT_MODE', 'theft_only')
    assert not task_router.introduction('你好，查一下这条警情附近的记录')
    assert not task_router.introduction('盗窃警情可以查什么？')
    assert not task_router.introduction('请整理盗窃时空资料')


def test_http_intro_bypasses_enabled_planner_and_restores_reply(multi, monkeypatch):
    monkeypatch.setenv('PX_AGENT_MODE', 'theft_only')
    from control import theft_planner
    monkeypatch.setattr(theft_planner, 'enabled', lambda _store, _uid: True)
    store, app, _, client, user, data, _, _ = multi
    calls = []
    previous = app.state.http
    def transport(request):
        calls.append((request.method, request.url.path))
        if '/internal/runtime/runs/' in request.url.path:
            return httpx.Response(200, json={'protocol': 'durable_run_v1', 'receipt': None})
        if request.url.path.endswith('/message'):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={'id': 'ses_intro', 'directory': '/workspace'})
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        body = {**data, 'text': '你好', 'agent_id': 'theft-assistant', 'client_request_id': str(uuid.uuid4())}
        response = client.post(P + '/sessions/ses_intro/messages', json=body)
        assert response.status_code == 202, response.text
        assert client.post(P + '/sessions/ses_intro/messages', json=body).json() == response.json()
        retired = client.post(P + '/sessions/ses_intro/messages', json={**body, 'text': '切换到赌博场景', 'client_request_id': str(uuid.uuid4())})
        assert retired.status_code == 422 and retired.json()['code'] == 'scenario_retired'
        row = business_runs.owned(store, user['uid'], 'ses_intro', response.json()['run_id'])
        assert row['status'] == 'completed' and row['phase'] == 'introduction'
        assert all(method == 'GET' for method, _ in calls)
        messages = client.get(P + '/sessions/ses_intro/messages')
        assert messages.status_code == 200
        assert '盗窃资料助手' in str(messages.json())
        assert '涉赌' not in str(messages.json())
    finally:
        client.portal.call(app.state.http.aclose)
        app.state.http = previous
