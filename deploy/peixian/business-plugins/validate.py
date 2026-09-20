import json
from pathlib import Path
import re
import sys


root = Path(__file__).resolve().parent
plugin_ids = set()
tool_ids = set()
errors = []

for directory in sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("peixian-")):
    manifest_path = directory / "manifest.json"
    entry_path = directory / "entry.mjs"
    skill_path = directory / "SKILL.md"
    if not all(path.is_file() for path in (manifest_path, entry_path, skill_path)):
        errors.append(f"{directory.name}: manifest.json, entry.mjs and SKILL.md are required")
        continue
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("id") != directory.name or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", manifest.get("id", "")):
        errors.append(f"{directory.name}: invalid plugin id")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest.get("version", "")):
        errors.append(f"{directory.name}: invalid version")
    if manifest.get("opencode_version") != "1.18.30" or manifest.get("entry") != "entry.mjs":
        errors.append(f"{directory.name}: unsupported OpenCode version or entry")
    if manifest["id"] in plugin_ids:
        errors.append(f"{directory.name}: duplicate plugin id")
    plugin_ids.add(manifest["id"])
    for tool_id in manifest.get("tools", []):
        if not re.fullmatch(r"peixian_[a-z0-9_]+", tool_id) or tool_id in tool_ids:
            errors.append(f"{directory.name}: invalid or duplicate tool {tool_id}")
        tool_ids.add(tool_id)
    if manifest.get("connections") != {"peixian_data": {"description": "沛县公安统一数据适配服务"}}:
        errors.append(f"{directory.name}: unexpected connection declaration")
    source = manifest_path.read_text(encoding="utf-8") + entry_path.read_text(encoding="utf-8")
    if re.search(r"https?://|appSecret\s*[:=]|apikey\s*=", source, re.IGNORECASE):
        errors.append(f"{directory.name}: package source contains a URL or credential-like literal")
    frontmatter = skill_path.read_text(encoding="utf-8").splitlines()
    if len(frontmatter) < 5 or frontmatter[0] != "---" or "name:" not in frontmatter[1] or "description:" not in frontmatter[2]:
        errors.append(f"{directory.name}: invalid SKILL.md frontmatter")

business_skills = root.parent / "business-skills"
for skill_path in business_skills.glob("*/SKILL.md"):
    frontmatter = skill_path.read_text(encoding="utf-8").splitlines()
    if len(frontmatter) < 5 or frontmatter[0] != "---" or "name:" not in frontmatter[1] or "description:" not in frontmatter[2]:
        errors.append(f"{skill_path.parent.name}: invalid business SKILL.md frontmatter")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"Validated {len(plugin_ids)} plugins, {len(tool_ids)} tools and {len(list(business_skills.glob('*/SKILL.md')))} business skills")
