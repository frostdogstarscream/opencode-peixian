import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from test_provider_flow import provider  # noqa: F401  (pytest fixtures)
from test_trusted_results import enabled, v6  # noqa: F401
from test_task_spec import task_env  # noqa: F401
from test_multi_agent import multi  # noqa: F401
from control import native_precheck_questions as q
from control import question_probes as qp
from shared import question_probe

TOKEN = 'a' * 24
CENTRE = (116.93, 34.72)


def _context(direction, confirmed=None):
    return {'direction': direction, 'confirmed': confirmed or {}, 'source_refs': [], 'capture_conditions': {},
            'capture_scope_version': 'capture-purpose-v1', 'user_conditions': {}}


def _spec(kind, card, code='scope_missing'):
    questions, values, fields, extra = card
    return {'token': TOKEN, 'kind': kind, 'code': code, 'status': 'pending', 'fields': fields,
            'questions': questions, 'values': values, **extra}


def _fake_freeze(monkeypatch):
    def freeze(store, uid, sid, applied, kind, context, start=None, end=None, radius=None, refs=None, point=None):
        query = {'start': start, 'end': end}
        if point:
            query.update(lon=str(point[0]), lat=str(point[1]), radius_m=str(radius))
        return {'kind': kind, 'query': query, 'refs': refs, 'radius': radius}
    monkeypatch.setattr(qp, '_freeze', freeze)
    import control.provider_contracts as contracts
    monkeypatch.setattr(contracts, 'settings', lambda uid: {'coordinate_compatibility': {'police:police': True}})


def _ago(days):
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')


def _labels(spec, index):
    return [o['label'] for o in spec['questions'][index]['options']]


def test_annotate_counts_orders_empty_last_and_answers_still_resolve():
    context = _context('person_to_case')
    spec = _spec('tracks', q.scope_card('tracks', ['start', 'end'], context, None, 'u', 's'))
    window = dict(spec['values']['近15天'])
    q.annotate(spec, {0: {'近7天': 0, '近15天': 12, '近31天': 30}, 1: {'半径 300 米': None}},
               {0: '轨迹 {} 条', 1: '警情 {} 起'})
    assert _labels(spec, 0) == ['近15天（轨迹 12 条）', '近31天（轨迹 30 条）', '近7天（无数据）']
    radius = spec['questions'][1]['options'][0]
    assert radius['label'] == '半径 300 米' and radius['description'].endswith('未能预查')
    assert spec['values']['近15天（轨迹 12 条）'] == window and '近15天' not in spec['values']
    nxt, _text, cancelled = q.apply_reply(spec, [['近15天（轨迹 12 条）'], ['半径 500 米']], context)
    assert not cancelled and nxt['confirmed']['start'] == window['start'] and nxt['confirmed']['radius_m'] == '500'
    assert q.match_public(spec, q.public(spec)['questions'])


def test_person_to_case_counts_tracks_then_incidents_around_stay_centres(monkeypatch):
    _fake_freeze(monkeypatch)
    context = _context('person_to_case', {'person_identity': '320322198803159911'})
    spec = _spec('tracks', q.scope_card('tracks', ['start', 'end'], context, None, 'u', 's'))
    plans = qp.start(spec, context, None, 'u', 's', {})
    assert [p['plan']['kind'] for p in plans] == ['tracks']
    assert plans[0]['plan']['query']['start'] == spec['values']['近31天']['start']
    points = [[_ago(days), CENTRE[0], CENTRE[1], '青枫小区南门'] for days in (10, 11, 12)]
    second = qp.complete(spec, [{'id': plans[0]['id'], 'status': 'ok', 'data': {'points': points}}],
                         context, None, 'u', 's', {})
    assert [p['plan']['kind'] for p in second] == ['incidents']
    assert second[0]['plan']['query']['radius_m'] == '1000'
    rows = [['J1', _ago(3), CENTRE[0], CENTRE[1] + 0.004], ['J2', _ago(4), CENTRE[0], CENTRE[1] + 0.008]]
    assert qp.complete(spec, [{'id': second[0]['id'], 'status': 'ok', 'data': {'total': 2, 'rows': rows}}],
                       context, None, 'u', 's', {}) == []
    assert _labels(spec, 0) == ['近15天（轨迹 3 条）', '近31天（轨迹 3 条）', '近7天（无数据）']
    assert _labels(spec, 1) == ['半径 500 米（警情 1 起）', '半径 1000 米（警情 2 起）', '半径 300 米（无数据）']
    assert '按近31天停留点统计' in spec['questions'][1]['options'][0]['description']
    audit = qp.audit(spec)
    assert [j['status'] for j in audit['jobs']] == ['ok', 'ok'] and 'J1' not in str(audit)


def test_no_tracks_marks_every_option_as_no_data(monkeypatch):
    _fake_freeze(monkeypatch)
    context = _context('person_to_case', {'person_identity': '320322198803159911'})
    spec = _spec('tracks', q.scope_card('tracks', ['start', 'end'], context, None, 'u', 's'))
    plans = qp.start(spec, context, None, 'u', 's', {})
    assert qp.complete(spec, [{'id': plans[0]['id'], 'status': 'ok', 'data': {'points': []}}],
                       context, None, 'u', 's', {}) == []
    assert all(label.endswith('（无数据）') for index in (0, 1) for label in _labels(spec, index))


def test_failed_probe_keeps_labels_and_says_not_probed(monkeypatch):
    _fake_freeze(monkeypatch)
    context = _context('person_to_case', {'person_identity': '320322198803159911'})
    spec = _spec('tracks', q.scope_card('tracks', ['start', 'end'], context, None, 'u', 's'))
    plans = qp.start(spec, context, None, 'u', 's', {})
    assert qp.complete(spec, [{'id': plans[0]['id'], 'status': 'failed'}], context, None, 'u', 's', {}) == []
    assert _labels(spec, 0) == ['近7天', '近15天', '近31天']
    assert all(o['description'].endswith('未能预查') for index in (0, 1) for o in spec['questions'][index]['options'])


def test_capture_card_probes_each_time_and_radius_choice(monkeypatch):
    _fake_freeze(monkeypatch)
    case = {'label': 'JJ-1', 'ref': {'record_id': 'run:call:1'}, 'cjsj': '2026-09-18 02:40:00', 'module': 'incidents',
            'fields': {'jjbh': 'JJ-1', 'cjsj': '2026-09-18 02:40:00'}}
    monkeypatch.setattr(q, 'case_sources', lambda *a, **k: [case])
    context = _context('case_to_person')
    spec = _spec('captures', q.scope_card('captures', ['start', 'end', 'radius_m'], context, object(), 'u', 's'))
    plans = qp.start(spec, context, None, 'u', 's', {})
    assert len(plans) == qp.MAX_PROBES and all(p['plan']['refs'] == [case['ref']] for p in plans)
    totals = {p['id']: index for index, p in enumerate(plans)}
    qp.complete(spec, [{'id': i, 'status': 'ok', 'data': {'total': n}} for i, n in totals.items()],
                context, None, 'u', 's', {})
    assert _labels(spec, 0)[-1] == '案发前1天（无数据）'
    assert all('（抓拍 ' in label for label in _labels(spec, 0)[:-1] + _labels(spec, 1))


def test_case_choice_is_probed_per_case_and_reply_keeps_the_plain_label(monkeypatch):
    _fake_freeze(monkeypatch)
    case = {'label': 'JJ-1 · 2026-09-18 02:40 · 入室盗窃', 'ref': {'record_id': 'run:call:1', 'run_id': 'run'},
            'cjsj': '2026-09-18 02:40:00', 'module': 'incidents',
            'fields': {'jjbh': 'JJ-1', 'cjsj': '2026-09-18 02:40:00', 'cjxz': '紫薇花园3号楼', 'gisX': '116.93', 'gisY': '34.72'}}
    other = {**case, 'label': 'JJ-2', 'ref': {'record_id': 'run:call:2', 'run_id': 'run'},
             'fields': {**case['fields'], 'jjbh': 'JJ-2'}}
    monkeypatch.setattr(q, 'case_sources', lambda *a, **k: [case, other])
    monkeypatch.setattr(q, 'source_match', lambda store, uid, sid, ref: case if ref['record_id'] == 'run:call:1' else other)
    import control.analysis_tasks as tasks
    monkeypatch.setattr(tasks, 'source', lambda *a, **k: None)
    context = {**_context('case_to_person', {'address': '紫薇花园'}), 'scope_version': 1, 'task_id': 'task'}
    spec = q.build('captures', 'scope_missing', {'start': 'x', 'end': 'x', 'radius_m': 'x'}, context, object(), 'u', 's')
    plans = qp.start(spec, context, object(), 'u', 's', {})
    assert len(plans) == 2 and plans[0]['plan']['query'] == {'start': '2026-09-03 02:40:00', 'end': '2026-09-18 02:40:00'}
    qp.complete(spec, [{'id': plans[0]['id'], 'status': 'ok', 'data': {'total': 4}},
                       {'id': plans[1]['id'], 'status': 'ok', 'data': {'total': 0}}], context, object(), 'u', 's', {})
    chosen = case['label'] + '（抓拍 4 人）'
    assert _labels(spec, 0) == [chosen, 'JJ-2（无数据）']
    nxt, text, _ = q.apply_reply(spec, [[chosen], ['案发前7天'], ['半径 500 米']], context, object(), 'u', 's')
    assert nxt['source_refs'] == [case['ref']] and case['label'] in text and '抓拍 4 人' not in text


def test_probe_digest_keeps_only_times_coordinates_and_totals():
    response = {'code': 200, 'data': {'targetIdCard': '320322198803159911', 'points': [
        {'captureTime': '2026-09-15 00:47:00', 'lon': 116.9, 'lat': 34.7, 'deviceName': '青枫小区南门',
         'faceStoragePath': 'http://internal/f.jpg'}]}}
    data = question_probe.digest('tracks', response)
    assert data == {'points': [['2026-09-15 00:47:00', 116.9, 34.7, '青枫小区南门']]}
    assert question_probe.digest('captures', {'code': 200, 'data': {'rows': [{'target_id_card': 'x'}], 'total': 7}}) == {'total': 7}
    assert question_probe.digest('tracks', {'code': 500}) is None


def test_gateway_runs_probes_and_falls_back_to_the_plain_card(monkeypatch):
    from gateway import theft_provider_execution as ex
    gate = SimpleNamespace(require_egress=lambda: None)
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(managed_root='unused'),
                                                runtime_management=SimpleNamespace(gate=gate)))
    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, False))
    monkeypatch.setattr(ex, 'specification', lambda root, plugin: {'plugin': plugin})
    plan = {'kind': 'captures', 'plugin_id': 'peixian-theft-captures', 'tool_id': 'peixian_query_captures',
            'request': {'method': 'POST', 'json': {'lon': '1'}}}
    sent = []

    async def process(value):
        return {'code': 200, 'data': {'rows': [{'target_id_card': '320322198803159911'}], 'total': 3}}

    async def rpc(action, **fields):
        sent.append((action, fields))
        return {'question': {'id': TOKEN, 'questions': ['labelled']}}
    probe = {'token': TOKEN, 'plans': [{'id': 'probe1', 'plan': plan}]}
    plain = {'id': TOKEN, 'questions': ['plain']}
    value = {'session_id': 's'}
    assert asyncio.run(ex.run_probes(request, app, value, rpc, 'parent', process, probe, plain))['questions'] == ['labelled']
    assert sent == [('native_probe_complete', {'session_id': 's', 'message_id': 'parent', 'token': TOKEN,
                                               'results': [{'id': 'probe1', 'status': 'ok', 'data': {'total': 3}}]})]

    async def broken(action, **fields):
        from fastapi import HTTPException
        raise HTTPException(409, {'code': 'native_tool_invalid'})
    assert asyncio.run(ex.run_probes(request, app, value, broken, 'parent', process, probe, plain)) == plain


def test_prepare_returns_probes_and_completion_labels_the_stored_card(provider, monkeypatch):
    from control import native_tool_gate
    from test_native_tool_execution import native_candidate
    from test_provider_flow import tool
    store = provider[0]; uid = provider[4]['uid']; row = native_candidate(provider, monkeypatch)
    _fake_freeze(monkeypatch)
    snap = store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?', (row['id'],))['request_ciphertext'])
    snap['native_tool_context'].update(direction='person_to_case', confirmed={'person_identity': '320322198803159911'})
    with store.tx() as db:
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?', (store.encrypt(snap), row['id']))
    decision = native_tool_gate.prepare(store, uid, 'ses_multi', row['message_id'], 'tracks-1', tool('tracks'), {}, 1)
    assert decision['needs_question'] and decision['probe']['token'] == decision['question']['id']
    token, plans = decision['probe']['token'], decision['probe']['plans']
    assert [p['plan']['kind'] for p in plans] == ['tracks']
    done = native_tool_gate.probe_complete(store, uid, 'ses_multi', row['message_id'], token,
                                           [{'id': plans[0]['id'], 'status': 'ok', 'data': {'points': []}}], 1)
    labels = [o['label'] for o in done['question']['questions'][0]['options']]
    assert labels == ['近7天（无数据）', '近15天（无数据）', '近31天（无数据）']
    stored = store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?', (row['id'],))['request_ciphertext'])
    assert 'probe_state' not in stored['native_pending_questions'][token] and stored['question_probes'][token]['jobs']
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        native_tool_gate.probe_complete(store, uid, 'ses_multi', row['message_id'], token, [], 1)


def test_clue_cards_and_source_detail_show_identity_numbers():
    from control.reply_presentation import reveal_cards, source_detail, VERSION
    ref, identity = 'person-' + 'b' * 32, '320322198803159911'
    card = {'title': '地点周边人员抓拍统计来源记录', 'headline': f'周军（{ref}）：抓拍 3 次。', 'summary': f'周军（{ref}）',
            'discoveries': [f'周军（{ref}）'], 'evidence': [{'id': 'source_x', 'content': f'周军（{ref}）',
                                                           'record_id': 'r1', 'snapshot_id': 's1', 'source_run_id': 'run'}]}
    presentation = reveal_cards({'version': VERSION, 'clues': [card]}, {ref: identity})
    assert ref not in str(presentation) and presentation['clues'][0]['headline'].startswith(f'周军（{identity}）')
    result = {'run_id': 'run', 'presentation': presentation,
              'records': [{'record_id': 'r1', 'snapshot_id': 's1', 'source_run_id': 'run',
                           'fields': {'target_name': '周军', 'target_id_card': ref}}]}
    detail = source_detail(result, 'source_x', {ref: identity})
    assert detail['record']['fields']['target_id_card'] == identity
    assert result['records'][0]['fields']['target_id_card'] == ref
