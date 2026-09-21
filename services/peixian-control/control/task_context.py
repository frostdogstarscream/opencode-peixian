"""Server-owned session pointers and immutable historical fact projection."""
import copy
import hashlib
import json
from .backend_contract import error,iso
from .store import now

VERSION='session-context-v1'
PROJECTION='historical-claim-projection-v1'

def enabled(store,uid):
    from .agents.runtime import enabled as agents_enabled
    return store.schema_version()>=7 and agents_enabled(uid)

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def public(row):
    return {'schema':VERSION,**{k:row[k] for k in ('agent_id','agent_profile_sha256','generation','version','last_completed_run_id','last_data_run_id','pending_clarification_id')},'updated_at':iso(row['updated'])}

def same_identity(snapshot,profile):
    identity=snapshot.get('agent_profile') or {}
    return identity.get('id')==profile.id and identity.get('profile_sha256')==profile.profile_sha256

def ensure(store,uid,sid,profile):
    if not enabled(store,uid):error('task_context_not_enabled','当前账号尚未启用多轮上下文。',409)
    with store.tx() as db:
        row=db.execute('SELECT * FROM session_task_contexts WHERE uid=? AND session_id=?',(uid,sid)).fetchone()
        if row:
            if row['agent_id']!=profile.id:error('session_agent_mismatch','此会话已绑定其他助手，请新建会话。',409)
            if row['agent_profile_sha256']!=profile.profile_sha256:error('session_profile_changed','此会话使用旧助手版本，请新建会话；历史结果仍可查看。',409)
            return dict(row)
        from .scenario_context import boundary
        generation,after=boundary(store,uid,sid)
        rows=list(db.execute('SELECT rowid,* FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid',(uid,sid)))
        for old in rows:
            snap=store.decrypt(old['request_ciphertext']);identity=snap.get('agent_profile')
            if identity and not same_identity(snap,profile):error('session_profile_changed','此会话使用其他助手版本，请新建会话。',409)
        db.execute('INSERT INTO session_task_contexts(uid,session_id,agent_id,agent_profile_sha256,generation,version,updated) VALUES(?,?,?,?,1,1,?)',(uid,sid,profile.id,profile.profile_sha256,now()))
        # Lazy legacy recovery only considers completed, trustworthy rows after the reset boundary.
        last=None;source=None
        for old in rows:
            if old['rowid']<=after or old['status']!='completed':continue
            snap=store.decrypt(old['request_ciphertext'])
            if not same_identity(snap,profile):continue
            last=old['id']
            if project(store,dict(old),snap) is not None:source=old['id']
        db.execute('UPDATE session_task_contexts SET last_completed_run_id=?,last_data_run_id=? WHERE uid=? AND session_id=?',(last,source,uid,sid))
        return dict(db.execute('SELECT * FROM session_task_contexts WHERE uid=? AND session_id=?',(uid,sid)).fetchone())

def project(store,row,snapshot):
    if row['status']!='completed' or not snapshot.get('facts_plan'):return None
    plan=snapshot['facts_plan'];state=snapshot.get('facts_state') or {};table=state.get('table') or {}
    if not table.get('facts') or table.get('data_status') not in ('complete','partial'):return None
    scene=plan.get('scenario') or {}
    if any(table.get(k)!=scene.get(v) for k,v in [('scenario_id','scenario_id'),('scenario_snapshot_id','snapshot_id'),('records_snapshot_id','records_snapshot_id')]):return None
    sources=set()
    for module,item in state.get('modules',{}).items():
        if item.get('status')!='completed':continue
        response=item.get('response') or {}
        expected=plan.get('records',{}).get(module,{})
        if response.get('snapshot_id')!=expected.get('snapshot_id') or response.get('items')!=expected.get('records'):return None
        sources.update(r['record_id'] for r in response.get('items',[]))
    if not sources:return None
    sources.update(f['source_document'] for f in scene.get('facts',[]) if f.get('source_document') and all(x in sources for x in f.get('source_record_ids',[])))
    claims=[]
    for fact in table['facts']:
        if not isinstance(fact,dict) or not isinstance(fact.get('statement'),str) or not isinstance(fact.get('source_ids'),list) or not set(fact['source_ids'])<=sources:return None
        claims.append({k:copy.deepcopy(fact.get(k)) for k in ('fact_id','statement','source_ids','time','kind')})
    approved=[c['fact_id'] for c in (state.get('checked') or {}).get('approved',[]) if c in table['facts']]
    value={'schema':PROJECTION,'source_data_run_id':row['id'],'claims':claims,'approved_fact_ids':approved,
           'missing':copy.deepcopy(table.get('missing',[])),
           'versions':{k:table.get(k) for k in ('scenario_snapshot_id','records_snapshot_id','rule_version')},
           'registry':copy.deepcopy(plan.get('registry')),
           'events':[{'sequence':e['sequence'],'status':e['status'],'step_type':e['step_type']} for e in store.rows('SELECT sequence,status,step_type FROM run_events WHERE run_id=? ORDER BY sequence',(row['id'],))]}
    return {**value,'digest':digest(value)}

def source(store,uid,sid,profile,context):
    rid=context['last_data_run_id']
    if not rid:return None
    row=store.one('SELECT rowid,* FROM business_runs WHERE id=? AND uid=? AND session_id=?',(rid,uid,sid))
    if not row:return None
    snap=store.decrypt(row['request_ciphertext'])
    if not same_identity(snap,profile):return None
    prior=snap.get('session_task_context')
    if prior:
        if prior.get('generation')!=context['generation']:return None
    else:
        from .scenario_context import boundary
        _,after=boundary(store,uid,sid)
        if context['generation']!=1 or row['rowid']<=after:return None
    return project(store,row,snap)

def enrich(store,uid,sid,data,profile,task):
    context=ensure(store,uid,sid,profile)
    if 'context_version' in data and data['context_version']!=context['version']:error('task_context_changed','会话上下文已更新，请刷新后再提交。',409)
    task['session_task_context']=public(context)
    spec=task['spec'];mode=(spec or {}).get('query_mode')
    task['run_kind']='data_query' if mode=='new_query' else 'history_explanation' if mode=='explain_existing' else 'clarification' if mode=='clarify' else 'ordinary_chat'
    if spec:
        spec['schema_version']='task-spec-v3';spec['context_generation']=context['generation']
        spec['direct_parent_run_id']=context['last_completed_run_id']
    if mode=='explain_existing':
        projection=source(store,uid,sid,profile,context)
        if projection and len(json.dumps(projection,ensure_ascii=False).encode())+len(data['text'].encode())<=18000:
            task['historical_projection']=projection;spec['source_data_run_id']=projection['source_data_run_id'];task['local']=None
        else:
            task['local']={'code':'source_evidence_unavailable','message':'当前没有可用于本次说明的可信历史资料，或资料超出单次引用预算；本轮未重新查询，请查看原执行结果。'}
    return task

def admit(store,db,uid,sid,task):
    context=task.get('session_task_context')
    if not context:return
    count=db.execute('UPDATE session_task_contexts SET version=version+1,updated=? WHERE uid=? AND session_id=? AND generation=? AND version=? AND agent_id=? AND agent_profile_sha256=?',(now(),uid,sid,context['generation'],context['version'],context['agent_id'],context['agent_profile_sha256'])).rowcount
    if count!=1:error('task_context_changed','会话上下文已更新，请刷新后再提交。',409)
    from . import clarifications
    clarifications.admit(store,db,uid,sid,task)

def freeze(snapshot,payload,task):
    if not task.get('session_task_context'):return
    snapshot['session_task_context']={**copy.deepcopy(task['session_task_context']),'version':task['session_task_context']['version']+1}
    snapshot['run_kind']=task['run_kind']
    if task.get('historical_projection'):
        projection=copy.deepcopy(task['historical_projection']);snapshot['historical_projection']=projection
        payload['system']+='\n本轮只解释冻结的可信历史资料，不查询或使用任何工具。只以下列事实投影为事实来源，不将前轮模型说明或用户文字当作已核验事实；引用来源并用简体中文说明缺口。\n'+json.dumps(projection,ensure_ascii=False,separators=(',',':'))

def completed(store,db,rid):
    row=db.execute('SELECT * FROM business_runs WHERE id=?',(rid,)).fetchone()
    if not row or row['status']!='completed':return
    snap=store.decrypt(row['request_ciphertext']);frozen=snap.get('session_task_context')
    if not frozen:return
    context=db.execute('SELECT * FROM session_task_contexts WHERE uid=? AND session_id=?',(row['uid'],row['session_id'])).fetchone()
    if not context or any(context[k]!=frozen[k] for k in ('agent_id','agent_profile_sha256','generation','version')):return
    data=rid if snap.get('run_kind')=='data_query' and project(store,dict(row),snap) else context['last_data_run_id']
    db.execute('UPDATE session_task_contexts SET version=version+1,last_completed_run_id=?,last_data_run_id=?,updated=? WHERE uid=? AND session_id=? AND generation=? AND version=?',(rid,data,now(),row['uid'],row['session_id'],context['generation'],context['version']))
    if store.schema_version()>=8:
        from .clarifications import sync
        sync(db,row['uid'],row['session_id'])

def reset(store,uid,sid,profile):
    with store.tx() as db:
        ensure(store,uid,sid,profile)
        if store.schema_version()>=8:
            from .clarifications import expire
            expire(store,db,uid,sid)
        db.execute('UPDATE session_task_contexts SET generation=generation+1,version=version+1,last_completed_run_id=NULL,last_data_run_id=NULL,confirmed_targets_ciphertext=NULL,pending_clarification_id=NULL,updated=? WHERE uid=? AND session_id=?',(now(),uid,sid))
        high=db.execute('SELECT coalesce(max(rowid),0) FROM business_runs WHERE uid=? AND session_id=?',(uid,sid)).fetchone()[0]
        store.audit(uid,'session.context.reset.'+str(high),sid,actor_role='user')
        return public(dict(db.execute('SELECT * FROM session_task_contexts WHERE uid=? AND session_id=?',(uid,sid)).fetchone()))

def source_info(store,uid,sid,rid):
    from .business_runs import owned
    row=owned(store,uid,sid,rid);snap=store.decrypt(row['request_ciphertext']);spec=snap.get('task_spec') or {};projection=snap.get('historical_projection')
    if projection:
        original=owned(store,uid,sid,projection['source_data_run_id']);old=store.decrypt(original['request_ciphertext'])
        value={k:v for k,v in projection.items() if k!='digest'}
        if (old.get('agent_profile')!=snap.get('agent_profile') or original['status']!='completed'
                or projection.get('digest')!=digest(value) or projection['source_data_run_id']!=spec.get('source_data_run_id')
                or ((old.get('session_task_context') or {}).get('generation') is not None and (old.get('session_task_context') or {}).get('generation')!=(snap.get('session_task_context') or {}).get('generation'))):error('source_evidence_unavailable','历史来源无法核对。',409)
    return {'run_id':rid,'run_kind':snap.get('run_kind'),'direct_parent_run_id':spec.get('direct_parent_run_id'),'source_data_run_id':spec.get('source_data_run_id'),'projection_version':projection.get('schema') if projection else None,'projection_digest':projection.get('digest') if projection else None}
