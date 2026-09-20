import pytest
from shared.connection_policy import policy, request_data, ConnectionFailure

def configuration():
    return policy({'base_url':'http://fixture:8099','allowed_methods':['GET','POST'],'allowed_paths':['/health','/v1/demo/records/query'],'timeout_seconds':10,'max_response_bytes':1048576,'request_rules':[{'method':'GET','path':'/health'},{'method':'POST','path':'/v1/demo/records/query','json':{'module':'funds'}}]})

def test_exact_module_and_health():
    c=configuration()
    assert request_data(c,{'method':'GET','path':'/health'})[0]=='GET'
    assert request_data(c,{'method':'POST','path':'/v1/demo/records/query','json':{'module':'funds'}})[0]=='POST'

@pytest.mark.parametrize('extra',[{'json':{'module':'calls'}},{'json':{'module':'funds','limit':1}},{'json':None},{'json':{}},{'query':{'module':'calls'}},{'method':'GET'},{'path':'/health'}])
def test_cross_module_and_shape_rejected(extra):
    with pytest.raises(ConnectionFailure):request_data(configuration(),{'method':'POST','path':'/v1/demo/records/query','json':{'module':'funds'},**extra})

@pytest.mark.parametrize('rules',[[],None,{},[{'method':'GET','path':'/health','json':{}}],[{'method':'POST','path':'/other','json':{}}],[{'method':'GET','path':'/health','headers':{}}]])
def test_invalid_policy(rules):
    with pytest.raises(ConnectionFailure):policy({**configuration(),'request_rules':rules})

def test_legacy_and_strict_json_types():
    c=configuration();c.pop('request_rules')
    assert request_data(c,{'method':'POST','path':'/v1/demo/records/query','json':{'module':'calls'}})[0]=='POST'
    c=configuration();c['request_rules'][1]['json']={'n':1}
    with pytest.raises(ConnectionFailure):request_data(c,{'method':'POST','path':'/v1/demo/records/query','json':{'n':True}})
