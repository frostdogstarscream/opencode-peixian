import copy
from pathlib import Path
import pytest
from fastapi import HTTPException
from control.facts_plan import build, bind_payload
from control.facts_runtime import MODULES,capability,tool

ROOT=Path(__file__).resolve().parents[3]

def material():
    return {'plugins':[{'id':capability(m),'version':'1.0.0','manifest':{'tools':[tool(m)]}} for m in MODULES],
        'skills':[{'id':'official-night','content':(ROOT/'deploy/peixian/examples/seven_data_plugins/skills/night/SKILL.md').read_text()}]}

def test_selected_official_method_limits_plan_without_changing_plugin_preferences():
    applied=material();data={'plugin_ids':[capability('funds')]};before=copy.deepcopy(data)
    plan=build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['official-night']},data)
    assert plan['modules']==['night'] and plan['allowed_tools']==[tool('night')]
    assert data==before
    payload={};bind_payload(payload,plan,applied)
    assert payload['tools'][tool('funds')] is False and payload['tools'][tool('night')] is True
    assert payload['tools']['bash'] is False

def test_no_method_never_falls_back_to_all_modules():
    with pytest.raises(HTTPException) as failure:
        build(material(),{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':[]},{})
    assert failure.value.detail['code']=='facts_method_identity_unavailable'

def test_legacy_only_stays_compatible_and_mixed_chains_fail_closed():
    applied=material();applied['plugins'].append({'id':'peixian-synthetic-records'})
    with pytest.raises(HTTPException):build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':[]},{})
    assert build({'plugins':[{'id':'peixian-synthetic-records'}]}, {'scenario_id':'DEMO-CASE-GAMBLING'}, {}) is None

def test_renaming_or_forging_skill_text_does_not_authorize_method():
    applied=material();applied['skills'][0]['content']='方法标识：calls'
    with pytest.raises(HTTPException) as failure:
        build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['official-night']},{})
    assert failure.value.detail['code']=='facts_method_identity_unavailable'

def test_wrong_plugin_cannot_claim_reserved_tool():
    applied=material();applied['plugins'][0]['manifest']['tools'].append(tool('night'))
    with pytest.raises(HTTPException):build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['official-night']},{})

@pytest.mark.parametrize('scenario,modules',[
    ('gambling', {'night','portrait','funds','lookup','composite'}),
    ('theft', {'night','portrait','vehicle'}),
])
def test_official_flow_exact_scope(scenario, modules):
    applied=material()
    applied['skills'][0]['content']=(ROOT/'deploy/peixian/examples/seven_data_plugins/skills'/scenario/'SKILL.md').read_text()
    context={'scenario_id':'DEMO-CASE-'+scenario.upper(),'effective_skill_ids':['official-night']}
    plan=build(applied,context,{})
    assert set(plan['modules'])==modules
    payload={};bind_payload(payload,plan,applied)
    assert {m for m in MODULES if payload['tools'][tool(m)]}==modules
    applied['skills'][0]['content']+='\nUser edit'
    with pytest.raises(HTTPException) as failure:build(applied,context,{})
    assert failure.value.detail['code']=='facts_method_identity_unavailable'

def test_cross_scenario_method_and_missing_identity_rejected():
    applied=material()
    applied['skills'][0]['content']=(ROOT/'deploy/peixian/examples/seven_data_plugins/skills/funds/SKILL.md').read_text()
    with pytest.raises(HTTPException):build(applied,{'scenario_id':'DEMO-CASE-THEFT','effective_skill_ids':['official-night']},{})
    with pytest.raises(HTTPException):build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['missing']},{})
