"""Encrypted frozen options and context CAS. Resolve never dispatches work."""
import copy,re,uuid
from .backend_contract import error,iso
from .store import now
from . import task_context

def enabled(store,uid):return store.schema_version()>=8 and task_context.enabled(store,uid)

def owned(store,uid,sid,cid):
    row=store.one('SELECT * FROM task_clarifications WHERE id=? AND uid=? AND session_id=?',(cid,uid,sid)) if store.schema_version()>=8 else None
    if not row:error('clarification_not_found','确认事项不存在。',404)
    return row

def public(store,row):
    value=store.decrypt(row['options_ciphertext'])
    return {'schema':'peixian.task-clarification','version':'1.0','clarification_id':row['id'],'agent_id':row['agent_id'],'field':row['field'],'question':row['question'],'options':[{'id':e['id'],'label':e['label']} for e in value['options']],'context_generation':row['context_generation'],'context_version':row['context_version'],'status':row['status'],'updated_at':iso(row['updated'])}

def prepare(store,uid,sid,data):
    from .agents import runtime as agents
    profile=agents.select(uid,data);agents.session(store,uid,sid,profile)
    context=task_context.ensure(store,uid,sid,profile)
    is_continue=bool(re.fullmatch(r'继续(?:查询)?[。！! ]*',data['text'].strip()))
    pending=context['pending_clarification_id']
    if pending and is_continue:
        return data,None,{'action':'pending','id':pending}
    confirmed=store.decrypt(context['confirmed_targets_ciphertext']) if context['confirmed_targets_ciphertext'] else None
    if confirmed and (is_continue or data['text']==confirmed['request']['text']):
        if confirmed['generation']!=context['generation']:error('clarification_expired','对象确认已失效，请重新确认。',409)
        routing={**data,'text':confirmed['request']['text'],'skill_ids':confirmed['request']['skill_ids']}
        return routing,confirmed['entity'],{'action':'resume','id':confirmed['clarification_id']}
    return data,None,None

def decorate(task,data,selection):
    target=task.get('target') or {};spec=task.get('spec')
    if selection and selection['action']=='pending':
        spec.update(query_mode='clarify',intent='clarification',methods=[],official_skill_ids=[],target_refs=[],target_mode=None,missing_fields=['target_confirmation_required'])
        task['local']={'code':'clarification_pending','message':'请先选择要核对的对象，确认后再发送“继续”。','clarification_id':selection['id']};task['context']['effective_skill_ids']=[];task['target']=None
        task['clarification']=selection
    elif selection:task['clarification']=selection
    elif target.get('status')=='ambiguous' and target.get('options'):
        task['clarification']={'action':'new','options':copy.deepcopy(target['options']),'request':{k:copy.deepcopy(data[k]) for k in ('text','skill_ids')},'source_run_id':target['projection']['source_data_run_id']}
        task['local']={'code':'target_confirmation_required','message':'请确认要核对的对象，确认后再发送“继续”；本轮未查询资料。'}
    elif spec and spec['query_mode']!='explain_existing':task['clarification']={'action':'expire'}
    return task

def expire(store,db,uid,sid):
    db.execute("UPDATE task_clarifications SET status='expired',updated=? WHERE uid=? AND session_id=? AND status='pending'",(now(),uid,sid))
    db.execute('UPDATE session_task_contexts SET pending_clarification_id=NULL,confirmed_targets_ciphertext=NULL WHERE uid=? AND session_id=?',(uid,sid))

def sync(db,uid,sid):
    db.execute("UPDATE task_clarifications SET context_version=(SELECT version FROM session_task_contexts WHERE uid=? AND session_id=?),updated=? WHERE uid=? AND session_id=? AND status='pending'",(uid,sid,now(),uid,sid))

def admit(store,db,uid,sid,task):
    if store.schema_version()<8:return
    action=task.get('clarification') or {};kind=action.get('action')
    if kind in ('new','expire','resume'):expire(store,db,uid,sid)
    if kind=='new':
        context=task['session_task_context'];cid='clr_'+uuid.uuid4().hex;timestamp=now()
        payload={'options':[{'id':'option-'+str(i+1),'label':e['display'],'entity':e} for i,e in enumerate(action['options'])],'request':action['request']}
        db.execute("INSERT INTO task_clarifications(id,uid,session_id,agent_id,agent_profile_sha256,context_generation,context_version,source_run_id,field,question,options_ciphertext,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?,?)",(cid,uid,sid,context['agent_id'],context['agent_profile_sha256'],context['generation'],context['version']+1,action['source_run_id'],'target_refs','请确认要核对哪个对象。',store.encrypt(payload),timestamp,timestamp))
        db.execute('UPDATE session_task_contexts SET pending_clarification_id=? WHERE uid=? AND session_id=?',(cid,uid,sid))
        task['local']['clarification_id']=cid
    sync(db,uid,sid)

def change(store,user,sid,cid,body,cancel=False):
    from .agents.registry import require
    from .app import current_authority
    allowed={'context_generation','context_version','client_request_id'}|({'option_id'} if not cancel else set())
    if not isinstance(body,dict) or set(body)!=allowed or any(type(body.get(k)) is not int or body[k]<1 for k in ('context_generation','context_version')) or not isinstance(body.get('client_request_id'),str) or not 1<=len(body['client_request_id'])<=128 or (not cancel and not isinstance(body.get('option_id'),str)):error('invalid_clarification_request','请提交有效的确认选项和上下文版本。',422)
    with store.tx() as db:
        current_authority(db,user)
        row=owned(store,user['uid'],sid,cid)
        context=task_context.ensure(store,user['uid'],sid,require(row['agent_id']))
        if row['agent_profile_sha256']!=context['agent_profile_sha256'] or row['context_generation']!=context['generation'] or body['context_generation']!=context['generation'] or row['status']=='expired':error('clarification_expired','确认事项已失效，请刷新。',409)
        value=store.decrypt(row['options_ciphertext']);key=body['client_request_id'];fingerprint=task_context.digest({'cancel':cancel,'body':body})
        receipt=value.get('receipt')
        if receipt and receipt['key']==key:
            if receipt['fingerprint']!=fingerprint:error('client_request_conflict','同一请求标识不能提交不同内容。',409)
            return receipt['response']
        if row['status']!='pending':error('clarification_already_resolved','此确认事项已处理，请刷新。',409)
        if context['pending_clarification_id']!=cid or body['context_version']!=context['version'] or row['context_version']!=context['version']:error('task_context_changed','会话已更新，请刷新确认选项。',409)
        entity=None
        if not cancel:
            choice=next((o for o in value['options'] if o['id']==body['option_id']),None)
            if not choice:error('invalid_clarification_option','选项不属于本次确认。',422)
            entity=choice['entity']
        status='cancelled' if cancel else 'resolved';timestamp=now()
        confirmed=None if cancel else store.encrypt({'generation':context['generation'],'clarification_id':cid,'entity':entity,'request':value['request']})
        db.execute('UPDATE session_task_contexts SET version=version+1,pending_clarification_id=NULL,confirmed_targets_ciphertext=?,updated=? WHERE uid=? AND session_id=? AND version=?',(confirmed,timestamp,user['uid'],sid,context['version']))
        response={status:True,'context_generation':context['generation'],'context_version':context['version']+1,'resume_required':not cancel}
        value['receipt']={'key':key,'fingerprint':fingerprint,'response':response}
        db.execute('UPDATE task_clarifications SET status=?,selected_option_id=?,options_ciphertext=?,updated=?,resolved=?,cancelled=? WHERE id=?',(status,body.get('option_id'),store.encrypt(value),timestamp,None if cancel else timestamp,timestamp if cancel else None,cid))
        return response

def register(app):
    from fastapi import Depends,Request
    from .app import PREFIX,normal
    @app.get(PREFIX+'/sessions/{sid}/clarifications/{cid}')
    async def get(sid:str,cid:str,user=Depends(normal)):
        def read():return public(app.state.store,owned(app.state.store,user['uid'],sid,cid))
        return await app.state.db_work.run(read)
    @app.post(PREFIX+'/sessions/{sid}/clarifications/{cid}/resolve')
    async def resolve(sid:str,cid:str,request:Request,user=Depends(normal)):
        return await app.state.db_work.run(change,app.state.store,user,sid,cid,await request.json())
    @app.post(PREFIX+'/sessions/{sid}/clarifications/{cid}/cancel')
    async def cancel(sid:str,cid:str,request:Request,user=Depends(normal)):
        return await app.state.db_work.run(change,app.state.store,user,sid,cid,await request.json(),True)
