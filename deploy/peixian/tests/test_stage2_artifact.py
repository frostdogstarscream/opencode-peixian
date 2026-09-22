import copy,importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('stage2_artifact',ROOT/'deploy/peixian/stage2-artifact.py');artifact=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifact)

@pytest.fixture
def bundle(tmp_path):
    for d in ('images','plugins','skills','registries','sbom'):(tmp_path/d).mkdir()
    for f in ('source.tar.gz','frontend.tar.gz','openapi.json'): (tmp_path/f).write_text('synthetic-test')
    sbom={'bomFormat':'CycloneDX','components':[{'type':'library','name':'test','version':'1'}]}
    for role in (*artifact.ROLES,'source'):(tmp_path/'sbom'/f'{role}.cdx.json').write_text(json.dumps(sbom))
    for role in artifact.ROLES:(tmp_path/'images'/f'{role}.tar').write_text('synthetic-test-image')
    plugins={}
    for module in artifact.MODULES:
        pid='peixian-records-'+module;f=tmp_path/'plugins'/(pid+'-1.0.0.zip');f.write_text('synthetic-test-plugin');plugins[pid]={'version':'1.0.0','sha256':artifact.digest(f)}
    (tmp_path/'skills/test.md').write_text('method');(tmp_path/'registries/rules.json').write_text('{}')
    (tmp_path/'rollback-manifest.json').write_text(json.dumps({'schema_version':9,'restore_to_empty_target':True,'downgrade_database':False,'requires_full_backup':True}))
    m={'schema':'peixian.stage2-release','version':'1.0','schema_version':9,'data_environment':'synthetic','tag':artifact.TAG,'source_revision':'1'*40,'source_matches_commit':True,'contains_runtime_data':False,'images':{role:{'image_id':'sha256:'+'2'*64,'source_revision':'1'*40} for role in artifact.ROLES},'plugins':plugins,'skills':{'test':{'sha256':artifact.digest(tmp_path/'skills/test.md')}},'registries':artifact.inventory(tmp_path/'registries'),'files':artifact.inventory(tmp_path)}
    (tmp_path/'release-manifest.json').write_text(json.dumps(m));return tmp_path

def mutate(folder,change):
    p=folder/'release-manifest.json';m=json.loads(p.read_text());change(m);p.write_text(json.dumps(m))

def test_valid_bundle(bundle):assert artifact.validate_manifest(bundle)['schema_version']==9

def test_manifest_pin(bundle):
    pin=artifact.digest(bundle/'release-manifest.json');artifact.validate_manifest(bundle,pin)
    mutate(bundle,lambda m:m.update(tag='other'))
    with pytest.raises(ValueError,match='untrusted_manifest'):artifact.validate_manifest(bundle,pin)

@pytest.mark.parametrize('change',[lambda m:m.update(source_matches_commit=False),lambda m:m.update(schema_version=8),lambda m:m.update(data_environment='production'),lambda m:m.update(contains_runtime_data=True),lambda m:m.update(tag='latest'),lambda m:m['images'].pop('agent'),lambda m:m['images']['control'].update(source_revision='3'*40),lambda m:m['plugins'].pop('peixian-records-night'),lambda m:m['plugins']['peixian-records-funds'].update(sha256='0'*64),lambda m:m['skills']['test'].update(sha256='0'*64),lambda m:m['registries'].update(extra='0'*64),lambda m:m['files'].update({'../secret':'0'*64})])
def test_bad_manifest(bundle,change):
    mutate(bundle,change)
    with pytest.raises(ValueError):artifact.validate_manifest(bundle)

@pytest.mark.parametrize('operation',['change','extra','delete','symlink'])
def test_inventory_drift(bundle,operation):
    if operation=='change':(bundle/'openapi.json').write_text('changed')
    if operation=='extra':(bundle/'.env').write_text('not-a-secret')
    if operation=='delete':(bundle/'images/agent.tar').unlink()
    if operation=='symlink':(bundle/'link').symlink_to(bundle/'openapi.json')
    with pytest.raises(ValueError):artifact.validate_manifest(bundle)

@pytest.mark.parametrize('field,value',[('bomFormat','other'),('components',[])])
def test_invalid_sbom_even_after_rehash(bundle,field,value):
    p=bundle/'sbom/agent.cdx.json';m=json.loads(p.read_text());m[field]=value;p.write_text(json.dumps(m))
    mutate(bundle,lambda m:m['files'].update({'sbom/agent.cdx.json':artifact.digest(p)}))
    with pytest.raises(ValueError,match='sbom_invalid'):artifact.validate_manifest(bundle)

def test_image_identity_requires_exact_revision():
    d={'Id':'sha256:'+'a'*64,'Config':{'Labels':{'org.opencontainers.image.revision':'1'*40,'org.peixian.control.schema.max':'9'}}}
    artifact.image_identity(d,'1'*40,'control')
    with pytest.raises(ValueError,match='image_source_mismatch'):artifact.image_identity(d,'2'*40,'control')

@pytest.mark.parametrize('tag',['stage2-dual-agent-v1.0.0-rc1','stage2-dual-agent-v1.0.0-rc2'])
def test_distinct_candidate_tags_keep_pinned_manifests(bundle,tag):
    mutate(bundle,lambda m:m.update(tag=tag))
    assert artifact.validate_manifest(bundle,artifact.digest(bundle/'release-manifest.json'))['tag']==tag

@pytest.mark.parametrize('tag',['stage2-dual-agent-v1.0.0-rc0','latest','../rc2'])
def test_invalid_candidate_tag(bundle,tag):
    mutate(bundle,lambda m:m.update(tag=tag))
    with pytest.raises(ValueError,match='release_identity'):artifact.validate_manifest(bundle)
