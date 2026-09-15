"""Read-only live relay boundary checks for the fixed isolated V1 test deployment.

No login, account mutation, configuration mutation, or model request is performed.
Only synthetic GET requests and deliberate rejection probes are issued. Credentials
are kept in memory and passed to docker exec over stdin, never command arguments.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
TEST = ROOT / ".runtime/platform-v1-test"
REPORT = ROOT / "output/platform-relay-acceptance.json"
DEPLOYMENT = "agent-v1-test"


class AcceptanceFailure(RuntimeError):
    pass


def docker(*args, stdin=None, timeout=30):
    result = subprocess.run(["docker", *args], input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=timeout, check=False)
    if result.returncode:
        raise AcceptanceFailure("docker_operation_failed")
    return result.stdout


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise AcceptanceFailure("invalid_test_identity")
    return value


def surfaces(name, account):
    uid, rid = identity(account["id"]), identity(account["runtime"])
    directory = TEST / "worker/runtimes" / rid
    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    if state.get("uid") != uid or state.get("runtime_id") != rid or state.get("paused"):
        raise AcceptanceFailure("runtime_identity_mismatch")
    release = Path(state["compose"]).resolve().parent
    if not release.is_relative_to(directory.resolve() / "releases"):
        raise AcceptanceFailure("runtime_release_outside_test")
    ids = docker("ps", "-q", "--filter", "label=peixian.runtime_id=" + rid).split()
    if len(ids) != 3:
        return None
    records = json.loads(docker("inspect", *ids))
    result = {}
    for container in records:
        labels = container["Config"]["Labels"]
        service = labels.get("com.docker.compose.service")
        if (labels.get("peixian.uid") != uid or labels.get("peixian.runtime_id") != rid
                or labels.get("peixian.deployment") != DEPLOYMENT or service not in ("agent", "gateway", "model-relay")):
            raise AcceptanceFailure("container_scope_mismatch")
        if container["State"].get("Health", {}).get("Status") != "healthy" or labels.get("peixian.revision") != str(state["revision"]):
            return None
        result[service] = container
    if set(result) != {"agent", "gateway", "model-relay"}:
        raise AcceptanceFailure("duplicate_runtime_surface")
    tests = json.loads((release / "gateway/plugin-tests.json").read_text(encoding="utf-8"))
    item = tests.get("sample-records", {})
    expected = "甲" if name == "platform-a" else "乙"
    if not item.get("platform_connections", {}).get("records") or item.get("options", {}).get("query") != expected:
        return None
    return {"containers": result, "binding": item["platform_connections"]["records"], "release": release,
            "query": expected, "revision": state["revision"], "uid": uid}


PROBE = r'''
import json,pathlib,re,socket,sys,urllib.request,urllib.error
values=json.load(sys.stdin)
results=[]
def need(name,value): results.append({'name':name,'passed':bool(value)})
loader=pathlib.Path('/managed/loaders/sample-records.mjs').read_text()
options=json.loads(re.search(r'const options = (.+);',loader).group(1))
bindings=json.loads(re.search(r'const platform = createPlatform\((.+)\);',loader).group(1))
mine=bindings['records']
need('managed_personal_query_matches',options['query']==values['query'])
need('managed_binding_matches_applied_snapshot',mine==values['binding'])
need('only_declared_connection_alias_exposed',set(bindings)=={'records'})
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def invoke(payload,binding=None,auth=True):
 b=binding or mine
 headers={'Content-Type':'application/json'}
 if auth: headers['Authorization']='Bearer '+b['token']
 req=urllib.request.Request('http://model-relay:8081/platform/connections/'+b['id']+'/request',
      data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers,method='POST')
 try:
  with opener.open(req,timeout=15) as response:
   body=response.read(2097153)
   return response.status,json.loads(body)
 except urllib.error.HTTPError as error:
  return error.code,{}
def denied(name,payload,status,binding=None,auth=True):
 code,_=invoke(payload,binding,auth)
 need(name,code==status)
status,data=invoke({'method':'GET','path':'/health'})
need('authorized_health_through_relay',status==200 and data.get('status')==200 and data.get('data',{}).get('ok') is True)
status,data=invoke({'method':'GET','path':'/records','query':{'q':options['query'],'limit':options['limit']}})
items=data.get('data',{}).get('items',[])
need('authorized_records_use_private_query',status==200 and data.get('status')==200 and len(items)==1 and items[0].get('name')=='资料'+values['query'])
denied('missing_invocation_token_denied',{'path':'/health'},403,auth=False)
denied('wrong_invocation_token_denied',{'path':'/health'},403,binding={**mine,'token':'0'*64})
denied('unauthorized_connection_id_denied',{'path':'/health'},403,binding={**mine,'id':'not-authorized'})
denied('cross_account_invocation_token_denied',{'path':'/health'},403,binding=values['foreign_binding'])
for name,payload,code in (
 ('arbitrary_url_denied',{'path':'http://example.invalid/health'},400),
 ('alternate_host_path_denied',{'path':'//example.invalid/health'},400),
 ('path_traversal_denied',{'path':'/records/../health'},400),
 ('encoded_path_traversal_denied',{'path':'/records/%2e%2e/health'},400),
 ('double_encoded_traversal_denied',{'path':'/records/%252e%252e/health'},400),
 ('backslash_path_denied',{'path':'/records\\health'},400),
 ('query_in_path_denied',{'path':'/records?q=else'},400),
 ('unapproved_path_denied',{'path':'/not-approved'},403),
 ('unapproved_method_denied',{'method':'DELETE','path':'/records'},403),
 ('upstream_header_injection_denied',{'path':'/health','headers':{'Host':'example.invalid'}},400),
 ('upstream_address_override_denied',{'path':'/health','base_url':'http://example.invalid'},400),
 ('oversized_request_denied',{'method':'POST','path':'/records','json':{'text':'x'*1048576}},413),
): denied(name,payload,code)
def cannot_connect(host,port):
 try:
  with socket.create_connection((host,port),timeout=2): return False
 except OSError: return True
need('public_direct_tcp_denied',cannot_connect('1.1.1.1',443))
need('other_account_relay_tcp_denied',cannot_connect(values['foreign_relay_ip'],8081))
need('service_direct_tcp_denied',cannot_connect('host.docker.internal',18094))
print(json.dumps({'checks':results},ensure_ascii=False))
'''

SCAN = r'''
import json,os,pathlib,sys
value=json.load(sys.stdin)
secret=value['secret'].encode()
files=0
found=False
for path in pathlib.Path('/managed').rglob('*'):
 if path.is_symlink(): raise RuntimeError('managed_symlink')
 if not path.is_file(): continue
 files+=1
 with path.open('rb') as stream:
  previous=b''
  while True:
   chunk=stream.read(65536)
   if not chunk: break
   combined=previous+chunk
   found=found or secret in combined
   previous=combined[-len(secret):]
print(json.dumps({'managed_files_checked':files,'public_service_secret_absent':not found,
 'public_service_secret_not_in_environment':all(value['secret'] not in v for v in os.environ.values()),
 'relay_private_config_not_mounted':not pathlib.Path('/managed/connections.json').exists() and not pathlib.Path('/managed/model-relay.json').exists()}))
'''


def exec_json(container, code, values):
    raw = docker("exec", "-i", container, "python3", "-c", code, stdin=json.dumps(values, ensure_ascii=False), timeout=90)
    try:
        return json.loads(raw)
    except ValueError:
        raise AcceptanceFailure("invalid_sanitized_probe_result") from None


def run():
    report = {"scope": "isolated_platform_v1_test_relay_only", "started_at": datetime.now(timezone.utc).isoformat(),
              "model_requests": 0, "configuration_changes": 0, "checks": [], "status": "running"}
    def save():
        report["passed"] = sum(row["passed"] for row in report["checks"])
        report["failed"] = len(report["checks"]) - report["passed"]
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def need(name, value):
        report["checks"].append({"name": name, "passed": bool(value)})
        save()
        print(("pass:" if value else "FAIL:") + name, flush=True)
    try:
        state = json.loads((TEST / "acceptance-private.json").read_text(encoding="utf-8"))
        secret = (TEST / "sample.key").read_text(encoding="utf-8").strip()
        if len(secret) < 16:
            raise AcceptanceFailure("invalid_synthetic_service_secret")
        deadline = time.monotonic() + 300
        while True:
            accounts = {name: surfaces(name, state[name]) for name in ("platform-a", "platform-b")}
            if all(accounts.values()):
                break
            if time.monotonic() > deadline:
                raise AcceptanceFailure("test_plugin_revisions_not_ready")
            time.sleep(2)
        for name, account in accounts.items():
            foreign = accounts["platform-b" if name == "platform-a" else "platform-a"]
            prefix = "a" if name == "platform-a" else "b"
            need(prefix + "_three_healthy_scoped_containers", True)
            own_agent = account["containers"]["agent"]
            networks = own_agent["NetworkSettings"]["Networks"]
            definition = json.loads(docker("network", "inspect", *networks))[0]
            need(prefix + "_agent_only_on_internal_network", len(networks) == 1 and definition["Internal"] is True)
            foreign_relay = foreign["containers"]["model-relay"]
            foreign_network = next(network for key, network in foreign_relay["NetworkSettings"]["Networks"].items() if key.endswith(("_internal", "-internal")))
            values = exec_json(own_agent["Id"], PROBE, {"query": account["query"], "binding": account["binding"],
                "foreign_binding": foreign["binding"], "foreign_relay_ip": foreign_network["IPAddress"]})
            for check in values["checks"]:
                need(prefix + "_" + check["name"], check["passed"])
            for service in ("agent", "gateway"):
                container = account["containers"][service]
                scan = exec_json(container["Id"], SCAN, {"secret": secret})
                need(prefix + "_" + service + "_managed_files_inspected", scan["managed_files_checked"] > 0)
                for key in ("public_service_secret_absent", "public_service_secret_not_in_environment", "relay_private_config_not_mounted"):
                    need(prefix + "_" + service + "_" + key, scan[key])
                need(prefix + "_" + service + "_docker_socket_not_mounted", not any("docker.sock" in item["Destination"] for item in container["Mounts"]))
        report["status"] = "passed" if not report["failed"] else "failed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc) if isinstance(exc, AcceptanceFailure) else "acceptance_failed_" + type(exc).__name__
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({k: report[k] for k in ("status", "passed", "failed")}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True, help="只对固定隔离测试环境执行只读边界检查")
    parser.parse_args()
    raise SystemExit(run())
