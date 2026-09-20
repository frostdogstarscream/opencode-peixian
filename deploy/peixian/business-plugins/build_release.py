import argparse
import hashlib
from pathlib import Path
import shutil


root = Path(__file__).resolve().parent
repository = root.parents[2]
parser = argparse.ArgumentParser(description="Assemble a credential-free Peixian plugin release directory.")
parser.add_argument("--version", default="1.0.0")
parser.add_argument("--output", type=Path, default=root.parent / "dist" / "release")
arguments = parser.parse_args()
target = arguments.output / f"peixian-data-plugins-{arguments.version}"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

(target / "plugins").mkdir(parents=True)
(target / "skills").mkdir()
for package in sorted((root.parent / "dist" / "plugins").glob("*.zip")):
    shutil.copy2(package, target / "plugins" / package.name)

skill_names = {
    "relationship-analysis": "关系人综合分析.md",
    "multi-dimensional-collision": "多维信息碰撞分析.md",
    "night-activity-analysis": "夜间活动分析.md",
    "vehicle-use-analysis": "驾乘车辆分析.md",
    "entity-cross-query": "关联互查与综合查询.md",
}
for directory, name in skill_names.items():
    shutil.copy2(root.parent / "business-skills" / directory / "SKILL.md", target / "skills" / name)

documents = {
    repository / "specs" / "peixian-data-adapter-openapi.yaml": "adapter-openapi.yaml",
    repository / "specs" / "peixian-data-plugin-field-mapping.md": "field-mapping.md",
    root / "connection-requirements.md": "connection-requirements.md",
    root / "TEST_SERVER_IMPORT.md": "test-server-import.md",
    root / "test-report.md": "test-report.md",
    root / "release-notes.md": "release-notes.md",
}
for source, name in documents.items():
    shutil.copy2(source, target / name)

files = sorted(path for path in target.rglob("*") if path.is_file())
(target / "SHA256SUMS.txt").write_text(
    "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(target).as_posix()}\n" for path in files),
    encoding="utf-8",
)
print(target)
