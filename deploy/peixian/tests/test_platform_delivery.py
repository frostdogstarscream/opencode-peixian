"""Server configuration and archive boundary tests use only synthetic files."""
import importlib.util
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_test", ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


platform = load("platform-manage")
backup = load("platform-backup")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "platform.json"
        self.raw = {"version": 1, "public_url": "https://agent.internal:14443", "control_port": 14093,
                    "tls": {"certificate": "./certificate.pem", "private_key": "./private-key.pem"}}

    def config(self, **changes):
        self.path.write_text(json.dumps({**self.raw, **changes}), encoding="utf-8")
        return platform.config.load_config(self.path)

    def test_defaults_are_shared_with_control_worker_budget(self):
        cfg = self.config()
        self.assertEqual(cfg.max_runtimes, 4)
        self.assertEqual(cfg.resource_limits["agent"], {"cpus": 2, "memory_mib": 2048})
        self.assertEqual(cfg.https_port, 14443)
        self.assertEqual(cfg.control_url, "http://127.0.0.1:14093")
        self.assertEqual(cfg.memory_budget_mib, 12288)
        self.assertEqual(cfg.cpu_budget, 13)
        self.assertEqual(cfg.worker_root, self.root / "platform-data/worker")

    def test_invalid_server_origins_rejected(self):
        for value in ("http://agent.internal", "https://user:pass@agent.internal", "https://agent.internal/path",
                      "https://agent.internal?query=yes", "https://agent.internal/#frag", "https://a\nb", [], None, "https://agent.internal:0"):
            with self.subTest(value=value), self.assertRaises(platform.config.ConfigError):
                self.config(public_url=value)

    def test_ports_unknown_keys_and_ids_fail(self):
        for changes in ({"https_port": 443}, {"control_port": 14443}, {"version": 2}, {"version": True}, {"data_root": str(self.root)},
                        {"anything": "x"}, {"deployment_id": "../foo"}, {"control_port": True}):
            with self.subTest(changes=changes), self.assertRaises(platform.config.ConfigError):
                self.config(**changes)

    def test_invalid_resources_and_images_rejected(self):
        for changes in ({"max_runtimes": 0}, {"max_runtimes": 33}, {"resource_limits": {"agent": {"cpus": 0}}},
                        {"resource_limits": {"gateway": {"memory_mib": "512m"}}}, {"images": []},
                        {"images": {"control": "service:latest"}}, {"images": {"control": "service"}}):
            with self.subTest(changes=changes), self.assertRaises(platform.config.ConfigError):
                self.config(**changes)

    def test_pool_requires_canonical_private_ipv4_range(self):
        for pool in ("8.8.0.0/16", "10.240.1.1/16", "10.240.0.0/28", "::/0"):
            with self.subTest(pool=pool), self.assertRaises(platform.config.ConfigError):
                self.config(network_pool=pool)

    def test_compose_secure_origin_resources_and_entry_boundary(self):
        cfg = self.config(max_runtimes=2, deployment_id="synthetic-server")
        data = platform.compose_config(cfg)
        console = data["services"]["console"]
        self.assertGreaterEqual(int(console["stop_grace_period"][:-1]), 5 + 4 * cfg.concurrency.get("hub_shutdown_seconds", 5))
        proxy = data["services"]["https"]
        self.assertEqual(console["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(console["environment"]["CONSOLE_ORIGINS"], cfg.public_url)
        self.assertEqual(console["environment"]["COOKIE_SECURE"], "true")
        self.assertEqual(console["environment"]["MAX_RUNTIMES"], "2")
        self.assertEqual(console["environment"]["PLATFORM_NAME"], "Agent 工作台")
        self.assertEqual(proxy["ports"][0]["target"], 8443)
        self.assertEqual(data["networks"]["front"]["ipam"]["config"][0]["subnet"], "10.240.0.0/28")
        for service in (console, proxy):
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertTrue(service["read_only"])
            self.assertFalse(any("docker.sock" in json.dumps(v) for v in service["volumes"]))

    def test_render_pins_immutable_images_without_credential_values(self):
        cfg = self.config()
        images = {key: "sha256:" + "a" * 64 for key in cfg.images}
        platform.render(cfg, images)
        source = json.loads(cfg.compose_path.read_text(encoding="utf-8"))
        self.assertEqual(source["services"]["console"]["image"], images["control"])
        self.assertTrue((cfg.root / "generated/nginx.conf").is_file())
        nginx = (cfg.root / "generated/nginx.conf").read_text()
        self.assertIn("location ^~ /internal/ { return 404; }", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertNotIn("proxy_set_header Origin", nginx)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def archive(self, members):
        path = self.root / (str(len(list(self.root.iterdir()))) + ".tar.gz")
        with tarfile.open(path, "w:gz") as output:
            for name, body, kind in members:
                item = tarfile.TarInfo(name)
                item.mode = 0o600
                item.size = len(body)
                item.type = kind
                if kind == tarfile.SYMTYPE:
                    item.linkname = "../../outside"
                output.addfile(item, io.BytesIO(body) if kind == tarfile.REGTYPE else None)
        return path

    def test_normal_roundtrip_retains_exact_content(self):
        source = self.root / "source"
        (source / "nested").mkdir(parents=True)
        (source / "nested/合成.txt").write_text("合成资料", encoding="utf-8")
        (source / "empty").mkdir()
        before = backup.scan(source)
        file = self.root / "normal.tar.gz"
        with file.open("wb") as stream:
            backup.pack(source, stream)
        self.assertEqual(backup.archive_inventory(file), before)
        target = self.root / "target"
        with tarfile.open(file, "r:gz") as archive:
            backup.unpack_empty(target, archive)
        self.assertEqual(backup.scan(target), before)
        self.assertTrue((target / "empty").is_dir())

    def test_path_escape_link_duplicate_and_case_collision_rejected(self):
        for members in ([('/outside', b'x', tarfile.REGTYPE)], [('../outside', b'x', tarfile.REGTYPE)],
                        [('a\\b', b'x', tarfile.REGTYPE)], [('a', b'', tarfile.SYMTYPE)],
                        [('a', b'x', tarfile.REGTYPE), ('a', b'y', tarfile.REGTYPE)],
                        [('A', b'x', tarfile.REGTYPE), ('a', b'y', tarfile.REGTYPE)]):
            with self.subTest(members=members):
                file = self.archive(members)
                with self.assertRaises(backup.BackupError):
                    backup.archive_inventory(file)

    def test_existing_restore_target_never_modified(self):
        target = self.root / "target"
        target.mkdir()
        (target / "precious.txt").write_text("preserve")
        file = self.archive([("precious.txt", b"overwrite", tarfile.REGTYPE)])
        with tarfile.open(file, "r:gz") as archive, self.assertRaises(backup.BackupError):
            backup.unpack_empty(target, archive)
        self.assertEqual((target / "precious.txt").read_text(), "preserve")

    def test_host_rebase_windows_source_to_current_platform(self):
        worker = self.root / "worker/runtimes" / ("a" * 32)
        worker.mkdir(parents=True)
        source = "D:\\synthetic\\server"
        state = {"compose": source + "\\worker\\runtimes\\" + "a" * 32 + "\\releases\\1\\compose.json",
                 "paused": False, "peixian.deployment": "original"}
        (worker / "state.json").write_text(json.dumps(state))
        published = worker / "releases/1/agent/plugins/sample/manifest.json"
        published.parent.mkdir(parents=True)
        published_bytes = b'{\n  "id": "sample",\n  "version": "1.0.0"\n}\n'
        published.write_bytes(published_bytes)
        backup.rewrite_host(self.root, source, "restored-platform")
        actual = json.loads((worker / "state.json").read_text())
        self.assertEqual(actual["compose"], str(worker / "releases/1/compose.json"))
        self.assertTrue(actual["paused"])
        self.assertEqual(actual["peixian.deployment"], "restored-platform")
        self.assertEqual(published.read_bytes(), published_bytes)

    def test_database_snapshot_detects_busy_jobs_without_source_writes(self):
        dbpath = self.root / "control.sqlite3"
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.executescript("CREATE TABLE users(id TEXT); INSERT INTO users VALUES('synthetic'); CREATE TABLE jobs(status TEXT); PRAGMA user_version=3;")
        before = backup.digest(dbpath)
        self.assertEqual(backup.database_meta(self.root), {"schema_version": 3, "busy": False, "users": 1})
        self.assertEqual(backup.digest(dbpath), before)
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute("INSERT INTO jobs VALUES('running')")
        self.assertTrue(backup.database_meta(self.root)["busy"])

    def test_source_links_rejected(self):
        source = self.root / "source"
        source.mkdir()
        (self.root / "outside").write_text("private")
        try:
            (source / "escape").symlink_to(self.root / "outside")
        except OSError:
            self.skipTest("OS does not permit unprivileged symbolic links")
        with self.assertRaises(backup.BackupError):
            backup.scan(source)

    def test_second_backup_or_worker_cannot_acquire_same_host_lock(self):
        cfg = SimpleNamespace(worker_root=self.root / "worker")
        with backup.worker_stopped(cfg):
            with self.assertRaisesRegex(backup.BackupError, "stop_worker_before_backup"):
                with backup.worker_stopped(cfg):
                    self.fail("second lock unexpectedly acquired")
        with backup.worker_stopped(cfg):
            pass

    def test_private_archive_uses_private_modes_even_from_windows(self):
        source = self.root / "source"
        (source / "secrets").mkdir(parents=True)
        (source / "secrets/key").write_text("synthetic")
        file = self.root / "private.tar.gz"
        with file.open("wb") as stream:
            backup.pack(source, stream, private=True)
        with tarfile.open(file) as archive:
            self.assertEqual(archive.getmember("secrets").mode, 0o700)
            self.assertEqual(archive.getmember("secrets/key").mode, 0o600)

    def test_manifest_requires_credentials_and_detects_tampering(self):
        folder = self.root / "backup"
        folder.mkdir()
        host = self.archive([("secrets/console-control.key", b"synthetic", tarfile.REGTYPE)])
        volume = self.archive([("content.txt", b"sample", tarfile.REGTYPE)])
        import shutil
        shutil.copyfile(host, folder / "host.tar.gz")
        shutil.copyfile(volume, folder / "control.tar.gz")
        entry = lambda name: {"file": name, "sha256": backup.digest(folder / name), "inventory": backup.archive_inventory(folder / name)}
        manifest = {"format": 1, "runtime_ids": [], "control_volume": "control", "volumes": {"control": entry("control.tar.gz")}, "host": entry("host.tar.gz")}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(backup.BackupError, "credentials_missing"):
            backup.verify(folder)
        with (folder / "control.tar.gz").open("ab") as file:
            file.write(b"tampered")
        with self.assertRaisesRegex(backup.BackupError, "checksum_mismatch"):
            backup.verify(folder)


if __name__ == "__main__":
    unittest.main()
