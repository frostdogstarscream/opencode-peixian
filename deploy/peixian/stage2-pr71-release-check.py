"""PR-7.1 immutable source, registry and evidence closeout checks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

FILES=['stage2-pr7-integration-'+name for name in ['review.md','findings.json','release.json']]
PATHS=['services/peixian-control','deploy/peixian/platform-facts','deploy/peixian/platform-config.py','deploy/peixian/Backend.Control.Dockerfile','deploy/peixian/stage2-pr71-release-check.py','deploy/peixian/tests/test_stage2_pr71_release.py','.github/workflows/peixian-stage2*.yml']
BASELINE='cb080805cb26d5ebbaa95a7283605737e634fee4'
WORKFLOW='Peixian PR-7.1 Integration Review checks'

def require(ok,code):
    if not ok:raise ValueError(code)

def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True)
    require(p.returncode==0,'git_check_failed');return p.stdout.strip()

def validate(root,candidate=False):
    root=Path(root);specs=root/'specs'
    release=json.loads((specs/'stage2-pr7-integration-release.json').read_text())
    require(release['baseline']==BASELINE and release['stage']=='pr71' and release['schema_version']==8,'release_identity')
    require(release['closeout_status']==('pending' if candidate else 'completed'),'closeout_status')
    require(release['deployment_performed'] is False and release['real_data_accessed'] is False and type(release['model_requests']) is int and release['model_requests']==0,'scope')
    lines=(specs/'stage2-pr7-integration-SHA256SUMS.txt').read_text().splitlines()
    require(len(lines)==len(FILES),'checksum_count')
    expected={}
    for line in lines:
        value,name=line.split('  ');require(name in FILES and name not in expected,'checksum_path');expected[name]=value
    require(set(expected)==set(FILES),'checksum_files')
    for name,digest in expected.items():
        p=specs/name
        require(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest,'checksum_mismatch')
    findings=json.loads((specs/'stage2-pr7-integration-findings.json').read_text())
    require(findings['baseline']==BASELINE and len(findings['findings'])==6,'findings_identity')
    require({f['id'] for f in findings['findings']}=={'IR-'+str(n).zfill(3) for n in range(1,7)},'findings_ids')
    require(all(f['status']=='fixed' and f['test_ids'] for f in findings['findings']),'open_findings')
    store=(root/'services/peixian-control/control/store.py').read_text()
    require('MAX_SCHEMA_VERSION = 8' in store and (root/'services/peixian-control/control/migrations_v8.py').is_file(),'schema_contract')
    historical=['specs/stage2-pr5-*','specs/stage2-pr55-*','specs/stage2-pr56-*','specs/stage2-pr6-*','services/peixian-control/control/migrations_v*.py','specs/stage2-pr7-contract.md','specs/stage2-pr7-acceptance.md','specs/stage2-pr7-clarification-cases.jsonl','specs/stage2-pr7-openapi.json','specs/stage2-pr7-release.json','specs/stage2-pr7-SHA256SUMS.txt','deploy/peixian/stage2-pr7-release-check.py','deploy/peixian/stage2-pr6-release-check.py','deploy/peixian/stage2-pr5-release-check.py','deploy/peixian/stage2-pr55-release-check.py']
    require(not git(root,'diff','--name-only',BASELINE,'--',*historical),'historical_drift')
    if candidate:
        require(release['github_ci']['executed'] is False,'candidate_ci');return release
    revision=release['implementation_revision'];ci=release['github_ci']
    require(isinstance(revision,str) and re.fullmatch('[0-9a-f]{40}',revision),'implementation_revision')
    require(git(root,'cat-file','-t',revision)=='commit','implementation_commit')
    git(root,'merge-base','--is-ancestor',BASELINE,revision);git(root,'merge-base','--is-ancestor',revision,'HEAD')
    require(not git(root,'diff','--name-only',revision,'--',*PATHS),'implementation_drift')
    require(not git(root,'ls-files','--others','--exclude-standard','--',*PATHS),'untracked_implementation')
    require(all(f['fix_commit']==revision for f in findings['findings']),'finding_fix_commit')
    require(ci.get('executed') is True and ci.get('workflow')==WORKFLOW and ci.get('head_sha')==revision and ci.get('conclusion')=='success' and type(ci.get('run_id')) is int and ci['run_id']>0,'ci_receipt')
    require(all(release['tests'].get(k,{}).get('exit_code')==0 for k in ('control_gateway','deployment','bun','historical')),'test_receipts')
    return release

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',action='store_true');a=p.parse_args()
    validate(Path(__file__).resolve().parents[2],a.candidate);print('PR-7.1 candidate valid' if a.candidate else 'PR-7.1 closeout valid')
