import json
import pytest
from gateway.service_connections import load_connections
from shared.connection_policy import request_data,ConnectionFailure

def test_loader_accepts_optional_fixed_rules_and_enforces_them(tmp_path):
    path=tmp_path/'connections.json'
    row={'id':'night','plugin_id':'peixian-records-night','alias':'records','allowed_user':'alice','token':'a'*64,
         'headers':{},'base_url':'http://synthetic','allowed_methods':['POST'],'allowed_paths':['/v1/demo/records/query'],
         'timeout_seconds':2,'max_response_bytes':4096,
         'request_rules':[{'method':'POST','path':'/v1/demo/records/query','json':{'module':'night'}}]}
    path.write_text(json.dumps({'account_id':'alice','connections':[row]}))
    loaded=load_connections(path,'alice')['night']
    request_data(loaded,{'method':'POST','path':'/v1/demo/records/query','json':{'module':'night'}})
    with pytest.raises(ConnectionFailure):request_data(loaded,{'method':'POST','path':'/v1/demo/records/query','json':{'module':'funds'}})
    row['unexpected']=True;path.write_text(json.dumps({'account_id':'alice','connections':[row]}))
    with pytest.raises(ValueError):load_connections(path,'alice')
