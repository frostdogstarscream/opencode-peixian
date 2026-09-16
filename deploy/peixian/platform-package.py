"""Assemble an allowlisted offline deployment directory; never include runtime data."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/peixian"
ALLOWED_FILES = (
    "LICENSE",
    "deploy/peixian/platform-capacity.py", "deploy/peixian/platform-sample.py",
    "deploy/peixian/server/platform.50-io.example.json",
    "deploy/peixian/server/platform.orchestration.example.json",
    "deploy/peixian/platform-config.py", "deploy/peixian/platform-manage.py", "deploy/peixian/platform-backup.py",
    "deploy/peixian/platform-package.py", "deploy/peixian/platform.ps1", "deploy/peixian/console-worker.py",
    "deploy/peixian/console-runtime.py", "deploy/peixian/console-guard.py", "deploy/peixian/plugin-client.mjs",
    "deploy/peixian/requirements.txt", "deploy/peixian/GENERIC_PLATFORM.md", "deploy/peixian/GENERIC_USER_GUIDE.md", "deploy/peixian/PLUGIN_DEVELOPER_GUIDE.md",
    "deploy/peixian/server/README.md", "deploy/peixian/server/nginx.conf", "deploy/peixian/server/platform.example.json",
    "deploy/peixian/server/agent-platform-worker.service", "deploy/peixian/examples/package-plugin.py",
    "deploy/peixian/examples/platform-python.py", "deploy/peixian/examples/records-api.py",
    "deploy/peixian/examples/records-plugin/entry.mjs", "deploy/peixian/examples/records-plugin/manifest.json",
    "deploy/peixian/examples/records-plugin/SKILL.md", "services/peixian-control/docs/openapi.json",
    "services/peixian-control/requirements.lock",
    "services/peixian-control/shared/orchestration_config.py",
    "deploy/peixian/constrained-test.py",
    "deploy/peixian/r2-acceptance.py", "deploy/peixian/R2_ACCEPTANCE.md",
    "deploy/peixian/r2-local-smoke.py", "deploy/peixian/R2_LOCAL_OPERATIONS.md",
    "deploy/peixian/reports/R2_LOCAL_REPORT.md",
    "deploy/peixian/reports/r2-local-smoke-01.json", "deploy/peixian/reports/r2-local-smoke-final.json",
    "deploy/peixian/reports/r2-local-smoke-verified.json",
    "services/peixian-control/docs/schema_v4_protocol.md",
    "services/peixian-control/gateway/README.md",
    "services/peixian-control/examples/console_client.py",
    "services/peixian-control/benchmarks/platform_load.py",
    "services/peixian-control/benchmarks/control_layer_load.py",
    "services/peixian-control/benchmarks/CONTROL_LAYER_LOAD.md",
    "services/peixian-control/docs/HARDENING_R1.md",
    "services/peixian-control/docs/HARDENING_R1_REPORT.md",
)
OPTIONAL_FILES = ("deploy/peixian/GENERIC_ACCEPTANCE_REPORT.md", "deploy/peixian/examples/openai-fixture.py")
ARTIFACTS = {"images.tar", "source.tar.gz", "source.tar", "release-manifest.json", "SHA256SUMS", "README.md"}
FORBIDDEN = {".runtime", ".secrets", ".private", "output", "__pycache__", ".git", "node_modules", ".venv"}


class PackageError(RuntimeError):
    pass


def command(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise PackageError("package_command_failed")
    return result.stdout.strip()


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def archive_images(path):
    """Read Docker save's own config IDs, so rebuilt local tags cannot falsify provenance."""
    with tarfile.open(path, "r:") as archive:
        try:
            member = archive.getmember("manifest.json")
            if not member.isfile() or member.size > 1024 * 1024:
                raise PackageError("invalid_docker_archive_manifest")
            manifest = json.load(archive.extractfile(member))
        except (KeyError, ValueError):
            raise PackageError("docker_save_archive_required") from None
        indexes = {}
        try:
            index_member = archive.getmember("index.json")
        except KeyError:
            index_member = None
        if index_member is not None:
            if not index_member.isfile() or index_member.size > 4 * 1024 * 1024:
                raise PackageError("invalid_oci_image_index")
            index = json.load(archive.extractfile(index_member))
            for descriptor in index.get("manifests", []):
                tag = (descriptor.get("annotations") or {}).get("io.containerd.image.name", "")
                indexes[tag.removeprefix("docker.io/library/")] = descriptor.get("digest")
        result = {}
        for item in manifest:
            name = item.get("Config", "")
            if not isinstance(name, str) or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                raise PackageError("invalid_image_config_path")
            member = archive.getmember(name)
            if not member.isfile() or member.size > 4 * 1024 * 1024:
                raise PackageError("invalid_image_config")
            raw = archive.extractfile(member).read()
            config = json.loads(raw)
            for tag in item.get("RepoTags") or []:
                if tag in result:
                    raise PackageError("duplicate_exported_image_tag")
                result[tag] = {"tag": tag, "config_id": "sha256:" + hashlib.sha256(raw).hexdigest(),
                               "archive_image_id": indexes.get(tag),
                               "os": config.get("os"), "architecture": config.get("architecture"),
                               "created": config.get("created"), "labels": config.get("config", {}).get("Labels") or {}}
        return result


def safe_source(path):
    if not path.is_file() or any(item.is_symlink() for item in (path, *path.parents)):
        raise PackageError("package_source_missing_or_link")
    relative = path.relative_to(ROOT)
    if any(part in FORBIDDEN for part in relative.parts):
        raise PackageError("private_source_path_forbidden")


def validate_output(folder, expected):
    if any(item.is_symlink() for item in (folder, *folder.parents)):
        raise PackageError("package_output_must_not_be_link")
    if not folder.exists():
        return
    for path in folder.rglob("*"):
        relative = path.relative_to(folder).as_posix()
        if path.is_symlink() or any(part in FORBIDDEN for part in path.relative_to(folder).parts):
            raise PackageError("unexpected_private_or_link_output")
        if path.is_file() and relative not in expected:
            raise PackageError("unexpected_output_file_preserved")


def assemble(destination, wheels, commit, *, export_images=False, config_path=None, source_only=False):
    if not re.fullmatch(r"(?:HEAD|[0-9a-fA-F]{7,40})", commit):
        raise PackageError("source_commit_requires_head_or_sha")
    full_commit = command("git", "rev-parse", "--verify", commit + "^{commit}")
    destination = Path(destination).absolute()
    if not destination.resolve().is_relative_to((DEPLOY / "dist").resolve()):
        raise PackageError("package_destination_must_be_inside_deployment_dist")
    wheel_root = Path(wheels).resolve()
    wheel_files = sorted(wheel_root.glob("*.whl"))
    if not wheel_files:
        raise PackageError("offline_wheelhouse_missing")
    for path in wheel_files:
        if path.is_symlink() or "win_" in path.name or "macosx" in path.name:
            raise PackageError("wheelhouse_requires_linux_or_portable_wheels")
    selected = [*ALLOWED_FILES, *(name for name in OPTIONAL_FILES if (ROOT / name).is_file())]
    for name in selected:
        safe_source(ROOT / name)
    expected = set(selected) | ARTIFACTS | {"wheels/" + path.name for path in wheel_files}
    validate_output(destination, expected)
    destination.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("platform_config_package", DEPLOY / "platform-config.py")
    settings = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = settings
    spec.loader.exec_module(settings)
    cfg = settings.load_config(config_path) if config_path is not None else None
    expected_images = cfg.images if cfg else settings.IMAGES
    config_version = cfg.version if cfg else 1
    effective_config = ({"version": cfg.version, "profile": cfg.profile, "max_runtimes": cfg.max_runtimes,
                         "control_resources": cfg.control_resources, "resource_limits": cfg.resource_limits,
                         "capacity_policy": cfg.capacity_policy, "concurrency": cfg.concurrency,
                         "orchestration": cfg.orchestration,
                         "resource_budget": cfg.resource_budget} if cfg else {"version": 1})
    archive = destination / "images.tar"
    if source_only and archive.exists():
        raise PackageError("source_only_package_must_not_include_old_images")
    if export_images and not source_only:
        if archive.exists():
            raise PackageError("existing_images_archive_preserved_use_assemble")
        partial = destination / "images.tar.partial"
        if partial.exists():
            raise PackageError("previous_partial_archive_preserved")
        with partial.open("xb") as output:
            result = subprocess.run(["docker", "save", *expected_images.values()], stdout=output, stderr=subprocess.PIPE)
        if result.returncode:
            raise PackageError("image_export_failed_partial_preserved")
        partial.rename(archive)
    images = {}
    if not source_only:
        if not archive.is_file():
            raise PackageError("export_images_before_assemble")
        images = archive_images(archive)
        if set(images) != set(expected_images.values()):
            raise PackageError("exported_image_tags_do_not_match_platform_version")
        if any(item["os"] != "linux" or item["architecture"] != "amd64" for item in images.values()):
            raise PackageError("exported_images_require_linux_amd64")
        try:
            settings.image_supports_config(images[expected_images["control"]]["labels"], config_version)
            for name, tag in expected_images.items():
                settings.image_supports_orchestration(images[tag]["labels"], name, config_version)
        except settings.ConfigError as error:
            raise PackageError(str(error)) from None
    else:
        source_archive = destination / "source.tar.gz"
        if source_archive.exists():
            raise PackageError("source_archive_already_exists_use_new_destination")
        # Archive only the chosen Git commit; never sweep workspace credentials.
        command("git", "archive", "--format=tar.gz", "--output=" + str(source_archive), full_commit)
    for tag, item in images.items():
        try:
            local = json.loads(command("docker", "image", "inspect", tag))[0]
            item["local_image_id"] = local["Id"]
            item["local_matches_archive"] = local["Id"] in (item["config_id"], item["archive_image_id"])
        except (PackageError, ValueError, KeyError, IndexError):
            item["local_image_id"] = None
            item["local_matches_archive"] = None
    for name in selected:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (destination / "wheels").mkdir(exist_ok=True)
    for path in wheel_files:
        shutil.copyfile(path, destination / "wheels" / path.name)
    readme = """# Agent 工作台离线部署包

目标：Ubuntu 24.04、x86_64、Docker Engine、Compose v2、Python 3.12。

1. 先运行 `sha256sum -c SHA256SUMS` 验证所有文件。
2. 运行 `docker load -i images.tar` 导入四个明确版本的镜像。
3. 按 `deploy/peixian/server/README.md` 配置 HTTPS、初始化私密目录并启动。
4. Python 依赖位于 `wheels/`；安装必须使用 `--no-index --find-links wheels`。

Docker/Compose、Python/venv、ACL 和操作系统 CA 包需预先安装；本包不包含 Ubuntu 系统 deb 包。
不包含账号、密码、密钥、数据库、运行目录或备份。首次部署会生成新的超级管理员临时密码。
`release-manifest.json` 记录源码状态、镜像归档内部 ID 和校验信息。只有 source_matches_commit=true 才表示部署源码对应所记录提交。
"""
    if source_only:
        readme = """# Agent 工作台并发加固：源码与工具包（不含镜像）

本包不是可直接离线安装的完整部署包。Docker 引擎或镜像验收未完成时，不以旧镜像代替本次版本。
source.tar.gz 为清单 source_commit 对应的已提交源码；部署脚本、配置模板和 Linux Python wheels 另行提供。
images.tar 不存在。镜像构建、Linux 容器运行、真实 50 环境容量与目标服务器验收仍需执行。
先校验 SHA256SUMS，再解压源码并按匹配版本构建镜像。真实凭据、账号与运行卷不包含在包中。
清单 source_matches_commit=false 时，随包部署脚本还包含未提交修改，不能声称它们属于归档提交。
"""
    (destination / "README.md").write_text(readme, encoding="utf-8")
    matches = True
    for name in selected:
        result = subprocess.run(["git", "show", full_commit + ":" + name], cwd=ROOT, capture_output=True)
        if result.returncode or result.stdout != (ROOT / name).read_bytes():
            # Git may normalize CRLF in checked-out files; compare canonical source.
            if result.returncode or result.stdout.replace(b"\r\n", b"\n") != (ROOT / name).read_bytes().replace(b"\r\n", b"\n"):
                matches = False
    manifest = {"format": 1, "product": "Agent 工作台", "source_commit": full_commit,
                "source_matches_commit": matches, "working_tree_clean": not bool(command("git", "status", "--porcelain")),
                "target": {"os": "Ubuntu 24.04", "architecture": "amd64", "python": "3.12", "docker": "Engine + Compose v2"},
                "control_schema_version": 4, "worker_protocol_version": 2, "runtime_protocol_version": 2,
                "opencode_version": "1.18.30",
                "package_kind": "source_and_tools_without_images" if source_only else "offline_deployment",
                "platform_config_version": config_version, "effective_config": effective_config,
                "requested_images": expected_images, "images_included": not source_only,
                "capacity_50_validation": "not_performed",
                "images": sorted(images.values(), key=lambda item: item["tag"]),
                "proxy_upstream": settings.PROXY_UPSTREAM,
                "excluded": ["accounts", "credentials", "databases", "runtime_data", "private_backups", "Ubuntu_deb_packages"],
                "ubuntu_host_validation": "not_performed", "intranet_vllm_validation": "not_performed",
                "files": {path.relative_to(destination).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
                          for path in sorted(destination.rglob("*")) if path.is_file() and path.name not in ("release-manifest.json", "SHA256SUMS")}}
    (destination / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [path for path in sorted(destination.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    sums = "".join(sha256(path) + "  " + path.relative_to(destination).as_posix() + "\n" for path in files)
    (destination / "SHA256SUMS").write_text(sums, encoding="utf-8")
    validate_output(destination, expected)
    return {"status": "assembled", "files": len(files) + 1, "images": len(images), "source_commit": full_commit,
            "source_matches_commit": matches, "manifest_sha256": sha256(destination / "release-manifest.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEPLOY / "dist/agent-platform-v1-linux-amd64")
    parser.add_argument("--wheels", type=Path, default=DEPLOY / "dist/platform/linux-wheels")
    parser.add_argument("--source-commit", default="HEAD")
    parser.add_argument("--assemble", action="store_true", help="Use the existing images.tar; never re-export or overwrite it")
    parser.add_argument("--config", type=Path, help="Select the exact image/config version; config file itself is not copied")
    parser.add_argument("--source-only", action="store_true", help="Export committed source/tools/wheels, explicitly without images")
    args = parser.parse_args()
    try:
        print(json.dumps(assemble(args.destination, args.wheels, args.source_commit, export_images=not args.assemble,
                                  config_path=args.config, source_only=args.source_only), ensure_ascii=False))
    except (PackageError, OSError, ValueError, tarfile.TarError) as error:
        print(json.dumps({"status": "failed", "error": str(error) if isinstance(error, PackageError) else "offline_package_failed"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
