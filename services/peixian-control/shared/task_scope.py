"""Exact target projection over already validated frozen responses (no I/O)."""
import copy


def scoped(plan, module, response, field='items'):
    value=copy.deepcopy(response)
    target=plan.get('task_target')
    if not target or target['target_mode']=='scenario_subject':return value
    version=target.get('contract_version')
    entity=target.get('entity_type','person')
    key='group_ref' if version=='method-target-v2' and entity=='vehicle' else 'member_ref'
    if (version not in ('method-target-v1','method-target-v2') or target['target_mode']!='record_filter'
        or len(target['target_refs'])!=1 or target['filter_fields']!=[key]
        or (key=='member_ref' and (module!='funds' or entity!='person'))
        or (key=='group_ref' and (module!='vehicle' or plan.get('agent_profile',{}).get('id')!='theft-assistant'
            or plan.get('scenario',{}).get('target_filter')!={'version':'method-target-v2','type':'vehicle','field':'group_ref','ref':target['target_refs'][0]}))):
        raise ValueError('unsupported_target_contract')
    records=[r for r in value[field] if r.get(key)==target['target_refs'][0]]
    value[field]=records
    value['source_returned_count']=value['returned_count']
    value['returned_count']=value['total_count']=len(records)
    if 'provenance' in value:
        ids={r['record_id'] for r in records}
        value['provenance']=[r for r in value['provenance'] if r.get('record_id') in ids]
    value['target_scope']={'mode':'record_filter','target_refs':target['target_refs'],
                           'description':'仅筛选本轮固定快照中明确归属目标对象的记录，不代表全库查询。'}
    return value
