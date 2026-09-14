"""Real HTTP and Docker isolation checks. Creates synthetic sessions/files only.

--lifecycle additionally stops, starts, and recreates client-a, preserving volumes.
No model is called. Browser and physical LAN acceptance are separate checks.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import subprocess
import sys
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
NAMES = ("client-a", "client-b")
PORTS = {"client-a": 14091, "client-b": 14092}
XDG = {
    "HOME": "/home/opencode",
    "XDG_CONFIG_HOME": "/home/opencode/.config",
    "XDG_DATA_HOME": "/home/opencode/.local/share",
    "XDG_CACHE_HOME": "/home/opencode/.cache",
    "XDG_STATE_HOME": "/home/opencode/.local/state",
}


class Verification:
    def __init__(self, args):
        self.args = args
        self.passwords = {name: (ROOT / ".secrets" / f"{name}.password").read_text(encoding="utf-8").rstrip("\r\n") for name in NAMES}
        if any(len(password) < 16 or any(char in password for char in "\r\n\0") for password in self.passwords.values()):
            raise ValueError("Password files must contain one value of at least 16 characters, with no internal CR/LF/NUL")
        if len(set(self.passwords.values())) != 2:
            raise ValueError("Client password files must contain distinct values")
        self.report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "run_id": uuid.uuid4().hex,
            "expected_version": args.version,
            "compose_sha256": hashlib.sha256((ROOT / "compose.yaml").read_bytes()).hexdigest(),
            "lifecycle_completed": False,
            "runtime": {},
            "checks": [],
            "not_verified": ["Real model inference and tool calls", "Browser rendering and separate browser profiles", "Access from a physical LAN client", "Proof that initial volumes were empty before first startup"],
        }
        if not args.lifecycle:
            self.report["not_verified"].append("Stop/start/recreate persistence (run with --lifecycle)")

    def redact(self, value):
        value = str(value)
        for name, password in self.passwords.items():
            value = value.replace(password, "[REDACTED]")
            value = value.replace(base64.b64encode(f"{name}:{password}".encode()).decode(), "[REDACTED]")
        return value

    def check(self, label, success, detail=None):
        item = {"name": label, "passed": bool(success)}
        if detail is not None:
            item["evidence"] = detail
        self.report["checks"].append(item)
        print(f"{'PASS' if success else 'FAIL'} {label}", flush=True)
        if not success:
            raise AssertionError(label)

    def docker(self, *args):
        result = subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=180)
        if result.returncode:
            raise RuntimeError(f"Docker {args[0]} failed: {self.redact(result.stderr)[:600]}")
        return result.stdout.strip()

    def compose(self, *args):
        return self.docker("compose", "-p", "peixian-opencode", "-f", str(ROOT / "compose.yaml"), *args)

    def container(self, name):
        identifier = self.compose("ps", "-q", name)
        if not identifier or "\n" in identifier:
            raise RuntimeError(f"Expected one running container for {name}")
        return json.loads(self.docker("inspect", identifier))[0]

    def python(self, identifier, script, *args):
        return json.loads(self.docker("exec", identifier, "python3", "-c", script, *args))

    async def request(self, client, method, path, **kwargs):
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def health(self, client, wait=False):
        deadline = time.monotonic() + (120 if wait else 0)
        while True:
            try:
                data = await self.request(client, "GET", "/global/health")
                if data.get("healthy") is True and data.get("version") == self.args.version:
                    return data
            except (httpx.HTTPError, ValueError):
                if not wait:
                    raise
            if time.monotonic() >= deadline:
                raise RuntimeError("Instance did not become healthy with the expected version")
            await asyncio.sleep(1)

    async def run(self):
        async with AsyncExitStack() as stack:
            clients = {name: await stack.enter_async_context(httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{PORTS[name]}", auth=(name, self.passwords[name]),
                trust_env=False, timeout=30,
            )) for name in NAMES}
            for name, client in clients.items():
                self.check(f"{name}: health/version", True, await self.health(client))
                response = await client.get("/", headers={"Cache-Control": "no-cache"})
                self.check(f"{name}: local HTML available", response.status_code == 200 and "text/html" in response.headers.get("content-type", ""))
                other = NAMES[1] if name == NAMES[0] else NAMES[0]
                for label, auth in [("anonymous", None), ("wrong password", (name, "synthetic-wrong-password")), ("other client's credentials", (other, self.passwords[other]))]:
                    response = await client.get("/session", params={"directory": "/workspace"}, auth=auth)
                    self.check(f"{name}: rejects {label}", response.status_code in (401, 403), {"status": response.status_code})

            containers = {name: self.container(name) for name in NAMES}
            entries = {name: self.container(f"{name}-entry") for name in NAMES}
            for name, container in {**containers, **{f"{name}-entry": entry for name, entry in entries.items()}}.items():
                image = json.loads(self.docker("image", "inspect", container["Image"]))[0]
                platform = f"{image['Os']}/{image['Architecture']}"
                if image.get("Variant"):
                    platform += "/" + image["Variant"]
                self.report["runtime"][name] = {"image_id": container["Image"], "platform": platform}
            self.inspect_isolation(containers, entries)
            sessions = await self.sessions_and_events(clients)
            marker_path = f".peixian-verification/{self.report['run_id']}.txt"
            markers = {name: f"synthetic:{name}:{uuid.uuid4().hex}" for name in NAMES}
            for name in NAMES:
                result = self.python(containers[name]["Id"],
                    "import json,pathlib,sys; p=pathlib.Path('/workspace')/sys.argv[1]; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(sys.argv[2],encoding='utf-8'); print(json.dumps({'written':True}))",
                    marker_path, markers[name])
                self.check(f"{name}: synthetic workspace file written", result.get("written"))
                await self.assert_file(clients[name], name, marker_path, markers[name])
            self.network_isolation(containers, entries)
            self.report["synthetic_records"] = {name: {"session_id": sessions[name]["id"], "file": marker_path, "content_sha256": hashlib.sha256(markers[name].encode()).hexdigest()} for name in NAMES}
            if self.args.lifecycle:
                await self.lifecycle(clients, containers, sessions, marker_path, markers)

    def inspect_isolation(self, containers, entries):
        volume_names = {}
        network_names = {}
        for name, container in containers.items():
            host = container["HostConfig"]
            mounts = container["Mounts"]
            env = dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
            safe = {
                "user": container["Config"].get("User"),
                "readonly_rootfs": host.get("ReadonlyRootfs"),
                "privileged": host.get("Privileged"),
                "cap_drop": host.get("CapDrop"),
                "security_opt": host.get("SecurityOpt"),
                "memory": host.get("Memory"), "nano_cpus": host.get("NanoCpus"), "pids_limit": host.get("PidsLimit"),
                "ports": host.get("PortBindings"),
                "mounts": [{"type": m["Type"], "destination": m["Destination"], "writable": m["RW"], "name": m.get("Name")} for m in mounts],
                "xdg": {key: env.get(key) for key in XDG},
            }
            self.check(f"{name}: ordinary user and hardened container", safe["user"] in ("10001", "10001:10001") and safe["readonly_rootfs"] and not safe["privileged"] and "ALL" in [x.upper() for x in (safe["cap_drop"] or [])] and any("no-new-privileges" in x for x in (safe["security_opt"] or [])) and not host.get("CapAdd"), safe)
            self.check(f"{name}: resource limits", safe["memory"] == 2 * 1024**3 and safe["nano_cpus"] == 2_000_000_000 and safe["pids_limit"] == 256)
            self.check(f"{name}: expected HOME/XDG", safe["xdg"] == XDG)
            bindings = host.get("PortBindings") or {}
            self.check(f"{name}: agent publishes no host ports", not bindings, bindings)
            volumes = {m["Destination"]: m for m in mounts if m["Type"] == "volume"}
            self.check(f"{name}: dedicated home and workspace volumes", set(volumes) == {"/home/opencode", "/workspace"} and all(m["RW"] for m in volumes.values()))
            volume_names[name] = {m["Name"] for m in volumes.values()}
            self.check(f"{name}: no host directory or Docker socket mounts", all(m["Type"] == "volume" or (m["Type"] == "bind" and m["Destination"].startswith("/run/secrets/") and not m["RW"]) or (m["Type"] == "tmpfs" and m["Destination"] == "/tmp") for m in mounts))
            self.check(f"{name}: isolated temporary filesystem", "/tmp" in (host.get("Tmpfs") or {}))
            network_names[name] = set(container["NetworkSettings"]["Networks"])
            self.check(f"{name}: one internal network", len(network_names[name]) == 1 and all(json.loads(self.docker("network", "inspect", network))[0].get("Internal") for network in network_names[name]))
            state = self.python(container["Id"], "import json,os,pathlib; print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'xdg':{k:os.environ.get(k) for k in " + repr(list(XDG)) + "},'routes':pathlib.Path('/proc/net/route').read_text()}))")
            self.check(f"{name}: runtime user and XDG match", state["uid"] == 10001 and state["gid"] == 10001 and state["xdg"] == XDG, {"uid": state["uid"], "gid": state["gid"], "xdg": state["xdg"]})
            self.report.setdefault("network_routes", {})[name] = state["routes"]
            routes = [line.split() for line in state["routes"].splitlines()[1:]]
            self.check(f"{name}: no active IPv4 default route", not any(len(route) > 3 and route[1] == "00000000" and int(route[3], 16) & 1 for route in routes))
        self.check("A/B share no persistent volume", not (volume_names[NAMES[0]] & volume_names[NAMES[1]]))
        self.check("A/B share no container network", not (network_names[NAMES[0]] & network_names[NAMES[1]]))

        entry_networks = {}
        for name, entry in entries.items():
            label = f"{name}-entry"
            host = entry["HostConfig"]
            config = entry["Config"]
            env = dict(item.split("=", 1) for item in config["Env"] if "=" in item)
            safe = {
                "user": config.get("User"),
                "readonly_rootfs": host.get("ReadonlyRootfs"),
                "privileged": host.get("Privileged"),
                "cap_drop": host.get("CapDrop"),
                "security_opt": host.get("SecurityOpt"),
                "sysctls": host.get("Sysctls"),
                "ports": host.get("PortBindings"),
                "upstream_host": env.get("UPSTREAM_HOST"),
                "upstream_port": env.get("UPSTREAM_PORT"),
                "entrypoint": config.get("Entrypoint"),
                "command": config.get("Cmd"),
                "mounts": [{"type": m["Type"], "destination": m["Destination"]} for m in entry["Mounts"]],
            }
            self.check(f"{label}: ordinary user and hardened container", safe["user"] in ("10001", "10001:10001") and safe["readonly_rootfs"] and not safe["privileged"] and "ALL" in [x.upper() for x in (safe["cap_drop"] or [])] and any("no-new-privileges" in x for x in (safe["security_opt"] or [])) and not host.get("CapAdd"), safe)
            self.check(f"{label}: only expected loopback port published", safe["ports"] == {"4096/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(PORTS[name])}]})
            self.check(f"{label}: no persistent volumes, secret mounts or password environment", all(m["Type"] == "tmpfs" and m["Destination"] == "/tmp" for m in entry["Mounts"]) and not any("PASSWORD" in key.upper() and value for key, value in env.items()) and not any(password in env.values() for password in self.passwords.values()))
            self.check(f"{label}: fixed upstream is its own agent", env.get("UPSTREAM_HOST") == name and env.get("UPSTREAM_PORT", "4096") == "4096")
            self.check(f"{label}: fixed TCP forwarder command", (config.get("Entrypoint") or []) + (config.get("Cmd") or []) == ["python3", "/opt/peixian/tcp-forward.py"])
            self.check(f"{label}: entry resource limits", host.get("Memory") == 128 * 1024**2 and host.get("NanoCpus") == 250_000_000 and host.get("PidsLimit") == 64)
            self.check(f"{label}: configured IPv4 forwarding disabled", (host.get("Sysctls") or {}).get("net.ipv4.ip_forward") == "0")
            state = self.python(entry["Id"], "import json,os,pathlib; print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'ip_forward':pathlib.Path('/proc/sys/net/ipv4/ip_forward').read_text().strip()}))")
            self.check(f"{label}: runtime UID and forwarding state", state == {"uid": 10001, "gid": 10001, "ip_forward": "0"}, state)
            attached = set(entry["NetworkSettings"]["Networks"])
            network_info = {network: json.loads(self.docker("network", "inspect", network))[0] for network in attached}
            internal = {network for network, info in network_info.items() if info.get("Internal")}
            external = attached - internal
            self.check(f"{label}: own internal plus one entry network", len(attached) == 2 and internal == network_names[name] and len(external) == 1, {"internal": sorted(internal), "entry": sorted(external)})
            entry_networks[name] = external
            for network, info in network_info.items():
                self.check(f"{label}: IPv6 disabled on {network}", not info.get("EnableIPv6"))
                expected = {entry["Id"], containers[name]["Id"]} if network in internal else {entry["Id"]}
                self.check(f"{label}: network contains only its own components ({network})", set(info.get("Containers", {})) == expected)
        self.check("A/B entries share no external network", not (entry_networks[NAMES[0]] & entry_networks[NAMES[1]]))

    async def sessions_and_events(self, clients):
        ready = {name: asyncio.Event() for name in NAMES}
        events = {name: [] for name in NAMES}
        async def collect(name):
            async with clients[name].stream("GET", "/global/event", timeout=None) as response:
                response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise RuntimeError("Expected an SSE response")
                ready[name].set()
                data = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    if not line and data:
                        events[name].append(json.loads("\n".join(data)))
                        data = []
        tasks = {name: asyncio.create_task(collect(name)) for name in NAMES}
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready.values())), timeout=30)
            sessions = {name: await self.request(clients[name], "POST", "/session", params={"directory": "/workspace"}, json={"title": f"SYNTHETIC-{name}-{self.report['run_id']}"}) for name in NAMES}
            self.check("A/B session IDs differ", sessions[NAMES[0]]["id"] != sessions[NAMES[1]]["id"])
            deadline = time.monotonic() + 20
            while not all(sessions[name]["id"] in json.dumps(events[name]) for name in NAMES) and time.monotonic() < deadline:
                for task in tasks.values():
                    if task.done():
                        await task
                        raise RuntimeError("SSE stream ended unexpectedly")
                await asyncio.sleep(0.2)
            await asyncio.sleep(3)
            for task in tasks.values():
                if task.done():
                    await task
                    raise RuntimeError("SSE stream ended before observation completed")
            for name in NAMES:
                other = NAMES[1] if name == NAMES[0] else NAMES[0]
                listing = await self.request(clients[name], "GET", "/session", params={"directory": "/workspace"})
                ids = {item["id"] for item in listing}
                self.check(f"{name}: list contains own session only", sessions[name]["id"] in ids and sessions[other]["id"] not in ids)
                own = await self.request(clients[name], "GET", f"/session/{sessions[name]['id']}", params={"directory": "/workspace"})
                self.check(f"{name}: own session detail", own["title"] == sessions[name]["title"])
                response = await clients[name].get(f"/session/{sessions[other]['id']}", params={"directory": "/workspace"})
                self.check(f"{name}: foreign session ID unavailable", response.status_code in (403, 404), {"status": response.status_code})
                serialized = json.dumps(events[name])
                self.check(f"{name}: SSE has own event, no other client's event in observed window", sessions[name]["id"] in serialized and sessions[other]["id"] not in serialized, {"events_observed": len(events[name]), "post_delivery_window_seconds": 3})
            return sessions
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def assert_file(self, client, name, path, expected):
        data = await self.request(client, "GET", "/file/content", params={"directory": "/workspace", "path": path})
        content = data.get("content")
        if data.get("encoding") == "base64":
            content = base64.b64decode(content).decode("utf-8")
        self.check(f"{name}: file API returns own marker", content == expected)

    def network_isolation(self, containers, entries):
        script = """import json,socket,sys
results=[]
for host,port,label in json.loads(sys.argv[1]):
    try:
        with socket.create_connection((host,port),timeout=3):
            results.append({'probe':label,'connected':True})
    except OSError as error:
        results.append({'probe':label,'connected':False,'error_type':type(error).__name__,'errno':error.errno})
print(json.dumps(results))
"""
        for name in NAMES:
            other = NAMES[1] if name == NAMES[0] else NAMES[0]
            own_network = next(iter(containers[name]["NetworkSettings"]["Networks"]))
            own_entry = entries[name]["NetworkSettings"]["Networks"][own_network]["IPAddress"]
            peer_agent = next(iter(containers[other]["NetworkSettings"]["Networks"].values()))["IPAddress"]
            peer_entries = [network["IPAddress"] for network in entries[other]["NetworkSettings"]["Networks"].values()]
            self.check(f"{name}: peers and own entry have testable IPv4 addresses", bool(own_entry and peer_agent) and all(peer_entries))
            probes = [["127.0.0.1", 4096, "own_agent_control"], [own_entry, 4096, "own_entry_control"], [peer_agent, 4096, "peer_agent"]]
            probes.extend([address, 4096, f"peer_entry_address_{index}"] for index, address in enumerate(peer_entries))
            probes.append(["1.1.1.1", 443, "public_ipv4_without_dns"])
            result = self.python(containers[name]["Id"], script, json.dumps(probes))
            self.check(f"{name}: own agent/entry reachable; peer agent/entries and public TCP blocked", all(item["connected"] for item in result[:2]) and not any(item["connected"] for item in result[2:]), result)

    async def lifecycle(self, clients, containers, sessions, path, markers):
        monitoring = True
        samples = []
        async def monitor_b():
            while monitoring:
                try:
                    await self.health(clients["client-b"])
                    samples.append(True)
                except (httpx.HTTPError, RuntimeError, ValueError):
                    samples.append(False)
                await asyncio.sleep(0.5)
        monitor = asyncio.create_task(monitor_b())
        completed = False
        try:
            await asyncio.to_thread(self.compose, "stop", "client-a")
            await self.health(clients["client-b"])
            await asyncio.to_thread(self.compose, "start", "client-a")
            await self.health(clients["client-a"], wait=True)
            self.check("client-a: stop/start retains container", self.container("client-a")["Id"] == containers["client-a"]["Id"])
            for phase in ("after stop/start", "after recreate"):
                if phase == "after recreate":
                    await asyncio.to_thread(self.compose, "up", "-d", "--no-deps", "--force-recreate", "client-a")
                    await self.health(clients["client-a"], wait=True)
                    self.check("client-a: recreate replaced container", self.container("client-a")["Id"] != containers["client-a"]["Id"])
                for name in NAMES:
                    detail = await self.request(clients[name], "GET", f"/session/{sessions[name]['id']}", params={"directory": "/workspace"})
                    self.check(f"{name}: session persists {phase}", detail["title"] == sessions[name]["title"])
                    await self.assert_file(clients[name], name, path, markers[name])
                self.check(f"client-b: container unchanged {phase}", self.container("client-b")["Id"] == containers["client-b"]["Id"])
                fresh = self.container("client-a")
                old_volumes = {m["Name"] for m in containers["client-a"]["Mounts"] if m["Type"] == "volume"}
                new_volumes = {m["Name"] for m in fresh["Mounts"] if m["Type"] == "volume"}
                self.check(f"client-a: volume identity unchanged {phase}", old_volumes == new_volumes)
            monitoring = False
            await monitor
            self.check("client-b: remained healthy during A lifecycle operations", bool(samples) and all(samples), {"health_samples": len(samples), "failed_samples": samples.count(False), "sampling_interval_seconds": 0.5})
            completed = True
            self.report["lifecycle_completed"] = True
        finally:
            monitoring = False
            await asyncio.gather(monitor, return_exceptions=True)
            if not completed:
                recovery = {"attempted": True, "healthy": False, "volumes_preserved": True}
                self.report["lifecycle_recovery"] = recovery
                try:
                    await asyncio.to_thread(self.compose, "up", "-d", "--no-deps", "client-a")
                    await self.health(clients["client-a"], wait=True)
                    recovery["healthy"] = True
                except Exception as error:
                    recovery["error"] = {"type": type(error).__name__, "message": self.redact(error)}
                    print(f"RECOVERY FAILED: {self.redact(error)}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle", action="store_true", help="Stop/start/recreate A; keep all volumes and check B throughout")
    parser.add_argument("--version", default="1.18.30")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "api-isolation.json")
    args = parser.parse_args()
    verification = None
    success = False
    failure = {"type": "Interrupted", "message": "Verification did not finish"}
    try:
        verification = Verification(args)
        asyncio.run(verification.run())
        success = True
    except Exception as error:
        message = verification.redact(error) if verification else str(error)
        failure = {"type": type(error).__name__, "message": message}
        print(f"FAILED: {message}", file=sys.stderr)
    finally:
        report = verification.report if verification else {"checks": [], "lifecycle_completed": False, "runtime": {}}
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "passed" if success else "failed"
        if not success:
            report["error"] = failure
        args.output.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        args.output.write_text((verification.redact(serialized) if verification else serialized) + "\n", encoding="utf-8")
        print(f"Evidence: {args.output}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
