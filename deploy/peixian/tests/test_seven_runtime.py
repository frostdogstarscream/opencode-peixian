import hashlib,io,json,zipfile
from unittest.mock import patch
import pytest
import test_console_runtime as base


def candidate():
    root=base.ROOT/'examples/seven_data_plugins/night'
    manifest=json.loads((root/'manifest.json').read_text())
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for name in ('manifest.json','entry.mjs'):archive.writestr(name,(root/name).read_bytes())
    raw=stream.getvalue()
    return raw,{'id':manifest['id'],'version':manifest['version'],'manifest':manifest,'digest':hashlib.sha256(raw).hexdigest(),'options':{},'platform_connections':{'records':{'id':'fixed-night','token':'synthetic-relay-token-1234567890'}}}

def test_seven_agent_has_fixed_bridge_not_relay_credentials(tmp_path):
    raw,plugin=candidate();spec=base.spec();spec['plugins']=[plugin];manager=base.FakeRuntime(tmp_path)
    with patch.object(base.runtime,'grant_container_read'):release=manager.prepare(spec,lambda _:raw)
    loader=(release/'agent/loaders/peixian-records-night.mjs').read_text()
    assert 'remoteTool' in loader and 'synthetic-relay-token' not in loader
    assert 'synthetic-relay-token' in (release/'gateway/plugin-tests.json').read_text()
    assert (release/'gateway/platform-facts/engine.mjs').is_file()
    assert not (release/'gateway/platform-facts/coordinator.mjs').exists()
    config=json.loads((release/'agent/opencode.json').read_text())
    assert config['plugin'].count('file:///managed/loaders/platform-facts.mjs')==1

def test_mixed_legacy_and_seven_is_rejected_before_publication(tmp_path):
    raw,plugin=candidate();spec=base.spec();spec['plugins']=[plugin,{'id':'peixian-synthetic-records'}]
    with pytest.raises(base.runtime.RuntimeFailure,match='ambiguous_records_plugin_chain'):
        base.FakeRuntime(tmp_path).prepare(spec,lambda _:raw)
