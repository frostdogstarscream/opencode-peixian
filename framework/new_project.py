"""Create a clean project from the framework's committed template, without runtime data."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import subprocess
import tarfile
import tempfile
from config import ROOT, validate

ROOT_FILES = {".dockerignore", ".editorconfig", ".gitattributes", ".gitignore",
              ".oxlintrc.json", ".prettierignore", "AGENTS.md", "LICENSE", "SECURITY.md",
              "package.json", "bun.lock", "bunfig.toml", "tsconfig.json", "turbo.json"}
ENGINE_FILES = {"console-runtime.py", "console-worker.py", "Managed.Dockerfile", "managed-entrypoint.sh"}
PRIVATE_PARTS = {".git", ".secrets", ".runtime", ".venv", "node_modules", "output",
                 "dist", "__pycache__", ".pytest_cache", ".test-runs"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

def path_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or "\\" in name or any(
            part in ("", ".", "..") or ":" in part or part.rstrip(". ") != part
            or part.split(".")[0].upper() in RESERVED for part in path.parts)):
        raise ValueError("Template contains a nonportable or unsafe path")
    return path

def included(name):
    path = path_name(name)
    if any(part.casefold() in PRIVATE_PARTS or part.casefold().startswith(".env") for part in path.parts):
        return False
    if path.suffix.casefold() in (".password", ".key") or path.name.casefold().endswith("deepseek-key"):
        return False
    if name in ROOT_FILES or name == ".github/TEAM_MEMBERS":
        return True
    if name.startswith(("packages/", "patches/", "framework/", "services/peixian-control/")):
        return True
    return path.parent.as_posix() == "deploy/peixian" and path.name in ENGINE_FILES

def export_sources(archive, selected):
    members = {m.name.rstrip("/"): m for m in archive.getmembers()}
    result = {}
    def expand(output_name, member, seen):
        if member.name in seen or len(seen) > 32:
            raise ValueError("Template contains a link cycle")
        if member.isfile():
            result[output_name] = member
            return
        if not member.issym() or member.linkname.startswith("/") or "\\\\" in member.linkname:
            raise ValueError("Template contains an unsupported or unsafe link")
        target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
        path_name(target)
        candidate = members.get(target)
        if candidate is None:
            raise ValueError("Template link points outside exported source")
        if not candidate.isdir():
            if target not in selected:
                raise ValueError("Template link points outside exported source")
            expand(output_name, candidate, seen | {member.name})
            return
        children = {name: value for name, value in selected.items() if name.startswith(target + "/")}
        if not children:
            raise ValueError("Template directory link has no exported content")
        for name, child in children.items():
            expand(output_name + "/" + name[len(target) + 1:], child, seen | {member.name})
    for name, member in selected.items():
        expand(name, member, set())
    folded = [name.casefold() for name in result]
    if len(folded) != len(set(folded)):
        raise ValueError("Template paths collide on case-insensitive filesystems")
    return result

def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError("Template Git operation failed")
    return result.stdout.strip()

def create_project(destination, profile, *, source=ROOT, initialize_git=False):
    profile = validate(profile)
    source = Path(source).resolve()
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must not exist; existing files are never overwritten")
    resolved = destination.resolve()
    if resolved == source or resolved.is_relative_to(source):
        raise ValueError("Create the new project outside the framework source directory")
    if not destination.parent.is_dir():
        raise ValueError("Destination parent must already exist")
    if git(source, "status", "--porcelain"):
        raise ValueError("Commit the framework changes before generating a project")
    commit = git(source, "rev-parse", "HEAD")
    with tempfile.TemporaryFile() as stream:
        operation = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", commit],
                                   stdout=stream, stderr=subprocess.PIPE)
        if operation.returncode:
            raise ValueError("Could not export the committed framework")
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            selected = {m.name: m for m in archive.getmembers() if not m.isdir() and included(m.name)}
            required = {"framework/manage.py", "framework/config.py", "framework/project.json",
                        "LICENSE", "package.json", "services/peixian-control/control/app.py"}
            if not required.issubset(selected):
                raise ValueError("Source commit is not a complete framework template")
            sources = export_sources(archive, selected)
            destination.mkdir(mode=0o755)
            for name, member in sources.items():
                target = destination.joinpath(*path_name(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as content, target.open("xb") as output:
                    while block := content.read(1024 * 1024):
                        output.write(block)
                if os.name != "nt":
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
    (destination / "framework/project.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = {"template_commit": commit, "template_format": 1, "project_id": profile["project_id"],
                  "symlinks": "materialized_from_tracked_included_files", "includes_runtime_data": False}
    (destination / "framework/template-origin.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    readme = ("# " + profile["display_name"] + "\n\n" + profile["tagline"] + "\n\n"
              "由 AI 应用框架生成的独立业务项目。开始使用请阅读 [框架入口](framework/README.md)。\n\n"
              "先安装开发依赖，再运行 `python framework/manage.py doctor` 和 `init`。"
              "新项目没有继承账号、模型密钥、插件凭据、历史会话或 Docker 数据卷。\n\n"
              "源码保留 OpenCode 的 [MIT 许可证](LICENSE)，模板提交记录见 "
              "[template-origin.json](framework/template-origin.json)。\n")
    (destination / "README.md").write_text(readme, encoding="utf-8")
    if initialize_git:
        git(destination, "init", "--initial-branch=main")
    return {"destination": str(destination), "template_commit": commit, "files": len(sources),
            "project_id": profile["project_id"], "git_initialized": initialize_git}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--name", required=True, dest="display_name")
    parser.add_argument("--tagline", default="面向企业的 AI 应用工作台")
    parser.add_argument("--port", type=int, default=14100)
    parser.add_argument("--max-runtimes", type=int, default=4)
    parser.add_argument("--git-init", action="store_true")
    args = parser.parse_args()
    profile = {"schema_version": 1, "project_id": args.project_id, "display_name": args.display_name,
               "tagline": args.tagline, "console_port": args.port, "max_runtimes": args.max_runtimes}
    print(json.dumps(create_project(args.destination, profile, initialize_git=args.git_init), ensure_ascii=False))

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, tarfile.TarError) as error:
        print(str(error), file=__import__("sys").stderr)
        raise SystemExit(1) from None
