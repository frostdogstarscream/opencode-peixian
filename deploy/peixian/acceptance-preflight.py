"""N4/N5 planning validation only. Does not execute Docker, restore, load or faults."""
import argparse
import json
from pathlib import Path
from evidence_contract import read_json, write_new


def preflight(value):
    missing = []
    def need(ok, code):
        if not ok:
            missing.append(code)
    need(value.get('kind') in ('N4', 'N5'), 'known_work_package')
    need(value.get('execution_enabled') is True, 'execution_not_authorized')
    need(bool(value.get('approval_reference')), 'approval_reference_missing')
    need(bool(value.get('run_id')), 'run_id_missing')
    if value.get('kind') == 'N4':
        source, target = value.get('source', {}), value.get('target', {})
        need(bool(source.get('engine_id')) and bool(target.get('engine_id')) and source.get('engine_id') != target.get('engine_id'), 'distinct_verified_engines_required')
        need(bool(source.get('deployment_id')) and bool(target.get('deployment_id')) and source.get('deployment_id') != target.get('deployment_id'), 'new_namespace_required')
        need(target.get('resources_empty') is True and target.get('data_root_empty') is True, 'target_not_verified_empty')
        for key in ('full_backup_verified', 'matching_key_verified', 'schema4_protocol2_verified', 'disk_budget_verified',
                    'source_writers_stopped', 'synthetic_egress_only', 'host_paths_isolated', 'allowed_operations_recorded'):
            need(value.get(key) is True, key)
        for key in ('backup_manifest_sha256', 'baseline_sha256', 'rpo_policy', 'rto_target'):
            need(bool(value.get(key)), key)
    if value.get('kind') == 'N5':
        for key in ('candidate', 'hardware', 'component_identities', 'quotas', 'dependencies', 'thresholds', 'stop_conditions'):
            need(bool(value.get(key)), key)
        for key in ('registered_accounts', 'viewers', 'upstreams', 'active_runtimes', 'generations', 'api_rps',
                    'lifecycle_rate', 'duration_seconds', 'sample_seconds'):
            x = value.get('load', {}).get(key)
            need(type(x) in (int, float) and x >= 0, 'load_' + key)
        need(value.get('budget_verified') is True, 'resource_budget_unverified')
        need(value.get('normal_and_fault_batches_separate') is True, 'separate_fault_batch_required')
    return {'status': 'blocked' if missing else 'prepared', 'missing': missing,
            'execution_performed': False, 'target_verified': False,
            'note': 'profile_validation_only_use_existing_tools_after_independent_environment_verification'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = preflight(read_json(a.profile))
    write_new(a.output, result)
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'prepared' else 2)
