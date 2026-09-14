"""Audit one synthetic managed runtime without sending an authorized model request."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
import uuid


ROOT = Path(__file__).resolve().parent
module = importlib.util.spec_from_file_location("security_runtime", ROOT / "console-runtime.py")
runtime = importlib.util.module_from_spec(module)
module.loader.exec_module(runtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--state-root", type=Path, default=ROOT / ".runtime/console")
    parser.add_argument("--report", type=Path, default=ROOT / ".runtime/console-security.json")
    args = parser.parse_args()
    identity = runtime.check_id(args.runtime_id)
    project = "px-" + identity
    report = {"status": "running", "runtime_id": identity, "checks": [], "limitations": [],
              "generated_at": datetime.now(timezone.utc).isoformat()}
    runtime.write_json(args.report, report)

    def check(name, passed, layer="deployed"):
        report["checks"].append({"name": name, "pass": bool(passed), "layer": layer})
        runtime.write_json(args.report, report)

    def docker(*values, **kwargs):
        return runtime.command(["docker", *values], **kwargs)

    def execute(container, code, data=None):
        return json.loads(docker("exec", "-i", container, "python3", "-c", code,
                                 data=runtime.json_bytes(data or {}), timeout=90))

    records = json.loads(docker("inspect", *[project + "-" + role + "-1" for role in ("agent", "gateway", "model-relay")]))
    services = {}
    for value in records:
        labels = value["Config"]["Labels"] or {}
        role = labels.get("com.docker.compose.service")
        if labels.get("peixian.runtime_id") != identity or labels.get("com.docker.compose.project") != project:
            raise runtime.RuntimeFailure("audit_runtime_owner_mismatch")
        services[role] = value
    expected_limits = {"agent": (2_000_000_000, 2 * 1024**3, 256),
                       "gateway": (500_000_000, 512 * 1024**2, 128),
                       "model-relay": (500_000_000, 128 * 1024**2, 128)}
    report["image_ids"] = {role: value["Image"] for role, value in services.items()}
    proc = """import json,os
items={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in open('/proc/1/status') if ':' in line}
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'init_uid':items['Uid'].split(),
'caps':items['CapEff'],'nnp':items['NoNewPrivs'],'seccomp':items['Seccomp']}))"""
    for role, value in services.items():
        host, mounts = value["HostConfig"], value["Mounts"]
        cpu, memory, pids = expected_limits[role]
        check(role + ".running_healthy", value["State"]["Running"] and value["State"].get("Health", {}).get("Status") == "healthy")
        check(role + ".configured_uid", value["Config"]["User"] == "10001:10001")
        check(role + ".root_readonly", host["ReadonlyRootfs"])
        check(role + ".all_capabilities_dropped", host["CapDrop"] == ["ALL"] and not host.get("CapAdd"))
        check(role + ".no_new_privileges", "no-new-privileges:true" in host["SecurityOpt"])
        check(role + ".resource_limits", (host["NanoCpus"], host["Memory"], host["PidsLimit"]) == (cpu, memory, pids))
        check(role + ".no_host_ports", not host.get("PortBindings"))
        check(role + ".no_docker_socket", all("docker.sock" not in m["Source"] and "docker.sock" not in m["Destination"] for m in mounts))
        check(role + ".binds_readonly", all(not m["RW"] for m in mounts if m["Type"] == "bind"))
        state = execute(value["Id"], proc)
        check(role + ".actual_uid", state["uid"] == state["gid"] == 10001 and set(state["init_uid"]) == {"10001"})
        check(role + ".actual_caps_nnp_seccomp", int(state["caps"], 16) == 0 and state["nnp"] == "1" and state["seccomp"] == "2")

    def mounted(role):
        return {item["Destination"]: item for item in services[role]["Mounts"]}

    agent, gateway, relay = mounted("agent"), mounted("gateway"), mounted("model-relay")
    check("agent.mount_allowlist", (set(agent) - {"/tmp"}) == {"/home/opencode", "/workspace", "/files", "/managed", "/run/secrets/opencode-password"})
    check("gateway.mount_allowlist", (set(gateway) - {"/tmp"}) == {"/workspace", "/files", "/managed", "/run/secrets/gateway-token", "/run/secrets/opencode-password"})
    check("relay.mount_allowlist", (set(relay) - {"/tmp"}) == {"/managed"})
    check("agent.files_readonly", not agent["/files"]["RW"] and gateway["/files"]["RW"])
    check("account.shared_workspace_only", agent["/workspace"]["Name"] == gateway["/workspace"]["Name"] and
          agent["/files"]["Name"] == gateway["/files"]["Name"] and agent["/workspace"]["Name"] != agent["/files"]["Name"])
    relay_source = relay["/managed"]["Source"]
    check("model_secret_directory_only_mounted_by_relay", all(m["Source"] != relay_source for role in ("agent", "gateway") for m in services[role]["Mounts"]))
    check("managed_directories_distinct", len({agent["/managed"]["Source"], gateway["/managed"]["Source"], relay_source}) == 3)

    networks = services["agent"]["NetworkSettings"]["Networks"]
    check("agent.only_own_internal_network", set(networks) == {project + "-internal"})
    net = json.loads(docker("network", "inspect", project + "-internal"))[0]
    check("agent.network_internal", net["Internal"] is True and net["Labels"].get("peixian.runtime_id") == identity)
    control = json.loads(docker("inspect", "peixian-console"))[0]
    destinations = [{"name": "public_ipv4", "host": "1.1.1.1", "port": 443}]
    if project + "-management" in control["NetworkSettings"]["Networks"]:
        destinations.append({"name": "control_management_compartment", "host": control["NetworkSettings"]["Networks"][project + "-management"]["IPAddress"], "port": 8080})
    other_management = 0
    for network in json.loads(docker("network", "inspect", *docker("network", "ls", "--filter", "label=" + runtime.MANAGED + "=true", "--format", "{{.ID}}").split())):
        labels = network.get("Labels") or {}
        if network["Name"].endswith("-management") and labels.get("peixian.runtime_id") != identity:
            other_management += 1
            for value in network.get("Containers", {}).values():
                if value["Name"].endswith("-gateway-1"):
                    destinations.append({"name": "other_account_management_" + str(other_management), "host": value["IPv4Address"].split("/")[0], "port": 8080})
    if not other_management:
        report["limitations"].append("No second managed account management network existed; checked own control compartment, legacy peer and absence of a default route.")
    legacy_ids = docker("ps", "--filter", "label=com.docker.compose.project=peixian-opencode",
                        "--filter", "label=com.docker.compose.service=client-b", "--format", "{{.ID}}").split()
    if legacy_ids:
        peer = json.loads(docker("inspect", legacy_ids[0]))[0]
        address = next(iter(peer["NetworkSettings"]["Networks"].values()))["IPAddress"]
        destinations.append({"name": "legacy_peer", "host": address, "port": 4096})
    network_probe = """import json,socket,sys
targets=json.load(sys.stdin)['targets'];values={}
routes=[line.split() for line in open('/proc/net/route').read().splitlines()[1:]]
values['no_default_route']=not any(line[1]=='00000000' for line in routes)
for target in targets:
 try:
  stream=socket.create_connection((target['host'],target['port']),timeout=2);stream.close();values[target['name']]=False
 except OSError: values[target['name']]=True
print(json.dumps(values))"""
    for name, result in execute(services["agent"]["Id"], network_probe, {"targets": destinations}).items():
        check("agent.network_denial." + name, result)

    request_probe = """import json,urllib.request,urllib.error,sys
v=json.load(sys.stdin);key=open('/run/secrets/gateway-token').read().rstrip('\\r\\n');results=[]
for item in v['requests']:
 headers={'Content-Type':'application/json'}
 if item.get('auth',True):headers['X-Peixian-Key']=key
 req=urllib.request.Request('http://127.0.0.1:8080'+item['path'],headers=headers,method=item['method'],
  data=json.dumps(item['body']).encode() if 'body' in item else None)
 try:
  with urllib.request.urlopen(req,timeout=10) as response:code=response.status
 except urllib.error.HTTPError as error:code=error.code
 results.append(code)
print(json.dumps(results))"""
    requests = [{"method": "GET", "path": "/health", "auth": False, "expected": 401}]
    for method, path in (("GET", "/config"), ("PATCH", "/config"), ("GET", "/pty"), ("POST", "/pty"),
                         ("GET", "/auth"), ("PUT", "/auth/synthetic"), ("GET", "/file/content?path=/etc/passwd"),
                         ("GET", "/arbitrary/synthetic/path"), ("POST", "/session/synthetic/shell")):
        requests.append({"method": method, "path": path, "expected": 404, **({"body": {}} if method != "GET" else {})})
    requests += [{"method": "GET", "path": "/session?directory=/etc", "expected": 400},
                 {"method": "GET", "path": "/session?tenant_id=synthetic", "expected": 400},
                 {"method": "POST", "path": "/session", "body": {"directory": "/etc"}, "expected": 400}]
    codes = execute(services["gateway"]["Id"], request_probe, {"requests": requests})
    for index, (request, code) in enumerate(zip(requests, codes)):
        check("gateway.forbidden_route_" + str(index + 1), code == request["expected"])

    forged = "synthetic-forbidden-" + uuid.uuid4().hex
    relay_probe = """import json,urllib.request,urllib.error,sys
value=json.load(sys.stdin)
request=urllib.request.Request('http://127.0.0.1:8081/v1/chat/completions',data=json.dumps({
'model':value['model'],'messages':[{'role':'user','content':'synthetic denied request'}]}).encode(),headers={'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(request,timeout=10) as response:code=response.status
except urllib.error.HTTPError as error:code=error.code
print(json.dumps({'code':code}))"""
    check("relay.forged_model_denied", execute(services["model-relay"]["Id"], relay_probe, {"model": forged})["code"] == 403)
    guard_probe = """import json,hashlib,httpx
from fastapi.testclient import TestClient
from gateway.model_relay import create_app
calls=[]
def upstream(request): calls.append(True);raise AssertionError('No upstream is permitted')
with TestClient(create_app(models={},transport=httpx.MockTransport(upstream))) as client:
 response=client.post('/v1/chat/completions',json={'model':'synthetic-denied','messages':[]})
print(json.dumps({'denied':response.status_code==403,'upstream_calls':len(calls),
'source_sha256':hashlib.sha256(open('/app/gateway/model_relay.py','rb').read().replace(b'\\r\\n',b'\\n')).hexdigest()}))"""
    guard = execute(services["model-relay"]["Id"], guard_probe)
    source = ROOT.parents[1] / "services/peixian-control/gateway/model_relay.py"
    check("relay.deployed_source_matches_guard", guard["source_sha256"] == hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest())
    check("relay.forged_model_never_calls_transport", guard["denied"] and guard["upstream_calls"] == 0, "deployed_image_inprocess")

    token = uuid.uuid4().hex
    name, volume = "px-security-" + token, "px-security-home-" + token
    temporary = ROOT / ".runtime" / "security" / token
    (temporary / "managed").mkdir(parents=True)
    runtime.write_secret(temporary / "password", "synthetic-empty-managed-password-0001")
    runtime.grant_container_read(temporary)
    created = False
    try:
        docker("volume", "create", "--label", "peixian.security.audit=" + token, volume)
        created = True
        docker("run", "--rm", "--pull", "never", "--network", "none", "--read-only", "--user", "0:0",
               "--cap-drop", "ALL", "--cap-add", "CHOWN", "--security-opt", "no-new-privileges:true",
               "--mount", "type=volume,source=" + volume + ",target=/empty,volume-nocopy",
               "--entrypoint", "python3", services["agent"]["Image"], "-c",
               "import os;assert not os.listdir('/empty');os.chown('/empty',10001,10001)")
        docker("create", "--name", name, "--label", "peixian.security.audit=" + token, "--pull", "never",
               "--network", "none", "--read-only", "--user", "10001:10001", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true", "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
               "--mount", "type=volume,source=" + volume + ",target=/home/opencode,volume-nocopy",
               "--mount", "type=bind,source=" + str(temporary / "managed") + ",target=/managed,readonly",
               "--mount", "type=bind,source=" + str(temporary / "password") + ",target=/run/secrets/opencode-password,readonly",
               services["agent"]["Image"])
        docker("start", name)
        code = int(docker("wait", name, timeout=30).strip())
        logs = subprocess.run(["docker", "logs", name], capture_output=True, check=False)
        check("missing_managed.exits_nonzero", code != 0)
        check("missing_managed.config_error_reported", b"Managed runtime configuration is unavailable" in logs.stdout + logs.stderr)
        count = json.loads(docker("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--mount", "type=volume,source=" + volume + ",target=/empty,readonly,volume-nocopy", "--entrypoint", "python3",
            services["agent"]["Image"], "-c", "import os,json;print(json.dumps({'entries':len(os.listdir('/empty'))}))"))["entries"]
        check("missing_managed.no_home_or_npm_cache_written", count == 0)
    finally:
        matches = docker("ps", "-a", "--filter", "name=^/" + name + "$", "--filter", "label=peixian.security.audit=" + token,
                         "--format", "{{.ID}}").split()
        for container in matches:
            state = json.loads(docker("inspect", "--format", "{{json .State.Running}}", container))
            if state:
                docker("stop", container)
            docker("rm", container)
        if created:
            labels = json.loads(docker("volume", "inspect", volume))[0].get("Labels") or {}
            if labels.get("peixian.security.audit") == token:
                docker("volume", "rm", volume)
    check("temporary_probe.cleaned_up", not docker("ps", "-a", "--filter", "label=peixian.security.audit=" + token, "--format", "{{.ID}}").strip())
    report["unit_evidence"] = {"managed_config_source_and_workspace_plugin_boundary": "166 previously passed core tests; not counted as deployed checks"}
    report["passed"] = sum(item["pass"] for item in report["checks"])
    report["failed"] = len(report["checks"]) - report["passed"]
    report["status"] = "passed" if not report["failed"] else "failed"
    runtime.write_json(args.report, report)
    print(json.dumps({"status": report["status"], "passed": report["passed"], "failed": report["failed"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        path = ROOT / ".runtime/console-security.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"checks": []}
        report["checks"].append({"name": "audit_operation_completed", "pass": False, "layer": "audit"})
        report["passed"] = sum(item["pass"] for item in report["checks"])
        report["failed"] = len(report["checks"]) - report["passed"]
        report["status"] = "failed"
        runtime.write_json(path, report)
        print(json.dumps({"status": "failed", "passed": report["passed"], "failed": report["failed"]}))
        raise SystemExit(1) from None
