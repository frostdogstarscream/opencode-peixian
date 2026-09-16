"""Read-only Docker capacity and resource evidence; never change deployment state.

Use budget before provisioning. sample --cgroup additionally reads Linux cgroup
counters inside existing containers. It does not reset counters, start containers,
send model requests, or imply a passed capacity test. Outputs exclude secrets,
account names, prompts, paths and raw Docker error text.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("sampling_platform_config", ROOT / "platform-config.py")
config = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = config
_spec.loader.exec_module(config)
CGROUP_CODE = """
import json
from pathlib import Path
root=Path('/sys/fs/cgroup')
out={}
for key in ('memory.current','memory.peak','memory.swap.current'):
    try: out[key]=int((root/key).read_text().strip())
    except (OSError,ValueError): out[key]=None
for key in ('memory.events','cpu.stat'):
    try: out[key]={line.split()[0]:int(line.split()[1]) for line in (root/key).read_text().splitlines()}
    except (OSError,ValueError,IndexError): out[key]=None
try:
    fields={line.split(':')[0]:line.split(':')[1].strip().split()[0] for line in Path('/proc/meminfo').read_text().splitlines()}
    for name in ('MemAvailable','SwapFree','SwapTotal'):
        out['engine.'+name]=int(fields[name])*1024
except (OSError,ValueError,IndexError,KeyError):
    pass
print(json.dumps(out))
"""
INSPECT_FORMAT = ('{"id":{{json .Id}},"running":{{json .State.Running}},'
                  '"oom_killed":{{json .State.OOMKilled}},"restart_count":{{json .RestartCount}},'
                  '"service":{{json (index .Config.Labels "com.docker.compose.service")}}}')


class SampleError(RuntimeError):
    pass


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise SampleError("resource_probe_unavailable") from None
    if result.returncode:
        raise SampleError("resource_probe_failed")
    return result.stdout.strip()


def docker_host():
    # A Docker context may point to a different host without DOCKER_HOST.
    records = json.loads(command("docker", "context", "inspect"))
    endpoint = records[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
    if not endpoint.startswith(("unix://", "npipe://")):
        raise SampleError("local_docker_engine_required")
    info = json.loads(command("docker", "info", "--format", "{{json .}}"))
    if info.get("OSType") != "linux":
        raise SampleError("docker_linux_engine_required")
    return info


def network_records():
    identifiers = command("docker", "network", "ls", "--format", "{{.ID}}").split()
    return json.loads(command("docker", "network", "inspect", *identifiers)) if identifiers else []


def assess(cfg, info, networks, retained):
    result = config.capacity.evaluate(info, cfg.resource_budget)
    network = config.capacity.network_capacity(cfg.network_pool, networks, cfg.deployment_id, cfg.max_runtimes, retained)
    result["network"] = network
    if network["status"] != "passed":
        result["failures"].append("configured_network_pool_capacity_insufficient")
        result["status"] = "insufficient"
    result.update(target_runtimes=cfg.max_runtimes, config_version=cfg.version, profile=cfg.profile,
                  actual_load_validation="not_run",
                  memory_shortfall_bytes=max(0, cfg.memory_budget_mib * 1024 * 1024 - (info.get("MemTotal") or 0)),
                  cpu_planning_shortfall=max(0, cfg.cpu_budget - (info.get("NCPU") or 0)))
    return result


def byte_quantity(value):
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*", value)
    if not match:
        raise SampleError("docker_stat_units_unrecognized")
    factor = {"B":1,"kB":1000,"KB":1000,"MB":1000**2,"GB":1000**3,"TB":1000**4,
              "KiB":1024,"MiB":1024**2,"GiB":1024**3,"TiB":1024**4}[match[2]]
    return int(float(match[1]) * factor)


def stat_record(data):
    try:
        used, ceiling = data["MemUsage"].split("/")
        cpu = float(data["CPUPerc"].removesuffix("%"))
        pids = int(data["PIDs"])
        if not math.isfinite(cpu) or cpu < 0 or pids < 0:
            raise ValueError()
        return {"cpu_percent":cpu, "docker_memory_usage_bytes":byte_quantity(used),
                "memory_limit_bytes":byte_quantity(ceiling), "pids":pids}
    except (KeyError, ValueError, AttributeError):
        raise SampleError("docker_stat_record_invalid") from None


def pseudonym(identity):
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def cgroup(identity):
    try:
        data = json.loads(command("docker", "exec", identity, "python3", "-I", "-S", "-c", CGROUP_CODE))
        return {"cgroup":data, "cgroup_status":"available" if data.get("memory.current") is not None else "unsupported"}
    except (SampleError, ValueError):
        return {"cgroup":None, "cgroup_status":"unavailable"}


def sample(cfg, with_cgroup=False):
    started = time.monotonic()
    ids = command("docker", "ps", "-a", "--filter", "label=peixian.deployment=" + cfg.deployment_id,
                  "--format", "{{.ID}}").split()
    if len(ids) > 3 * 64 + 16:
        raise SampleError("deployment_container_inventory_exceeds_probe_bound")
    records = []
    if ids:
        raw = command("docker", "inspect", "--format", INSPECT_FORMAT, *ids)
        records = [json.loads(line) for line in raw.splitlines()]
    running = [item["id"] for item in records if item["running"]]
    stats = {}
    if running:
        raw = command("docker", "stats", "--no-stream", "--format", "{{json .}}", *running)
        for line in raw.splitlines():
            value = json.loads(line)
            stats[value.get("ID", value.get("Container", ""))] = stat_record(value)
    probes = {}
    if with_cgroup:
        with ThreadPoolExecutor(max_workers=4) as executor:
            probes = dict(zip(running, executor.map(cgroup, running)))
    result = []
    for item in records:
        identity = item["id"]
        selected = next((value for key, value in stats.items() if key and identity.startswith(key)), None)
        result.append({"container":pseudonym(identity), "service":item.get("service") if item.get("service") in
                       ("agent","gateway","model-relay","console","https") else "other",
                       "running":bool(item["running"]), "oom_killed":bool(item["oom_killed"]),
                       "restart_count":item["restart_count"], "stats":selected,
                       **probes.get(identity, {"cgroup_status":"not_sampled"})})
    return {"time":datetime.now(timezone.utc).isoformat(), "probe_seconds":round(time.monotonic()-started,3),
            "container_count":len(result), "running_count":len(running), "containers":result}


def report_path(path, cfg):
    target = Path(path).resolve()
    if target.is_relative_to(cfg.root) or target.exists():
        raise SampleError("sampling_output_requires_new_path_outside_data_root")
    if any(item.is_symlink() for item in (Path(path), *Path(path).parents)):
        raise SampleError("sampling_output_must_not_be_link")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("budget", "sample"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="A new report outside data_root; defaults to standard output")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--cgroup", action="store_true", help="Bounded read-only docker exec probes; no counter reset")
    args = parser.parse_args()
    try:
        if not 1 <= args.samples <= 720 or not math.isfinite(args.interval) or not 1 <= args.interval <= 60:
            raise SampleError("sampling_bounds_invalid")
        cfg = config.load_config(args.config)
        output = report_path(args.output, cfg) if args.output else None
        report = {"format":1, "capacity":assess(cfg,docker_host(),network_records(),config.capacity.retained_ids(cfg.worker_root)),
                  "samples":[], "evidence":"resource_observation_only", "target_50_verified":False}
        if args.action == "sample":
            for index in range(args.samples):
                started=time.monotonic()
                report["samples"].append(sample(cfg,args.cgroup))
                if index + 1 < args.samples:
                    time.sleep(max(0,args.interval-(time.monotonic()-started)))
        payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
        if output:
            with os.fdopen(os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),"w",encoding="utf-8") as stream:
                stream.write(payload)
            print(json.dumps({"status":"recorded","capacity":report["capacity"]["status"],"sample_count":len(report["samples"])}))
        else:
            print(payload,end="")
        return 0 if report["capacity"]["status"] == "passed" else 2
    except (config.ConfigError,SampleError,ValueError,OSError,KeyError) as error:
        code=str(error) if isinstance(error,(config.ConfigError,SampleError)) else "resource_sampling_failed"
        print(json.dumps({"status":"failed","code":code}),file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
