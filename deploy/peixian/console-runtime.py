"""Host-only lifecycle operations for isolated Peixian account runtimes.

No Docker socket is mounted into application containers. All commands are argv
arrays and every durable path is beneath the explicitly configured state root.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import time
import uuid


MANAGED = "peixian.console.managed"
DEPLOYMENT = "peixian.deployment"
NAMESPACE = re.compile(r"[a-z][a-z0-9-]{0,15}")
ID = re.compile(r"[a-f0-9]{32}")
SLUG = re.compile(r"[a-z][a-z0-9_-]{0,63}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
DIGEST = re.compile(r"[a-f0-9]{64}")
MAX_PACKAGE = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024


class RuntimeFailure(Exception):
    def __init__(self, code, *, rolled_back=False, cleanup_confirmed=False):
        self.code, self.rolled_back = code, rolled_back
        self.cleanup_confirmed = cleanup_confirmed
        super().__init__(code)


class Deferred(Exception):
    pass


def check_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise RuntimeFailure("invalid_runtime_identity")
    return value


def check_namespace(value):
    if value is not None and (not isinstance(value, str) or not NAMESPACE.fullmatch(value)):
        raise RuntimeFailure("invalid_deployment_namespace")
    return value


def project_name(runtime_id, namespace=None):
    return (check_namespace(namespace) or "px") + "-" + check_id(runtime_id)


def deployment_tag(namespace):
    return {} if namespace is None else {DEPLOYMENT: check_namespace(namespace)}


def root_identity(root, namespace, control_container):
    marker = root / "deployment.json"
    if root.is_symlink() or marker.is_symlink():
        raise RuntimeFailure("deployment_root_identity_invalid")
    if namespace is None:
        if marker.exists():
            raise RuntimeFailure("deployment_root_identity_mismatch")
        return None
    expected = {DEPLOYMENT: namespace, "control_container": control_container, "version": 1}
    if marker.is_file():
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise RuntimeFailure("deployment_root_identity_invalid") from None
        if value != expected:
            raise RuntimeFailure("deployment_root_identity_mismatch")
        return None
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise RuntimeFailure("deployment_root_unmarked_nonempty")
    return expected


def inside(root, candidate):
    root, candidate = Path(root).resolve(), Path(candidate).resolve()
    if not candidate.is_relative_to(root):
        raise RuntimeFailure("path_outside_worker_root")
    return candidate


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("xb") as handle:
        if os.name == "posix":
            os.fchmod(handle.fileno(), 0o600)
        handle.write(json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_secret(path, value):
    if not isinstance(value, str) or len(value) < 16 or any(c in value for c in "\r\n\0"):
        raise RuntimeFailure("invalid_private_credential")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        if os.name == "posix":
            os.fchmod(handle.fileno(), 0o600)
        handle.write(value)


def command(args, *, data=None, timeout=240, allowed=(0,)):
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeFailure("host_command_unavailable") from None
    if result.returncode not in allowed:
        # Docker errors can contain mount paths or app logs: do not persist or print them.
        raise RuntimeFailure("host_command_failed")
    return result.stdout.decode("utf-8", errors="replace")



def host_identity():
    if os.name == "posix":
        return str(os.getuid())
    import csv
    rows = list(csv.reader(io.StringIO(command(["whoami", "/user", "/fo", "csv", "/nh"]))))
    sid = rows[0][-1] if rows else ""
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise RuntimeFailure("host_acl_identity_unavailable")
    return sid


def protect_root(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise RuntimeFailure("worker_root_must_not_be_symlink")
    if os.name == "posix":
        os.chmod(root, 0o700)
        if shutil.which("setfacl") is None:
            raise RuntimeFailure("linux_acl_required_install_acl_package")
        return
    sid = host_identity()
    command(["icacls", str(root), "/inheritance:r", "/grant:r",
             f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], timeout=30)


def grant_container_read(root):
    if os.name == "posix":
        for directory, directories, files in os.walk(root):
            os.chmod(directory, 0o700)
            for name in files:
                os.chmod(Path(directory) / name, 0o600)
        command(["setfacl", "-R", "-m", "u:10001:rX,m::rX", str(root)], timeout=30)


def unpack_plugin(data, expected, target):
    import zipfile
    if len(data) > MAX_PACKAGE or hashlib.sha256(data).hexdigest() != expected["digest"]:
        raise RuntimeFailure("plugin_digest_mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(item.file_size for item in members) > MAX_EXPANDED:
                raise RuntimeFailure("plugin_package_limit")
            names = set()
            for item in members:
                name = item.orig_filename
                relative = PurePosixPath(name)
                mode = item.external_attr >> 16
                if (name != item.filename or not name or relative.is_absolute() or ".." in relative.parts or
                        "\\" in name or ":" in name or "\0" in name or
                        stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or
                        name.casefold().rstrip("/") in names):
                    raise RuntimeFailure("unsafe_plugin_archive")
                names.add(name.casefold().rstrip("/"))
            manifest = json.loads(archive.read("manifest.json"))
            entry = manifest.get("entry", "entry.mjs")
            if (manifest.get("id") != expected["id"] or manifest.get("version") != expected["version"] or
                    entry != expected["manifest"].get("entry", "entry.mjs") or
                    not entry.endswith(".mjs") or entry.casefold() not in names or
                    manifest.get("opencode_version", "1.18.30") != "1.18.30"):
                raise RuntimeFailure("plugin_manifest_mismatch")
            target = Path(target)
            target.mkdir(parents=True, exist_ok=False)
            for item in members:
                destination = inside(target, target.joinpath(*PurePosixPath(item.filename).parts))
                if item.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as handle:
                    handle.write(archive.read(item))
            # The gateway probes a stable entry.mjs, including optional named test.
            if entry != "entry.mjs":
                if (target / "entry.mjs").exists():
                    raise RuntimeFailure("plugin_entry_collision")
                (target / "entry.mjs").write_text(
                    "export { default } from " + json.dumps("./" + entry) + ";\n"
                    "export * from " + json.dumps("./" + entry) + ";\n", encoding="utf-8")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        raise RuntimeFailure("invalid_plugin_archive") from None


AGENT_HEALTH = (
    "import base64,json,urllib.request;"
    "p=open('/run/secrets/opencode-password').read().rstrip('\\r\\n');"
    "h={'Authorization':'Basic '+base64.b64encode(('opencode:'+p).encode()).decode()};"
    "r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:4096/global/health',headers=h),timeout=3);"
    "d=json.load(r);assert d.get('healthy') and d.get('version')=='1.18.30'"
)
GATEWAY_HEALTH = (
    "import json,urllib.request;"
    "p=open('/run/secrets/gateway-token').read().rstrip('\\r\\n');"
    "r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/health',headers={'X-Peixian-Key':p}),timeout=3);"
    "assert json.load(r).get('ok')"
)
RELAY_HEALTH = "import json,urllib.request;assert json.load(urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=3)).get('ok')"

# Executed only in the control container, with secret values supplied on stdin.
CONTROL_GET = """import json,sys,urllib.request
v=json.load(sys.stdin)
try:
 r=urllib.request.urlopen(urllib.request.Request(v['url'],headers={'X-Peixian-Key':v['key']}),timeout=8)
 b=r.read(2097153)
 if len(b)>2097152: raise ValueError()
 print(json.dumps(json.loads(b)))
except Exception:
 print('{"error":"private_gateway_unavailable"}')
 sys.exit(2)
"""


def compose_spec(spec, release, *, agent_image, gateway_image, namespace=None):
    runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
    project = project_name(runtime_id, namespace)
    if namespace is not None and spec["private"].get("legacy") is not None:
        raise RuntimeFailure("namespaced_legacy_volumes_forbidden")
    release = Path(release).resolve()
    revision = spec["revision"]
    if type(revision) is not int or revision < 1:
        raise RuntimeFailure("invalid_revision")
    labels = {MANAGED: "true", "peixian.runtime_id": runtime_id, "peixian.uid": uid, "peixian.revision": str(revision), **deployment_tag(namespace)}
    common = {
        "user": "10001:10001", "init": True, "restart": "unless-stopped", "read_only": True,
        "pull_policy": "never",
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"], "pids_limit": 128,
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=128m,mode=1777"], "stop_grace_period": "30s",
        "labels": labels, "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }

    def bind(source, target):
        return {"type": "bind", "source": str(release / source), "target": target, "read_only": True,
                "bind": {"create_host_path": False}}

    def health(code, period="60s"):
        return {"test": ["CMD", "python3", "-c", code], "interval": "10s", "timeout": "5s",
                "start_period": period, "retries": 12}

    def volume(source, target, readonly=False):
        return {"type": "volume", "source": source, "target": target, "read_only": readonly}

    legacy = spec["private"].get("legacy") or {}
    if not isinstance(legacy, dict) or set(legacy) - {"home_volume", "workspace_volume", "files_volume"}:
        raise RuntimeFailure("invalid_legacy_volume_mapping")
    volumes = {}
    for name in ("home", "workspace", "files"):
        external = legacy.get(name + "_volume")
        if external is not None:
            if not isinstance(external, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", external):
                raise RuntimeFailure("invalid_legacy_volume_name")
            volumes[name] = {"name": external, "external": True}
        else:
            volumes[name] = {"name": project + "-" + name, "labels": labels}

    services = {
        "agent": {
            **common, "image": agent_image, "platform": "linux/amd64", "working_dir": "/workspace",
            "cpus": 2.0, "mem_limit": "2g", "pids_limit": 256,
            "environment": {"PEIXIAN_MANAGED_ROOT": "/managed"},
            "volumes": [volume("home", "/home/opencode"), volume("workspace", "/workspace"),
                        volume("files", "/files", True), bind("agent", "/managed"),
                        bind("private/opencode-password", "/run/secrets/opencode-password")],
            "networks": ["internal"], "healthcheck": health(AGENT_HEALTH),
        },
        "gateway": {
            **common, "image": gateway_image, "platform": "linux/amd64", "cpus": 0.5, "mem_limit": "512m",
            "entrypoint": ["python3", "-m", "uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"],
            "environment": {"MANAGED_ROOT": "/managed", "ACCOUNT_ID": uid, "WORKSPACE": "/workspace",
                            "FILES_ROOT": "/files", "OPENCODE_URL": "http://agent:4096",
                            "INTERNAL_TOKEN_FILE": "/run/secrets/gateway-token",
                            "OPENCODE_PASSWORD_FILE": "/run/secrets/opencode-password"},
            "volumes": [volume("workspace", "/workspace"), volume("files", "/files"),
                        bind("gateway", "/managed"), bind("private/gateway-token", "/run/secrets/gateway-token"),
                        bind("private/opencode-password", "/run/secrets/opencode-password")],
            "networks": {"internal": {}, "management": {"aliases": [project + "-gateway"]}},
            "depends_on": {"agent": {"condition": "service_healthy"}},
            "healthcheck": health(GATEWAY_HEALTH), "sysctls": {"net.ipv4.ip_forward": "0"},
        },
        "model-relay": {
            **common, "image": gateway_image, "platform": "linux/amd64", "cpus": 0.5, "mem_limit": "128m",
            "entrypoint": ["python3", "-m", "uvicorn", "gateway.model_relay:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"],
            "environment": {"MANAGED_ROOT": "/managed", "ACCOUNT_ID": uid},
            "volumes": [bind("relay", "/managed")],
            "networks": ["internal", "egress"], "healthcheck": health(RELAY_HEALTH, "10s"),
            "sysctls": {"net.ipv4.ip_forward": "0"},
        },
    }
    return {
        "name": project, "services": services, "volumes": volumes,
        "networks": {
            "internal": {"name": project + "-internal", "internal": True, "labels": labels},
            "management": {"name": project + "-management", "internal": True, "labels": labels},
            "egress": {"name": project + "-egress", "internal": False, "labels": labels},
        },
    }


class RuntimeManager:
    namespace = None

    def __init__(self, root, *, control_container="peixian-console",
                 agent_image="peixian-opencode:1.18.30-managed-r1",
                 gateway_image="peixian-gateway:console-r1", maximum=4, namespace=None):
        self.namespace = check_namespace(namespace)
        self.root = Path(root).absolute()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", control_container):
            raise RuntimeFailure("invalid_control_container")
        if not 1 <= maximum <= 32:
            raise RuntimeFailure("invalid_runtime_capacity")
        self.control_container, self.agent_image, self.gateway_image = control_container, agent_image, gateway_image
        self.maximum = maximum
        identity = root_identity(self.root, self.namespace, self.control_container)
        protect_root(self.root)
        self.root = self.root.resolve()
        if identity is not None:
            write_json(self.root / "deployment.json", identity)
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeFailure("docker_required")
        if os.getenv("DOCKER_HOST", "").startswith(("tcp:", "ssh:")):
            raise RuntimeFailure("local_docker_required")
        context = json.loads(self.docker_run("context", "inspect"))[0]
        endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not endpoint.startswith(("npipe://", "unix://")):
            raise RuntimeFailure("local_docker_required")

    def docker_run(self, *args, data=None, timeout=240, allowed=(0,)):
        return command([self.docker, *args], data=data, timeout=timeout, allowed=allowed)

    def project_name(self, runtime_id):
        return project_name(runtime_id, self.namespace)

    def check_owner(self, labels, runtime_id, uid=None):
        if self.namespace is None:
            return
        if (not isinstance(labels, dict) or labels.get(DEPLOYMENT) != self.namespace
                or labels.get(MANAGED) != "true" or labels.get("peixian.runtime_id") != runtime_id
                or not ID.fullmatch(str(labels.get("peixian.uid", "")))
                or (uid is not None and labels.get("peixian.uid") != uid)):
            raise RuntimeFailure("deployment_resource_owner_mismatch")

    def check_control(self):
        if self.namespace is None:
            return
        labels = json.loads(self.docker_run("inspect", "--format", "{{json .Config.Labels}}", self.control_container))
        if not isinstance(labels, dict) or labels.get(DEPLOYMENT) != self.namespace:
            raise RuntimeFailure("deployment_control_owner_mismatch")

    def check_compose(self, source, runtime_id):
        if self.namespace is None:
            return
        project = self.project_name(runtime_id)
        if (source.get("name") != project or set(source.get("services", {})) != {"agent", "gateway", "model-relay"}
                or set(source.get("volumes", {})) != {"home", "workspace", "files"}
                or set(source.get("networks", {})) != {"internal", "management", "egress"}):
            raise RuntimeFailure("deployment_compose_mismatch")
        uid = check_id(source["services"]["agent"].get("labels", {}).get("peixian.uid"))
        for service in source["services"].values():
            self.check_owner(service.get("labels"), runtime_id, uid)
        for group in ("networks", "volumes"):
            for name, item in source[group].items():
                if item.get("name") != project + "-" + name or item.get("external"):
                    raise RuntimeFailure("deployment_compose_resource_mismatch")
                self.check_owner(item.get("labels"), runtime_id, uid)
        self.running(runtime_id, uid=uid)

    def directory(self, runtime_id):
        return inside(self.root, self.root / "runtimes" / check_id(runtime_id))

    def compose(self, file, *args, timeout=240):
        # Infrastructure outlives every release. Compose must not recreate a network
        # to update revision labels while the control container is attached to it.
        if self.namespace is not None:
            inside(self.root, file)
        source = json.loads(Path(file).read_text(encoding="utf-8"))
        prefix = (self.namespace or "px") + "-"
        if not source["name"].startswith(prefix):
            raise RuntimeFailure("deployment_compose_mismatch")
        identity = check_id(source["name"][len(prefix):])
        self.check_compose(source, identity)
        directory = self.directory(identity)
        inside(directory, file)
        for group in ("networks", "volumes"):
            source[group] = {key: {"name": item["name"], "external": True} for key, item in source[group].items()}
        source["services"]["agent"].update(cpus=2.0, mem_limit="2g")
        source["services"]["gateway"].update(cpus=0.5, mem_limit="512m")
        source["services"]["model-relay"].update(cpus=0.5, mem_limit="128m")
        target = directory / "operations" / (Path(file).parent.name + "-compose.json")
        write_json(target, source)
        return self.docker_run("compose", "-f", str(target), *args, timeout=timeout)

    def ensure_networks(self, spec):
        identity, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        existing = set(self.docker_run("network", "ls", "--format", "{{.Name}}").split())
        for suffix in ("internal", "management", "egress"):
            name = self.project_name(identity) + "-" + suffix
            internal = suffix != "egress"
            if name not in existing:
                args = ["network", "create", "--driver", "bridge", "--label", MANAGED + "=true",
                        "--label", "peixian.runtime_id=" + identity, "--label", "peixian.uid=" + uid]
                if self.namespace is not None:
                    args.extend(("--label", DEPLOYMENT + "=" + self.namespace))
                if internal:
                    args.append("--internal")
                self.docker_run(*args, name)
            record = json.loads(self.docker_run("network", "inspect", name))[0]
            labels = record.get("Labels") or {}
            self.check_owner(labels, identity, uid)
            if (record.get("Name") != name or record.get("Internal") is not internal or
                    labels.get(MANAGED) != "true" or labels.get("peixian.runtime_id") != identity or
                    labels.get("peixian.uid") != uid):
                raise RuntimeFailure("runtime_network_owner_mismatch")

    def state(self, runtime_id):
        file = self.directory(runtime_id) / "state.json"
        if not file.exists():
            return None
        data = json.loads(file.read_text(encoding="utf-8"))
        if self.namespace is not None:
            if data.get(DEPLOYMENT) != self.namespace:
                raise RuntimeFailure("deployment_state_owner_mismatch")
            check_id(data.get("uid"))
        if data["runtime_id"] != runtime_id or data["uid"] is None:
            raise RuntimeFailure("invalid_local_runtime_state")
        return data

    def private_get(self, spec, endpoint):
        if endpoint not in ("/health", "/session/status", "/global/health", "/skill"):
            raise RuntimeFailure("invalid_private_probe")
        self.check_control()
        url = "http://" + self.project_name(spec["runtime_id"]) + "-gateway:8080" + endpoint
        text = self.docker_run("exec", "-i", self.control_container, "python3", "-c", CONTROL_GET,
                               data=json_bytes({"url": url, "key": spec["private"]["gateway_key"]}), timeout=15)
        result = json.loads(text)
        if not isinstance(result, list if endpoint == "/skill" else dict):
            raise RuntimeFailure("invalid_private_probe_response")
        return result

    def attach_control(self, runtime_id):
        self.check_control()
        network = self.project_name(runtime_id) + "-management"
        record = json.loads(self.docker_run("network", "inspect", network))[0]
        labels = record.get("Labels") or {}
        local = self.state(runtime_id) if self.namespace is not None else None
        self.check_owner(labels, runtime_id, local["uid"] if local else None)
        if (record.get("Name") != network or record.get("Internal") is not True or
                labels.get(MANAGED) != "true" or labels.get("peixian.runtime_id") != runtime_id):
            raise RuntimeFailure("management_network_owner_mismatch")
        attached = json.loads(self.docker_run("inspect", "--format", "{{json .NetworkSettings.Networks}}", self.control_container))
        if network not in attached:
            self.docker_run("network", "connect", network, self.control_container, timeout=30)

    def verify(self, spec, revision):
        self.attach_control(spec["runtime_id"])
        for _ in range(18):
            try:
                health = self.private_get(spec, "/health")
                native = self.private_get(spec, "/global/health")
                # This instance route initializes managed Config, Skills and Plugin services.
                skills = self.private_get(spec, "/skill")
                if (health.get("ok") is True and health.get("revision") == revision and
                        health.get("runtime_id") == spec["runtime_id"] and native.get("healthy") is True and
                        native.get("version") == "1.18.30" and isinstance(skills, list)):
                    return
            except (RuntimeFailure, ValueError):
                pass
            time.sleep(2)
        raise RuntimeFailure("runtime_revision_health_failed")

    def wait_idle(self, spec, heartbeat, *, seconds=300):
        deadline = time.monotonic() + seconds
        while True:
            heartbeat()
            status = self.private_get(spec, "/session/status")
            if all(isinstance(item, dict) and item.get("type") == "idle" for item in status.values()):
                return
            if time.monotonic() >= deadline:
                raise Deferred()
            time.sleep(min(5, max(0, deadline - time.monotonic())))

    def reconcile(self):
        failures = []
        directory = self.root / "runtimes"
        if not directory.is_dir():
            return failures
        for account in directory.iterdir():
            if not ID.fullmatch(account.name):
                continue
            try:
                value = self.state(account.name)
                if value is None or value.get("paused"):
                    continue
                active = self.running(account.name, uid=value["uid"]) if self.namespace is not None else self.running(account.name)
                if not active:
                    continue
                check_id(value["uid"])
                inside(account, Path(value["compose"]))
                self.attach_control(account.name)
            except (RuntimeFailure, ValueError, KeyError, OSError):
                failures.append("registered_runtime_network_reconcile_failed")
        return failures

    def capacity(self, runtime_id):
        ids = self.docker_run("ps", "--filter", "label=" + MANAGED + "=true",
                              "--filter", "label=com.docker.compose.service=agent", "--format", "{{.ID}}").split()
        records = json.loads(self.docker_run("inspect", *ids)) if ids else []
        if self.namespace is not None:
            if any((item["Config"].get("Labels") or {}).get(DEPLOYMENT) != self.namespace for item in records):
                raise RuntimeFailure("another_deployment_has_running_agents")
            records = [item for item in records if item["Config"]["Labels"].get(DEPLOYMENT) == self.namespace]
        others = {item["Config"]["Labels"].get("peixian.runtime_id") for item in records}
        others.discard(runtime_id)
        if len(others) >= self.maximum:
            raise RuntimeFailure("runtime_capacity_reached")
        info = json.loads(self.docker_run("info", "--format", "{{json .}}"))
        # Reserve the configured maximum: agent 2 GiB + gateway 512 MiB + relay 128 MiB.
        # Control gets 512 MiB and the host/engine keeps at least 1 GiB.
        required_memory = self.maximum * (2688 * 1024 * 1024) + 1536 * 1024 * 1024
        if type(info.get("MemTotal")) is not int or info["MemTotal"] < required_memory:
            raise RuntimeFailure("docker_memory_budget_exceeded")
        if type(info.get("NCPU")) is not int or info["NCPU"] < self.maximum * 3 + 1:
            raise RuntimeFailure("docker_cpu_budget_exceeded")

    def prepare(self, spec, download):
        if self.namespace is not None and spec["private"].get("legacy") is not None:
            raise RuntimeFailure("namespaced_legacy_volumes_forbidden")
        runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        revision = spec["revision"]
        if type(revision) is not int or revision < 1:
            raise RuntimeFailure("invalid_revision")
        directory = self.directory(runtime_id)
        directory.mkdir(parents=True, exist_ok=True)
        release = inside(directory, directory / "releases" / str(revision))
        digest = hashlib.sha256(json_bytes(spec)).hexdigest()
        publication = {"digest": digest, "uid": uid, "revision": revision, **deployment_tag(self.namespace)}
        if release.exists():
            if json.loads((release / "publication.json").read_text(encoding="utf-8")) != publication:
                raise RuntimeFailure("immutable_release_conflict")
            return release
        stage = directory / "releases" / (".staging-" + uuid.uuid4().hex)
        stage.mkdir(parents=True, exist_ok=False)
        for folder in ("agent/skills", "agent/loaders", "gateway/plugins", "relay", "private"):
            (stage / folder).mkdir(parents=True, exist_ok=True)
        config = json.loads(json.dumps(spec["config"]))
        config["plugin"] = []
        config["skills"] = {"paths": ["/managed/skills"]}
        tests = {}
        seen = set()
        for plugin in spec["plugins"]:
            if (not SLUG.fullmatch(plugin["id"]) or not VERSION.fullmatch(plugin["version"]) or
                    not DIGEST.fullmatch(plugin["digest"]) or plugin["id"] in seen or
                    not isinstance(plugin["options"], dict)):
                raise RuntimeFailure("invalid_published_plugin")
            seen.add(plugin["id"])
            relative = Path("plugins") / plugin["id"] / plugin["version"]
            unpack_plugin(download(plugin["digest"]), plugin, stage / "agent" / relative)
            shutil.copytree(stage / "agent" / relative, stage / "gateway" / relative)
            entry = "/managed/" + relative.as_posix() + "/entry.mjs"
            tests[plugin["id"]] = {"entry": entry, "options": plugin["options"]}
            loader = stage / "agent/loaders" / (plugin["id"] + ".mjs")
            loader.write_text(
                "import plugin from " + json.dumps("../" + relative.as_posix() + "/entry.mjs") + ";\n"
                "const options = " + json.dumps(plugin["options"], ensure_ascii=False) + ";\n"
                "export default async (context) => plugin(context, options);\n", encoding="utf-8")
            config["plugin"].append("file:///managed/loaders/" + plugin["id"] + ".mjs")
        for skill in spec["skills"]:
            check_id(skill["id"])
            if not all(isinstance(skill.get(key), str) for key in ("name", "description", "content")):
                raise RuntimeFailure("invalid_published_skill")
            target = stage / "agent/skills" / skill["id"] / "SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("---\nname: " + json.dumps(skill["name"], ensure_ascii=False) +
                              "\ndescription: " + json.dumps(skill["description"], ensure_ascii=False) +
                              "\n---\n" + skill["content"], encoding="utf-8")
        version = {"uid": uid, "runtime_id": runtime_id, "revision": revision, **deployment_tag(self.namespace)}
        write_json(stage / "agent/opencode.json", config)
        write_json(stage / "agent/revision.json", version)
        write_json(stage / "gateway/revision.json", version)
        write_json(stage / "gateway/plugin-tests.json", tests)
        write_json(stage / "relay/model-relay.json", {"models": spec["models"]})
        write_json(stage / "relay/revision.json", version)
        write_secret(stage / "private/gateway-token", spec["private"]["gateway_key"])
        write_secret(stage / "private/opencode-password", spec["private"]["agent_password"])
        write_json(stage / "publication.json", publication)
        # Compose paths point at the final immutable location, never the staging name.
        write_json(stage / "compose.json", compose_spec(spec, release, agent_image=self.agent_image, gateway_image=self.gateway_image, namespace=self.namespace))
        grant_container_read(stage)
        os.rename(stage, release)
        return release

    def ensure_volumes(self, spec, compose):
        project = self.project_name(spec["runtime_id"])
        if self.namespace is not None:
            if spec["private"].get("legacy") is not None:
                raise RuntimeFailure("namespaced_legacy_volumes_forbidden")
            self.check_compose(compose, spec["runtime_id"])
        for definition in compose["volumes"].values():
            name = definition["name"]
            if definition.get("external"):
                self.docker_run("volume", "inspect", name)
                consumers = self.docker_run("ps", "--filter", "volume=" + name, "--format", "{{.ID}}").split()
                if consumers:
                    records = json.loads(self.docker_run("inspect", *consumers))
                    if any(item["Config"]["Labels"].get("com.docker.compose.project") != project for item in records):
                        raise RuntimeFailure("legacy_volume_still_in_use")
                continue
            found = self.docker_run("volume", "ls", "--filter", "name=^" + re.escape(name) + "$", "--format", "{{.Name}}").split()
            if found:
                record = json.loads(self.docker_run("volume", "inspect", name))[0]
                self.check_owner(record.get("Labels"), spec["runtime_id"], spec["uid"])
                if (record.get("Labels") or {}).get("peixian.runtime_id") != spec["runtime_id"]:
                    raise RuntimeFailure("volume_owner_mismatch")
            else:
                labels = ["--label", MANAGED + "=true", "--label", "peixian.runtime_id=" + spec["runtime_id"]]
                if self.namespace is not None:
                    labels.extend(("--label", DEPLOYMENT + "=" + self.namespace, "--label", "peixian.uid=" + spec["uid"]))
                self.docker_run("volume", "create", *labels, name)
            if self.namespace is not None:
                # Docker volume create can return a concurrently existing volume.
                record = json.loads(self.docker_run("volume", "inspect", name))[0]
                self.check_owner(record.get("Labels"), spec["runtime_id"], spec["uid"])
            # Recover an interrupted initialization only when the owned volume is still empty.
            # Imported volumes took the branch above and can never reach this operation.
            self.docker_run("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                            "--security-opt", "no-new-privileges:true", "--memory", "64m", "--cpus", "0.5", "--pids-limit", "32",
                            "--cap-drop", "ALL", "--cap-add", "CHOWN", "--user", "0:0",
                            "--mount", "type=volume,source=" + name + ",target=/volume",
                            "--entrypoint", "python3", self.agent_image, "-c",
                            "import os,sys;s=os.stat('/volume');"
                            "sys.exit(0) if (s.st_uid,s.st_gid)==(10001,10001) else None;"
                            "assert s.st_uid==0 and not os.listdir('/volume');"
                            "os.chmod('/volume',0o700);os.chown('/volume',10001,10001)", timeout=30)

    def running(self, runtime_id, *, uid=None):
        project = self.project_name(runtime_id)
        args = ["ps", *(["-a"] if self.namespace is not None else []),
                "--filter", "label=com.docker.compose.project=" + project, "--format", "{{.ID}}"]
        ids = self.docker_run(*args).split()
        if self.namespace is not None and ids:
            records = json.loads(self.docker_run("inspect", *ids))
            services, owners = set(), set()
            for item in records:
                labels = item["Config"].get("Labels") or {}
                self.check_owner(labels, runtime_id, uid)
                service = labels.get("com.docker.compose.service")
                if (labels.get("com.docker.compose.project") != project
                        or service not in {"agent", "gateway", "model-relay"} or service in services):
                    raise RuntimeFailure("deployment_container_owner_mismatch")
                services.add(service)
                owners.add(labels["peixian.uid"])
            if len(owners) != 1:
                raise RuntimeFailure("deployment_container_owner_mismatch")
            return [item["Id"] for item in records if item["State"]["Running"]]
        return ids

    def stop_checked(self, runtime_id, file):
        self.compose(file, "stop", timeout=90)
        if self.running(runtime_id):
            raise RuntimeFailure("runtime_stop_unconfirmed")

    def check_images(self):
        # Fail locally when images are absent; never pull at account creation.
        for image in (self.agent_image, self.gateway_image):
            result = json.loads(self.docker_run("image", "inspect", image))[0]
            if result.get("Os") != "linux" or result.get("Architecture") != "amd64":
                raise RuntimeFailure("runtime_image_platform_mismatch")

    def apply(self, job, spec, download, heartbeat):
        if self.namespace is not None and spec["private"].get("legacy") is not None:
            raise RuntimeFailure("namespaced_legacy_volumes_forbidden")
        runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        if job["uid"] != uid or job["revision"] != spec["revision"] or job["action"] not in {"provision", "apply", "pause", "resume"}:
            raise RuntimeFailure("job_spec_mismatch")
        previous = self.state(runtime_id)
        if previous and previous["uid"] != uid:
            raise RuntimeFailure("runtime_owner_mismatch")
        running = self.running(runtime_id, uid=uid) if self.namespace is not None else self.running(runtime_id)
        old_file = inside(self.directory(runtime_id), Path(previous["compose"])) if previous else None
        pending_file = self.directory(runtime_id) / "pending.json"
        if running and not previous:
            # Resume only a deployment this worker journaled before Compose started.
            pending = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.is_file() else {}
            if self.namespace is not None and pending.get(DEPLOYMENT) != self.namespace:
                raise RuntimeFailure("deployment_state_owner_mismatch")
            if pending.get("uid") != uid or pending.get("runtime_id") != runtime_id:
                raise RuntimeFailure("runtime_state_missing")
            old_file = inside(self.directory(runtime_id), Path(pending["compose"]))
            previous = {**pending, "paused": True}
        if previous and not previous.get("paused") and running:
            self.attach_control(runtime_id)
            self.wait_idle(spec, heartbeat)
        if job["action"] == "pause":
            if previous:
                self.stop_checked(runtime_id, old_file)
                write_json(self.directory(runtime_id) / "state.json", {**previous, "paused": True})
            return {"ok": True, "cleanup_confirmed": True}
        file = None
        attempted = False
        try:
            self.capacity(runtime_id)
            self.check_images()
            release = self.prepare(spec, download)
            file = release / "compose.json"
            config = json.loads(file.read_text(encoding="utf-8"))
            self.ensure_volumes(spec, config)
            self.ensure_networks(spec)
            heartbeat()
            write_json(pending_file, {
                "uid": uid, "runtime_id": runtime_id, "revision": spec["revision"], "compose": str(file),
                **deployment_tag(self.namespace),
            })
            attempted = True
            self.compose(file, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180", timeout=240)
            self.verify(spec, spec["revision"])
            write_json(self.directory(runtime_id) / "state.json", {
                "uid": uid, "runtime_id": runtime_id, "revision": spec["revision"], "compose": str(file), "paused": False,
                **deployment_tag(self.namespace),
            })
            return {"ok": True}
        except Exception as error:
            code = error.code if isinstance(error, RuntimeFailure) else "release_failed"
            if previous and not previous.get("paused"):
                try:
                    if attempted:
                        self.compose(old_file, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180", timeout=240)
                    self.verify(spec, previous["revision"])
                except (RuntimeFailure, ValueError):
                    pass
                else:
                    raise RuntimeFailure("release_failed_rolled_back", rolled_back=True) from None
            try:
                current = self.running(runtime_id)
                if current:
                    stop_file = file if attempted else old_file
                    if stop_file is None:
                        raise RuntimeFailure("runtime_stop_unconfirmed")
                    self.stop_checked(runtime_id, stop_file)
            except (RuntimeFailure, ValueError):
                raise RuntimeFailure("release_failed_cleanup_unconfirmed") from None
            # Only this branch has confirmed every project container is stopped.
            raise RuntimeFailure(code, cleanup_confirmed=True) from None
