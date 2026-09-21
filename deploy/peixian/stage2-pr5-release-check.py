"""Offline PR-5 evidence validation. Default mode requires completed closeout.

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
    'stage2-pr5-contract.md', 'stage2-pr5-acceptance.md',
    'stage2-pr5-openapi.json', 'stage2-pr5-routing-cases.jsonl', 'stage2-pr5-release.json',
)
IMPLEMENTATION_PATHS = tuple('services/peixian-control/' + path for path in (
    'control/task_router.py', 'control/task_spec.py', 'control/task_methods.py',
    'control/task_targets.py', 'control/app.py', 'control/business_runs.py',
    'control/facts_plan.py', 'control/facts_evidence.py', 'control/store.py',
    'gateway/facts_execution.py', 'shared/task_scope.py',
    'tests/test_task_spec.py', 'tests/test_facts_execution.py',
)) + ('deploy/peixian/stage2-pr5-release-check.py',
      'deploy/peixian/tests/test_stage2_pr5_release.py', '.github/workflows/peixian-stage2.yml')
WORKFLOW = 'Peixian PR-5 TaskSpec checks'


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
    manifest = safe_file(root, 'stage2-pr5-release.json')
    release = json.loads(manifest.read_text(encoding='utf-8'))
    require(release.get('closeout_status') == ('pending' if candidate else 'completed'), 'closeout_status_mismatch')
    require(release.get('deployment_performed') is False and release.get('pr6_started') is False
            and release.get('pr55_started') is False, 'scope_mismatch')
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
        require((root / path).is_file() and not (root / path).is_symlink(), 'implementation_file_missing')
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
    expected = {
        'schema_version': ast.literal_eval(assigned(root, base+'store.py', 'MAX_SCHEMA_VERSION')),
        'router_version': ast.literal_eval(assigned(root, base+'task_router.py', 'VERSION')),
        'target_contract_version': ast.literal_eval(assigned(root, base+'task_targets.py', 'VERSION')),
        'task_spec_version': ast.literal_eval(field(field(field(assigned(root, base+'task_spec.py', 'SPEC_SCHEMA'), 'properties'), 'schema_version'), 'const')),
    }
    require(expected == {'schema_version': 6, 'router_version': 'peixian-router-v1',
                         'target_contract_version': 'method-target-v1', 'task_spec_version': 'task-spec-v1'}, 'source_version_mismatch')
    require(all(type(release.get(key)) is type(value) and release[key] == value for key, value in expected.items()), 'manifest_version_mismatch')
    schema = json.loads(safe_file(root, 'stage2-pr5-openapi.json').read_text(encoding='utf-8'))
    require(schema['components']['schemas']['TaskSpec']['properties']['schema_version']['const'] == expected['task_spec_version'], 'openapi_version_mismatch')
    tests = release['tests']
    require(set(tests) == {'control','gateway','deployment','plugins','router_corpus'}, 'test_groups_mismatch')
    for counts in tests.values():
        require(isinstance(counts, dict) and {'passed','skipped'} <= counts.keys(), 'test_counts_missing')
        require(all(type(value) is int and value >= 0 for value in counts.values()), 'invalid_test_count')
        require(counts['skipped'] == 0, 'tests_skipped')
    cases = [json.loads(line) for line in safe_file(root, 'stage2-pr5-routing-cases.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(len(cases) == 21 == tests['router_corpus']['passed'], 'corpus_count_mismatch')
    require({row['id'] for row in cases} == {f'PR5-R{i:02}' for i in range(1,22)}, 'corpus_identity_mismatch')
    spec = importlib.util.spec_from_file_location('pr5_release_router', root / (base+'task_router.py'))
    router = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(router)
    for row in cases:
        require(type(row['selected_skill']) is bool and isinstance(row['text'],str), 'invalid_corpus_case')
        result = router.parse(row['text'], row['selected_skill'])
        require((result['query_mode_candidate'],result['intent_candidate']) == (row['query_mode'],row['intent']), 'corpus_result_mismatch')
    files = release['delivery_files']
    require(isinstance(files,list) and len(files) == len(DELIVERY_FILES) and set(files) == set(DELIVERY_FILES), 'delivery_set_mismatch')
    entries = {}
    for line in safe_file(root, 'stage2-pr5-SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
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
    parser.add_argument('--candidate', action='store_true', help='Pre-CI validation only; cannot close PR-5')
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
        parser.exit(1, 'PR-5 validation failed: '+str(error)+'\n')


if __name__ == '__main__':
    main()
