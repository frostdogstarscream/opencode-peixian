import asyncio
import json
import os
from pathlib import Path
import shutil

import pytest
from gateway.plugin_test import specification, run_plugin_test


@pytest.mark.skipif(not os.environ.get('BUN_EXECUTABLE'), reason='Explicit Bun runtime required')
def test_gateway_test_receives_same_platform_sdk(tmp_path):
    entry = tmp_path / 'plugins/sample/1.0.0/entry.mjs'
    entry.parent.mkdir(parents=True)
    entry.write_text("export async function test(options, platform) { return {ok: !!platform && typeof platform.connections.request === 'function' && !('secret' in options), message: 'done'}; }")
    client = Path(__file__).resolve().parents[4] / 'deploy/peixian/plugin-client.mjs'
    shutil.copyfile(client, tmp_path / 'platform-client.mjs')
    (tmp_path / 'plugin-tests.json').write_text(json.dumps({'sample': {'entry': str(entry), 'options': {}, 'platform_connections': {'records': {'id': 'a'*32, 'token': 'synthetic-delegated-token'}}}}))
    assert specification(tmp_path, 'sample')['platform_client'] == str((tmp_path / 'platform-client.mjs').resolve())
    assert asyncio.run(run_plugin_test(tmp_path, 'sample')) == {'supported': True, 'ok': True, 'message': 'Connection test passed'}
