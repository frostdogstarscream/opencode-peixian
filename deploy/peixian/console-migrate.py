"""Inspect and migrate the two fixed legacy accounts without deleting any volume."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import inspect
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import time
import uuid

import httpx


ROOT = Path(__file__).resolve().parent
loaded = importlib.util.spec_from_file_location("console_migration_worker", ROOT / "console-worker.py")
worker = importlib.util.module_from_spec(loaded)
loaded.loader.exec_module(worker)
runtime = worker.runtime
PROJECT = "peixian-opencode"
CLIENTS = ("client-a", "client-b")
INSPECT = ('{"id":{{json .Id}},"name":{{json .Name}},"image_id":{{json .Image}},'
           '"state":{{json .State.Status}},"running":{{json .State.Running}},'
           '"labels":{{json .Config.Labels}},"mounts":{{json .Mounts}}}')

# The helper has a read-only source mount, no network and no output mount.
# File contents travel directly into a private host archive through stdout.
SNAPSHOT = r'''
import hashlib,io,json,os,stat,sys,tarfile
records=[]
class HashReader:
 def __init__(self,source): self.source,self.digest=source,hashlib.sha256()
 def read(self,size):
  value=self.source.read(size);self.digest.update(value);return value
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|',format=tarfile.PAX_FORMAT) as archive:
 for directory,dirs,files in os.walk('/source',followlinks=False):
  dirs.sort();files.sort()
  for name in dirs+files:
   path=os.path.join(directory,name);relative=os.path.relpath(path,'/source').replace(os.sep,'/')
   before=os.lstat(path);archive.inodes.clear();member=archive.gettarinfo(path,arcname='data/'+relative)
   record={'path':relative,'mode':stat.S_IMODE(before.st_mode),'uid':before.st_uid,'gid':before.st_gid}
   if stat.S_ISREG(before.st_mode):
    with open(path,'rb') as source:
     reader=HashReader(source);archive.addfile(member,reader);after=os.fstat(source.fileno())
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns): raise ValueError('source_changed')
    record.update(type='file',size=before.st_size,sha256=reader.digest.hexdigest())
   elif stat.S_ISDIR(before.st_mode): archive.addfile(member);record.update(type='directory')
   elif stat.S_ISLNK(before.st_mode): archive.addfile(member);record.update(type='symlink',target=os.readlink(path))
   else: raise ValueError('unsupported_file_type')
   records.append(record)
 records.sort(key=lambda item:item['path'])
 body=json.dumps(records,sort_keys=True,separators=(',',':')).encode()
 member=tarfile.TarInfo('manifest.json');member.size=len(body);member.mode=0o600
 archive.addfile(member,io.BytesIO(body))
'''


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def docker(*args, timeout=60):
    return runtime.command(["docker", *args], timeout=timeout)


def containers(*filters):
    args = ["ps", "-a"]
    for value in filters:
        args.extend(("--filter", value))
    ids = docker(*args, "--format", "{{.ID}}").split()
    return [json.loads(docker("inspect", "--format", INSPECT, identity)) for identity in ids]


def inventory(client):
    if client not in CLIENTS:
        raise runtime.RuntimeFailure("unsupported_legacy_account")
    records = containers("label=com.docker.compose.project=" + PROJECT)
    selected = {}
    for item in records:
        service = (item["labels"] or {}).get("com.docker.compose.service")
        if service not in (client, client + "-entry", client + "-deepseek"):
            continue
        if service in selected:
            raise runtime.RuntimeFailure("ambiguous_legacy_container")
        selected[service] = item
    if client not in selected or client + "-entry" not in selected:
        raise runtime.RuntimeFailure("legacy_container_missing")
    volumes = {}
    for name, target in (("home_volume", "/home/opencode"), ("workspace_volume", "/workspace")):
        matches = [m for m in selected[client]["mounts"] if m["Destination"] == target]
        expected = PROJECT + "_" + client + ("-home" if name == "home_volume" else "-workspace")
        if len(matches) != 1 or matches[0]["Type"] != "volume" or matches[0].get("Name") != expected:
            raise runtime.RuntimeFailure("unexpected_legacy_volume_mapping")
        volumes[name] = expected
    consumers = {}
    for name in volumes.values():
        consumers[name] = [{"id": item["id"], "running": item["running"],
                            "project": (item["labels"] or {}).get("com.docker.compose.project")}
                           for item in containers("volume=" + name)]
    # Do not serialize environment variables, host bind paths or secret mounts.
    return {"client": client, "legacy": volumes, "containers": {
        service: {key: item[key] for key in ("id", "name", "image_id", "state", "running")}
        for service, item in selected.items()}, "consumers": consumers}


def stopped(info):
    return not any(item["running"] for item in info["containers"].values()) and not any(
        item["running"] for values in info["consumers"].values() for item in values)



def verify_handoff(info, imported):
    """Only the account's exact Agent and file Gateway may use the imported volumes."""
    if any(item["running"] for item in info["containers"].values()):
        raise runtime.RuntimeFailure("migration_old_runtime_check_failed")
    rid, uid = runtime.check_id(imported["runtime_id"]), runtime.check_id(imported["uid"])
    records = containers("label=com.docker.compose.project=px-" + rid)
    expected = {}
    for service in ("agent", "gateway"):
        matching = [item for item in records
                    if (item.get("labels") or {}).get("com.docker.compose.service") == service]
        if len(matching) != 1 or not matching[0]["running"]:
            raise runtime.RuntimeFailure("migration_new_agent_missing")
        item = matching[0]
        labels = item.get("labels") or {}
        if (labels.get(runtime.MANAGED) != "true" or labels.get("peixian.runtime_id") != rid
                or labels.get("peixian.uid") != uid):
            raise runtime.RuntimeFailure("migration_new_agent_owner_mismatch")
        expected[service] = item
    for field, destination in (("home_volume", "/home/opencode"), ("workspace_volume", "/workspace")):
        volume = info["legacy"][field]
        # The established template gives the Gateway workspace access for file management.
        services = ("agent",) if field == "home_volume" else ("agent", "gateway")
        for service in services:
            mounts = [item for item in expected[service]["mounts"] if item.get("Destination") == destination]
            if (len(mounts) != 1 or mounts[0].get("Type") != "volume"
                    or mounts[0].get("Name") != volume or mounts[0].get("RW") is not True):
                raise runtime.RuntimeFailure("migration_new_agent_volume_mismatch")
        writers = {item["id"] for item in info["consumers"].get(volume, []) if item["running"]}
        if writers != {expected[service]["id"] for service in services}:
            raise runtime.RuntimeFailure("migration_unexpected_volume_writer")
    return {"old_containers_stopped": True, "only_expected_runtime_uses_volumes": True,
            "agent_id": expected["agent"]["id"], "gateway_id": expected["gateway"]["id"], "runtime_id": rid,
            "home_consumers": [expected["agent"]["id"]],
            "workspace_consumers": [expected[service]["id"] for service in ("agent", "gateway")]}


def verify_archive(path):
    actual = []
    with tarfile.open(path, "r:") as archive:
        names = set()
        for member in archive:
            if member.name in names:
                raise runtime.RuntimeFailure("snapshot_duplicate_member")
            names.add(member.name)
            if member.name == "manifest.json":
                continue
            relative = Path(member.name)
            if not member.name.startswith("data/") or relative.is_absolute() or ".." in relative.parts:
                raise runtime.RuntimeFailure("snapshot_unsafe_member")
            record = {"path": member.name[5:], "mode": member.mode, "uid": member.uid, "gid": member.gid}
            if member.isfile():
                value = hashlib.sha256()
                with archive.extractfile(member) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        value.update(chunk)
                record.update(type="file", size=member.size, sha256=value.hexdigest())
            elif member.isdir():
                record.update(type="directory")
            elif member.issym():
                record.update(type="symlink", target=member.linkname)
            else:
                raise runtime.RuntimeFailure("snapshot_unsupported_member")
            actual.append(record)
        declared = json.load(archive.extractfile("manifest.json"))
    actual.sort(key=lambda item: item["path"])
    if declared != actual:
        raise runtime.RuntimeFailure("snapshot_manifest_mismatch")
    return {"sha256": digest(path), "manifest_sha256": hashlib.sha256(runtime.json_bytes(actual)).hexdigest(),
            "files": sum(item["type"] == "file" for item in actual), "entries": len(actual)}


def archive_volume(volume, image, target):
    temporary = target.with_suffix(".partial")
    args = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit", "64", "--memory", "256m", "--cpus", "0.5",
            "--label", "peixian.console.snapshot=true",
            "--mount", "type=volume,source=" + volume + ",target=/source,readonly",
            "--entrypoint", "python3", image, "-c", SNAPSHOT]
    with temporary.open("xb") as output:
        if os.name == "posix":
            os.fchmod(output.fileno(), 0o600)
        result = subprocess.run(args, stdout=output, stderr=subprocess.PIPE, timeout=900, check=False)
    if result.returncode != 0:
        raise runtime.RuntimeFailure("snapshot_read_failed")
    os.replace(temporary, target)
    return verify_archive(target)


def snapshot(root, client, *, require_stopped=False):
    before = inventory(client)
    if require_stopped and not stopped(before):
        raise runtime.RuntimeFailure("legacy_or_volume_writer_still_running")
    identity = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    target = runtime.inside(root, root / "migrations" / client / identity)
    target.mkdir(parents=True, exist_ok=False)
    runtime.write_json(target / "snapshot.json", {"status": "preparing", "id": identity, "client": client})
    hashes = {}
    try:
        for name, volume in before["legacy"].items():
            hashes[name] = archive_volume(volume, before["containers"][client]["image_id"], target / (name + ".tar"))
        after = inventory(client)
        offline = stopped(before) and stopped(after)
        if require_stopped and not offline:
            raise runtime.RuntimeFailure("snapshot_writer_started")
        report = {"status": "passed", "id": identity, "client": client, "offline": offline,
                  "inventory": after, "archives": hashes}
        runtime.write_json(target / "snapshot.json", report)
        runtime.write_json(target / "snapshot.sha256.json", {"sha256": digest(target / "snapshot.json")})
        return target, report
    except Exception:
        runtime.write_json(target / "snapshot.json", {"status": "failed", "id": identity, "client": client})
        raise


def verify_snapshot(path):
    path = Path(path)
    report = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    declared = json.loads((path / "snapshot.sha256.json").read_text(encoding="utf-8"))
    if report.get("status") != "passed" or declared != {"sha256": digest(path / "snapshot.json")}:
        raise runtime.RuntimeFailure("snapshot_report_mismatch")
    if set(report.get("archives", {})) not in ({"home_volume", "workspace_volume"}, {"home_volume", "workspace_volume", "files_volume"}):
        raise runtime.RuntimeFailure("snapshot_archive_set_invalid")
    for name in report["archives"]:
        if verify_archive(path / (name + ".tar")) != report["archives"][name]:
            raise runtime.RuntimeFailure("snapshot_archive_mismatch")
    return report


def session_inventory(fetch):
    # This same function runs in the host and container probes. Only counts and
    # stable digests leave a probe; message bodies are never printed or saved.
    import hashlib
    import json
    import re
    sessions = fetch("/session?directory=%2Fworkspace&limit=100000")
    if not isinstance(sessions, list) or len(sessions) >= 100000:
        raise ValueError("migration_session_inventory_limit")
    result = {}
    for item in sessions:
        sid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", sid) or sid in result:
            raise ValueError("migration_session_inventory_invalid")
        messages = fetch("/session/" + sid + "/message?directory=%2Fworkspace")
        if not isinstance(messages, list):
            raise ValueError("migration_message_inventory_invalid")
        raw = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        result[sid] = {"count": len(messages), "sha256": hashlib.sha256(raw).hexdigest()}
    return {"ids": sorted(result), "messages": result, "message_count": sum(item["count"] for item in result.values())}


SESSION_PROBE = inspect.getsource(session_inventory) + r"""
import base64,json,sys,urllib.request
value=json.load(sys.stdin)
if 'password_file' in value:
 password=open(value['password_file']).read().rstrip('\r\n')
 headers={'Authorization':'Basic '+base64.b64encode((value['username']+':'+password).encode()).decode()}
else:
 headers={'X-Peixian-Key':value['key']}
def fetch(path):
 with urllib.request.urlopen(urllib.request.Request(value['url']+path,headers=headers),timeout=30) as response:
  return json.load(response)
print(json.dumps(session_inventory(fetch),sort_keys=True,separators=(',',':')))
"""


def old_sessions(client):
    password = (ROOT / ".secrets" / (client + ".password")).read_text(encoding="utf-8").rstrip("\r\n")
    url = "http://127.0.0.1:" + ("14091" if client == "client-a" else "14092")
    with httpx.Client(base_url=url, trust_env=False, timeout=30, auth=(client, password)) as api:
        def fetch(path):
            response = api.get(path)
            response.raise_for_status()
            return response.json()
        return session_inventory(fetch)


def old_session_snapshot(info):
    client = info["client"]
    value = runtime.command(["docker", "exec", "-i", info["containers"][client]["id"], "python3", "-c", SESSION_PROBE],
        data=runtime.json_bytes({"url": "http://127.0.0.1:4096", "username": client,
                                 "password_file": "/run/secrets/opencode-password"}), timeout=300)
    return json.loads(value)


def stop_legacy(info):
    client = info["client"]
    entry = info["containers"][client + "-entry"]
    if entry["running"]:
        docker("stop", "--time", "30", entry["id"], timeout=60)
    agent = info["containers"][client]
    captured = None
    if agent["running"]:
        deadline = time.monotonic() + 300
        probe = ("import base64,json,urllib.request;"
                 "p=open('/run/secrets/opencode-password').read().rstrip('\\r\\n');"
                 "h={'Authorization':'Basic '+base64.b64encode((" + repr(client + ":") + "+p).encode()).decode()};"
                 "r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:4096/session/status?directory=%2Fworkspace',headers=h),timeout=10);"
                 "print(json.dumps(json.load(r)))")
        while True:
            current = json.loads(docker("exec", agent["id"], "python3", "-c", probe, timeout=20))
            if isinstance(current, dict) and all(isinstance(item, dict) and item.get("type") == "idle" for item in current.values()):
                break
            if time.monotonic() >= deadline:
                raise runtime.RuntimeFailure("legacy_sessions_still_busy")
            time.sleep(5)
        captured = old_session_snapshot(info)
    for service in (client + "-deepseek", client):
        if service in info["containers"] and info["containers"][service]["running"]:
            docker("stop", "--time", "30", info["containers"][service]["id"], timeout=60)
    if not stopped(inventory(client)):
        raise runtime.RuntimeFailure("legacy_stop_unconfirmed")
    return captured


def start_legacy(info):
    client = info["client"]
    for service in (client + "-deepseek", client, client + "-entry"):
        if service in info["containers"] and info["containers"][service]["running"]:
            docker("start", info["containers"][service]["id"], timeout=60)
    for _ in range(30):
        try:
            old_sessions(client)
            return
        except (httpx.HTTPError, ValueError):
            time.sleep(2)
    raise runtime.RuntimeFailure("legacy_restart_health_failed")


def api_call(api, method, path, **kwargs):
    kwargs["headers"] = {**kwargs.pop("headers", {}), "X-Peixian-Protocol": "2"}
    response = api.request(method, "/internal/worker/" + path, **kwargs)
    if response.status_code not in (200, 202):
        raise runtime.RuntimeFailure("migration_control_api_failed")
    return response.json()


def account_password(client):
    folder = ROOT / ".secrets"
    runtime.protect_root(folder)
    path = folder / ("console-" + client + ".password")
    if not path.exists():
        runtime.write_secret(path, secrets.token_urlsafe(24))
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if len(value) < 16 or any(char in value for char in "\r\n\0"):
        raise runtime.RuntimeFailure("migration_password_invalid")
    return value


def private_sessions(manager, imported, key):
    url = "http://px-" + runtime.check_id(imported["runtime_id"]) + "-gateway:8080"
    value = manager.docker_run("exec", "-i", manager.control_container, "python3", "-c", SESSION_PROBE,
                               data=runtime.json_bytes({"url": url, "key": key}), timeout=300)
    return json.loads(value)


def verify_migrated_sessions(existing, current):
    if (not set(existing["ids"]).issubset(current["ids"]) or
            any(current["messages"].get(sid) != existing["messages"][sid] for sid in existing["ids"])):
        raise runtime.RuntimeFailure("migration_session_message_digest_changed")


def rollback(manager, api, journal, path):
    imported = journal.get("imported")
    managed_files = None
    if imported:
        rid = runtime.check_id(imported["runtime_id"])
        state = manager.state(rid)
        if state is None:
            pending = manager.directory(rid) / "pending.json"
            state = json.loads(pending.read_text()) if pending.is_file() else None
        if manager.running(rid):
            if state is None:
                raise runtime.RuntimeFailure("new_runtime_stop_requires_inspection")
            compose = runtime.inside(manager.directory(rid), Path(state["compose"]))
            if manager.state(rid) is not None:
                key = (compose.parent / "private/gateway-token").read_text(encoding="utf-8")
                manager.wait_idle({"runtime_id": rid, "private": {"gateway_key": key}}, lambda: None)
            manager.stop_checked(rid, compose)
        if manager.running(rid):
            raise runtime.RuntimeFailure("new_runtime_stop_unconfirmed")
        if state is not None:
            config = json.loads(runtime.inside(manager.directory(rid), Path(state["compose"])).read_text(encoding="utf-8"))
            managed_files = config["volumes"]["files"]["name"]
        # A complete host observation and current version authorize release.
        status = api_call(api, "GET", "legacy-status/" + imported["uid"])
        components, complete = manager.components(imported)
        mutation = manager.mutation_state(rid)
        if not complete or mutation != "idle" or any(value != "stopped" for value in components.values()):
            raise runtime.RuntimeFailure("legacy_rollback_stop_observation_incomplete")
        observation_id = uuid.uuid4().hex
        api_call(api, "POST", "reconcile", json={"observation_id": observation_id,
            "runtime_id": rid, "state_version": status["state_version"], "host_boot_id": worker.host_boot_id(),
            "observed_at": int(time.time()), "components": components, "mutation_state": mutation,
            "complete": True, "evidence_ref": uuid.uuid4().hex})
        # Persist the exact request before sending. An unknown response must be
        # reconciled using this same operation; do not invent a second rollback.
        body = {"uid": imported["uid"], "snapshot_id": verify_snapshot(Path(journal["snapshot"]))["id"],
                "cleanup_confirmed": True, "observation_id": observation_id,
                "expected_state_version": status["state_version"], "operation_id": uuid.uuid4().hex}
        prior = journal.get("rollback_request")
        if prior is not None:
            body = prior
        else:
            journal["rollback_request"] = body
            runtime.write_json(path, journal)
        api_call(api, "POST", "legacy-rollback", json=body)
    if imported or stopped(inventory(journal["client"])):
        saved, report = snapshot(manager.root, journal["client"], require_stopped=True)
        if managed_files is not None:
            if any(item["running"] for item in containers("volume=" + managed_files)):
                raise runtime.RuntimeFailure("managed_files_writer_still_running")
            report["archives"]["files_volume"] = archive_volume(managed_files,
                journal["before"]["containers"][journal["client"]]["image_id"], saved / "files_volume.tar")
            report["retained_managed_files_volume"] = managed_files
            runtime.write_json(saved / "snapshot.json", report)
            runtime.write_json(saved / "snapshot.sha256.json", {"sha256": digest(saved / "snapshot.json")})
        journal["rollback_snapshot"] = str(saved)
    else:
        journal["rollback_snapshot_skipped"] = "old_stop_failed_before_import"
    runtime.write_json(path, journal)
    # Keep all new files/sessions in the shared volumes. Never restore over them.
    start_legacy(journal["before"])
    journal["status"] = "rolled_back"
    runtime.write_json(path, journal)



def retry_import(api, client, imported, snapshot_id, permitted):
    if imported.get("status") != "failed":
        return False
    if not permitted:
        raise runtime.RuntimeFailure("migration_retry_requires_explicit_flag")
    if not stopped(inventory(client)):
        raise runtime.RuntimeFailure("migration_retry_requires_stopped_sources")
    result = api_call(api, "POST", "legacy-retry", json={"uid": imported["uid"],
                      "snapshot_id": snapshot_id, "legacy_stopped": True})
    if result.get("uid") != imported["uid"] or result.get("runtime_id") != imported["runtime_id"]:
        raise runtime.RuntimeFailure("migration_retry_identity_mismatch")
    return True


def migrate(manager, api, client, model_ids, *, retry_failed=False):
    before = inventory(client)
    if any(item["running"] and item["project"] != PROJECT for values in before["consumers"].values() for item in values):
        raise runtime.RuntimeFailure("legacy_volume_has_foreign_writer")
    existing = old_sessions(client)
    directory = manager.root / "migrations" / client
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("migration-" + uuid.uuid4().hex + ".json")
    journal = {"status": "preparing", "client": client, "before": before, "old_session_ids": existing["ids"], "old_sessions": existing}
    runtime.write_json(path, journal)
    try:
        captured = stop_legacy(before)
        if captured is not None:
            existing = captured
            journal.update(old_session_ids=existing["ids"], old_sessions=existing)
            runtime.write_json(path, journal)
        saved, evidence = snapshot(manager.root, client, require_stopped=True)
        verify_snapshot(saved)
        journal.update(snapshot=str(saved), status="snapshotted")
        runtime.write_json(path, journal)
        # Two independent reads must agree before a new agent writes to the source volumes.
        checked, repeated = snapshot(manager.root, client, require_stopped=True)
        if any(evidence["archives"][key]["manifest_sha256"] != repeated["archives"][key]["manifest_sha256"]
               for key in evidence["archives"]):
            raise runtime.RuntimeFailure("offline_source_digest_changed")
        journal["prebind_verification"] = str(checked)
        imported = api_call(api, "POST", "legacy-import", json={"username": client, "password": account_password(client),
            "model_ids": model_ids, "legacy": before["legacy"],
            "snapshot": {"id": evidence["id"], "sha256": digest(saved / "snapshot.json")}})
        runtime.check_id(imported["uid"])
        runtime.check_id(imported["runtime_id"])
        journal.update(imported=imported, status="imported")
        runtime.write_json(path, journal)
        if retry_import(api, client, imported, evidence["id"], retry_failed):
            journal["retried_failed_import"] = True
            runtime.write_json(path, journal)
        runner = worker.Worker(api, manager)
        for _ in range(40):
            state = api_call(api, "GET", "legacy-status/" + imported["uid"])
            if state["status"] == "ready" and state["revision"] == state["desired"]:
                break
            if state["status"] == "failed":
                raise runtime.RuntimeFailure("new_runtime_failed")
            runner.once()
            time.sleep(1)
        else:
            raise runtime.RuntimeFailure("new_runtime_not_ready")
        local = manager.state(imported["runtime_id"])
        if local is None or local.get("paused"):
            raise runtime.RuntimeFailure("new_runtime_local_state_missing")
        release = runtime.inside(manager.directory(imported["runtime_id"]), Path(local["compose"])).parent
        key = (release / "private/gateway-token").read_text(encoding="utf-8")
        manager.verify({"runtime_id": imported["runtime_id"], "private": {"gateway_key": key}}, local["revision"])
        current = private_sessions(manager, imported, key)
        verify_migrated_sessions(existing, current)
        journal.update(new_session_ids=current["ids"], new_sessions=current,
                       session_message_digest_match=True)
        runtime.write_json(path, journal)
        handoff = verify_handoff(inventory(client), imported)
        workspace = archive_volume(before["legacy"]["workspace_volume"], before["containers"][client]["image_id"],
                                   path.with_name(path.stem + "-workspace-after.tar"))
        if workspace["manifest_sha256"] != evidence["archives"]["workspace_volume"]["manifest_sha256"]:
            raise runtime.RuntimeFailure("migration_workspace_digest_changed")
        journal.update(status="passed", new_session_ids=current["ids"], new_sessions=current,
                       postbind_workspace=workspace, old_entry_stopped=True, handoff=handoff)
        runtime.write_json(path, journal)
        return path
    except Exception as error:
        journal["failure_code"] = error.code if isinstance(error, runtime.RuntimeFailure) else "migration_operation_failed"
        journal["status"] = "failed"
        runtime.write_json(path, journal)
        rollback(manager, api, journal, path)
        raise runtime.RuntimeFailure("migration_failed_rolled_back") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "snapshot", "verify", "migrate", "rollback"))
    parser.add_argument("--client", choices=CLIENTS, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Explicitly retry this fixed legacy account after a completed rollback")
    parser.add_argument("--require-stopped", action="store_true")
    parser.add_argument("--path", type=Path)
    parser.add_argument("--model-id", action="append", default=[])
    parser.add_argument("--state-root", type=Path, default=ROOT / ".runtime/console")
    parser.add_argument("--control-url", default="http://127.0.0.1:14090")
    parser.add_argument("--key-file", type=Path, default=ROOT / ".secrets/console-worker.key")
    args = parser.parse_args()
    if args.action in ("migrate", "rollback") and not args.execute:
        print(json.dumps({"status": "plan", "client": args.client,
                          "sequence": ["stop old entry/relay/agent", "offline snapshot and compare", "import fixed volumes",
                                       "wait for managed runtime", "verify sessions", "preserve all data on rollback"],
                          "requires": "--execute"}))
        return
    manager = runtime.RuntimeManager(args.state_root)
    if args.action == "inventory":
        result = inventory(args.client)
        path = manager.root / "migrations" / args.client / "inventory.json"
        runtime.write_json(path, result)
        print(json.dumps({"status": "passed", "inventory": str(path), "offline": stopped(result)}))
        return
    if args.action == "snapshot":
        path, result = snapshot(manager.root, args.client, require_stopped=args.require_stopped)
        print(json.dumps({"status": "passed", "snapshot": str(path), "offline": result["offline"]}))
        return
    if args.action == "verify":
        if args.path is None:
            parser.error("--path is required for verify")
        path = runtime.inside(manager.root, args.path)
        result = verify_snapshot(path)
        if result["client"] != args.client:
            raise runtime.RuntimeFailure("snapshot_account_mismatch")
        print(json.dumps({"status": "passed", "offline": result["offline"]}))
        return
    from urllib.parse import urlsplit
    address = urlsplit(args.control_url)
    if (address.scheme not in ("http", "https") or address.hostname not in ("127.0.0.1", "localhost", "::1") or
            address.username or address.password or address.path not in ("", "/") or address.query or address.fragment):
        raise runtime.RuntimeFailure("control_api_must_be_local")
    key = args.key_file.read_text(encoding="utf-8").rstrip("\r\n")
    if len(key) < 32 or any(char in key for char in "\r\n\0"):
        raise runtime.RuntimeFailure("worker_key_invalid")
    with worker.host_lock(manager.root), httpx.Client(base_url=args.control_url,
        headers={"X-Worker-Key": key}, timeout=60, trust_env=False, follow_redirects=False) as api:
        if args.action == "migrate":
            path = migrate(manager, api, args.client, args.model_id, retry_failed=args.retry_failed)
        else:
            if args.path is None:
                parser.error("--path is required for rollback")
            path = runtime.inside(manager.root, args.path)
            journal = json.loads(path.read_text(encoding="utf-8"))
            if journal["client"] != args.client:
                raise runtime.RuntimeFailure("migration_account_mismatch")
            rollback(manager, api, journal, path)
        print(json.dumps({"status": "passed", "journal": str(path)}))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('{"status":"interrupted","data_preserved":true}')
        raise SystemExit(1) from None
    except Exception as error:
        code = error.code if isinstance(error, runtime.RuntimeFailure) else "migration_operation_failed"
        print(json.dumps({"status": "failed", "code": code, "data_preserved": True}))
        raise SystemExit(1) from None
