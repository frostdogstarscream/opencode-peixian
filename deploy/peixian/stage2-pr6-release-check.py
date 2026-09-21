"""PR-6 immutable source, registry and evidence closeout checks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

FILES=['stage2-pr6-'+name for name in ['contract.md','acceptance.md','context-cases.jsonl','openapi.json','release.json']]
PATHS=['services/peixian-control','deploy/peixian/platform-facts','deploy/peixian/platform-config.py','deploy/peixian/Backend.Control.Dockerfile','deploy/peixian/stage2-pr6-release-check.py','deploy/peixian/tests/test_stage2_pr6_release.py','.github/workflows/peixian-stage2-session-context.yml']
BASELINE='679e4e6f7cbe60642c529e0ed840b172e7bd8370'
WORKFLOW='Peixian PR-6 Session Context checks'

def require(ok,code):
    if not ok:raise ValueError(code)

def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True)
    require(p.returncode==0,'git_check_failed');return p.stdout.strip()

def validate(root,candidate=False):
    root=Path(root);specs=root/'specs'
    release=json.loads((specs/'stage2-pr6-release.json').read_text())
    require(release['baseline']==BASELINE and release['stage']=='pr6' and release['schema_version']==7,'release_identity')
    require(release['closeout_status']==('pending' if candidate else 'completed'),'closeout_status')
    require(release['deployment_performed'] is False and release['real_data_accessed'] is False and type(release['model_requests']) is int and release['model_requests']==0,'scope')
    lines=(specs/'stage2-pr6-SHA256SUMS.txt').read_text().splitlines()
    require(len(lines)==len(FILES),'checksum_count')
    expected={}
    for line in lines:
        value,name=line.split('  ');require(name in FILES and name not in expected,'checksum_path');expected[name]=value
    require(set(expected)==set(FILES),'checksum_files')
    for name,digest in expected.items():
        p=specs/name
        require(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest,'checksum_mismatch')
    cases=[json.loads(line) for line in (specs/'stage2-pr6-context-cases.jsonl').read_text().splitlines()]
    require(len(cases)==6 and len({c['id'] for c in cases})==6,'context_corpus')
    store=(root/'services/peixian-control/control/store.py').read_text()
    require('MAX_SCHEMA_VERSION = 7' in store and (root/'services/peixian-control/control/migrations_v7.py').is_file(),'schema_contract')
    historical=['specs/stage2-pr5-*','specs/stage2-pr55-*','specs/stage2-pr56-*','deploy/peixian/stage2-pr5-release-check.py','deploy/peixian/stage2-pr55-release-check.py']
    require(not git(root,'diff','--name-only',BASELINE,'--',*historical),'historical_drift')
    if candidate:
        require(release['github_ci']['executed'] is False,'candidate_ci');return release
    revision=release['implementation_revision'];ci=release['github_ci']
    require(isinstance(revision,str) and re.fullmatch('[0-9a-f]{40}',revision),'implementation_revision')
    require(git(root,'cat-file','-t',revision)=='commit','implementation_commit')
    git(root,'merge-base','--is-ancestor',BASELINE,revision);git(root,'merge-base','--is-ancestor',revision,'HEAD')
    require(not git(root,'diff','--name-only',revision,'--',*PATHS),'implementation_drift')
    require(not git(root,'ls-files','--others','--exclude-standard','--',*PATHS),'untracked_implementation')
    require(ci.get('executed') is True and ci.get('workflow')==WORKFLOW and ci.get('head_sha')==revision and ci.get('conclusion')=='success' and type(ci.get('run_id')) is int and ci['run_id']>0,'ci_receipt')
    require(all(release['tests'].get(k,{}).get('exit_code')==0 for k in ('control_gateway','deployment','bun','historical')),'test_receipts')
    return release

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',action='store_true');a=p.parse_args()
    validate(Path(__file__).resolve().parents[2],a.candidate);print('PR-6 candidate valid' if a.candidate else 'PR-6 closeout valid')
