"""Explicit local lifecycle for a generated AI application. Never deletes volumes."""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
from config import ROOT, load, names

def command(values, *, cwd=ROOT, capture=False):
    result = subprocess.run([str(x) for x in values], cwd=cwd, check=False,
                            capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError("Command failed: " + Path(str(values[0])).name)
    return result.stdout if capture else None

def local_directory(root, name):
    base = (Path(root) / "framework").resolve()
    path = base / name
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("Local state and credential directories cannot be links")
    path.mkdir(mode=0o700, exist_ok=True)
    if path.resolve().parent != base:
        raise ValueError("Local directory escaped the project")
    return path

def secure_directory(path):
    if os.name == "nt":
        identity = command(["whoami", "/user", "/fo", "csv", "/nh"], capture=True)
        sid = re.search(r"S-1-\d+(?:-\d+)+", identity)
        if sid is None:
            raise ValueError("Could not determine the current Windows security identity")
        command(["icacls", path, "/inheritance:r", "/grant:r", "*" + sid.group(0) + ":(OI)(CI)F"], capture=True)
    else:
        path.chmod(0o700)

def ownership(profile, root=ROOT):
    location = os.path.normcase(str(Path(root).resolve()))
    return {"peixian.deployment": profile["project_id"],
            "ai-framework.source-root": hashlib.sha256(location.encode("utf-8")).hexdigest()}

def check_existing(profile, root=ROOT):
    expected = ownership(profile, root)
    ids = names(profile)
    containers = command(["docker", "ps", "-a", "--filter", "name=^/" + ids["console"] + "$",
                          "--format", "{{.ID}}"], capture=True).split()
    volumes = command(["docker", "volume", "ls", "--filter", "name=^" + ids["data_volume"] + "$",
                       "--format", "{{.Name}}"], capture=True).split()
    for kind, values in (("container", containers), ("volume", volumes)):
        if not values:
            continue
        records = json.loads(command(["docker", kind, "inspect", *values], capture=True))
        for item in records:
            labels = (item.get("Config", {}).get("Labels") if kind == "container" else item.get("Labels")) or {}
            if any(labels.get(key) != value for key, value in expected.items()):
                raise ValueError("Deployment name already belongs to another project directory; no resources were changed")

def compose(profile, root=ROOT):
    identifiers = names(profile)
    private = (Path(root) / "framework/.secrets").resolve()
    port = profile["console_port"]
    return {
        "name": profile["project_id"],
        "services": {"console": {
            "container_name": identifiers["console"], "image": identifiers["control_image"],
            "labels": ownership(profile, root),
            "user": "10001:10001", "init": True, "read_only": True,
            "restart": "unless-stopped", "cpus": 1.0, "mem_limit": "512m", "pids_limit": 128,
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/tmp:rw,nosuid,nodev,size=128m,mode=1777"],
            "ports": [f"127.0.0.1:{port}:8080"],
            "environment": {
                "CONTROL_DATA": "/data", "CONTROL_KEY_FILE": "/run/secrets/control-key",
                "WORKER_KEY_FILE": "/run/secrets/worker-key", "ADMIN_PASSWORD_FILE": "/run/secrets/admin-password",
                "CONSOLE_ORIGINS": f"http://127.0.0.1:{port},http://localhost:{port}",
                "CONSOLE_COOKIE_NAME": identifiers["cookie"], "RUNTIME_NAMESPACE": profile["project_id"],
                "MAX_RUNTIMES": str(profile["max_runtimes"])},
            "volumes": ["control-data:/data"],
            "secrets": [{"source": key, "target": key} for key in ("control-key", "worker-key", "admin-password")],
            "healthcheck": {
                "test": ["CMD", "python", "-c",
                         "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"],
                "interval": "10s", "timeout": "5s", "start_period": "20s", "retries": 6},
            "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}}},
        "volumes": {"control-data": {"name": identifiers["data_volume"], "labels": ownership(profile, root)}},
        "secrets": {key: {"file": (private / filename).as_posix()} for key, filename in (
            ("control-key", "console-control.key"), ("worker-key", "console-worker.key"),
            ("admin-password", "console-admin.password"))}
    }

def initialize(profile, root=ROOT):
    state = local_directory(root, ".runtime")
    identity = state / "project.json"
    expected = {"project_id": profile["project_id"]}
    if identity.is_symlink() or (identity.exists() and json.loads(identity.read_text()) != expected):
        raise ValueError("Initialized project identity cannot be changed; create a new project directory")
    if not identity.exists():
        with identity.open("x", encoding="utf-8") as output:
            json.dump(expected, output)
    private = local_directory(root, ".secrets")
    secure_directory(private)
    factories = {
        "console-control.key": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "console-worker.key": lambda: secrets.token_urlsafe(48),
        "console-admin.password": lambda: secrets.token_urlsafe(24)}
    for name, create in factories.items():
        path = private / name
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Credential files cannot be links")
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if len(value) < 24 or any(c in value for c in "\r\n\0"):
                raise ValueError("Invalid existing credential; file was preserved")
            if name == "console-control.key" and len(base64.urlsafe_b64decode(value)) != 32:
                raise ValueError("Invalid existing encryption key; file was preserved")
            continue
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(create() + "\n")
    target = state / "compose.json"
    if target.is_symlink():
        raise ValueError("Compose output cannot be a link")
    target.write_text(json.dumps(compose(profile, root), indent=2) + "\n", encoding="utf-8")
    return target

def worker_args(profile, root=ROOT, *, once=False):
    folder = Path(root) / "framework"
    ids = names(profile)
    result = [sys.executable, Path(root) / "deploy/peixian/console-worker.py",
              "--namespace", profile["project_id"],
              "--control-url", f"http://127.0.0.1:{profile['console_port']}",
              "--control-container", ids["console"],
              "--state-root", folder / ".runtime/worker",
              "--key-file", folder / ".secrets/console-worker.key",
              "--agent-image", ids["agent_image"], "--gateway-image", ids["gateway_image"],
              "--max-runtimes", str(profile["max_runtimes"])]
    return result + (["--once"] if once else [])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "init", "build", "up", "status", "stop", "worker"))
    parser.add_argument("--bun", default=os.getenv("BUN_EXECUTABLE", "bun"))
    parser.add_argument("--once", action="store_true", help="Worker: process at most one job")
    args = parser.parse_args()
    profile = load()
    ids = names(profile)
    if args.action == "doctor":
        print(json.dumps({"project": profile, "deployment": ids,
                          "tools": {tool: bool(shutil.which(tool)) for tool in ("git", "docker", "npm")},
                          "bun": bool(shutil.which(args.bun) or Path(args.bun).is_file()),
                          "scope": "configuration_and_tool_presence_only"}, ensure_ascii=True))
        return
    if args.action == "init":
        initialize(profile)
        print("Initialized independent credentials. Administrator: admin")
        print("Initial password file: " + str(ROOT / "framework/.secrets/console-admin.password"))
        return
    if args.action == "build":
        check_existing(profile)
        frontend = ROOT / "packages/peixian-console"
        command([args.bun, "run", "typecheck"], cwd=frontend)
        command([args.bun, "run", "build"], cwd=frontend)
        for dockerfile, image in (("services/peixian-control/Gateway.Dockerfile", ids["gateway_image"]),
                                  ("deploy/peixian/Managed.Dockerfile", ids["agent_image"]),
                                  ("services/peixian-control/Dockerfile", ids["control_image"])):
            command(["docker", "build", "-f", dockerfile, "-t", image, "."])
        return
    target = ROOT / "framework/.runtime/compose.json"
    if not target.is_file():
        raise ValueError("Run init before lifecycle operations")
    identity = json.loads((ROOT / "framework/.runtime/project.json").read_text())
    if identity != {"project_id": profile["project_id"]}:
        raise ValueError("Project identity changed after initialization")
    if json.loads(target.read_text()) != compose(profile):
        raise ValueError("Profile changed; run init to regenerate the deployment definition")
    check_existing(profile)
    if args.action == "worker":
        command(worker_args(profile, once=args.once))
        return
    if args.action == "up":
        with socket.socket() as probe:
            probe.settimeout(1)
            occupied = probe.connect_ex(("127.0.0.1", profile["console_port"])) == 0
        if occupied:
            raise ValueError("Console port is occupied; no process was stopped. Use status to inspect an existing deployment")
        engine = command(["docker", "info", "--format", "{{.OSType}}"], capture=True)
        if engine.strip() != "linux":
            raise ValueError("A Docker Linux Engine is required")
    actions = {"up": ["up", "-d", "--no-build", "--pull", "never", "--wait"],
               "status": ["ps", "--all"], "stop": ["stop"]}
    command(["docker", "compose", "-f", target, *actions[args.action]])

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
