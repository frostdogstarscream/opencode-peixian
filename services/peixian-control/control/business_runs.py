"""Durable user-level execution records. Never retry an ambiguous provider dispatch."""
import hashlib
import hmac
import json
import sqlite3
import uuid
from .backend_contract import error, iso, require_v6
from .store import ident, now, encode

TERMINAL=('completed','failed','cancelled')
ACTIVE=('queued','running','cancelling','reconciling')


def normalized(data):
    value=dict(data)
    from .agents.registry import require
    if 'agent_id' in value:require(value['agent_id'])
    key=value.get('client_request_id') or str(uuid.uuid4())
    try:uuid.UUID(key)
    except (ValueError,TypeError,AttributeError):error('invalid_request_id','client_request_id 必须为UUID',422,{'client_request_id':'UUID required'})
    value['client_request_id']=key
    if value.get('mode','standard')!='standard':error('unsupported_mode','首版仅支持standard模式',422,{'mode':'standard'})
    value.setdefault('mode','standard')
    for field in ('skill_ids','plugin_ids','file_ids'):
        value.setdefault(field,[])
        if not isinstance(value[field],list) or len(value[field])>5 or any(not isinstance(x,str) for x in value[field]) or len(set(value[field]))!=len(value[field]):
            error('invalid_selection','每类最多选择五个不重复资源',422,{field:'最多五个不同ID'})
    return value


def fingerprint(store, data):
    return hmac.new(store.worker_key.encode(),json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def receipt(row):
    return {'accepted':True,'run_id':row['id'],'message_id':row['message_id']}


def replay(store, uid, sid, data):
    row=store.one('SELECT * FROM business_runs WHERE uid=? AND session_id=? AND request_key=?',(uid,sid,data['client_request_id']))
    if row:
        if not hmac.compare_digest(row['request_hash'],fingerprint(store,data)):error('request_conflict','同一请求标识对应不同内容',409)
        return receipt(row)


def submit(store, user, sid, data, payload, applied, revision, parent=None, draft=None, trial=None, context=None, task=None):
    from .app import current_authority
    require_v6(store)
    identity=ident();message='msg_'+ident();timestamp=now();payload={**payload,'messageID':message}
    snapshot={'request':data,'payload':payload,'models':[x['id'] for x in applied.get('models',[])],
              'plugins':[{'id':x['id'],'version':x.get('version'),'tools':x.get('manifest',{}).get('tools',[])} for x in applied.get('plugins',[])],
              'skills':[{'id':x['id'],'name':x['name'],'version':x.get('version')} for x in applied.get('skills',[])]}
    if context is not None:snapshot['scenario_context']={**context,'revision':revision}
    with store.tx() as db:
        current_authority(db,user)
        row=db.execute('SELECT * FROM business_runs WHERE uid=? AND session_id=? AND request_key=?',(user['uid'],sid,data['client_request_id'])).fetchone()
        if row:
            if row['request_hash']!=fingerprint(store,data):error('request_conflict','同一请求标识对应不同内容',409)
            return receipt(row)
        from .agents import runtime as agents
        profile=agents.select(user['uid'],data)
        agents.session(store,user['uid'],sid,profile)
        if task is not None:
            from . import task_spec
            fresh = task_spec.resolve(store,user['uid'],sid,data,applied)
            if fresh.get('agent_profile')!=task.get('agent_profile'):error('agent_profile_changed','助手版本已变化，请刷新后重新确认。',409)
            if fresh != task:error('task_context_changed','任务范围或能力已变化，请刷新后重新确认。',409)
        if context is not None:
            from .scenario_context import boundary
            if boundary(store,user['uid'],sid)[0]!=context['generation']:error('scenario_context_changed','场景已被清除，请刷新后重新确认。',409)
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(user['uid'],)).fetchone()
        if not runtime or runtime['status']!='ready' or runtime['gate_policy']!='open' or runtime['security_blocked'] or runtime['recovery_required'] or runtime['revision']!=revision:
            error('runtime_changed','运行环境或配置已变化，请刷新后重新确认',409)
        if db.execute("SELECT 1 FROM business_runs WHERE uid=? AND session_id=? AND status IN ('queued','running','cancelling','reconciling')",(user['uid'],sid)).fetchone():error('session_busy','此会话已有未结束的执行',409)
        from .capabilities import check_selection
        selection = task_spec.admission_selection(data,task,context['effective_skill_ids']) if task is not None else ({**data,'skill_ids':context['effective_skill_ids']} if context is not None else data)
        check_selection(store,user['uid'],selection)
        if not db.execute("SELECT 1 FROM models m JOIN grants g ON g.resource=m.id AND g.kind='model' WHERE g.uid=? AND m.id=? AND m.enabled=1",(user['uid'],payload['model']['modelID'])).fetchone():error('model_unavailable','所选模型授权已变化',403)
        if agents.enabled(user['uid']):
            agents.bind(payload,profile,context,[x for x in applied.get('skills',[]) if x['id'] in (context or {}).get('effective_skill_ids',[])])
        from .facts_plan import build, bind_payload
        plan = build(applied, context, data, task) if task and task['spec'] and task['spec']['query_mode']=='new_query' else None if task else build(applied, context, data)
        if task and task['spec'] and task['spec']['query_mode']=='new_query' and not plan:error('task_plan_unavailable','固定方法执行链尚未生效。',409)
        if plan:
            # Verify every planned dependency, not only the user's preferences.
            check_selection(store,user['uid'],{'skill_ids':context['effective_skill_ids'],'plugin_ids':plan['allowed_capabilities']})
            bind_payload(payload,plan,applied)
            snapshot['facts_plan']=plan
            snapshot['execution_plan']={k:plan[k] for k in ('plan_version','methods','modules','steps')}
            snapshot['allowed_capabilities']=plan['allowed_capabilities']
            snapshot['allowed_tools']=plan['allowed_tools']
        if task is not None:
            from .task_spec import bind
            bind(snapshot,payload,task)
        agents.freeze(snapshot,payload,profile)
        # Admission freezes encrypted inputs; SQL never holds a network operation.
        db.execute("INSERT INTO business_runs(id,uid,session_id,request_key,request_hash,message_id,parent_id,status,phase,model_id,revision,auth_version,request_ciphertext,created,updated) VALUES(?,?,?,?,?,?,?,'queued','pending_dispatch',?,?,?,?,?,?)",(identity,user['uid'],sid,data['client_request_id'],fingerprint(store,data),message,parent,payload['model']['modelID'],revision,user['version'],store.encrypt(snapshot),timestamp,timestamp))
        if task and task['local']:
            response=task['local']
            phase='clarification' if task['spec']['query_mode']=='clarify' else 'history_unavailable'
            empty={'status':'empty','cards':[],'summary':[],'missing':[response['message']]}
            db.execute("UPDATE business_runs SET status='completed',phase=?,assistant_id=?,completed=?,evidence_ciphertext=? WHERE id=?",(phase,'msg_task_'+identity,timestamp,store.encrypt(empty),identity))
            event(store,identity,'task-route','routing','需要补充信息' if phase=='clarification' else '历史解释尚未开放','completed',timestamp,timestamp)
        else:
            db.execute("INSERT INTO run_deliveries(run_id,state) VALUES(?,'pending')",(identity,))
        profile=db.execute('SELECT department_id FROM user_profiles WHERE uid=?',(user['uid'],)).fetchone()
        db.execute('INSERT INTO invocations(id,run_id,uid,department_id,model_id,selected_skills,selected_plugins,query_summary,created) VALUES(?,?,?,?,?,?,?,?,?)',(ident(),identity,user['uid'],profile['department_id'] if profile else None,payload['model']['modelID'],encode(data['skill_ids']),encode(data['plugin_ids']),'技能对话' if data['skill_ids'] else '普通对话',timestamp))
        if trial:
            count=db.execute('UPDATE draft_trials SET run_id=?,session_id=? WHERE id=? AND uid=? AND run_id IS NULL',(identity,sid,trial,user['uid'])).rowcount
            if count!=1:error('trial_conflict','试运行已受理或正在核对',409)
        if draft:
            count=db.execute("UPDATE skill_drafts SET run_id=?,status='generating',updated=? WHERE id=? AND uid=? AND run_id IS NULL AND status='preparing'",(identity,timestamp,draft,user['uid'])).rowcount
            if count!=1:error('draft_conflict','草稿受理状态已变化',409)
    return {'accepted':True,'run_id':identity,'message_id':message}


def owned(store,uid,sid,rid):
    require_v6(store)
    row=store.one('SELECT * FROM business_runs WHERE id=? AND uid=? AND session_id=?',(rid,uid,sid))
    if not row:error('run_not_found','执行记录不存在',404)
    return row


def public(row):
    return {'id':row['id'],'session_id':row['session_id'],'status':row['status'],'phase':row['phase'],'model_id':row['model_id'],'message_id':row['assistant_id'],'user_message_id':row['message_id'],'parent_run_id':row['parent_id'],'created_at':iso(row['created']),'started_at':iso(row['started']),'completed_at':iso(row['completed']),'updated_at':iso(row['updated']),'cancel_requested':bool(row['cancel_requested']),'error':{'code':row['error_code'],'message':'执行未确认或未能完成，请查看状态'} if row['error_code'] else None}


def set_state(store,rid,status,phase,code=None):
    with store.tx() as db:
        row=db.execute('SELECT status,phase,error_code,cancel_requested FROM business_runs WHERE id=?',(rid,)).fetchone()
        if not row or row['status'] in TERMINAL:return
        if row['cancel_requested'] and status not in ('cancelling','cancelled','completed','failed','reconciling'):return
        if (row['status'],row['phase'],row['error_code'])==(status,phase,code):return
        if status=='cancelling':db.execute('UPDATE business_runs SET cancel_requested=1 WHERE id=?',(rid,))
        db.execute("UPDATE business_runs SET status=?,phase=?,error_code=?,updated=?,started=CASE WHEN ? IN ('running','cancelling') THEN coalesce(started,?) ELSE started END,completed=CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE completed END WHERE id=?",(status,phase,code,now(),status,now(),status,now(),rid))


def event(store,rid,key,kind,name,status,started=None,completed=None,capability=None,count=0):
    with store.tx() as db:
        existing=db.execute('SELECT * FROM run_events WHERE run_id=? AND event_key=?',(rid,key)).fetchone()
        if existing:
            first=existing['started'] if existing['started'] is not None else started
            if (existing['status'],existing['started'],existing['completed'],existing['record_count'])==(status,first,completed,count):return
            sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM run_events WHERE run_id=?',(rid,)).fetchone()[0]
            db.execute('UPDATE run_events SET sequence=?,status=?,started=?,completed=?,record_count=? WHERE id=?',(sequence,status,first,completed,count,existing['id']))
        else:
            sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM run_events WHERE run_id=?',(rid,)).fetchone()[0]
            db.execute('INSERT INTO run_events(id,run_id,event_key,sequence,step_type,name,status,started,completed,capability_id,record_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident(),rid,key,sequence,kind,name,status,started,completed,capability,count))


def public_event(row):
    return {'id':row['id'],'sequence':row['sequence'],'step_type':row['step_type'],'name':row['name'],'status':row['status'],'started_at':iso(row['started']),'completed_at':iso(row['completed']),'elapsed_ms':max(0,(row['completed']-row['started'])*1000) if row['completed'] is not None and row['started'] is not None else None,'capability_id':row['capability_id'],'input_summary':row['input_summary'],'output_summary':row['output_summary'],'record_count':row['record_count'],'evidence_refs':json.loads(row['evidence_refs']),'error_message':'步骤未完成' if row['error_code'] else None}
