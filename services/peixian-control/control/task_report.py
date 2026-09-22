"""Frozen task report from one read transaction; no provider/model path."""
import html
import json
from contextlib import contextmanager
from . import analysis_tasks,business_runs,trusted_results,trusted_report,run_reviews
from .backend_contract import error
from shared.theft_provider_v2 import public_result


class ReadView:
    def __init__(self,store,db):self.store,self.db=store,db
    def __getattr__(self,name):
        if name not in ('decrypt','worker_key'):raise AttributeError(name)
        return getattr(self.store,name)
    def schema_version(self):return self.db.execute('PRAGMA user_version').fetchone()[0]
    def rows(self,sql,args=()):return [dict(x) for x in self.db.execute(sql,args)]
    def one(self,sql,args=()):
        row=self.db.execute(sql,args).fetchone();return dict(row) if row is not None else None
    @contextmanager
    def read(self,**kwargs):yield self.db


def snapshot(store,uid,sid,tid):
    with store.read(snapshot=True) as db:
        view=ReadView(store,db);row=analysis_tasks.owned(view,uid,sid,tid)
        state=store.decrypt(row['payload_ciphertext'])
        if any(c['state']=='sending' or (c['state']=='completed' and (not c.get('receipt') or (c.get('decision',{}).get('action')=='query' and not c.get('advanced')))) for c in state['planning_calls']):error('task_active','任务规划尚未结束，暂不能导出。',409)
        task=analysis_tasks.view(view,uid,sid,tid)
        if len(task['steps'])>100:error('task_report_limit','步骤较多，请按任务拆分导出。',413)
        results=[];record_count=0;sources={}
        for step in task['steps']:
            for reference in step['source_refs']:
                key=json.dumps(reference,sort_keys=True)
                if key not in sources:
                    source_record,_=analysis_tasks.source(view,uid,sid,reference,row['environment'])
                    sources[key]={'reference':reference,'record':source_record}
                if len(sources)>1000:error('task_report_limit','来源引用过多，请拆分任务。',413)
            run=business_runs.owned(view,uid,sid,step['run_id'])
            if run['status'] not in business_runs.TERMINAL:error('task_active','任务仍有未结束执行。',409)
            result=trusted_results.read(view,uid,sid,run['id'])
            record_count+=len(result.get('records',[]))
            if record_count>10000:error('task_report_limit','来源条目较多，请按任务拆分导出。',413)
            events=view.rows('SELECT * FROM run_events WHERE run_id=? ORDER BY sequence',(run['id'],))
            reviews=run_reviews.report_rows(view,uid,sid,run['id'])
            results.append({'run_id':run['id'],'status':run['status'],'result':result,'result_digest':trusted_results.digest(result),'events':events,'reviews':reviews})
        frozen={'version':'theft-task-report-v1','task':task,'runs':results,'sources':list(sources.values())}
        frozen=public_result(frozen,store.worker_key.encode(),uid+'/'+sid)
        frozen['digest']=trusted_results.digest(frozen)
        return frozen


def render(value,format):
    if format not in ('html','md'):error('invalid_report_format','请选择html或md格式。',422)
    task=value['task'];groups=[('任务信息',['任务编号：'+task['analysis_task_id'],'目标：'+task['goal'],'数据环境：'+task['data_environment'],'资料包摘要：'+value['digest'],'任务上下文版本：'+str(task['context_version']),'预算计数：'+json.dumps(task['budget'],ensure_ascii=False),'仅包含本次只读快照中已保存的来源与复核；不新增取数。'])]
    groups.append(('选定来源索引',[json.dumps(x,ensure_ascii=False,sort_keys=True) for x in value['sources']] or ['未引用外部步骤；来源见各查询结果。']))
    for step,run in zip(task['steps'],value['runs']):
        groups.append(('步骤 '+str(step['sequence']),['执行编号：'+run['run_id'],'执行状态：'+{'completed':'执行结束','failed':'失败','cancelled':'已中止'}.get(run['status'],'待核对'),'结果摘要：'+run['result_digest'],'来源关系：'+json.dumps(step['source_refs'],ensure_ascii=False),'实际版本：'+json.dumps({k:v for k,v in step.items() if k in ('provider_contract','plugin_version','connection_revision','planning_method')},ensure_ascii=False)]))
        groups.extend(trusted_report.sections(run['result'],run['events'],run['reviews']))
    if format=='md':
        def escape(v):
            text=html.escape(str(v)).replace('\n',' ').replace('\r',' ')
            for c in ('\\','`','*','_','[',']','#','>','|'):text=text.replace(c,'\\'+c)
            return text
        return '# 任务资料包\n\n'+'\n\n'.join('## '+t+'\n\n'+'\n'.join('- '+escape(v) for v in values) for t,values in groups)+'\n'
    content=''.join('<section><h2>'+html.escape(t)+'</h2><ul>'+''.join('<li>'+html.escape(str(v))+'</li>' for v in values)+'</ul></section>' for t,values in groups)
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务资料包</title><body><h1>任务资料包</h1>'+content+'</body></html>'


def register(app):
    from fastapi import Request,Depends
    from starlette.responses import Response
    from .app import PREFIX,normal
    from .concurrency import blocking_endpoint
    @app.get(PREFIX+'/sessions/{sid}/scenarios/{scenario_id}/report')
    @blocking_endpoint(app)
    def report(sid:str,scenario_id:str,request:Request,format:str='html',user=Depends(normal)):
        result=snapshot(app.state.store,user['uid'],sid,scenario_id)
        body=render(result,format)
        return Response(body,media_type='text/html' if format=='html' else 'text/markdown',headers={'Content-Disposition':'attachment; filename="task-'+scenario_id+'.'+format+'"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"})
