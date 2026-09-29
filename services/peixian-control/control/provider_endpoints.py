"""Super administrator view of the business-data interfaces: switch, connection and request path.

Published bundles and frozen plans keep the contract path; a changed path is an
egress rewrite stored on the interface's own connection and applied by Gateway.
"""
import json

from fastapi import Depends, Request

from shared.connection_policy import ConnectionFailure, PERSON, policy, template_path
from shared.theft_provider_v2 import CATALOG, ENDPOINT_KEYS, default_path
from .data_plugin_policy import ACTIVE_KINDS, ACTIVE_VERSION
from .store import encode, now

KEYS = tuple(key for kind in ACTIVE_KINDS for key in ((kind,) if kind != 'warnings' else tuple(ENDPOINT_KEYS)))
NAMES = {'warnings': '按姓名查找人员', 'warnings_phone': '按手机号查找人员'}


def kind_of(key):
    return ENDPOINT_KEYS.get(key, (key,))[0]


def plugin_of(key):
    return 'peixian-theft-' + kind_of(key).replace('_', '-')


def checked_path(key, value):
    try:
        template_path(value)
    except ConnectionFailure as exc:
        raise ValueError(str(exc)) from None
    if value.endswith(PERSON) != default_path(key).endswith(PERSON):
        raise ValueError('人员占位 {person} 只能用在原本带占位的接口上')
    return value


def listing(db):
    items = []
    for key in KEYS:
        pid = plugin_of(key)
        plugin = db.execute('SELECT name,enabled FROM plugins WHERE id=? AND version=?', (pid, ACTIVE_VERSION)).fetchone()
        row = db.execute("SELECT c.id,c.config FROM connections c JOIN plugin_connections b ON b.connection_id=c.id "
                         "WHERE b.plugin=? AND b.version=? AND b.alias='provider'", (pid, ACTIVE_VERSION)).fetchone()
        config = json.loads(row['config']) if row else {}
        override = config.get('endpoint_paths', {}).get(key)
        items.append({'key': key, 'kind': kind_of(key), 'name': NAMES.get(key, CATALOG[kind_of(key)][0]),
                      'method': CATALOG[kind_of(key)][1], 'plugin_id': pid, 'plugin_version': ACTIVE_VERSION,
                      'published': plugin is not None, 'enabled': bool(plugin and plugin['enabled']),
                      'connection_id': row['id'] if row else None, 'connection_name': config.get('name'),
                      'default_path': default_path(key), 'path': override['path'] if override else default_path(key),
                      'updated_by': override.get('updated_by') if override else None,
                      'updated_at': override.get('updated_at') if override else None})
    return items


def register_provider_endpoints(app):
    from .app import PREFIX, body_fields, fail, require_capability
    from .concurrency import blocking_endpoint

    permission = require_capability('connections.manage')

    @app.get(PREFIX + '/admin/provider-endpoints')
    @blocking_endpoint(app)
    def endpoints_list(request: Request, user=Depends(permission)):
        with app.state.store.read(snapshot=True) as db:
            return {'items': listing(db)}

    @app.put(PREFIX + '/admin/provider-endpoints')
    @blocking_endpoint(app, json_body=True)
    def endpoints_put(request: Request, user=Depends(permission)):
        from .runtime_security import block_runtime
        raw = body_fields(request.state.json_body, ('key', 'path'))
        key, path = raw.get('key'), raw.get('path')
        if key not in KEYS:
            fail('接口不存在', 404)
        if path is not None and not isinstance(path, str):
            fail('请求路径格式不正确')
        try:
            path = checked_path(key, path.strip()) if path and path.strip() else None
        except ValueError as exc:
            fail(str(exc))
        if path == default_path(key):
            path = None
        s = app.state.store
        with s.tx() as db:
            pid = plugin_of(key)
            row = db.execute("SELECT c.* FROM connections c JOIN plugin_connections b ON b.connection_id=c.id "
                             "WHERE b.plugin=? AND b.version=? AND b.alias='provider'", (pid, ACTIVE_VERSION)).fetchone()
            if not row:
                fail('此接口尚未绑定连接，请先在连接页配置', 409)
            config = json.loads(row['config'])
            overrides = dict(config.get('endpoint_paths', {}))
            if path is None:
                overrides.pop(key, None)
            else:
                overrides[key] = {'path': path, 'updated_by': user['username'], 'updated_at': now()}
            if overrides == config.get('endpoint_paths', {}):
                return {'items': listing(db), 'jobs': []}
            changed = {k: v for k, v in config.items() if k != 'endpoint_paths'}
            if overrides:
                changed['endpoint_paths'] = overrides
            try:
                changed = policy({**changed, 'path_rewrites': [[default_path(k), v['path']] for k, v in sorted(overrides.items())]})
            except ConnectionFailure as exc:
                fail(str(exc))
            changed.pop('path_rewrites')
            db.execute('UPDATE connections SET config=?,revision=revision+1 WHERE id=?', (encode(changed), row['id']))
            users = [r[0] for r in db.execute(
                "SELECT DISTINCT i.uid FROM installs i JOIN plugin_connections b ON b.plugin=i.plugin AND b.version=i.version "
                "JOIN plugins p ON p.id=i.plugin AND p.version=i.version JOIN grants g ON g.uid=i.uid AND g.kind='plugin' AND g.resource=i.plugin "
                "WHERE i.enabled=1 AND p.enabled=1 AND b.connection_id=?", (row['id'],))]
            for uid in users:
                block_runtime(s, db, uid, reason='connection_restricted')
            jobs = [s.queue_in_transaction(db, uid) for uid in users]
            request.state.management_target = key
            return {'items': listing(db), 'jobs': jobs}
