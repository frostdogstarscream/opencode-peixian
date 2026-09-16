"""Read-only evidence for the fixed synthetic Windows N3 namespace."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'output_exists'
    module = importlib.util.spec_from_file_location('n3_config', ROOT / 'deploy/peixian/platform-config.py')
    settings = importlib.util.module_from_spec(module)
    sys.modules[module.name] = settings
    module.loader.exec_module(settings)
    cfg = settings.load_config(args.config)
    raw = json.loads(args.config.read_text())
    assert raw['deployment_id'] == 'synthetic-r2-local'
    assert raw['public_url'] == 'https://127.0.0.1:19444'
    def command(*values):
        return subprocess.check_output(values, cwd=ROOT, stderr=subprocess.PIPE)
    candidate = command('git', 'rev-parse', args.source_commit).decode().strip()
    container = json.loads(command('docker', 'inspect', 'synthetic-r2-local-console'))[0]
    assert container['State']['Health']['Status'] == 'healthy'
    image = json.loads(command('docker', 'image', 'inspect', container['Image']))[0]
    assert image['Config']['Labels']['org.opencontainers.image.revision'] == candidate
    collect = "import pathlib,json,hashlib; print(json.dumps({str(p.relative_to('/app')):hashlib.sha256(p.read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() for d in ('control','shared') for p in pathlib.Path('/app',d).rglob('*.py')}))"
    hashes = json.loads(command('docker', 'exec', 'synthetic-r2-local-console', 'python', '-c', collect))
    for name, digest in hashes.items():
        blob = command('git', 'show', candidate + ':services/peixian-control/' + name)
        assert hashlib.sha256(blob.replace(b'\r\n', b'\n')).hexdigest() == digest, name
    worker_files = {}
    for name in ('deploy/peixian/console-worker.py', 'services/peixian-control/shared/worker_errors.py'):
        local = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
        assert local == command('git', 'show', candidate + ':' + name).replace(b'\r\n', b'\n')
        worker_files[name] = hashlib.sha256(local).hexdigest()
    key = (cfg.secrets / 'console-worker.key').read_text().strip()
    with httpx.Client(base_url=cfg.control_url, trust_env=False, timeout=5) as api:
        # GET query is deliberately read-only; protocol validation runs before query.
        path = '/internal/worker/jobs/' + '0' * 32
        anonymous = api.get(path)
        mismatch = api.get(path, headers={'X-Worker-Key': key, 'X-Peixian-Protocol': '1'})
        assert anonymous.status_code == 403 and 'X-Peixian-Worker-Code' not in anonymous.headers
        assert mismatch.status_code == 409 and mismatch.headers.get('X-Peixian-Worker-Code') == 'worker_protocol_mismatch'
    receipts = []
    historical_unconfirmed = 0
    for path in (cfg.worker_root / 'receipts').rglob('*.json'):
        value = json.loads(path.read_text())
        # Older journals lack N3's phase/version fields. Preserve, count and
        # report their unresolved outcomes separately rather than claiming repair.
        if not {'phase', 'state_version', 'gate_epoch'} <= value.keys():
            historical_unconfirmed += value.get('status') != 'recorded'
            continue
        receipts.append({k: value[k] for k in ('job_id', 'attempt', 'operation_id', 'kind', 'status', 'phase', 'receipt_hit', 'failure_code') if k in value})
    assert receipts and all(r['status'] == 'recorded' for r in receipts), 'unconfirmed_n3_receipt'
    assert any(r['kind'] == 'complete' for r in receipts)
    report = {'status': 'passed', 'source_candidate': candidate, 'scope': 'windows_local_preliminary',
        'control_image': container['Image'], 'image_config_id': image['Id'],
        'control_shared_files': hashes, 'worker_source_sha256': worker_files,
        'protected_protocol_diagnostic': True, 'n3_receipts': receipts,
        'historical_unconfirmed_journals_not_resolved': historical_unconfirmed,
        'fault_injection': False, 'capacity_tested': False, 'paid_model_used': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({'status': 'passed', 'python_files_verified': len(hashes), 'recorded_receipts': len(receipts)}))


if __name__ == '__main__':
    main()
