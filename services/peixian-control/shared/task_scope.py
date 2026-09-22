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


def validate_target(plan):
    """Validate the full frozen target chain before any plugin invocation."""
    task=plan.get('agent_task')
    if not task:return  # Immutable plans predating TaskSpec.
    target=plan.get('task_target') or {};scene=plan.get('scenario') or {}
    # Bind every frozen module response contract to the scenario's recorded
    # data snapshot. Do not consult today's fixtures or accept a substituted
    # module version as the expected response for an already frozen Run.
    records=plan.get('records') or {};modules=plan.get('modules') or []
    expected_snapshot=scene.get('records_snapshot_id')
    if (not isinstance(expected_snapshot,str) or not expected_snapshot
        or set(records)!=set(modules)
        or any(not isinstance(records[m],dict) or records[m].get('module')!=m
               or records[m].get('snapshot_id')!=expected_snapshot for m in modules)):
        raise ValueError('task_records_snapshot_mismatch')
    refs=target.get('target_refs');mode=target.get('target_mode')
    if (target.get('status')!='resolved' or target.get('contract_version') not in ('method-target-v1','method-target-v2')
        or not isinstance(refs,list) or len(refs)!=1 or not isinstance(refs[0],str) or not refs[0]
        or refs!=task.get('target_refs') or mode!=task.get('target_mode') or scene.get('subject_ref')!=refs[0]
        or task.get('methods')!=plan.get('methods') or task.get('query_mode')!='new_query'):
        raise ValueError('task_target_mismatch')
    entity=target.get('entity_type','person')
    vehicle=entity=='vehicle'
    if vehicle:
        if (target['contract_version']!='method-target-v2' or task.get('schema_version')!='task-spec-v3'
            or task.get('agent_id')!='theft-assistant' or plan.get('agent_profile',{}).get('id')!='theft-assistant'
            or task['methods']!=['vehicles'] or mode!='record_filter'
            or scene.get('target_filter')!={'version':'method-target-v2','type':'vehicle','field':'group_ref','ref':refs[0]}):
            raise ValueError('task_target_mismatch')
    elif entity!='person' or scene.get('target_filter') is not None:
        raise ValueError('task_target_mismatch')
    if mode=='record_filter':
        if target.get('filter_fields')!=(['group_ref'] if vehicle else ['member_ref']) or (not vehicle and task['methods']!=['funds']):raise ValueError('task_target_mismatch')
    elif mode!='scenario_subject' or target.get('filter_fields')!=[]:
        raise ValueError('task_target_mismatch')
