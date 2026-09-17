"""Read-only gate, separate from development package assembly. Never rewrites a package."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
from evidence_contract import EvidenceError, archive_identity, read_json, regular, require, safe_name, sha, validate_public, write_new


def source_equal(name, left, right):
    # Git archive on Windows may apply the repository's text EOL attributes.
    # Archive/package integrity is separately checked on raw bytes above.
    text = Path(name).suffix in ('.py', '.json', '.md', '.txt', '.ps1', '.sh', '.lock', '.mjs', '.service', '.conf')
    if text and 'migration' not in name.lower():
        return left.replace(b'\r\n', b'\n') == right.replace(b'\r\n', b'\n')
    return left == right


def verify_package(folder):
    folder = Path(folder)
    sums = {}
    for line in regular(folder / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        safe_name(name)
        require(name not in sums, 'duplicate_checksum')
        sums[name] = digest
    actual = set()
    for path in folder.rglob('*'):
        require(not path.is_symlink(), 'package_link')
        if path.is_dir():
            continue
        regular(path)
        name = path.relative_to(folder).as_posix()
        if name == 'SHA256SUMS':
            continue
        actual.add(name)
        require(name in sums, 'unlisted_package_file')
        with path.open('rb') as source:
            require(hashlib.file_digest(source, 'sha256').hexdigest() == sums[name], 'package_checksum_mismatch')
    require(actual == sums.keys(), 'package_file_missing')
    manifest = read_json(folder / 'release-manifest.json')
    require(manifest.get('source_matches_commit') is True, 'package_source_mismatch')
    require(re.fullmatch('[0-9a-f]{40}', manifest.get('source_commit', '')) is not None, 'fixed_source_commit_required')
    # Independently compare exported deployment sources to the fixed source archive.
    with tarfile.open(regular(folder / 'source.tar.gz'), 'r:gz') as source:
        members = {m.name: m for m in source.getmembers()}
        for name in actual:
            if name.startswith(('deploy/', 'services/')):
                require(name in members and members[name].isfile(), 'source_archive_file_missing')
                archived = source.extractfile(members[name]).read()
                committed = subprocess.check_output(['git', 'show', manifest['source_commit'] + ':' + name],
                    cwd=Path(__file__).resolve().parents[2], stderr=subprocess.PIPE, timeout=15)
                require(source_equal(name, archived, committed), 'source_archive_git_blob_mismatch')
                require(source_equal(name, archived, (folder / name).read_bytes()), 'source_archive_content_mismatch')
    return manifest, sums


def runtime_pool_blockers(manifest, profile):
    if manifest.get('control_schema_version') != 5 and manifest.get('platform_config_version') != 4:
        return []
    blocked = []
    pool = manifest.get('effective_config', {}).get('runtime_pool', {})
    if (manifest.get('control_schema_version') != 5 or manifest.get('platform_config_version') != 4
            or manifest.get('worker_capabilities') != ['runtime_pool_v1']
            or pool.get('runtime_mode') != 'on_demand'
            or pool.get('capacity_wait_enabled') is not False
            or pool.get('idle_pause_enabled') is not False):
        blocked.append('pr7_runtime_pool_contract_mismatch')
    required = {'PR7A-2slot-5account', 'PR7A-v5-restore', 'PR7A-component-compatibility'}
    if not required <= set(profile.get('required_cases', [])):
        blocked.append('pr7_required_profile_cases_missing')
    return blocked


def check(folder, evidence, profile):
    manifest, sums = verify_package(folder)
    pool_blocked = runtime_pool_blockers(manifest, profile)
    if evidence.get('status') in ('incomplete', 'archive_verified'):
        return {'status': 'blocked', 'blocked': ['complete_runtime_evidence_required', 'N4', 'N5'] + pool_blocked,
                'source_commit': manifest['source_commit'], 'checksums_verified': len(sums),
                'package_manifest_sha256': sums['release-manifest.json'], 'production_approved': False}
    validate_public(evidence)
    require(manifest['source_commit'] == evidence['package_source_commit'], 'evidence_package_commit_mismatch')
    images = manifest['requested_images']
    identity = archive_identity(Path(folder) / 'images.tar', images['control'], evidence['platform'])
    for key, value in identity.items():
        require(value == evidence['image'][key], 'evidence_archive_identity_mismatch')
    for component, tag in images.items():
        objects = archive_identity(Path(folder) / 'images.tar', tag, evidence['platform'])
        recorded = [v for v in manifest['images'] if v['tag'] == tag]
        require(len(recorded) == 1 and recorded[0]['config_id'] == objects['archive_config_digest']['digest'], 'package_component_identity_mismatch')
    require(profile.get('kind') == 'production' and profile.get('required_cases'), 'release_profile_required')
    missing = sorted(k for k in profile['required_cases'] if profile.get('results', {}).get(k, {}).get('status') != 'passed')
    blocked = list(evidence['blocked']) + missing + pool_blocked
    for key in ('python_source_set_verified', 'host_disk_source_verified'):
        if evidence[key].get('status') != 'passed':
            blocked.append(key)
    if evidence.get('worker_loaded_version') != 'verified_startup_attestation':
        blocked.append('worker_loaded_version')
    if evidence.get('resource_state') != 'fresh_complete_reconciliation':
        blocked.append('fresh_resource_state')
    if evidence.get('static_resources') != 'verified_build_inputs':
        blocked.append('complete_build_inputs')
    minimum = {'N3-E', 'N4', 'N5-load', 'N5-fault', 'historical-disposition'}
    if not minimum <= set(profile['required_cases']):
        blocked.append('required_profile_cases_missing')
    if not profile.get('approval_reference'):
        blocked.append('profile_not_approved')
    # Every required result needs immutable evidence bound to this package and tool.
    for case in profile['required_cases']:
        item = profile.get('results', {}).get(case, {})
        if item.get('status') == 'passed':
            require(item.get('source_commit') == manifest['source_commit'] and item.get('evidence_sha256') in sums.values(), 'required_result_unbound')
    return {'status': 'blocked' if blocked else 'pass', 'blocked': sorted(set(blocked)),
            'package_manifest_sha256': sums['release-manifest.json'], 'source_commit': manifest['source_commit'],
            'run_id': evidence['run_id'], 'evidence_sha256': sha(json.dumps(evidence, sort_keys=True).encode()),
            'checksums_verified': len(sums), 'production_approved': not blocked}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'evidence', 'profile', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    require(not a.output.resolve().is_relative_to(a.package.resolve()), 'check_output_must_be_outside_package')
    require(not a.output.exists(), 'output_exists')
    try:
        result = check(a.package, read_json(a.evidence), read_json(a.profile))
    except Exception as error:
        result = {'status': 'fail', 'failure_code': str(error) if isinstance(error, EvidenceError) else 'release_check_incomplete'}
    root = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    tool_inputs = {}
    for name in ('deploy/peixian/release-check.py', 'deploy/peixian/evidence_contract.py'):
        raw = regular(root/name).read_bytes()
        committed = subprocess.check_output(['git', 'show', commit+':'+name], cwd=root)
        tool_inputs[name] = {'raw_sha256': sha(raw), 'matches_commit': source_equal(name, raw, committed)}
    result.update(checker_source_commit=commit, checker_inputs=tool_inputs)
    write_new(a.output, result)
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'pass' else 2)
