"""Migration, capacity and network lifecycle checks without a Docker daemon."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import httpx

import test_console_runtime as base


loaded = importlib.util.spec_from_file_location("migration_test", base.ROOT / "console-migrate.py")
migration = importlib.util.module_from_spec(loaded)
loaded.loader.exec_module(migration)


class RuntimeInfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = base.FakeRuntime(self.temp.name)
        # This suite exercises lifecycle logic without host ACL commands.
        acl = patch.object(base.runtime, "grant_container_read")
        acl.start()
        self.addCleanup(acl.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_capacity_reserves_all_four_accounts_and_host_headroom(self):
        def capacity(memory, cpus):
            def docker(*args, **kwargs):
                if args[0] == "ps":
                    return ""
                if args[0] == "info":
                    return json.dumps({"MemTotal": memory, "NCPU": cpus})
                raise AssertionError(args)
            self.manager.docker_run = docker
            base.runtime.RuntimeManager.capacity(self.manager, base.RID)

        capacity(12 * 1024**3, 20)
        with self.assertRaisesRegex(base.runtime.RuntimeFailure, "docker_memory_budget_exceeded"):
            capacity(12 * 1024**3 - 1, 20)
        with self.assertRaisesRegex(base.runtime.RuntimeFailure, "docker_cpu_budget_exceeded"):
            capacity(12 * 1024**3, 12)

    def test_compose_render_keeps_networks_and_volumes_external(self):
        with patch.object(base.runtime, "grant_container_read"):
            release = self.manager.prepare(base.spec(), lambda _: b"")
        calls = []
        self.manager.docker_run = lambda *args, **kwargs: calls.append(args) or ""
        base.runtime.RuntimeManager.compose(self.manager, release / "compose.json", "up", "--no-build")
        operational = json.loads(Path(calls[0][2]).read_text())
        for group in ("networks", "volumes"):
            self.assertTrue(all(set(item) == {"name", "external"} and item["external"] for item in operational[group].values()))
        self.assertEqual(sum(item["cpus"] for item in operational["services"].values()), 3)
        self.assertEqual(operational["services"]["gateway"]["mem_limit"], "512m")
        self.assertEqual(operational["services"]["model-relay"]["mem_limit"], "128m")
        self.assertNotEqual(release / "compose.json", Path(calls[0][2]))

    def test_reconcile_reconnects_only_registered_active_runtime(self):
        self.manager.apply(base.job(), base.spec(), lambda _: b"", lambda: None)
        other = "d" * 32
        base.runtime.write_json(self.manager.root / "runtimes" / other / "state.json", {
            "uid": base.UID, "runtime_id": other, "compose": str(self.manager.root / "runtimes" / other / "old.json"), "paused": True})
        (self.manager.root / "runtimes" / "unknown-folder").mkdir()
        attached = []
        self.manager.attach_control = attached.append
        self.assertEqual(base.runtime.RuntimeManager.reconcile(self.manager), [])
        self.assertEqual(attached, [base.RID])

    def test_network_reconcile_rejects_foreign_network(self):
        def docker(*args, **kwargs):
            return json.dumps([{"Name": "px-" + base.RID + "-management", "Internal": True,
                                "Labels": {base.runtime.MANAGED: "true", "peixian.runtime_id": "d" * 32}}])
        self.manager.docker_run = docker
        with self.assertRaisesRegex(base.runtime.RuntimeFailure, "management_network_owner_mismatch"):
            base.runtime.RuntimeManager.attach_control(self.manager, base.RID)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_archive(self):
        source = self.root / "source"
        source.mkdir()
        (source / "session.txt").write_bytes(b"synthetic retained session")
        (source / "folder").mkdir()
        (source / "folder" / "data.txt").write_bytes(b"synthetic data")
        os.link(source / "session.txt", source / "hardlink.txt")
        target = self.root / "snapshot.tar"
        code = migration.SNAPSHOT.replace("'/source'", repr(str(source)))
        with target.open("wb") as output:
            result = subprocess.run([sys.executable, "-c", code], stdout=output, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual((source / "session.txt").read_bytes(), b"synthetic retained session")
        return target

    def test_snapshot_stream_preserves_content_and_independently_verifies_hashes(self):
        target = self.make_archive()
        report = migration.verify_archive(target)
        self.assertEqual(report["files"], 3)
        self.assertEqual(report["entries"], 4)
        with tarfile.open(target) as archive:
            self.assertTrue(archive.getmember("data/hardlink.txt").isfile())
            self.assertIn("manifest.json", archive.getnames())

    def test_corrupted_snapshot_is_rejected(self):
        target = self.make_archive()
        raw = target.read_bytes()
        self.assertIn(b"synthetic retained session", raw)
        target.write_bytes(raw.replace(b"synthetic retained session", b"synthetic tampered session", 1))
        with self.assertRaises(migration.runtime.RuntimeFailure):
            migration.verify_archive(target)

    def test_archive_verifier_does_not_extract_path_traversal(self):
        target = self.root / "bad.tar"
        with tarfile.open(target, "w") as archive:
            member = tarfile.TarInfo("data/../../outside")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
        with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "snapshot_unsafe_member"):
            migration.verify_archive(target)
        self.assertFalse((self.root / "outside").exists())

    def test_inventory_limits_named_volumes_and_omits_secret_bind_paths(self):
        agent = {"id": "synthetic-agent", "name": "agent", "image_id": "sha256:synthetic", "state": "running", "running": True,
                 "labels": {"com.docker.compose.service": "client-a"}, "mounts": [
                     {"Type": "volume", "Name": "peixian-opencode_client-a-home", "Destination": "/home/opencode"},
                     {"Type": "volume", "Name": "peixian-opencode_client-a-workspace", "Destination": "/workspace"},
                     {"Type": "bind", "Source": "private-secret-source", "Destination": "/run/secrets/example"}]}
        entry = {**agent, "id": "synthetic-entry", "labels": {"com.docker.compose.service": "client-a-entry"}, "mounts": []}
        with patch.object(migration, "containers", side_effect=lambda value: [agent, entry] if value.startswith("label=") else [agent]):
            result = migration.inventory("client-a")
            self.assertNotIn("private-secret-source", json.dumps(result))
            self.assertFalse(migration.stopped(result))
            agent["mounts"][0]["Name"] = "another-account-home"
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "unexpected_legacy_volume_mapping"):
                migration.inventory("client-a")

    def handoff_fixture(self):
        imported = {"uid": base.UID, "runtime_id": base.RID}
        info = {"containers": {"client-a": {"running": False}, "client-a-entry": {"running": False}},
                "legacy": {"home_volume": "old-home", "workspace_volume": "old-workspace"},
                "consumers": {name: [{"id": "new-agent", "running": True}] for name in ("old-home", "old-workspace")}}
        agent = {"id": "new-agent", "running": True,
                 "labels": {migration.runtime.MANAGED: "true", "peixian.uid": base.UID, "peixian.runtime_id": base.RID, "com.docker.compose.service": "agent"},
                 "mounts": [{"Destination": path, "Type": "volume", "Name": volume, "RW": True} for path, volume in
                            (("/home/opencode", "old-home"), ("/workspace", "old-workspace"))]}
        gateway = copy.deepcopy(agent)
        gateway["id"] = "new-gateway"
        gateway["labels"]["com.docker.compose.service"] = "gateway"
        gateway["mounts"] = [gateway["mounts"][1]]
        info["consumers"]["old-workspace"].append({"id": "new-gateway", "running": True})
        return imported, info, agent, gateway

    def test_handoff_allows_only_exact_new_agent_without_weakening_offline_snapshot_gate(self):
        imported, info, agent, gateway = self.handoff_fixture()
        self.assertFalse(migration.stopped(info))
        with patch.object(migration, "containers", return_value=[agent, gateway]) as queried:
            self.assertTrue(migration.verify_handoff(info, imported)["only_expected_runtime_uses_volumes"])
        queried.assert_called_once_with("label=com.docker.compose.project=px-" + base.RID)

    def test_handoff_rejects_old_service_or_foreign_writer_even_with_matching_project(self):
        imported, info, agent, gateway = self.handoff_fixture()
        with patch.object(migration, "containers", return_value=[agent, gateway]):
            info["containers"]["client-a-entry"]["running"] = True
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "old_runtime_check_failed"):
                migration.verify_handoff(info, imported)
            info["containers"]["client-a-entry"]["running"] = False
            info["consumers"]["old-home"].append({"id": "another-container", "running": True,
                                                  "project": "px-" + base.RID})
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "unexpected_volume_writer"):
                migration.verify_handoff(info, imported)

    def test_handoff_rejects_wrong_account_or_wrong_volume(self):
        imported, info, agent, gateway = self.handoff_fixture()
        with patch.object(migration, "containers", return_value=[agent, gateway]):
            agent["labels"]["peixian.uid"] = "f" * 32
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "agent_owner_mismatch"):
                migration.verify_handoff(info, imported)
            agent["labels"]["peixian.uid"] = base.UID
            agent["mounts"][0]["Name"] = "another-account-home"
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "agent_volume_mismatch"):
                migration.verify_handoff(info, imported)

    def test_handoff_gateway_may_use_workspace_but_never_home(self):
        imported, info, agent, gateway = self.handoff_fixture()
        with patch.object(migration, "containers", return_value=[agent, gateway]):
            info["consumers"]["old-home"].append({"id": "new-gateway", "running": True})
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "unexpected_volume_writer"):
                migration.verify_handoff(info, imported)
            info["consumers"]["old-home"].pop()
            gateway["mounts"][0]["Name"] = "another-account-workspace"
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "agent_volume_mismatch"):
                migration.verify_handoff(info, imported)

    def test_retry_requires_explicit_flag_and_all_legacy_volume_writers_stopped(self):
        imported = {"uid": base.UID, "runtime_id": base.RID, "status": "failed"}
        with patch.object(migration, "api_call") as api:
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "explicit_flag"):
                migration.retry_import(object(), "client-a", imported, "new-snapshot", False)
            info = {"containers": {"old": {"running": False}}, "consumers": {"home": [{"running": True}]}}
            with patch.object(migration, "inventory", return_value=info), self.assertRaisesRegex(
                    migration.runtime.RuntimeFailure, "stopped_sources"):
                migration.retry_import(object(), "client-a", imported, "new-snapshot", True)
            api.assert_not_called()

    def test_retry_binds_same_identity_and_new_offline_snapshot(self):
        imported = {"uid": base.UID, "runtime_id": base.RID, "status": "failed"}
        info = {"containers": {"old": {"running": False}}, "consumers": {}}
        with patch.object(migration, "inventory", return_value=info), \
             patch.object(migration, "api_call", return_value=imported) as api:
            self.assertTrue(migration.retry_import("api", "client-a", imported, "new-snapshot", True))
            api.assert_called_once_with("api", "POST", "legacy-retry", json={
                "uid": base.UID, "snapshot_id": "new-snapshot", "legacy_stopped": True})
            api.return_value = {"uid": "another-user", "runtime_id": base.RID}
            with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "identity_mismatch"):
                migration.retry_import("api", "client-a", imported, "new-snapshot", True)

    def test_first_import_never_uses_retry_endpoint(self):
        with patch.object(migration, "api_call") as api, patch.object(migration, "inventory") as inventory:
            self.assertFalse(migration.retry_import(object(), "client-a", {"status": "pending"}, "snapshot", False))
            api.assert_not_called()
            inventory.assert_not_called()

    def test_import_accepts_202_without_exposing_password(self):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202, json={"uid": base.UID})),
                          base_url="http://127.0.0.1") as api:
            self.assertEqual(migration.api_call(api, "POST", "legacy-import", json={"password": "synthetic"}), {"uid": base.UID})

    def test_migrate_without_execute_does_not_access_docker_or_secrets(self):
        result = subprocess.run([sys.executable, str(base.ROOT / "console-migrate.py"), "migrate", "--client", "client-a"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "plan")

    def migration_case(self, *, message_changed=False, workspace_changed=False):
        events = []
        saved = self.root / "snapshot"
        saved.mkdir()
        (saved / "snapshot.json").write_text('{"id":"synthetic-snapshot"}')
        release = self.root / "runtime" / "releases" / "1"
        (release / "private").mkdir(parents=True)
        (release / "private/gateway-token").write_text("synthetic-key")
        state = {"compose": str(release / "compose.json"), "paused": False, "revision": 1}
        info = {"client": "client-a", "legacy": {"home_volume": "synthetic-home", "workspace_volume": "synthetic-workspace"},
                "containers": {"client-a": {"running": False, "image_id": "synthetic-image"}}, "consumers": {}}
        evidence = {"id": "synthetic-snapshot", "archives": {"home_volume": {"manifest_sha256": "h"},
                    "workspace_volume": {"manifest_sha256": "w"}}}
        manager = SimpleNamespace(root=self.root, state=lambda _: state, directory=lambda _: self.root / "runtime",
                                  verify=lambda *_: events.append("verify-runtime"))
        ready = False

        def step():
            nonlocal ready
            events.append("worker")
            ready = True

        def request(api, method, path, **kwargs):
            if path == "legacy-import":
                events.append("import")
                self.assertEqual(events.count("snapshot"), 2)
                self.assertEqual(kwargs["json"]["snapshot"]["id"], evidence["id"])
                return {"uid": base.UID, "runtime_id": base.RID}
            return {"status": "ready" if ready else "provisioning", "revision": 1, "desired": 1}

        def snap(*args, **kwargs):
            self.assertTrue(kwargs["require_stopped"])
            self.assertIn("stop", events)
            events.append("snapshot")
            return saved, evidence

        existing = {"ids": ["s1"], "messages": {"s1": {"count": 1, "sha256": "a" * 64}}, "message_count": 1}
        current = {"ids": ["s1", "s2"], "messages": {"s1": {"count": 1, "sha256": ("b" if message_changed else "a") * 64},
                   "s2": {"count": 0, "sha256": "c" * 64}}, "message_count": 1}
        with patch.object(migration, "inventory", return_value=info), patch.object(migration, "old_sessions", return_value=existing), \
             patch.object(migration, "stop_legacy", side_effect=lambda *_: events.append("stop") or existing), \
             patch.object(migration, "snapshot", side_effect=snap), patch.object(migration, "verify_snapshot", return_value=evidence), \
             patch.object(migration, "account_password", return_value="synthetic-new-password"), \
             patch.object(migration, "api_call", side_effect=request), patch.object(migration.worker, "Worker", return_value=SimpleNamespace(once=step)), \
             patch.object(migration, "private_sessions", return_value=current), patch.object(migration.time, "sleep"), \
             patch.object(migration, "verify_handoff", return_value={"only_expected_runtime_uses_volumes": True}), \
             patch.object(migration, "archive_volume", return_value={"manifest_sha256": "changed" if workspace_changed else "w"}) as archive, \
             patch.object(migration, "rollback") as rollback:
            if message_changed or workspace_changed:
                with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "migration_failed_rolled_back"):
                    migration.migrate(manager, object(), "client-a", [])
                rollback.assert_called_once()
                return
            path = migration.migrate(manager, object(), "client-a", [])
        journal = json.loads(path.read_text())
        self.assertEqual(journal["status"], "passed")
        self.assertEqual(journal["old_session_ids"], ["s1"])
        self.assertEqual(journal["new_session_ids"], ["s1", "s2"])
        self.assertEqual(journal["old_sessions"]["messages"]["s1"], journal["new_sessions"]["messages"]["s1"])
        self.assertEqual(journal["postbind_workspace"]["manifest_sha256"], "w")
        archive.assert_called_once()
        self.assertIn("verify-runtime", events)

    def test_formal_migration_preserves_message_digests_and_workspace_files(self):
        self.migration_case()

    def test_same_session_ids_but_changed_messages_roll_back(self):
        self.migration_case(message_changed=True)

    def test_changed_workspace_digest_rolls_back(self):
        self.migration_case(workspace_changed=True)

    def test_message_summary_is_canonical_and_does_not_contain_body(self):
        routes = {"/session?directory=%2Fworkspace&limit=100000": [{"id": "ses_synthetic"}],
                  "/session/ses_synthetic/message?directory=%2Fworkspace": [{"info": {"id": "msg_1"}, "parts": [{"text": "synthetic body"}]}]}
        first = migration.session_inventory(routes.__getitem__)
        routes["/session/ses_synthetic/message?directory=%2Fworkspace"] = [{"parts": [{"text": "synthetic body"}], "info": {"id": "msg_1"}}]
        self.assertEqual(first, migration.session_inventory(routes.__getitem__))
        self.assertEqual(first["message_count"], 1)
        self.assertNotIn("synthetic body", json.dumps(first))
        routes["/session/ses_synthetic/message?directory=%2Fworkspace"][0]["parts"][0]["text"] = "changed"
        changed = migration.session_inventory(routes.__getitem__)
        self.assertEqual(first["ids"], changed["ids"])
        with self.assertRaisesRegex(migration.runtime.RuntimeFailure, "message_digest_changed"):
            migration.verify_migrated_sessions(first, changed)

    def test_stop_captures_final_messages_after_entry_stop_and_idle_before_agent_stop(self):
        events = []
        info = {"client": "client-a", "containers": {name: {"id": name, "running": True}
                for name in ("client-a", "client-a-entry", "client-a-deepseek")}}
        summary = {"ids": [], "messages": {}, "message_count": 0}
        def docker(*args, **kwargs):
            events.append(args[0] + ":" + (args[-1] if args[0] == "stop" else "idle"))
            return "{}"
        with patch.object(migration, "docker", side_effect=docker), \
             patch.object(migration, "old_session_snapshot", side_effect=lambda *_: events.append("capture") or summary), \
             patch.object(migration, "inventory", return_value={"containers": {}, "consumers": {}}):
            self.assertEqual(migration.stop_legacy(info), summary)
        self.assertEqual(events, ["stop:client-a-entry", "exec:idle", "capture", "stop:client-a-deepseek", "stop:client-a"])


    def test_rollback_stops_new_runtime_and_backs_up_new_files_before_old_restart(self):
        events = []
        directory = self.root / "runtime"
        release = directory / "releases" / "1"
        (release / "private").mkdir(parents=True)
        (release / "private/gateway-token").write_text("synthetic-key")
        compose = release / "compose.json"
        compose.write_text(json.dumps({"volumes": {"files": {"name": "synthetic-managed-files"}}}))
        state = {"compose": str(compose), "revision": 1}
        current = ["synthetic-container"]
        manager = SimpleNamespace(root=self.root, state=lambda _: state, directory=lambda _: directory,
            running=lambda _: current.copy(), wait_idle=lambda *_: events.append("idle"),
            components=lambda _: ({key: "stopped" for key in ("agent", "gateway", "relay")}, True),
            mutation_state=lambda _: "idle",
            stop_checked=lambda *_: (events.append("stop-new"), current.clear()))
        saved = self.root / "saved"
        saved.mkdir()
        journal = {"client": "client-a", "imported": {"uid": base.UID, "runtime_id": base.RID},
                   "snapshot": str(saved), "before": {"containers": {"client-a": {"image_id": "synthetic-image"}}}}
        report = {"archives": {"home_volume": {}, "workspace_volume": {}}}

        def request(*args, **kwargs):
            self.assertEqual(current, [])
            if args[1] == "GET":
                return {"state_version": 7}
            if args[2] == "reconcile":
                self.assertTrue(kwargs["json"]["complete"])
                events.append("control-observation")
                return {"classification": "stopped"}
            self.assertTrue(kwargs["json"]["cleanup_confirmed"])
            self.assertEqual(kwargs["json"]["snapshot_id"], "synthetic-snapshot")
            self.assertEqual(kwargs["json"]["expected_state_version"], 7)
            self.assertEqual(len(kwargs["json"]["observation_id"]), 32)
            events.append("control-rollback")

        with patch.object(migration, "api_call", side_effect=request), \
             patch.object(migration, "verify_snapshot", return_value={"id": "synthetic-snapshot"}), \
             patch.object(migration, "snapshot", side_effect=lambda *_args, **_kwargs: (events.append("snapshot") or saved, report)), \
             patch.object(migration, "containers", return_value=[]), \
             patch.object(migration, "archive_volume", side_effect=lambda *_: events.append("new-files-backup") or {"sha256": "synthetic"}), \
             patch.object(migration, "start_legacy", side_effect=lambda *_: events.append("start-old")):
            migration.rollback(manager, object(), journal, self.root / "journal.json")
        self.assertEqual(events, ["idle", "stop-new", "control-observation", "control-rollback", "snapshot", "new-files-backup", "start-old"])
        self.assertEqual(journal["status"], "rolled_back")
        self.assertEqual(json.loads((saved / "snapshot.json").read_text())["retained_managed_files_volume"], "synthetic-managed-files")

    def test_foreign_running_volume_consumer_blocks_migration_before_stop(self):
        info = {"consumers": {"home": [{"running": True, "project": "another-project"}]}}
        with patch.object(migration, "inventory", return_value=info), patch.object(migration, "stop_legacy") as stop, \
             self.assertRaisesRegex(migration.runtime.RuntimeFailure, "legacy_volume_has_foreign_writer"):
            migration.migrate(SimpleNamespace(root=self.root), object(), "client-a", [])
        stop.assert_not_called()

    def test_online_snapshot_cannot_satisfy_offline_gate(self):
        info = {"containers": {"client-a": {"running": True}}, "consumers": {"volume": [{"running": True}]}}
        with patch.object(migration, "inventory", return_value=info), self.assertRaisesRegex(
                migration.runtime.RuntimeFailure, "legacy_or_volume_writer_still_running"):
            migration.snapshot(self.root, "client-a", require_stopped=True)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
