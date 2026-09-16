"""Stopped full-deployment backups. Never delete or overwrite a restore target."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")
IDENTITY = re.compile(r"[a-f0-9]{32}")


class BackupError(RuntimeError):
    pass


def command(*args, timeout=300):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("backup_host_command_unavailable") from None
    if result.returncode:
        raise BackupError("backup_host_command_failed")
    return result.stdout.strip()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or name.startswith("/") or ".." in path.parts or "\\" in name or ":" in name
            or "\0" in name or str(path) != name.rstrip("/")):
        raise BackupError("backup_unsafe_member")
    return path


def scan(root, *, skip_lock=False):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if skip_lock and path in (root / "worker.lock", root / "windows-worker.process.json"):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise BackupError("backup_source_contains_unsupported_link_or_device")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"sha256": digest(path), "size": path.stat().st_size}
    return result


def pack(root, stream, *, private=False):
    before = scan(root)
    with tarfile.open(fileobj=stream, mode="w|gz", format=tarfile.PAX_FORMAT, dereference=True) as archive:
        for path in sorted(Path(root).rglob("*")):
            def protect(info):
                if private:
                    info.mode = 0o700 if info.isdir() else 0o600
                return info
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False, filter=protect)
    if scan(root) != before:
        raise BackupError("backup_source_changed_during_archive")


def archive_inventory(path):
    result, names = {}, set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            safe_name(member.name)
            folded = member.name.rstrip("/").casefold()
            if folded in names or (not member.isfile() and not member.isdir()):
                raise BackupError("backup_duplicate_or_link_member")
            names.add(folded)
            if member.isfile():
                value = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        value.update(chunk)
                result[member.name] = {"sha256": value.hexdigest(), "size": member.size}
    return result


def unpack_empty(root, archive, *, owner=None):
    root = Path(root)
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise BackupError("restore_target_must_be_empty")
    root.mkdir(parents=True, exist_ok=True)
    names = set()
    for member in archive:
        relative = safe_name(member.name)
        folded = member.name.rstrip("/").casefold()
        if folded in names or not (member.isfile() or member.isdir()):
            raise BackupError("backup_duplicate_or_link_member")
        names.add(folded)
        target = root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
            raise BackupError("restore_path_outside_target")
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.isdir():
            target.mkdir(exist_ok=True)
            continue
        with archive.extractfile(member) as source, target.open("xb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        os.chmod(target, member.mode & 0o777)
    if owner is not None and os.name == "posix":
        for path in [root, *root.rglob("*")]:
            os.chown(path, owner, owner)


@contextmanager
def worker_stopped(cfg):
    cfg.worker_root.mkdir(parents=True, exist_ok=True)
    with (cfg.worker_root / "worker.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BackupError("stop_worker_before_backup") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def runtime_inventory(cfg):
    volumes = {cfg.control_volume}
    identities = []
    root = cfg.worker_root / "runtimes"
    for account in sorted(root.iterdir()) if root.exists() else []:
        if account.is_symlink() or not account.is_dir() or not IDENTITY.fullmatch(account.name):
            raise BackupError("invalid_worker_runtime_inventory")
        identities.append(account.name)
        for path in account.rglob("compose.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("name") != "px-" + account.name:
                raise BackupError("runtime_compose_identity_mismatch")
            for volume in data.get("volumes", {}).values():
                if not NAME.fullmatch(volume.get("name", "")):
                    raise BackupError("invalid_backup_volume_name")
                volumes.add(volume["name"])
    existing = set(command("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
    if cfg.control_volume not in existing:
        raise BackupError("control_volume_missing")
    return sorted(volumes & existing), identities


def helper(image, volume, operation):
    write = operation == "_unpack"
    result = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges:true", "--cpus", "0.5", "--memory", "512m", "--pids-limit", "32",
              "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--user", "0:0" if write else "10001:10001"]
    if write:
        result.extend(["--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "-i"])
    result.extend(["--mount", "type=volume,source=" + volume + ",target=/data,volume-nocopy" + ("" if write else ",readonly"),
                   "--mount", "type=bind,source=" + str(Path(__file__).resolve()) + ",target=/backup.py,readonly",
                   "--entrypoint", "python", image, "-B", "/backup.py", operation])
    return result


def assert_stopped(volumes, cfg):
    if command("docker", "ps", "--filter", "label=peixian.deployment=" + cfg.deployment_id, "--format", "{{.ID}}"):
        raise BackupError("stop_platform_before_backup")
    for name in volumes:
        if command("docker", "ps", "--filter", "volume=" + name, "--format", "{{.ID}}"):
            raise BackupError("stop_all_volume_consumers_before_backup")


def validate_key(image, volume, key_file):
    args = helper(image, volume, "_validate_key")
    args.insert(2, "-i")
    process = subprocess.run(args, input=key_file.read_bytes().strip(), capture_output=True, timeout=60)
    if process.returncode:
        raise BackupError("control_database_and_master_key_do_not_match")


def backup(cfg, destination):
    if destination is None:
        raise BackupError("backup_destination_required")
    destination = Path(destination).resolve()
    if destination.is_relative_to(cfg.root) or destination.exists():
        raise BackupError("backup_requires_new_destination_outside_data_root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    image = json.loads(command("docker", "image", "inspect", cfg.images["control"]))[0]
    with worker_stopped(cfg):
        volumes, identities = runtime_inventory(cfg)
        assert_stopped(volumes, cfg)
        manifest = {"format": 1, "created": datetime.now(timezone.utc).isoformat(), "deployment_id": cfg.deployment_id,
                    "source_data_root": str(cfg.root), "control_volume": cfg.control_volume, "runtime_ids": identities,
                    "control_image": {"id": image["Id"], "labels": image.get("Config", {}).get("Labels", {})},
                    "images": cfg.images, "volumes": {}, "host": {}}
        for name in volumes:
            before = json.loads(command(*helper(image["Id"], name, "_scan")))
            if name == cfg.control_volume:
                meta = json.loads(command(*helper(image["Id"], name, "_database")))
                if meta["busy"]:
                    raise BackupError("finish_environment_jobs_before_backup")
                if meta["schema_version"] >= 4 and (meta.get("maintenance_mode") != "frozen" or meta.get("runtime_unsafe")):
                    raise BackupError("freeze_and_resolve_runtime_responsibility_before_backup")
                manifest["database"] = meta
            file = destination / (name + ".tar.gz")
            with file.open("xb") as out:
                result = subprocess.run(helper(image["Id"], name, "_pack"), stdout=out, stderr=subprocess.PIPE, timeout=1800)
            if result.returncode:
                raise BackupError("volume_backup_failed_partial_preserved")
            if archive_inventory(file) != before or json.loads(command(*helper(image["Id"], name, "_scan"))) != before:
                raise BackupError("volume_changed_during_backup")
            volume_info = json.loads(command("docker", "volume", "inspect", name))[0]
            manifest["volumes"][name] = {"file": file.name, "sha256": digest(file), "inventory": before,
                                         "labels": volume_info.get("Labels") or {}}
        with tempfile.TemporaryDirectory(prefix="platform-host-backup-") as temporary:
            staging = Path(temporary)
            host_before = {"worker": scan(cfg.worker_root, skip_lock=True), "secrets": scan(cfg.secrets),
                           "certificate": digest(cfg.certificate), "private_key": digest(cfg.private_key)}
            for name, source in (("worker", cfg.worker_root), ("secrets", cfg.secrets)):
                shutil.copytree(source, staging / name, ignore=(lambda directory, names: ["worker.lock", "windows-worker.process.json"] if Path(directory) == cfg.worker_root else []))
            (staging / "tls").mkdir()
            shutil.copyfile(cfg.certificate, staging / "tls/certificate.pem")
            shutil.copyfile(cfg.private_key, staging / "tls/private-key.pem")
            shutil.copyfile(cfg.source, staging / "platform.source.json")
            validate_key(image["Id"], cfg.control_volume, staging / "secrets/console-control.key")
            manifest["matching_keys_verified"] = True
            with (destination / "host.tar.gz").open("xb") as out:
                pack(staging, out, private=True)
            after = {"worker": scan(cfg.worker_root, skip_lock=True), "secrets": scan(cfg.secrets),
                     "certificate": digest(cfg.certificate), "private_key": digest(cfg.private_key)}
            if after != host_before:
                raise BackupError("host_changed_during_backup")
            manifest["host"] = {"file": "host.tar.gz", "sha256": digest(destination / "host.tar.gz"),
                                "inventory": archive_inventory(destination / "host.tar.gz")}
        assert_stopped(volumes, cfg)
        (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if os.name == "posix":
            for path in destination.iterdir():
                os.chmod(path, 0o600)
    verify(destination)
    return {"status": "backed_up", "directory": str(destination), "volumes": len(volumes),
            "runtime_count": len(identities), "manifest_sha256": digest(destination / "manifest.json")}


def read_manifest(folder):
    if folder is None:
        raise BackupError("backup_archive_directory_required")
    folder = Path(folder).resolve()
    try:
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BackupError("backup_manifest_unavailable") from None
    if (data.get("format") != 1 or not isinstance(data.get("volumes"), dict) or not data["volumes"]
            or not isinstance(data.get("runtime_ids"), list) or any(not IDENTITY.fullmatch(v) for v in data["runtime_ids"])
            or data.get("control_volume") not in data["volumes"]):
        raise BackupError("backup_manifest_invalid")
    return folder, data


def verify(folder):
    folder, manifest = read_manifest(folder)
    for name, entry in [*manifest["volumes"].items(), ("host", manifest["host"])]:
        if not NAME.fullmatch(name) or not isinstance(entry.get("file"), str) or Path(entry["file"]).name != entry["file"]:
            raise BackupError("backup_manifest_invalid_path")
        file = folder / entry["file"]
        if file.is_symlink() or not file.is_file() or digest(file) != entry["sha256"]:
            raise BackupError("backup_checksum_mismatch")
        if archive_inventory(file) != entry["inventory"]:
            raise BackupError("backup_inventory_mismatch")
    required = {"secrets/console-control.key", "secrets/console-worker.key", "secrets/console-admin.password",
                "tls/certificate.pem", "tls/private-key.pem"}
    if not required.issubset(manifest["host"]["inventory"]):
        raise BackupError("backup_matching_credentials_missing")
    if manifest.get("matching_keys_verified") is not True:
        raise BackupError("backup_master_key_verification_missing")
    return {"status": "verified", "volumes": len(manifest["volumes"]), "runtime_count": len(manifest["runtime_ids"])}


def rewrite_host(root, source_root, deployment_id):
    separator = "\\" if "\\" in source_root else "/"
    source_worker = source_root.rstrip("/\\") + separator + "worker"
    target_worker = str(root / "worker")
    for path in (root / "worker").rglob("*.json"):
        parts = path.relative_to(root / "worker").parts
        metadata = (len(parts) >= 3 and parts[0] == "runtimes" and IDENTITY.fullmatch(parts[1]) and
                    ((len(parts) == 3 and parts[2] in ("state.json", "pending.json")) or
                     (len(parts) == 5 and parts[2] == "releases" and parts[4] == "compose.json") or
                     (len(parts) == 4 and parts[2] == "operations" and parts[3].endswith("-compose.json"))))
        if not metadata:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))

        def rewrite(value):
            if isinstance(value, dict):
                return {k: deployment_id if k == "peixian.deployment" else rewrite(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if isinstance(value, str) and (value == source_worker or value.startswith(source_worker + separator)):
                tail = value[len(source_worker):].lstrip("/\\").replace("\\", "/")
                return str(Path(target_worker).joinpath(*PurePosixPath(tail).parts))
            return value

        original = data
        data = rewrite(data)
        if path.name == "state.json":
            data["paused"] = True
        if data != original:
            path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def restore(cfg, folder):
    verify(folder)
    folder, manifest = read_manifest(folder)
    if cfg.root.exists() and any(cfg.root.iterdir()):
        raise BackupError("restore_requires_empty_data_root")
    if cfg.deployment_id == manifest["deployment_id"]:
        raise BackupError("restore_requires_new_deployment_namespace")
    image = json.loads(command("docker", "image", "inspect", cfg.images["control"]))[0]
    labels = image.get("Config", {}).get("Labels", {})
    if getattr(cfg, "version", 1) >= 2:
        try:
            cfg.verify_control_image(labels)
        except ValueError as error:
            raise BackupError(str(error)) from None
    try:
        low, high = (int(labels["org.peixian.control.schema." + key]) for key in ("min", "max"))
    except (KeyError, ValueError):
        raise BackupError("restore_image_schema_contract_missing") from None
    if not low <= manifest["database"]["schema_version"] <= high:
        raise BackupError("restore_image_database_incompatible")
    if manifest["database"]["schema_version"] >= 4 and not manifest["database"].get("migration_identity"):
        raise BackupError("restore_migration_identity_missing")
    targets = {name: cfg.control_volume if name == manifest["control_volume"] else name for name in manifest["volumes"]}
    existing = set(command("docker", "volume", "ls", "--format", "{{.Name}}").splitlines())
    containers = command("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
    networks = command("docker", "network", "ls", "--format", "{{.Name}}").splitlines()
    if (set(targets.values()) & existing or cfg.control_container in containers
            or any(name.startswith("px-" + rid) for rid in manifest["runtime_ids"] for name in containers + networks)):
        raise BackupError("restore_target_resources_already_exist")
    # All validation is complete before allocating any target. Partial failures
    # are retained for inspection; this command never deletes resources.
    cfg.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(folder / manifest["host"]["file"], "r:gz") as archive:
        unpack_empty(cfg.root, archive)
    rewrite_host(cfg.root, manifest["source_data_root"], cfg.deployment_id)
    for original, target in targets.items():
        labels = {**manifest["volumes"][original].get("labels", {}), "peixian.deployment": cfg.deployment_id}
        if original == manifest["control_volume"]:
            labels.update({"com.docker.compose.project": cfg.deployment_id, "com.docker.compose.volume": "control-data"})
        arguments = ["docker", "volume", "create"]
        for key, value in labels.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", key) or not isinstance(value, str) or any(c in value for c in "\r\n\0"):
                raise BackupError("invalid_backup_volume_labels")
            arguments.extend(["--label", key + "=" + value])
        command(*arguments, target)
        with (folder / manifest["volumes"][original]["file"]).open("rb") as source:
            process = subprocess.run(helper(image["Id"], target, "_unpack"), stdin=source, capture_output=True, timeout=1800)
        if process.returncode:
            raise BackupError("restore_failed_partial_target_preserved")
        if json.loads(command(*helper(image["Id"], target, "_scan"))) != manifest["volumes"][original]["inventory"]:
            raise BackupError("restore_volume_verification_failed")
    validate_key(image["Id"], cfg.control_volume, cfg.secrets / "console-control.key")
    # Restored accounts start paused and old browser/token credentials are revoked.
    # Account IDs, password hashes, personal content and grants remain unchanged.
    changed = helper(image["Id"], cfg.control_volume, "_pause_database")
    index = changed.index("type=volume,source=" + cfg.control_volume + ",target=/data,volume-nocopy,readonly")
    changed[index] = changed[index].removesuffix(",readonly")
    command(*changed)
    receipt = {"status": "restored_paused", "volumes": len(targets), "runtime_count": len(manifest["runtime_ids"]),
               "source_manifest_sha256": digest(folder / "manifest.json"), "authentication_revoked": True}
    (cfg.root / "restore-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def database_meta(root):
    root = Path(root)
    with tempfile.TemporaryDirectory(prefix="backup-db-") as temporary:
        for name in ("control.sqlite3", "control.sqlite3-wal"):
            if (root / name).exists():
                shutil.copyfile(root / name, Path(temporary) / name)
        with closing(sqlite3.connect(str(Path(temporary) / "control.sqlite3"))) as db:
            result = {"schema_version": db.execute("PRAGMA user_version").fetchone()[0],
                      "busy": bool(db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]),
                      "users": db.execute("SELECT count(*) FROM users").fetchone()[0]}
            if result["schema_version"] >= 4:
                db.row_factory = sqlite3.Row
                try:
                    from control.migrations_v4 import validate
                except ModuleNotFoundError:
                    import importlib.util
                    module_path = Path(__file__).resolve().parents[2] / "services/peixian-control/control/migrations_v4.py"
                    module_spec = importlib.util.spec_from_file_location("backup_migrations_v4", module_path)
                    module = importlib.util.module_from_spec(module_spec)
                    module_spec.loader.exec_module(module)
                    validate = module.validate
                try:
                    validate(db)
                except ValueError:
                    raise BackupError("backup_v4_migration_identity_invalid") from None
                result["migration_identity"] = [dict(row) for row in db.execute(
                    "SELECT migration_id,from_version,to_version,script_digest,structure_digest FROM schema_migrations ORDER BY migration_id")]
                result["maintenance_mode"] = db.execute("SELECT maintenance_mode FROM platform_state WHERE id=1").fetchone()[0]
                result["runtime_unsafe"] = bool(db.execute(
                    "SELECT 1 FROM runtimes WHERE recovery_required=1 OR drain_job_id IS NOT NULL OR status IN ('updating','draining') LIMIT 1").fetchone())
            return result


def pause_database(path):
    with closing(sqlite3.connect(str(path))) as db, db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        db.execute("UPDATE runtimes SET status='paused',reserved=0,error=NULL")
        db.execute("UPDATE users SET auth_version=auth_version+1")
        db.execute("DELETE FROM auth")
        if version >= 4:
            db.execute("UPDATE runtimes SET gate_policy='closed',state_version=state_version+1,gate_epoch=gate_epoch+1,gateway_boot_id=NULL,relay_boot_id=NULL")
            db.execute("UPDATE platform_state SET maintenance_mode='frozen',state_version=state_version+1 WHERE id=1")
            db.execute("DELETE FROM runtime_observations")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "_scan":
        print(json.dumps(scan("/data"), sort_keys=True))
    elif action == "_database":
        print(json.dumps(database_meta("/data")))
    elif action == "_pack":
        pack("/data", sys.stdout.buffer)
    elif action == "_unpack":
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
            unpack_empty("/data", archive, owner=10001)
    elif action == "_pause_database":
        pause_database("/data/control.sqlite3")
    elif action == "_validate_key":
        from cryptography.fernet import Fernet
        cipher = Fernet(sys.stdin.buffer.read(128).strip())
        with tempfile.TemporaryDirectory(prefix="backup-key-") as temporary:
            for name in ("control.sqlite3", "control.sqlite3-wal"):
                source = Path("/data") / name
                if source.exists():
                    shutil.copyfile(source, Path(temporary) / name)
            with closing(sqlite3.connect(str(Path(temporary) / "control.sqlite3"))) as db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table, column in (("runtimes", "spec"), ("models", "secret"), ("installs", "config"), ("connections", "secret"),
                                      ("job_attempts", "spec_ciphertext"), ("request_idempotency", "response_ciphertext")):
                    if table in tables:
                        for row in db.execute("SELECT " + column + " FROM " + table + " WHERE " + column + " IS NOT NULL"):
                            json.loads(cipher.decrypt(row[0].encode()))
                if "applied_spec_ciphertext" in {row[1] for row in db.execute("PRAGMA table_info(runtimes)")}:
                    for row in db.execute("SELECT applied_spec_ciphertext FROM runtimes WHERE applied_spec_ciphertext IS NOT NULL"):
                        json.loads(cipher.decrypt(row[0].encode()))
