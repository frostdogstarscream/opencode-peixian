"""Tool-only evidence contracts. No runtime mutation or database migration."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import uuid
from datetime import datetime, timezone


class EvidenceError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise EvidenceError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def safe_name(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'unsafe_relative_path')
    p = PurePosixPath(name)
    require(not p.is_absolute() and all(x not in ('', '.', '..') for x in name.split('/')), 'unsafe_relative_path')
    return name


def regular(path):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'link_forbidden')
    require(stat.S_ISREG(path.stat().st_mode), 'regular_file_required')
    return path


def read_json(path):
    return json.loads(regular(path).read_text(encoding='utf-8'))


def write_new(path, value):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'link_forbidden')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')


def replace_owned(path, value, run_id):
    require(read_json(path)['run_id'] == run_id, 'run_identity_conflict')
    tmp = Path(path).with_name(Path(path).name + '.' + uuid.uuid4().hex + '.tmp')
    write_new(tmp, value)
    os.replace(tmp, path)


def source_digest(raw):
    return {'raw_sha256': sha(raw), 'lf_sha256': sha(raw.replace(b'\r\n', b'\n'))}


def compare_sets(expected, actual):
    for name in (*expected, *actual):
        safe_name(name)
    missing, unexpected = sorted(expected.keys() - actual.keys()), sorted(actual.keys() - expected.keys())
    changed = sorted(k for k in expected.keys() & actual.keys() if expected[k]['lf_sha256'] != actual[k]['lf_sha256'])
    return {'status': 'passed' if not (missing or unexpected or changed) else 'failed',
            'missing': missing, 'unexpected': unexpected, 'changed': changed,
            'comparison': 'python_source_lf_equivalence_only', 'expected': expected, 'actual': actual}


def archive_identity(path, tag, platform):
    """Verify actual raw config/manifest/index descriptor relationships without extraction."""
    with tarfile.open(regular(path), 'r:*') as archive:
        members = {}
        for item in archive.getmembers():
            name = item.name.rstrip('/')
            safe_name(name)
            require(name not in members, 'duplicate_archive_member')
            require(item.isfile() or item.isdir(), 'archive_link_or_special_file')
            members[name] = item
        def raw(name):
            safe_name(name)
            require(name in members and members[name].isfile() and members[name].size <= 8 * 1024 * 1024,
                    'archive_object_missing_or_large')
            return archive.extractfile(members[name]).read()
        def descriptor(d):
            require(re.fullmatch('sha256:[0-9a-f]{64}', d.get('digest', '')) is not None, 'invalid_descriptor')
            value = raw('blobs/sha256/' + d['digest'][7:])
            require(len(value) == d['size'] and 'sha256:' + sha(value) == d['digest'], 'descriptor_digest_mismatch')
            obj = json.loads(value)
            require(obj.get('mediaType') == d['mediaType'], 'descriptor_type_mismatch')
            return obj, value
        def identity(kind, value, source, media=None):
            return {'object_kind': kind, 'digest': 'sha256:' + sha(value), 'algorithm': 'sha256',
                    'source': source, 'media_type': media, 'platform': platform}
        manifest = json.loads(raw('manifest.json'))
        found = [v for v in manifest if tag in (v.get('RepoTags') or [])]
        require(len(found) == 1, 'archive_tag_ambiguous')
        config_raw = raw(found[0]['Config'])
        config = json.loads(config_raw)
        require(all(config.get(k, '') == platform.get(k, '') for k in ('os', 'architecture', 'variant')), 'platform_mismatch')
        result = {'archive_config_digest': identity('image_config', config_raw, 'docker_save_config'),
                  'archive_manifest_digest': {'status': 'not_applicable', 'reason': 'docker_save_without_oci_manifest'},
                  'archive_index_digest': {'status': 'not_applicable', 'reason': 'docker_save_without_oci_index'}}
        if 'index.json' not in members:
            return result
        top_raw = raw('index.json')
        top = json.loads(top_raw)
        selected = [v for v in top.get('manifests', []) if (v.get('annotations') or {}).get('io.containerd.image.name', '').removeprefix('docker.io/library/') == tag]
        require(len(selected) == 1, 'archive_index_tag_ambiguous')
        obj, value = descriptor(selected[0])
        result['archive_catalog_digest'] = identity('archive_catalog_index', top_raw, 'index.json', top.get('mediaType'))
        if 'manifests' in obj:
            result['archive_index_digest'] = identity('image_index', value, 'selected_tag_descriptor', obj['mediaType'])
            children = [v for v in obj['manifests'] if all((v.get('platform') or {}).get(k, '') == platform.get(k, '') for k in ('os', 'architecture', 'variant'))]
            require(len(children) == 1, 'platform_manifest_ambiguous')
            obj, value = descriptor(children[0])
        require('config' in obj and 'layers' in obj, 'image_manifest_required')
        result['archive_manifest_digest'] = identity('image_manifest', value, 'platform_manifest_descriptor', obj['mediaType'])
        cfg = obj['config']
        require(cfg.get('mediaType') in ('application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json'), 'config_type_mismatch')
        require(cfg['digest'] == result['archive_config_digest']['digest'] and cfg['size'] == len(config_raw), 'manifest_config_mismatch')
        require(raw('blobs/sha256/' + cfg['digest'][7:]) == config_raw, 'manifest_config_bytes_mismatch')
        return result


def journal_snapshot(root):
    require(Path(root).is_dir(), 'journal_root_missing')
    result = {}
    for p in Path(root).rglob('*'):
        require(not p.is_symlink(), 'journal_link_forbidden')
        if p.is_dir():
            continue
        require(p.suffix == '.json', 'unexpected_journal_file')
        value = read_json(p)
        keys = ('job_id', 'attempt', 'operation_id')
        require(all(k in value for k in keys), 'journal_identity_incomplete')
        require(type(value['attempt']) is int and value['attempt'] > 0, 'invalid_attempt')
        for k in ('job_id', 'operation_id'):
            require(re.fullmatch('[A-Za-z0-9_-]{1,100}', value[k]) is not None, 'invalid_identity')
        key = '/'.join(str(value[k]) for k in keys)
        require(p.relative_to(root).as_posix() == key + '.json' and key not in result, 'journal_path_identity_conflict')
        require(value.get('status') in ('recorded', 'pending', 'retry_pending', 'unknown', 'rejected'), 'invalid_journal_status')
        result[key] = {**{k: value[k] for k in keys}, 'status': value['status'], 'sha256': sha(regular(p).read_bytes())}
    return result


def classify_receipts(before, after, owned_jobs, other_operations=()):
    groups = {k: [] for k in ('batch', 'historical', 'other_batch', 'unattributed')}
    for key, record in after.items():
        group = 'batch' if record['job_id'] in owned_jobs else 'other_batch' if key in other_operations else 'historical' if key in before and record == before[key] else 'unattributed'
        groups[group].append(record)
    missing = sorted(before.keys() - after.keys())
    return {'groups': groups, 'counts': {k: len(v) for k, v in groups.items()}, 'missing': missing,
            'status': 'incomplete' if missing or groups['unattributed'] else 'passed'}


def check_outcome(record, expected):
    allowed = {'recorded', 'rejected', 'unknown'}
    require(expected in allowed and record.get('status') in allowed, 'outcome_not_terminal')
    return record['status'] == expected


class Run:
    """Private manifest; explicit jobs are authoritative, timestamps never assign ownership."""
    def __init__(self, path):
        self.path = Path(path)
        self.value = read_json(path)
        require(self.value.get('evidence_format') == 1 and self.value.get('status') == 'running', 'run_not_running')

    @classmethod
    def create(cls, path, baseline, runtime, tool, cases, snapshot):
        for value in (baseline, runtime, tool):
            require(re.fullmatch('[0-9a-f]{40}', value or '') is not None, 'fixed_commit_required')
        require(cases and len(set(cases)) == len(cases), 'expected_cases_required')
        write_new(path, {'evidence_format': 1, 'run_id': uuid.uuid4().hex, 'status': 'running',
                        'repository_baseline': baseline, 'runtime_source_commit': runtime, 'tool_source_commit': tool,
                        'deployment_id': 'synthetic-r2-local', 'started_at': utc(), 'finished_at': None,
                        'expected_cases': cases, 'owned_jobs': [], 'owned_operations': [], 'evidence_files': [],
                        'journal_before': snapshot})
        return cls(path)

    def save(self):
        replace_owned(self.path, self.value, self.value['run_id'])

    def own(self, jid, case, expected='recorded'):
        require(case in self.value['expected_cases'], 'undeclared_case')
        require(re.fullmatch('[A-Za-z0-9_-]{1,100}', jid or '') is not None, 'invalid_job_id')
        require(expected in ('recorded', 'rejected', 'unknown'), 'invalid_expected_outcome')
        self.value['owned_jobs'].append({'job_id': jid, 'case': case, 'expected': expected})
        self.save()


    def finish(self, status, code=None):
        require(status in ('passed', 'failed', 'incomplete', 'blocked'), 'invalid_result')
        self.value.update(status=status, finished_at=utc(), failure_code=code)
        self.save()


def validate_public(report):
    allowed = {'evidence_format', 'status', 'run_id', 'collected_at', 'correction_of', 'correction_reason',
        'runtime_source_commit', 'tool_source_commit', 'package_source_commit', 'platform', 'image',
        'python_source_set_verified', 'host_disk_source_verified', 'worker_loaded_version',
        'build_input_subset', 'static_resources', 'receipt_counts', 'historical_unconfirmed',
        'maintenance', 'resource_state', 'release_status', 'blocked', 'scope'}
    require(set(report) == allowed and report['evidence_format'] == 2 and report['status'] == 'passed', 'public_schema_invalid')
    require(report['correction_of'] == 'deploy/peixian/reports/n3-local-evidence.json', 'invalid_correction_reference')
    require(re.fullmatch('[0-9a-f]{32}', report['run_id']) is not None, 'invalid_run_id')
    require(set(report['platform']) <= {'os', 'architecture', 'variant'} and report['platform'].get('os') == 'linux'
            and report['platform'].get('architecture') == 'amd64', 'unsupported_platform')
    require(set(report['receipt_counts']) == {'batch', 'historical', 'other_batch', 'unattributed'}
            and all(type(v) is int and v >= 0 for v in report['receipt_counts'].values()), 'invalid_public_counts')
    require(type(report['historical_unconfirmed']) is int and report['historical_unconfirmed'] >= 0, 'invalid_public_counts')
    for key in ('runtime_source_commit', 'tool_source_commit', 'package_source_commit'):
        require(re.fullmatch('[0-9a-f]{40}', report[key]) is not None, 'public_commit_invalid')
    allowed_images = {'container_image_reference': 'docker_container_Image', 'docker_image_inspect_id': 'docker_image_Id',
        'archive_config_digest': 'image_config', 'archive_manifest_digest': 'image_manifest',
        'archive_index_digest': 'image_index', 'archive_catalog_digest': 'archive_catalog_index'}
    require(set(report['image']) <= set(allowed_images) | {'image_revision_label'}, 'public_image_extra_fields')
    require(set(allowed_images) - {'archive_catalog_digest'} <= report['image'].keys(), 'image_identity_incomplete')
    for name, obj in report['image'].items():
        if name == 'image_revision_label':
            require(obj is None or re.fullmatch('[0-9a-f]{40}', obj) is not None, 'invalid_revision_label')
            continue
        if obj.get('status') == 'not_applicable':
            require(name in ('archive_index_digest', 'archive_manifest_digest') and set(obj) == {'status', 'reason'}, 'invalid_not_applicable')
            require(obj['reason'] in ('docker_save_without_oci_manifest', 'docker_save_without_oci_index'), 'invalid_reason')
            continue
        require(set(obj) <= {'object_kind', 'digest', 'algorithm', 'source', 'media_type', 'platform'}, 'public_image_extra_fields')
        require(obj.get('object_kind') == allowed_images[name], 'image_object_type_conflict')
        require(re.fullmatch('sha256:[0-9a-f]{64}', obj.get('digest', '')) is not None, 'invalid_digest')
        require(obj.get('algorithm') == 'sha256' and obj.get('platform') == report['platform'], 'identity_platform_conflict')
        require(obj.get('source') in ('container_inspect', 'image_inspect', 'docker_save_config', 'index.json',
                                    'selected_tag_descriptor', 'platform_manifest_descriptor'), 'invalid_source')
    # Reject undeclared nested fields, including secret/raw-response injection.
    nested = {'raw_sha256', 'lf_sha256', 'status', 'missing', 'unexpected', 'changed', 'comparison',
              'expected', 'actual', 'candidate', 'package_source', 'maintenance_mode', 'capacity_healthy',
              'recovery_required', 'security_pending', 'batch', 'historical', 'other_batch', 'unattributed'}
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                require(key in nested or (key.startswith(('control/', 'shared/', 'deploy/peixian/', 'services/peixian-control/', 'packages/peixian-console/')) or key == 'bun.lock'), 'public_nested_field_forbidden')
                if '/' in key:
                    safe_name(key)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for key in ('python_source_set_verified', 'host_disk_source_verified', 'build_input_subset', 'maintenance', 'receipt_counts'):
        visit(report[key])


async def tracked_run(function, args, case):
    """Optional adapter: record failure even before a legacy tool's inner try block."""
    path = getattr(args, 'run_manifest', None)
    if path is None:
        return await function(args)
    root = Path(__file__).resolve().parent / '.runtime'
    require(Path(path).resolve().is_relative_to(root.resolve()), 'private_manifest_required')
    run = Run(path)
    require(run.value['expected_cases'] == [case], 'tool_cases_do_not_match_manifest')
    require(Path(run.value['journal_root']).resolve().is_relative_to(root.resolve()), 'private_journal_required')
    result = 'failed'
    code = None
    try:
        status = await function(args)
        run = Run(path)  # The tool may have added owned jobs.
        groups = classify_receipts(run.value['journal_before'], journal_snapshot(run.value['journal_root']),
                                   [v['job_id'] for v in run.value['owned_jobs']])
        run.value['receipt_classification'] = groups
        run.value['owned_operations'] = groups['groups']['batch']
        result = 'passed' if status == 0 and groups['status'] == 'passed' else 'incomplete'
        run.value['completed_cases'] = [case] if status == 0 else []
        for owned in run.value['owned_jobs']:
            records = [r for r in groups['groups']['batch'] if r['job_id'] == owned['job_id']]
            if not records or not all(check_outcome(r, owned['expected']) for r in records):
                result = 'incomplete'
        run.value['evidence_files'] = [{'sha256': sha(regular(args.output).read_bytes()), 'kind': 'acceptance_result'}]
        return 0 if result == 'passed' else 1
    except Exception:
        code = 'acceptance_incomplete'
        return 1
    finally:
        run.finish(result, code)
