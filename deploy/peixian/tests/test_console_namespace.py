"""Deployment namespace checks use synthetic state and mocked Docker only."""
import contextlib
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_console_runtime as base

runtime, worker = base.runtime, base.worker
NS = "agent-framework"


class NamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = base.FakeRuntime(self.root)
        self.manager.namespace = NS
        self.manager.control_container = "agent-framework-console"

    def tearDown(self):
        self.temp.cleanup()

    def labels(self, **changes):
        return {runtime.MANAGED: "true", runtime.DEPLOYMENT: NS, "peixian.runtime_id": base.RID,
                "peixian.uid": base.UID, **changes}

    def compose(self):
        return runtime.compose_spec(base.spec(), self.root, agent_image="new-agent", gateway_image="new-gateway", namespace=NS)

    def construct(self, *, namespace=NS, container="agent-framework-console"):
        with patch.object(runtime, "protect_root", side_effect=lambda root: root.mkdir(parents=True, exist_ok=True)), \
             patch.object(runtime.shutil, "which", return_value="mock-docker"), \
             patch.object(runtime.RuntimeManager, "docker_run", return_value='[{"Endpoints":{"docker":{"Host":"npipe://local"}}}]'), \
             patch.dict(os.environ, {"DOCKER_HOST": ""}):
            return runtime.RuntimeManager(self.root, namespace=namespace, control_container=container)

    def test_namespace_validation_and_legacy_project_name(self):
        self.assertEqual(runtime.project_name(base.RID), "px-" + base.RID)
        self.assertEqual(runtime.project_name(base.RID, NS), NS + "-" + base.RID)
        for value in ("", "A", "../x", "a_b", "1first", "a" * 17, "a\n", 1, False):
            with self.subTest(value=value), self.assertRaisesRegex(runtime.RuntimeFailure, "invalid_deployment_namespace"):
                runtime.project_name(base.RID, value)
        self.assertEqual(runtime.check_namespace("a" * 16), "a" * 16)

    def test_compose_names_and_all_resource_labels_are_namespaced(self):
        config = self.compose()
        project = NS + "-" + base.RID
        self.assertEqual(config["name"], project)
        for group in ("services", "networks", "volumes"):
            for name, item in config[group].items():
                self.assertEqual(item["labels"][runtime.DEPLOYMENT], NS)
                self.assertEqual(item["labels"]["peixian.uid"], base.UID)
                if group != "services":
                    self.assertEqual(item["name"], project + "-" + name)
                    self.assertFalse(item.get("external"))
        self.assertEqual(config["services"]["gateway"]["networks"]["management"]["aliases"], [project + "-gateway"])
        self.assertNotIn("ports", config["services"]["agent"])

    def test_framework_rejects_every_non_null_legacy_value_before_side_effects(self):
        for legacy in ({}, {"home_volume": "old-home"}, [], "old-home", False):
            spec = base.spec()
            spec["private"]["legacy"] = legacy
            with self.subTest(legacy=legacy), self.assertRaisesRegex(runtime.RuntimeFailure, "legacy_volumes_forbidden"):
                runtime.compose_spec(spec, self.root, agent_image="a", gateway_image="g", namespace=NS)
            with self.assertRaisesRegex(runtime.RuntimeFailure, "legacy_volumes_forbidden"):
                self.manager.apply(base.job(), spec, lambda _: b"", lambda: None)
        self.assertEqual(self.manager.commands, [])
        self.assertEqual(list(self.root.iterdir()), [])
        spec["private"]["legacy"] = None
        runtime.compose_spec(spec, self.root, agent_image="a", gateway_image="g", namespace=NS)

    def test_empty_root_is_stamped_and_same_identity_reopens(self):
        self.construct()
        self.assertEqual(json.loads((self.root / "deployment.json").read_text()), {
            runtime.DEPLOYMENT: NS, "control_container": "agent-framework-console", "version": 1})
        self.construct()
        for namespace, container in (("other", "agent-framework-console"), (NS, "wrong-control"), (None, "agent-framework-console")):
            with self.assertRaisesRegex(runtime.RuntimeFailure, "deployment_root_identity_mismatch"):
                self.construct(namespace=namespace, container=container)

    def test_nonempty_unmarked_root_is_rejected_before_acl_or_docker(self):
        (self.root / "legacy-state").write_text("synthetic")
        with patch.object(runtime, "protect_root") as acl, patch.object(runtime.RuntimeManager, "docker_run") as docker, \
             self.assertRaisesRegex(runtime.RuntimeFailure, "unmarked_nonempty"):
            runtime.RuntimeManager(self.root, namespace=NS)
        acl.assert_not_called()
        docker.assert_not_called()
        self.assertEqual((self.root / "legacy-state").read_text(), "synthetic")

    def test_old_mode_keeps_existing_unmarked_root_compatible(self):
        (self.root / "old-state").write_text("synthetic")
        self.construct(namespace=None)
        self.assertFalse((self.root / "deployment.json").exists())

    def test_invalid_stamp_fails_closed(self):
        (self.root / "deployment.json").write_text("not-json")
        with self.assertRaisesRegex(runtime.RuntimeFailure, "identity_invalid"):
            self.construct()

    def test_release_and_state_namespace_cannot_be_reused_by_other_deployment(self):
        with patch.object(runtime, "grant_container_read"):
            release = self.manager.prepare(base.spec(), lambda _: b"")
        for relative in ("publication.json", "agent/revision.json", "gateway/revision.json", "relay/revision.json"):
            self.assertEqual(json.loads((release / relative).read_text())[runtime.DEPLOYMENT], NS)
        self.assertEqual(self.manager.prepare(base.spec(), lambda _: self.fail("redownload")), release)
        published = json.loads((release / "publication.json").read_text())
        published[runtime.DEPLOYMENT] = "foreign"
        runtime.write_json(release / "publication.json", published)
        with self.assertRaisesRegex(runtime.RuntimeFailure, "immutable_release_conflict"):
            self.manager.prepare(base.spec(), lambda _: b"")
        state = {"runtime_id": base.RID, "uid": base.UID, "compose": str(release / "compose.json"), runtime.DEPLOYMENT: NS}
        runtime.write_json(self.manager.directory(base.RID) / "state.json", state)
        self.assertEqual(self.manager.state(base.RID), state)
        state.pop(runtime.DEPLOYMENT)
        runtime.write_json(self.manager.directory(base.RID) / "state.json", state)
        with self.assertRaisesRegex(runtime.RuntimeFailure, "state_owner_mismatch"):
            self.manager.state(base.RID)

    def test_compose_rejects_foreign_labels_names_and_external_volume(self):
        for target in ("namespace", "name", "external", "uid"):
            value = self.compose()
            if target == "namespace": value["services"]["gateway"]["labels"][runtime.DEPLOYMENT] = "other"
            elif target == "name": value["volumes"]["home"]["name"] = "old-home"
            elif target == "external": value["volumes"]["home"]["external"] = True
            else: value["services"]["gateway"]["labels"] = {**value["services"]["gateway"]["labels"], "peixian.uid": "f" * 32}
            with self.subTest(target=target), self.assertRaises(runtime.RuntimeFailure):
                self.manager.check_compose(value, base.RID)

    def test_stopped_foreign_container_is_rejected_before_compose_adoption(self):
        labels = self.labels(**{"com.docker.compose.project": self.manager.project_name(base.RID), "com.docker.compose.service": "agent"})
        item = {"Id": "synthetic-id", "Config": {"Labels": labels}, "State": {"Running": False}}
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            return "synthetic-id" if args[0] == "ps" else json.dumps([item])
        self.manager.docker_run = docker
        self.assertEqual(self.manager.running(base.RID, uid=base.UID), [])
        self.assertIn("-a", calls[0])
        labels[runtime.DEPLOYMENT] = "foreign"
        with self.assertRaisesRegex(runtime.RuntimeFailure, "resource_owner_mismatch"):
            self.manager.running(base.RID, uid=base.UID)

    def test_existing_network_requires_namespace_and_account_owner(self):
        project = self.manager.project_name(base.RID)
        labels = self.labels(**{runtime.DEPLOYMENT: "foreign"})
        def docker(*args, **kwargs):
            if args[:2] == ("network", "ls"): return project + "-internal"
            if args[:2] == ("network", "inspect"):
                return json.dumps([{"Name": project + "-internal", "Internal": True, "Labels": labels}])
            self.fail("Unexpected mutation")
        self.manager.docker_run = docker
        with self.assertRaisesRegex(runtime.RuntimeFailure, "resource_owner_mismatch"):
            runtime.RuntimeManager.ensure_networks(self.manager, base.spec())

    def test_volume_create_race_rechecks_owner_before_chown(self):
        config = self.compose()
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == "ps" or args[:2] == ("volume", "ls"): return ""
            if args[:2] == ("volume", "create"): return args[-1]
            if args[:2] == ("volume", "inspect"):
                return json.dumps([{"Labels": self.labels(**{runtime.DEPLOYMENT: "foreign"})}])
            self.fail("Unowned volume must never be initialized")
        self.manager.docker_run = docker
        with self.assertRaisesRegex(runtime.RuntimeFailure, "resource_owner_mismatch"):
            runtime.RuntimeManager.ensure_volumes(self.manager, base.spec(), config)
        create = next(call for call in calls if call[:2] == ("volume", "create"))
        self.assertIn(runtime.DEPLOYMENT + "=" + NS, create)
        self.assertIn("peixian.uid=" + base.UID, create)
        self.assertFalse(any(call[0] == "run" for call in calls))

    def test_reconcile_never_connects_unmarked_state_or_wrong_control(self):
        directory = self.manager.directory(base.RID)
        runtime.write_json(directory / "state.json", {"runtime_id": base.RID, "uid": base.UID, "paused": False,
                           "compose": str(directory / "release/compose.json")})
        with patch.object(self.manager, "attach_control") as attach:
            self.assertEqual(runtime.RuntimeManager.reconcile(self.manager), ["registered_runtime_network_reconcile_failed"])
            attach.assert_not_called()
        self.manager.docker_run = lambda *_args, **_kwargs: json.dumps({runtime.DEPLOYMENT: "old-console"})
        with self.assertRaisesRegex(runtime.RuntimeFailure, "control_owner_mismatch"):
            runtime.RuntimeManager.attach_control(self.manager, base.RID)

    def test_capacity_refuses_old_or_foreign_agent_before_engine_budget_or_mutations(self):
        for namespace in (None, "another"):
            labels = self.labels()
            if namespace is None: labels.pop(runtime.DEPLOYMENT)
            else: labels[runtime.DEPLOYMENT] = namespace
            def docker(*args, **kwargs):
                if args[0] == "ps": return "foreign-agent"
                if args[0] == "inspect": return json.dumps([{"Config": {"Labels": labels}}])
                self.fail("Foreign running deployment must fail immediately")
            self.manager.docker_run = docker
            with self.subTest(namespace=namespace), self.assertRaisesRegex(runtime.RuntimeFailure, "another_deployment_has_running_agents"):
                runtime.RuntimeManager.capacity(self.manager, base.RID)

    def test_own_capacity_excludes_current_runtime_and_preserves_engine_budget(self):
        labels = self.labels()
        self.manager.maximum = 1
        info = {"MemTotal": 12 * 1024**3, "NCPU": 20}
        def docker(*args, **kwargs):
            if args[0] == "ps": return "own-agent"
            if args[0] == "inspect": return json.dumps([{"Config": {"Labels": labels}}])
            if args[0] == "info": return json.dumps(info)
            self.fail("Unexpected mutation")
        self.manager.docker_run = docker
        runtime.RuntimeManager.capacity(self.manager, base.RID)
        labels["peixian.runtime_id"] = "f" * 32
        with self.assertRaisesRegex(runtime.RuntimeFailure, "runtime_capacity_reached"):
            runtime.RuntimeManager.capacity(self.manager, base.RID)
        labels["peixian.runtime_id"] = base.RID
        info["MemTotal"] = 1
        with self.assertRaisesRegex(runtime.RuntimeFailure, "memory_budget_exceeded"):
            runtime.RuntimeManager.capacity(self.manager, base.RID)

    def test_shared_budget_lock_conflicts_across_namespaces_and_releases(self):
        with patch.object(worker.tempfile, "gettempdir", return_value=str(self.root)), \
             patch.object(runtime, "host_identity", return_value="synthetic-os-user"), \
             patch.object(runtime, "protect_root", side_effect=lambda path: path.mkdir(parents=True, exist_ok=True)):
            with worker.budget_lock("one"):
                with self.assertRaisesRegex(runtime.RuntimeFailure, "another_host_worker"):
                    with worker.budget_lock("two"):
                        self.fail("Simultaneous deployment workers were allowed")
            with worker.budget_lock("two"):
                pass
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_main_holds_shared_budget_lock_before_manager_and_entire_worker_loop(self):
        key = self.root / "synthetic-worker-key"
        key.write_text("synthetic-worker-key-value-32-characters")
        events = []
        @contextlib.contextmanager
        def budget(namespace):
            self.assertEqual(namespace, NS)
            events.append("budget-enter")
            try:
                yield
            finally:
                events.append("budget-exit")
        @contextlib.contextmanager
        def local_lock(root):
            events.append("local-enter")
            yield
            events.append("local-exit")
        def manager(*args, **kwargs):
            self.assertEqual(events, ["budget-enter"])
            self.assertEqual(kwargs["namespace"], NS)
            return self.manager
        runner = unittest.mock.Mock()
        runner.once.side_effect = lambda: events.append("once") or False
        argv = ["console-worker.py", "--namespace", NS, "--key-file", str(key), "--once"]
        with patch.object(worker.sys, "argv", argv), patch.object(worker, "budget_lock", side_effect=budget), \
             patch.object(worker, "host_lock", side_effect=local_lock), \
             patch.object(runtime, "RuntimeManager", side_effect=manager), \
             patch.object(worker.httpx, "Client"), patch.object(worker, "Worker", return_value=runner):
            worker.main()
        self.assertEqual(events, ["budget-enter", "local-enter", "once", "local-exit", "budget-exit"])

    def test_legacy_worker_does_not_acquire_new_budget_lock(self):
        with patch.object(runtime, "protect_root") as protect, patch.object(worker, "host_lock") as lock:
            with worker.budget_lock(None): pass
            protect.assert_not_called()
            lock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
