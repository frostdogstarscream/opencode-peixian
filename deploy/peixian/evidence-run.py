"""Create a private batch before invoking an already-authorized acceptance tool."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
from evidence_contract import Run, journal_snapshot, require

ROOT = Path(__file__).resolve().parents[2]


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline', required=True)
    p.add_argument('--runtime-commit', required=True)
    p.add_argument('--tool-commit', required=True)
    p.add_argument('--case', action='append', required=True)
    a = p.parse_args()
    require(a.output.resolve().is_relative_to((ROOT / 'deploy/peixian/.runtime').resolve()), 'private_manifest_required')
    spec = importlib.util.spec_from_file_location('batch_cfg', Path(__file__).with_name('platform-config.py'))
    cfg = importlib.util.module_from_spec(spec); sys.modules[spec.name] = cfg; spec.loader.exec_module(cfg)
    c = cfg.load_config(a.config)
    require(c.deployment_id == 'synthetic-r2-local', 'isolated_namespace_required')
    def fixed(ref):
        require(not ref.startswith('-'), 'invalid_ref')
        return subprocess.check_output(['git', 'rev-parse', '--verify', ref + '^{commit}'], cwd=ROOT).decode().strip()
    r = Run.create(a.output, fixed(a.baseline), fixed(a.runtime_commit), fixed(a.tool_commit), a.case, journal_snapshot(c.worker_root / 'receipts'))
    r.value['journal_root'] = str(c.worker_root / 'receipts')
    r.save()
    print(r.value['run_id'])
