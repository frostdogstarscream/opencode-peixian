"""Real temporary Git histories and offline artifacts; no Docker/provider calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'deploy/peixian/stage2-pr55-release-check.py'
spec = importlib.util.spec_from_file_location('pr55_check', SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
SOURCE_FILES=tuple('services/peixian-control/control/'+name for name in (
    'store.py','task_router.py','task_spec.py','agents/registry.py','agents/schema.py',
    'agents/profiles/gambling.json','agents/profiles/gambling_prompt.md','agents/profiles/theft.json','agents/profiles/theft_prompt.md'))+(
    'deploy/peixian/stage2-pr55-release-check.py','deploy/peixian/tests/test_stage2_pr55_release.py','.github/workflows/peixian-stage2-multi-agent.yml')



def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True, stderr=subprocess.PIPE).strip()


def save(root, manifest):
    (root/'specs/stage2-pr55-release.json').write_text(json.dumps(manifest), encoding='utf-8')
    hashes=''.join(hashlib.sha256((root/'specs'/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in check.DELIVERY_FILES)
    (root/'specs/stage2-pr55-SHA256SUMS.txt').write_text(hashes, encoding='utf-8')


@pytest.fixture
def release(tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'.gitignore').write_text('__pycache__/\n')
    for name in SOURCE_FILES + tuple('specs/'+name for name in check.DELIVERY_FILES):
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    git(root,'init','-q');git(root,'config','user.email','test@example.invalid');git(root,'config','user.name','Release test')
    git(root,'add','.');git(root,'commit','-qm','baseline');baseline=git(root,'rev-parse','HEAD')
    (root/'implementation-marker').write_text('source candidate')
    git(root,'add','.');git(root,'commit','-qm','implementation');revision=git(root,'rev-parse','HEAD')
    manifest={'closeout_status':'completed','baseline':baseline,'implementation_revision':revision,
        'schema_version':6,'router_version':'peixian-router-v2','task_spec_version':'task-spec-v2',
        'registry_version':'agent-registry-v1','deployment_performed':False,'model_requests':0,
        'pr6_started':False,'real_data_accessed':False,'profiles':json.loads((ROOT/'specs/stage2-pr55-release.json').read_text())['profiles'],
        'github_ci':{'executed':True,'workflow':check.WORKFLOW,'run_id':123,'head_sha':revision,'conclusion':'success'},
        'tests':{name:{'passed':40 if name=='agent_corpus' else 1,'skipped':0} for name in ('control','gateway','deployment','plugins','agent_corpus','historical_pr5')},
        'delivery_files':list(check.DELIVERY_FILES)}
    save(root,manifest)
    return root,manifest


def test_valid_release_allows_document_only_followup(release):
    root,m=release
    git(root,'add','.');git(root,'commit','-qm','documentation')
    result=check.validate(root)
    assert result['status']=='verified' and result['implementation_revision']==m['implementation_revision']
    assert result['github_verified_online'] is False


@pytest.mark.parametrize('path,value',[
    ('closeout_status','pending'),('github_ci.executed',False),('github_ci.executed',1),
    ('github_ci.workflow','different'),('github_ci.conclusion','failure'),('github_ci.conclusion','skipped'),
    ('github_ci.run_id',0),('github_ci.run_id',True),('github_ci.run_id','123'),
    ('github_ci.head_sha','bad'),('github_ci.head_sha','f'*40),
    ('baseline','bad'),('implementation_revision','f'*40),
    ('schema_version',4),('schema_version',True),('router_version','v2'),
    ('task_spec_version','v2'),('registry_version','v2'),
    ('deployment_performed',True),('pr6_started',True),('real_data_accessed',True),
    ('model_requests',1),('model_requests',False),
    ('tests.control.passed',-1),('tests.gateway.passed',True),
    ('tests.deployment.skipped',1),('tests.plugins.passed','14'),
    ('tests.agent_corpus.passed',39),
])
def test_rejects_false_evidence(release,path,value):
    root,m=release;target=m;keys=path.split('.')
    for key in keys[:-1]:target=target[key]
    target[keys[-1]]=value;save(root,m)
    with pytest.raises(ValueError):check.validate(root)


@pytest.mark.parametrize('path',SOURCE_FILES)
def test_each_fixed_source_path_rejects_drift(release,path):
    root,m=release
    with (root/path).open('a') as stream:stream.write('\n# unverified source change\n')
    with pytest.raises(ValueError,match='implementation_drift'):check.validate(root)
    git(root,'add',path)
    with pytest.raises(ValueError,match='implementation_drift'):check.validate(root)
    git(root,'commit','-qm','later unverified source')
    with pytest.raises(ValueError,match='implementation_drift'):check.validate(root)


@pytest.mark.parametrize('name',check.DELIVERY_FILES)
def test_each_delivery_file_hash_is_checked(release,name):
    root,m=release
    with (root/'specs'/name).open('a') as stream:stream.write(' ')
    with pytest.raises(ValueError):check.validate(root)


@pytest.mark.parametrize('mode',['missing','extra','duplicate','traversal','manifest_extra','symlink'])
def test_exact_safe_delivery_set(release,mode):
    root,m=release;path=root/'specs/stage2-pr55-SHA256SUMS.txt';lines=path.read_text().splitlines()
    if mode=='missing':lines.pop()
    elif mode=='extra':lines.append('0'*64+'  extra.md')
    elif mode=='duplicate':lines.append(lines[0])
    elif mode=='traversal':lines[0]='0'*64+'  ../outside.md'
    elif mode=='manifest_extra':m['delivery_files'].append('extra.md');save(root,m);lines=path.read_text().splitlines()
    elif mode=='symlink':
        target=root/'specs/stage2-pr55-contract.md';content=target.read_bytes();target.unlink()
        outside=root/'outside.md';outside.write_bytes(content);target.symlink_to(outside)
    path.write_text('\n'.join(lines)+'\n')
    with pytest.raises(ValueError):check.validate(root)


def test_unrelated_ci_and_reversed_baseline_rejected(release):
    root,m=release
    tree=git(root,'rev-parse','HEAD^{tree}')
    unrelated=git(root,'commit-tree',tree,'-m','unrelated history')
    m['github_ci']['head_sha']=unrelated;save(root,m)
    with pytest.raises(ValueError,match='ancestor'):check.validate(root)
    m['github_ci']['head_sha']=m['baseline'];save(root,m)
    with pytest.raises(ValueError,match='ancestor'):check.validate(root)
    m['github_ci']['head_sha']=m['implementation_revision'];m['baseline']=unrelated;save(root,m)
    with pytest.raises(ValueError,match='ancestor'):check.validate(root)


@pytest.mark.parametrize('mode',['remove','duplicate','wrong_expectation'])
def test_corpus_content_and_count_rejected(release,mode):
    root,m=release;path=root/'specs/stage2-pr55-agent-cases.jsonl'
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    if mode=='remove':rows.pop()
    elif mode=='duplicate':rows[-1]=rows[0]
    else:rows[0]['query_mode']='clarify'
    path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8');save(root,m)
    with pytest.raises(ValueError):check.validate(root)


def test_source_version_and_openapi_not_just_manifest(release):
    root,m=release
    path=root/'services/peixian-control/control/store.py';path.write_text(path.read_text().replace('MAX_SCHEMA_VERSION = 6','MAX_SCHEMA_VERSION = 7'))
    git(root,'add','.');git(root,'commit','-qm','incompatible version')
    m['implementation_revision']=git(root,'rev-parse','HEAD');m['github_ci']['head_sha']=m['implementation_revision'];save(root,m)
    with pytest.raises(ValueError,match='source_version'):check.validate(root)


def test_cli_output_only_after_validation_and_never_overwrites(release,tmp_path):
    root,m=release;output=tmp_path/'result.json'
    def run():return subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),'--output',str(output)],capture_output=True,text=True)
    m['github_ci']['executed']=False;save(root,m)
    assert run().returncode!=0 and not output.exists()
    m['github_ci']['executed']=True;save(root,m)
    assert run().returncode==0
    before=output.read_bytes();assert json.loads(before)['status']=='verified'
    assert run().returncode!=0 and output.read_bytes()==before


def test_candidate_is_explicit_and_cannot_claim_closeout(release):
    root,m=release;m['closeout_status']='pending';m['github_ci']={'executed':False};save(root,m)
    with pytest.raises(ValueError,match='closeout_status'):check.validate(root)
    assert check.validate(root,candidate=True)['status']=='candidate_only'
    m['github_ci']['executed']=True;save(root,m)
    with pytest.raises(ValueError,match='candidate_must_not_claim_ci'):check.validate(root,candidate=True)
    m['closeout_status']='completed';save(root,m)
    with pytest.raises(ValueError,match='closeout_status'):check.validate(root,candidate=True)


def test_historical_evidence_cannot_be_rewritten(release):
    root,m=release
    p=root/'specs/stage2-pr5-contract.md';p.write_text('original')
    git(root,'add','.');git(root,'commit','-qm','original PR5');m['baseline']=git(root,'rev-parse','HEAD')
    m['implementation_revision']=m['baseline'];m['github_ci']['head_sha']=m['baseline'];save(root,m)
    p.write_text('changed historical evidence')
    with pytest.raises(ValueError,match='historical_artifact_drift'):check.validate(root)


def test_profile_hash_and_untracked_implementation_rejected(release):
    root,m=release
    m['profiles']['theft-assistant']['profile_sha256']='0'*64;save(root,m)
    with pytest.raises(ValueError,match='profile_hash_mismatch'):check.validate(root)


def test_untracked_source_is_not_docs_only(release):
    root,m=release
    p=root/'services/peixian-control/hidden_new_code.py';p.write_text('x=1')
    with pytest.raises(ValueError,match='untracked_implementation'):check.validate(root)
