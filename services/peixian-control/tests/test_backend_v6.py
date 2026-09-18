import json
import pytest
import httpx
from control.store import Store, MAX_SCHEMA_VERSION
from control.schema import validate
from test_control import context, create_user, login_user, PASSWORD, P

@pytest.fixture
def v6(tmp_path,monkeypatch):
    monkeypatch.setenv('PX_BACKEND_V6','1')
    yield from context.__wrapped__(tmp_path,monkeypatch)


def test_v6_structure_and_reopen(v6,tmp_path):
    s,app,c=v6
    assert s.schema_version()==6
    with s.read() as db:validate(db)
    reopened=Store(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    assert reopened.schema_version()==6
    with s.tx() as db:db.execute('DROP INDEX runs_owner_created')
    with pytest.raises(ValueError,match='structure'):Store(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')


def test_department_profile_atomicity_and_roles(v6):
    s,app,c=v6
    d=c.post(P+'/admin/departments',json={'name':'DEMO Unit','code':'DEMO-UNIT'});assert d.status_code==201,d.text
    did=d.json()['id']
    child=c.post(P+'/admin/departments',json={'name':'DEMO Child','code':'DEMO-CHILD','parent_id':did}).json()['id']
    assert c.patch(P+'/admin/departments/'+did,json={'parent_id':child}).json()['code']=='department_cycle'
    assert c.delete(P+'/admin/departments/'+did).status_code==409
    user=c.post(P+'/admin/users',json={'username':'person-a','password':PASSWORD,'display_name':'DEMO Officer','department_id':did}).json()['user']
    assert user['department']['id']==did
    c.post(P+'/admin/users',json={'username':'manager','password':PASSWORD,'role':'admin'})
    manager=login_user(app,'manager')
    try:
        assert manager.get(P+'/admin/departments/tree').status_code==200
        assert manager.post(P+'/admin/departments',json={'name':'x','code':'x'}).status_code==403
        assert manager.patch(P+'/admin/users/'+user['id'],json={'department_id':None,'active':False}).status_code==403
        assert s.user(user['id'])['active']
        assert manager.get(P+'/admin/users/summary').json()['users']==1
    finally:manager.__exit__(None,None,None)
    a=login_user(app,'person-a')
    try:
        profile=a.get(P+'/me').json()['user']
        assert profile['system_role']=='user' and profile['last_login_at'].endswith('Z')
        assert a.get(P+'/admin/departments/tree').status_code==403
    finally:a.__exit__(None,None,None)


def test_model_fields_default_and_unsaved_test(v6):
    s,app,c=v6
    data={'name':'DEMO','base_url':'http://model/v1','model_id':'demo','api_key':'synthetic-secret','provider':'local','context_length':32000,'supports_tools':True,'is_default':True}
    response=c.post(P+'/admin/models',json=data);assert response.status_code==200,response.text
    assert response.json()['supports_tools'] and response.json()['context_length']==32000
    mid=response.json()['id'];assert 'synthetic-secret' not in response.text
    other=c.post(P+'/admin/models',json={**data,'name':'Other'}).json()['id']
    assert s.one('SELECT sum(is_default) AS n FROM models')['n']==1
    assert c.patch(P+'/admin/models/'+other,json={'enabled':False}).status_code==200
    assert s.one('SELECT is_default FROM models WHERE id=?',(other,))['is_default']==0
    old=app.state.http
    app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':[{'id':'demo'}]})))
    try:
        before=s.one('SELECT count(*) AS n FROM models')['n']
        result=c.post(P+'/admin/models/test',json=data);assert result.status_code==200,result.text
        assert result.json()['ok'] and isinstance(result.json()['elapsed_ms'],int)
        assert s.one('SELECT count(*) AS n FROM models')['n']==before
    finally:
        c.portal.call(app.state.http.aclose);app.state.http=old


@pytest.mark.parametrize('mode,version',[('eager',4),('on_demand',5)])
def test_offline_migration_preserves_accounts_and_rejects_unfrozen(tmp_path,monkeypatch,mode,version):
    from cryptography.fernet import Fernet
    monkeypatch.delenv('PX_BACKEND_V6',raising=False)
    for name,value in [('key',Fernet.generate_key()),('worker',b'x'*40),('admin',PASSWORD.encode())]:(tmp_path/name).write_bytes(value)
    args=(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    s=Store(*args,runtime_mode=mode)
    before=s.one("SELECT id,password,auth_version,role FROM users WHERE username='admin'")
    assert s.schema_version()==version
    monkeypatch.setenv('PX_BACKEND_V6','1')
    with pytest.raises(ValueError,match='frozen offline'):Store(*args)
    assert s.schema_version()==version
    monkeypatch.setenv('PX_ALLOW_V6_MIGRATION','1')
    with s.tx() as db:db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
    migrated=Store(*args)
    assert migrated.schema_version()==6
    assert migrated.one("SELECT id,password,auth_version,role FROM users WHERE username='admin'")==before
    assert migrated.maintenance_status()['maintenance_mode']=='frozen'
    assert Store(*args).schema_version()==6
    if mode=='on_demand':assert migrated.maintenance_status()['runtime_mode']=='on_demand'


def test_draft_generation_uses_client_request_identity_not_config_header():
    from control.idempotency import MUTATIONS
    assert not MUTATIONS.fullmatch(P+'/skill-drafts/from-requirement')
    assert not MUTATIONS.fullmatch(P+'/skill-drafts/from-session')
    assert MUTATIONS.fullmatch(P+'/skill-drafts/abc/save')
    assert MUTATIONS.fullmatch(P+'/skill-drafts/abc')
