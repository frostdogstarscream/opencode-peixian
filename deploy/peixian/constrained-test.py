"""Opt-in Linux cgroup-v1 harness for a synthetic 16-CPU/32-GiB platform test.

This does not alter the host Docker daemon or existing containers. All workload
containers and the worker use one new deployment-owned parent. Four GiB remains
an accounting reserve: application aggregate memory is capped at 28 GiB. This is
resource-constrained testing on a shared host, not a dedicated 16-core machine.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
GIB = 1024**3


def load(name):
    spec = importlib.util.spec_from_file_location('constrained_' + name.replace('-', '_'), ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expand_cpus(value):
    result = []
    for item in value.strip().split(','):
        ends = item.split('-')
        if len(ends) not in (1, 2) or any(not v.isdigit() for v in ends):
            raise ValueError('invalid_cpu_set')
        result.extend(range(int(ends[0]), int(ends[-1]) + 1))
    return sorted(set(result))


class Boundary:
    def __init__(self, cfg, base=Path('/sys/fs/cgroup')):
        if not re.fullmatch(r'loadtest-[a-z0-9-]{1,30}', cfg.deployment_id):
            raise ValueError('synthetic_deployment_required')
        if cfg.version not in (2, 3) or cfg.capacity_policy.get('host_memory_reserve_mib', 0) < 4096:
            raise ValueError('test_requires_v2_and_four_gib_reserve')
        self.cfg, self.base = cfg, Path(base)
        self.name = cfg.deployment_id
        self.paths = {key: self.base / key / self.name for key in ('cpu,cpuacct', 'memory', 'cpuset', 'pids')}

    def safe_paths(self):
        for path in self.paths.values():
            if path.parent.is_symlink() or path.is_symlink() or path.resolve() != path.parent.resolve() / self.name:
                raise ValueError('test_cgroup_path_is_link')
            if path.exists() and any(item.is_symlink() for item in path.iterdir() if not item.is_dir()):
                raise ValueError('test_cgroup_counter_is_link')

    def expected(self):
        cpus = expand_cpus((self.base / 'cpuset/cpuset.cpus').read_text())
        if len(cpus) < 16:
            raise ValueError('host_has_fewer_than_sixteen_cpus')
        return {
            'cpu,cpuacct': {'cpu.cfs_period_us': '100000', 'cpu.cfs_quota_us': '1600000'},
            'memory': {'memory.use_hierarchy': '1', 'memory.limit_in_bytes': str(28 * GIB),
                       'memory.memsw.limit_in_bytes': str(28 * GIB)},
            'cpuset': {'cpuset.mems': (self.base / 'cpuset/cpuset.mems').read_text().strip(),
                       'cpuset.cpus': ','.join(map(str, cpus[-16:]))},
            'pids': {'pids.max': '16384'},
        }

    def initialize(self):
        self.safe_paths()
        expected = self.expected()
        if any(path.exists() for path in self.paths.values()):
            self.verify()
            return
        for key, values in expected.items():
            path = self.paths[key]
            path.mkdir(exist_ok=False)
            for name, value in values.items():
                (path / name).write_text(value)
        self.verify()

    def verify(self):
        self.safe_paths()
        for key, values in self.expected().items():
            for name, value in values.items():
                actual = (self.paths[key] / name).read_text().strip()
                same = expand_cpus(actual) == expand_cpus(value) if name == 'cpuset.cpus' else actual == value
                if not same:
                    raise ValueError('test_parent_limit_changed')

    def join(self):
        self.verify()
        for path in self.paths.values():
            (path / 'cgroup.procs').write_text(str(os.getpid()))

    def capacity(self, module):
        evaluate = module.evaluate
        def constrained(info, required):
            self.verify()
            effective = {**info, 'NCPU': min(info.get('NCPU', 0), 16),
                         'MemTotal': min(info.get('MemTotal', 0), 32 * GIB)}
            result = evaluate(effective, required)
            result.update(capacity_source='verified_test_parent', application_memory_ceiling_bytes=28 * GIB,
                          host_accounting_reserve_bytes=4 * GIB)
            return result
        module.evaluate = constrained

    def compose(self, spec):
        services = spec.get('services', {})
        if not services or any(service.get('labels', {}).get('peixian.deployment') != self.name for service in services.values()):
            raise ValueError('compose_deployment_mismatch')
        for service in services.values():
            # Docker/containerd can resolve relative parents against its service
            # cgroup on v1; absolute paths keep every controller under our group.
            service['cgroup_parent'] = '/' + self.name
        return spec

    def audit_containers(self):
        try:
            ids = subprocess.check_output(
                ['docker', 'ps', '-q', '--filter', 'label=peixian.deployment=' + self.name],
                text=True, timeout=30, stderr=subprocess.PIPE).split()
        except (OSError, subprocess.SubprocessError):
            raise ValueError('test_container_inventory_unavailable') from None
        if not ids:
            raise ValueError('no_running_test_containers')
        if len(ids) > 3 * 64 + 16 or len(set(ids)) != len(ids):
            raise ValueError('test_container_inventory_invalid')
        try:
            records = json.loads(subprocess.check_output(
                ['docker', 'inspect', *ids], text=True, timeout=30, stderr=subprocess.PIPE))
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ValueError('test_container_inventory_unavailable') from None
        if not isinstance(records, list) or len(records) != len(ids):
            raise ValueError('test_container_inventory_changed')
        for record in records:
            if (not isinstance(record, dict) or not isinstance(record.get('Config'), dict) or
                    not isinstance(record['Config'].get('Labels'), dict) or
                    not isinstance(record.get('State'), dict) or not isinstance(record.get('HostConfig'), dict)):
                raise ValueError('test_container_inventory_invalid')
            if record['Config']['Labels'].get('peixian.deployment') != self.name:
                raise ValueError('container_deployment_changed_during_audit')
            pid = record['State'].get('Pid')
            if record['State'].get('Running') is not True or type(pid) is not int or pid <= 0:
                raise ValueError('container_stopped_during_audit')
            if record['HostConfig'].get('CgroupParent') != '/' + self.name:
                raise ValueError('container_parent_not_absolute_test_group')
            groups = {}
            try:
                for line in (Path('/proc') / str(pid) / 'cgroup').read_text().splitlines():
                    _, controllers, path = line.split(':', 2)
                    groups.update({key: path for key in controllers.split(',')})
            except (OSError, ValueError):
                raise ValueError('container_cgroup_unavailable_during_audit') from None
            if any(not groups.get(key,'').startswith('/'+self.name+'/') for key in ('memory','cpu','cpuacct','cpuset','pids')):
                raise ValueError('container_escaped_effective_test_boundary')
        return {'running_containers':len(records),'all_controller_paths_verified':True}

    def report(self):
        self.verify()
        result = {'deployment_id': self.name, 'cpu_quota': 16, 'application_memory_limit_bytes': 28 * GIB,
                  'accounting_total_memory_bytes': 32 * GIB, 'cgroup_version': 1, 'counters': {}}
        for key, names in {
            'memory': ('memory.usage_in_bytes','memory.max_usage_in_bytes','memory.failcnt','memory.oom_control'),
            'cpu,cpuacct': ('cpu.stat','cpuacct.usage'), 'pids': ('pids.current',), 'cpuset': ('cpuset.cpus',)
        }.items():
            for name in names:
                result['counters'][name] = (self.paths[key] / name).read_text().strip()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init-group', 'status', 'audit', 'manage', 'worker'))
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--manage-action', choices=('init', 'check', 'render', 'up', 'status', 'stop'))
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    cfg = load('platform-config').load_config(args.config)
    boundary = Boundary(cfg)
    if args.action == 'init-group':
        boundary.initialize()
        print(json.dumps(boundary.report()))
        return
    boundary.verify()
    if args.action == 'status':
        print(json.dumps(boundary.report()))
        return
    if args.action == 'audit':
        print(json.dumps({**boundary.report(), **boundary.audit_containers()}))
        return
    if args.action == 'manage':
        if not args.manage_action:
            parser.error('--manage-action is required')
        manager = load('platform-manage')
        boundary.capacity(manager.config.capacity)
        compose = manager.compose_config
        manager.compose_config = lambda *a, **kw: boundary.compose(compose(*a, **kw))
        sys.argv = [str(ROOT / 'platform-manage.py'), args.manage_action, '--config', str(args.config)]
        manager.main()
        return
    worker = load('console-worker')
    boundary.capacity(worker.runtime.capacity_contract)
    compose = worker.runtime.compose_spec
    worker.runtime.compose_spec = lambda *a, **kw: boundary.compose(compose(*a, **kw))
    boundary.join()
    sys.argv = [str(ROOT / 'console-worker.py'), '--config', str(args.config)] + (['--once'] if args.once else [])
    worker.main()


if __name__ == '__main__':
    main()
