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

def test_scene_fallback_is_fixed_and_relations_include_composite():
    plan=build(material(),{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':[]},{})
    assert 'lookup' in plan['modules'] and 'composite' in plan['modules']
    assert set(plan['modules'])==set(MODULES)

def test_legacy_only_stays_compatible_and_mixed_chains_fail_closed():
    applied=material();applied['plugins'].append({'id':'peixian-synthetic-records'})
    with pytest.raises(HTTPException):build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':[]},{})
    assert build({'plugins':[{'id':'peixian-synthetic-records'}]}, {'scenario_id':'DEMO-CASE-GAMBLING'}, {}) is None

def test_renaming_or_forging_skill_text_does_not_authorize_method():
    applied=material();applied['skills'][0]['content']='方法标识：calls'
    plan=build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['official-night']},{})
    assert set(plan['methods'])=={'night','companions','funds','relations','calls','vehicles'}
    assert plan['allowed_capabilities']==[capability(m) for m in plan['modules']]

def test_wrong_plugin_cannot_claim_reserved_tool():
    applied=material();applied['plugins'][0]['manifest']['tools'].append(tool('night'))
    with pytest.raises(HTTPException):build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['official-night']},{})
