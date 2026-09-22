import copy
import json
import pytest
from fastapi import HTTPException
from control import entity_graph as graphs, trusted_results, business_runs as runs
from control.execution_view import observed, attach, event_view
from control.source_display import source, complete
from test_control import context, P, create_user, login_user
from test_task_spec import task_env
from test_multi_agent import multi
from test_trusted_results import v6, enabled, finish


def result():
    records = [{'record_id': 'DEMO-' + str(i), 'module': 'portrait', 'snapshot_id': 'snapshot',
                'member_ref': '甲', 'co_member_ref': '乙' if i < 2 else '丙', 'kind': 'same_frame',
                'occurred_at': '2026-09-20T22:00:00+08:00'} for i in range(4)]
    return {'schema': 'peixian.analysis-result', 'version': '2.0', 'run_id': 'run-1', 'data_environment': 'synthetic',
            'records': records, 'claims': [{'type': 'fact', 'verification_status': 'approved', 'source_ids': [r['record_id']],
                'protected_fields': {'record_id': r['record_id'], 'snapshot_id': r['snapshot_id']}} for r in records],
            'data_usage': {'status': 'confirmed'}, 'generated_at': '2026-09-22T00:00:00Z'}


def test_graph_pages_replay_binding_and_no_dangling_edges():
    graph = graphs.build(result(), 'session'); secret = b'test-only'; cursor = None; ids = []
    for _ in range(4):
        page = graphs.page(graph, 'owner', secret, 2, 1, cursor)
        assert all(e['source'] in {n['id'] for n in page['nodes']} and e['target'] in {n['id'] for n in page['nodes']} for e in page['edges'])
        assert all(e['type'] == 'same_frame' for e in page['edges'])
        ids += [e['id'] for e in page['edges']]
        cursor = page['meta']['next_cursor']
    assert cursor is None and len(set(ids)) == 4
    first = graphs.page(graph, 'owner', secret, 2, 1)
    for uid, limit, token in [('other', 2, first['meta']['next_cursor']), ('owner', 3, first['meta']['next_cursor']), ('owner', 2, 'malformed')]:
        with pytest.raises(HTTPException): graphs.page(graph, uid, secret, limit, 1, token)


def test_unapproved_and_mixed_snapshot_never_get_graph_edges():
    value = result(); value['claims'][0]['protected_fields']['snapshot_id'] = 'wrong'; value['claims'][1]['verification_status'] = 'pending'
    graph = graphs.build(value, 'session')
    assert len(graph['edges']) == 2 and graph['status'] == 'partial'
    value['claims'] = []
    assert not graphs.build(value, 'session')['edges']


def test_funds_preserve_ledger_not_fabricated_transfer_chain():
    value = result()
    for r in value['records']:
        r.update(module='funds', amount_minor=780000, counterparty_ref='账户乙', direction='out')
    graph = graphs.build(value, 's')
    assert len(graph['edges']) == 4
    assert all(e['type'] == 'ledger_record' and not e['directed'] for e in graph['edges'])
    assert not any(n['type'] == 'account' for n in graph['nodes'])


def test_bounded_paths_components_and_degree():
    graph = graphs.build(result(), 's'); nodes = graph['nodes']
    path = graphs.paths(graph, nodes[0]['id'], nodes[-1]['id'])
    assert path['found']
    assert len(path['paths'][0]['edge_ids']) == len(path['paths'][0]['node_ids']) - 1
    assert graphs.analysis(graph, 'communities', {})['analysis'][0]['metrics']['size'] == 3
    assert len(graphs.analysis(graph, 'centrality', {'method': 'degree'})['analysis']) == 3
    for algorithm, params in [('exec', {}), ('centrality', {'code': 'private'}), ('communities', {'method': 'degree'})]:
        with pytest.raises(HTTPException): graphs.analysis(graph, algorithm, params)


def test_expand_and_limits():
    graph = graphs.build(result(), 's'); key = graph['nodes'][0]['id']
    value = graphs.page(graph, 'owner', b'key', node_id=key, depth=2, relation_types=['same_frame'])
    assert value['meta']['mode'] == 'delta' and key in {n['id'] for n in value['nodes']}
    assert not graphs.page(graph, 'owner', b'key', node_id=key, relation_types=['same_trip'])['edges']
    for n, e in [(0, 1), (201, 1), (2, 401), (True, 2)]:
        with pytest.raises(HTTPException): graphs.page(graph, 'owner', b'key', n, e)


def test_graph_http_contract_and_owner_checks(enabled):
    s, app, admin, client, user, *_ = enabled
    row, _ = finish(enabled); rid = row['id']; path = P + '/sessions/ses_multi/runs/' + rid + '/graphs'
    assert client.get(path).json()['items'] == []
    frozen = result(); frozen['run_id'] = rid
    with s.tx() as db:
        db.execute('UPDATE run_results SET result_ciphertext=?,result_digest=? WHERE run_id=?', (s.encrypt(frozen), trusted_results.digest(frozen), rid))
    directory = client.get(path); assert directory.status_code == 200, directory.text
    gid = directory.json()['items'][0]['id']; url = path + '/' + gid
    response = client.get(url + '?node_limit=2&edge_limit=1'); assert response.status_code == 200, response.text
    page = response.json(); rev = page['meta']['data_revision']; nid = page['nodes'][0]['id']
    assert client.get(url + '/nodes/' + nid, params={'data_revision': rev}).status_code == 200
    assert client.get(url + '/nodes/' + nid, params={'data_revision': 'wrong'}).status_code == 409
    assert client.get(url + '/nodes/missing', params={'data_revision': rev}).status_code == 404
    assert client.post(url + '/expand', json={'node_id': nid, 'data_revision': rev},headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert admin.get(url).status_code == 403
    assert client.post(url + '/expand', json={'node_id': nid, 'data_revision': rev}).status_code == 200
    assert client.post(url + '/paths', json={'source_id': nid, 'target_id': nid, 'data_revision': rev}).json()['found']
    assert client.post(url + '/analysis/query', json={'algorithm': 'communities', 'data_revision': rev}).status_code == 200
    assert client.post(url + '/expand', json={'node_id': nid, 'data_revision': rev, 'url': 'forged'}).status_code == 422
    create_user(admin, 'graph-other'); other = login_user(app, 'graph-other')
    try:
        assert other.get(url).status_code == 404
        assert other.post(url + '/expand', json={'node_id': nid, 'data_revision': rev}).status_code == 404
        assert client.get(url.replace('ses_multi', 'other')).status_code == 404
    finally: other.__exit__(None, None, None)
    audits=s.rows("SELECT * FROM audit WHERE action LIKE 'graph.%'")
    assert audits and any(a['result']=='denied' for a in audits)
    assert all(json.loads(a['target']).get('request_id') for a in audits)
    from control.openapi import build_openapi
    from test_openapi import validator
    doc = build_openapi(app)
    validator(doc, 'GraphPage').validate(page)
    validator(doc, 'GraphDirectory').validate(directory.json())
    validator(doc, 'GraphNodeResponse').validate(client.get(url + '/nodes/' + nid, params={'data_revision': rev}).json())


def test_step_only_observed_skill_and_sanitized_plugin():
    snapshot = {'skills': [{'id': 'skill-a', 'name': '方法甲', 'version': 3}], 'plugins': []}
    part = {'id': 'part', 'callID': 'call', 'tool': 'skill', 'state': {'input': {'name': '方法甲'}, 'status': 'completed', 'output': 'private content'}}
    step = observed(snapshot, part)
    assert step['capability_id'] == 'skill-a' and step['capability_version'] == '3'
    assert step['result'] == {} and 'private content' not in json.dumps(step)
    part['state']['input']['name'] = 'selected-but-not-called'
    assert observed(snapshot, part)['capability_id'] is None
    snapshot['plugins'] = [{'id': 'plugin-a', 'name': '查询甲', 'version': '1.0', 'tools': ['query'], 'display': {'output_fields': ['returned_count', 'token', 'address']}}]
    part.update(tool='query'); part['state'].update(output=json.dumps({'returned_count': 4, 'token': 'secret', 'address': 'http://private', 'raw': 'private'}))
    step = observed(snapshot, part)
    assert step['result'] == {'returned_count': 4} and step['result_truncated'] and step['record_count'] == 4


def test_durable_steps_and_message_identity(enabled):
    s, _, _, _, user, *_ = enabled
    row, snapshot = finish(enabled)
    part = {'type': 'tool', 'id': 'part-one', 'messageID': 'assistant-one', 'callID': 'call-one', 'tool': 'skill', 'state': {'input': {'name': '方法甲'}, 'status': 'completed'}}
    snapshot['skills'] = [{'id': 'skill-a', 'name': '方法甲', 'version': 3}]
    meta = observed(snapshot, part)
    runs.event(s, row['id'], part['id'], 'skill', meta['name'], 'completed', 100, 110, meta['capability_id'], metadata=meta)
    event = s.one('SELECT * FROM run_events WHERE run_id=? AND event_key=?', (row['id'], part['id']))
    runs.event(s, row['id'], part['id'], 'skill', 'old', 'running', 99)
    assert s.one('SELECT * FROM run_events WHERE id=?', (event['id'],))['status'] == 'completed'
    from control.app import public_messages
    raw = [{'info': {'id': 'assistant-one', 'role': 'assistant', 'parentID': row['message_id']}, 'parts': [part]}]
    projected = attach(s, user['uid'], 'ses_multi', public_messages(raw))
    assert projected[0]['info']['run_id'] == row['id']
    assert projected[0]['parts'][0]['step_id'] == event['id']
    assert projected[0]['parts'][0]['execution']['capability_name'] == '方法甲'
    assert attach(s, user['uid'], 'another-session', public_messages(raw))[0]['info'].get('run_id') is None


def test_readable_sources_integer_money_and_unsupported_timestamp():
    value = source('funds', {'record_id': 'demo1', 'amount_minor': 780001, 'direction': 'out', 'occurred_at': '2026-09-14T12:14:00Z'})
    assert value['label'] == '资金流水记录 · 2026-09-14 20:14'
    assert '7800.01元' in value['content'] and value['record_id'] == 'demo1' and value['synthetic'] is True
    assert 'demo1' not in value['label']
    assert source('funds', {'record_id': 'x', 'occurred_at': 'private/path'})['occurred_at'] is None


def test_recommendations_are_bounded_information_requests():
    view = complete({'missing_details': [{'id': 'gap-1', 'category': 'source_missing', 'text': '车辆资料未取得', 'source_ids': []}], 'conclusions': [], 'clues': []})
    assert view['recommendations'][0]['gap_refs'] == ['gap-1']
    assert not view['recommendations'][0]['actionable'] and '下一步建议' in view['public_markdown']
    assert complete({})['next_steps_status'] == 'no_verified_suggestion'


def test_cursor_revision_conflict():
    graph = graphs.build(result(), 's'); key = b'key'
    cursor = graphs.page(graph, 'u', key, 2, 1)['meta']['next_cursor']
    changed = copy.deepcopy(graph); changed['data_revision'] = 'another'
    with pytest.raises(HTTPException) as exc: graphs.page(changed, 'u', key, 2, 1, cursor)
    assert exc.value.status_code == 409


def test_graph_empty_no_path_unknown_node_and_partial_without_cursor():
    graph = graphs.build(result(), 's')
    graph['nodes'].append({'id': 'isolated', 'type': 'person', 'label': '人员四', 'properties': {}, 'evidence_refs': []})
    assert graphs.paths(graph, graph['nodes'][0]['id'], 'isolated')['paths'] == []
    with pytest.raises(HTTPException) as exc: graphs.paths(graph, 'missing', 'isolated')
    assert exc.value.status_code == 404
    graph['status'] = 'partial'
    value = graphs.page(graph, 'u', b'key')
    assert value['meta']['truncated'] and value['meta']['next_cursor'] is None and value['meta']['truncation_reason']


def test_actual_compiler_to_graph(enabled):
    from test_trusted_results import test_compiled_facts_roundtrip
    test_compiled_facts_roundtrip(enabled, 'gambling-assistant', '核对同行')
    s, _, _, client, user, *_ = enabled
    row = s.one('SELECT * FROM business_runs ORDER BY rowid DESC LIMIT 1')
    value = trusted_results.read(s, user['uid'], 'ses_multi', row['id'])
    graph = graphs.build(value, 'ses_multi')
    assert graph['edges'] and all(e['type'] in ('same_frame', 'same_trip', 'same_vehicle') for e in graph['edges'])
    approved = {c['protected_fields']['record_id'] for c in value['claims'] if c['type'] == 'fact' and 'record_id' in c['protected_fields']}
    assert all(ref['id'] in approved for edge in graph['edges'] for ref in edge['evidence_refs'])
    assert client.get(P + '/sessions/ses_multi/runs/' + row['id'] + '/graphs').status_code == 200


def test_file_status_ownership_and_stable_id(enabled):
    import httpx
    s, app, admin, client, user, *_ = enabled
    old = app.state.http
    def response(request):
        assert request.url.path == '/files'
        return httpx.Response(200, json={'items': [{'id': 'file_demo', 'name': '合成.txt', 'status': 'partial', 'truncated': True, 'size': 10}]})
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(response))
    try:
        answer = client.get(P + '/files/file_demo')
        assert answer.status_code == 200, answer.text
        assert answer.json()['id'] == 'file_demo' and answer.json()['status'] == 'partial'
        assert client.get(P + '/files/file_missing').status_code == 404
        assert admin.get(P + '/files/file_demo').status_code == 403
    finally:
        admin.portal.call(app.state.http.aclose); app.state.http = old


def test_metadata_change_advances_cursor_and_terminal_does_not_regress(enabled):
    s, _, _, _, _, *_ = enabled; row, _ = finish(enabled)
    runs.event(s, row['id'], 'call', 'plugin', '查询', 'running', 100, metadata={'input_summary': '已确认范围'})
    first = s.one('SELECT * FROM run_events WHERE run_id=? AND event_key=?', (row['id'], 'call'))
    runs.event(s, row['id'], 'call', 'plugin', '查询', 'running', 100, metadata={'input_summary': '更新公开范围'})
    second = s.one('SELECT * FROM run_events WHERE id=?', (first['id'],))
    assert second['sequence'] > first['sequence'] and second['input_summary'] == '更新公开范围'


@pytest.mark.parametrize('count',[True,-1,1000001,'unknown'])
def test_invalid_tool_count_not_reported_as_zero(count):
    snapshot={'plugins':[{'id':'plugin','version':'1.0','tools':['query'],'display':{'output_fields':['returned_count','metric']}}]}
    step=observed(snapshot,{'id':'part','tool':'query','state':{'status':'completed','output':{'returned_count':count,'metric':float('nan')}}})
    assert step['result']=={} and '0 条' not in step['output_summary']


def test_graph_algorithm_time_budget(monkeypatch):
    graph=graphs.build(result(),'s')
    ticks=iter([0,2])
    from types import SimpleNamespace
    monkeypatch.setattr(graphs,'time',SimpleNamespace(monotonic=lambda:next(ticks)))
    with pytest.raises(HTTPException) as exc:graphs.analysis(graph,'communities',{})
    assert exc.value.status_code==503 and exc.value.detail['code']=='GRAPH_QUERY_TIMEOUT'
