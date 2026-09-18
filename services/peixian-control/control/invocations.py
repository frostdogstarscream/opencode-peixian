import csv
import io
import json
from datetime import datetime
from fastapi import Depends, Request
from fastapi.responses import Response
from .backend_contract import error,require_v6,iso,page_values
from .business_runs import public_event
from .concurrency import blocking_endpoint


def filters(values):
    clauses=["u.role='user'"];args=[]
    for key,column in [('uid','i.uid'),('department_id','i.department_id'),('model_id','i.model_id'),('status','r.status')]:
        if values.get(key):clauses.append(column+'=?');args.append(values[key])
    for key,op in [('start','>='),('end','<')]:
        if not values.get(key):continue
        try:
            dt=datetime.fromisoformat(values[key].replace('Z','+00:00'))
            if dt.tzinfo is None:raise ValueError()
            timestamp=int(dt.timestamp())
        except ValueError:error('invalid_time','时间必须使用带时区的ISO 8601格式')
        clauses.append('i.created'+op+'?');args.append(timestamp)
    if values.get('skill_id'):clauses.append('EXISTS(SELECT 1 FROM json_each(i.selected_skills) WHERE value=?)');args.append(values['skill_id'])
    if values.get('query'):
        if len(values['query'])>100:error('query_too_long','搜索词不能超过100字符')
        clauses.append("(instr(u.username,?)>0 OR instr(i.query_summary,?)>0)");args.extend([values['query']]*2)
    return ' AND '.join(clauses),args


BASE="FROM invocations i JOIN business_runs r ON r.id=i.run_id JOIN users u ON u.id=i.uid LEFT JOIN user_profiles p ON p.uid=u.id LEFT JOIN departments d ON d.id=i.department_id LEFT JOIN models m ON m.id=i.model_id"
SELECT="SELECT i.*,r.session_id,r.status,r.started,r.completed,r.evidence_ciphertext,u.username,p.display_name,d.name AS department_name,m.name AS model_name "

def public(row,store=None):
    count=len(store.decrypt(row['evidence_ciphertext']).get('cards',[])) if store and row.get('evidence_ciphertext') else 0
    return {k:row[k] for k in ('id','run_id','session_id','username','display_name','department_name','model_id','model_name','status','query_summary')} | {'created_at':iso(row['created']),'duration_ms':max(0,(row['completed']-row['started'])*1000) if row['started'] is not None and row['completed'] is not None else None,'record_count':count,'skill_ids':json.loads(row['selected_skills']),'plugin_ids':json.loads(row['selected_plugins']),'actual_plugin_ids':json.loads(row['actual_plugins'])}


def register(app):
    from .app import PREFIX,require_capability
    authorized=require_capability('invocations.read')
    def query(request):
        values=dict(request.query_params)
        if set(values)-{'page','page_size','query','start','end','uid','department_id','model_id','skill_id','status'}:error('unknown_filter','包含不支持的筛选字段')
        return filters(values)
    @app.get(PREFIX+'/admin/invocations')
    @blocking_endpoint(app)
    def invocation_list(request:Request,page:int=1,page_size:int=20,user=Depends(authorized)):
        s=app.state.store;require_v6(s);offset=page_values(page,page_size);where,args=query(request)
        rows=s.rows(SELECT+BASE+' WHERE '+where+' ORDER BY i.created DESC,i.id LIMIT ? OFFSET ?',(*args,page_size,offset))
        return {'items':[public(x,s) for x in rows],'total':s.one('SELECT count(*) AS n '+BASE+' WHERE '+where,args)['n'],'page':page,'page_size':page_size}

    @app.get(PREFIX+'/admin/invocations/export')
    @blocking_endpoint(app)
    def invocation_export(request:Request,user=Depends(authorized)):
        s=app.state.store;require_v6(s);where,args=query(request)
        if s.one('SELECT count(*) AS n '+BASE+' WHERE '+where,args)['n']>10000:error('export_too_large','最多导出10000条，请缩小时间范围',413)
        values=s.rows(SELECT+BASE+' WHERE '+where+' ORDER BY i.created DESC,i.id',args)
        output=io.StringIO();writer=csv.writer(output);columns=['id','run_id','created_at','username','model_name','status','duration_ms','query_summary'];writer.writerow(columns)
        for row in values:
            value=public(row,s);cells=[]
            for key in columns:
                text=str(value.get(key) or '')
                if text.lstrip().startswith(('=','+','-','@')):text="'"+text
                cells.append(text)
            writer.writerow(cells)
        s.audit(user['uid'],'invocation.export','filtered-metadata',actor_role=user['role'])
        return Response(('\ufeff'+output.getvalue()).encode('utf-8'),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="invocations.csv"'})

    @app.get(PREFIX+'/admin/invocations/{iid}')
    @blocking_endpoint(app)
    def invocation_get(iid:str,request:Request,user=Depends(authorized)):
        s=app.state.store;require_v6(s);row=s.one(SELECT+BASE+" WHERE i.id=? AND u.role='user'",(iid,))
        if not row:error('invocation_not_found','调用记录不存在',404)
        s.audit(user['uid'],'invocation.read',iid,actor_role=user['role'])
        return {**public(row,s),'steps':[public_event(x) for x in s.rows('SELECT * FROM run_events WHERE run_id=? ORDER BY sequence',(row['run_id'],))]}
