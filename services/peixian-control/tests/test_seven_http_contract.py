"""Actual records Handler -> fixed connection policy -> real JS plugin, over TCP."""
import asyncio
import copy
import importlib.util
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from shared.connection_policy import ConnectionFailure, exchange, policy

ROOT = Path(__file__).resolve().parents[3]
PLUGINS = ROOT / "deploy/peixian/examples/seven_data_plugins"
FIXTURES = json.loads((ROOT / "deploy/peixian/platform-facts/fixtures.json").read_text())
MODULES = tuple(FIXTURES["records"])

@pytest.fixture
def chain(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text("contract-only-synthetic-token")
    monkeypatch.setenv("PEIXIAN_RECORDS_KEY_FILE", str(key))
    spec = importlib.util.spec_from_file_location("records_contract", ROOT / "deploy/peixian/examples/peixian_synthetic_records/records_service.py")
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    payloads = copy.deepcopy(FIXTURES["records"])
    calls = []
    def response(module):
        calls.append(module)
        return payloads[module]
    service.response_for = response
    data = ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
    threading.Thread(target=data.serve_forever, daemon=True).start()
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            module = self.path.rsplit("/", 1)[-1]
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            config = policy({**json.loads((PLUGINS / module / "connection-policy.json").read_text()),
                "base_url": f"http://127.0.0.1:{data.server_port}", "timeout_seconds": 2,
                "max_response_bytes": 1048576, "headers": {"Authorization": "Bearer " + key.read_text()}})
            async def execute():
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await exchange(client, config, value)
            try:
                result = asyncio.run(execute()); status = 200
            except ConnectionFailure as exc:
                result = {"error": "rejected"}; status = exc.status
            raw = json.dumps(result).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    def invoke(module, args=None):
        script = """
import plugin from ENTRY;
const platform={connections:{request:async(alias,input)=>{
 const response=await fetch(URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});
 if(!response.ok)throw new Error('policy_rejected');return response.json();
}}};
const loaded=await plugin({}, {},platform);
try {const output=JSON.parse(await loaded.tool[TOOL].execute(ARGS));console.log(JSON.stringify({ok:true,output}));}
catch {console.log(JSON.stringify({ok:false}));}
""".replace("ENTRY", json.dumps((PLUGINS / module / "entry.mjs").as_uri())).replace("URL", json.dumps(f"http://127.0.0.1:{proxy.server_port}/{module}")).replace("TOOL", json.dumps("peixian_get_"+module+"_records")).replace("ARGS",json.dumps(args or {}))
        runner=json.loads(os.environ.get("PEIXIAN_TEST_JS_COMMAND", '["node","--input-type=module"]'))
        result=subprocess.run([*runner,"-e",script],capture_output=True,text=True,timeout=10,check=True)
        return json.loads(result.stdout)
    yield payloads,calls,invoke,f"http://127.0.0.1:{proxy.server_port}"
    proxy.shutdown();data.shutdown();proxy.server_close();data.server_close()

@pytest.mark.parametrize("module", MODULES)
def test_http_success_preserves_rows_and_stable_provenance(chain,module):
    payloads,calls,invoke,_=chain
    result=invoke(module)
    assert result["ok"]
    output=result["output"]
    assert output["items"]==payloads[module]["records"]
    assert len(output["provenance"])==len(output["items"])
    assert len({r["evidence_id"] for r in output["provenance"]})==len(output["items"])
    assert invoke(module)["output"]["provenance"]==output["provenance"]
    assert calls==[module,module]

@pytest.mark.parametrize("fault",["missing_id","duplicate_id","duplicate_row","count","module","snapshot","partial"])
def test_invalid_service_payload_never_becomes_plugin_result(chain,fault):
    payloads,calls,invoke,_=chain
    value=payloads["funds"]
    if fault=="missing_id":del value["records"][0]["record_id"]
    if fault=="duplicate_id":value["records"][1]["record_id"]=value["records"][0]["record_id"]
    if fault=="duplicate_row":
        value["records"][0]["source_row_id"]="row";value["records"][1]["source_row_id"]="row"
    if fault=="count":value["returned_count"]+=1
    if fault=="module":value["module"]="calls"
    if fault=="snapshot":del value["snapshot_id"]
    if fault=="partial":value["data_status"]="partial"
    assert not invoke("funds")["ok"]
    assert calls==["funds"]

def test_repeated_business_identifier_retains_distinct_rows(chain):
    payloads,_,invoke,_=chain
    for i,row in enumerate(payloads["funds"]["records"]):
        row["source_record_id"]="same-business-reference";row["source_row_id"]=f"row-{i}"
    output=invoke("funds")["output"]
    assert len(output["items"])==len(payloads["funds"]["records"])
    assert len({r["evidence_id"] for r in output["provenance"]})==len(output["items"])

def test_module_path_method_and_extra_fields_rejected_before_service(chain):
    _,calls,invoke,url=chain
    assert not invoke("funds",{"module":"calls"})["ok"]
    invalid=[{"method":"POST","path":"/v1/demo/records/query","json":{"module":"calls"}},
             {"method":"GET","path":"/v1/demo/records/query"},
             {"method":"POST","path":"/other","json":{"module":"funds"}},
             {"method":"POST","path":"/v1/demo/records/query","json":{"module":"funds","limit":1}}]
    with httpx.Client(trust_env=False) as client:
        for body in invalid:assert client.post(url+"/funds",json=body).status_code==403
    assert calls==[]
