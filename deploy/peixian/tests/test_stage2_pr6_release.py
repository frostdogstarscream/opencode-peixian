"""Real temporary Git histories; offline receipts are not online CI proof."""
import hashlib,importlib.util,json,shutil,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('pr6',ROOT/'deploy/peixian/stage2-pr6-release-check.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
def git(root,*args):return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.PIPE).strip()
def save(root,m):
 (root/'specs/stage2-pr6-release.json').write_text(json.dumps(m))
 (root/'specs/stage2-pr6-SHA256SUMS.txt').write_text(''.join(hashlib.sha256((root/'specs'/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in check.FILES))
@pytest.fixture
def release(tmp_path,monkeypatch):
 root=tmp_path/'repo';root.mkdir()
 for name in check.FILES:
  p=root/'specs'/name;p.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/'specs'/name,p)
 p=root/'services/peixian-control/control';p.mkdir(parents=True);(p/'store.py').write_text('MAX_SCHEMA_VERSION = 7');(p/'migrations_v7.py').write_text('fixture')
 git(root,'init','-q');git(root,'config','user.name','Test');git(root,'config','user.email','test@example.invalid');git(root,'add','.');git(root,'commit','-qm','baseline')
 baseline=git(root,'rev-parse','HEAD');monkeypatch.setattr(check,'BASELINE',baseline)
 (root/'services/peixian-control/marker').write_text('implementation');git(root,'add','.');git(root,'commit','-qm','implementation');revision=git(root,'rev-parse','HEAD')
 m={'stage':'pr6','schema_version':7,'closeout_status':'completed','baseline':baseline,'implementation_revision':revision,'deployment_performed':False,'real_data_accessed':False,'model_requests':0,'github_ci':{'executed':True,'workflow':check.WORKFLOW,'head_sha':revision,'run_id':123,'conclusion':'success'},'tests':{k:{'exit_code':0} for k in ('control_gateway','deployment','bun','historical')}}
 save(root,m);return root,m

def test_valid_receipt(release):
 root,m=release;git(root,'add','.');git(root,'commit','-qm','docs');assert check.validate(root)==m
@pytest.mark.parametrize('field,value',[('closeout_status','pending'),('deployment_performed',True),('real_data_accessed',True),('model_requests',False),('implementation_revision','f'*40),('github_ci.executed',False),('github_ci.run_id',True),('github_ci.conclusion','failure'),('tests.control_gateway.exit_code',1)])
def test_rejects_bad_receipt(release,field,value):
 root,m=release;target=m;keys=field.split('.')
 for k in keys[:-1]:target=target[k]
 target[keys[-1]]=value;save(root,m)
 with pytest.raises(ValueError):check.validate(root)
@pytest.mark.parametrize('name',check.FILES)
def test_hash_drift(release,name):
 root,m=release;p=root/'specs'/name;p.write_text(p.read_text()+' ')
 with pytest.raises(ValueError):check.validate(root)
@pytest.mark.parametrize('staged',[False,True])
def test_implementation_drift(release,staged):
 root,m=release;(root/'services/peixian-control/marker').write_text('changed')
 if staged:git(root,'add','services')
 with pytest.raises(ValueError,match='implementation_drift'):check.validate(root)

def test_corpus_drift(release):
 root,m=release;p=root/'specs/stage2-pr6-context-cases.jsonl';p.write_text('');save(root,m)
 with pytest.raises(ValueError,match='context_corpus'):check.validate(root)


def test_v7_image_preserves_runtime_pool_protocol():
 spec=importlib.util.spec_from_file_location('platform_config_pr6',ROOT/'deploy/peixian/platform-config.py')
 config=importlib.util.module_from_spec(spec);__import__('sys').modules[spec.name]=config;spec.loader.exec_module(config)
 labels={'org.peixian.runtime.protocol':'2','org.peixian.worker.protocol':'2','org.peixian.control.schema.max':'7','org.peixian.worker.capabilities':config.pool_settings.CAPABILITY}
 config.image_supports_orchestration(labels,'control',4)
 labels['org.peixian.control.schema.max']='999'
 with pytest.raises(config.ConfigError):config.image_supports_orchestration(labels,'control',4)
