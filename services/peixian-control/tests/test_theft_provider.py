import copy
import pytest
from shared.theft_provider import *
def query(kind):
    q={'start':DATES[0],'end':DATES[1]}
    if kind in ('tracks','warning_detail','warning_logs'):q['subject']='DEMO-PERSON-001'
    if kind in ('warning_detail','warning_logs'):q={ 'subject':'DEMO-PERSON-001'}
    if kind=='incidents':q['address']='DEMO-演示路段'
    if kind=='captures':q.update(center='DEMO-LOCATION-A',radius_m=1000)
    return q
@pytest.mark.parametrize('kind',CATALOG)
def test_contract(kind):
    q=query(kind);response=fixture_response(kind,q);value=parse_response(kind,q,response)
    assert value['records'] and value['synthetic'] and 'deductScore' not in canonical(value)
    assert 'faceStoragePath' not in canonical(value)
    assert request_spec(kind,q)['method']==CATALOG[kind][1]
    response['_fixture']['snapshot_id']='old'
    with pytest.raises(ContractError):parse_response(kind,q,response)
def test_scope_and_units():
    q={**query('incidents'),'center':'DEMO-LOCATION-A','radius_m':1500}
    assert request_spec('incidents',q)['json']['scope']==1.5
    q.pop('address');assert request_spec('captures',q)['json']['scope']==1500
    for data in ({**query('tracks'),'subject':'real-id'},{**q,'url':'http://anything'},{**q,'radius_m':1.5}):
        with pytest.raises(ContractError):normalize_query('captures',data)
def test_pagination_no_false_completeness():
    q={**query('incidents'),'page_size':1}
    v=parse_response('incidents',q,fixture_response('incidents',q))
    assert v['coverage']=='partial' and v['total']==3 and len(v['records'])==1 and v['has_more']
    payload=fixture_response('incidents',q);payload['data']['total']=0
    with pytest.raises(ContractError):parse_response('incidents',q,payload)
def test_subject_boundaries_and_unknown_response():
    q=query('tracks');p=fixture_response('tracks',q);p['data']['targetIdCard']='DEMO-PERSON-002'
    with pytest.raises(ContractError):parse_response('tracks',q,p)
    for p in ({'code':500},{'code':200,'data':[]},None):
        with pytest.raises(ContractError):parse_response('incidents',query('incidents'),p)
def test_empty_is_not_absence():
    q={**query('incidents'),'start':'2026-09-01 00:00:00','end':'2026-09-02 00:00:00'}
    v=parse_response('incidents',q,fixture_response('incidents',q));assert not v['records'] and v['coverage']=='complete' and v['limitations']
