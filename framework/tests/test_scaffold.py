"""Scaffold contracts using temporary state and Git history only.

Run from framework: python -B -m unittest discover -s tests -p test_scaffold.py
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))

import config
import manage
import new_project


def profile(**changes):
    value = {
        "schema_version": 1,
        "project_id": "sample-one",
        "display_name": "合成应用",
        "tagline": "仅用于脚手架测试",
        "console_port": 14111,
        "max_runtimes": 4,
    }
    return value | changes


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        base = FRAMEWORK / ".test-runs"
        base.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="scaffold-", dir=base)
        self.folder = Path(self.temporary.name).resolve()
        self.assertTrue(self.folder.is_relative_to(base.resolve()))
        self.addCleanup(self.temporary.cleanup)

    def project_folder(self, name):
        root = self.folder / name
        (root / "framework").mkdir(parents=True)
        return root


class ProfileTests(TemporaryCase):
    def test_valid_boundaries_and_copy(self):
        for port, maximum in ((1024, 1), (65535, 4)):
            value = profile(console_port=port, max_runtimes=maximum)
            result = config.validate(value)
            self.assertEqual(result, value)
            self.assertIsNot(result, value)
        self.assertEqual(config.validate(profile(project_id="a"))["project_id"], "a")
        config.validate(profile(project_id="a" * 16, display_name="名" * 60, tagline="文" * 180))

    def test_rejects_wrong_shape_types_ranges_and_control_text(self):
        invalid = [None, [], {}, profile(extra="not-allowed")]
        missing = profile()
        del missing["tagline"]
        invalid.append(missing)
        cases = {
            "schema_version": [True, "1", 0, 2],
            "project_id": [None, "", "A", "1app", "a_b", "../other", "a/b", "a" * 17],
            "display_name": [None, "", "   ", "x\ny", "x\ry", "x\0y", "x\x7fy", "名" * 61],
            "tagline": [None, "", "\t", "x\ny", "文" * 181],
            "console_port": [True, "14111", 1023, 65536, 14111.0],
            "max_runtimes": [True, "4", 0, 5, 2.5],
        }
        invalid.extend(profile(**{key: value}) for key, values in cases.items() for value in values)
        for index, value in enumerate(invalid):
            with self.subTest(case=index):
                with self.assertRaises(ValueError):
                    config.validate(value)

    def test_load_uses_project_root_and_validates(self):
        root = self.project_folder("load")
        path = root / "framework/project.json"
        path.write_text(json.dumps(profile(), ensure_ascii=False), encoding="utf-8")
        self.assertEqual(config.load(root), profile())
        path.write_text(json.dumps(profile(console_port=True)), encoding="utf-8")
        with self.assertRaises(ValueError):
            config.load(root)

    def test_two_projects_have_independent_deployment_identity(self):
        first = profile()
        second = profile(project_id="sample-two", console_port=14112, max_runtimes=2)
        roots = [self.project_folder("one"), self.project_folder("two")]
        values = [manage.compose(first, roots[0]), manage.compose(second, roots[1])]
        a, b = [item["services"]["console"] for item in values]
        self.assertNotEqual(values[0]["name"], values[1]["name"])
        self.assertNotEqual(a["container_name"], b["container_name"])
        self.assertEqual(a["ports"], ["127.0.0.1:14111:8080"])
        self.assertEqual(b["ports"], ["127.0.0.1:14112:8080"])
        self.assertNotEqual(values[0]["volumes"]["control-data"]["name"], values[1]["volumes"]["control-data"]["name"])
        self.assertNotEqual(a["environment"]["CONSOLE_COOKIE_NAME"], b["environment"]["CONSOLE_COOKIE_NAME"])
        for image in ("control_image", "gateway_image", "agent_image"):
            self.assertNotEqual(config.names(first)[image], config.names(second)[image])
        for value, service, expected in zip(values, (a, b), (first, second)):
            self.assertEqual(service["environment"]["RUNTIME_NAMESPACE"], expected["project_id"])
            self.assertEqual(service["environment"]["MAX_RUNTIMES"], str(expected["max_runtimes"]))
            self.assertIn(str(expected["console_port"]), service["environment"]["CONSOLE_ORIGINS"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertTrue(service["read_only"])
            self.assertNotIn("privileged", service)
            self.assertFalse(any("docker.sock" in item for item in service["volumes"]))
        for key in values[0]["secrets"]:
            self.assertNotEqual(values[0]["secrets"][key]["file"], values[1]["secrets"][key]["file"])

    def test_worker_flags_preserve_namespace_paths_images_and_once(self):
        value = profile(project_id="sample-worker", console_port=14113, max_runtimes=2)
        root = self.project_folder("worker")
        args = [str(item) for item in manage.worker_args(value, root, once=True)]
        options = dict(zip(args[2:-1:2], args[3:-1:2]))
        self.assertEqual(args[-1], "--once")
        self.assertEqual(args.count("--once"), 1)
        self.assertEqual(options["--namespace"], "sample-worker")
        self.assertEqual(options["--control-url"], "http://127.0.0.1:14113")
        self.assertEqual(options["--control-container"], "sample-worker-console")
        self.assertEqual(Path(options["--state-root"]), root / "framework/.runtime/worker")
        self.assertEqual(Path(options["--key-file"]), root / "framework/.secrets/console-worker.key")
        self.assertEqual(options["--agent-image"], config.names(value)["agent_image"])
        self.assertEqual(options["--gateway-image"], config.names(value)["gateway_image"])
        self.assertEqual(options["--max-runtimes"], "2")
        self.assertNotIn("--once", manage.worker_args(value, root))


class OwnershipTests(TemporaryCase):
    def inspect_responses(self, root, container_labels, volume_labels):
        calls = []

        def respond(args, **options):
            args = [str(value) for value in args]
            calls.append(args)
            self.assertTrue(options.get("capture"))
            if args[:2] == ["docker", "ps"]:
                return "fixture-container\n" if container_labels is not False else ""
            if args[:3] == ["docker", "volume", "ls"]:
                return "fixture-volume\n" if volume_labels is not False else ""
            if args[:3] == ["docker", "container", "inspect"]:
                return json.dumps([{"Config": {"Labels": container_labels}}])
            if args[:3] == ["docker", "volume", "inspect"]:
                return json.dumps([{"Labels": volume_labels}])
            self.fail("Ownership check attempted a non-read-only command")

        return calls, respond

    def test_matching_owned_resources_and_absent_resources_are_accepted(self):
        root = self.project_folder("owned")
        expected = manage.ownership(profile(), root)
        for present in (True, False):
            with self.subTest(resources_present=present):
                labels = expected if present else False
                calls, respond = self.inspect_responses(root, labels, labels)
                with patch.object(manage, "command", side_effect=respond):
                    manage.check_existing(profile(), root)
                self.assertEqual(len(calls), 4 if present else 2)

    def test_foreign_or_unlabeled_container_and_volume_are_rejected(self):
        root = self.project_folder("current")
        other = self.project_folder("other")
        expected = manage.ownership(profile(), root)
        foreign = manage.ownership(profile(), other)
        self.assertNotEqual(expected["ai-framework.source-root"], foreign["ai-framework.source-root"])
        for kind in ("container", "volume"):
            for labels in (foreign, {}, None):
                with self.subTest(resource=kind, labels_missing=not labels):
                    container = labels if kind == "container" else expected
                    volume = labels if kind == "volume" else expected
                    calls, respond = self.inspect_responses(root, container, volume)
                    with patch.object(manage, "command", side_effect=respond):
                        with self.assertRaisesRegex(ValueError, "another project directory"):
                            manage.check_existing(profile(), root)
                    self.assertTrue(calls)

    def test_compose_ownership_binds_container_and_volume_to_source_root(self):
        first, second = self.project_folder("first-owner"), self.project_folder("second-owner")
        a, b = manage.compose(profile(), first), manage.compose(profile(), second)
        self.assertEqual(a["services"]["console"]["container_name"], b["services"]["console"]["container_name"])
        for value, root in ((a, first), (b, second)):
            expected = manage.ownership(profile(), root)
            self.assertEqual(value["services"]["console"]["labels"], expected)
            self.assertEqual(value["volumes"]["control-data"]["labels"], expected)
        self.assertNotEqual(a["services"]["console"]["labels"], b["services"]["console"]["labels"])

class InitializationTests(TemporaryCase):
    def fingerprints(self, root):
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (root / "framework/.secrets").iterdir()
        }

    def test_reinitialization_preserves_credentials_and_updates_safe_profile(self):
        root = self.project_folder("init")
        target = manage.initialize(profile(), root)
        first = self.fingerprints(root)
        self.assertEqual(set(first), {"console-control.key", "console-worker.key", "console-admin.password"})
        for path in (root / "framework/.secrets").iterdir():
            self.assertGreaterEqual(len(path.read_text(encoding="utf-8").rstrip("\r\n")), 24)
        key = (root / "framework/.secrets/console-control.key").read_text(encoding="utf-8").strip()
        self.assertEqual(len(base64.urlsafe_b64decode(key)), 32)
        changed = profile(display_name="新的展示名称", console_port=14115)
        self.assertEqual(manage.initialize(changed, root), target)
        self.assertEqual(self.fingerprints(root), first)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), manage.compose(changed, root))
        self.assertEqual(json.loads((root / "framework/.runtime/project.json").read_text()), {"project_id": "sample-one"})

    def test_initialized_project_id_cannot_be_changed(self):
        root = self.project_folder("rename")
        target = manage.initialize(profile(), root)
        before = self.fingerprints(root)
        definition = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "identity cannot be changed"):
            manage.initialize(profile(project_id="changed"), root)
        self.assertEqual(self.fingerprints(root), before)
        self.assertEqual(target.read_bytes(), definition)

    def test_separate_initializations_generate_distinct_credentials(self):
        first, second = self.project_folder("first"), self.project_folder("second")
        manage.initialize(profile(), first)
        manage.initialize(profile(project_id="second", console_port=14116), second)
        a, b = self.fingerprints(first), self.fingerprints(second)
        self.assertTrue(all(a[name] != b[name] for name in a))

    def test_invalid_existing_credential_is_preserved_and_rejected(self):
        root = self.project_folder("invalid")
        manage.initialize(profile(), root)
        path = root / "framework/.secrets/console-worker.key"
        for invalid in ("short", "a" * 30 + "\n" + "b" * 30, "a" * 30 + "\0"):
            with self.subTest(length=len(invalid)):
                path.write_text(invalid, encoding="utf-8")
                before = self.fingerprints(root)
                with self.assertRaises(ValueError):
                    manage.initialize(profile(), root)
                self.assertEqual(self.fingerprints(root), before)


class ExportTests(TemporaryCase):
    LICENSE = b"MIT License\n\nCopyright (c) 2026 Synthetic Test Fixture\n\nPermission is hereby granted, free of charge, to any person obtaining a copy.\n"

    def git(self, root, *args, input=None):
        result = subprocess.run(
            ["git", "-C", str(root), *args], input=input, capture_output=True,
            text=True, encoding="utf-8", check=False,
        )
        if result.returncode:
            self.fail("Temporary fixture Git command failed: " + args[0] + "\n" + result.stderr)
        return result.stdout.strip()

    def commit(self, root):
        self.git(root, "commit", "--quiet", "-m", "Synthetic scaffold fixture")
        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def source(self, name="source", extra=None):
        root = self.folder / name
        root.mkdir()
        files = {
            "LICENSE": self.LICENSE,
            ".gitignore": b"*.ignored\n",
            "package.json": b'{"name":"synthetic-template","private":true}\n',
            "framework/config.py": b"VALUE = 'committed'\n",
            "framework/manage.py": b"# Synthetic fixture; never executed.\n",
            "framework/new_project.py": b"# Synthetic fixture; never executed.\n",
            "framework/project.schema.json": b'{"type":"object"}\n',
            "framework/project.json": (json.dumps(profile()) + "\n").encode(),
            "framework/README.md": b"# Synthetic framework documentation\n",
            "services/peixian-control/control/app.py": b"# Synthetic service; never executed.\n",
            "packages/app/source.txt": b"COMMITTED_SOURCE\n",
            "packages/app/LICENSE": b"Synthetic dependency license, preserved byte for byte.\n",
            "deploy/peixian/console-runtime.py": b"# Included runtime source\n",
            "deploy/peixian/console-worker.py": b"# Included worker source\n",
        }
        files.update(extra or {})
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git(root, "init", "--quiet", "--initial-branch=fixture")
        # Identity exists only inside a temporary, synthetic repository.
        self.git(root, "config", "user.name", "Scaffold Test Fixture")
        self.git(root, "config", "user.email", "scaffold-fixture@example.invalid")
        self.git(root, "config", "core.autocrlf", "false")
        self.git(root, "config", "core.symlinks", "false")
        self.git(root, "add", "--force", "--all")
        self.commit(root)
        return root

    def link(self, root, name, target):
        # core.symlinks=false keeps the checkout portable on Windows. The Git
        # index records a real 120000 link and git archive supplies its target.
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(target, encoding="utf-8")
        blob = self.git(root, "hash-object", "-w", "--stdin", input=target)
        self.git(root, "update-index", "--add", "--cacheinfo", f"120000,{blob},{name}")

    def test_export_preserves_licenses_replaces_profile_and_records_head(self):
        source = self.source()
        commit = self.git(source, "rev-parse", "HEAD")
        destination = self.folder / "generated"
        value = profile(project_id="generated", display_name="合成新项目", console_port=14121)
        report = new_project.create_project(destination, value, source=source)
        self.assertEqual(report["template_commit"], commit)
        self.assertFalse(report["git_initialized"])
        self.assertEqual((destination / "LICENSE").read_bytes(), self.LICENSE)
        self.assertEqual((destination / "packages/app/LICENSE").read_bytes(), (source / "packages/app/LICENSE").read_bytes())
        self.assertEqual(json.loads((destination / "framework/project.json").read_text(encoding="utf-8")), value)
        origin = json.loads((destination / "framework/template-origin.json").read_text())
        self.assertEqual(origin["template_commit"], commit)
        self.assertFalse(origin["includes_runtime_data"])
        self.assertIn("合成新项目", (destination / "README.md").read_text(encoding="utf-8"))
        self.assertFalse((destination / ".git").exists())
        self.assertFalse((destination / "framework/.secrets").exists())
        self.assertFalse((destination / "framework/.runtime").exists())

    def test_export_uses_head_instead_of_local_files(self):
        source = self.source()
        self.git(source, "update-index", "--assume-unchanged", "packages/app/source.txt")
        (source / "packages/app/source.txt").write_text("LOCAL_ONLY_NOT_COMMITTED", encoding="utf-8")
        (source / "packages/app/local.ignored").write_text("IGNORED_LOCAL_ONLY", encoding="utf-8")
        self.assertEqual(self.git(source, "status", "--porcelain"), "")
        destination = self.folder / "from-head"
        new_project.create_project(destination, profile(), source=source)
        self.assertEqual((destination / "packages/app/source.txt").read_bytes(), b"COMMITTED_SOURCE\n")
        self.assertFalse((destination / "packages/app/local.ignored").exists())

    def test_existing_destination_is_never_overwritten(self):
        source = self.source()
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                destination = self.folder / kind
                if kind == "directory":
                    destination.mkdir()
                    sentinel = destination / "keep.txt"
                else:
                    sentinel = destination
                sentinel.write_text("PRESERVE_ME", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "must not exist"):
                    new_project.create_project(destination, profile(), source=source)
                self.assertEqual(sentinel.read_text(), "PRESERVE_ME")

    def test_dirty_source_is_rejected_before_destination_creation(self):
        for kind in ("modified", "staged", "untracked"):
            with self.subTest(kind=kind):
                source = self.source("dirty-" + kind)
                path = source / ("untracked.txt" if kind == "untracked" else "packages/app/source.txt")
                path.write_text("DIRTY_SYNTHETIC_DATA", encoding="utf-8")
                if kind == "staged":
                    self.git(source, "add", "packages/app/source.txt")
                destination = self.folder / ("reject-" + kind)
                with self.assertRaisesRegex(ValueError, "Commit the framework changes"):
                    new_project.create_project(destination, profile(), source=source)
                self.assertFalse(destination.exists())

    def test_destination_inside_source_and_missing_parent_are_rejected(self):
        source = self.source()
        for destination in (source / "nested-project", self.folder / "missing-parent/new-project"):
            with self.subTest(destination=destination.name):
                with self.assertRaises(ValueError):
                    new_project.create_project(destination, profile(), source=source)
                self.assertFalse(destination.exists())

    def test_committed_private_paths_and_files_are_excluded_case_insensitively(self):
        private = [
            "framework/.SECRETS/value.txt", "framework/.RUNTIME/state.txt",
            "packages/app/.secrets/value.txt", "packages/app/.runtime/state.txt",
            "packages/app/node_modules/library.js", "packages/app/output/report.json",
            "packages/app/dist/bundle.js", "packages/app/__pycache__/cache.pyc",
            "packages/app/.venv/installed.txt", "packages/app/.pytest_cache/state",
            "packages/app/.test-runs/fixture.txt", "packages/app/.env.local",
            "packages/other/.ENV.production", "packages/app/key.key",
            "packages/app/API.KEY", "packages/app/admin.password",
            "packages/app/ADMIN.PASSWORD", "packages/app/client.deepseek-key",
            "packages/app/CLIENT.DEEPSEEK-KEY",
        ]
        extra = {name: b"SYNTHETIC_PRIVATE_SENTINEL\n" for name in private}
        extra["deploy/peixian/legacy-not-exported.txt"] = b"OMIT_OLD_DEPLOYMENT\n"
        source = self.source(extra=extra)
        destination = self.folder / "public-export"
        new_project.create_project(destination, profile(), source=source)
        for name in private:
            with self.subTest(path=name):
                self.assertFalse(new_project.included(name))
                self.assertFalse((destination / name).exists())
        self.assertFalse((destination / "deploy/peixian/legacy-not-exported.txt").exists())
        self.assertTrue((destination / "deploy/peixian/console-worker.py").is_file())
        self.assertTrue((destination / "packages/app/source.txt").is_file())

    def test_tracked_safe_link_chain_is_materialized_as_regular_files(self):
        source = self.source()
        self.link(source, "packages/app/alias.txt", "source.txt")
        self.link(source, "packages/app/alias-chain.txt", "alias.txt")
        self.commit(source)
        destination = self.folder / "safe-links"
        new_project.create_project(destination, profile(), source=source)
        for name in ("alias.txt", "alias-chain.txt"):
            path = destination / "packages/app" / name
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_bytes(), b"COMMITTED_SOURCE\n")

    def test_tracked_directory_link_materializes_only_exported_children(self):
        source = self.source(extra={
            "packages/mail/templates/emails/welcome.html": b"SYNTHETIC_WELCOME\n",
            "packages/mail/templates/emails/nested/footer.html": b"SYNTHETIC_FOOTER\n",
            "packages/mail/templates/emails/.secrets/hidden.txt": b"SYNTHETIC_PRIVATE\n",
        })
        self.link(source, "packages/console/public/email", "../../mail/templates/emails")
        self.commit(source)
        destination = self.folder / "directory-link"
        new_project.create_project(destination, profile(), source=source)
        target = destination / "packages/console/public/email"
        self.assertTrue(target.is_dir())
        self.assertFalse(target.is_symlink())
        self.assertEqual((target / "welcome.html").read_bytes(), b"SYNTHETIC_WELCOME\n")
        self.assertEqual((target / "nested/footer.html").read_bytes(), b"SYNTHETIC_FOOTER\n")
        self.assertFalse((target / ".secrets").exists())

    def test_casefold_output_collision_is_rejected_before_materialization(self):
        # A case-sensitive Git source can contain these two paths even though
        # the current Windows checkout cannot create both physical files.
        with io.BytesIO() as buffer:
            with tarfile.open(fileobj=buffer, mode="w") as archive:
                for name in ("packages/app/Name.txt", "packages/app/name.txt"):
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b"x"))
            buffer.seek(0)
            with tarfile.open(fileobj=buffer, mode="r:") as archive:
                selected = {member.name: member for member in archive.getmembers()}
                with self.assertRaisesRegex(ValueError, "case-insensitive"):
                    new_project.export_sources(archive, selected)
    def test_links_outside_exported_source_are_rejected_before_writes(self):
        targets = ["../../../outside.txt", "/outside.txt", "C:/outside.txt", "..\\outside.txt", "missing.txt", "../../framework/.secrets/private.txt"]
        for index, target in enumerate(targets):
            with self.subTest(case=index):
                source = self.source("unsafe-" + str(index), extra={"framework/.secrets/private.txt": b"SYNTHETIC_PRIVATE\n"})
                self.link(source, "packages/app/alias.txt", target)
                self.commit(source)
                destination = self.folder / ("rejected-link-" + str(index))
                with self.assertRaises(ValueError):
                    new_project.create_project(destination, profile(), source=source)
                self.assertFalse(destination.exists())

    def test_link_cycles_are_rejected_before_destination_creation(self):
        source = self.source()
        self.link(source, "packages/app/first.txt", "second.txt")
        self.link(source, "packages/app/second.txt", "first.txt")
        self.commit(source)
        destination = self.folder / "cycle"
        with self.assertRaisesRegex(ValueError, "link cycle"):
            new_project.create_project(destination, profile(), source=source)
        self.assertFalse(destination.exists())

    def test_incomplete_template_is_rejected_before_destination_creation(self):
        source = self.source()
        self.git(source, "rm", "framework/manage.py")
        self.commit(source)
        destination = self.folder / "incomplete"
        with self.assertRaisesRegex(ValueError, "complete framework template"):
            new_project.create_project(destination, profile(), source=source)
        self.assertFalse(destination.exists())

    def test_optional_git_initialization_creates_independent_empty_history(self):
        source = self.source()
        destination = self.folder / "new-git"
        result = new_project.create_project(destination, profile(), source=source, initialize_git=True)
        self.assertTrue(result["git_initialized"])
        self.assertEqual(self.git(destination, "rev-parse", "--is-inside-work-tree"), "true")
        self.assertEqual(self.git(destination, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(self.git(destination, "remote"), "")
        history = subprocess.run(["git", "-C", str(destination), "rev-parse", "--verify", "HEAD"], capture_output=True)
        self.assertNotEqual(history.returncode, 0)
        self.assertEqual((destination / "LICENSE").read_bytes(), self.LICENSE)

    def test_unsafe_portable_path_names_are_rejected(self):
        for value in ("/absolute.txt", "../outside.txt", "packages/../outside.txt", "packages/a\\b", "packages/a:stream", "packages/CON.txt", "packages/name. "):
            with self.subTest(path=value):
                with self.assertRaises(ValueError):
                    new_project.path_name(value)


if __name__ == "__main__":
    unittest.main()
