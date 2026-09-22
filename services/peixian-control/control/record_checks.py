"""Code verifies vehicle record facts independently of model-selected summaries.

No new collection: exact frozen source response, durable call receipts, rule
bindings, object/window membership, and the compiler's record template must match.
The result never approves model prose or scenario annotations.
"""
VERSION = 'vehicle-record-check-v1'


def verify(snapshot, events):
    from .trusted_results import confirmed_inputs, local, digest
    plan = snapshot.get('facts_plan') or {}
    table = (snapshot.get('facts_state') or {}).get('table') or {}
    scene = plan.get('scenario') or {}
    approved, rejected = [], []
    if snapshot.get('record_check_version') != VERSION or 'vehicle' not in plan.get('modules', []):
        return None
    try:
        valid, records, invalid = confirmed_inputs(snapshot, events)
        bindings = [b for b in scene.get('rule_bindings', []) if b['module'] in valid]
        if ('vehicle' not in valid or 'vehicle' in invalid or table.get('rule_executions') != bindings
            or table.get('rule_version') != plan.get('facts_rule_version')
            or any(table.get(k) != scene.get(v) for k,v in (
                ('scenario_id','scenario_id'),('scenario_snapshot_id','snapshot_id'),('records_snapshot_id','records_snapshot_id')))):
            raise ValueError('record_context_mismatch')
        rows = valid['vehicle']
        summary = next((s for s in table.get('summary', []) if s.get('module') == 'vehicle'), {})
        dates = sorted({local(r['occurred_at']).date().isoformat() for r in rows if r.get('occurred_at')})
        nights = sum(bool(r.get('occurred_at')) and (local(r['occurred_at']).hour >= 22 or local(r['occurred_at']).hour < 6) for r in rows)
        if (summary.get('count'),summary.get('dates'),summary.get('night_count')) != (len(rows),dates,nights):
            raise ValueError('record_summary_mismatch')
        for record in rows:
            rid = record['record_id']
            facts = [f for f in table.get('facts', []) if f.get('fact_id') == rid]
            if any(not isinstance(record.get(k),str) or not record[k] for k in ('group_ref','member_ref','direction','device_ref')):
                rejected.append(rid); continue
            at = local(record['occurred_at']).isoformat(timespec='seconds') if record.get('occurred_at') else '资料未提供时间'
            statement = f"{scene['subject_ref']}，{at}，车辆 {record['group_ref']}，{record['direction']}，设备 {record['device_ref']}；不能据不同时间共用车辆推导同乘。"
            expected = {'fact_id':rid,'statement':statement,'source_ids':[rid], 'time':record.get('occurred_at') or '', 'kind':'record'}
            if facts != [expected]:rejected.append(rid); continue
            approved.append(expected)
    except (ValueError, KeyError, TypeError):
        approved=[];rejected=['record_context_mismatch']
    return {'version':VERSION,'scenario_id':scene.get('scenario_id'),
            'scenario_snapshot_id':scene.get('snapshot_id'),'records_snapshot_id':scene.get('records_snapshot_id'),
            'table_digest':digest(table),'approved':approved,'rejected':rejected}
