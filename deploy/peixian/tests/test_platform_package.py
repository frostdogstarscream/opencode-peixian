"""Offline bundle provenance and allowlist checks without Docker side effects."""
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
from unittest.mock import patch
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

    def package_tree(self, tags):
        source=self.root/"source"
        deploy=source/"deploy/peixian"
        deploy.mkdir(parents=True)
        for name in ("platform-config.py","platform-capacity.py"):
            shutil.copyfile(ROOT/name,deploy/name)
        shared = source / "services/peixian-control/shared"
        shared.mkdir(parents=True)
        shutil.copyfile(ROOT.parents[1] / "services/peixian-control/shared/orchestration_config.py", shared / "orchestration_config.py")
        shutil.copyfile(ROOT.parents[1] / "services/peixian-control/shared/eventhub_config.py", shared / "eventhub_config.py")
        (source/"LICENSE").write_text("synthetic")
        wheels=self.root/"wheels"
        wheels.mkdir()
        (wheels/"synthetic-1-py3-none-any.whl").write_bytes(b"synthetic")
        destination=deploy/"dist/test"
        destination.mkdir(parents=True)
        config=b'{"os":"linux","architecture":"amd64","config":{"Labels":{"org.peixian.control.config.max":"2"}}}'
        archive=self.image_archive([{"Config":"config.json","RepoTags":tags}],config)
        shutil.copyfile(archive,destination/"images.tar")
        profile=json.loads((ROOT/"server/platform.50-io.example.json").read_text(encoding="utf-8"))
        cfg=self.root/"profile.json"
        cfg.write_text(json.dumps(profile),encoding="utf-8")
        return source,deploy,wheels,destination,cfg

    def test_configured_image_tags_are_required_not_default_old_release(self):
        new=json.loads((ROOT/"server/platform.50-io.example.json").read_text(encoding="utf-8"))["images"]
        old=dict(new,control="agent-platform-control:1.0.0",gateway="agent-platform-gateway:1.0.0")
        source,deploy,wheels,destination,cfg=self.package_tree(list(old.values()))
        with patch.object(package,"ROOT",source),patch.object(package,"DEPLOY",deploy), \
                patch.object(package,"ALLOWED_FILES",("LICENSE",)),patch.object(package,"OPTIONAL_FILES",()), \
                patch.object(package,"command",return_value="a"*40):
            with self.assertRaisesRegex(package.PackageError,"tags_do_not_match"):
                package.assemble(destination,wheels,"HEAD",config_path=cfg)
        self.assertTrue((destination/"images.tar").is_file())

    def test_matching_tags_manifest_is_sanitized_and_source_only_rejects_old_archive(self):
        profile=json.loads((ROOT/"server/platform.50-io.example.json").read_text(encoding="utf-8"))
        source,deploy,wheels,destination,cfg=self.package_tree(list(profile["images"].values()))
        def command(*args):
            if args[:2]==("git","rev-parse"):
                return "a"*40
            if args[:2]==("git","status"):
                return ""
            if args[:3]==("docker","image","inspect"):
                return json.dumps([{"Id":"synthetic"}])
            if args[:2]==("git","archive"):
                Path(args[3].removeprefix("--output=")).write_bytes(b"synthetic committed archive")
                return ""
            self.fail("unexpected side effect")
        with patch.object(package,"ROOT",source),patch.object(package,"DEPLOY",deploy), \
                patch.object(package,"ALLOWED_FILES",("LICENSE",)),patch.object(package,"OPTIONAL_FILES",()), \
                patch.object(package,"command",side_effect=command):
            result=package.assemble(destination,wheels,"HEAD",config_path=cfg)
            self.assertEqual(result["images"],4)
            self.assertEqual((destination/"source.tar.gz").read_bytes(), b"synthetic committed archive")
            report=json.loads((destination/"release-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(report["platform_config_version"],2)
            self.assertEqual(report["requested_images"],profile["images"])
            self.assertEqual(report["effective_config"]["concurrency"]["sse_viewers"],128)
            self.assertNotIn("private_key",json.dumps(report["effective_config"]))
            with self.assertRaisesRegex(package.PackageError,"must_not_include_old_images"):
                package.assemble(destination,wheels,"HEAD",config_path=cfg,source_only=True)

    def test_allowlist_has_no_runtime_or_credential_sources(self):
        for name in package.ALLOWED_FILES:
            self.assertFalse(package.FORBIDDEN.intersection(Path(name).parts))
        self.assertIn("deploy/peixian/plugin-client.mjs", package.ALLOWED_FILES)
        self.assertIn("deploy/peixian/platform.ps1", package.ALLOWED_FILES)
        self.assertIn("source.tar.gz", package.ARTIFACTS)

    def test_full_bundle_exports_real_commit_and_preserves_existing_archive(self):
        profile = json.loads((ROOT / "server/platform.50-io.example.json").read_text(encoding="utf-8"))
        source, deploy, wheels, destination, cfg = self.package_tree(list(profile["images"].values()))
        def git(*args):
            return subprocess.run(["git", *args], cwd=source, capture_output=True, check=True, text=True).stdout.strip()
        docs = tuple(name for name in package.ALLOWED_FILES if name.endswith(("EVENTHUB_HF1_REVIEW.md", "N1_N2_LOCAL_REVIEW.md")))
        self.assertEqual(len(docs), 2)
        for name in docs:
            (source / name).write_text("synthetic review", encoding="utf-8")
        git("init", "--quiet")
        git("add", "LICENSE", *docs)
        git("-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "test: synthetic source")
        sha = git("rev-parse", "HEAD")
        original = package.command
        def command(*args):
            if args[:3] == ("docker", "image", "inspect"):
                return json.dumps([{"Id": "synthetic"}])
            return original(*args)
        with patch.object(package, "ROOT", source), patch.object(package, "DEPLOY", deploy), \
                patch.object(package, "ALLOWED_FILES", ("LICENSE", *docs)), patch.object(package, "OPTIONAL_FILES", ()), \
                patch.object(package, "command", side_effect=command):
            self.assertTrue(package.assemble(destination, wheels, sha, config_path=cfg)["source_matches_commit"])
            archive = destination / "source.tar.gz"
            before = archive.read_bytes()
            with tarfile.open(archive) as contents:
                self.assertEqual(contents.pax_headers["comment"], sha)
                self.assertEqual(contents.extractfile("LICENSE").read(), b"synthetic")
                for name in docs:
                    self.assertEqual(contents.extractfile(name).read(), b"synthetic review")
                    self.assertEqual((destination / name).read_text(encoding="utf-8"), "synthetic review")
            with self.assertRaisesRegex(package.PackageError, "source_archive_already_exists"):
                package.assemble(destination, wheels, sha, config_path=cfg)
            self.assertEqual(archive.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
