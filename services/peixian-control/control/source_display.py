"""Readable source labels and bounded, code-owned follow-up suggestions."""
from datetime import datetime

LABELS = {'funds': '资金流水记录', 'trajectory': '夜间观测记录', 'companion': '明确同行记录',
          'vehicle': '车辆记录', 'place': '地点来源记录', 'relation': '已有关系记录'}


def source(kind, record, synthetic=True):
    at = record.get('occurred_at'); shown = '时间未提供'
    if isinstance(at, str):
        try:
            value = datetime.fromisoformat(at.replace('Z', '+00:00'))
            if value.tzinfo is not None:
                from datetime import timezone, timedelta
                shown = value.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
            else:
                at = None
        except ValueError:
            at = None
    title = LABELS.get(kind, '来源记录')
    description = '本轮已取得的' + title + '，仅说明该条资料中的记录。'
    if kind == 'funds' and type(record.get('amount_minor')) is int:
        amount = record['amount_minor']; sign = '-' if amount < 0 else ''; amount = abs(amount)
        direction = {'in': '收入', 'out': '支出', 'income': '收入', 'expense': '支出'}.get(record.get('direction'), '收支方向未明确')
        description = f'原始流水：{direction}，{sign}{amount // 100}.{amount % 100:02d}元；不合并双边记录，不据此推断资金用途。'
    return {'type': kind, 'label': title + ' · ' + shown, 'content': description,
            'record_id': record['record_id'], 'source_ids': [record['record_id']],
            'occurred_at': at, 'synthetic': synthetic, 'verification_status': 'source_verified'}


def complete(view):
    """Only invoked on a newly built, trusted view, never on assistant prose."""
    gaps = view.get('missing_details', [])
    recommendations = []
    for category in ('source_missing', 'verification_pending', 'scope_limit'):
        related = [g for g in gaps if g['category'] == category]
        if not related:
            continue
        text = {'source_missing': '先补齐未取得的资料，再核对相关问题；当前缺少记录不表示没有发生。',
                'verification_pending': '请先核对未完成步骤和对应来源，暂不采用未核对内容形成结论。',
                'scope_limit': '如需扩大时间或对象范围，请先确认资料接口支持；当前结论仅适用于已注明范围。'}[category]
        recommendations.append({'id': 'next-' + category, 'type': 'manual_review' if category == 'verification_pending' else 'request_information',
                                'text': text, 'gap_refs': [g['id'] for g in related], 'source_ids': [], 'actionable': False})
    view['recommendations'] = recommendations
    view['next_steps_status'] = 'available' if recommendations else 'no_verified_suggestion'
    view['next_steps'] = '\n'.join('- ' + r['text'] for r in recommendations)
    lines = []
    if view.get('conclusions'):
        lines += ['### 已核对结果'] + ['- ' + c['text'] for c in view['conclusions'][:5]]
    if view.get('clues'):
        lines += ['', '### 来源依据']
        for clue in view['clues']:
            for item in clue.get('evidence', [])[:3]:
                lines.append('- ' + item['label'] + '：' + item['content'])
    if gaps:
        lines += ['', '### 资料范围与待核对项'] + ['- ' + g['text'] for g in gaps]
    if recommendations:
        lines += ['', '### 下一步建议', view['next_steps']]
    view['public_markdown'] = '\n'.join(lines).strip()
    return view
