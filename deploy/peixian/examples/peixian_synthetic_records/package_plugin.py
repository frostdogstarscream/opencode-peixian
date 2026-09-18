"""Package only the reviewed Peixian synthetic-records plugin files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "plugin"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=ROOT / "dist" / "peixian-synthetic-records-1.0.0.zip")
parser.add_argument("--version", default="1.0.0")
options = parser.parse_args()

if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", options.version):
    raise SystemExit("invalid_version")

manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
manifest["version"] = options.version
entry = (PLUGIN / "entry.mjs").read_text(encoding="utf-8").replace('const VERSION = "1.0.0";', "const VERSION = " + json.dumps(options.version) + ";")

options.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(options.output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    archive.writestr("entry.mjs", entry)

print("Packaged peixian-synthetic-records " + options.version)
