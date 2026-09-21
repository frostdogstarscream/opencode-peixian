"""Resolve account-owned official copies without creating or enabling resources."""
import json
from fastapi import HTTPException
from .official_methods import identify, BY_ID
from .backend_contract import error
from .capabilities import catalog


def unavailable(code):
    error(code, '当前官方方法不可执行，请检查我的技能中的安装、启用、内容和配置生效状态。', 409)


def resolve(store, uid, applied, selected_ids, method_ids):
    owned = {x['id']: x for x in store.rows('SELECT * FROM skills WHERE uid=?', (uid,))}
    active = {x['id']: x for x in applied.get('skills', [])}
    availability = {x['id']: x for x in catalog(store, uid) if x['kind'] == 'personal_skill'}

    def validate(sid):
        row = owned.get(sid)
        if row is None:
            unavailable('official_method_not_owned')
        identity = identify(row['content'])
        if identity is None:
            unavailable('official_method_identity_changed')
        if identity['state'] != 'published':
            unavailable('official_method_not_published')
        if not row['enabled']:
            unavailable('official_method_disabled')
        if sid not in active or active[sid]['content'] != row['content'] or active[sid].get('version') != row['version']:
            unavailable('official_method_pending')
        profile = store.one('SELECT dependencies FROM skill_profiles WHERE sid=?', (sid,))
        if not profile or set(json.loads(profile['dependencies'])) != set(identity['dependency_ids']):
            unavailable('official_method_dependency_unavailable')
        if not availability.get(sid, {}).get('available'):
            unavailable('official_method_dependency_unavailable')
        return identity

    if selected_ids:
        return [(sid, validate(sid)) for sid in selected_ids]
    result = []
    for method in method_ids:
        expected = BY_ID['peixian.method.' + method]
        matches = sorted(sid for sid, row in owned.items() if identify(row['content']) == expected or identify(active.get(sid,{}).get('content','')) == expected)
        if not matches:
            unavailable('official_method_not_owned')
        valid, failure = [], None
        for sid in matches:
            try:
                valid.append((sid, validate(sid)))
            except HTTPException as exc:
                failure = exc
        if not valid:
            raise failure
        result.append(valid[0])
    return result
