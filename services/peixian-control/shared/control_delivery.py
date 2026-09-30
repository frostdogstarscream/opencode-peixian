"""Build and verify the immutable Control frontend inventory (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit, unquote

FORMAT = 1
SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
HASHED_ASSET = re.compile(r"(?:^|/)[^/]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")


class DeliveryError(RuntimeError):
    """A fixed diagnostic code, never a private path or file content."""


def checksum(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inventory(static):
    root = Path(static)
    if root.is_symlink() or not root.is_dir():
        raise DeliveryError("control_static_missing")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise DeliveryError("control_static_link_forbidden")
        if path.is_dir():
            continue
        if not path.is_file():
            raise DeliveryError("control_static_nonregular_file")
        name = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in PurePosixPath(name).parts):
            raise DeliveryError("control_static_hidden_file")
        if name.endswith(".map"):
            raise DeliveryError("control_static_sourcemap_forbidden")
        files[name] = {"sha256": checksum(path), "bytes": path.stat().st_size}
    if "index.html" not in files or not any(name.startswith("assets/") for name in files):
        raise DeliveryError("control_static_entry_missing")
    return files


def frontend_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get("src") if tag in ("script", "img") else attrs.get("href") if tag == "link" else None
        if value:
            self.paths.append(value)


def check_entry(static, files):
    parser = References()
    try:
        parser.feed((Path(static) / "index.html").read_text(encoding="utf-8"))
    except (UnicodeError, OSError):
        raise DeliveryError("control_static_entry_unreadable") from None
    for value in parser.paths:
        parsed = urlsplit(value)
        name = unquote(parsed.path).lstrip("/")
        if (parsed.scheme or parsed.netloc or not name or ".." in PurePosixPath(name).parts
                or name not in files):
            raise DeliveryError("control_static_entry_reference_invalid")
    if not any(path.startswith("/assets/") and urlsplit(path).path.endswith(".js") for path in parser.paths):
        raise DeliveryError("control_static_script_missing")


def generate(static, *, mode, source_commit=None, input_digest=None, base_images=None):
    if mode not in ("dev", "release"):
        raise DeliveryError("control_build_mode_invalid")
    if mode == "release" and (not COMMIT.fullmatch(source_commit or "") or not SHA.fullmatch(input_digest or "")):
        raise DeliveryError("control_release_identity_required")
    files = inventory(static)
    check_entry(static, files)
    value = {"format": FORMAT, "mode": mode, "source_commit": source_commit if mode == "release" else None,
             "input_digest": input_digest or None, "frontend_digest": frontend_digest(files),
             "base_images": base_images or {}, "files": files}
    value["build_id"] = mode + "-" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]
    return value


def verify(static, manifest):
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("mode") not in ("dev", "release"):
        raise DeliveryError("control_build_manifest_invalid")
    expected = generate(static, mode=manifest["mode"], source_commit=manifest.get("source_commit"),
                        input_digest=manifest.get("input_digest"), base_images=manifest.get("base_images"))
    if expected != manifest:
        raise DeliveryError("control_static_manifest_mismatch")
    return manifest


def load(static, manifest_path, *, required=False):
    path = Path(manifest_path)
    if not path.exists() and not required:
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise DeliveryError("control_build_manifest_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DeliveryError("control_build_manifest_unreadable") from None
    return verify(static, value)


def public_build(manifest):
    return {name: manifest[name] for name in ("mode", "source_commit", "build_id", "frontend_digest")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("dev", "release"), required=True)
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--input-digest", default="")
    parser.add_argument("--frontend-base", required=True)
    parser.add_argument("--runtime-base", required=True)
    args = parser.parse_args()
    value = generate(args.static, mode=args.mode, source_commit=args.source_commit, input_digest=args.input_digest,
                     base_images={"frontend": args.frontend_base, "runtime": args.runtime_base})
    args.output.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
