import json

from test_provider_flow import provider  # noqa: F401  (pytest fixtures)
from test_trusted_results import enabled, v6  # noqa: F401
from test_task_spec import task_env  # noqa: F401
from test_multi_agent import multi  # noqa: F401
from control import native_precheck_questions as q
from control import native_tool_scope as scope
from control import question_contract
from control import table_answer as t
from control import theft_scoring as s


def test_case_time_presets_end_at_incident_time():
    options, values = q.case_time_presets('2026-09-18 02:40:00')
    assert [o['label'] for o in options] == ['案发前1天', '案发前3天', '案发前7天', '案发前15天']
    assert values['案发前7天'] == {'start': '2026-09-11 02:40:00', 'end': '2026-09-18 02:40:00'}
    for value in values.values():
        q.check_window(value['start'], value['end'])
    options, values = q.case_time_presets(None)
    assert values['案发前15天'] == {'case_days': 15} and '向前 15 天' in options[3]['description']


def test_recent_presets_use_short_labels():
    options, values = q.recent_time_presets()
    assert [o['label'] for o in options] == ['近7天', '近15天', '近31天']
    assert all(' 至 ' in o['description'] for o in options) and set(values) == {'近7天', '近15天', '近31天'}


def test_community_name_is_case_to_person_input():
    assert scope.community_address('紫薇花园附近有什么可疑人员') == '紫薇花园'
    assert scope.community_address('查一下演示壬家属院') == '演示壬家属院'
    assert scope.community_address('帮我分析一下华府名邸') == '华府名邸'
    assert scope.community_address('近7天有哪些人员') is None
    assert scope.infer_direction({}, [], '紫薇花园') == 'case_to_person'
    assert scope.infer_direction({'person_identity': '320322198803159911'}, [], '紫薇花园') == 'person_to_case'


def _context(direction, confirmed, refs=None):
    return {'direction': direction, 'confirmed': confirmed, 'source_refs': refs or [], 'capture_conditions': {},
            'capture_scope_version': 'capture-purpose-v1', 'user_conditions': {}}


def test_incident_query_by_address_needs_no_coordinates():
    context = _context('case_to_person', {'address': '紫薇花园'})
    args = scope.resolve_arguments('incidents', {}, context)
    assert scope.arguments('incidents', args, context) == {'address': '紫薇花园'}
    person = _context('person_to_case', {'address': '紫薇花园', 'lon': '116.9', 'lat': '34.7', 'radius_m': '500'})
    assert 'address' not in scope.resolve_arguments('incidents', {}, person)


def test_model_placeholders_count_as_missing():
    context = {**_context('case_to_person', {'address': '紫薇花园'}), 'current_text': '紫薇花园附近有什么可疑人员', 'constraints_text': ''}
    assert scope.grounded_arguments('incidents', {'lon': '0', 'lat': 0, 'radius_m': 1000, 'page': 1}, context) == {'radius_m': 1000, 'page': 1}
    assert scope.grounded_arguments('incidents', {'lon': 116.9, 'lat': 34.7}, context) == {}
    assert scope.grounded_arguments('captures', {'radius_m': 0, 'start': '2000-01-01 00:00:00', 'end': '2000-01-01 00:00:00'}, context) == {}
    person = {**_context('person_to_case', {'person_identity': '320322198803159911'}), 'current_text': '查一下 320322198803159911'}
    assert scope.grounded_arguments('tracks', {'person_identity': '320322198803159911', 'start': '', 'end': ''}, person) == {'person_identity': '320322198803159911'}
    stated = {**_context('case_to_person', {}), 'current_text': '查询坐标 117.08, 34.860 周边 2000 米内 2026-09-01 至 2026-09-15 的警情'}
    args = {'lon': '117.080', 'lat': 34.86, 'radius_m': 2000, 'start': '2026-09-01 00:00:00', 'end': '2026-09-15 23:59:59'}
    assert scope.grounded_arguments('incidents', args, stated) == args
    answered = {**_context('person_to_case', {'start': '2026-09-13 00:00:00', 'end': '2026-09-28 00:00:00'}), 'current_text': '查一下'}
    assert scope.grounded_arguments('tracks', {'start': '2026-09-13 00:00:00', 'end': '2026-09-28 00:00:00'}, answered)['start'] == '2026-09-13 00:00:00'


def test_card_matches_when_model_drops_custom_but_free_text_is_refused():
    spec = {'token': 't', 'kind': 'captures', 'status': 'pending', 'fields': ['source'],
            'questions': [{'field': 'source', 'header': '选择案件', 'question': '请选择案件',
                           'options': [{'label': 'JJ-1 · 2026-09-18 02:40', 'description': '紫薇花园'}], 'custom': False}],
            'values': {'JJ-1 · 2026-09-18 02:40': {'source_ref': {'record_id': 'r'}}}}
    asked = [{'header': '选择案件', 'question': '紫薇花园有1起警情，请选择', 'options': [{'label': 'JJ-1 · 2026-09-18 02:40', 'description': 'x'}]}]
    assert q.match_public(spec, asked)
    assert all(o.get('description') for o in q.public(spec)['questions'][0]['options'])
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        q._resolve_answer(spec['questions'][0], ['随便写的'], spec['values'])


def test_person_to_case_incidents_reuse_track_window():
    context = _context('person_to_case', {'start': '2026-09-13 00:00:00', 'end': '2026-09-28 00:00:00', 'radius_m': '500'},
                       refs=[{'record_id': 'r'}])
    args = scope.resolve_arguments('incidents', {}, context)
    assert args == {'start': '2026-09-13 00:00:00', 'end': '2026-09-28 00:00:00', 'radius_m': '500'}
    assert scope.arguments('incidents', args, context) == args


def test_person_scope_card_is_options_only():
    card = q.scope_card('tracks', ['start', 'end'], _context('person_to_case', {}), None, 'u', 's')
    questions, values, fields, extra = card
    assert [x['header'] for x in questions] == ['时间范围', '警情关联半径']
    assert [o['label'] for o in questions[0]['options']] == ['近7天', '近15天', '近31天']
    assert fields == ['start', 'end', 'radius_m'] and not extra
    assert '近15天' in values and '半径 500 米' in values


def test_case_scope_reply_resolves_days_before_selected_case(monkeypatch):
    case = {'label': 'JJ-1 · 2026-09-18 02:40 · 入室盗窃', 'ref': {'record_id': 'run:call:1', 'run_id': 'run'},
            'cjsj': '2026-09-18 02:40:00', 'module': 'incidents',
            'fields': {'jjbh': 'JJ-1', 'cjsj': '2026-09-18 02:40:00', 'cjxz': '紫薇花园3号楼', 'cljgnr': '入室盗窃',
                       'gisX': '116.93', 'gisY': '34.72'}}
    other = {**case, 'label': 'JJ-2', 'ref': {'record_id': 'run:call:2', 'run_id': 'run'},
             'fields': {**case['fields'], 'jjbh': 'JJ-2'}}
    monkeypatch.setattr(q, 'case_sources', lambda *a, **k: [case, other])
    monkeypatch.setattr(q, 'source_match', lambda store, uid, sid, ref: case if ref['record_id'] == 'run:call:1' else other)
    import control.analysis_tasks as tasks
    monkeypatch.setattr(tasks, 'source', lambda *a, **k: None)
    context = {**_context('case_to_person', {'address': '紫薇花园'}), 'scope_version': 1, 'task_id': 'task'}
    spec = q.build('captures', 'scope_missing', {'start': 'x', 'end': 'x', 'radius_m': 'x'}, context, object(), 'u', 's')
    assert [x['header'] for x in spec['questions']] == ['选择案件', '抓拍时间', '抓拍范围']
    assert [o['label'] for o in spec['questions'][1]['options']][2] == '案发前7天'
    nxt, text, cancelled = q.apply_reply(spec, [[case['label']], ['案发前7天'], ['半径 500 米']], context, object(), 'u', 's')
    assert not cancelled and nxt['source_refs'] == [case['ref']]
    assert nxt['capture_conditions'] == {'start': '2026-09-11 02:40:00', 'end': '2026-09-18 02:40:00', 'radius_m': '500'}
    assert nxt['case_info']['jjbh'] == 'JJ-1' and '案发前7天' in text


def test_single_case_is_selected_automatically(monkeypatch):
    case = {'label': 'JJ-1', 'ref': {'record_id': 'run:call:1'}, 'cjsj': '2026-09-18 02:40:00', 'module': 'incidents',
            'fields': {'jjbh': 'JJ-1', 'cjsj': '2026-09-18 02:40:00'}}
    monkeypatch.setattr(q, 'case_sources', lambda *a, **k: [case])
    card = q.scope_card('captures', ['start', 'end', 'radius_m'], _context('case_to_person', {}), object(), 'u', 's')
    questions, values, fields, extra = card
    assert [x['header'] for x in questions] == ['抓拍时间', '抓拍范围'] and extra['auto_source_ref'] == case['ref']
    assert values['案发前3天'] == {'start': '2026-09-15 02:40:00', 'end': '2026-09-18 02:40:00'}


def _track(rid, when, lon=116.93, lat=34.72):
    return {'record_id': rid, 'module': 'tracks', 'fields': {'captureTime': when, 'lon': lon, 'lat': lat, 'deviceName': '紫薇花园东门'}}


def _incident(rid, number, when, lon=116.9301, lat=34.7201, brief='入室盗窃，损失现金'):
    return {'record_id': rid, 'module': 'incidents',
            'fields': {'jjbh': number, 'cjbh': 'CJ' + number, 'cjsj': when, 'gisX': lon, 'gisY': lat, 'cljgnr': brief, 'cjxz': '紫薇花园'}}


def test_case_checks_carry_number_and_brief_and_dedupe():
    tracks = [_track('t1', '2026-09-18 01:30:00')]
    incidents = [_incident('i1', 'JJ-1', '2026-09-18 02:40:00'), _incident('i1b', 'JJ-1', '2026-09-18 02:40:00'),
                 _incident('i2', 'JJ-2', '2026-09-20 12:00:00', lon=116.99, lat=34.79)]
    view = s.case_checks(tracks, incidents)
    assert [x['jjbh'] for x in view['items']] == ['JJ-1', 'JJ-2']
    assert view['items'][0]['grade'] == '时空同现较强' and view['items'][0]['brief'] == '入室盗窃，损失现金'
    d5 = s.score_d5(tracks + incidents)
    assert '与警情 JJ-1 ' in d5['evidence']


def test_suspect_case_section_names_incident_or_says_none():
    tracks = [_track('t1', '2026-09-18 01:30:00')]
    view = s.case_checks(tracks, [_incident('i1', 'JJ-1', '2026-09-18 02:40:00')])
    suspect = t.suspect_case(view)
    assert suspect['top']['jjbh'] == 'JJ-1'
    text = t.markdown({'version': 'person-tables-v3', 'evidence': [], 'suspect_case': suspect,
                       'query_window': '时间 2026-09-13 00:00:00 至 2026-09-28 00:00:00；警情关联半径 500 米'})
    assert '### 最可疑警情' in text and 'JJ-1' in text and '入室盗窃，损失现金' in text and '本次查询条件' in text
    far = s.case_checks(tracks, [_incident('i2', 'JJ-2', '2026-09-20 12:00:00', lon=116.99, lat=34.79)])
    text = t.markdown({'version': 'person-tables-v3', 'evidence': [], 'suspect_case': t.suspect_case(far)})
    assert '未发现时空关联警情' in text and 'JJ-2' not in text.split('### 最可疑警情')[1].split('###')[0]
    none = t.suspect_case(s.case_checks(tracks, []))
    assert none == {'top': None, 'others': [], 'checked': 0}
    assert '已比对 0 起警情' in t.markdown({'version': 'person-tables-v3', 'evidence': [], 'suspect_case': none})
    assert t.suspect_case(None) is None


def test_late_night_stop_gets_a_stay_centre():
    from control import person_case_flow as pcf
    def point(i, lon, lat, when):
        return {'record_id': f'r{i}', 'source_run_id': 'run', 'snapshot_id': 'snap', 'result_digest': 'd',
                'fields': {'lon': lon, 'lat': lat, 'captureTime': when, 'deviceName': f'点{lon}'}}
    busy = [point(f'{k}{i}', lon, 34.78, f'2026-09-{14 + i} {h}:00:00')
            for k, (lon, h) in enumerate(((117.015, '09'), (117.03, '12'), (117.04, '15'))) for i in range(8)]
    centers = pcf.stay_points_from_tracks(busy + [point('n', 117.02, 34.80, '2026-09-18 02:15:00')])
    assert len(centers) == 3 and centers[-1]['night_count'] == 1 and centers[-1]['lat'] == 34.8
    assert len(pcf.stay_points_from_tracks(busy)) == 3


def test_case_info_section_and_case_reference():
    info = {'jjbh': 'JJ-1', 'cjsj': '2026-09-18 02:40:00', 'cjxz': '紫薇花园3号楼', 'cljgnr': '入室盗窃', 'gisX': '116.93', 'gisY': '34.72'}
    text = t.markdown({'version': 'person-tables-v3', 'evidence': [], 'case_info': info})
    assert '### 案件信息' in text and 'JJ-1' in text and '入室盗窃' in text
    ref = t.case_reference({'case_info': info, 'confirmed': {}}, [])
    assert ref['number'] == 'JJ-1' and ref['time'] is not None
    d5 = s.score_d5_case([_track('t1', '2026-09-18 01:30:00')], ref)
    assert d5['status'] == 'available' and '案发点 JJ-1' in d5['evidence']


def test_model_time_question_without_options_gets_recent_choices():
    questions = question_contract.limit_time_options([{'header': '时间', 'question': '请填写开始时间与结束时间', 'options': []}])
    assert [o['label'][:4] for o in questions[0]['options']] == ['近7天（', '近15天', '近31天']


def test_person_to_case_incidents_never_ask_for_coordinates(provider, monkeypatch):
    import pytest
    from fastapi import HTTPException
    from control import native_tool_gate, person_case_flow
    from test_native_tool_execution import native_candidate
    from test_provider_flow import tool
    store = provider[0]; uid = provider[4]['uid']; row = native_candidate(provider, monkeypatch)
    snap = store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?', (row['id'],))['request_ciphertext'])
    snap['native_tool_context']['direction'] = 'person_to_case'
    with store.tx() as db:
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?', (store.encrypt(snap), row['id']))
    for count, code in ((3, 'person_case_centers_done'), (0, 'person_case_tracks_first')):
        monkeypatch.setattr(person_case_flow, 'pending_center', lambda *a, count=count, **k: (None, None, count))
        with pytest.raises(HTTPException) as exc:
            native_tool_gate.prepare(store, uid, 'ses_multi', row['message_id'], f'inc-{count}', tool('incidents'), {'radius_m': 500}, 1)
        assert exc.value.detail['code'] == code and '经度' not in json.dumps(exc.value.detail, ensure_ascii=False)


