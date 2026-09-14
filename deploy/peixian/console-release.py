"""Record source/image provenance for the local, secret-free image export."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ["peixian-control:console-r1", "peixian-gateway:console-r1", "peixian-opencode:1.18.30-managed-r1"]

def command(*values):
    result = subprocess.run(values, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("release_command_failed")
    return result.stdout.strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "deploy/peixian/dist/console/peixian-console-images.tar")
    args = parser.parse_args()
    archive = args.archive.resolve()
    allowed = (ROOT / "deploy/peixian/dist/console").resolve()
    if not archive.is_relative_to(allowed) or not archive.is_file():
        raise RuntimeError("release_archive_must_exist_in_export_directory")
    if command("git", "status", "--porcelain"):
        raise RuntimeError("commit_reviewed_source_before_recording_release")
    checksum = hashlib.sha256()
    with archive.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            checksum.update(block)
    items = []
    for tag in IMAGES:
        image = json.loads(command("docker", "image", "inspect", tag))[0]
        items.append({"tag": tag, "id": image["Id"], "os": image["Os"], "architecture": image["Architecture"],
                      "created": image["Created"], "size": image["Size"], "repository_digests": image.get("RepoDigests", [])})
    frontend = ROOT / "packages/peixian-console/dist/assets"
    assets = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(frontend.glob("*")) if path.is_file()}
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": command("git", "rev-parse", "HEAD"),
        "branch": command("git", "branch", "--show-current"),
        "baseline": "c5632f795b4efefdaf6d31c24c120a1761ff6b98",
        "opencode_version": "1.18.30",
        "archive": archive.name, "archive_bytes": archive.stat().st_size, "archive_sha256": checksum.hexdigest(),
        "images": items, "frontend_assets": assets,
        "excludes": ["account_data", "credentials", "control_database", "private_snapshots"],
        "intranet_vllm_live_test": "not_performed",
        "provenance_note": "Image digests identify the accepted build; apt repositories are not snapshotted for byte-for-byte rebuilds."
    }
    target = archive.parent / "release-manifest.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(target), "source_commit": report["source_commit"], "archive_bytes": report["archive_bytes"], "sha256": report["archive_sha256"]}))

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "code": str(error) if isinstance(error, RuntimeError) else "release_recording_failed"}))
        raise SystemExit(1) from None
