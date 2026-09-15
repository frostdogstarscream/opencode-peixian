import ipaddress
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_console_runtime import FakeRuntime, package, runtime, spec


class PlatformRuntimeTests(unittest.TestCase):
    def test_resource_budget_reaches_compose_and_rejects_invalid_values(self):
        limits = {"agent": {"cpus": 1.5, "memory_mib": 1024}, "gateway": {"cpus": 0.4, "memory_mib": 256},
                  "relay": {"cpus": 0.2, "memory_mib": 128}}
        value = runtime.compose_spec(spec(), Path.cwd(), agent_image='a', gateway_image='g', limits=limits, deployment_id='example')
        self.assertEqual(value['services']['agent']['mem_limit'], '1024m')
        self.assertEqual(value['services']['model-relay']['cpus'], 0.2)
        self.assertEqual(value['volumes']['workspace']['labels']['peixian.deployment'], 'example')
        limits['agent']['cpus'] = True
        with self.assertRaises(runtime.RuntimeFailure):
            runtime.normalize_limits(limits)

    def test_service_credentials_only_reach_relay_and_plugin_tokens_are_scoped(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'grant_container_read'):
            manager = FakeRuntime(folder)
            payload, plugin = package()
            plugin['platform_connections'] = {'records': {'id': '1' * 32, 'token': 'synthetic-binding-token'}}
            value = spec()
            value['plugins'] = [plugin]
            value['connections'] = [{'id': '1' * 32, 'headers': {'Authorization': 'synthetic-upstream-secret'}}]
            release = manager.prepare(value, lambda _: payload)
            for name in ('agent', 'gateway'):
                for path in (release / name).rglob('*'):
                    if path.is_file():
                        self.assertNotIn(b'synthetic-upstream-secret', path.read_bytes())
                self.assertTrue((release / name / 'platform-client.mjs').exists())
            self.assertIn('synthetic-upstream-secret', (release / 'relay/connections.json').read_text())
            tests = json.loads((release / 'gateway/plugin-tests.json').read_text())
            self.assertEqual(tests['synthetic']['platform_connections'], plugin['platform_connections'])
            self.assertEqual(len(json.loads((release / 'compose.json').read_text())['services']), 3)

    def test_pool_allocation_avoids_every_existing_docker_subnet(self):
        manager = object.__new__(runtime.RuntimeManager)
        manager.network_pool = ipaddress.ip_network('10.240.0.0/24')
        def docker(*args):
            if args[:2] == ('network', 'ls'):
                return 'one two'
            return json.dumps([{'IPAM': {'Config': [{'Subnet': '10.240.0.0/28'}, {'Subnet': '10.240.0.16/28'}]}}])
        manager.docker_run = docker
        self.assertEqual(manager.available_subnet(), '10.240.0.32/28')
        manager.docker_run = lambda *args: 'one' if args[:2] == ('network', 'ls') else json.dumps([{'IPAM': {'Config': [{'Subnet': '10.240.0.0/24'}]}}])
        with self.assertRaisesRegex(runtime.RuntimeFailure, 'configured_network_pool_exhausted'):
            manager.available_subnet()


if __name__ == '__main__':
    unittest.main()
