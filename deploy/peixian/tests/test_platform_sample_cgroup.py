"""Execute the actual in-container probe against synthetic cgroup file trees."""
from pathlib import Path
import tempfile
import unittest

from test_platform_delivery import load


sampler = load('platform-sample')
namespace = {'__name__': 'cgroup_probe_test'}
exec(compile(sampler.CGROUP_CODE, '<cgroup-probe>', 'exec'), namespace)
collect = namespace['collect']


class CgroupProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'cgroup'
        self.proc = self.base / 'proc'
        self.root.mkdir()
        self.proc.mkdir()
        self.put(self.proc / 'meminfo', 'MemAvailable: 1024 kB\nSwapFree: 0 kB\nSwapTotal: 0 kB\n')

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value), encoding='utf-8')

    def layout(self, version, member='/synthetic/tenant', mount_root='/', memory_mount='memory'):
        if version == 2:
            self.put(self.proc / 'self/cgroup', f'0::{member}\n')
            self.put(self.proc / 'self/mountinfo',
                     f'30 20 0:1 {mount_root} /sys/fs/cgroup ro - cgroup2 cgroup rw\n')
            relative = member.removeprefix(mount_root).lstrip('/') if mount_root != '/' else member.lstrip('/')
            return self.root / relative
        self.put(self.proc / 'self/cgroup', f'3:memory:{member}\n2:cpu,cpuacct:{member}\n')
        self.put(self.proc / 'self/mountinfo',
                 f'30 20 0:1 {mount_root} /sys/fs/cgroup/{memory_mount} ro - cgroup cgroup rw,memory\n'
                 f'31 20 0:2 {mount_root} /sys/fs/cgroup/cpu,cpuacct ro - cgroup cgroup rw,cpu,cpuacct\n')
        relative = member.removeprefix(mount_root).lstrip('/') if mount_root != '/' else member.lstrip('/')
        return self.root / memory_mount / relative

    def probe(self):
        return collect(self.root, self.proc)

    def v1_values(self, directory, oom='oom_kill_disable 0\nunder_oom 0\noom_kill 2\n'):
        for name, value in {'memory.usage_in_bytes': 101, 'memory.max_usage_in_bytes': 205,
                            'memory.limit_in_bytes': 4096, 'memory.failcnt': 7,
                            'memory.oom_control': oom}.items():
            self.put(directory / name, value)

    def test_v1_current_process_not_host_root_and_distinct_oom_counters(self):
        directory = self.layout(1)
        self.v1_values(directory)
        self.put(self.root / 'memory/memory.usage_in_bytes', 999999)
        result = self.probe()
        self.assertEqual(result['version'], 1)
        self.assertEqual(result['hierarchy_versions'], [1])
        self.assertEqual(result['memory.current'], 101)
        self.assertEqual(result['memory.peak'], 205)
        self.assertEqual(result['memory.max'], 4096)
        self.assertEqual(result['memory.failcnt'], 7)
        self.assertEqual(result['memory.oom_kill'], 2)
        self.assertIsNone(result['memory.events'])
        self.assertIsNone(result['memory.swap.current'])
        self.assertNotIn('tenant', str(result))
        self.assertNotIn(str(self.base), str(result))

    def test_v1_older_kernel_without_oom_kill_keeps_unknown(self):
        self.v1_values(self.layout(1), 'oom_kill_disable 0\nunder_oom 1\n')
        result = self.probe()
        self.assertEqual(result['memory.failcnt'], 7)
        self.assertEqual(result['memory.oom_control']['under_oom'], 1)
        self.assertIsNone(result['memory.oom_kill'])
        self.assertIsNone(result['memory.events'])

    def test_v1_container_scoped_mount_root(self):
        self.v1_values(self.layout(1, mount_root='/synthetic/tenant'))
        self.assertEqual(self.probe()['memory.current'], 101)

    def test_v1_namespaced_membership_at_root(self):
        self.v1_values(self.layout(1, member='/'))
        self.assertEqual(self.probe()['memory.current'], 101)

    def test_v1_cpu_time_has_explicit_units(self):
        self.v1_values(self.layout(1))
        directory = self.root / 'cpu,cpuacct/synthetic/tenant'
        self.put(directory / 'cpu.stat', 'nr_periods 10\nnr_throttled 2\nthrottled_time 8000000\n')
        self.put(directory / 'cpuacct.usage', 123456789)
        self.put(directory / 'cpuacct.stat', 'user 12\nsystem 3\n')
        result = self.probe()
        self.assertEqual(result['cpu.version'], 1)
        self.assertEqual(result['cpu.stat.time_unit'], 'nanoseconds')
        self.assertEqual(result['cpu.stat']['throttled_time'], 8000000)
        self.assertEqual(result['cpuacct.usage'], 123456789)
        self.assertEqual(result['cpuacct.usage.unit'], 'nanoseconds')
        self.assertEqual(result['cpuacct.stat'], {'user': 12, 'system': 3})

    def test_v2_existing_fields_and_unlimited_limit_remain_compatible(self):
        directory = self.layout(2, member='/')
        for key, value in {'memory.current': 100, 'memory.peak': 200, 'memory.max': 'max',
                           'memory.swap.current': 30, 'memory.events': 'oom 1\noom_kill 0\n',
                           'cpu.stat': 'usage_usec 42\nnr_throttled 3\nthrottled_usec 100\n'}.items():
            self.put(directory / key, value)
        result = self.probe()
        self.assertEqual(result['version'], 2)
        self.assertEqual(result['memory.current'], 100)
        self.assertEqual(result['memory.peak'], 200)
        self.assertEqual(result['memory.max'], 'max')
        self.assertEqual(result['memory.swap.current'], 30)
        self.assertEqual(result['memory.events'], {'oom': 1, 'oom_kill': 0})
        self.assertEqual(result['cpu.stat']['usage_usec'], 42)
        self.assertEqual(result['cpu.stat.time_unit'], 'microseconds')
        self.assertEqual(result['engine.MemAvailable'], 1024 * 1024)

    def test_v2_full_hierarchy_uses_current_subgroup(self):
        directory = self.layout(2)
        self.put(self.root / 'memory.current', 999999)
        self.put(directory / 'memory.current', 321)
        self.assertEqual(self.probe()['memory.current'], 321)

    def test_hybrid_hierarchy_does_not_mislabel_memory_or_cpu(self):
        self.v1_values(self.layout(1))
        membership = self.proc / 'self/cgroup'
        mounts = self.proc / 'self/mountinfo'
        self.put(membership, membership.read_text() + '0::/\n')
        self.put(mounts, mounts.read_text() +
                 '32 20 0:3 / /sys/fs/cgroup/unified ro - cgroup2 cgroup rw\n')
        result = self.probe()
        self.assertEqual(result['version'], 1)
        self.assertEqual(result['cpu.version'], 1)
        self.assertEqual(result['hierarchy_versions'], [1, 2])

    def test_missing_malformed_or_negative_counters_are_unknown_not_zero(self):
        directory = self.layout(1)
        self.put(directory / 'memory.usage_in_bytes', 'not a number')
        self.put(directory / 'memory.max_usage_in_bytes', -1)
        self.put(directory / 'memory.oom_control', 'oom_kill password\n')
        result = self.probe()
        for key in ('memory.current', 'memory.peak', 'memory.max', 'memory.failcnt', 'memory.oom_kill'):
            self.assertIsNone(result[key])
        self.assertNotIn('password', str(result))

    def test_wrong_mount_or_membership_never_falls_back_to_visible_root(self):
        for member, mount_root, memory_mount in (
                ('/other/tenant', '/synthetic', 'memory'),
                ('/synthetic/../tenant', '/', 'memory'),
                ('/synthetic/tenant', '/', '../outside')):
            with self.subTest(member=member, mount_root=mount_root, memory_mount=memory_mount):
                self.layout(1, member=member, mount_root=mount_root, memory_mount=memory_mount)
                self.put(self.root / 'memory/memory.usage_in_bytes', 999999)
                self.assertIsNone(self.probe()['memory.current'])

    def test_symlink_escape_is_not_read(self):
        directory = self.layout(1)
        directory.mkdir(parents=True)
        private = self.base / 'private'
        private.write_text('999999', encoding='utf-8')
        try:
            (directory / 'memory.usage_in_bytes').symlink_to(private)
        except OSError:
            self.skipTest('symlink privilege unavailable')
        self.assertIsNone(self.probe()['memory.current'])

    def test_probe_does_not_reset_peaks_failures_or_other_files(self):
        self.v1_values(self.layout(1))
        before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.base.rglob('*') if path.is_file()}
        self.probe()
        after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.base.rglob('*') if path.is_file()}
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
