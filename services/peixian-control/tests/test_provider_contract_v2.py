import copy
import json
import pytest
from shared import theft_provider_v2 as v

# Independent supplier-document-shaped samples; no v1 fixture generator.
ID='990000200001010014'
KEY=b'k'*32
REF=v.person_ref(ID,KEY,'account/session')
LIMITS={'max_radius_m':5000,'max_duration_seconds':86400*31,'max_page':100,'max_rows':100,'max_response_bytes':1048576}


def query(kind):
    q={'lon':'116.1','lat':'34.1','radius_m':500} if kind in ('incidents','captures') else {'person_ref':REF}
    if kind in v.TIMED:q.update(start='2026-09-20 22:13:14',end='2026-09-21 02:03:04')
    return q


def response(kind):
    rows={
        'incidents':[{'cjbh':'fixture-cj-1','jjbh':'fixture-jj-1','cjsj':'20260921030000','sfsjsx':'20260920220000','sfsjxx':'20260921020000','bzdzmc':'测试地址','cjxz':'来源详址','cjlb':'0101','cjlbDesc':'来源类别','cljgnr':'来源内容','ssxxqk':'来源损失','gisX':'116.1','gisY':'34.1'}],
        'captures':[{'target_id_card':ID,'target_name':'测试对象','capture_count':0,'tags':'来源标签'}],
        'night':[{'targetIdCard':ID,'captureTime':'2026-09-20 23:10:00','location':'测试点位'}],
        'community':[{'idCard':ID,'timeRangeStart':'2026-09-20 01:00:00','timeRangeEnd':'2026-09-20 09:00:00','communityCount':4,'crossHours':8,'communityList':'甲,乙,丙,丁'}],
        'warnings':[{'idCard':ID,'warningCount':1,'warningTypes':'来源规则','deductScore':3}],
    }
    if kind in rows:
        page={'rows':rows[kind],'total':1,'pageNum':1,'pageSize':20}
        return {'code':200,**page} if kind in ('night','community','warnings') else {'code':200,'data':page}
    if kind=='tracks':return {'code':200,'data':{'targetIdCard':ID,'points':[{'deviceId':'test-device','captureTime':'2026-09-20 23:10:00','lon':116.1,'lat':34.1}],'photos':[]}}
    if kind=='warning_detail':return {'code':200,'data':{'idCard':ID,'warningCount':1,'deductScore':3}}
    if kind=='warning_logs':return {'code':200,'data':[{'warningType':'来源规则','count':1,'deductScore':3,'records':[{'idCard':ID,'warningTime':'2026-09-20 23:10:00','warningLocation':'测试位置','detailJson':'{bad'}]}]}
    return {'code':200,'data':{'person':{'sfz':ID,'xm':'测试对象','phone':'13900000000'},'captures':[],'warning':{'idCard':ID}}}


@pytest.mark.parametrize('kind',v.CATALOG)
def test_document_contract_without_fixture(kind):
    result=v.parse_response(kind,query(kind),response(kind),LIMITS,{REF:ID})
    assert result['records'] and result['supplier_snapshot_id'] is None
    assert result['records'][0]['source_ref'].startswith(result['response_snapshot_id']+':')
    public=v.public_result(result,KEY,'account/session')
    assert ID not in json.dumps(public) and 'deductScore' not in json.dumps(public)
    assert '13900000000' not in json.dumps(public)
    assert v.request_spec(kind,query(kind),LIMITS,{REF:ID})['method'] in ('GET','POST')


def test_scope_time_units_and_no_unrequested_filters():
    r=v.request_spec('incidents',query('incidents'),LIMITS,{})
    assert r['json']=={'lon':'116.1','lat':'34.1','scope':0.5,'pageNum':1,'pageSize':20}
    r=v.request_spec('captures',query('captures'),LIMITS,{})
    assert r['json']['scope']==500 and r['json']['startTime'].endswith('22:13:14')
    for field in ('start','end','address','ajType','djdwPrefix'):
        with pytest.raises(v.ContractError):v.normalize('incidents',{**query('incidents'),field:'额外限制'},LIMITS)
    for start in ('2026-09-20','昨晚','2026-9-20 22:13:14'):
        with pytest.raises(v.ContractError):v.normalize('tracks',{**query('tracks'),'start':start},LIMITS)
    assert v.request_spec('tracks',query('tracks'),LIMITS,{REF:ID})['json']['trackTypes']==[0,1,2]


def test_mapping_preserves_source_meaning_and_detail_failure():
    r=v.parse_response('incidents',query('incidents'),response('incidents'),LIMITS,{})
    f=r['records'][0]['fields']
    for field in ('cjbh','jjbh','cjsj','sfsjsx','sfsjxx','bzdzmc','cjxz','cjlb','cjlbDesc','cljgnr','ssxxqk'):assert field in f
    assert 'address' not in f and 'ajType' not in f
    r=v.parse_response('warning_logs',query('warning_logs'),response('warning_logs'),LIMITS,{REF:ID})
    assert r['records'][0]['fields']['records'][0]['detailParseStatus']=='invalid'
    assert r['coverage']=='source_window' and r['returned_count']==1


@pytest.mark.parametrize('bad',[{'code':500,'data':{'rows':[],'total':0}},{'code':200,'data':{}},{'code':200,'data':{'rows':[],'total':-1}},{'code':True,'data':{'rows':[],'total':0}}])
def test_business_failure_not_empty(bad):
    with pytest.raises(v.ContractError):v.parse_response('incidents',query('incidents'),bad,LIMITS,{})


def test_identity_mismatch_unknown_coverage_and_disabled_contracts():
    p=response('tracks');p['data']['targetIdCard']='990000200001010022'
    with pytest.raises(v.ContractError):v.parse_response('tracks',query('tracks'),p,LIMITS,{REF:ID})
    r=v.parse_response('tracks',query('tracks'),response('tracks'),LIMITS,{REF:ID})
    assert r['total'] is None and r['coverage']=='unknown'
    for kind in v.DISABLED:
        with pytest.raises(v.ContractError):v.normalize(kind,{},LIMITS)
    with pytest.raises(v.ContractError):v.normalize('tracks',query('tracks'),{})


def test_snapshot_refs_are_response_scoped_and_zero_not_missing():
    a=v.parse_response('captures',query('captures'),response('captures'),LIMITS,{})
    b=v.parse_response('captures',query('captures'),response('captures'),LIMITS,{})
    assert a['records'][0]['source_ref']!=b['records'][0]['source_ref']
    assert a['records'][0]['fields']['capture_count']==0
    assert a['coverage']=='current_page'


def test_recursive_privacy_and_no_fetch():
    value={'note':ID+' https://internal.invalid/image','nested':{'deductScore':9,'faceSmallImage':'http://private.invalid','phone':'13900000000'},'detailJson':json.dumps({'idCard':ID})}
    result=v.public_result(value,KEY,'owner/session')
    assert ID not in json.dumps(result) and 'internal.invalid' not in json.dumps(result)
    assert result['nested']=={}
    assert v.person_ref(ID,KEY,'other/session')!=REF


def test_serialized_details_cannot_bypass_redaction():
    raw={'detailJson':json.dumps({'deductScore':99,'phone':'13900000000','nested':{'idCard':ID,'faceImage':'http://internal.invalid'}})}
    result=v.public_result(raw,KEY,'owner/session')
    assert 'detailJson' not in result
    assert result['detailParsed']['nested']['idCard'].startswith('person-')
    assert 'deductScore' not in json.dumps(result)
    assert '13900000000' not in json.dumps(result)
    assert v.public_result({'detailJson':'not json'},KEY,'scope')=={'detailParseStatus':'invalid'}
    assert v.public_result({'text':'123456789012345678'},KEY,'scope')['text']=='[身份号码已隐藏]'


def test_warning_dates_are_explicit_calendar_dates():
    with pytest.raises(v.ContractError):
        v.normalize('warnings',{**query('warnings'),'start_date':'2026-9-1','end_date':'2026-09-02'},LIMITS)


def test_malformed_record_is_rejected_not_stringified():
    p=response('tracks');p['data']['points'][0]['deviceName']={'unexpected':'value'}
    with pytest.raises(v.ContractError):v.parse_response('tracks',query('tracks'),p,LIMITS,{REF:ID})
    p=response('warning_logs');del p['data'][0]['records'][0]['idCard']
    with pytest.raises(v.ContractError):v.parse_response('warning_logs',query('warning_logs'),p,LIMITS,{REF:ID})
