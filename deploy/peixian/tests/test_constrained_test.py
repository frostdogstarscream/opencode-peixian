"""Synthetic regular-file cgroups only; never touch Docker or host cgroups."""
import copy
import contextlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from test_platform_delivery import load
from test_console_runtime import runtime, spec


harness = load('constrained-test')
capacity = load('platform-capacity')
manager = load('platform-manage')


class ConstrainedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.cgroups = self.base / 'synthetic-cgroups'
        for controller in ('cpu,cpuacct', 'memory', 'cpuset', 'pids'):
            directory = self.cgroups / controller
            directory.mkdir(parents=True)
            (directory / 'production-group').mkdir()
            (directory / 'production-group/sentinel').write_text('preserve', encoding='utf-8')
        (self.cgroups / 'cpuset/cpuset.cpus').write_text('0-31', encoding='utf-8')
        (self.cgroups / 'cpuset/cpuset.mems').write_text('0-1', encoding='utf-8')
        self.cfg = SimpleNamespace(deployment_id='loadtest-synthetic', version=2,
                                   capacity_policy={'host_memory_reserve_mib': 4096})
        self.boundary = harness.Boundary(self.cfg, self.cgroups)

    def snapshot(self):
        return {str(path.relative_to(self.cgroups)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.cgroups.rglob('*') if path.is_file()}

    def test_new_parent_sets_exact_cpu_cpuset_memory_and_pids_limits(self):
        existing = self.snapshot()
        self.boundary.initialize()
        cpu = self.boundary.paths['cpu,cpuacct']
        memory = self.boundary.paths['memory']
        cpuset = self.boundary.paths['cpuset']
        period = int((cpu / 'cpu.cfs_period_us').read_text())
        quota = int((cpu / 'cpu.cfs_quota_us').read_text())
        self.assertEqual(quota / period, 16)
        self.assertEqual(harness.expand_cpus((cpuset / 'cpuset.cpus').read_text()), list(range(16, 32)))
        self.assertEqual((cpuset / 'cpuset.mems').read_text(), '0-1')
        for name in ('memory.limit_in_bytes', 'memory.memsw.limit_in_bytes'):
            self.assertEqual(int((memory / name).read_text()), 28 * harness.GIB)
        self.assertEqual((memory / 'memory.use_hierarchy').read_text(), '1')
        self.assertEqual((self.boundary.paths['pids'] / 'pids.max').read_text(), '16384')
        after = self.snapshot()
        self.assertTrue(all(after[path] == value for path, value in existing.items()))
        self.assertTrue(all(self.cfg.deployment_id in path for path in set(after) - set(existing)))

    def test_existing_exact_group_is_read_only_and_accepts_kernel_cpu_range_format(self):
        self.boundary.initialize()
        (self.boundary.paths['cpuset'] / 'cpuset.cpus').write_text('16-31', encoding='utf-8')
        before = self.snapshot()
        self.boundary.initialize()
        self.boundary.verify()
        self.assertEqual(self.snapshot(), before)

    def test_existing_changed_limit_is_rejected_without_overwrite(self):
        self.boundary.initialize()
        (self.boundary.paths['memory'] / 'memory.limit_in_bytes').write_text(str(64 * harness.GIB))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'test_parent_limit_changed'):
            self.boundary.initialize()
        self.assertEqual(self.snapshot(), before)

    def test_partial_parent_is_not_repaired_or_overwritten(self):
        self.boundary.paths['memory'].mkdir()
        sentinel = self.boundary.paths['memory'] / 'memory.limit_in_bytes'
        sentinel.write_text('123', encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises((OSError, ValueError)):
            self.boundary.initialize()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.boundary.paths['cpu,cpuacct'].exists())

    def test_insufficient_host_cpus_fails_before_creating_any_parent(self):
        (self.cgroups / 'cpuset/cpuset.cpus').write_text('0-14', encoding='utf-8')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'host_has_fewer_than_sixteen_cpus'):
            self.boundary.initialize()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(path.exists() for path in self.boundary.paths.values()))

    def test_production_and_path_like_deployment_names_are_rejected(self):
        for name in ('platform', 'production', '../loadtest-a', 'loadtest-../../memory',
                     'loadtest-/other', 'loadtest-', 'loadtest-' + 'a' * 31):
            with self.subTest(name=name), self.assertRaises(ValueError):
                harness.Boundary(SimpleNamespace(**{**vars(self.cfg), 'deployment_id': name}), self.cgroups)

    def test_old_config_or_less_than_four_gib_accounting_reserve_is_rejected(self):
        for version, reserve in ((1, 4096), (2, 1024), (2, 4095)):
            cfg = SimpleNamespace(deployment_id=self.cfg.deployment_id, version=version,
                                  capacity_policy={'host_memory_reserve_mib': reserve})
            with self.subTest(version=version, reserve=reserve), self.assertRaisesRegex(
                    ValueError, 'test_requires_v2_and_four_gib_reserve'):
                harness.Boundary(cfg, self.cgroups)

    def test_symlink_controller_parent_or_counter_is_rejected_before_join(self):
        # Exercise the guard without requiring Windows symlink privileges. All
        # I/O still uses the synthetic regular-file tree; only link detection is
        # substituted, so a missing guard would actually write cgroup.procs.
        self.boundary.initialize()
        path = self.boundary.paths['memory']
        (path / 'cgroup.procs').write_text('existing-worker', encoding='utf-8')
        for linked in (path.parent, path, path / 'cgroup.procs'):
            before = self.snapshot()
            with self.subTest(linked=linked.name), patch.object(
                    Path, 'is_symlink', lambda value: value == linked):
                for operation in (self.boundary.initialize, self.boundary.verify, self.boundary.join):
                    with self.assertRaisesRegex(ValueError, 'test_cgroup_.*_is_link'):
                        operation()
            self.assertEqual(self.snapshot(), before)

    def test_capacity_uses_16_cpu_32_gib_despite_larger_host(self):
        self.boundary.initialize()
        module = SimpleNamespace(evaluate=capacity.evaluate)
        self.boundary.capacity(module)
        host = {'NCPU': 32, 'MemTotal': 251 * harness.GIB, 'SwapTotal': 1024 * harness.GIB}
        result = module.evaluate(host, {'cpu_required': 16, 'memory_required_mib': 32768})
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['docker_cpus'], 16)
        self.assertEqual(result['docker_memory_bytes'], 32 * harness.GIB)
        self.assertEqual(result['application_memory_ceiling_bytes'], 28 * harness.GIB)
        self.assertEqual(result['host_accounting_reserve_bytes'], 4 * harness.GIB)
        self.assertEqual(host['NCPU'], 32)
        self.assertEqual(host['MemTotal'], 251 * harness.GIB)
        for required in ({'cpu_required': 16.01, 'memory_required_mib': 32768},
                         {'cpu_required': 16, 'memory_required_mib': 32769}):
            with self.subTest(required=required):
                self.assertEqual(module.evaluate(host, required)['status'], 'insufficient')

    def test_capacity_never_inflates_smaller_host_and_reverifies_limits(self):
        self.boundary.initialize()
        module = SimpleNamespace(evaluate=capacity.evaluate)
        self.boundary.capacity(module)
        result = module.evaluate({'NCPU': 8, 'MemTotal': 16 * harness.GIB},
                                 {'cpu_required': 9, 'memory_required_mib': 17000})
        self.assertEqual(result['status'], 'insufficient')
        self.assertEqual(result['docker_cpus'], 8)
        self.assertEqual(result['docker_memory_bytes'], 16 * harness.GIB)
        (self.boundary.paths['cpu,cpuacct'] / 'cpu.cfs_quota_us').write_text('3200000')
        with self.assertRaisesRegex(ValueError, 'test_parent_limit_changed'):
            module.evaluate({'NCPU': 32, 'MemTotal': 251 * harness.GIB},
                            {'cpu_required': 1, 'memory_required_mib': 1})

    def test_original_fifty_account_profile_cannot_borrow_host_memory(self):
        self.boundary.initialize()
        config_file = self.base / 'platform.json'
        config_file.write_text(json.dumps({
            'version': 2, 'profile': 'single-host-50-io', 'deployment_id': self.cfg.deployment_id,
            'max_runtimes': 50, 'capacity_policy': {'cpu_mode': 'shared', 'cpu_overcommit_factor': 4},
            'public_url': 'https://synthetic.invalid:18443',
            'tls': {'certificate': './certificate.pem', 'private_key': './private-key.pem'},
        }), encoding='utf-8')
        cfg = manager.config.load_config(config_file)
        module = SimpleNamespace(evaluate=capacity.evaluate)
        self.boundary.capacity(module)
        result = module.evaluate({'NCPU': 32, 'MemTotal': 251 * harness.GIB}, cfg.resource_budget)
        self.assertEqual(result['status'], 'insufficient')
        self.assertIn('docker_memory_below_configured_runtime_budget', result['failures'])
        self.assertEqual(result['memory_required_mib'], 140544)

    def test_same_parent_injected_into_all_actual_account_services(self):
        payload = runtime.compose_spec(spec(), self.base / 'release', agent_image='agent:test',
                                       gateway_image='gateway:test', deployment_id=self.cfg.deployment_id)
        before = copy.deepcopy(payload)
        self.boundary.initialize()
        self.boundary.compose(payload)
        self.assertEqual(set(payload['services']), {'agent', 'gateway', 'model-relay'})
        for service in payload['services'].values():
            self.assertEqual(service.pop('cgroup_parent'), '/' + self.cfg.deployment_id)
        self.assertEqual(payload, before)

    def test_control_and_https_receive_same_parent(self):
        config_file = self.base / 'platform.json'
        config_file.write_text(json.dumps({
            'version': 2, 'profile': 'single-host-50-io', 'deployment_id': self.cfg.deployment_id,
            'public_url': 'https://synthetic.invalid:18443',
            'tls': {'certificate': './certificate.pem', 'private_key': './private-key.pem'},
        }), encoding='utf-8')
        payload = manager.compose_config(manager.config.load_config(config_file))
        self.boundary.initialize()
        self.boundary.compose(payload)
        self.assertEqual(set(payload['services']), {'console', 'https'})
        self.assertTrue(all(value['cgroup_parent'] == '/' + self.cfg.deployment_id
                            for value in payload['services'].values()))

    def test_foreign_or_unlabelled_compose_rejected_atomically(self):
        for labels in ({}, {'peixian.deployment': 'production'}):
            payload = {'services': {'agent': {'labels': {'peixian.deployment': self.cfg.deployment_id}},
                                    'gateway': {'labels': labels}}}
            before = copy.deepcopy(payload)
            with self.subTest(labels=labels), self.assertRaisesRegex(ValueError, 'compose_deployment_mismatch'):
                self.boundary.compose(payload)
            self.assertEqual(payload, before)
        with self.assertRaisesRegex(ValueError, 'compose_deployment_mismatch'):
            self.boundary.compose({'services': {}})

    def test_worker_join_only_writes_current_pid_to_owned_parent_groups(self):
        self.boundary.initialize()
        before = self.snapshot()
        with patch.object(harness.os, 'getpid', return_value=123456):
            self.boundary.join()
        after = self.snapshot()
        self.assertTrue(all(after[path] == value for path, value in before.items()))
        added = set(after) - set(before)
        self.assertEqual(len(added), 4)
        for path in added:
            self.assertIn(self.cfg.deployment_id, path)
            self.assertTrue(path.endswith('cgroup.procs'))
            self.assertEqual(after[path][0], b'123456')

    def test_worker_join_does_not_move_process_after_limit_drift(self):
        self.boundary.initialize()
        (self.boundary.paths['pids'] / 'pids.max').write_text('32768')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'test_parent_limit_changed'):
            self.boundary.join()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any((path / 'cgroup.procs').exists() for path in self.boundary.paths.values()))

    def test_report_is_read_only_and_keeps_failure_count_separate_from_oom(self):
        self.boundary.initialize()
        values = {
            'memory': {'memory.usage_in_bytes': '1', 'memory.max_usage_in_bytes': '2', 'memory.failcnt': '7',
                       'memory.oom_control': 'oom_kill_disable 0\nunder_oom 0\noom_kill 0\n'},
            'cpu,cpuacct': {'cpu.stat': 'nr_periods 1\nnr_throttled 0\nthrottled_time 0\n',
                           'cpuacct.usage': '123456'}, 'pids': {'pids.current': '3'},
        }
        for controller, fields in values.items():
            for name, value in fields.items():
                (self.boundary.paths[controller] / name).write_text(value, encoding='utf-8')
        before = self.snapshot()
        result = self.boundary.report()
        self.assertEqual(result['cgroup_version'], 1)
        self.assertEqual(result['accounting_total_memory_bytes'], 32 * harness.GIB)
        self.assertEqual(result['application_memory_limit_bytes'], 28 * harness.GIB)
        self.assertEqual(result['counters']['memory.failcnt'], '7')
        self.assertIn('oom_kill 0', result['counters']['memory.oom_control'])
        self.assertNotIn(str(self.base), json.dumps(result))
        self.assertEqual(self.snapshot(), before)

    def audit(self, records=None, groups=None, *, identifiers='synthetic-one\nsynthetic-two\n'):
        if records is None:
            records = [{'HostConfig': {'CgroupParent': '/' + self.cfg.deployment_id},
                        'State': {'Pid': pid, 'Running': True},
                        'Config': {'Labels': {'peixian.deployment': self.cfg.deployment_id}}}
                       for pid in (501, 502)]
        lines = {key: '/' + self.cfg.deployment_id + '/synthetic-container'
                 for key in ('memory', 'cpu', 'cpuacct', 'cpuset', 'pids')}
        lines.update(groups or {})
        text = '\n'.join(str(index) + ':' + controller + ':' + path
                         for index, (controller, path) in enumerate(lines.items(), 1) if path is not None) + '\n'
        expected_proc = {Path('/proc') / str(record['State']['Pid']) / 'cgroup' for record in records}
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            self.assertEqual(kwargs['timeout'], 30)
            self.assertEqual(kwargs['stderr'], subprocess.PIPE)
            if args == ['docker', 'ps', '-q', '--filter', 'label=peixian.deployment=' + self.cfg.deployment_id]:
                return identifiers
            if args == ['docker', 'inspect', *identifiers.split()]:
                return json.dumps(records)
            raise AssertionError('unexpected command in audit')
        def read(path, *args, **kwargs):
            if path not in expected_proc:
                raise AssertionError('unexpected filesystem access in audit')
            return text
        with patch.object(harness.subprocess, 'check_output', side_effect=command), patch.object(Path, 'read_text', read):
            result = self.boundary.audit_containers()
        self.assertEqual(len(calls), 2)
        return result

    def test_audit_verifies_all_actual_controller_paths_and_only_returns_counts(self):
        result = self.audit()
        self.assertEqual(result, {'running_containers': 2, 'all_controller_paths_verified': True})
        self.assertNotIn('501', json.dumps(result))
        self.assertNotIn('synthetic-container', json.dumps(result))
        self.assertNotIn(self.cfg.deployment_id, json.dumps(result))

    def test_audit_catches_each_controller_resolved_below_containerd_service(self):
        for controller in ('memory', 'cpu', 'cpuacct', 'cpuset', 'pids'):
            with self.subTest(controller=controller), self.assertRaisesRegex(
                    ValueError, 'container_escaped_effective_test_boundary'):
                self.audit(groups={controller: '/system.slice/containerd.service/'
                                   + self.cfg.deployment_id + '/synthetic-container'})

    def test_audit_rejects_similar_prefix_and_host_root_membership(self):
        for path in ('/', '/' + self.cfg.deployment_id + '-other/container',
                     '/' + self.cfg.deployment_id, '/production/container'):
            with self.subTest(path=path), self.assertRaisesRegex(
                    ValueError, 'container_escaped_effective_test_boundary'):
                self.audit(groups={'memory': path})

    def test_audit_rejects_missing_controller(self):
        for controller in ('memory', 'cpu', 'cpuacct', 'cpuset', 'pids'):
            with self.subTest(controller=controller), self.assertRaisesRegex(
                    ValueError, 'container_escaped_effective_test_boundary'):
                self.audit(groups={controller: None})

    def test_audit_rejects_relative_or_foreign_declared_parent_before_proc_access(self):
        for parent in (self.cfg.deployment_id, '/production', ''):
            records = [{'HostConfig': {'CgroupParent': parent}, 'State': {'Pid': 501, 'Running': True},
                        'Config': {'Labels': {'peixian.deployment': self.cfg.deployment_id}}}]
            with self.subTest(parent=parent), self.assertRaisesRegex(
                    ValueError, 'container_parent_not_absolute_test_group'):
                self.audit(records=records, identifiers='synthetic-one\n')

    def test_audit_rejects_no_running_containers(self):
        with patch.object(harness.subprocess, 'check_output', return_value='') as command:
            with self.assertRaisesRegex(ValueError, 'no_running_test_containers'):
                self.boundary.audit_containers()
        self.assertEqual(command.call_count, 1)

    def test_audit_does_not_mark_vanished_process_as_verified(self):
        records = [{'HostConfig': {'CgroupParent': '/' + self.cfg.deployment_id},
                    'State': {'Pid': 501, 'Running': True},
                    'Config': {'Labels': {'peixian.deployment': self.cfg.deployment_id}}}]
        with patch.object(harness.subprocess, 'check_output', side_effect=['synthetic-one\n', json.dumps(records)]), \
                patch.object(Path, 'read_text', side_effect=FileNotFoundError('synthetic proc disappeared')):
            with self.assertRaises((OSError, ValueError)):
                self.boundary.audit_containers()

    def test_audit_rejects_changed_inventory_or_foreign_label(self):
        with self.assertRaisesRegex(ValueError, 'test_container_inventory_changed'):
            self.audit(records=[])
        record = {'HostConfig': {'CgroupParent': '/' + self.cfg.deployment_id},
                  'State': {'Pid': 501, 'Running': True},
                  'Config': {'Labels': {'peixian.deployment': 'production'}}}
        with self.assertRaisesRegex(ValueError, 'container_deployment_changed_during_audit'):
            self.audit(records=[record], identifiers='synthetic-one\n')

    def test_audit_rejects_stopped_or_invalid_pid_before_reading_proc(self):
        for running, pid in ((False, 501), (True, 0), (True, -1), (True, True), (True, '501'), (1, 501)):
            record = {'HostConfig': {'CgroupParent': '/' + self.cfg.deployment_id},
                      'State': {'Pid': pid, 'Running': running},
                      'Config': {'Labels': {'peixian.deployment': self.cfg.deployment_id}}}
            with self.subTest(running=running, pid=pid), self.assertRaisesRegex(
                    ValueError, 'container_stopped_during_audit'):
                self.audit(records=[record], identifiers='synthetic-one\n')

    def test_audit_bounds_inventory_and_sanitizes_docker_failures(self):
        for output in ('same\nsame\n', '\n'.join(str(index) for index in range(209))):
            with self.subTest(kind='inventory'), patch.object(harness.subprocess, 'check_output', return_value=output):
                with self.assertRaisesRegex(ValueError, 'test_container_inventory_invalid'):
                    self.boundary.audit_containers()
        for error in (subprocess.TimeoutExpired('synthetic-private-command', 30),
                      subprocess.CalledProcessError(1, 'synthetic-private-command', stderr='private payload'),
                      OSError('private path')):
            with self.subTest(kind=type(error).__name__), patch.object(
                    harness.subprocess, 'check_output', side_effect=error):
                with self.assertRaisesRegex(ValueError, '^test_container_inventory_unavailable$'):
                    self.boundary.audit_containers()
            with patch.object(harness.subprocess, 'check_output', side_effect=['synthetic-one', error]):
                with self.assertRaisesRegex(ValueError, '^test_container_inventory_unavailable$'):
                    self.boundary.audit_containers()

    def test_audit_malformed_inspect_is_rejected_without_private_output(self):
        for payload in ('private payload', '{"private": "payload"}', '[null]'):
            with self.subTest(payload=payload), patch.object(
                    harness.subprocess, 'check_output', side_effect=['synthetic-one', payload]):
                with self.assertRaisesRegex(ValueError, '^test_container_inventory_(unavailable|changed|invalid)$'):
                    self.boundary.audit_containers()

    def test_cli_status_stays_read_only_and_audit_explicitly_adds_controller_check(self):
        self.boundary.initialize()
        before = self.snapshot()
        for action in ('status', 'audit'):
            config_module = SimpleNamespace(load_config=lambda _: self.cfg)
            output = io.StringIO()
            with self.subTest(action=action), patch.object(harness, 'load', return_value=config_module), \
                    patch.object(harness, 'Boundary', return_value=self.boundary), \
                    patch.object(self.boundary, 'report', return_value={'cpu_quota': 16}), \
                    patch.object(self.boundary, 'audit_containers', return_value={
                        'running_containers': 2, 'all_controller_paths_verified': True}) as audit, \
                    patch.object(harness.sys, 'argv', ['constrained-test.py', action, '--config', 'synthetic.json']), \
                    contextlib.redirect_stdout(output):
                harness.main()
            self.assertEqual(audit.call_count, int(action == 'audit'))
            result = json.loads(output.getvalue())
            self.assertEqual(result['cpu_quota'], 16)
            self.assertEqual('all_controller_paths_verified' in result, action == 'audit')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
