import copy
import pytest
import jsonschema
from fastapi import HTTPException
from control.developer_registry import registry as reg
from control.facts_runtime import FactsState
from test_multi_agent import multi,prepare,submit
from test_task_spec import task_env,v6

@pytest.mark.parametrize('value,expression,expected',[
 ('1.0.0','=1.0.0',True),('1.0.1','=1.0.0',False),('1.10.0','>=1.0.0 <2.0.0',True),('2.0.0','>=1.0.0 <2.0.0',False),('0.9.9','>=1.0.0 <2.0.0',False)])
def test_semver_numeric(value,expression,expected):assert reg.compatible(value,expression)==expected

@pytest.mark.parametrize('value',['01.0.0','1.0','v1.0.0','1.0.0-beta','1.0.0+meta','1.0.0\n',None])
def test_invalid_semver(value):
 with pytest.raises(ValueError):reg.compatible(value,'=1.0.0')

@pytest.mark.parametrize('expression',['1.*','^1.0.0','>=2.0.0 <1.0.0','>=1.0.0','1.0.0'])
def test_invalid_range(expression):
 with pytest.raises(ValueError):reg.compatible('1.0.0',expression)

@pytest.mark.parametrize('change',['extra','duplicate','state','tool','plugin','schema','implementation','agent','method'])
def test_closed_release_contract(change):
 d=reg.REGISTRY.documents()
 if change=='extra':d['capabilities'][0]['url']='https://invalid'
 if change=='duplicate':d['capabilities'].append(d['capabilities'][0])
 if change=='state':d['rules'][0]['state']='active'
 if change=='tool':d['capabilities'][0]['tool_ids']=['bash']
 if change=='plugin':d['capabilities'][0]['plugin_id']='other'
 if change=='schema':d['capabilities'][0]['output_schema']='arbitrary'
 if change=='implementation':d['rules'][0]['implementation']='eval(user)'
 if change=='agent':d['rules'][0]['supported_agents']=['unknown']
 if change=='method':d['methods'][0]['required_capabilities']=['records.funds']
 with pytest.raises((ValueError,jsonschema.ValidationError)):reg.Registry(**d)

@pytest.mark.parametrize('kind',['capabilities','rules'])
@pytest.mark.parametrize('state',[s for s in reg.STATES if s!='published'])
def test_unpublished_is_local_without_dispatch(multi,monkeypatch,kind,state):
 d=reg.REGISTRY.documents()
 for item in d[kind]:
  if item['id'] in ('records.vehicle','theft.vehicle.summary'):item['state']=state
 monkeypatch.setattr(reg,'REGISTRY',reg.Registry(**d))
 request,task=prepare(multi)
 assert task['local']['code']==('capability_not_ready' if kind=='capabilities' else 'rule_not_ready')
 _,row,snapshot=submit(multi,request,task)
 assert row['status']=='completed' and snapshot['allowed_tools']==[] and 'facts_plan' not in snapshot
 assert not multi[0].one('SELECT * FROM run_deliveries WHERE run_id=?',(row['id'],))
 assert not multi[0].one("SELECT * FROM run_events WHERE run_id=? AND event_key LIKE 'facts.%'",(row['id'],))

@pytest.mark.parametrize('change',['digest','version','implementation','removed','current_disabled'])
def test_frozen_identity_or_revocation_rejects_before_reserve(multi,monkeypatch,change):
 request,task=prepare(multi);_,row,snapshot=submit(multi,request,task)
 if change=='current_disabled':
  d=reg.REGISTRY.documents()
  next(c for c in d['capabilities'] if c['id']=='records.vehicle')['state']='disabled'
  monkeypatch.setattr(reg,'REGISTRY',reg.Registry(**d))
 elif change=='removed':snapshot['facts_plan'].pop('registry')
 elif change=='digest':snapshot['facts_plan']['registry']['digest']='0'*64
 elif change=='version':snapshot['facts_plan']['registry']['capabilities'][0]['plugin_version']='1.9.0'
 else:snapshot['facts_plan']['registry']['rules'][0]['implementation']='funds_summary_v1'
 with multi[0].tx() as db:
  with pytest.raises(HTTPException):FactsState(multi[0]).authorize(db,row,snapshot,'vehicle')


def test_manifest_range_and_snapshot(multi):
 request,task=prepare(multi);_,row,snapshot=submit(multi,request,task)
 plan=snapshot['facts_plan'];frozen=plan['registry']
 assert snapshot['registry_snapshot']==frozen
 assert frozen['capabilities'][0]['output_schema']=='vehicle-records-v1'
 plugins=copy.deepcopy(multi[7]['plugins'])
 next(p for p in plugins if p['id']=='peixian-records-vehicle')['version']='1.12.3'
 assert reg.REGISTRY.freeze('theft-assistant',['vehicles'],plugins)['capabilities'][0]['plugin_version']=='1.12.3'
 next(p for p in plugins if p['id']=='peixian-records-vehicle')['version']='2.0.0'
 with pytest.raises(ValueError):reg.REGISTRY.freeze('theft-assistant',['vehicles'],plugins)
 assert reg.rule_bindings(frozen)==plan['scenario']['rule_bindings']


@pytest.mark.parametrize('change',['none','digest','binding','tools'])
def test_gateway_validates_frozen_plan(multi,change):
 from shared.developer_plan import validate
 request,task=prepare(multi);_,_,snapshot=submit(multi,request,task)
 plan=snapshot['facts_plan']
 if change=='none':validate(plan);return
 if change=='digest':plan['registry']['digest']='0'*64
 if change=='binding':plan['scenario']['rule_bindings'][0]['implementation']='funds_summary_v1'
 if change=='tools':plan['allowed_tools']=['bash']
 with pytest.raises(ValueError):validate(plan)
