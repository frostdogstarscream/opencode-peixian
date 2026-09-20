import json
from fastapi import Depends, Request
from fastapi.responses import Response
from .backend_contract import error, require_v6, page_values
from .concurrency import blocking_endpoint
from . import business_runs as runs
from .store import now


def evidence(store,row):
    from .scenario_evidence import permitted
    if not permitted(store,row['uid']):return {'run_id':row['id'],'status':'unavailable','cards':[],'summary':[]}
    return {'run_id':row['id'],**(store.decrypt(row['evidence_ciphertext']) if row['evidence_ciphertext'] else {'status':'pending','cards':[],'summary':[]})}


def attach_results(store,uid,values):
    if store.schema_version()<6:return values
    from .scenario_evidence import permitted
    if not permitted(store,uid):return values
    for message in values:
        mid=message['info'].get('id')
        row=store.one('SELECT id,result_ciphertext FROM business_runs WHERE uid=? AND assistant_id=? AND result_ciphertext IS NOT NULL',(uid,mid))
        if row:message['parts'].append({'id':'part_run_'+row['id'],'type':'analysis_result','data':store.decrypt(row['result_ciphertext'])})
    return values


def cancel(store,uid,sid,rid):
    row=runs.owned(store,uid,sid,rid)
    if row['status'] not in runs.TERMINAL:runs.set_state(store,rid,'cancelling','stopping')
    return runs.public(runs.owned(store,uid,sid,rid))


def register(app):
    from .app import PREFIX,normal,body_fields
    @app.get(PREFIX+'/sessions/{sid}/runs')
    async def run_list(sid:str,request:Request,page:int=1,page_size:int=20,user=Depends(normal)):
        from .app import session_owned
        s=app.state.store;offset=page_values(page,page_size)
        def read():
            require_v6(s)
            with s.read(snapshot=True) as db:
                rows=[dict(x) for x in db.execute('SELECT * FROM business_runs WHERE uid=? AND session_id=? ORDER BY created DESC,id LIMIT ? OFFSET ?',(user['uid'],sid,page_size,offset))]
                total=db.execute('SELECT count(*) FROM business_runs WHERE uid=? AND session_id=?',(user['uid'],sid)).fetchone()[0]
            return {'items':[runs.public(x) for x in rows],'total':total,'page':page,'page_size':page_size}
        value=await app.state.db_work.run(read)
        if not value['total']:await session_owned(request,user,sid)
        return value

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}')
    @blocking_endpoint(app)
    def run_get(sid:str,rid:str,request:Request,user=Depends(normal)):
        return runs.public(runs.owned(app.state.store,user['uid'],sid,rid))

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/events')
    @blocking_endpoint(app)
    def run_events(sid:str,rid:str,request:Request,page:int=1,page_size:int=100,after:int=0,user=Depends(normal)):
        s=app.state.store;runs.owned(s,user['uid'],sid,rid);offset=page_values(page,page_size)
        if after<0:error('invalid_sequence','事件序号无效')
        rows=s.rows('SELECT * FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ? OFFSET ?',(rid,after,page_size,offset))
        return {'items':[runs.public_event(x) for x in rows],'total':s.one('SELECT count(*) AS n FROM run_events WHERE run_id=? AND sequence>?',(rid,after))['n'],'page':page,'page_size':page_size}

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/evidence')
    @blocking_endpoint(app)
    def run_evidence(sid:str,rid:str,request:Request,user=Depends(normal)):
        return evidence(app.state.store,runs.owned(app.state.store,user['uid'],sid,rid))

    @app.post(PREFIX+'/sessions/{sid}/runs/{rid}/abort',status_code=202)
    @blocking_endpoint(app)
    def run_abort(sid:str,rid:str,request:Request,user=Depends(normal)):
        return cancel(app.state.store,user['uid'],sid,rid)

    @app.post(PREFIX+'/sessions/{sid}/runs/{rid}/rerun',status_code=202)
    async def run_again(sid:str,rid:str,request:Request,user=Depends(normal)):
        s=app.state.store;row=await app.state.db_work.run(runs.owned,s,user['uid'],sid,rid)
        data=body_fields(await request.json(),('client_request_id','text','model_id','skill_ids','plugin_ids','file_ids','mode'))
        if not data.get('client_request_id'):error('request_id_required','重跑必须提供新的client_request_id')
        if row['status'] not in runs.TERMINAL:error('run_active','原执行尚未结束',409)
        merged={**s.decrypt(row['request_ciphertext'])['request'],**data}
        if merged['client_request_id']==row['request_key']:error('request_id_reused','重跑需要新的请求标识',409)
        async def receive():return {'type':'http.request','body':json.dumps(merged).encode(),'more_body':False}
        forwarded=Request(request.scope,receive);forwarded.state.run_parent=rid
        endpoint=next(route.endpoint for route in app.routes if getattr(route,'name',None)=='message_send')
        return await endpoint(sid,forwarded,user)

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/report')
    @blocking_endpoint(app)
    def run_report(sid:str,rid:str,request:Request,user=Depends(normal)):
        s=app.state.store;row=runs.owned(s,user['uid'],sid,rid)
        if row['status'] not in runs.TERMINAL:error('run_not_finished','执行尚未结束，暂不能导出',409)
        data=evidence(s,row);view=data.get('presentation',{});state=runs.public(row)
        lines=['# 执行报告','',f"- 执行编号：{rid}",f"- 状态：{ {'completed':'已完成','failed':'未完成','cancelled':'已取消'}.get(state['status'],'状态待确认')}",f"- 创建时间：{state['created_at']}",'']
        if data.get('synthetic') is True or data.get('scenario'):lines += ['资料性质：合成测试资料，不代表真实业务事实。','']
        lines += ['## 已核对结论','']+[('- '+x['text']) for x in view.get('conclusions',[])]
        if not view.get('conclusions'):lines+=['暂无可导出的已核对结论。']
        lines+=['','## 过程','']+[f"- {x['name']}：{ {'completed':'已完成','failed':'未完成','cancelled':'已取消','pending':'等待处理','running':'执行中'}.get(x['status'],'状态待确认')}" for x in s.rows('SELECT name,status FROM run_events WHERE run_id=? ORDER BY sequence',(rid,))]
        diagram=view.get('diagram') or {}
        if diagram.get('version')=='1.0':
            lines += ['', '## 事件脉络图', '', diagram.get('legend','')]
            for page in diagram.get('pages',[]):
                lines += ['', '### 第 '+str(page['number'])+' 页', '', '```mermaid', page['mermaid'], '```']
                for node in page['nodes']:
                    lines += ['- '+node['number']+'：'+(node['time'] or '时间未明确')+'；'+node['subject']+'；'+node['event']+'；来源 '+', '.join(node['source_ids'])]
        lines+=['','## 来源','']
        for clue in view.get('clues',[]):
            for item in clue.get('evidence',[]):lines.append('- '+item['label']+'：'+item['content'])
        lines+=['','## 资料缺口','']+['- '+x for x in view.get('missing',[])]
        if row['error_code']:lines+=['- 执行未正常完成；不得将未取得资料补写为结论。']
        lines+=['','## 版本','',json.dumps({k:data[k] for k in ('scenario','snapshots','rule_version') if k in data},ensure_ascii=False)]
        s.audit(user['uid'],'run.report',rid,actor_role='user')
        return Response('\n'.join(lines)+'\n',media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="run-{rid}.md"'})
