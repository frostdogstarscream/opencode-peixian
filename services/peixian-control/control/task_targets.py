"""PR-5 target contracts: one person; no inferred account ownership or pair transfers."""
import re
from .scenario_versions import DATA151

VERSION = 'method-target-v1'
# Funds supports an exact original member_ref match. Counterparty accounts are
# deliberately not converted into people by removing a suffix from an account name.
CONTRACTS = {
    'funds': {'query_scope': 'fixed_snapshot', 'supported_target_modes': ['scenario_subject', 'record_filter'],
              'supported_entity_types': ['person'], 'max_targets': 1, 'filter_fields': ['member_ref']},
    **{m: {'query_scope': 'fixed_snapshot', 'supported_target_modes': ['scenario_subject'],
           'supported_entity_types': ['person'], 'max_targets': 1, 'filter_fields': []}
       for m in ('night', 'companions', 'relations', 'vehicles')},
}


def visible(store, uid, sid, scene, profile=None):
    from .scenario_context import boundary
    _, after = boundary(store, uid, sid)
    subject = DATA151['scenarios'][scene]['subject_ref']
    names = {subject}
    # Only successful, code-compiled records from this account/session/generation.
    rows = store.rows("SELECT request_ciphertext FROM business_runs WHERE uid=? AND session_id=? AND rowid>? AND status='completed' ORDER BY rowid DESC LIMIT 100", (uid, sid, after))
    for row in rows:
        snap = store.decrypt(row['request_ciphertext'])
        if profile:
            from .agents.runtime import frozen_identity
            if frozen_identity(snap)!=profile.id:continue
        plan, state = snap.get('facts_plan', {}), snap.get('facts_state', {})
        if plan.get('scenario', {}).get('scenario_id') != scene or not state.get('table'):
            continue
        source_ids = {x for fact in state['table'].get('facts', []) for x in fact.get('source_ids', [])}
        for module, value in state.get('modules', {}).items():
            if value.get('status') != 'completed':
                continue
            for record in value.get('response', {}).get('items', []):
                if record.get('record_id') not in source_ids:
                    continue
                fields = ('member_ref', 'co_member_ref') if module == 'portrait' else ('member_ref',) if module in ('funds', 'vehicle', 'calls') else ('group_ref',) if module in ('night', 'lookup') else ()
                names.update(record[f] for f in fields if isinstance(record.get(f), str))
    return names


def resolve(store, uid, sid, scene, text, methods, profile=None):
    subject = DATA151['scenarios'][scene]['subject_ref']
    names = visible(store, uid, sid, scene, profile)
    found = sorted(name for name in names if name in text)
    # Text with an unrecognised name must never silently default to the subject.
    residual = text
    for name in found:
        residual = residual.replace(name, '')
    if not found and re.search(r'他|她|这两个人|他们|她们|两人|另一个|其他人', text):
        return {'status': 'ambiguous', 'target_refs': [], 'reason': 'target_confirmation_required'}
    # Fixed grammar fails closed on unknown names and ranges, even without 的.
    vocabulary = ('涉赌案件资料整理', '盗窃案件时空资料核对', '涉赌', '盗窃', '场景', '时空', '当前对象', '主对象',
                  '资金往来', '夜间活动', '夜间', '夜晚', '晚上', '夜里', '资金', '流水', '转账', '收支',
                  '同行', '同框', '共现', '共同出现', '一起出现', '已有关系', '之间的关系', '有没有关系',
                  '关联互查', '关系资料', '综合分析', '综合整理', '综合看看', '全面整理', '总流程',
                  '重新查询', '重新核对', '重新查', '再取一次', '最新资料', '最新', '更新一下',
                  '请帮我', '帮我', '请', '看看', '查询', '分析', '核对', '整理', '查一下', '统计',
                  '记录', '资料', '一下', '情况', '明细', '展示', '列出', '的', '和', '与', '是否', '有', '吗')
    if profile:vocabulary+=('车辆','车牌','卡口','过车','驾乘','凌晨','综合核对','全面分析','有没有')
    for word in sorted(vocabulary, key=len, reverse=True):
        residual = residual.replace(word, '')
    if re.search(r'[\w\u4e00-\u9fff]', residual):
        return {'status': 'unsupported', 'target_refs': [], 'reason': 'unsupported_target_scope'}
    targets = found or [subject]
    if len(targets) != 1:
        return {'status': 'unsupported', 'target_refs': targets, 'reason': 'unsupported_target_scope'}
    mode = 'scenario_subject' if targets == [subject] else 'record_filter'
    if any(mode not in CONTRACTS[m]['supported_target_modes'] for m in methods):
        return {'status': 'unsupported', 'target_refs': targets, 'reason': 'unsupported_target_scope'}
    return {'status': 'resolved', 'target_refs': targets, 'target_mode': mode,
            'contract_version': VERSION, **({'agent_target_profile':profile.data['target_contract_profile']} if profile else {}), 'filter_fields': ['member_ref'] if mode == 'record_filter' else []}
