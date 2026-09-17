"""Preserve old journals; append a private disposition ledger and public summary."""
import argparse
import json
from pathlib import Path
from evidence_contract import journal_snapshot, require, utc, write_new


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--journal-root', type=Path, required=True)
    p.add_argument('--private-output', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    base = Path(__file__).resolve().parent
    require(a.journal_root.resolve() == (base/'.runtime/r2-local/data/worker/receipts').resolve(), 'isolated_journal_root_required')
    require(a.private_output.resolve().is_relative_to((base/'.runtime').resolve()), 'private_output_required')
    require(not a.private_output.exists() and not a.output.exists(), 'output_exists')
    before = journal_snapshot(a.journal_root)
    selected = [v for v in before.values() if v['status'] != 'recorded']
    private, public = [], []
    for index, value in enumerate(selected):
        common = {'reference': 'H' + str(index+1).zfill(2), 'journal_sha256': value['sha256'],
                  'original_status': value['status'], 'classification': 'historical_unconfirmed',
                  'server_receipt': 'not_collected_local_journals_only', 'current_runtime': 'not_verified',
                  'recovery_responsibility': 'not_verified', 'root_cause': 'undetermined',
                  'original_success': 'not_proven', 'owner_decision': 'required'}
        private.append({**common, **value})
        public.append(common)
    require(before == journal_snapshot(a.journal_root), 'journals_changed_during_collection')
    write_new(a.private_output, {'collected_at': utc(), 'records': private})
    write_new(a.output, {'status': 'blocked', 'collection': 'local_journals_only', 'records': public,
                        'journals_modified': False, 'production_approved': False})
    print(json.dumps({'status': 'blocked', 'historical_unconfirmed': len(public), 'journals_modified': False}))
