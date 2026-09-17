"""Pure capacity contracts shared by preflight, the host executor and profiling tools.

CPU sharing is an admission planning policy, not CPU isolation or a throughput promise.
Memory remains the sum of container ceilings plus explicit host/platform headroom.
"""
from __future__ import annotations

import ipaddress
import math
import re
from pathlib import Path

MAX_RUNTIMES = {1: 32, 2: 64, 3: 64, 4: 64}
PROXY_MEMORY_MIB = 128
PROXY_CPUS = 0.5
POLICY = {"cpu_mode": "strict", "cpu_reserve": 4.0, "cpu_overcommit_factor": 1.0,
          "host_memory_reserve_mib": 4096}


def runtime_limit(version, maximum):
    if type(version) is not int or version not in MAX_RUNTIMES:
        raise ValueError("invalid_platform_configuration_version")
    if type(maximum) is not int or not 1 <= maximum <= MAX_RUNTIMES[version]:
        raise ValueError("invalid_runtime_capacity")


def policy(value, control):
    if not isinstance(value, dict) or set(value) - set(POLICY):
        raise ValueError("invalid_capacity_policy")
    result = {**POLICY, **value}
    if result["cpu_mode"] not in ("strict", "shared"):
        raise ValueError("invalid_cpu_budget_mode")
    for name, low, high in (("cpu_reserve", 1, 64), ("cpu_overcommit_factor", 1, 16)):
        number = result[name]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError("invalid_capacity_policy")
    if result["cpu_reserve"] < control["cpus"] + PROXY_CPUS:
        raise ValueError("cpu_reserve_below_platform_caps")
    if result["cpu_mode"] == "strict" and result["cpu_overcommit_factor"] != 1:
        raise ValueError("strict_cpu_mode_disallows_overcommit")
    memory = result["host_memory_reserve_mib"]
    if type(memory) is not int or not 1024 <= memory <= 1048576:
        raise ValueError("invalid_capacity_policy")
    return result


def budget(version, maximum, limits, control, settings):
    runtime_limit(version, maximum)
    cpu_caps = maximum * sum(v["cpus"] for v in limits.values())
    memory_caps = maximum * sum(v["memory_mib"] for v in limits.values())
    if version == 1:
        return {"cpu_required": 1 + cpu_caps, "memory_required_mib": 1536 + memory_caps,
                "runtime_cpu_caps": cpu_caps, "cpu_mode": "strict", "cpu_overcommit_factor": 1,
                "cpu_reserve": 1, "memory_includes_swap": False}
    settings = policy(settings, control)
    return {"cpu_required": settings["cpu_reserve"] + cpu_caps / settings["cpu_overcommit_factor"],
            # Host reserve includes Docker, proxy and executor; control is separate.
            "memory_required_mib": settings["host_memory_reserve_mib"] + control["memory_mib"] + memory_caps,
            "runtime_cpu_caps": cpu_caps, "cpu_mode": settings["cpu_mode"],
            "cpu_overcommit_factor": settings["cpu_overcommit_factor"], "cpu_reserve": settings["cpu_reserve"],
            "memory_includes_swap": False}


def evaluate(info, required):
    """Use Docker's actual Linux engine bytes/CPUs; host swap is not capacity."""
    failures = []
    if type(info.get("MemTotal")) is not int or info["MemTotal"] < required["memory_required_mib"] * 1024 * 1024:
        failures.append("docker_memory_below_configured_runtime_budget")
    if type(info.get("NCPU")) is not int or info["NCPU"] < required["cpu_required"]:
        failures.append("docker_cpus_below_configured_runtime_budget")
    return {"status": "passed" if not failures else "insufficient", "failures": failures,
            "docker_memory_bytes": info.get("MemTotal"), "docker_cpus": info.get("NCPU"), **required}


def retained_ids(worker_root):
    root = Path(worker_root) / "runtimes"
    if not root.exists():
        return set()
    if root.is_symlink():
        raise ValueError("invalid_retained_runtime_directory")
    result = set()
    for item in root.iterdir():
        if item.is_symlink() or not item.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", item.name):
            raise ValueError("invalid_retained_runtime_identity")
        result.add(item.name)
    return result


def network_capacity(pool, records, deployment_id, maximum, retained_ids=()):
    """Count whole /28s, including historical paused identities and foreign overlap.

    Existing deployment-owned allocations count as occupied *and* reusable for their
    owner, never as free slots for another identity. No networks are changed here.
    """
    pool = ipaddress.ip_network(pool, strict=True)
    identities = set(retained_ids)
    if any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value) for value in identities):
        raise ValueError("invalid_retained_runtime_identity")
    allocated = []
    existing_own = 0
    for record in records:
        labels = record.get("Labels") or {}
        name = record.get("Name", "")
        own = labels.get("peixian.deployment") == deployment_id
        identity = labels.get("peixian.runtime_id", "")
        account = (own and re.fullmatch(r"[a-f0-9]{32}", identity) and
                   name in {"px-" + identity + "-" + suffix for suffix in ("internal", "management", "egress")})
        if account:
            identities.add(identity)
        for item in (record.get("IPAM", {}).get("Config") or []):
            if not item.get("Subnet"):
                continue
            subnet = ipaddress.ip_network(item["Subnet"], strict=False)
            if subnet.version == 4 and own and (account or name == deployment_id + "-front"):
                if subnet.prefixlen != 28 or not subnet.subnet_of(pool):
                    raise ValueError("deployment_network_outside_expected_subnet_contract")
                existing_own += 1
            if subnet.version != 4 or not subnet.overlaps(pool):
                continue
            allocated.append(subnet)
    free = sum(not any(part.overlaps(used) for used in allocated) for part in pool.subnets(new_prefix=28))
    required = 1 + 3 * max(maximum, len(identities))
    missing = max(0, required - existing_own)
    return {"status": "passed" if free >= missing else "insufficient", "required_subnets": required,
            "existing_owned_subnets": existing_own, "free_subnets": free, "missing_subnets": missing,
            "retained_runtime_count": len(identities), "prefix": 28}
