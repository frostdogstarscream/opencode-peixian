"""Check control database compatibility and preserve stopped control data before an upgrade.

Only metadata is printed. Backups contain private data and stay in .runtime.
The guard covers the supported deployment commands, not arbitrary Docker commands
issued by a host administrator.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
READER = "peixian-control:console-r2-roles"
MIN_LABEL = "org.peixian.control.schema.min"
MAX_LABEL = "org.peixian.control.schema.max"


class GuardError(RuntimeError):
    pass


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise GuardError("docker_operation_failed")
    return result.stdout.strip()


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inspect_data(root):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GuardError("control_data_contains_link")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = sha256(path)
    database = root / "control.sqlite3"
    result = {"schema_version": 0, "roles": {}, "counts": {}, "files": files}
    if not database.is_file():
        if files:
            raise GuardError("control_database_missing_from_nonempty_volume")
        return result
    # A stopped WAL database can require a writable SHM file even for mode=ro.
    # Query a verified private DB+WAL copy; never mount the source writable or
    # use immutable=1 (which would silently ignore committed WAL transactions).
    with tempfile.TemporaryDirectory(prefix="control-schema-") as scratch:
        copied = Path(scratch) / database.name
        for name in (database.name, database.name + "-wal"):
            if name in files:
                shutil.copyfile(root / name, Path(scratch) / name)
                if sha256(Path(scratch) / name) != files[name] or sha256(root / name) != files[name]:
                    raise GuardError("control_database_changed_during_check")
        with closing(sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True)) as db:
            result["schema_version"] = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "users" not in tables:
                raise GuardError("control_database_invalid")
            result["roles"] = dict(db.execute("SELECT role,COUNT(*) FROM users GROUP BY role"))
            for table in ("users", "runtimes", "grants", "installs", "skills", "files", "models", "templates", "jobs", "audit"):
                if table in tables:
                    result["counts"][table] = db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            result["preservation"] = {}
            for table in ("users", "runtimes", "grants", "installs", "skills", "files", "models", "templates", "jobs"):
                if table not in tables:
                    continue
                cursor = db.execute("SELECT * FROM " + table)
                records = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor]
                if table == "users" and result["schema_version"] < 2:
                    for record in records:
                        if record["role"] == "admin":
                            record["role"] = "super_admin"
                            if "auth_version" in record:
                                record["auth_version"] += 1
                canonical = sorted(json.dumps(record, sort_keys=True) for record in records)
                result["preservation"][table] = hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
    # Exclude SHM, an ephemeral reader/writer coordination file, from identity.
    stable = {k: v for k, v in files.items() if not k.endswith("-shm")}
    result["fingerprint"] = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    return result


def compatible(schema_version, labels):
    labels = labels or {}
    if MIN_LABEL not in labels and MAX_LABEL not in labels:
        # All historical unlabelled Peixian control images used schema 0.
        minimum = maximum = 0
    else:
        try:
            minimum, maximum = int(labels[MIN_LABEL]), int(labels[MAX_LABEL])
        except (KeyError, TypeError, ValueError):
            raise GuardError("image_schema_contract_invalid") from None
    if minimum < 0 or maximum < minimum or not minimum <= schema_version <= maximum:
        raise GuardError("image_database_schema_incompatible")
    return maximum


def deployment(compose, image_override=None):
    config = json.loads(command("docker", "compose", "-f", str(compose), "config", "--format", "json"))
    service = config["services"]["console"]
    volumes = [v for v in service.get("volumes", []) if v.get("target") == "/data" and v.get("type") == "volume"]
    if len(volumes) != 1:
        raise GuardError("control_named_volume_required")
    volume = config["volumes"][volumes[0]["source"]]["name"]
    image = image_override or service["image"]
    item = json.loads(command("docker", "image", "inspect", image))[0]
    return volume, image, item


def volume_exists(volume):
    return volume in command("docker", "volume", "ls", "--format", "{{.Name}}").splitlines()


def stopped(volume):
    return not command("docker", "ps", "--filter", "volume=" + volume, "--format", "{{.ID}}")


def probe_args(volume, operation):
    reader = json.loads(command("docker", "image", "inspect", READER))[0]
    compatible(2, reader.get("Config", {}).get("Labels"))
    return ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--memory", "512m", "--cpus", "0.5", "--pids-limit", "32",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
            "--mount", "type=volume,source=" + volume + ",target=/data,readonly,volume-nocopy",
            "--mount", "type=bind,source=" + str(Path(__file__).resolve()) + ",target=/guard.py,readonly",
            "--entrypoint", "python", reader["Id"], "-B", "/guard.py", operation]


def inspect_volume(volume):
    if not volume_exists(volume):
        return {"schema_version": 0, "roles": {}, "counts": {}, "files": {}}
    return json.loads(command(*probe_args(volume, "_inspect")))


def backup_matches(folder, volume, state):
    for path in folder.glob("*/manifest.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            archive = path.parent / "control-data.tar.gz"
            if (data["volume"] == volume and data["state"].get("fingerprint") == state.get("fingerprint")
                    and archive.is_file() and sha256(archive) == data["archive_sha256"]):
                return True
        except (OSError, ValueError, KeyError):
            continue
    return False


def check(compose, backups, image=None):
    volume, image, item = deployment(compose, image)
    state = inspect_volume(volume)
    maximum = compatible(state["schema_version"], item.get("Config", {}).get("Labels"))
    if state["counts"].get("users", 0) and state["schema_version"] < maximum:
        if not stopped(volume) or not backup_matches(backups, volume, state):
            raise GuardError("legacy_database_requires_stopped_verified_backup")
    return {"status": "passed", "image": image, "image_id": item["Id"],
            "schema_version": state["schema_version"], "target_schema_max": maximum}


def backup(compose, backups):
    volume, _, _ = deployment(compose)
    if not volume_exists(volume) or not stopped(volume):
        raise GuardError("backup_requires_existing_stopped_control_volume")
    state = inspect_volume(volume)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    folder = backups / stamp
    folder.mkdir(parents=True, exist_ok=False)
    partial = folder / "control-data.tar.gz.partial"
    with partial.open("xb") as destination:
        process = subprocess.run(probe_args(volume, "_archive"), stdout=destination, stderr=subprocess.PIPE)
    if process.returncode:
        raise GuardError("control_backup_failed_partial_preserved")
    with tarfile.open(partial, "r:gz") as archive:
        actual = {}
        for member in archive:
            if not member.isfile() or member.name.startswith("/") or ".." in Path(member.name).parts:
                raise GuardError("control_backup_invalid_member")
            if member.name in actual:
                raise GuardError("control_backup_duplicate_member")
            digest = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            actual[member.name] = digest.hexdigest()
        if actual != state["files"]:
            raise GuardError("control_backup_contents_changed")
    if not stopped(volume) or inspect_volume(volume) != state:
        raise GuardError("control_data_changed_during_backup")
    target = folder / "control-data.tar.gz"
    partial.rename(target)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "volume": volume,
                "state": state, "archive_sha256": sha256(target),
                "scope": "control database and published packages only; account workspaces and keys are separate"}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "backed_up", "backup": str(folder), "schema_version": state["schema_version"],
            "roles": state["roles"], "counts": state["counts"], "archive_sha256": manifest["archive_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "backup", "_inspect", "_archive"))
    parser.add_argument("--compose", type=Path, default=ROOT / "compose.console.yaml")
    parser.add_argument("--backups", type=Path, default=ROOT / ".runtime/role-backups")
    parser.add_argument("--image", help="Check a proposed rollback image without starting it")
    args = parser.parse_args()
    if args.action == "_inspect":
        print(json.dumps(inspect_data(Path("/data"))))
        return
    if args.action == "_archive":
        root = Path("/data")
        state = inspect_data(root)
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
            for name in state["files"]:
                archive.add(root / name, arcname=name, recursive=False)
        return
    result = check(args.compose, args.backups, args.image) if args.action == "check" else backup(args.compose, args.backups)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, GuardError) else "control_schema_guard_failed"
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        raise SystemExit(1) from None
