"""Build context/provenance checks exercise real Git archives, without Docker."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("control_build_test", DEPLOY / "control-build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ControlBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        # Use a complete minimal input set, not a replacement implementation.
        for name in build.INPUTS:
            target = self.source / name
            if name.endswith(("/control", "/shared", "/src")):
                target.mkdir(parents=True, exist_ok=True)
                (target / "synthetic.py").write_text("synthetic = 1\n")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(build.ROOT / name, target)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.source, text=True).strip()

    def test_development_context_excludes_old_dist_dependencies_and_private_files(self):
        for name in ("packages/peixian-console/dist/stale.js", "packages/peixian-console/node_modules/private.js",
                     "services/peixian-control/control/.secrets/key", "services/peixian-control/control/__pycache__/x.pyc"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("must not be included")
        output = self.root / "context"
        output.mkdir()
        build.copy_dev(self.source, output)
        names = [path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()]
        assert not any("dist" in name or "node_modules" in name or ".secrets" in name or "__pycache__" in name for name in names)
        assert build.base_images(output)["frontend"].startswith("oven/bun:1.3.14-slim@sha256:")

    def test_release_uses_committed_source_and_never_uncommitted_changes(self):
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "test: delivery source")
        commit = self.git("rev-parse", "HEAD")
        path = self.source / "packages/peixian-console/index.html"
        original = path.read_bytes()
        path.write_text("uncommitted page")
        output = self.root / "context"
        output.mkdir()
        assert build.copy_release(self.source, output, commit) == commit
        assert (output / "packages/peixian-console/index.html").read_bytes().replace(b"\r\n", b"\n") == original.replace(b"\r\n", b"\n")
        assert path.read_text() == "uncommitted page"
        assert not (output / ".git").exists()

    def test_context_digest_tracks_contents_and_pinned_images_are_required(self):
        output = self.root / "context"
        output.mkdir()
        build.copy_dev(self.source, output)
        before = build.context_digest(output)
        (output / "packages/peixian-console/index.html").write_text("changed")
        assert build.context_digest(output) != before
        (output / build.INPUTS[0]).write_text("FROM python:latest\n")
        with self.assertRaisesRegex(build.BuildError, "pinned_base"):
            build.base_images(output)

    def test_invalid_mode_or_existing_output_fails_before_any_docker_operation(self):
        for arguments in ({"mode": "release"}, {"mode": "dev", "commit": "HEAD"}):
            with patch.object(build, "command", side_effect=AssertionError("Docker must not be called")):
                with self.assertRaises(build.BuildError):
                    build.build(**arguments, root=self.source)
        output = self.root / "previous.json"
        output.write_text("preserve")
        with self.assertRaisesRegex(build.BuildError, "output_exists"):
            build.build(mode="dev", output=output, root=self.source)
        assert output.read_text() == "preserve"

    def test_development_or_wrong_source_cannot_be_exported_as_release(self):
        for value in ({"build": {"mode": "dev"}},
                      {"build": {"mode": "release", "source_commit": "a" * 40}, "user": "10001:10001"}):
            with self.assertRaises(build.BuildError):
                build.verify_release(value, "b" * 40)

    def test_inspection_rejects_a_non_delivery_image_before_creating_a_container(self):
        with patch.object(build, "command", return_value=json.dumps([{"Id": "sha256:" + "a" * 64, "Os": "linux", "Architecture": "amd64", "Config": {}}])) as called:
            with self.assertRaisesRegex(build.BuildError, "delivery_image_required"):
                build.inspect_image("synthetic:1")
            assert called.call_count == 1

    def test_package_gate_rejects_development_source_and_image_mismatches(self):
        spec = importlib.util.spec_from_file_location("delivery_release_gate", DEPLOY / "release-check.py")
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        folder = self.root / "package"
        folder.mkdir()
        with tarfile.open(folder / "source.tar.gz", "w:gz"):
            pass
        manifest = {"source_matches_commit": True, "source_commit": "a" * 40,
                    "images": [{"config_id": "sha256:" + "b" * 64,
                                "labels": {"org.peixian.control.delivery.format": "1"}}],
                    "control_delivery": {"image_id": "sha256:" + "b" * 64,
                                         "build": {"mode": "release", "source_commit": "a" * 40}}}
        def save():
            (folder / "release-manifest.json").write_text(json.dumps(manifest))
            (folder / "SHA256SUMS").write_text("".join(build.checksum(p) + "  " + p.name + "\n"
                for p in sorted(folder.iterdir()) if p.name != "SHA256SUMS"))
        save()
        assert gate.verify_package(folder)[0] == manifest
        for field, bad, expected in (("mode", "dev", "development_image"),
                                     ("source_commit", "c" * 40, "source_mismatch")):
            previous = manifest["control_delivery"]["build"][field]
            manifest["control_delivery"]["build"][field] = bad
            save()
            with self.assertRaisesRegex(gate.EvidenceError, expected):
                gate.verify_package(folder)
            manifest["control_delivery"]["build"][field] = previous
        manifest["control_delivery"]["image_id"] = "sha256:" + "d" * 64
        save()
        with self.assertRaisesRegex(gate.EvidenceError, "image_mismatch"):
            gate.verify_package(folder)


if __name__ == "__main__":
    unittest.main()
