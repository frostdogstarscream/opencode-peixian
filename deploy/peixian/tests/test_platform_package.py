"""Offline bundle provenance and allowlist checks without Docker side effects."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("platform_package_test", ROOT / "platform-package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def image_archive(self, manifest, config):
        path = self.root / "images.tar"
        with tarfile.open(path, "w") as archive:
            for name, value in (("manifest.json", json.dumps(manifest).encode()), ("config.json", config)):
                member = tarfile.TarInfo(name)
                member.size = len(value)
                archive.addfile(member, io.BytesIO(value))
        return path

    def test_image_identity_is_derived_from_archive_bytes(self):
        config = b'{"os":"linux","architecture":"amd64","config":{"Labels":{"synthetic":"true"}}}'
        path = self.image_archive([{"Config": "config.json", "RepoTags": ["sample:1.0.0"]}], config)
        result = package.archive_images(path)["sample:1.0.0"]
        self.assertEqual(result["config_id"], "sha256:" + hashlib.sha256(config).hexdigest())
        self.assertEqual(result["architecture"], "amd64")
        self.assertEqual(result["labels"], {"synthetic": "true"})

    def test_duplicate_tags_and_config_escape_are_rejected(self):
        config = b'{"os":"linux","architecture":"amd64"}'
        for manifest in ([{"Config": "../config.json", "RepoTags": ["sample:1"]}],
                         [{"Config": "config.json", "RepoTags": ["sample:1", "sample:1"]}]):
            with self.subTest(manifest=manifest), self.assertRaises(package.PackageError):
                package.archive_images(self.image_archive(manifest, config))

    def test_unknown_output_preserved_instead_of_deleted(self):
        (self.root / "precious.txt").write_text("preserve")
        with self.assertRaisesRegex(package.PackageError, "unexpected_output"):
            package.validate_output(self.root, {"images.tar"})
        self.assertEqual((self.root / "precious.txt").read_text(), "preserve")

    def test_private_subdirectory_is_rejected_even_when_empty(self):
        (self.root / ".secrets").mkdir()
        with self.assertRaisesRegex(package.PackageError, "private_or_link"):
            package.validate_output(self.root, set())

    def test_allowlist_has_no_runtime_or_credential_sources(self):
        for name in package.ALLOWED_FILES:
            self.assertFalse(package.FORBIDDEN.intersection(Path(name).parts))
        self.assertIn("deploy/peixian/plugin-client.mjs", package.ALLOWED_FILES)
        self.assertIn("deploy/peixian/platform.ps1", package.ALLOWED_FILES)
        self.assertIn("source.tar.gz", package.ARTIFACTS)


if __name__ == "__main__":
    unittest.main()
