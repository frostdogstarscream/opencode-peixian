import hashlib,importlib.util,json,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('release_check',ROOT/'deploy/peixian/stage2-pr8b-release-check.py');check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)

@pytest.fixture
def files(tmp_path):
    for name in check.FILES+['stage2-pr8b-SHA256SUMS.txt']:shutil.copyfile(ROOT/'specs'/name,tmp_path/name)
    return tmp_path

def update(files,change):
    path=files/'stage2-pr8b-release.json';value=json.loads(path.read_text());change(value);path.write_text(json.dumps(value))
    (files/'stage2-pr8b-SHA256SUMS.txt').write_text(''.join(hashlib.sha256((files/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in check.FILES))

def test_current_candidate_or_closeout():
    release=json.loads((ROOT/'specs/stage2-pr8b-release.json').read_text());check.validate(ROOT,release['closeout_status']=='pending')

@pytest.mark.parametrize('change',[
    lambda v:v.update(stage='wrong'),lambda v:v.update(baseline='0'*40),lambda v:v.update(schema_version=8),
    lambda v:v.update(deployment_performed=True),lambda v:v.update(real_data_accessed=True),lambda v:v.update(model_requests=1),
    lambda v:v.update(closeout_status='wrong')])
def test_bad_metadata(files,change):
    candidate=json.loads((files/'stage2-pr8b-release.json').read_text())['closeout_status']=='pending';update(files,change)
    with pytest.raises(ValueError):check.artifacts(files,candidate)

def test_changed_artifact(files):
    (files/'stage2-pr8b-contract.md').write_text('changed')
    with pytest.raises(ValueError,match='checksum'):check.artifacts(files,json.loads((files/'stage2-pr8b-release.json').read_text())['closeout_status']=='pending')

def test_duplicate_checksum(files):
    path=files/'stage2-pr8b-SHA256SUMS.txt';path.write_text(path.read_text()+path.read_text().splitlines()[0]+'\n')
    with pytest.raises(ValueError,match='checksum_path'):check.artifacts(files,json.loads((files/'stage2-pr8b-release.json').read_text())['closeout_status']=='pending')

@pytest.mark.parametrize('key,value',[('head_sha','0'*40),('conclusion','failure'),('executed',False),('run_id',0),('workflow','other')])
def test_closed_requires_matching_ci(files,key,value):
    def mutate(v):
        v.update(closeout_status='completed',implementation_revision='1'*40,tests={k:{'exit_code':0} for k in ('control_gateway','deployment','bun','historical','frontend','browser')})
        v['github_ci']={'head_sha':'1'*40,'conclusion':'success','executed':True,'run_id':1,'workflow':check.WORKFLOW};v['github_ci'][key]=value
    update(files,mutate)
    with pytest.raises(ValueError,match='ci_receipt'):check.artifacts(files,False)
