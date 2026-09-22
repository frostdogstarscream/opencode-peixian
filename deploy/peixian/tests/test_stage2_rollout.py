import copy,importlib.util
from pathlib import Path
import pytest
P=Path(__file__).resolve().parents[1]/'stage2-rollout.py';s=importlib.util.spec_from_file_location('rollout',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def sample():return {'schema_version':9,'source_matches_commit':True,'contains_runtime_data':False,'data_environment':'synthetic','source_revision':'a'*40,'images':{k:{'source_revision':'a'*40,'image_id':'sha256:'+'b'*64} for k in ('control','gateway','agent')}}
ACCOUNTS={'alignment-a':'1'*32,'alignment-b':'2'*32}
@pytest.mark.parametrize('phase,expected',[('legacy',''),('a','1'*32),('ab','1'*32+','+'2'*32)])
def test_gray_scope_is_explicit(phase,expected):
 x=m.projection(sample(),phase,ACCOUNTS);assert set(x['environment'].values())=={expected}
 assert all('ALLOW' not in key for key in x['environment'])
@pytest.mark.parametrize('tamper',['phase','account','duplicate','extra','revision','image','missing','data','match','schema'])
def test_unsafe_rollout_refused(tamper):
 doc=sample();accounts=dict(ACCOUNTS);phase='a'
 if tamper=='phase':phase='all'
 elif tamper=='account':accounts['alignment-a']='admin'
 elif tamper=='duplicate':accounts['alignment-b']=accounts['alignment-a']
 elif tamper=='extra':accounts['other']='3'*32
 elif tamper=='revision':doc['images']['agent']['source_revision']='c'*40
 elif tamper=='image':doc['images']['control']['image_id']='latest'
 elif tamper=='missing':doc['images'].pop('gateway')
 elif tamper=='data':doc['contains_runtime_data']=True
 elif tamper=='match':doc['source_matches_commit']=False
 else:doc['schema_version']=6
 with pytest.raises(ValueError):m.projection(doc,phase,accounts)
