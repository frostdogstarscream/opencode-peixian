"""Check PR-8B immutable code, migration ancestry and exact CI receipts."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
BASELINE='b5910d279d9130ee53cc0d9c8cfb6078607636e8'
FILES=['stage2-pr8b-'+x for x in ['contract.md','acceptance.md','openapi.json','release.json']]
PATHS=['packages/peixian-console','services/peixian-control','deploy/peixian/platform-config.py','deploy/peixian/Backend.Control.Dockerfile','deploy/peixian/stage2-pr8b-release-check.py','deploy/peixian/tests/test_stage2_pr8b_release.py','.github/workflows/peixian-stage2-trusted-result-ui.yml']
WORKFLOW='Peixian PR-8B Trusted Result UI checks'

def require(ok,code):
    if not ok:raise ValueError(code)

def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,text=True,capture_output=True)
    require(p.returncode==0,'git_check_failed');return p.stdout.strip()

def artifacts(specs,candidate):
    release=json.loads((specs/'stage2-pr8b-release.json').read_text())
    require(release['stage']=='pr8b' and release['baseline']==BASELINE and release['schema_version']==9,'identity')
    require(release['closeout_status']==('pending' if candidate else 'completed'),'closeout')
    require(release['deployment_performed'] is False and release['real_data_accessed'] is False and type(release['model_requests']) is int and release['model_requests']==0,'scope')
    entries={}
    for line in (specs/'stage2-pr8b-SHA256SUMS.txt').read_text().splitlines():
        digest,name=line.split('  ');require(name in FILES and name not in entries,'checksum_path');entries[name]=digest
    require(set(entries)==set(FILES),'checksum_set')
    for name,digest in entries.items():
        file=specs/name
        require(not file.is_symlink() and hashlib.sha256(file.read_bytes()).hexdigest()==digest,'checksum_mismatch')
    doc=json.loads((specs/'stage2-pr8b-openapi.json').read_text())
    require(set(['TrustedResultV2','ClaimV1','DataUsageV1','NarrativeReviewV1'])<=set(doc['components']['schemas']),'contract')
    if candidate:require(release['github_ci'].get('executed') is False,'candidate_ci')
    else:
        ci=release['github_ci'];revision=release['implementation_revision']
        require(isinstance(revision,str) and re.fullmatch('[0-9a-f]{40}',revision),'revision')
        require(ci.get('executed') is True and ci.get('head_sha')==revision and ci.get('conclusion')=='success' and ci.get('workflow')==WORKFLOW and type(ci.get('run_id')) is int and ci['run_id']>0,'ci_receipt')
        require(all(release['tests'].get(k,{}).get('exit_code')==0 for k in ('control_gateway','deployment','bun','historical','frontend','browser')),'test_receipts')
    return release

def validate(root,candidate=False):
    root=Path(root);release=artifacts(root/'specs',candidate)
    require('MAX_SCHEMA_VERSION = 9' in (root/'services/peixian-control/control/store.py').read_text(),'schema')
    old=['services/peixian-control/control/migrations_v'+str(v)+'.py' for v in range(4,10)]
    old+=['specs/stage2-pr5*','specs/stage2-pr6*','specs/stage2-pr7*','specs/stage2-pr8a*']
    require(not git(root,'diff','--name-only',BASELINE,'--',*old),'historical_drift')
    if not candidate:
        revision=release['implementation_revision']
        git(root,'merge-base','--is-ancestor',BASELINE,revision);git(root,'merge-base','--is-ancestor',revision,'HEAD')
        require(not git(root,'diff','--name-only',revision,'--',*PATHS),'source_drift')
        require(not git(root,'ls-files','--others','--exclude-standard','--',*PATHS),'untracked_source')
    return release

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',action='store_true');p.add_argument('--auto',action='store_true');args=p.parse_args();root=Path(__file__).resolve().parents[2]
    candidate=args.candidate or (args.auto and json.loads((root/'specs/stage2-pr8b-release.json').read_text())['closeout_status']=='pending')
    validate(root,candidate);print('PR-8B candidate validated' if candidate else 'PR-8B closeout validated')
