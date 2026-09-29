"""Interface switches, request-path rewrites and account/password login connections."""
import asyncio
import json

import httpx
import pytest

from control.connections import connection_extras, connection_headers
from control.store import encode
from shared import connection_policy
from shared.connection_policy import ConnectionFailure, exchange, policy, rewritten
from test_control import context, P

BASE = {'name': 'fixture', 'base_url': 'http://provider.test', 'auth_type': 'none', 'header_name': '', 'enabled': True,
        'allowed_methods': ['GET', 'POST'], 'timeout_seconds': 5, 'max_response_bytes': 65536}


def bind(store, kind, config, secret=''):
    pid = 'peixian-theft-' + kind.replace('_', '-')
    cid = 'conn-' + kind.replace('_', '-')
    with store.tx() as db:
        db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)', (pid, '3.0.0', kind, '', encode({'id': pid}), '/dev/null', 'd' * 64))
        db.execute('INSERT INTO connections VALUES(?,?,?,1)', (cid, encode(policy(config)), store.encrypt(secret)))
        db.execute('INSERT INTO plugin_connections VALUES(?,?,?,?)', (pid, '3.0.0', 'provider', cid))
    return cid


def test_rewrites_keep_contract_paths_and_the_person_segment():
    connection = {'path_rewrites': [['/jq/search', '/api/jq/search'], ['/caputer/profile/{person}', '/v2/profile/{person}']]}
    assert rewritten(connection, '/jq/search') == '/api/jq/search'
    assert rewritten(connection, '/caputer/profile/990000200001010014') == '/v2/profile/990000200001010014'
    assert rewritten(connection, '/caputer/profile/a/b') == '/caputer/profile/a/b'
    assert rewritten(connection, '/jq/capture') == '/jq/capture'
    for bad in ([['/jq/search', '/x/{person}']], [['/jq/search', '/../x']], [['/p/{person}', '/q/{person}/r']], [['/a', '/b'], ['/a', '/c']]):
        with pytest.raises(ConnectionFailure):
            policy({**BASE, 'allowed_paths': ['/jq/search'], 'path_rewrites': bad})


def test_endpoint_listing_and_path_update(context):
    store, app, admin = context
    cid = bind(store, 'incidents', {**BASE, 'allowed_paths': ['/jq/search']})
    bind(store, 'profile', {**BASE, 'auth_type': 'bearer', 'allowed_paths': ['/caputer/profile/*']}, 'fixture-token-value')
    items = {item['key']: item for item in admin.get(P + '/admin/provider-endpoints').json()['items']}
    assert set(items) >= {'incidents', 'profile', 'warnings', 'warnings_phone'}
    assert items['incidents']['path'] == '/jq/search' and items['incidents']['enabled'] and items['incidents']['connection_id'] == cid
    assert items['warnings']['connection_id'] is None and not items['warnings']['published']
    for body in ({'key': 'incidents', 'path': 'jq/search'}, {'key': 'incidents', 'path': '/a/../b'},
                 {'key': 'incidents', 'path': '/a/{person}'}, {'key': 'profile', 'path': '/v2/profile'}):
        assert admin.put(P + '/admin/provider-endpoints', json=body).status_code == 400, body
    assert admin.put(P + '/admin/provider-endpoints', json={'key': 'warnings', 'path': '/x'}).status_code == 409
    assert admin.put(P + '/admin/provider-endpoints', json={'key': 'nope', 'path': '/x'}).status_code == 404
    changed = admin.put(P + '/admin/provider-endpoints', json={'key': 'incidents', 'path': '/api/v2/jq/search'})
    assert changed.status_code == 200, changed.text
    item = next(i for i in changed.json()['items'] if i['key'] == 'incidents')
    assert item['path'] == '/api/v2/jq/search' and item['updated_by']
    row = store.one('SELECT * FROM connections WHERE id=?', (cid,))
    assert row['revision'] == 2 and json.loads(row['config'])['allowed_paths'] == ['/jq/search']
    assert connection_extras(store, row) == {'path_rewrites': [['/jq/search', '/api/v2/jq/search']]}
    assert admin.put(P + '/admin/provider-endpoints', json={'key': 'profile', 'path': '/v2/profile/{person}'}).status_code == 200
    reset = admin.put(P + '/admin/provider-endpoints', json={'key': 'incidents', 'path': '/jq/search'})
    assert next(i for i in reset.json()['items'] if i['key'] == 'incidents')['updated_by'] is None
    row = store.one('SELECT * FROM connections WHERE id=?', (cid,))
    assert 'endpoint_paths' not in json.loads(row['config']) and connection_extras(store, row) == {}


def test_login_connection_keeps_the_password_out_of_public_views(context):
    store, app, admin = context
    created = admin.post(P + '/admin/connections', json={'name': 'warning', 'base_url': 'http://provider.test', 'auth_type': 'login',
        'login_username': 'reader', 'secret': 'fixture-login-password', 'allowed_paths': ['/system/multiDimension/list']})
    assert created.status_code == 200, created.text
    public = created.json()
    assert public['login_path'] == '/login' and public['login_username'] == 'reader' and public['secret_configured']
    assert 'fixture-login-password' not in json.dumps(admin.get(P + '/admin/connections').json())
    row = store.one('SELECT * FROM connections WHERE id=?', (public['id'],))
    assert connection_headers(store, row) == {}
    assert connection_extras(store, row) == {'login': {'path': '/login', 'username': 'reader', 'password': 'fixture-login-password'}}
    kept = admin.patch(P + '/admin/connections/' + public['id'], json={'login_path': '/auth/login'})
    assert kept.status_code == 200, kept.text
    row = store.one('SELECT * FROM connections WHERE id=?', (public['id'],))
    assert connection_extras(store, row)['login'] == {'path': '/auth/login', 'username': 'reader', 'password': 'fixture-login-password'}
    assert admin.patch(P + '/admin/connections/' + public['id'], json={'login_username': ''}).status_code == 400
    cleared = admin.patch(P + '/admin/connections/' + public['id'], json={'auth_type': 'none'}).json()['connection']
    assert 'login_path' not in cleared and 'login_username' not in cleared


def login_server(business):
    calls = {'login': 0, 'tokens': []}

    def handler(request):
        if request.url.path == '/login':
            calls['login'] += 1
            assert json.loads(request.content) == {'username': 'reader', 'password': 'fixture-login-password'}
            return httpx.Response(200, json={'code': 200, 'msg': 'ok', 'token': 'token-%d' % calls['login']})
        calls['tokens'].append(request.headers.get('authorization'))
        return business(request, calls)
    return calls, httpx.MockTransport(handler)


def login_connection(**extra):
    return {**BASE, 'allowed_paths': ['/system/multiDimension/list'], 'headers': {},
            'login': {'path': '/login', 'username': 'reader', 'password': 'fixture-login-password'}, **extra}


def run(transport, connection, value):
    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            return await exchange(client, connection, value)
    return asyncio.run(go())


@pytest.fixture(autouse=True)
def fresh_tokens():
    connection_policy.LOGIN_TOKENS.clear()
    connection_policy.LOGIN_LOCKS.clear()


def test_login_token_is_cached_and_renewed_once_on_401():
    def business(request, calls):
        if request.headers.get('authorization') == 'Bearer token-1' and len(calls['tokens']) > 1:
            return httpx.Response(200, json={'code': 401, 'msg': '认证失败'})
        return httpx.Response(200, json={'code': 200, 'rows': []})
    calls, transport = login_server(business)
    value = {'method': 'GET', 'path': '/system/multiDimension/list'}
    assert run(transport, login_connection(), value)['data'] == {'code': 200, 'rows': []}
    assert run(transport, login_connection(), value)['data'] == {'code': 200, 'rows': []}
    assert calls['login'] == 2 and calls['tokens'] == ['Bearer token-1', 'Bearer token-1', 'Bearer token-2']


def test_http_401_twice_fails_without_leaking_credentials():
    calls, transport = login_server(lambda request, calls: httpx.Response(401, json={'code': 401}))
    with pytest.raises(ConnectionFailure) as failure:
        run(transport, login_connection(), {'method': 'GET', 'path': '/system/multiDimension/list'})
    assert calls['login'] == 2 and 'fixture-login-password' not in str(failure.value) and 'token' not in str(failure.value)


def test_failed_login_and_reflected_password_are_rejected():
    def refused(request):
        return httpx.Response(200, json={'code': 500, 'msg': '用户不存在/密码错误'})
    with pytest.raises(ConnectionFailure, match='登录失败'):
        run(httpx.MockTransport(refused), login_connection(), {'method': 'GET', 'path': '/system/multiDimension/list'})
    calls, transport = login_server(lambda request, calls: httpx.Response(200, json={'echo': 'fixture-login-password'}))
    with pytest.raises(ConnectionFailure, match='鉴权信息'):
        run(transport, login_connection(), {'method': 'GET', 'path': '/system/multiDimension/list'})


def test_gateway_loads_login_and_rewrite_fields(tmp_path):
    from gateway.service_connections import load_connections
    item = {'id': 'binding', 'plugin_id': 'peixian-theft-warnings', 'alias': 'provider', 'allowed_user': 'u1', 'token': 'a' * 64,
            'headers': {}, 'base_url': 'http://provider.test', 'allowed_methods': ['GET'], 'allowed_paths': ['/system/multiDimension/list'],
            'timeout_seconds': 5, 'max_response_bytes': 65536,
            'login': {'path': '/login', 'username': 'reader', 'password': 'fixture-login-password'},
            'path_rewrites': [['/system/multiDimension/list', '/v2/list']]}
    path = tmp_path / 'connections.json'
    path.write_text(json.dumps({'account_id': 'u1', 'connections': [item]}))
    loaded = load_connections(path, 'u1')['binding']
    assert loaded['login']['username'] == 'reader' and loaded['path_rewrites'] == [['/system/multiDimension/list', '/v2/list']]
    path.write_text(json.dumps({'account_id': 'u1', 'connections': [{**item, 'login': {'path': '/login', 'username': 'reader'}}]}))
    with pytest.raises(ValueError):
        load_connections(path, 'u1')


def test_warning_binding_accepts_login_but_police_stays_anonymous(monkeypatch):
    from control import provider_contracts
    config = {'enabled': True, 'users': ['u1'], 'environment': 'acceptance_real', 'connections': {'warning': 'c1', 'police': 'c2'},
              'limits': {'max_duration_seconds': 86400 * 31, 'max_radius_m': 5000, 'max_page': 10, 'max_rows': 100, 'max_response_bytes': 65536}}
    monkeypatch.setattr(provider_contracts, 'settings', lambda uid: config)
    monkeypatch.setattr(provider_contracts, 'check_selection', lambda *a: None)

    class Store:
        auth = 'login'

        def one(self, sql, args):
            return {'id': args[-1], 'revision': 1, 'config': json.dumps({**BASE, 'auth_type': self.auth})}
    applied = {'plugins': [{'id': 'peixian-theft-' + k, 'version': '3.0.0', 'manifest': {'tools': ['peixian_query_' + k.replace('-', '_')]}}
                           for k in ('profile', 'incidents')]}
    assert provider_contracts.binding(Store(), 'u1', 'profile', applied)['connection_id'] == 'c1'
    with pytest.raises(Exception):
        provider_contracts.binding(Store(), 'u1', 'incidents', applied)


def test_rewritten_request_reaches_the_configured_path():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={'code': 200})
    connection = {**BASE, 'allowed_paths': ['/jq/search'], 'headers': {}, 'path_rewrites': [['/jq/search', '/api/jq/search']]}
    run(httpx.MockTransport(handler), connection, {'method': 'POST', 'path': '/jq/search', 'json': {}})
    assert seen == ['/api/jq/search']
    with pytest.raises(ConnectionFailure):
        run(httpx.MockTransport(handler), connection, {'method': 'POST', 'path': '/api/jq/search', 'json': {}})
