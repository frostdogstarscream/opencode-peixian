"""Real SQLite fixtures exercise the control schema boundary without account data."""
import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.util.spec_from_file_location("console_guard_test", Path(__file__).resolve().parents[1] / "console-guard.py")
guard = importlib.util.module_from_spec(loader)
loader.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def database(self, version=0):
        with closing(sqlite3.connect(self.root / "control.sqlite3")) as db, db:
            db.execute("CREATE TABLE users(id TEXT, role TEXT, password TEXT)")
            db.execute("INSERT INTO users VALUES('synthetic', 'admin', 'private-synthetic-value')")
            db.execute("PRAGMA user_version=" + str(version))

    def test_old_image_cannot_read_new_restricted_admin_database(self):
        self.database(2)
        state = guard.inspect_data(self.root)
        with self.assertRaisesRegex(guard.GuardError, "schema_incompatible"):
            guard.compatible(state["schema_version"], {})

    def test_supported_and_future_versions(self):
        labels = {guard.MIN_LABEL: "0", guard.MAX_LABEL: "2"}
        for version in (0, 1, 2):
            self.assertEqual(guard.compatible(version, labels), 2)
        with self.assertRaises(guard.GuardError):
            guard.compatible(3, labels)
        for invalid in ({guard.MAX_LABEL: "2"}, {guard.MIN_LABEL: "0", guard.MAX_LABEL: "invalid"},
                        {guard.MIN_LABEL: "-1", guard.MAX_LABEL: "2"}):
            with self.assertRaises(guard.GuardError):
                guard.compatible(0, invalid)

    def test_probe_only_returns_counts_and_digests_and_preserves_database(self):
        self.database()
        before = (self.root / "control.sqlite3").read_bytes()
        state = guard.inspect_data(self.root)
        self.assertEqual(state["roles"], {"admin": 1})
        self.assertEqual(state["counts"], {"users": 1})
        self.assertNotIn("private-synthetic-value", json.dumps(state))
        self.assertNotIn("synthetic", json.dumps(state))
        self.assertEqual(before, (self.root / "control.sqlite3").read_bytes())

    def test_fingerprint_detects_changed_credentials_and_packages(self):
        self.database()
        before = guard.inspect_data(self.root)
        with closing(sqlite3.connect(self.root / "control.sqlite3")) as db, db:
            db.execute("UPDATE users SET password='another-synthetic-value'")
        after = guard.inspect_data(self.root)
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])
        (self.root / "package.zip").write_bytes(b"synthetic-package")
        self.assertNotEqual(after["fingerprint"], guard.inspect_data(self.root)["fingerprint"])

    def test_wal_without_shm_is_included_without_writing_source(self):
        writer_root = self.root / "writer"
        writer_root.mkdir()
        readonly = self.root / "source"
        readonly.mkdir()
        with closing(sqlite3.connect(writer_root / "control.sqlite3")) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE users(id TEXT,role TEXT)")
            db.execute("INSERT INTO users VALUES('synthetic','admin')")
            db.execute("PRAGMA user_version=2")
            db.commit()
            for name in ("control.sqlite3", "control.sqlite3-wal"):
                shutil.copyfile(writer_root / name, readonly / name)
            before = {p.name: p.read_bytes() for p in readonly.iterdir()}
            state = guard.inspect_data(readonly)
            self.assertEqual(state["schema_version"], 2)
            self.assertEqual(state["counts"]["users"], 1)
            self.assertEqual(before, {p.name: p.read_bytes() for p in readonly.iterdir()})

    def test_empty_fresh_volume_and_corrupt_volume_differ(self):
        self.assertEqual(guard.inspect_data(self.root)["counts"], {})
        (self.root / "unexpected").write_text("synthetic", encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "missing_from_nonempty"):
            guard.inspect_data(self.root)

    def test_migration_requires_matching_verified_backup_and_stopped_writers(self):
        self.database()
        state = guard.inspect_data(self.root)
        image = {"Id": "sha256:synthetic", "Config": {"Labels": {guard.MIN_LABEL: "0", guard.MAX_LABEL: "2"}}}
        with patch.object(guard, "deployment", return_value=("synthetic-volume", "new-image", image)), \
                patch.object(guard, "inspect_volume", return_value=state), \
                patch.object(guard, "stopped", return_value=True):
            with self.assertRaisesRegex(guard.GuardError, "verified_backup"):
                guard.check(Path("synthetic-compose"), self.root)
            folder = self.root / "backup"
            folder.mkdir()
            archive = folder / "control-data.tar.gz"
            archive.write_bytes(b"synthetic-verified-archive")
            (folder / "manifest.json").write_text(json.dumps({"volume": "synthetic-volume", "state": state,
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}), encoding="utf-8")
            self.assertEqual(guard.check(Path("synthetic-compose"), self.root)["status"], "passed")
            with patch.object(guard, "stopped", return_value=False):
                with self.assertRaises(guard.GuardError):
                    guard.check(Path("synthetic-compose"), self.root)
            archive.write_bytes(b"changed")
            with self.assertRaises(guard.GuardError):
                guard.check(Path("synthetic-compose"), self.root)

if __name__ == "__main__":
    unittest.main()
