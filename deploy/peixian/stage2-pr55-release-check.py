"""Offline PR-5.5 evidence validation. Default mode requires completed closeout.

--candidate is an explicit pre-CI bootstrap, never a completed release. It validates
artifacts and tests but cannot attest to CI or pin its own not-yet-created commit.
Remote GitHub authenticity must also be checked by the release operator.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

DELIVERY_FILES = (
    'stage2-pr55-contract.md', 'stage2-pr55-acceptance.md',
    'stage2-pr55-openapi.json', 'stage2-pr55-agent-cases.jsonl', 'stage2-pr55-release.json',
)
IMPLEMENTATION_PATHS = ('services/peixian-control', 'deploy/peixian/stage2-pr55-release-check.py',
    'deploy/peixian/tests/test_stage2_pr55_release.py', '.github/workflows/peixian-stage2-multi-agent.yml')
WORKFLOW = 'Peixian PR-5.5 Multi-Agent checks'
HISTORICAL_PATHS = ('specs/stage2-pr5-*','deploy/peixian/stage2-pr5-release-check.py','deploy/peixian/tests/test_stage2_pr5_release.py')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
    require(result.returncode == 0, 'git_check_failed')
    return result.stdout.strip()


def revision(root, value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value), 'invalid_revision')
    require(git(root, 'cat-file', '-t', value) == 'commit', 'revision_not_commit')


def ancestor(root, old, new):
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', old, new],
                           cwd=root, capture_output=True).returncode == 0, 'revision_not_ancestor')


def assigned(root, path, name):
    tree = ast.parse((root / path).read_text(encoding='utf-8'))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)]
    require(len(values) == 1, 'source_constant_missing')
    return values[0]


def field(node, key):
    require(isinstance(node, ast.Dict), 'source_schema_missing')
    values = [value for name, value in zip(node.keys, node.values)
              if isinstance(name, ast.Constant) and name.value == key]
    require(len(values) == 1, 'source_schema_missing')
    return values[0]


def safe_file(root, name):
    path = root / 'specs' / name
    require(path.is_file() and not path.is_symlink() and path.resolve().parent == (root / 'specs').resolve(), 'unsafe_delivery_file')
    return path


def validate(root, *, candidate=False):
    root = Path(root).resolve()
    manifest = safe_file(root, 'stage2-pr55-release.json')
    release = json.loads(manifest.read_text(encoding='utf-8'))
    require(release.get('closeout_status') == ('pending' if candidate else 'completed'), 'closeout_status_mismatch')
    require(release.get('deployment_performed') is False and release.get('pr6_started') is False
            and release.get('real_data_accessed') is False, 'scope_mismatch')
    require(type(release.get('model_requests')) is int and release['model_requests'] == 0, 'model_requests_mismatch')
    require('source_revision' not in release and 'github_ci_executed' not in release, 'obsolete_manifest_fields')
    head = git(root, 'rev-parse', 'HEAD')
    baseline, implementation = release['baseline'], release['implementation_revision']
    for value in (baseline, implementation, head):
        revision(root, value)
    ancestor(root, baseline, implementation)
    ancestor(root, implementation, head)
    # A candidate has no self-referential implementation commit/CI attestation yet.
    if not candidate:
        require(not git(root, 'diff', '--name-only', implementation, '--', *IMPLEMENTATION_PATHS), 'implementation_drift')
        require(not git(root, 'diff', '--cached', '--name-only', implementation, '--', *IMPLEMENTATION_PATHS), 'implementation_drift')
    for path in IMPLEMENTATION_PATHS:
        require((root / path).exists() and not (root / path).is_symlink(), 'implementation_file_missing')
    require(not git(root,'diff','--name-only',baseline,'--',*HISTORICAL_PATHS), 'historical_artifact_drift')
    require(not git(root,'diff','--cached','--name-only',baseline,'--',*HISTORICAL_PATHS), 'historical_artifact_drift')
    if not candidate:
        require(not git(root,'ls-files','--others','--exclude-standard','--',*IMPLEMENTATION_PATHS), 'untracked_implementation')
    ci = release['github_ci']
    if candidate:
        require(ci.get('executed') is False, 'candidate_must_not_claim_ci')
    else:
        require(ci.get('executed') is True, 'ci_not_executed')
        require(ci.get('workflow') == WORKFLOW, 'ci_workflow_mismatch')
        require(type(ci.get('run_id')) is int and ci['run_id'] > 0, 'invalid_ci_run_id')
        require(ci.get('conclusion') == 'success', 'ci_not_successful')
        revision(root, ci.get('head_sha'))
        ancestor(root, implementation, ci['head_sha'])
        ancestor(root, ci['head_sha'], head)
    base = 'services/peixian-control/control/'
    v2 = [n.value for n in ast.parse((root/(base+'task_spec.py')).read_text()).body
          if isinstance(n,ast.Assign) and any(ast.unparse(t)=="SPEC_V2_SCHEMA['properties']['schema_version']" for t in n.targets)]
    require(len(v2)==1,'source_schema_missing')
    expected={'schema_version':ast.literal_eval(assigned(root,base+'store.py','MAX_SCHEMA_VERSION')),
        'router_version':ast.literal_eval(assigned(root,base+'task_router.py','MULTI_VERSION')),
        'task_spec_version':ast.literal_eval(v2[0])['const'],
        'registry_version':ast.literal_eval(assigned(root,base+'agents/registry.py','VERSION'))}
    require(expected=={'schema_version':6,'router_version':'peixian-router-v2','task_spec_version':'task-spec-v2','registry_version':'agent-registry-v1'},'source_version_mismatch')
    require(all(type(release.get(k)) is type(v) and release[k]==v for k,v in expected.items()),'manifest_version_mismatch')
    schema=json.loads(safe_file(root,'stage2-pr55-openapi.json').read_text())
    require(schema['components']['schemas']['TaskSpecV2']['properties']['schema_version']['const']=='task-spec-v2','openapi_version_mismatch')
    profiles={}
    for name in ('gambling','theft'):
        path=root/(base+'agents/profiles/'+name+'.json');doc=json.loads(path.read_text())
        prompt_name=doc['prompt_file']
        require(re.fullmatch('[a-z_]+[.]md',prompt_name) is not None,'unsafe_prompt')
        prompt_path=path.parent/prompt_name
        require(prompt_path.is_file() and not prompt_path.is_symlink(),'unsafe_prompt')
        prompt=prompt_path.read_text(encoding='utf-8')
        hashes={'version':doc['version'],'profile_sha256':hashlib.sha256((json.dumps(doc,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n'+prompt).encode()).hexdigest(),
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
        require(release['profiles'].get(doc['id'])==hashes,'profile_hash_mismatch')
        profiles[doc['id']]=doc
    require(set(release['profiles'])==set(profiles),'profile_set_mismatch')
    tests=release['tests']
    require(set(tests)=={'control','gateway','deployment','plugins','agent_corpus','historical_pr5'},'test_groups_mismatch')
    for counts in tests.values():
        require(isinstance(counts,dict) and {'passed','skipped'}<=counts.keys(),'test_counts_missing')
        require(all(type(v) is int and v>=0 for v in counts.values()),'invalid_test_count')
        require(counts['passed']>0 and counts['skipped']==0,'tests_missing_or_skipped')
    cases=[json.loads(line) for line in safe_file(root,'stage2-pr55-agent-cases.jsonl').read_text().splitlines() if line.strip()]
    require(len(cases)==40==tests['agent_corpus']['passed'],'corpus_count_mismatch')
    require({row['id'] for row in cases}=={f'PR55-R{i:02}' for i in range(1,41)},'corpus_identity_mismatch')
    from collections import Counter
    from types import SimpleNamespace
    require(Counter(row['category'] for row in cases)=={'gambling':15,'theft':15,'cross_agent':5,'injection':5},'corpus_categories_mismatch')
    spec=importlib.util.spec_from_file_location('pr55_router',root/(base+'task_router.py'))
    router=importlib.util.module_from_spec(spec);spec.loader.exec_module(router)
    for row in cases:
        require(type(row['selected_skill']) is bool and isinstance(row['text'],str),'invalid_corpus_case')
        result=router.parse(row['text'],row['selected_skill'],SimpleNamespace(data=profiles[row['agent_id']]))
        require((result['query_mode_candidate'],result['intent_candidate'])==(row['query_mode'],row['intent']),'corpus_result_mismatch')
    files = release['delivery_files']
    require(isinstance(files,list) and len(files) == len(DELIVERY_FILES) and set(files) == set(DELIVERY_FILES), 'delivery_set_mismatch')
    entries = {}
    for line in safe_file(root, 'stage2-pr55-SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([a-zA-Z0-9_.-]+)', line)
        require(match is not None, 'invalid_checksum_entry')
        digest, name = match.groups()
        require(name not in entries, 'duplicate_checksum')
        entries[name] = digest
    require(set(entries) == set(DELIVERY_FILES), 'checksum_set_mismatch')
    for name, digest in entries.items():
        require(hashlib.sha256(safe_file(root,name).read_bytes()).hexdigest() == digest, 'delivery_hash_mismatch')
    return {'status':'candidate_only' if candidate else 'verified', 'head_sha':head,
            'implementation_revision':implementation, 'github_verified_online':False,
            'router_cases':len(cases), 'deployment_performed':False, 'model_requests':0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--candidate', action='store_true', help='Pre-CI validation only; cannot close PR-5.5')
    args = parser.parse_args()
    try:
        result = validate(args.root, candidate=args.candidate)
        encoded = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
        if args.output:
            # Validate everything first; never overwrite a prior evidence artifact.
            with args.output.open('x',encoding='utf-8') as stream:
                stream.write(encoded)
        print(encoded,end='')
    except (ValueError, KeyError, TypeError, OSError, SyntaxError) as error:
        parser.exit(1, 'PR-5.5 validation failed: '+str(error)+'\n')


if __name__ == '__main__':
    main()
