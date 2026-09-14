"""Verify a new, empty Compose copy without altering the main project.

Uses loopback ports 14093/14094. The copy is stopped afterwards; its containers,
volumes, networks, and generated Compose file are retained for inspection.
No model requests, package builds, or data deletion are performed.
"""

import base64
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit
import uuid

import httpx


ROOT = Path(__file__).resolve().parent
IMAGE = "peixian-opencode:1.18.30-r1"
VERSION = "1.18.30"
CLIENTS = ("client-a", "client-b")
SERVICES = (*CLIENTS, "client-a-entry", "client-b-entry")
PORTS = {"client-a": 14093, "client-b": 14094}


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" else None
        if value and urlsplit(value).path.lower().endswith((".js", ".css")):
            self.urls.append(value)


def cold_config(config, project):
    if config.get("name") != project or set(config.get("services", {})) != set(SERVICES):
        raise ValueError("Expected exactly four services in the unique cold project")
    for name, service in config["services"].items():
        if service.get("image") != IMAGE or service.get("container_name"):
            raise ValueError("Cold services must use the approved image and Compose-generated container names")
        if name in CLIENTS:
            if service.get("ports"):
                raise ValueError("Agent services must not publish ports")
            continue
        ports = service.get("ports", [])
        if len(ports) != 1 or ports[0].get("target") != 4096 or ports[0].get("protocol", "tcp") != "tcp":
            raise ValueError("Expected one TCP 4096 port on each entry service")
        ports[0]["host_ip"] = "127.0.0.1"
        ports[0]["published"] = str(PORTS[name.removesuffix("-entry")])
    resources = {}
    for kind in ("volumes", "networks"):
        resources[kind] = []
        for value in config.get(kind, {}).values():
            name = value.get("name", "")
            if value.get("external") or not name.startswith(project + "_"):
                raise ValueError("Cold resources must be new and confined to the unique project")
            resources[kind].append(name)
    if len(resources["volumes"]) != 4 or len(set(resources["volumes"])) != 4:
        raise ValueError("Expected four distinct new persistent volumes")
    return config, resources


class ColdStart:
    def __init__(self):
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:12]
        self.project = "peixian-opencode-cold-" + suffix
        self.directory = ROOT / ".runtime" / ("cold-" + suffix)
        self.compose_file = self.directory / "compose.json"
        self.output = ROOT / "evidence/cold-start.json"
        self.passwords = {}
        self.resources = {"volumes": [], "networks": []}
        self.started = False
        self.report = {
            "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
            "image_id": None, "compose_sha256": None, "project": self.project,
            "expected_version": VERSION, "scope": "A separate Compose copy created from absent volumes; this does not assert that the main project's volumes were unused",
            "checks": [], "runtime": {}, "volumes": [], "networks": [],
            "not_verified": ["Real model inference", "Browser rendering", "First startup history of the main project"],
        }

    def redact(self, value):
        value = str(value)
        for name, password in self.passwords.items():
            value = value.replace(password, "[REDACTED]")
            value = value.replace(base64.b64encode(f"{name}:{password}".encode()).decode(), "[REDACTED]")
        return value

    def save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_suffix(".json.tmp")
        temporary.write_text(self.redact(json.dumps(self.report, ensure_ascii=False, indent=2)) + "\n", encoding="utf-8")
        temporary.replace(self.output)

    def check(self, name, passed, detail=None):
        item = {"name": name, "passed": bool(passed)}
        if detail is not None:
            item["evidence"] = detail
        self.report["checks"].append(item)
        self.save()
        print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)
        if not passed:
            raise AssertionError(name)

    def docker(self, *args, timeout=180):
        result = subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"Docker {args[0]} failed: {self.redact(result.stderr)[:600]}")
        return result.stdout.strip()

    def compose(self, *args, timeout=180):
        return self.docker("compose", "-p", self.project, "-f", str(self.compose_file), *args, timeout=timeout)

    def names(self, kind, name=None):
        args = [kind, "ls", "--format", "{{.Name}}"]
        if name:
            args += ["--filter", f"name={name}"]
        else:
            args += ["--filter", f"label=com.docker.compose.project={self.project}"]
        return self.docker(*args).splitlines()

    def prepare(self):
        self.report["compose_sha256"] = hashlib.sha256((ROOT / "compose.yaml").read_bytes()).hexdigest()
        try:
            for name in CLIENTS:
                password = (ROOT / ".secrets" / f"{name}.password").read_text(encoding="utf-8").rstrip("\r\n")
                if len(password) < 16 or any(char in password for char in "\r\n\0"):
                    raise ValueError("Invalid per-client password file")
                self.passwords[name] = password
        except (OSError, UnicodeError) as error:
            raise ValueError("Unable to read initialized per-client credentials") from error
        self.check("Two valid distinct credentials", len(set(self.passwords.values())) == 2)
        image = json.loads(self.docker("image", "inspect", IMAGE))[0]
        self.report["image_id"] = image["Id"]
        self.check("Current image is linux/amd64", image.get("Os") == "linux" and image.get("Architecture") == "amd64")
        config = json.loads(self.docker("compose", "-p", self.project, "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"))
        config, self.resources = cold_config(config, self.project)
        self.check("Main Compose unchanged while generating copy", hashlib.sha256((ROOT / "compose.yaml").read_bytes()).hexdigest() == self.report["compose_sha256"])
        before = {"containers": self.docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}").splitlines(),
                  "volumes": self.names("volume"), "networks": self.names("network")}
        for plural, singular in (("volumes", "volume"), ("networks", "network")):
            for name in self.resources[plural]:
                if name in self.names(singular, name) and name not in before[plural]:
                    before[plural].append(name)
        self.report["before_creation"] = before
        self.report["expected_resources"] = self.resources
        self.check("Unique project has no preexisting containers, volumes, or networks", not any(before.values()), before)
        for port in PORTS.values():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(("127.0.0.1", port))
            self.check(f"Loopback port {port} is available", True)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.compose_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        self.report["copy_config"] = self.compose_file.relative_to(ROOT).as_posix()
        self.report["copy_config_sha256"] = hashlib.sha256(self.compose_file.read_bytes()).hexdigest()
        self.report["created_from_absent_volumes"] = True
        self.save()

    def inspect(self):
        containers = {}
        for name in SERVICES:
            identifier = self.compose("ps", "-q", name)
            if not identifier or "\n" in identifier:
                raise ValueError(f"Expected one cold container for {name}")
            container = json.loads(self.docker("inspect", identifier))[0]
            containers[name] = container
            self.report["runtime"][name] = {"container_id": identifier, "image_id": container["Image"], "platform": "linux/amd64"}
            self.check(f"{name}: uses accepted image in cold project", container["Image"] == self.report["image_id"] and container["Config"]["Labels"].get("com.docker.compose.project") == self.project)
        for name in self.resources["volumes"]:
            value = json.loads(self.docker("volume", "inspect", name))[0]
            self.report["volumes"].append({"name": value["Name"], "driver": value["Driver"], "created_at": value.get("CreatedAt"), "project": value.get("Labels", {}).get("com.docker.compose.project")})
            self.check("Volume belongs to cold project: " + name, value.get("Labels", {}).get("com.docker.compose.project") == self.project)
        networks = {}
        for name in self.resources["networks"]:
            value = json.loads(self.docker("network", "inspect", name))[0]
            networks[name] = value
            self.report["networks"].append({"name": value["Name"], "id": value["Id"], "internal": value["Internal"], "project": value.get("Labels", {}).get("com.docker.compose.project")})
        actual_volumes = []
        for name in CLIENTS:
            mounts = [m for m in containers[name]["Mounts"] if m["Type"] == "volume"]
            self.check(f"{name}: fresh HOME and workspace volumes", {m["Destination"] for m in mounts} == {"/home/opencode", "/workspace"} and len(mounts) == 2 and all(m["Name"] in self.resources["volumes"] for m in mounts))
            actual_volumes.extend(m["Name"] for m in mounts)
            attached = containers[name]["NetworkSettings"]["Networks"]
            self.check(f"{name}: agent has only one internal network and no published ports", len(attached) == 1 and all(networks.get(net, {}).get("Internal") is True for net in attached) and not containers[name]["HostConfig"].get("PortBindings"))
            entry = containers[name + "-entry"]
            self.check(f"{name}-entry: only cold loopback port is published", entry["HostConfig"].get("PortBindings") == {"4096/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(PORTS[name])}]})
        self.check("Four distinct volumes match the cold configuration", len(set(actual_volumes)) == 4 and set(actual_volumes) == set(self.resources["volumes"]))
        return containers

    def http_checks(self):
        for name in CLIENTS:
            base_url = f"http://127.0.0.1:{PORTS[name]}"
            with httpx.Client(base_url=base_url, auth=(name, self.passwords[name]), trust_env=False, timeout=30) as client:
                response = client.get("/global/health")
                response.raise_for_status()
                health = response.json()
                self.check(f"{name}: cold health and version", health.get("healthy") is True and health.get("version") == VERSION, health)
                other = "client-b" if name == "client-a" else "client-a"
                for label, auth in (("anonymous", None), ("wrong password", (name, "synthetic-invalid")), ("other client", (other, self.passwords[other]))):
                    response = client.get("/session", params={"directory": "/workspace"}, auth=auth)
                    self.check(f"{name}: rejects {label}", response.status_code in (401, 403), {"status": response.status_code})
                response = client.get("/session", params={"directory": "/workspace"})
                response.raise_for_status()
                self.check(f"{name}: initial session list is empty", response.json() == [])
                response = client.get("/provider")
                response.raise_for_status()
                self.check(f"{name}: no connected providers", response.json().get("connected") == [])
                response = client.get("/", headers={"Cache-Control": "no-cache"})
                self.check(f"{name}: local HTML is served", response.status_code == 200 and "text/html" in response.headers.get("content-type", ""))
                parser = Assets()
                parser.feed(response.text)
                candidates = []
                for value in parser.urls:
                    url = urljoin(base_url + "/", value)
                    parsed = urlsplit(url)
                    if parsed.scheme == "http" and parsed.netloc == urlsplit(base_url).netloc:
                        candidates.append(url)
                fetched = []
                for url in dict.fromkeys(candidates):
                    asset = client.get(url, headers={"Cache-Control": "no-cache"})
                    content_type = asset.headers.get("content-type", "")
                    good = asset.status_code == 200 and bool(asset.content) and ("javascript" in content_type or "text/css" in content_type)
                    fetched.append({"path": urlsplit(url).path, "status": asset.status_code, "content_type": content_type, "bytes": len(asset.content)})
                    if good:
                        break
                self.check(f"{name}: a real local JavaScript or CSS asset is served", bool(fetched) and good, fetched)

    def network_checks(self, containers):
        script = """import json,pathlib,socket,sys
routes=pathlib.Path('/proc/net/route').read_text()
ipv6=pathlib.Path('/proc/net/ipv6_route').read_text()
results={}
for name,host,port in [('self','127.0.0.1',4096),('peer',sys.argv[1],4096),('public','1.1.1.1',443)]:
    try:
        with socket.create_connection((host,port),timeout=2):
            results[name]=True
    except OSError:
        results[name]=False
print(json.dumps({'routes':routes,'ipv6_routes':ipv6,'connections':results}))
"""
        for name in CLIENTS:
            other = "client-b" if name == "client-a" else "client-a"
            peer = next(iter(containers[other]["NetworkSettings"]["Networks"].values()))["IPAddress"]
            state = json.loads(self.docker("exec", containers[name]["Id"], "python3", "-c", script, peer))
            routes = [line.split() for line in state["routes"].splitlines()[1:]]
            ipv6 = [line.split() for line in state["ipv6_routes"].splitlines()]
            has_default = any(len(row) > 3 and row[1] == "00000000" and int(row[3], 16) & 1 for row in routes)
            has_default6 = any(len(row) > 8 and row[0] == "0" * 32 and row[1] == "00" and int(row[8], 16) & 1 for row in ipv6)
            self.check(f"{name}: no active default route", not has_default and not has_default6, {"ipv4_default": bool(has_default), "ipv6_default": bool(has_default6)})
            self.check(f"{name}: self reachable, peer and public blocked", state["connections"] == {"self": True, "peer": False, "public": False}, state["connections"])

    def log_checks(self, containers):
        rules = {
            "npm_install_failure": re.compile(r"(?:npm|reify|dependency install).*(?:error|failed|failure)|(?:error|failed|failure).*(?:npm|reify|registry\.npm)", re.I),
            "download_failure": re.compile(r"(?:download|fetch).*(?:error|failed|failure)|(?:error|failed|failure).*(?:download|registry\.npm)", re.I),
            "network_dependency_error": re.compile(r"EAI_AGAIN|ENETUNREACH|ETIMEDOUT|ENOTFOUND|ECONNREFUSED|FailedToOpenSocket", re.I),
        }
        for name in CLIENTS:
            result = subprocess.run(["docker", "logs", containers[name]["Id"]], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            if result.returncode:
                raise RuntimeError("Unable to inspect cold agent logs")
            logs = result.stdout + result.stderr
            matches = {label: sum(bool(pattern.search(line)) for line in logs.splitlines()) for label, pattern in rules.items()}
            self.check(f"{name}: no dependency download errors in startup logs", not any(matches.values()), {"matching_lines": matches, "log_sha256": hashlib.sha256(logs.encode()).hexdigest(), "log_bytes": len(logs.encode())})

    def run(self):
        self.prepare()
        self.started = True
        print("Starting only the unique cold project with the existing image...", flush=True)
        self.compose("up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "180", timeout=240)
        containers = self.inspect()
        self.http_checks()
        self.network_checks(containers)
        time.sleep(3)
        self.log_checks(containers)
        image = json.loads(self.docker("image", "inspect", IMAGE))[0]
        self.check("Image and main Compose remained unchanged", image["Id"] == self.report["image_id"] and hashlib.sha256((ROOT / "compose.yaml").read_bytes()).hexdigest() == self.report["compose_sha256"])

    def stop(self):
        self.report["cleanup"] = {"action": "stop only", "attempted": self.started, "volumes_removal_requested": False}
        if not self.started:
            return
        self.compose("stop", "--timeout", "30", timeout=90)
        running = self.docker("ps", "-q", "--filter", f"label=com.docker.compose.project={self.project}").splitlines()
        self.report["cleanup"]["stopped"] = not running
        self.check("Cold copy stopped; main project was not targeted", not running)
        self.report["cleanup"]["retained_volumes"] = self.names("volume")


def main():
    verification = ColdStart()
    success = False
    # Replace any earlier pass before reading credentials or talking to Docker.
    verification.save()
    try:
        verification.run()
        success = True
    except (Exception, KeyboardInterrupt) as error:
        verification.report["error"] = {"type": type(error).__name__, "message": verification.redact(error)}
        print("FAILED: " + verification.redact(error), file=sys.stderr)
    finally:
        try:
            verification.stop()
        except (Exception, KeyboardInterrupt) as error:
            success = False
            verification.report["cleanup_error"] = {"type": type(error).__name__, "message": verification.redact(error)}
            print("Cold project stop failed: " + verification.redact(error), file=sys.stderr)
        verification.report["status"] = "passed" if success else "failed"
        verification.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        verification.save()
        print("Evidence: evidence/cold-start.json")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
