"""Host lifecycle tests use synthetic data and never contact Docker or models."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import httpx


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("console_worker_test", ROOT / "console-worker.py")
worker = importlib.util.module_from_spec(loader)
loader.loader.exec_module(worker)
runtime = worker.runtime
RID, UID, JID = "a" * 32, "b" * 32, "c" * 32


def spec(revision=1):
    return {"runtime_id": RID, "uid": UID, "revision": revision,
            "private": {"gateway_key": "synthetic-gateway-credential-32char", "agent_password": "synthetic-agent-password"},
            "config": {"enabled_providers": [], "mcp": {}, "share": "disabled", "autoupdate": False},
            "models": [], "plugins": [], "skills": []}


def job(action="provision", revision=1):
    return {"id": JID, "uid": UID, "action": action, "lease": "synthetic-lease", "revision": revision}


def package(extra=None, *, entry="entry.mjs"):
    manifest = {"id": "synthetic", "version": "1.0.0", "entry": entry, "opencode_version": "1.18.30"}
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(entry, "export default async (ctx, options) => ({tool:{}});export const test = async () => true;")
        for name, content in (extra or []):
            if isinstance(name, str):
                info = zipfile.ZipInfo()
                info.filename = name  # Preserve unsafe backslashes on Windows for the rejection test.
                name = info
            archive.writestr(name, content)
    raw = data.getvalue()
    return raw, {"id": "synthetic", "version": "1.0.0", "manifest": manifest,
                 "digest": hashlib.sha256(raw).hexdigest(), "options": {"synthetic": True}}


class FakeRuntime(runtime.RuntimeManager):
    def __init__(self, root):
        self.root, self.agent_image, self.gateway_image = Path(root), "local-agent", "local-gateway"
        self.maximum, self.control_container = 4, "peixian-console"
        self.commands, self.active, self.fail_revision = [], False, None
        self.fail_stop, self.busy, self.fail_prepare = False, False, False

    def docker_run(self, *args, **kwargs):
        self.commands.append(tuple(args))
        if args[0] == "ps":
            return "synthetic-container" if self.active else ""
        if args[:2] == ("image", "inspect"):
            return '[{"Os":"linux","Architecture":"amd64"}]'
        raise AssertionError("Unexpected Docker operation")

    def compose(self, file, *args, **kwargs):
        self.commands.append(("compose", str(file), *args))
        if args[0] == "up":
            self.active = True
        elif args[0] == "stop":
            if not self.fail_stop:
                self.active = False
        else:
            raise AssertionError("Unexpected Compose operation")

    def capacity(self, runtime_id):
        pass

    def ensure_volumes(self, spec, compose):
        pass

    def ensure_networks(self, spec):
        pass

    def attach_control(self, runtime_id, uid=None):
        pass

    def verify(self, spec, revision):
        if revision == self.fail_revision:
            raise runtime.RuntimeFailure("synthetic_health_failed")

    def wait_idle(self, spec, heartbeat, **kwargs):
        if self.busy:
            raise runtime.Deferred()

    def prepare(self, spec, download):
        if self.fail_prepare:
            raise runtime.RuntimeFailure("synthetic_prepare_failed")
        return super().prepare(spec, download)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.acl = patch.object(runtime, "grant_container_read")
        self.acl.start()

    def tearDown(self):
        self.acl.stop()
        self.temp.cleanup()

    def test_facts_status_probe_uses_fixed_authenticated_management_route(self):
        manager = FakeRuntime(self.root)
        value = spec()
        with patch.object(manager, "docker_run", return_value='{"protocol":"facts-coordinator-v1","ready":true,"modules":["night"]}') as request:
            result = manager.private_get(value, "/internal/facts/status")
            self.assertTrue(result["ready"])
            payload = json.loads(request.call_args.kwargs["data"])
            self.assertTrue(payload["url"].endswith("/internal/facts/status"))
            self.assertEqual(payload["key"], value["private"]["gateway_key"])
        with self.assertRaises(runtime.RuntimeFailure):
            manager.private_get(value, "/internal/facts/arbitrary")

    def test_skill_identity_compatibility_in_real_release_preparation(self):
        for identity in ("a" * 28, "b" * 32):
            with self.subTest(identity=identity):
                value = spec()
                value["skills"] = [{"id": identity, "name": "method", "description": "method", "content": "text"}]
                manager = FakeRuntime(self.root / identity)
                release = manager.prepare(value, lambda digest: b"")
                self.assertTrue((release / "agent/skills" / identity / "SKILL.md").is_file())
        for identity in ("../outside", "a" * 27, "a" * 29, "a" * 33):
            value = spec()
            value["skills"] = [{"id": identity, "name": "method", "description": "method", "content": "text"}]
            with self.subTest(identity=identity), self.assertRaises(runtime.RuntimeFailure):
                FakeRuntime(self.root / str(len(identity))).prepare(value, lambda digest: b"")

    def test_compose_has_three_private_services_and_separate_mounts(self):
        value = runtime.compose_spec(spec(), self.root, agent_image="agent", gateway_image="gateway")
        self.assertEqual(value["name"], "px-" + RID)
        self.assertEqual(set(value["services"]), {"agent", "gateway", "model-relay"})
        self.assertEqual(value["services"]["agent"]["networks"], ["internal"])
        self.assertTrue(value["networks"]["internal"]["internal"])
        self.assertTrue(value["networks"]["management"]["internal"])
        self.assertFalse(value["networks"]["egress"].get("internal", False))
        for name, service in value["services"].items():
            self.assertNotIn("ports", service)
            self.assertEqual(service["user"], "10001:10001")
            self.assertTrue(service["read_only"])
            self.assertEqual(service["pull_policy"], "never")
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertNotIn("/var/run/docker.sock", json.dumps(service))
            self.assertNotIn("synthetic-agent-password", json.dumps(service))
        agent = json.dumps(value["services"]["agent"]["volumes"])
        self.assertNotIn('"relay"', agent)
        self.assertNotIn("gateway-token", agent)
        self.assertEqual(value["services"]["gateway"]["networks"]["management"]["aliases"], ["px-" + RID + "-gateway"])

    def test_legacy_only_uses_explicit_safe_external_volumes(self):
        value = spec()
        value["private"]["legacy"] = {"home_volume": "verified-home", "workspace_volume": "verified-workspace"}
        result = runtime.compose_spec(value, self.root, agent_image="a", gateway_image="g")
        self.assertEqual(result["volumes"]["home"], {"name": "verified-home", "external": True})
        value["private"]["legacy"]["home_volume"] = "../../private"
        with self.assertRaises(runtime.RuntimeFailure):
            runtime.compose_spec(value, self.root, agent_image="a", gateway_image="g")

    def test_plugin_digest_and_archive_paths_fail_closed(self):
        for extra in [None, [("../escape", "x")], [("a\\escape", "x")], [("ENTRY.MJS", "x")]]:
            with self.subTest(extra=extra):
                raw, expected = package(extra)
                if extra is None:
                    expected["digest"] = "0" * 64
                with self.assertRaises(runtime.RuntimeFailure):
                    runtime.unpack_plugin(raw, expected, self.root / "target")
                self.assertFalse((self.root / "escape").exists())

    def test_plugin_symlink_is_rejected(self):
        link = zipfile.ZipInfo("linked.mjs")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        raw, expected = package([(link, "../../secret")])
        with self.assertRaisesRegex(runtime.RuntimeFailure, "unsafe_plugin_archive"):
            runtime.unpack_plugin(raw, expected, self.root / "target")

    def test_prepare_separates_keys_and_wraps_only_default_plugin_export(self):
        value = spec()
        raw, plugin = package(entry="src/main.mjs")
        value["plugins"] = [plugin]
        value["models"] = [{"api_key": "synthetic-model-key"}]
        value["skills"] = [{"id": "d" * 32, "name": "Test skill", "description": "Synthetic", "content": "Use synthetic data."}]
        manager = FakeRuntime(self.root)
        release = manager.prepare(value, lambda digest: raw)
        config = json.loads((release / "agent/opencode.json").read_text())
        self.assertEqual(config["plugin"], ["file:///managed/loaders/synthetic.mjs"])
        wrapper = (release / "agent/loaders/synthetic.mjs").read_text()
        self.assertIn("export default async (context) => plugin(context, options, platform)", wrapper)
        self.assertNotIn("export *", wrapper)
        self.assertIn("export *", (release / "gateway/plugins/synthetic/1.0.0/entry.mjs").read_text())
        for file in (release / "agent").rglob("*"):
            if file.is_file():
                self.assertNotIn("synthetic-model-key", file.read_text(encoding="utf-8"))
        self.assertIn("synthetic-model-key", (release / "relay/model-relay.json").read_text())
        self.assertEqual(manager.prepare(value, lambda _: self.fail("Redownloaded immutable package")), release)
        value["config"]["enabled_providers"] = ["changed"]
        with self.assertRaisesRegex(runtime.RuntimeFailure, "immutable_release_conflict"):
            manager.prepare(value, lambda _: raw)

    def test_path_escape_is_rejected(self):
        with self.assertRaisesRegex(runtime.RuntimeFailure, "path_outside_worker_root"):
            runtime.inside(self.root, self.root / ".." / "outside")
        for identity in ("../x", "A" * 32, "a" * 31, None):
            with self.assertRaises(runtime.RuntimeFailure):
                runtime.check_id(identity)

    def apply(self, manager, revision=1, action="provision"):
        return manager.apply(job(action, revision), spec(revision), lambda _: b"", lambda: None)

    def test_success_is_idempotent_and_preserves_three_volumes(self):
        manager = FakeRuntime(self.root)
        self.assertTrue(self.apply(manager)["ok"])
        self.assertTrue(self.apply(manager)["ok"])
        state = manager.state(RID)
        self.assertEqual(state["revision"], 1)
        compose = json.loads(Path(state["compose"]).read_text())
        self.assertEqual(set(compose["volumes"]), {"home", "workspace", "files"})
        self.assertFalse(any("down" in args or "rm" in args for args in manager.commands))

    def test_busy_runtime_is_deferred_without_compose_stop(self):
        manager = FakeRuntime(self.root)
        self.apply(manager)
        manager.commands.clear()
        manager.busy = True
        with self.assertRaises(runtime.Deferred):
            self.apply(manager, 2, "apply")
        self.assertFalse(any(args[0] == "compose" for args in manager.commands))

    def test_failure_rolls_back_to_previous_healthy_revision(self):
        manager = FakeRuntime(self.root)
        self.apply(manager)
        manager.fail_revision = 2
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.apply(manager, 2, "apply")
        self.assertTrue(caught.exception.rolled_back)
        self.assertFalse(caught.exception.cleanup_confirmed)
        self.assertEqual(manager.state(RID)["revision"], 1)
        self.assertTrue(manager.active)

    def test_prepare_failure_keeps_existing_healthy_runtime_reserved(self):
        manager = FakeRuntime(self.root)
        self.apply(manager)
        manager.fail_prepare = True
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.apply(manager, 2, "apply")
        self.assertTrue(caught.exception.rolled_back)
        self.assertTrue(manager.active)

    def test_first_failure_releases_slot_only_after_confirmed_stop(self):
        manager = FakeRuntime(self.root)
        manager.fail_revision = 1
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.apply(manager)
        self.assertTrue(caught.exception.cleanup_confirmed)
        self.assertFalse(manager.active)
        self.assertIsNone(manager.state(RID))

    def test_unconfirmed_stop_keeps_slot_reserved(self):
        manager = FakeRuntime(self.root)
        manager.fail_revision, manager.fail_stop = 1, True
        with self.assertRaises(runtime.RuntimeFailure) as caught:
            self.apply(manager)
        self.assertFalse(caught.exception.cleanup_confirmed)
        self.assertFalse(caught.exception.rolled_back)
        self.assertTrue(manager.active)

    def test_pause_never_succeeds_when_stop_unconfirmed(self):
        manager = FakeRuntime(self.root)
        self.apply(manager)
        manager.fail_stop = True
        with self.assertRaises(runtime.RuntimeFailure):
            self.apply(manager, 1, "pause")
        self.assertFalse(manager.state(RID)["paused"])

    def test_interrupted_initial_compose_resumes_only_with_owned_journal(self):
        manager = FakeRuntime(self.root)
        release = manager.prepare(spec(), lambda _: b"")
        manager.active = True
        with self.assertRaisesRegex(runtime.RuntimeFailure, "runtime_state_missing"):
            self.apply(manager)
        runtime.write_json(manager.directory(RID) / "pending.json", {
            "uid": UID, "runtime_id": RID, "revision": 1, "compose": str(release / "compose.json")})
        self.assertTrue(self.apply(manager)["ok"])

    def test_ready_requires_skill_instance_initialization(self):
        manager = FakeRuntime(self.root)
        seen = []

        def probe(value, endpoint):
            seen.append(endpoint)
            return {"/health": {"ok": True, "revision": 1, "runtime_id": RID},
                    "/global/health": {"healthy": True, "version": "1.18.30"}, "/skill": []}[endpoint]

        manager.private_get = probe
        runtime.RuntimeManager.verify(manager, spec(), 1)
        self.assertEqual(seen, ["/health", "/global/health", "/skill"])
        manager.private_get = lambda *_: {"ok": True, "healthy": True, "version": "1.18.30", "revision": 1, "runtime_id": RID}
        with patch.object(runtime.time, "sleep"), self.assertRaisesRegex(runtime.RuntimeFailure, "runtime_revision_health_failed"):
            runtime.RuntimeManager.verify(manager, spec(), 1)


class WorkerTests(unittest.TestCase):
    def test_legacy_claim_is_rejected_before_any_host_mutation(self):
        bodies = []

        def dispatch(request):
            if request.url.path.endswith("/reconcile"):
                return httpx.Response(200, json={"protocol_version": 2, "items": []})
            if request.url.path.endswith("/claim"):
                return httpx.Response(200, json={"job": job(), "spec": spec()})
            bodies.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"ok": True})

        class Manager:
            def reconcile(self, **kwargs):
                return []

            def apply(self, *args):
                raise runtime.RuntimeFailure("synthetic_failure", cleanup_confirmed=False)

        out = io.StringIO()
        with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://127.0.0.1") as client:
            with contextlib.redirect_stdout(out):
                with self.assertRaisesRegex(runtime.RuntimeFailure, "worker_protocol_mismatch"):
                    worker.Worker(client, Manager()).once()
        self.assertEqual(bodies, [])
        self.assertNotIn("synthetic-gateway-credential", out.getvalue())
        self.assertNotIn("synthetic-agent-password", out.getvalue())
        self.assertNotIn("synthetic-lease", out.getvalue())


if __name__ == "__main__":
    unittest.main()


class StopConfirmationTests(unittest.TestCase):
    def test_daemon_exit_visibility_is_polled(self):
        manager = object.__new__(runtime.RuntimeManager)
        from unittest.mock import Mock
        manager.compose = Mock()
        manager.running = Mock(side_effect=[["synthetic"], []])
        with patch.object(runtime.time, "sleep") as sleep:
            manager.stop_checked(RID, Path("synthetic.json"))
        self.assertEqual(manager.running.call_count, 2)
        sleep.assert_called_once_with(0.2)

    def test_unconfirmed_exit_fails_closed(self):
        manager = object.__new__(runtime.RuntimeManager)
        from unittest.mock import Mock
        manager.compose = Mock()
        manager.running = Mock(return_value=["synthetic"])
        with patch.object(runtime.time, "monotonic", side_effect=[0, 6]):
            with self.assertRaises(runtime.RuntimeFailure) as result:
                manager.stop_checked(RID, Path("synthetic.json"))
        self.assertEqual(result.exception.code, "runtime_stop_unconfirmed")
