"""Exact target projection over already validated frozen responses (no I/O)."""
import copy


def scoped(plan, module, response, field='items'):
    value=copy.deepcopy(response)
    target=plan.get('task_target')
    if not target or target['target_mode']=='scenario_subject':return value
    if (target.get('contract_version')!='method-target-v1' or target['target_mode']!='record_filter'
        or module!='funds' or len(target['target_refs'])!=1 or target['filter_fields']!=['member_ref']):
        raise ValueError('unsupported_target_contract')
    records=[r for r in value[field] if r.get('member_ref')==target['target_refs'][0]]
    value[field]=records
    value['source_returned_count']=value['returned_count']
    value['returned_count']=value['total_count']=len(records)
    if 'provenance' in value:
        ids={r['record_id'] for r in records}
        value['provenance']=[r for r in value['provenance'] if r.get('record_id') in ids]
    value['target_scope']={'mode':'record_filter','target_refs':target['target_refs'],
                           'description':'仅筛选本轮固定快照中明确归属目标对象的记录，不代表全库查询。'}
    return value
