"""Read-only N3-E collection. Never start, stop, claim, replay or alter a runtime."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import httpx
from evidence_contract import (EvidenceError, Run, archive_identity, classify_receipts, compare_sets,
    journal_snapshot, regular, require, sha, source_digest, unchanged, utc, validate_public, write_new)

ROOT = Path(__file__).resolve().parents[2]
HOST = ('deploy/peixian/console-worker.py', 'deploy/peixian/console-runtime.py',
        'deploy/peixian/platform-config.py', 'deploy/peixian/platform-capacity.py',
        'services/peixian-control/shared/orchestration_config.py',
        'services/peixian-control/shared/eventhub_config.py', 'services/peixian-control/shared/worker_errors.py')
BUILD = ('services/peixian-control/Dockerfile', 'services/peixian-control/requirements.lock',
         'deploy/peixian/platform.ps1', 'deploy/peixian/platform-manage.py',
         'packages/peixian-console/package.json', 'bun.lock')


def command(*values):
    return subprocess.check_output(values, cwd=ROOT, stderr=subprocess.PIPE, timeout=40)


def fixed(ref):
    require(ref and not ref.startswith('-'), 'invalid_git_ref')
    return command('git', 'rev-parse', '--verify', ref + '^{commit}').decode().strip()


def collect(args, run, cfg):
    value = run.value
    candidate = value['runtime_source_commit']
    archive_stat = regular(args.archive).stat()
    paths = command('git', 'ls-tree', '-r', '--name-only', candidate, 'services/peixian-control/control', 'services/peixian-control/shared').decode().splitlines()
    paths = [p for p in paths if p.endswith('.py')]
    modes = command('git', 'ls-tree', '-r', candidate, 'services/peixian-control/control', 'services/peixian-control/shared').decode().splitlines()
    require(all(line.split()[0] in ('100644', '100755') for line in modes if line.endswith('.py')), 'candidate_link_or_special')
    expected = {p.removeprefix('services/peixian-control/'): source_digest(command('git', 'show', candidate + ':' + p)) for p in paths}
    require(expected, 'empty_source_set')
    for path in paths + list(HOST):
        require(command('git', 'show', candidate + ':' + path) == command('git', 'show', value['repository_baseline'] + ':' + path), 'runtime_inputs_changed')
    host_before = {p: source_digest(regular(ROOT / p).read_bytes()) for p in HOST}
    host_expected = {p: source_digest(command('git', 'show', candidate + ':' + p)) for p in HOST}
    container = 'synthetic-r2-local-console'
    def snapshot():
        v = json.loads(command('docker', 'inspect', container))[0]
        require(v['State']['Running'] and v['State']['Health']['Status'] == 'healthy', 'container_not_healthy')
        return {k: v[k] for k in ('Id', 'Image', 'RestartCount')} | {'started_at': v['State']['StartedAt']}
    before = snapshot()
    image = json.loads(command('docker', 'image', 'inspect', before['Image']))[0]
    platform = {k: image[k.capitalize()] for k in ('os', 'architecture')}
    if image.get('Variant'):
        platform['variant'] = image['Variant']
    archive = archive_identity(args.archive, cfg.images['control'], platform)
    require(before['Image'] in [v.get('digest') for v in archive.values()], 'running_image_not_in_archive')
    require(image['Id'] in [v.get('digest') for v in archive.values()], 'inspect_image_not_in_archive')
    source = '''import os,pathlib,stat,json,hashlib
result={}
for root in ('control','shared'):
 for parent,dirs,files in os.walk('/app/'+root,followlinks=False):
  for name in dirs+files:
   p=pathlib.Path(parent,name)
   if p.is_symlink(): raise RuntimeError('source_link')
   if name.endswith('.py'):
    if not stat.S_ISREG(p.stat().st_mode): raise RuntimeError('source_special')
    raw=p.read_bytes(); result[str(p.relative_to('/app'))]={'raw_sha256':hashlib.sha256(raw).hexdigest(),'lf_sha256':hashlib.sha256(raw.replace(b'\\r\\n',b'\\n')).hexdigest()}
print(json.dumps(result))'''
    actual = json.loads(command('docker', 'exec', container, 'python', '-c', source))
    comparison = compare_sets(expected, actual)
    host = compare_sets(host_expected, host_before)
    # Save detailed differences privately even when the public result is incomplete.
    write_new(args.run_manifest.with_suffix('.sets.json'), {'container': comparison, 'host': host})
    require(comparison['status'] == 'passed' and host['status'] == 'passed', 'source_set_mismatch')
    inputs = {p: {'candidate': source_digest(command('git', 'show', candidate + ':' + p)),
                  'package_source': source_digest(command('git', 'show', value['repository_baseline'] + ':' + p))} for p in BUILD}
    require(all(v['candidate'] == v['package_source'] for v in inputs.values()), 'build_inputs_changed')
    key = (cfg.secrets / 'console-worker.key').read_text().strip()
    private_history = []
    after = journal_snapshot(cfg.worker_root / 'receipts')
    with httpx.Client(base_url=cfg.control_url, trust_env=False, timeout=5,
                      headers={'X-Worker-Key': key, 'X-Peixian-Protocol': '2'}) as api:
        maintenance = api.get('/internal/worker/maintenance'); maintenance.raise_for_status()
        state = maintenance.json()
        for record in after.values():
            if record['status'] == 'recorded':
                continue
            response = api.get('/internal/worker/jobs/' + record['job_id'], params={'attempt': record['attempt'], 'operation_id': record['operation_id']})
            response.raise_for_status(); remote = response.json()
            job = remote['job']
            rid = job['runtime_id']
            import re
            require(re.fullmatch('[0-9a-f]{32}', rid) is not None, 'invalid_runtime_identity')
            ids = command('docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=px-' + rid, '--format', '{{.ID}}').decode().split()
            require(ids, 'runtime_components_missing')
            components = json.loads(command('docker', 'inspect', *ids))
            states = {}
            for component in components:
                labels = component['Config']['Labels']
                role = labels.get('com.docker.compose.service')
                require(role in ('agent', 'gateway', 'model-relay') and role not in states, 'runtime_component_ambiguous')
                require(labels.get('peixian.deployment') == cfg.deployment_id and labels.get('peixian.runtime_id') == rid,
                        'runtime_component_foreign')
                states[role] = 'running' if component['State']['Running'] else 'stopped'
            require(set(states) == {'agent', 'gateway', 'model-relay'}, 'runtime_components_incomplete')
            mutation = cfg.worker_root / 'runtimes' / rid / 'mutation.json'
            mutation_state = 'unknown'
            if mutation.exists():
                observed = json.loads(regular(mutation).read_text(encoding='utf-8'))
                if observed.get('runtime_id') == rid and observed.get('state') == 'idle':
                    mutation_state = 'recorded_idle_not_process_attestation'
            private_history.append({**record, 'classification': 'historical_unconfirmed',
                'server_receipt_present': remote.get('receipt') is not None,
                'job_status_now': remote['job'].get('status'), 'attempt_phase_now': (remote.get('attempt') or {}).get('phase'),
                'current_control_observation': {k: job.get(k) for k in ('gate_policy', 'security_blocked', 'recovery_required', 'applied_revision', 'desired', 'stop_reason')},
                'current_components': states, 'host_mutation_record': mutation_state,
                'gateway_activity_and_mutation_processes': 'not_attested',
                'root_cause': 'undetermined', 'original_operation_success': 'not_proven',
                'disposition': 'owner_decision_required'})
    require(after == journal_snapshot(cfg.worker_root / 'receipts'), 'journals_changed_during_collection')
    unchanged(before, snapshot(), 'container_changed_during_collection')
    require(host_before == {p: source_digest(regular(ROOT / p).read_bytes()) for p in HOST}, 'host_source_changed_during_collection')
    require(actual == json.loads(command('docker', 'exec', container, 'python', '-c', source)), 'container_source_changed_during_collection')
    now = regular(args.archive).stat()
    require((archive_stat.st_size, archive_stat.st_mtime_ns) == (now.st_size, now.st_mtime_ns), 'archive_changed_during_collection')
    groups = classify_receipts(value['journal_before'], after, [v['job_id'] for v in value['owned_jobs']])
    run.value['owned_operations'] = ['/'.join(str(v[k]) for k in ('job_id', 'attempt', 'operation_id')) for v in groups['groups']['batch']]
    require(groups['status'] == 'passed', 'unattributed_or_missing_journals')
    write_new(args.run_manifest.with_suffix('.historical.json'), {'run_id': value['run_id'], 'records': private_history})
    def reference(kind, digest, source):
        return {'object_kind': kind, 'digest': digest, 'algorithm': 'sha256', 'source': source, 'platform': platform}
    return {'evidence_format': 2, 'status': 'passed', 'run_id': value['run_id'], 'collected_at': utc(),
        'correction_of': 'deploy/peixian/reports/n3-local-evidence.json',
        'correction_reason': 'inspect_fields_are_not_archive_config_objects',
        'runtime_source_commit': candidate, 'tool_source_commit': value['tool_source_commit'],
        'package_source_commit': value['repository_baseline'], 'platform': platform,
        'image': {'container_image_reference': reference('docker_container_Image', before['Image'], 'container_inspect'),
                  'docker_image_inspect_id': reference('docker_image_Id', image['Id'], 'image_inspect'),
                  'image_revision_label': image['Config']['Labels'].get('org.opencontainers.image.revision'), **archive},
        'python_source_set_verified': comparison, 'host_disk_source_verified': host,
        'worker_loaded_version': 'not_proven_no_startup_digest_attestation',
        'build_input_subset': inputs, 'static_resources': 'not_verified_by_python_source_check',
        'receipt_counts': groups['counts'], 'historical_unconfirmed': len(private_history),
        'maintenance': {k: state.get(k) for k in ('maintenance_mode', 'capacity_healthy', 'recovery_required', 'security_pending')},
        'resource_state': 'control_observation_only_not_fresh_full_docker_reconciliation',
        'release_status': 'blocked', 'blocked': ['historical_owner_decision', 'runtime_loaded_attestation', 'N4', 'N5'],
        'scope': 'local_read_only_no_fault_or_load'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'archive', 'run-manifest', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--tool-commit', required=True)
    parser.add_argument('--package-source-commit', required=True)
    args = parser.parse_args()
    require(args.output.resolve().is_relative_to((ROOT / 'deploy/peixian/reports').resolve()), 'report_directory_required')
    run = None
    try:
        require(not args.output.exists() and not args.run_manifest.exists(), 'output_exists')
        require(args.run_manifest.resolve().is_relative_to((ROOT / 'deploy/peixian/.runtime').resolve()), 'private_run_manifest_required')
        module = importlib.util.spec_from_file_location('evidence_settings', ROOT / 'deploy/peixian/platform-config.py')
        settings = importlib.util.module_from_spec(module); sys.modules[module.name] = settings; module.loader.exec_module(settings)
        cfg = settings.load_config(args.config)
        require(cfg.deployment_id == 'synthetic-r2-local' and cfg.public_url == 'https://127.0.0.1:19444', 'isolated_namespace_required')
        candidate, tool, baseline = fixed(args.source_commit), fixed(args.tool_commit), fixed(args.package_source_commit)
        for path in ('deploy/peixian/n3-local-evidence.py', 'deploy/peixian/evidence_contract.py'):
            require(source_digest(regular(ROOT / path).read_bytes())['lf_sha256'] == source_digest(command('git', 'show', tool + ':' + path))['lf_sha256'], 'tool_source_mismatch')
        run = Run.create(args.run_manifest, baseline, candidate, tool, ['read_only_identity'], journal_snapshot(cfg.worker_root / 'receipts'))
        report = collect(args, run, cfg)
        validate_public(report)
        write_new(args.output, report)
        run.value['evidence_files'] = [{'sha256': sha(regular(args.output).read_bytes()), 'kind': 'read_only_identity'}]
        run.finish('passed')
        print(json.dumps({'status': 'passed', 'release_status': 'blocked', 'run_id': run.value['run_id']}))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, EvidenceError) else 'collection_incomplete'
        if run:
            run.finish('incomplete', code)
        if not args.output.exists():
            write_new(args.output, {'evidence_format': 2, 'status': 'incomplete', 'failure_code': code,
                                    'run_id': run.value['run_id'] if run else None})
        print(json.dumps({'status': 'incomplete', 'failure_code': code}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
