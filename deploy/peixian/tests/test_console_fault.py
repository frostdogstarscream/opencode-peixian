"""Fault driver guard checks; these never access Docker, credentials or models."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("console_fault_test", ROOT / "console-fault-acceptance.py")
fault = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fault)
UID, RID, JID = "a" * 32, "b" * 32, "c" * 32


class ProcessInterrupted(BaseException):
    pass


class FaultDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Path(self.temp.name) / "state.json"
        self.journal.write_text(json.dumps({"uid": UID, "runtime_id": RID, "claims": []}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def manager(self, interrupt=False):
        with patch.object(fault.runtime.RuntimeManager, "__init__", return_value=None):
            return fault.ScopedRuntime(self.temp.name, journal=self.journal, interrupt=interrupt)

    def test_default_is_a_plan_without_secret_or_docker_access(self):
        result = subprocess.run([sys.executable, str(ROOT / "console-fault-acceptance.py")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "plan")
        self.assertNotIn("credential", result.stdout)

    def test_process_exit_occurs_only_after_target_volume_create_completed(self):
        events = []
        manager = self.manager(interrupt=True)
        volume = "px-" + RID + "-home"
        def created(*args, **kwargs):
            events.append("volume-created")
            return volume
        def interrupt(code):
            events.append("exit")
            self.assertEqual(code, 73)
            saved = json.loads(self.journal.read_text())
            self.assertEqual(saved["first_volume"], volume)
            self.assertEqual(saved["phase"], "interrupted_after_volume_create")
            raise ProcessInterrupted()
        with patch.object(fault.runtime.RuntimeManager, "docker_run", side_effect=created), \
             patch.object(fault.os, "_exit", side_effect=interrupt), self.assertRaises(ProcessInterrupted):
            manager.docker_run("volume", "create", "--label", "synthetic=true", volume)
        self.assertEqual(events, ["volume-created", "exit"])

    def test_foreign_volume_is_rejected_before_docker_runs(self):
        manager = self.manager(interrupt=True)
        with patch.object(fault.runtime.RuntimeManager, "docker_run") as docker, self.assertRaisesRegex(
                fault.runtime.RuntimeFailure, "fault_volume_scope_mismatch"):
            manager.docker_run("volume", "create", "another-account-home")
        docker.assert_not_called()

    def test_failed_volume_create_does_not_write_crash_evidence(self):
        manager = self.manager(interrupt=True)
        with patch.object(fault.runtime.RuntimeManager, "docker_run", side_effect=fault.runtime.RuntimeFailure("synthetic-create-failed")), \
             patch.object(fault.os, "_exit") as interrupt, self.assertRaises(fault.runtime.RuntimeFailure):
            manager.docker_run("volume", "create", "px-" + RID + "-home")
        interrupt.assert_not_called()
        self.assertNotIn("first_volume", json.loads(self.journal.read_text()))

    def test_other_accounts_cannot_reach_runtime_apply_or_reconcile(self):
        manager = self.manager()
        self.assertEqual(manager.reconcile(), [])
        with patch.object(fault.runtime.RuntimeManager, "apply") as apply, self.assertRaisesRegex(
                fault.runtime.RuntimeFailure, "fault_runtime_scope_mismatch"):
            manager.apply({"uid": "d" * 32}, {"runtime_id": RID}, lambda _: None, lambda: None)
        apply.assert_not_called()

    def test_claim_race_never_mutates_or_fabricates_observation_for_other_lease(self):
        calls = []
        def dispatch(request):
            calls.append(request)
            if request.url.path.endswith("/claim"):
                return httpx.Response(200, json={"job": {"id": "d" * 32, "uid": "e" * 32, "lease": "synthetic-lease"}})
            return httpx.Response(200, json={})
        with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(dispatch)) as api:
            client = fault.ScopedWorker(api, SimpleNamespace(), self.journal, JID)
            with self.assertRaisesRegex(fault.runtime.RuntimeFailure, "other_job_claimed_without_execution"):
                client.request("POST", "/internal/worker/claim")
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(self.journal.read_text())["claims"], [])

    def test_target_claim_persists_only_lease_digest(self):
        payload = {"job": {"id": JID, "uid": UID, "lease": "synthetic-private-lease"}, "spec": {"runtime_id": RID}}
        with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as api:
            fault.ScopedWorker(api, SimpleNamespace(), self.journal, JID).request("POST", "/internal/worker/claim")
        saved = self.journal.read_text()
        self.assertNotIn("synthetic-private-lease", saved)
        self.assertEqual(len(json.loads(saved)["claims"][0]["lease_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
