"""Synthetic-only provider contract. No network or real identity lookup here."""
from datetime import datetime
from decimal import Decimal,InvalidOperation
import copy,hashlib,json,re
VERSION='theft-provider-contract-v1'
SNAPSHOT='DEMO-PROVIDER-20260922-01'
CATALOG={
 'incidents':('警情资料查询','POST','/jq/search'),
 'captures':('周边抓拍资料','POST','/jq/capture'),
 'tracks':('指定对象轨迹','POST','/track/person'),
 'warnings':('来源预警列表','GET','/system/multiDimension/list'),
 'warning_detail':('来源预警详情','GET','/system/multiDimension/idCard/{subject}'),
 'warning_logs':('来源预警明细','GET','/system/multiDimension/logs/{subject}'),
}
SUBJECTS={'DEMO-PERSON-001':'演示对象甲','DEMO-PERSON-002':'演示对象乙'}
DATES=('2026-09-01 00:00:00','2026-09-22 23:59:59')
class ContractError(ValueError):pass

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def normalize_query(kind,data):
    if not isinstance(kind,str) or kind not in CATALOG or not isinstance(data,dict):raise ContractError('unknown_contract')
    allowed={'start','end','page','page_size','subject','address','center','radius_m'}
    if set(data)-allowed:raise ContractError('unknown_query_fields')
    q=copy.deepcopy(data)
    if kind in ('incidents','captures') and 'subject' in q:raise ContractError('unsupported_subject_filter')
    if kind in ('tracks','warning_detail','warning_logs') and any(q.get(k,default)!=default for k,default in [('page',1),('page_size',20)]):raise ContractError('unsupported_pagination')
    for k,default,upper in [('page',1,10000),('page_size',20,100)]:
        q.setdefault(k,default)
        if type(q[k]) is not int or not 1<=q[k]<=upper:raise ContractError('invalid_pagination')
    if kind not in ('warning_detail','warning_logs'):
        try:
            start,end=(datetime.strptime(q[k],'%Y-%m-%d %H:%M:%S') for k in ('start','end'))
        except (ValueError,TypeError,KeyError):raise ContractError('explicit_time_required') from None
        if start>=end or (end-start).total_seconds()>31*86400:raise ContractError('invalid_time_range')
        if kind=='warnings' and (q['start'][11:]!='00:00:00' or q['end'][11:]!='23:59:59'):raise ContractError('warning_calendar_days_required')
    elif 'start' in q or 'end' in q:raise ContractError('source_window_fixed')
    if kind in ('tracks','warning_detail','warning_logs') or 'subject' in q:
        if not isinstance(q.get('subject'),str) or q.get('subject') not in SUBJECTS:raise ContractError('synthetic_subject_required')
    if kind=='incidents':
        if not q.get('address') and not q.get('center'):raise ContractError('incident_scope_required')
    elif 'address' in q:raise ContractError('unsupported_address_filter')
    if 'address' in q and (not isinstance(q['address'],str) or not q['address'].startswith('DEMO-') or len(q['address'])>100):raise ContractError('synthetic_address_required')
    if kind=='captures' or 'center' in q or 'radius_m' in q:
        if kind not in ('incidents','captures'):raise ContractError('unsupported_radius')
        center=q.get('center')
        # These are fixture positions, deliberately not real map coordinates.
        if center not in ('DEMO-LOCATION-A','DEMO-LOCATION-B'):raise ContractError('synthetic_center_required')
        if type(q.get('radius_m')) is not int or not 1<=q['radius_m']<=5000:raise ContractError('radius_m_required')
    return q

def request_spec(kind,data):
    q=normalize_query(kind,data);method,path=CATALOG[kind][1:]
    body={'pageNum':q['page'],'pageSize':q['page_size']}
    if kind in ('incidents','captures'):
        body.update(startTime=q['start'],endTime=q['end'])
        if q.get('center'):
            body.update(lon='0.001' if q['center'].endswith('A') else '0.002',lat='0.001',scope=float(Decimal(q['radius_m'])/1000) if kind=='incidents' else q['radius_m'])
        if kind=='incidents':body.update(address=q.get('address',''),ajType='盗窃')
    elif kind=='tracks':body={'certificateNo':q['subject'],'beginTime':q['start'],'endTime':q['end'],'trackTypes':[0,1,2]}
    elif kind=='warnings':body.update(beginTime=q['start'][:10],endTime=q['end'][:10],**({'idCard':q['subject']} if q.get('subject') else {}))
    else:path=path.replace('{subject}',q['subject']);body={}
    return {'method':method,'path':path,'json':body} if method=='POST' else {'method':method,'path':path,'query':body}

FIELDS={
 'incidents':('cjbh','jjbh','cjsj','address','gisX','gisY','ajType'),
 'captures':('target_id_card','target_name','capture_count','tags'),
 'tracks':('deviceId','deviceName','captureTime','trackType','lon','lat'),
 'warnings':('id','idCard','personName','warningTypes','warningCount','latestTime'),
 'warning_detail':('id','idCard','personName','warningTypes','warningCount','latestTime'),
 'warning_logs':('warningType','count','records'),
}
LIMITATIONS={
 'incidents':'处警时间不等于案发时间；本次仅有坐标且符合来源范围的盗窃类资料。',
 'captures':'来源只覆盖限定标签人群的抓拍汇总；抓拍次数不等于到访次数，不证明违法行为。',
 'tracks':'设备补充位置不证明人员精确到达现场；未读取照片，也不从时间接近推断同行。',
 'warnings':'预警类型和标签属于来源记录；类型数量不是事件次数，不构成嫌疑判断。',
 'warning_detail':'来源标签不证明前科；不使用来源扣分计算人员嫌疑。',
 'warning_logs':'来源只覆盖最近7天明细；规则触发次数不等于独立事件数。',
}
def parse_response(kind,q,payload):
    q=normalize_query(kind,q)
    if not isinstance(payload,dict) or payload.get('code')!=200:raise ContractError('provider_business_error')
    if not isinstance(payload.get('_fixture'),dict) or payload.get('_fixture',{}).get('snapshot_id')!=SNAPSHOT or payload.get('_fixture',{}).get('synthetic') is not True:raise ContractError('fixture_identity_required')
    data=payload if kind=='warnings' else payload.get('data')
    if kind in ('incidents','captures','warnings'):
        if not isinstance(data,dict) or not isinstance(data.get('rows'),list) or type(data.get('total')) is not int:raise ContractError('pagination_contract')
        rows,total=data['rows'],data['total'];offset=(q['page']-1)*q['page_size']
        if len(rows)>q['page_size'] or total<0 or (rows and total<offset+len(rows)):raise ContractError('pagination_inconsistent')
        coverage='partial' if offset>0 or total>len(rows) else 'complete'
    elif kind=='tracks':
        if not isinstance(data,dict) or data.get('targetIdCard')!=q['subject'] or not isinstance(data.get('points'),list):raise ContractError('track_contract')
        rows=data['points'];total=None;coverage='unknown'
    elif kind=='warning_detail':
        if data is None:rows=[]
        elif isinstance(data,dict) and data.get('idCard')==q['subject']:rows=[data]
        else:raise ContractError('subject_mismatch')
        total=len(rows);coverage='complete'
    else:
        if not isinstance(data,list):raise ContractError('warning_logs_contract')
        rows=data;total=None;coverage='source_window'
    if len(rows)>100:raise ContractError('response_rows_limit')
    result=[]
    for i,row in enumerate(rows):
        if not isinstance(row,dict):raise ContractError('record_contract')
        fields={k:copy.deepcopy(row[k]) for k in FIELDS[kind] if k in row}
        if kind in ('warnings','warning_detail','captures'):
            key='target_id_card' if kind=='captures' else 'idCard'
            if not isinstance(fields.get(key),str) or fields.get(key) not in SUBJECTS or q.get('subject') and fields[key]!=q['subject']:raise ContractError('subject_mismatch')
        if kind=='warning_logs':
            if not isinstance(fields.get('records'),list):raise ContractError('warning_record_contract')
            if len(fields['records'])>100:raise ContractError('response_rows_limit')
            if any(not isinstance(r,dict) for r in fields['records']):raise ContractError('warning_record_contract')
            fields['records']=[{k:r[k] for k in ('id','idCard','createTime') if k in r} for r in fields['records'] if isinstance(r,dict)]
            if any(r.get('idCard')!=q['subject'] for r in fields['records']):raise ContractError('subject_mismatch')
        for key in ('capture_count','warningCount','count'):
            if key in fields and (type(fields[key]) is not int or fields[key]<0):raise ContractError('invalid_count')
        for key,val in fields.items():
            if key=='records':
                if any(any(not isinstance(v,(str,int)) or isinstance(v,bool) or len(str(v))>200 for v in r.values()) for r in val):raise ContractError('invalid_field_type')
                continue
            if not isinstance(val,(str,int,float,type(None))) or isinstance(val,bool) or len(str(val))>500:raise ContractError('invalid_field_type')
        result.append({'source_ref':'response-row-'+str(i+1),'fields':fields})
    return {'version':VERSION,'kind':kind,'synthetic':True,'snapshot_id':SNAPSHOT,'query':q,'records':result,'returned_count':len(result),'total':total,'coverage':coverage,'has_more':total is not None and q['page']*q['page_size']<total,'limitations':[LIMITATIONS[kind],'坐标系尚未确认，本轮不进行精确距离计算。'],'response_digest':digest(payload)}

def fixture_response(kind,data):
    q=normalize_query(kind,data)
    warning=[{'id':i,'idCard':p,'personName':name,'warningTypes':'夜间游荡预警','warningCount':1,'latestTime':'2026-09-20 23:30:00','deductScore':3} for i,(p,name) in enumerate(SUBJECTS.items(),1)]
    if kind=='incidents':rows=[{'cjbh':'DEMO-INCIDENT-'+str(i),'jjbh':'DEMO-REPORT-'+str(i),'cjsj':'2026-09-20 23:10:00','address':'DEMO-演示路段'+str(i),'gisX':'0.001','gisY':'0.001','ajType':'盗窃'} for i in range(1,4)]
    elif kind=='captures':rows=[{'target_id_card':p,'target_name':name,'capture_count':i+1,'tags':'来源演示标签'} for i,(p,name) in enumerate(SUBJECTS.items(),1)]
    elif kind=='tracks':rows=[{'deviceId':'DEMO-DEVICE-'+str(i),'deviceName':'DEMO-LOCATION-'+('A' if i==1 else 'B'),'captureTime':'2026-09-20 23:'+str(10+i)+':00','trackType':0,'lon':0.001*i,'lat':0.001} for i in range(1,3)]
    else:rows=[w for w in warning if not q.get('subject') or w['idCard']==q['subject']]
    if kind in ('incidents','tracks','warnings'):
        timefield={'incidents':'cjsj','tracks':'captureTime','warnings':'latestTime'}[kind]
        rows=[r for r in rows if q['start']<=r[timefield]<=q['end']]
    if kind=='incidents' and q.get('address'):rows=[r for r in rows if q['address'] in r['address']]
    if kind=='incidents' and q.get('center')=='DEMO-LOCATION-B':rows=[]
    if kind=='captures' and (q.get('center')!='DEMO-LOCATION-A' or not q['start']<='2026-09-20 23:15:00'<=q['end']):rows=[]
    if kind in ('incidents','captures','warnings'):
        total=len(rows);offset=(q['page']-1)*q['page_size'];value={'rows':rows[offset:offset+q['page_size']],'total':total,'pageNum':q['page'],'pageSize':q['page_size']}
    elif kind=='tracks':value={'targetIdCard':q['subject'],'targetName':SUBJECTS[q['subject']],'points':rows,'photos':[]}
    elif kind=='warning_detail':value=rows[0] if rows else None
    else:value=[{'warningType':'夜间游荡预警','count':1,'deductScore':3,'records':[{'id':1,'idCard':q['subject'],'createTime':'2026-09-20 23:30:00'}]}]
    return {'code':200,**(value if kind=='warnings' else {'data':value}),'_fixture':{'synthetic':True,'snapshot_id':SNAPSHOT}}
