"""Owner-only append-only source review. Human opinions do not approve Claims."""
from fastapi import Depends,Request
from .backend_contract import error,iso,page_values
from .business_runs import owned,TERMINAL
from .store import ident,now
STATES={'consistent':'来源核对一致','needs_information':'需要补充资料','inconsistent':'发现资料不一致'}
def require(store):
    if store.schema_version()<10:error('reviews_unavailable','当前版本尚未启用复核记录。',409)
def public(store,row):
    return {'id':row['id'],'run_id':row['run_id'],'result_digest':row['result_digest'],'status':row['status'],'status_label':STATES[row['status']],'supersedes':row['supersedes'],'created_at':iso(row['created']),**store.decrypt(row['payload_ciphertext'])}
def append(store,user,sid,rid,data):
    from .app import current_authority
    from .trusted_results import read,digest
    require(store)
    if not isinstance(data,dict) or set(data)-{'result_digest','status','note','claim_ids','supersedes'}:error('invalid_review','复核字段无效。',422)
    if not isinstance(data.get('status'),str) or data.get('status') not in STATES or not isinstance(data.get('note'),str) or not 1<=len(data['note'].strip())<=2000:error('invalid_review','请选择复核状态并填写1至2000字意见。',422)
    ids=data.get('claim_ids',[])
    if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):error('invalid_review_claims','复核来源引用无效。',422)
    with store.tx() as db:
        current_authority(db,user);run=owned(store,user['uid'],sid,rid)
        if run['status'] not in TERMINAL:error('review_run_active','请等待本轮执行结束后复核。',409)
        result=read(store,user['uid'],sid,rid)
        if result.get('version')!='2.0':error('review_result_unsupported','当前结果结构不支持复核。',409)
        if data.get('result_digest')!=digest(result):error('review_result_changed','结果版本不匹配，请刷新。',409)
        if not set(ids)<={c['claim_id'] for c in result['claims']}:error('invalid_review_claims','复核引用不属于本轮结果。',422)
        supersedes=data.get('supersedes')
        if supersedes is not None:
            if not isinstance(supersedes,str) or not db.execute('SELECT 1 FROM run_reviews WHERE id=? AND run_id=? AND uid=?',(supersedes,rid,user['uid'])).fetchone():error('review_not_found','被更正的复核记录不存在。',404)
            if db.execute('SELECT 1 FROM run_reviews WHERE supersedes=?',(supersedes,)).fetchone():error('review_already_superseded','此意见已被更正，请刷新后选择最新记录。',409)
        identity=ident()
        actor=db.execute('SELECT username FROM users WHERE id=?',(user['uid'],)).fetchone()[0]
        payload={'reviewer':actor,'note':data['note'].strip(),'claim_ids':ids}
        db.execute('INSERT INTO run_reviews VALUES(?,?,?,?,?,?,?,?)',(identity,rid,user['uid'],data['result_digest'],data['status'],store.encrypt(payload),supersedes,now()))
        store.audit(user['uid'],'run.review.append',identity)
        return public(store,dict(db.execute('SELECT * FROM run_reviews WHERE id=?',(identity,)).fetchone()))
def listing(store,uid,sid,rid,page=1,page_size=20):
    require(store);owned(store,uid,sid,rid);offset=page_values(page,page_size)
    with store.read(snapshot=True) as db:
        rows=[dict(x) for x in db.execute('SELECT * FROM run_reviews WHERE uid=? AND run_id=? ORDER BY created,rowid LIMIT ? OFFSET ?',(uid,rid,page_size,offset))]
        total=db.execute('SELECT count(*) FROM run_reviews WHERE uid=? AND run_id=?',(uid,rid)).fetchone()[0]
    from .trusted_results import read,digest
    result_digest=digest(read(store,uid,sid,rid))
    return {'result_digest':result_digest,'items':[public(store,x) for x in rows],'total':total,'page':page,'page_size':page_size,'unreviewed':total==0}
def report_rows(store,uid,sid,rid):
    if store.schema_version()<10:return []
    owned(store,uid,sid,rid)
    return [public(store,r) for r in store.rows('SELECT * FROM run_reviews WHERE uid=? AND run_id=? ORDER BY created,rowid',(uid,rid))]
def register(app):
    from .app import PREFIX,normal
    from .concurrency import blocking_endpoint
    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/reviews')
    @blocking_endpoint(app)
    def get_reviews(sid:str,rid:str,request:Request,page:int=1,page_size:int=20,user=Depends(normal)):
        return listing(app.state.store,user['uid'],sid,rid,page,page_size)
    @app.post(PREFIX+'/sessions/{sid}/runs/{rid}/reviews',status_code=201)
    async def post_review(sid:str,rid:str,request:Request,user=Depends(normal)):
        from .idempotency import execute
        data=await request.json()
        request.state.json_body=data
        return await app.state.db_work.run(execute,request,user,lambda:append(app.state.store,user,sid,rid,data))
