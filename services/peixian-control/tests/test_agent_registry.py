import copy,json,hashlib
from dataclasses import FrozenInstanceError
import pytest
from jsonschema import ValidationError
from control.agents import registry


def test_immutable_identity_and_prompt():
    for profile in registry.PROFILES.values():
        assert registry.load([profile.data])[profile.id]==profile
        assert profile.prompt_sha256==hashlib.sha256(profile.prompt.encode()).hexdigest()
        changed=profile.data;changed['name']='changed';assert profile.data['name']!='changed'
        with pytest.raises(FrozenInstanceError):profile.prompt='changed'
        public=profile.public()
        assert set(public)=={'id','name','version','domain','description','supported_intents'}
    legacy=registry.ROOT.parent.parent/'gambling_agent_prompt.md'
    assert registry.require('gambling-assistant').prompt==legacy.read_text()


@pytest.mark.parametrize('kind',['duplicate','extra','unknown_method','draft','scene','intent','flow','path','missing','empty','domain','version','tools','contract'])
def test_closed_registry_rejects_invalid_release(kind,tmp_path):
    profile=registry.require('gambling-assistant');value=profile.data
    (tmp_path/value['prompt_file']).write_text(profile.prompt)
    if kind=='duplicate':
        with pytest.raises(ValueError):registry.load([value,value],tmp_path)
        return
    if kind=='extra':value['extra']=True
    if kind=='unknown_method':value['official_method_ids'].append('peixian.method.unknown')
    if kind=='draft':value['official_method_ids'].append('peixian.method.calls')
    if kind=='scene':value['scenario_ids']=['DEMO-CASE-THEFT']
    if kind=='intent':value['intents']['funds_analysis']['methods']=['vehicles']
    if kind=='flow':value['intents']['integrated_analysis']['methods']=['night']
    if kind=='path':value['prompt_file']='../gambling_agent_prompt.md'
    if kind=='missing':value['prompt_file']='missing.md'
    if kind=='empty':(tmp_path/value['prompt_file']).write_text(' ')
    if kind=='domain':value['domain']='unknown'
    if kind=='version':value['version']='latest'
    if kind=='tools':value['allowed_tools']=['peixian_get_funds_records']
    if kind=='contract':value['claim_profile']='theft-claims-v1'
    with pytest.raises((ValueError,ValidationError)):
        registry.load([value],tmp_path)
