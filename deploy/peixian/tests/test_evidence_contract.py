import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import evidence_contract as e


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def image(tmp_path, oci=True, corrupt=False):
    entries = {}
    def add(kind, data):
        raw = json.dumps(data).encode()
        digest = 'sha256:' + e.sha(raw)
        entries['blobs/sha256/' + digest[7:]] = raw
        return {'mediaType': kind, 'digest': digest, 'size': len(raw)}
    config = add('application/vnd.oci.image.config.v1+json', {'os': 'linux', 'architecture': 'amd64'})
    manifest = add('application/vnd.oci.image.manifest.v1+json', {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'config': config, 'layers': []})
    manifest['platform'] = {'os': 'linux', 'architecture': 'amd64'}
    index = add('application/vnd.oci.image.index.v1+json', {'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [manifest]})
    index['annotations'] = {'io.containerd.image.name': 'docker.io/library/test:1'}
    if oci:
        entries['index.json'] = json.dumps({'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [index]}).encode()
    entries['manifest.json'] = json.dumps([{'Config': 'blobs/sha256/' + config['digest'][7:], 'RepoTags': ['test:1']}]).encode()
    if corrupt:
        entries['blobs/sha256/' + manifest['digest'][7:]] = b'{}'
    path = tmp_path / ('image-' + str(oci) + str(corrupt) + '.tar')
    with tarfile.open(path, 'w') as tar:
        for name, raw in entries.items():
            item = tarfile.TarInfo(name); item.size = len(raw); tar.addfile(item, io.BytesIO(raw))
    return path, config, manifest, index


def test_raw_identity_descriptor_chain(tmp_path):
    path, config, manifest, index = image(tmp_path)
    found = e.archive_identity(path, 'test:1', {'os': 'linux', 'architecture': 'amd64'})
    assert found['archive_config_digest']['digest'] == config['digest']
    assert found['archive_manifest_digest']['digest'] == manifest['digest']
    assert found['archive_index_digest']['digest'] == index['digest']
    path, *_ = image(tmp_path, corrupt=True)
    with pytest.raises(e.EvidenceError, match='descriptor_digest_mismatch'):
        e.archive_identity(path, 'test:1', {'os': 'linux', 'architecture': 'amd64'})


def test_legacy_archive_without_index(tmp_path):
    path, *_ = image(tmp_path, oci=False)
    result = e.archive_identity(path, 'test:1', {'os': 'linux', 'architecture': 'amd64'})
    assert result['archive_index_digest']['status'] == 'not_applicable'
    assert result['archive_manifest_digest']['status'] == 'not_applicable'


@pytest.mark.parametrize('actual,field', [({}, 'missing'), ({'control/x.py': e.source_digest(b'a')}, 'unexpected'),
    ({'control/a.py': e.source_digest(b'b')}, 'changed')])
def test_bidirectional_set(actual, field):
    result = e.compare_sets({'control/a.py': e.source_digest(b'a')}, actual)
    assert result['status'] == 'failed' and result[field]


def test_equal_counts_not_equal_sets():
    result = e.compare_sets({'control/a.py': e.source_digest(b'a')}, {'control/b.py': e.source_digest(b'a')})
    assert result['missing'] and result['unexpected']


def test_four_receipt_groups_and_missing():
    def record(job, status='recorded'):
        return {'job_id': job, 'status': status}
    before = {'old': record('old', 'pending')}
    after = before | {'a': record('a'), 'b': record('b'), 'x': record('x')}
    result = e.classify_receipts(before, after, ['a'], ['b'])
    assert result['counts'] == dict(batch=1, historical=1, other_batch=1, unattributed=1)
    assert result['status'] == 'incomplete'
    assert e.classify_receipts(before, {}, [])['missing'] == ['old']
    assert before['old']['status'] == 'pending'


@pytest.mark.parametrize('status', ['recorded', 'rejected', 'unknown'])
def test_expected_negative_outcomes(status):
    assert e.check_outcome({'status': status}, status)


def test_exclusive_manifest_and_failed_run(tmp_path):
    path = tmp_path / 'run.json'
    run = e.Run.create(path, 'a'*40, 'b'*40, 'c'*40, ['busy_update'], {})
    run.own('job', 'busy_update', 'rejected')
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        e.Run.create(path, 'a'*40, 'b'*40, 'c'*40, ['busy_update'], {})
    assert path.read_bytes() == original
    run.finish('incomplete', 'acceptance_incomplete')
    assert e.read_json(path)['status'] == 'incomplete'


def test_unsafe_paths_and_read_failures(tmp_path):
    for name in ('../a', '/x', 'a\\b', 'C:/x', 'a/../b'):
        with pytest.raises(e.EvidenceError):
            e.safe_name(name)
    with pytest.raises(FileNotFoundError):
        e.read_json(tmp_path / 'absent')
    with pytest.raises(e.EvidenceError, match='journal_root_missing'):
        e.journal_snapshot(tmp_path / 'absent')


def test_changed_historical_record_not_silently_ignored():
    old = {'a': {'job_id': 'old', 'status': 'pending'}}
    new = {'a': {'job_id': 'old', 'status': 'recorded'}}
    assert e.classify_receipts(old, new, [])['counts']['unattributed'] == 1


def test_package_corruption_and_extra_file(tmp_path):
    check = module('release-check')
    (tmp_path / 'a').write_bytes(b'a')
    (tmp_path / 'SHA256SUMS').write_text(e.sha(b'a') + '  a\n')
    (tmp_path / 'a').write_bytes(b'bad')
    with pytest.raises(e.EvidenceError, match='checksum'):
        check.verify_package(tmp_path)


def test_unapproved_profiles_never_enable_execution():
    prep = module('acceptance-preflight')
    for kind in ('N4', 'N5'):
        result = prep.preflight({'kind': kind, 'execution_enabled': False})
        assert result['status'] == 'blocked' and not result['execution_performed']


def test_no_assert_in_new_safety_contracts():
    for name in ('evidence_contract.py', 'n3-local-evidence.py', 'release-check.py'):
        import ast
        assert not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse((ROOT / name).read_text())))


def public(tmp_path):
    path, *_ = image(tmp_path)
    platform = {'os': 'linux', 'architecture': 'amd64'}
    objects = e.archive_identity(path, 'test:1', platform)
    for name, kind in (('container_image_reference', 'docker_container_Image'), ('docker_image_inspect_id', 'docker_image_Id')):
        objects[name] = {'object_kind': kind, 'digest': objects['archive_index_digest']['digest'],
                         'algorithm': 'sha256', 'source': 'container_inspect' if name.startswith('container') else 'image_inspect', 'platform': platform}
    objects['image_revision_label'] = 'a'*40
    return dict(evidence_format=2, status='passed', run_id='a'*32, collected_at=e.utc(),
        correction_of='deploy/peixian/reports/n3-local-evidence.json', correction_reason='inspect_fields_are_not_archive_config_objects',
        runtime_source_commit='a'*40, tool_source_commit='b'*40, package_source_commit='c'*40,
        platform=platform, image=objects, python_source_set_verified={}, host_disk_source_verified={},
        worker_loaded_version='not_proven', build_input_subset={}, static_resources='not_verified',
        receipt_counts=dict(batch=0, historical=2, other_batch=0, unattributed=0), historical_unconfirmed=2,
        maintenance={}, resource_state='unverified', release_status='blocked', blocked=['N4', 'N5'], scope='read_only')


def test_config_manifest_swap_rejected_and_render_consistent(tmp_path):
    report = public(tmp_path)
    renderer = module('render-evidence-report')
    text = renderer.render(report)
    assert report['image']['archive_config_digest']['digest'] in text
    a, b = 'archive_config_digest', 'archive_manifest_digest'
    report['image'][a], report['image'][b] = report['image'][b], report['image'][a]
    with pytest.raises(e.EvidenceError, match='object_type'):
        renderer.render(report)


@pytest.mark.parametrize('where', ['root', 'image', 'nested', 'counts'])
def test_raw_secret_rejected(tmp_path, where):
    report = public(tmp_path)
    if where == 'root':
        report['raw_response'] = 'secret'
    elif where == 'image':
        report['image']['archive_config_digest']['environment'] = {'KEY': 'secret'}
    elif where == 'counts':
        report['receipt_counts']['batch'] = 'secret'
    else:
        report['host_disk_source_verified']['key'] = 'secret'
    with pytest.raises(e.EvidenceError):
        module('render-evidence-report').render(report)


def test_release_blocks_missing_required_tests(tmp_path, monkeypatch):
    report = public(tmp_path)
    check = module('release-check')
    obj = e.archive_identity(tmp_path/'image-TrueFalse.tar', 'test:1', report['platform'])
    manifest = {'source_commit': 'c'*40, 'requested_images': {'control': 'test:1'},
        'images': [{'tag': 'test:1', 'config_id': obj['archive_config_digest']['digest']}]}
    monkeypatch.setattr(check, 'verify_package', lambda _: (manifest, {'release-manifest.json': 'd'*64}))
    monkeypatch.setattr(check, 'archive_identity', lambda *a: obj)
    result = check.check(tmp_path, report, {'kind': 'production', 'required_cases': ['N4'], 'results': {}})
    assert result['status'] == 'blocked' and 'N4' in result['blocked']
    report['image']['archive_config_digest']['digest'] = 'sha256:'+'f'*64
    with pytest.raises(e.EvidenceError, match='archive_identity'):
        check.check(tmp_path, report, {'kind': 'production', 'required_cases': ['N4']})


def test_source_false_refused(tmp_path):
    (tmp_path/'release-manifest.json').write_text(json.dumps({'source_matches_commit':False}))
    (tmp_path/'SHA256SUMS').write_text(e.sha((tmp_path/'release-manifest.json').read_bytes())+'  release-manifest.json\n')
    with pytest.raises(e.EvidenceError, match='source_mismatch'):
        module('release-check').verify_package(tmp_path)
