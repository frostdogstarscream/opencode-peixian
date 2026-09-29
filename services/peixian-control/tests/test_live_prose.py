from types import SimpleNamespace

import pytest

from control import controlled_answer, live_push
from control.live_prose import COMPOSING, Pushes, visible

REF = 'person-' + 'a' * 32
ID = '320322199001011234'
IDS = {REF: ID}


class Store:
    def __init__(self, rows):
        self.run_rows = rows

    def rows(self, sql, args):
        return [r for r in self.run_rows if (r['uid'], r['session_id']) == args]

    def decrypt(self, value):
        return value

    def one(self, sql, args):
        return None


def run(status='running', snapshot=None):
    snap = snapshot or {'table_answer_policy': {'version': 'person-tables-v3', 'display_identities': IDS}}
    return {'id': 'run1', 'uid': 'u', 'session_id': 'ses', 'message_id': 'msg_user', 'assistant_id': None,
            'status': status, 'created': 1, 'request_ciphertext': snap}


@pytest.fixture
def pushed(monkeypatch):
    out = []
    monkeypatch.setattr(live_push, 'push', lambda uid, notice: out.append(notice))
    monkeypatch.setattr(controlled_answer, '_PUSHES', Pushes())
    return out


def test_prose_is_cut_at_fence_or_leading_json():
    assert visible('我先查询轨迹记录。\n```json\n{"format":1}', {}) == ('我先查询轨迹记录。', True)
    assert visible('已完成查询，整理如下：\n{"format":1}', {}) == ('已完成查询，整理如下：', True)
    assert visible('正在查询近7天的轨迹', {}, open_part=True) == ('正在查询近7天的轨迹', False)


def test_person_refs_are_revealed_and_an_unfinished_ref_is_held():
    assert visible(f'对象 {REF} 共有记录', IDS)[0] == f'对象 {ID} 共有记录'
    assert visible('对象 person-aaaa', IDS, open_part=True)[0] == '对象'
    assert visible('查询结果如下 `', IDS, open_part=True)[0] == '查询结果如下'


def test_english_or_empty_prose_is_not_shown():
    assert visible('Let me check the records first.', {}) == ('', False)
    assert visible('OK 我 will call the tracks tool now', {}) == ('', False)
    assert visible('{"format":1}', {}) == ('', True)


def test_messages_show_filtered_prose_while_live_then_the_table(monkeypatch):
    store = Store([run()])
    values = [{'info': {'id': 'msg_a', 'parentID': 'msg_user', 'role': 'assistant'},
               'parts': [{'id': 'p0', 'type': 'reasoning', 'text': 'thinking'},
                         {'id': 'p1', 'type': 'text', 'text': f'正在核对 {REF} 的轨迹。\n```json\n{{}}', 'time': {'start': 1}},
                         {'id': 'p2', 'type': 'tool', 'tool': 'tracks'}]}]
    projected = controlled_answer.messages(store, 'u', 'ses', values)
    assert [p['id'] for p in projected[0]['parts']] == ['p1', 'p2']
    assert projected[0]['parts'][0]['text'] == f'正在核对 {ID} 的轨迹。'

    store = Store([{**run('completed'), 'assistant_id': 'msg_a'}])
    values[0]['parts'] = [{'id': 'p1', 'type': 'text', 'text': '正在核对。'}]
    monkeypatch.setattr(controlled_answer, 'final_body', lambda *a: '### 平台表格')
    projected = controlled_answer.messages(store, 'u', 'ses', values)
    assert [p['text'] for p in projected[0]['parts']] == ['### 平台表格']


def test_deltas_carry_offsets_and_composing_starts_once(pushed):
    app = SimpleNamespace(state=SimpleNamespace(live_text=SimpleNamespace(text=lambda *a: cache['text'])))
    cache = {'text': ''}
    controlled_answer._PUSHES.target('u', 'msg_a', {'run_id': 'run1', 'identities': IDS})

    def delta(text):
        cache['text'] = text
        controlled_answer.push_prose(app, 'u', {'type': 'message.part.delta', 'properties': {
            'sessionID': 'ses_1', 'messageID': 'msg_a', 'partID': 'prt_1', 'field': 'text'}})

    delta('正在查询')
    delta(f'正在查询 person-aa')
    delta(f'正在查询 {REF} 的轨迹。')
    delta(f'正在查询 {REF} 的轨迹。\n```json\n{{"a"')
    delta(f'正在查询 {REF} 的轨迹。\n```json\n{{"a":1}}')
    texts = [(n['offset'], n['text']) for n in pushed if n['type'] == 'answer.delta']
    assert texts == [(0, '正在查询'), (4, f' {ID} 的轨迹。')]
    assert all(n['version'] == 'live-push-v1' and n['run_id'] == 'run1' for n in pushed)
    progress = [n for n in pushed if n['type'] == 'run.progress']
    assert [(n['phase'], n['label']) for n in progress] == [COMPOSING]


def test_gambling_answer_policy_still_blocks_model_text():
    store = Store([run(snapshot={'answer_policy_version': controlled_answer.VERSION})])
    info = {'id': 'msg_a', 'parentID': 'msg_user', 'role': 'assistant'}
    assert controlled_answer.message_target(store, 'u', 'ses', info) == (True, None)
    values = [{'info': info, 'parts': [{'id': 'p1', 'type': 'text', 'text': '中文说明'}]}]
    assert controlled_answer.messages(store, 'u', 'ses', values)[0]['parts'] == []


def test_table_run_without_live_status_blocks_until_final():
    store = Store([run('reconciling')])
    info = {'id': 'msg_a', 'parentID': 'msg_user', 'role': 'assistant'}
    assert controlled_answer.message_target(store, 'u', 'ses', info) == (True, None)
    live = Store([run()])
    blocked, target = controlled_answer.message_target(live, 'u', 'ses', info)
    assert blocked is False and target == {'run_id': 'run1', 'identities': IDS}
