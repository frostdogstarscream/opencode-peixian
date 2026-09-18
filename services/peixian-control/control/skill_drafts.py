"""Private editable drafts. Generation uses a durable Run with tools denied."""
import json
import re
import uuid
from fastapi import Depends,Request
from .backend_contract import error,require_v6,iso
from .concurrency import blocking_endpoint
from .store import ident,now,encode
from . import business_runs as runs

FIELDS=('name','description','content','dependency_ids','input_schema','default_rules')
# Conservative detection is a review aid, not a universal personal-data classifier.
SENSITIVE=re.compile(r'DEMO-[A-Za-z0-9-]+|\b\d{6,}[Xx]?\b|\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?:身份证|手机号|车牌|姓名|住址|经纬度)\s*[:：]\s*[^\s,，;；]+|https?://[^\s]+|(?:王|张|李|赵|刘|陈|杨|黄|周|吴)某(?:某)?')

def clean(text):return SENSITIVE.sub('[参数]',text)

def owned(s,uid,did):
    require_v6(s);row=s.one('SELECT * FROM skill_drafts WHERE id=? AND uid=?',(did,uid))
    if not row:error('draft_not_found','草稿不存在',404)
    return row

def public(s,row):
    data=s.decrypt(row['content_ciphertext'])
    return {'id':row['id'],'session_id':row['session_id'],'source_type':row['source_type'],'status':row['status'],'run_id':row['run_id'],'saved_skill_id':row['saved_skill_id'],'scope':'personal','created_at':iso(row['created']),'updated_at':iso(row['updated']),'error':{'code':row['error_code'],'message':'草稿未能完成，请编辑或检查执行状态'} if row['error_code'] else None,**{k:data.get(k,[] if k in ('dependency_ids','default_rules') else {} if k=='input_schema' else '') for k in FIELDS}}

def validate(s,uid,data):
    problems={}
    for name,minimum,maximum in [('name',1,60),('description',0,500),('content',1,32000)]:
        value=data.get(name,'')
        if not isinstance(value,str) or not minimum<=len(value)<=maximum:problems[name]='长度或类型无效'
        elif SENSITIVE.search(value):problems[name]='存在具体资料标识或敏感事实，请改为参数或方法'
    if isinstance(data.get('name'),str) and re.search(r'[/\\\r\n\x00]',data['name']):problems['name']='名称不能包含路径或换行'
    deps=data.get('dependency_ids',[])
    if not isinstance(deps,list) or len(deps)>20 or any(not isinstance(x,str) for x in deps) or len(set(deps))!=len(deps):problems['dependency_ids']='依赖列表无效'
    else:
        from .capabilities import catalog
        allowed={x['id'] for x in catalog(s,uid) if x['kind']=='plugin'}
        if set(deps)-allowed:problems['dependency_ids']='包含未授权插件'
    schema=data.get('input_schema',{})
    if not isinstance(schema,dict) or len(encode(schema))>8000:problems['input_schema']='参数结构无效或超限'
    else:
        import jsonschema
        try:jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError:problems['input_schema']='JSON Schema 无效'
    rules=data.get('default_rules',[])
    if not isinstance(rules,list) or len(rules)>20 or any(not isinstance(x,str) or len(x)>500 for x in rules):problems['default_rules']='规则列表无效'
    if SENSITIVE.search(encode({'input_schema':schema,'default_rules':rules})):problems['default_rules']='参数或规则包含具体事实'
    return problems

def finalize(s,rid,messages):
    row=s.one("SELECT * FROM skill_drafts WHERE run_id=? AND status='generating'",(rid,))
    if not row:return
    run=s.one('SELECT status FROM business_runs WHERE id=?',(rid,))
    if not run or run['status'] not in runs.TERMINAL:return
    status='failed';code='generation_failed';data=s.decrypt(row['content_ciphertext'])
    if run['status']=='completed':
        texts=[p.get('text','') for m in messages if m.get('info',{}).get('role')=='assistant' for p in m.get('parts',[]) if p.get('type')=='text']
        try:
            raw=texts[-1].strip()
            if raw.startswith('```'):raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw)
            candidate=json.loads(raw)
            if not isinstance(candidate,dict) or set(candidate)-set(FIELDS):raise ValueError()
            problems=validate(s,row['uid'],candidate)
            data={k:candidate.get(k) for k in FIELDS};status='needs_review' if problems else 'ready';code='content_review_required' if problems else None
        except (ValueError,IndexError,TypeError):code='invalid_draft_output'
    with s.tx() as db:db.execute("UPDATE skill_drafts SET status=?,error_code=?,content_ciphertext=?,updated=? WHERE id=? AND status='generating'",(status,code,s.encrypt(data),now(),row['id']))

async def forward(app,request,user,sid,data,draft=None,deny_tools=False,trial=None):
    async def receive():return {'type':'http.request','body':encode(data).encode(),'more_body':False}
    forwarded=Request(dict(request.scope, state=dict(request.scope.get('state',{}))),receive)
    forwarded.state.trial_id=trial;forwarded.state.draft_id=draft;forwarded.state.draft_no_tools=deny_tools
    endpoint=next(route.endpoint for route in app.routes if getattr(route,'name',None)=='message_send')
    return await endpoint(sid,forwarded,user)


def register(app):
    from .app import PREFIX,normal,body_fields,upstream,session_owned,current_authority
    async def generate(request,user,source):
        s=app.state.store;require_v6(s)
        data=body_fields(await request.json(),('requirement','session_id','model_id','client_request_id'))
        if not data.get('client_request_id'):error('request_id_required','草稿生成需要client_request_id')
        key=runs.normalized({'client_request_id':data['client_request_id']})['client_request_id'];digest=runs.fingerprint(s,{'source':source,**data})
        if source=='requirement':
            text=data.get('requirement')
            if not isinstance(text,str) or not 1<=len(text)<=4000:error('invalid_requirement','需求应为1至4000字符')
            brief=clean(text)
        else:
            sid=data.get('session_id')
            if not isinstance(sid,str):error('session_required','请选择本人会话')
            await session_owned(request,user,sid)
            # Whitelist method metadata only. No names, messages, tool output, or trajectories sent to drafting model.
            rows=await app.state.db_work.run(s.rows,'SELECT selected_skills,selected_plugins FROM invocations WHERE uid=? AND run_id IN (SELECT id FROM business_runs WHERE uid=? AND session_id=?)',(user['uid'],user['uid'],sid))
            brief='从会话的方法结构形成技能：明确输入范围、使用已授权能力、核对来源、列出缺口。能力数量：'+str(sum(len(json.loads(x['selected_skills']))+len(json.loads(x['selected_plugins'])) for x in rows))
        def reserve():
            with s.tx() as db:
                current_authority(db,user)
                previous=db.execute('SELECT * FROM skill_drafts WHERE uid=? AND request_key=?',(user['uid'],key)).fetchone()
                if previous:
                    if previous['request_hash']!=digest:error('request_conflict','请求标识内容冲突',409)
                    return dict(previous),False
                did=ident();initial={'name':'','description':'','content':'','dependency_ids':[],'input_schema':{},'default_rules':[]}
                db.execute("INSERT INTO skill_drafts(id,uid,request_key,request_hash,session_id,source_type,status,content_ciphertext,created,updated) VALUES(?,?,?,?,?,?,'preparing',?,?,?)",(did,user['uid'],key,digest,data.get('session_id'),source,s.encrypt(initial),now(),now()))
                return dict(db.execute('SELECT * FROM skill_drafts WHERE id=?',(did,)).fetchone()),True
        row,created=await app.state.db_work.run(reserve)
        if not created:return public(s,row)
        try:
            session=(await upstream(request,user,'POST','/session',json={'title':'技能草稿生成'})).json()['id']
            prompt='请生成通用个人Skill草稿，只返回JSON对象，字段为name、description、content、dependency_ids（空数组）、input_schema（JSON Schema对象）、default_rules（字符串数组）。只沉淀方法与参数，不含具体人名、身份、日期、地址、资料编号，不调用工具，不输出已验证结论。需求：'+brief
            body={'text':prompt,'client_request_id':key,'model_id':data.get('model_id'),'skill_ids':[],'plugin_ids':[],'file_ids':[]}
            await forward(app,request,user,session,body,row['id'],True)
        except Exception:
            def fail_draft():
                with s.tx() as db:db.execute("UPDATE skill_drafts SET status='failed',error_code='generation_admission_failed',updated=? WHERE id=? AND run_id IS NULL",(now(),row['id']))
            await app.state.db_work.run(fail_draft)
            raise
        return public(s,await app.state.db_work.run(owned,s,user['uid'],row['id']))

    @app.post(PREFIX+'/skill-drafts/from-requirement',status_code=202)
    async def from_requirement(request:Request,user=Depends(normal)):return await generate(request,user,'requirement')
    @app.post(PREFIX+'/skill-drafts/from-session',status_code=202)
    async def from_session(request:Request,user=Depends(normal)):return await generate(request,user,'session')
    @app.get(PREFIX+'/skill-drafts/{did}')
    @blocking_endpoint(app)
    def get_draft(did:str,request:Request,user=Depends(normal)):return public(app.state.store,owned(app.state.store,user['uid'],did))
    @app.patch(PREFIX+'/skill-drafts/{did}')
    @blocking_endpoint(app,json_body=True)
    def edit_draft(did:str,request:Request,user=Depends(normal)):
        s=app.state.store;row=owned(s,user['uid'],did)
        if row['status'] in ('preparing','generating','saved'):error('draft_busy','草稿正在生成或已经保存',409)
        data={**s.decrypt(row['content_ciphertext']),**body_fields(request.state.json_body,FIELDS)};problems=validate(s,user['uid'],data)
        if problems:error('draft_invalid','请修改草稿中的不合法或具体事实内容',422,problems)
        with s.tx() as db:db.execute("UPDATE skill_drafts SET content_ciphertext=?,status='ready',error_code=NULL,updated=? WHERE id=? AND uid=?",(s.encrypt(data),now(),did,user['uid']))
        return public(s,owned(s,user['uid'],did))
    @app.post(PREFIX+'/skill-drafts/{did}/test')
    async def test_draft(did:str,request:Request,user=Depends(normal)):
        s=app.state.store;row=await app.state.db_work.run(owned,s,user['uid'],did);data=s.decrypt(row['content_ciphertext'])
        body=body_fields(await request.json(),('mode','text','model_id','client_request_id'));mode=body.get('mode','validation')
        problems=await app.state.db_work.run(validate,s,user['uid'],data)
        if mode=='validation':return {'mode':'validation','ok':not problems,'field_errors':problems,'model_executed':False}
        if mode!='model':error('unsupported_mode','测试仅支持validation或model')
        if problems:error('draft_invalid','草稿尚未通过结构检查',422,problems)
        if not body.get('client_request_id') or not isinstance(body.get('text'),str):error('test_input_required','试运行需要text和client_request_id')
        from .capabilities import catalog
        available={x['id'] for x in await app.state.db_work.run(catalog,s,user['uid']) if x['kind']=='plugin' and x['available']}
        if set(data.get('dependency_ids',[]))-available:error('dependency_unavailable','草稿依赖尚未生效或不可用',409)
        key=runs.normalized({'client_request_id':body['client_request_id']})['client_request_id']
        digest=runs.fingerprint(s,{'draft_id':did,'draft_content':data,'request':body})
        def reserve_trial():
            with s.tx() as db:
                current_authority(db,user)
                prior=db.execute('SELECT * FROM draft_trials WHERE uid=? AND request_key=?',(user['uid'],key)).fetchone()
                if prior:
                    if prior['request_hash']!=digest:error('request_conflict','试运行标识对应不同内容',409)
                    return dict(prior),False
                identity=ident();db.execute('INSERT INTO draft_trials(id,uid,draft_id,request_key,request_hash,created) VALUES(?,?,?,?,?,?)',(identity,user['uid'],did,key,digest,now()))
                return {'id':identity},True
        trial,created=await app.state.db_work.run(reserve_trial)
        if not created:
            if not trial['run_id']:error('trial_reconciling','试运行受理结果待核对，不会重复执行',409)
            run=await app.state.db_work.run(runs.owned,s,user['uid'],trial['session_id'],trial['run_id'])
            return {'mode':'model','model_executed':None,'session_id':trial['session_id'],**runs.receipt(run)}
        session=(await upstream(request,user,'POST','/session',json={'title':'技能草稿试运行'})).json()['id']
        accepted=await forward(app,request,user,session,{'text':'仅在本次测试采用以下方法：\n'+data['content']+'\n测试输入：'+body['text'],'model_id':body.get('model_id'),'client_request_id':key,'skill_ids':[],'plugin_ids':[],'file_ids':[]},trial=trial['id'])
        return {'mode':'model','model_executed':None,'session_id':session,**accepted}
    @app.post(PREFIX+'/skill-drafts/{did}/save')
    @blocking_endpoint(app,json_body=True)
    def save_draft(did:str,request:Request,user=Depends(normal)):
        body_fields(request.state.json_body,())
        s=app.state.store
        with s.tx() as db:
            row=owned(s,user['uid'],did)
            if row['saved_skill_id']:return {'skill_id':row['saved_skill_id'],'scope':'personal','already_saved':True}
            if row['status']!='ready':error('draft_not_ready','草稿尚不能保存',409)
            data=s.decrypt(row['content_ciphertext']);problems=validate(s,user['uid'],data)
            if problems:error('draft_invalid','草稿需要修改后保存',422,problems)
            if db.execute('SELECT 1 FROM skills WHERE uid=? AND name=?',(user['uid'],data['name'])).fetchone():error('skill_name_conflict','已有同名技能',409)
            sid=ident();content=data['content']+'\n\n参数结构：\n'+json.dumps(data.get('input_schema',{}),ensure_ascii=False)+'\n默认规则：\n'+'\n'.join(data.get('default_rules',[]))
            if len(content)>32000:error('draft_too_large','完整技能内容超过限制',413)
            db.execute("INSERT INTO skills VALUES(?,?,?,?,?,0,1,'[]')",(sid,user['uid'],data['name'],data.get('description',''),content))
            from .capabilities import save_dependencies
            save_dependencies(db,user['uid'],sid,data)
            db.execute("UPDATE skill_drafts SET saved_skill_id=?,status='saved',updated=? WHERE id=?",(sid,now(),did))
            job=s.queue(user['uid'])
        return {'skill_id':sid,'scope':'personal','enabled':False,'job':job,'already_saved':False}
