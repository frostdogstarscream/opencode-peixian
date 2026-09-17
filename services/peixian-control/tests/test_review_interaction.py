import pytest
from test_runtime_pool import pool, account, begin
from control.runtime_view import interaction_view


@pytest.mark.parametrize('mode', ['normal','frozen','repair_only'])
@pytest.mark.parametrize('status', ['ready','draining','updating','paused','unprovisioned'])
def test_interaction_matrix(mode, status):
    view = interaction_view(dict(status=status,gate_policy='open'), True, mode)['interaction']
    assert view['can_submit_new'] == (mode == 'normal' and status == 'ready')
    assert view['can_observe'] == (mode != 'repair_only' and status in ('ready','draining'))
    assert view['can_continue'] == view['can_observe']


@pytest.mark.parametrize('flag', ['security_blocked','recovery_required'])
def test_restricted_activity_is_never_exposed(flag):
    assert not any(interaction_view(dict(status='draining',gate_policy='closed',**{flag:True}),True,'normal')['interaction'].values())


@pytest.mark.parametrize('mode', ['normal','frozen','repair_only'])
@pytest.mark.parametrize('waiting', [False, True])
def test_authenticated_maintenance_and_views(pool, mode, waiting):
    from client_helpers import TestClient
    from control.app import create_app
    from control.store import digest, now
    s, _ = pool
    uid = account(s)
    with s.tx() as db:
        db.execute('UPDATE users SET must_change=0 WHERE id=?',(uid,))
        db.execute('INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)',(digest('synthetic-token'),uid,'token','test',None,now()+600,1,now()))
    with TestClient(create_app(s)) as client:
        if waiting:
            with s.tx() as db:
                db.execute('UPDATE platform_state SET capacity_wait_enabled=1,pool_policy_version=2')
            begin(s, account(s,'holder-a'))
            begin(s, account(s,'holder-b'))
        client.headers['Authorization']='Bearer synthetic-token'
        prefix='/api/console/v1'
        assert client.post(prefix+'/me/runtime/start',json={}).status_code == 202
        with s.tx() as db:
            db.execute('UPDATE platform_state SET maintenance_mode=?',(mode,))
        state=client.get(prefix+'/me/runtime').json()
        assert bool(state['waiting']) == waiting
        me=client.get(prefix+'/me').json()
        assert state['maintenance_mode'] == mode
        assert me['user']['runtime']['interaction'] == state['interaction']
        assert ('stop' in state['allowed_actions']) == (mode == 'normal')
        jobs=s.rows('SELECT id,status,phase FROM jobs')
        response=client.post(prefix+'/me/runtime/stop',json={'expected_state_version':state['state_version']})
        if mode != 'normal':
            assert response.status_code == 503
            assert s.rows('SELECT id,status,phase FROM jobs') == jobs
        else:
            assert response.status_code == 200
