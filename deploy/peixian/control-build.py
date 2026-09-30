"""Build, inspect and export a Control image without touching running services."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/peixian-control"))
from shared.control_delivery import DeliveryError, checksum, verify

INPUTS = ("services/peixian-control/Dockerfile", "services/peixian-control/requirements.lock",
          "services/peixian-control/control", "services/peixian-control/shared",
          "packages/peixian-console/package.json", "packages/peixian-console/bun.lock",
          "packages/peixian-console/tsconfig.json", "packages/peixian-console/vite.config.ts",
          "packages/peixian-console/index.html", "packages/peixian-console/src",
          "packages/ui/src/styles/theme.css")
TAG = re.compile(r"[a-z0-9][a-z0-9./:_-]{0,180}")


class BuildError(RuntimeError):
    pass


def command(*args, cwd=ROOT, timeout=60):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise BuildError("control_command_unavailable_or_timeout") from None
    if result.returncode:
        raise BuildError("control_command_failed")
    return result.stdout.strip()


def new_output(path):
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise BuildError("control_output_exists_use_new_destination")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def allowed_file(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(part.startswith(".") for part in path.parts):
        return False
    if any(part in ("node_modules", "dist", "__pycache__", "tests") for part in path.parts):
        return False
    return any(name == prefix or name.startswith(prefix + "/") for prefix in INPUTS)


def copy_dev(root, destination):
    for name in INPUTS:
        source = root / name
        if source.is_symlink() or not source.exists():
            raise BuildError("control_build_input_missing_or_link")
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in files:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise BuildError("control_build_input_link_forbidden")
            if path.is_file() and allowed_file(relative):
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)


def copy_release(root, destination, commit):
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}", commit) or commit.startswith("-"):
        raise BuildError("control_commit_invalid")
    resolved = command("git", "rev-parse", "--verify", commit + "^{commit}", cwd=root)
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise BuildError("control_commit_not_full_sha")
    archive = destination.parent / "source-inputs.tar"
    command("git", "archive", "--format=tar", "--output=" + str(archive), resolved, "--", *INPUTS, cwd=root)
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or not allowed_file(member.name):
                raise BuildError("control_archive_input_forbidden")
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as content, target.open("xb") as output:
                shutil.copyfileobj(content, output)
    return resolved


def context_digest(context):
    files = {path.relative_to(context).as_posix(): checksum(path) for path in sorted(context.rglob("*")) if path.is_file()}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def base_images(context):
    sources = re.findall(r"^FROM ([^\s]+)", (context / INPUTS[0]).read_text(encoding="utf-8"), re.M)
    if len(sources) != 2 or any(not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", value) for value in sources):
        raise BuildError("control_pinned_base_images_required")
    return dict(zip(("frontend", "runtime"), sources))


def inspect_image(image):
    if not TAG.fullmatch(image) or image.startswith("-"):
        raise BuildError("control_image_reference_invalid")
    info = json.loads(command("docker", "image", "inspect", image))[0]
    identity = info.get("Id", "")
    labels = info.get("Config", {}).get("Labels", {}) or {}
    if (not re.fullmatch(r"sha256:[0-9a-f]{64}", identity) or info.get("Os") != "linux"
            or info.get("Architecture") != "amd64" or labels.get("org.peixian.control.delivery.format") != "1"):
        raise BuildError("control_delivery_image_required")
    created = False
    container = "control-delivery-inspect-" + uuid.uuid4().hex[:16]
    try:
        command("docker", "create", "--network", "none", "--name", container, identity)
        created = True
        with tempfile.TemporaryDirectory(prefix="control-image-inspect-") as directory:
            root = Path(directory)
            command("docker", "cp", container + ":/app/build-manifest.json", str(root / "build-manifest.json"))
            command("docker", "cp", container + ":/app/static", str(root / "static"))
            manifest = verify(root / "static", json.loads((root / "build-manifest.json").read_text(encoding="utf-8")))
        if labels.get("org.peixian.control.delivery.mode") != manifest["mode"]:
            raise BuildError("control_image_mode_mismatch")
        if labels.get("org.opencontainers.image.revision", "") != (manifest["source_commit"] or ""):
            raise BuildError("control_image_source_mismatch")
        return {"image_id": identity, "image": image, "build": manifest,
                "user": info["Config"].get("User"), "os": info["Os"], "architecture": info["Architecture"]}
    finally:
        if created:
            command("docker", "rm", container)


def verify_release(value, source_commit=None):
    if value["build"]["mode"] != "release":
        raise BuildError("control_development_image_not_publishable")
    if source_commit is not None and value["build"]["source_commit"] != source_commit:
        raise BuildError("control_package_source_mismatch")
    if value.get("user") != "10001:10001":
        raise BuildError("control_image_user_mismatch")
    return value


def build(*, mode, commit=None, tag=None, output=None, root=ROOT):
    if mode == "release" and not commit:
        raise BuildError("control_release_commit_required")
    if mode not in ("dev", "release") or mode == "dev" and commit:
        raise BuildError("control_build_mode_invalid")
    output = new_output(output) if output else None
    with tempfile.TemporaryDirectory(prefix="control-build-") as directory:
        context = Path(directory) / "context"
        context.mkdir()
        source_commit = copy_release(root, context, commit) if mode == "release" else None
        if mode == "dev":
            copy_dev(root, context)
        digest = context_digest(context)
        bases = base_images(context)
        tag = tag or "agent-platform-control:" + ("delivery-" + source_commit[:12] if source_commit else "dev-" + digest[:12])
        if not TAG.fullmatch(tag) or tag.startswith("-"):
            raise BuildError("control_image_tag_invalid")
        # BuildKit's temporary IID file prevents tag races from changing what is inspected.
        iid = Path(directory) / "image-id"
        args = ["docker", "build", "--platform", "linux/amd64", "--iidfile", str(iid),
                "--file", str(context / INPUTS[0]), "--tag", tag,
                "--build-arg", "BUILD_MODE=" + mode, "--build-arg", "SOURCE_COMMIT=" + (source_commit or ""),
                "--build-arg", "INPUT_DIGEST=" + digest, "--build-arg", "FRONTEND_BASE=" + bases["frontend"],
                "--build-arg", "RUNTIME_BASE=" + bases["runtime"], str(context)]
        if subprocess.run(args, cwd=root).returncode:
            raise BuildError("control_image_build_failed")
        value = inspect_image(iid.read_text().strip())
        value["requested_tag"] = tag
        if (value["build"]["mode"] != mode or value["build"]["input_digest"] != digest
                or value["build"]["source_commit"] != source_commit or value["build"]["base_images"] != bases):
            raise BuildError("control_build_result_mismatch")
        if mode == "release":
            verify_release(value, source_commit)
        if output:
            output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return value


def export(image, destination, *, source_commit=None):
    value = verify_release(inspect_image(image), source_commit)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise BuildError("control_export_exists_use_new_destination")
    destination.mkdir(parents=True)
    partial = destination / "control-image.tar.partial"
    command("docker", "save", "--output", str(partial), value["image_id"], timeout=900)
    if json.loads(command("docker", "image", "inspect", image))[0]["Id"] != value["image_id"]:
        raise BuildError("control_image_changed_during_export")
    archive = destination / "control-image.tar"
    partial.rename(archive)
    result = {"format": 1, "package_kind": "control_image_only", **value, "archive": archive.name,
              "archive_sha256": checksum(archive), "runtime_environment_validation": "not_implied",
              "excluded": ["account_data", "credentials", "databases", "runtime_volumes"]}
    (destination / "release-manifest.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (destination / "SHA256SUMS").write_text("".join(checksum(p) + "  " + p.name + "\n" for p in sorted(destination.iterdir()) if p.is_file()), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for mode in ("dev", "release"):
        sub = commands.add_parser(mode)
        sub.add_argument("--tag")
        sub.add_argument("--output", type=Path)
        if mode == "release":
            sub.add_argument("--commit", required=True)
    sub = commands.add_parser("inspect")
    sub.add_argument("--image", required=True)
    sub = commands.add_parser("export")
    sub.add_argument("--image", required=True)
    sub.add_argument("--destination", type=Path, required=True)
    sub.add_argument("--commit")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            value = inspect_image(args.image)
        elif args.action == "export":
            value = export(args.image, args.destination, source_commit=args.commit)
        else:
            value = build(mode=args.action, commit=getattr(args, "commit", None), tag=args.tag, output=args.output)
        print(json.dumps({"status": "passed", **value}, ensure_ascii=False))
    except (BuildError, DeliveryError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
