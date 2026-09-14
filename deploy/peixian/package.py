"""Package the no-model baseline and opt-in DeepSeek materials from a file allowlist."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "3104c1428ec91f809e5ab86631300de41eb6952e"
IMAGE_NAME = "peixian-opencode:1.18.30-r1"
PLATFORM = "linux/amd64"
ARCHIVE_ROOT = "peixian-deployment"
IMAGE_ARCHIVE = "peixian-opencode-1.18.30-r1-linux-amd64.tar"
FILES = (
    "README.md", "ACCEPTANCE.md", "DEEPSEEK.md", "Dockerfile", "compose.yaml",
    # Optional profile files do not enable it: no credentials or runtime marker are packaged.
    "compose.deepseek.yaml", "config/deepseek.json", "api-forward.py", "deepseek.ps1", "deepseek_verify.py",
    "entrypoint.sh", "healthcheck.py", "manage.ps1", "manage.sh",
    "verify.py", "client.py", "cold_start.py", "tcp-forward.py", "requirements.txt", "package.py",
    ".gitignore", ".dockerignore", ".gitattributes",
    "config/opencode.json", "config/package.json", "config/package-lock.json",
    "config/vllm.example.json", "evidence/api-isolation.json",
    "evidence/browser.json", "evidence/cold-start.json",
    "evidence/windows-lifecycle.json", "evidence/browser-client-a.json", "evidence/browser-client-b.json",
    "evidence/browser-client-a.png", "evidence/browser-client-b.png",
    "evidence/deepseek-preflight.json", "evidence/deepseek-network.json", "evidence/deepseek-live.json",
    "evidence/deepseek-lifecycle.json", "evidence/deepseek-browser.json",
    "evidence/deepseek-browser-client-a.png", "evidence/deepseek-browser-client-b.png",
)


def source_file(root, relative):
    path = root / relative
    # Do not allow an approved filename to point at a secret or another directory.
    if path.resolve(strict=True) != path.absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"Package input must be a regular file without links: {relative}")
    return path


def validate_evidence(contents, image_id):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("An inspected sha256 image ID is required")
    compose_hash = hashlib.sha256(contents["compose.yaml"]).hexdigest()
    api = json.loads(contents["evidence/api-isolation.json"])
    if api.get("status") != "passed" or api.get("lifecycle_completed") is not True or api.get("compose_sha256") != compose_hash:
        raise ValueError("API, isolation, and lifecycle evidence does not match this Compose file")
    for name in ("client-a", "client-b", "client-a-entry", "client-b-entry"):
        runtime = api.get("runtime", {}).get(name, {})
        if runtime.get("image_id") != image_id or runtime.get("platform") != PLATFORM:
            raise ValueError(f"API evidence does not match the image and platform for {name}")
    for name in ("browser", "cold-start"):
        evidence = json.loads(contents[f"evidence/{name}.json"])
        if evidence.get("status") != "passed" or evidence.get("image_id") != image_id or evidence.get("compose_sha256") != compose_hash:
            raise ValueError(f"{name} evidence does not match this image and Compose file")
    return compose_hash


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_member(archive, name, limit=None):
    member = archive.getmember(name)
    if not member.isfile() or (limit is not None and member.size > limit):
        raise ValueError("Invalid Docker image archive member")
    return member


def archive_json(archive, name):
    member = archive_member(archive, name, 10 * 1024 * 1024)
    with archive.extractfile(member) as handle:
        return json.load(handle)


def stream_sha256(handle):
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    return "sha256:" + digest.hexdigest()


def verify_descriptor(archive, descriptor, verified):
    digest = descriptor.get("digest", "")
    size = descriptor.get("size")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or type(size) is not int or size < 0:
        raise ValueError("Invalid OCI descriptor digest or size")
    name = "blobs/" + digest.replace(":", "/")
    member = archive_member(archive, name)
    if member.size != size:
        raise ValueError("OCI descriptor size does not match its blob")
    if digest not in verified:
        with archive.extractfile(member) as handle:
            if stream_sha256(handle) != digest:
                raise ValueError("OCI descriptor digest does not match its blob")
        verified.add(digest)
    return name


def inspect_oci_image(archive, image_id, config_digest, layers):
    index_types = {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
    manifest_types = {"application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"}
    index = archive_json(archive, "index.json")
    roots = [item for item in index.get("manifests", []) if item.get("digest") == image_id]
    if index.get("schemaVersion") != 2 or len(roots) != 1:
        raise ValueError("The OCI archive does not reference the accepted image ID")
    annotations = roots[0].get("annotations", {})
    names = {IMAGE_NAME, "docker.io/library/" + IMAGE_NAME}
    if annotations.get("io.containerd.image.name") and annotations["io.containerd.image.name"] not in names:
        raise ValueError("The OCI image name does not match the expected tag")
    if annotations.get("org.opencontainers.image.ref.name") and annotations["org.opencontainers.image.ref.name"] not in names | {IMAGE_NAME.rsplit(":", 1)[1]}:
        raise ValueError("The OCI image reference does not match the expected tag")
    verified = set()
    visited = set()
    images = []

    def visit(descriptor, depth=0):
        if depth > 16:
            raise ValueError("OCI descriptor nesting is too deep")
        name = verify_descriptor(archive, descriptor, verified)
        if name in visited:
            return
        visited.add(name)
        document = archive_json(archive, name)
        media_type = descriptor.get("mediaType")
        if document.get("schemaVersion") != 2 or document.get("mediaType", media_type) != media_type:
            raise ValueError("Invalid OCI index or manifest schema")
        if media_type in index_types:
            for child in document.get("manifests", []):
                visit(child, depth + 1)
            return
        if media_type not in manifest_types:
            raise ValueError("Unsupported OCI index or manifest media type")
        config = document["config"]
        configuration = archive_json(archive, verify_descriptor(archive, config, verified))
        layer_names = [verify_descriptor(archive, layer, verified) for layer in document.get("layers", [])]
        if document.get("subject"):
            visit(document["subject"], depth + 1)
        is_artifact = document.get("artifactType") or descriptor.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest"
        if not is_artifact:
            platform = descriptor.get("platform", {})
            if any(key in platform and platform[key] != configuration.get(key) for key in ("os", "architecture")):
                raise ValueError("OCI platform descriptor does not match its configuration")
            images.append({"manifest_digest": descriptor["digest"], "config_digest": config["digest"], "layers": layer_names,
                           "os": configuration.get("os"), "architecture": configuration.get("architecture")})

    visit(roots[0])
    matching = [item for item in images if item["config_digest"] == config_digest and item["os"] == "linux" and item["architecture"] == "amd64"]
    if len(matching) != 1 or matching[0]["layers"] != layers:
        raise ValueError("The tagged Docker manifest does not match the accepted OCI image and platform")
    return {"identity_kind": "oci-index" if roots[0].get("mediaType") in index_types else "oci-manifest",
            "manifest_digest": matching[0]["manifest_digest"], "config_digest": config_digest}


def inspect_image_archive(path, image_id):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("An inspected sha256 image ID is required")
    with tarfile.open(path, "r:") as archive:
        manifest = archive_json(archive, "manifest.json")
        if not isinstance(manifest, list) or len(manifest) != 1 or IMAGE_NAME not in (manifest[0].get("RepoTags") or []):
            raise ValueError("The image archive must contain the expected tagged image")
        config_member = archive_member(archive, manifest[0]["Config"], 10 * 1024 * 1024)
        with archive.extractfile(config_member) as handle:
            config_digest = stream_sha256(handle)
        configuration = archive_json(archive, manifest[0]["Config"])
        if configuration.get("os") != "linux" or configuration.get("architecture") != "amd64":
            raise ValueError("The saved image must use linux/amd64")
        layers = manifest[0].get("Layers", [])
        if config_digest != image_id:
            # Containerd-backed Docker identifies images by an OCI index or manifest.
            return inspect_oci_image(archive, image_id, config_digest, layers)
        # Classic Docker identifies an image by its configuration, whose diff IDs
        # bind the uncompressed layers even if a newer exporter stores gzip blobs.
        diff_ids = configuration.get("rootfs", {}).get("diff_ids", [])
        if len(diff_ids) != len(layers):
            raise ValueError("Legacy image layer count does not match its configuration")
        for name, expected in zip(layers, diff_ids):
            member = archive_member(archive, name)
            with archive.extractfile(member) as handle:
                compressed = handle.read(2) == b"\x1f\x8b"
                handle.seek(0)
                if compressed:
                    with gzip.GzipFile(fileobj=handle) as uncompressed:
                        actual = stream_sha256(uncompressed)
                else:
                    actual = stream_sha256(handle)
            if actual != expected:
                raise ValueError("Legacy image layer digest does not match its configuration")
        return {"identity_kind": "legacy-config", "config_digest": config_digest}


def validate_image_archive(root, image_id):
    path = source_file(root, f"dist/{IMAGE_ARCHIVE}")
    identity = inspect_image_archive(path, image_id)
    digest = file_sha256(path)
    checksum = source_file(root, f"dist/{IMAGE_ARCHIVE}.sha256").read_text(encoding="utf-8").split()
    if checksum != [digest, IMAGE_ARCHIVE]:
        raise ValueError("The saved image checksum does not match")
    return {"filename": IMAGE_ARCHIVE, "sha256": digest, **identity}


def build_package(root, image_id):
    root = root.resolve(strict=True)
    # Read each approved input once so the manifest hashes the exact archived bytes.
    contents = {name: source_file(root, name).read_bytes() for name in FILES}
    compose_hash = validate_evidence(contents, image_id)
    image_archive = validate_image_archive(root, image_id)
    wheel_files = sorted((root / "dist/wheels").glob("*.whl"))
    if not wheel_files:
        raise ValueError("No offline wheels found; run the managed export first")
    for path in wheel_files:
        relative = path.relative_to(root).as_posix()
        contents[f"wheels/{path.name}"] = source_file(root, relative).read_bytes()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}
    manifest = {
        "upstream_commit": UPSTREAM_COMMIT,
        "image_name": IMAGE_NAME,
        "image_id": image_id,
        "platform": PLATFORM,
        "compose_sha256": compose_hash,
        "image_archive": image_archive,
        "files": hashes,
    }
    contents["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output_dir = root / "dist"
    if output_dir.resolve(strict=True) != output_dir.absolute():
        raise ValueError("The output directory must not be a link")
    output = output_dir / "peixian-deployment.zip"
    temporary = output.with_suffix(".zip.tmp")
    for path in (output, temporary, output.with_suffix(".zip.sha256")):
        if path.is_symlink() or (path.exists() and path.resolve() != path.absolute()):
            raise ValueError("The output files must not be links")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{name}")
            info.create_system = 3
            mode = 0o755 if name in ("manage.sh", "entrypoint.sh") else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    temporary.replace(output)
    digest = file_sha256(output)
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8", newline="\n")
    return output, len(hashes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True, help="Immutable image ID validated by manage.ps1 export")
    args = parser.parse_args()
    try:
        output, count = build_package(ROOT, args.image_id)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, tarfile.TarError) as error:
        print(f"Packaging failed: {error}", file=sys.stderr)
        return 1
    print(f"Deployment package: {output} ({count} allowlisted files plus manifest.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
