import hashlib
import uuid
import pytest
from fastapi import HTTPException
from test_backend_v6 import v6
from test_business_runs import setup_run
from control import scenario_context as sc, business_runs as runs

def configured(v6,monkeypatch):
    values=setup_run(v6);s,app,c,client,user,data,payload,applied=values
    for sid,scene in [('skill-g','DEMO-CASE-GAMBLING'),('skill-t','DEMO-CASE-THEFT')]:
        content='controlled '+sid
        monkeypatch.setitem(sc.REGISTRY,hashlib.sha256(content.encode()).hexdigest(),scene)
        with s.tx() as db:db.execute('INSERT INTO skills VALUES(?,?,?,?,?,?,?,?)',(sid,user['uid'],'renamed '+sid,'',content,1,1,'[]'))
        applied['skills'].append({'id':sid,'name':'renamed '+sid,'content':content,'version':1})
    with s.tx() as db:db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(s.encrypt(applied),user['uid']))
    return values

def test_inherit_switch_replay_reset_and_isolation(v6,monkeypatch):
    s,app,c,client,user,data,payload,applied=configured(v6,monkeypatch)
    try:
        data={**data,'text':'分析涉赌资料'}
        ctx=sc.resolve(s,user['uid'],'ses_ctx',data,applied)
        assert ctx['effective_skill_ids']==['skill-g']
        receipt=runs.submit(s,user,'ses_ctx',data,payload,applied,1,context=ctx)
        runs.set_state(s,receipt['run_id'],'completed','completed')
        for question in ['继续','看看资金','同行的是谁','把依据展开']:
            assert sc.resolve(s,user['uid'],'ses_ctx',{**data,'text':question},applied)['scenario_id']=='DEMO-CASE-GAMBLING'
        assert sc.resolve(s,user['uid'],'ses_ctx',{**data,'text':'改为盗窃场景'},applied)['scenario_id']=='DEMO-CASE-THEFT'
        assert sc.current(s,user['uid'],'new-session')['scenario_id'] is None
        assert sc.current(s,'another-account','ses_ctx')['scenario_id'] is None
        high=s.one('SELECT max(rowid) AS n FROM business_runs')['n']
        s.audit(user['uid'],sc.RESET+str(high),'ses_ctx')
        assert sc.current(s,user['uid'],'ses_ctx')['scenario_id'] is None
        assert runs.replay(s,user['uid'],'ses_ctx',data)==receipt
        with pytest.raises(HTTPException) as e:runs.submit(s,user,'ses_ctx',{**data,'client_request_id':str(uuid.uuid4())},payload,applied,1,context=ctx)
        assert e.value.detail['code']=='scenario_context_changed'
    finally:client.__exit__(None,None,None)

def test_conflicts_unsupported_and_revocation(v6,monkeypatch):
    s,app,c,client,user,data,payload,applied=configured(v6,monkeypatch)
    try:
        with pytest.raises(HTTPException):sc.resolve(s,user['uid'],'s',{**data,'text':'分析盗窃','skill_ids':['skill-g']},applied)
        for text in ['分析涉赌，查询身份证号','分析涉赌，近30天','分析涉赌，换一个人']:
            with pytest.raises(HTTPException) as e:sc.resolve(s,user['uid'],'s',{**data,'text':text},applied)
            assert e.value.detail['code']=='scenario_scope_unsupported'
        with s.tx() as db:db.execute('UPDATE skills SET enabled=0 WHERE id=?',('skill-g',))
        with pytest.raises(HTTPException):sc.resolve(s,user['uid'],'s',{**data,'text':'分析涉赌'},applied)
        assert not s.one('SELECT count(*) AS n FROM business_runs')['n']
    finally:client.__exit__(None,None,None)

def test_display_name_not_a_binding_and_user_quotes_not_directives():
    assert sc.skill_scenario({'name':'涉赌案件资料整理','content':'user text'}) is None
    assert sc.explicit('解释“改为盗窃场景”这句话')==set()
    assert '简体中文' in sc.LANGUAGE and '原始编号' in sc.LANGUAGE

def test_clear_endpoint_is_durable_idempotent_and_account_owned(v6,monkeypatch):
    import httpx
    from test_control import P
    s,app,c,client,user,data,payload,applied=configured(v6,monkeypatch)
    old=app.state.http
    def transport(request):
        if request.url.path.endswith('/ses_ctx'):return httpx.Response(200,json={'id':'ses_ctx','directory':'/workspace'})
        return httpx.Response(404,json={})
    app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        ctx=sc.resolve(s,user['uid'],'ses_ctx',{**data,'text':'分析涉赌'},applied)
        accepted=runs.submit(s,user,'ses_ctx',data,payload,applied,1,context=ctx)
        assert client.delete(P+'/sessions/ses_ctx/context',headers={'Idempotency-Key':str(uuid.uuid4())}).status_code==409
        runs.set_state(s,accepted['run_id'],'completed','completed')
        key=str(uuid.uuid4())
        a=client.delete(P+'/sessions/ses_ctx/context',headers={'Idempotency-Key':key})
        assert a.status_code==200,a.text
        assert a.json()['scenario_id'] is None
        b=client.delete(P+'/sessions/ses_ctx/context',headers={'Idempotency-Key':key})
        assert b.json()==a.json()
        assert client.get(P+'/sessions/ses_ctx/context').json()['scenario_id'] is None
        assert client.get(P+'/sessions/unknown/context').status_code==404
        assert s.one("SELECT count(*) AS n FROM audit WHERE action LIKE 'session.context.reset.%'")['n']==1
    finally:
        c.portal.call(app.state.http.aclose);app.state.http=old;client.__exit__(None,None,None)

def test_message_admission_freezes_context_and_system_language(v6,monkeypatch):
    import httpx
    from test_control import P
    s,app,c,client,user,data,payload,applied=configured(v6,monkeypatch)
    c.portal.call(app.state.run_coordinator.close)
    old=app.state.http
    def transport(request):
        if request.url.path.endswith('/message'):return httpx.Response(200,json=[])
        if '/internal/runtime/runs/' in request.url.path:return httpx.Response(200,json={'protocol':'durable_run_v1'})
        return httpx.Response(200,json={'id':'ses_ctx','directory':'/workspace'})
    app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        data={**data,'text':'分析涉赌资料'}
        result=client.post(P+'/sessions/ses_ctx/messages',json=data)
        assert result.status_code==202,result.text
        snap=s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(result.json()['run_id'],))['request_ciphertext'])
        assert '简体中文' in snap['payload']['system']
        assert snap['scenario_context']['scenario_id']=='DEMO-CASE-GAMBLING'
        assert snap['scenario_context']['effective_skill_ids']==['skill-g']
        assert snap['request']['skill_ids']==[]
        from control.gambling_agent import PROMPT
        assert PROMPT in snap['payload']['system']
        assert snap['scenario_context']['agent']['id']=='gambling-assistant'
        assert snap['scenario_context']['agent']['skills'][0]['id']=='skill-g'
        assert any('controlled skill-g' in part['text'] for part in snap['payload']['parts'])
        assert not snap['payload']['tools']['read']
        assert not snap['payload']['tools']['skill']
        assert 'peixian_prepare_scenario_facts' not in snap['payload']['tools']
        assert client.post(P+'/sessions/ses_ctx/messages',json=data).json()==result.json()
    finally:
        c.portal.call(app.state.http.aclose);app.state.http=old;client.__exit__(None,None,None)


def test_explicit_agent_scope_and_validation(v6,monkeypatch):
    s,app,c,client,user,data,payload,applied=configured(v6,monkeypatch)
    try:
        data=runs.normalized({**data,'text':'继续整理','agent_id':'gambling-assistant'})
        ctx=sc.resolve(s,user['uid'],'new',data,applied)
        assert ctx['scenario_id']=='DEMO-CASE-GAMBLING'
        assert ctx['effective_skill_ids']==['skill-g']
        for extra in [{'text':'分析盗窃资料'},{'skill_ids':['skill-t']}]:
            with pytest.raises(HTTPException) as e:sc.resolve(s,user['uid'],'new',{**data,**extra},applied)
            assert e.value.detail['code']=='agent_scenario_conflict'
        for bad in ['admin',None,{},['gambling-assistant']]:
            with pytest.raises(HTTPException):runs.normalized({**data,'agent_id':bad})
        with s.tx() as db:db.execute('UPDATE skills SET enabled=0 WHERE id=?',('skill-g',))
        with pytest.raises(HTTPException):sc.resolve(s,user['uid'],'new',data,applied)
    finally:client.__exit__(None,None,None)
