import argparse
import hashlib
import json
from pathlib import Path
import zipfile


root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="Package reviewed Peixian business plugins without credentials or development files.")
parser.add_argument("--plugin", help="Plugin id; omit to package every peixian-* directory")
parser.add_argument("--output", type=Path, default=root.parent / "dist" / "plugins")
args = parser.parse_args()

directories = [root / args.plugin] if args.plugin else sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("peixian-"))
args.output.mkdir(parents=True, exist_ok=True)

for directory in directories:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    output = args.output / f"{manifest['id']}-{manifest['version']}.zip"
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")
    entry = directory / manifest["entry"]
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        archive.write(entry, manifest["entry"])
    if output.stat().st_size > 20 * 1024 * 1024:
        output.unlink()
        raise SystemExit(f"package exceeds 20 MiB: {output}")
    print(f"{output.name}  {hashlib.sha256(output.read_bytes()).hexdigest()}")
