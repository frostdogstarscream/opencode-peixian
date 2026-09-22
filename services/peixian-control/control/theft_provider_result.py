"""Projection of authenticated provider receipts, never model prose."""
import copy
from .trusted_results import claim
from .backend_contract import iso
from shared.theft_provider import CATALOG,LIMITATIONS

def sentence(kind,f):
    if kind=='incidents':return f"警情引用 {f.get('cjbh','未提供')}；处警时间 {f.get('cjsj','未提供')}；来源地址 {f.get('address','未提供')}。"
    if kind=='captures':return f"{f.get('target_name','对象未提供')}（{f.get('target_id_card','未提供')}）：来源范围内抓拍汇总 {f.get('capture_count','未提供')} 次，不等于到访次数。"
    if kind=='tracks':return f"观测时间 {f.get('captureTime','未提供')}；设备 {f.get('deviceId','未提供')}；来源地点 {f.get('deviceName','未提供')}；轨迹类型 { {0:'人卡',1:'机动车',2:'非机动车'}.get(f.get('trackType'),'未明确')}。"
    if kind in ('warnings','warning_detail'):return f"{f.get('personName','对象未提供')}（{f.get('idCard','未提供')}）：来源预警类型 {f.get('warningTypes','未提供')}；类型数 {f.get('warningCount','未提供')}；最新触发时间 {f.get('latestTime','未提供')}。"
    return f"来源预警类型 {f.get('warningType','未提供')}；来源近7天规则触发 {f.get('count','未提供')} 次，不等于独立事件数。"

def project(row,snapshot):
    if snapshot.get('provider_history'):
        result=copy.deepcopy(snapshot['provider_history']);source=result.get('data_usage',{}).get('source_data_run_id') or result['run_id']
        result.update(run_id=row['id'],task=copy.deepcopy(snapshot['task_spec']),generated_at=iso(row.get('completed') or row['created']))
        result['data_usage']={'status':'historical_evidence','queried':False,'attempted':False,'may_have_sent':False,'new_call_count':0,'reuse_count':0,'source_data_run_id':source,'modules':[],'basis':'本人已冻结来源；未重新取数'}
        result['answer']['summary']='本次说明已有资料，没有重新查询。'+result['answer']['summary'].removeprefix('本次说明已有资料，没有重新查询。')
        return result
    plan=snapshot['provider_plan'];kind=plan['kind'];state=snapshot.get('provider_state',{});entry=state.get('modules',{}).get(kind,{})
    data=entry.get('response') if entry.get('status')=='completed' else None
    records=[];claims=[];identity=snapshot['agent_profile'];missing=[LIMITATIONS[kind]]
    if data:
        for record in data['records']:
            rid=row['id']+':'+record['source_ref'];fields=copy.deepcopy(record['fields'])
            records.append({'record_id':rid,'module':kind,'source_run_id':row['id'],'snapshot_id':data['snapshot_id'],'fields':fields})
            claims.append(claim(row,identity,'fact','provider.'+kind+'.record.v1',sentence(kind,fields),{'record_id':rid,'subject_refs':snapshot['task_spec']['target_refs'],'fields':fields,'snapshot_id':data['snapshot_id']},[rid]))
        summary=f"{CATALOG[kind][0]}：本次取得 {data['returned_count']} 条来源记录。"
        summary+=f"来源总数 {data['total']}；当前第 {plan['query']['page']} 页。" if data['total'] is not None else '来源未提供完整总数。'
        claims.insert(0,claim(row,identity,'computed','provider.page.v1',summary,{'subject_refs':snapshot['task_spec']['target_refs'],'returned_count':data['returned_count'],'total':data['total'],'coverage':data['coverage']},[r['record_id'] for r in records]))
        if data['coverage']!='complete':missing.append('本次覆盖有限，不能把当前返回数量当作全部资料。')
        missing+=data['limitations']
    else:summary='本轮尚未取得可核对的资料；不能解释为没有相关记录。';missing.append('请查看原执行状态；结果未知时不会自动重新查询。')
    if snapshot.get('provider_followup'):summary=snapshot['task_response']['message']
    status='needs_input' if snapshot.get('provider_followup') else 'partial' if data and (data['coverage']!='complete' or row['status']!='completed') else 'ready' if data else 'unavailable'
    use='partial' if data and data['coverage']!='complete' else 'confirmed' if data else 'unknown' if entry else 'not_started'
    items=[{'text':c['statement'],'claim_id':c['claim_id'],'source_run_id':row['id'],'source_ids':c['source_ids']} for c in claims[:5]]
    steps=['可展开本轮来源，确认对象和范围后继续查询。','可追加来源复核意见或导出本轮报告。'] if data else ['请查看本轮执行步骤，不要自动重复发送。']
    return {'schema':'peixian.analysis-result','version':'2.0','run_id':row['id'],'agent':identity,'task':copy.deepcopy(snapshot['task_spec']),'data_environment':'synthetic','data_usage':{'status':use,'queried':True if data else None if entry else False,'attempted':bool(entry),'may_have_sent':bool(entry),'new_call_count':int(bool(entry)),'reuse_count':0,'source_data_run_id':None,'modules':[{'module':kind,'status':entry.get('status','not_started'),'reserved':bool(entry),'response_confirmed':bool(data)}],'basis':'受控Gateway投递与持久回执'},'claims':claims,'records':records,'missing':list(dict.fromkeys(missing)),'narrative':{'status':'not_generated','text':None,'claim_refs':[],'conflicts':[],'review_version':'provider-code-v1','coverage':'公开说明由代码从已确认回执生成。'},'versions':{'provider_contract':plan['version'],'provider_snapshot':data['snapshot_id'] if data else None,'plugin_versions':{plan['plugin_id']:plan['plugin_version']},'query':plan['query']},'generated_at':iso(row.get('completed') or row['created']),'answer':{'version':'controlled-zh-v1','status':status,'summary':summary,'items':items,'missing':list(dict.fromkeys(missing)),'next_steps':steps}}
