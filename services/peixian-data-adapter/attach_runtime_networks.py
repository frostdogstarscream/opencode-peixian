"""Attach the adapter container to verified Peixian runtime management networks.

The script is dry-run by default. Use --execute only on the test server after
reviewing the selected networks. It never creates, removes, or disconnects a
network.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess


NETWORK = re.compile(r"px-[a-f0-9]{32}-management")


def docker(*arguments):
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, check=True, text=True
    )
    return result.stdout.strip()


def eligible_networks(deployment):
    identifiers = docker("network", "ls", "--format", "{{.ID}}").splitlines()
    if not identifiers:
        return []
    records = json.loads(docker("network", "inspect", *identifiers))
    return sorted(
        record["Name"]
        for record in records
        if NETWORK.fullmatch(record.get("Name", ""))
        and record.get("Internal") is True
        and (record.get("Labels") or {}).get("peixian.console.managed") == "true"
        and (not deployment or (record.get("Labels") or {}).get("peixian.deployment") == deployment)
        and re.fullmatch(r"[a-f0-9]{32}", (record.get("Labels") or {}).get("peixian.runtime_id", ""))
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="peixian-data-adapter")
    parser.add_argument("--deployment", help="只选择指定 peixian.deployment 标签")
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    container = json.loads(docker("inspect", arguments.container))[0]
    attached = set((container.get("NetworkSettings") or {}).get("Networks") or {})
    pending = [name for name in eligible_networks(arguments.deployment) if name not in attached]
    print(json.dumps({"container": arguments.container, "pending": pending, "execute": arguments.execute}, ensure_ascii=False))
    if not arguments.execute:
        return
    for network in pending:
        docker("network", "connect", "--alias", "peixian-data-adapter", network, container["Id"])
    current = json.loads(docker("inspect", container["Id"]))[0]
    networks = set((current.get("NetworkSettings") or {}).get("Networks") or {})
    missing = [name for name in pending if name not in networks]
    if missing:
        raise SystemExit("network attachment verification failed: " + ", ".join(missing))


if __name__ == "__main__":
    main()
