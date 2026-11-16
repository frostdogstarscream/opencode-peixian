"""Offline deployment defaults: `*` feature scopes, all-account provider config, installs on grant."""
import json

import pytest

from control import provider_contracts
from control.feature_scope import allowed
from control.store import encode
from test_control import context, create_user, P

LIMITS = {'max_radius_m': 5000, 'max_duration_seconds': 2678400, 'max_page': 100, 'max_rows': 100, 'max_response_bytes': 1048576}


def test_star_scope_admits_every_account(monkeypatch):
    monkeypatch.setenv('PX_THEFT_NATIVE_UIDS', '*')
    assert allowed('PX_THEFT_NATIVE_UIDS', 'a' * 32) and allowed('PX_THEFT_NATIVE_UIDS', 'b' * 32)
    monkeypatch.setenv('PX_THEFT_NATIVE_UIDS', ' ' + 'a' * 32 + ' ,')
    assert allowed('PX_THEFT_NATIVE_UIDS', 'a' * 32) and not allowed('PX_THEFT_NATIVE_UIDS', 'b' * 32)
    monkeypatch.delenv('PX_THEFT_NATIVE_UIDS')
    assert not allowed('PX_THEFT_NATIVE_UIDS', 'a' * 32)


def test_provider_settings_accept_all_accounts(monkeypatch, tmp_path):
    path = tmp_path / 'provider.json'
    config = {'enabled': True, 'users': '*', 'environment': 'acceptance_real',
              'connections': {'police': 'c1', 'warning': 'c2'}, 'limits': LIMITS}
    path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setenv('PX_THEFT_REAL_CONFIG_FILE', str(path))
    assert provider_contracts.settings('any-account')['connections'] == {'police': 'c1', 'warning': 'c2'}
    path.write_text(json.dumps({**config, 'users': ['only-this']}), encoding='utf-8')
    with pytest.raises(Exception):
        provider_contracts.settings('any-account')


def plugin(store, pid, schema=None):
    manifest = {'id': pid, 'tools': ['peixian_query_x'], 'connections': {'provider': {}},
                'config_schema': schema or {'type': 'object', 'properties': {}}}
    with store.tx() as db:
        db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)', (pid, '3.0.0', pid, '', encode(manifest), '/dev/null', 'd' * 64))


def test_granting_plugins_installs_them(context):
    store, app, admin = context
    plugin(store, 'peixian-theft-incidents')
    plugin(store, 'peixian-theft-night', {'type': 'object', 'properties': {'k': {'type': 'string'}}, 'required': ['k']})
    uid = create_user(admin)['id']
    r = admin.patch(P + '/admin/users/' + uid, json={'plugin_ids': ['peixian-theft-incidents', 'peixian-theft-night']})
    assert r.status_code == 200, r.text
    rows = {row['plugin']: row for row in store.rows('SELECT * FROM installs WHERE uid=?', (uid,))}
    assert set(rows) == {'peixian-theft-incidents'}
    assert rows['peixian-theft-incidents']['version'] == '3.0.0' and rows['peixian-theft-incidents']['enabled']
    assert store.decrypt(rows['peixian-theft-incidents']['config']) == {}
    with store.tx() as db:
        db.execute('UPDATE installs SET enabled=0 WHERE uid=?', (uid,))
    admin.patch(P + '/admin/users/' + uid, json={'plugin_ids': ['peixian-theft-incidents']})
    assert not store.one('SELECT enabled FROM installs WHERE uid=?', (uid,))['enabled']


def model(store, mid, default):
    with store.tx() as db:
        db.execute('INSERT INTO models VALUES(?,?,?,?,?,?,?,?)', (mid, mid, '', 'http://model.invalid/v1', mid, store.encrypt(''), 1, int(default)))


def grants(store, uid):
    rows = store.rows('SELECT kind,resource FROM grants WHERE uid=?', (uid,))
    return sorted(r['resource'] for r in rows if r['kind'] == 'model'), sorted(r['resource'] for r in rows if r['kind'] == 'plugin')


def test_empty_grants_default_to_model_and_all_plugins(context, monkeypatch):
    store, app, admin = context
    model(store, 'm-other', False)
    model(store, 'm-default', True)
    plugin(store, 'peixian-theft-incidents')
    plugin(store, 'peixian-theft-captures')
    assert grants(store, create_user(admin, 'plain-user')['id']) == ([], [])
    monkeypatch.setenv('PX_DEFAULT_GRANTS', '1')
    uid = create_user(admin, 'offline-user')['id']
    assert grants(store, uid) == (['m-default'], ['peixian-theft-captures', 'peixian-theft-incidents'])
    assert {r['plugin'] for r in store.rows('SELECT plugin FROM installs WHERE uid=?', (uid,))} == {'peixian-theft-captures', 'peixian-theft-incidents'}
    with store.tx() as db:
        db.execute('DELETE FROM grants WHERE uid=?', (uid,))
    r = admin.patch(P + '/admin/users/' + uid, json={'model_ids': [], 'plugin_ids': [], 'active': True})
    assert r.status_code == 200, r.text
    assert grants(store, uid) == (['m-default'], ['peixian-theft-captures', 'peixian-theft-incidents'])
    admin.patch(P + '/admin/users/' + uid, json={'model_ids': ['m-other'], 'plugin_ids': ['peixian-theft-incidents']})
    assert grants(store, uid) == (['m-other'], ['peixian-theft-incidents'])
