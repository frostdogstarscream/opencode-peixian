"""Synthetic failure-boundary checks; no Docker, real credentials or HTTP requests."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

loader = importlib.util.spec_from_file_location("console_role_acceptance_test", Path(__file__).resolve().parents[1] / "console-role-acceptance.py")
acceptance = importlib.util.module_from_spec(loader)
loader.loader.exec_module(acceptance)


class AcceptanceTests(unittest.TestCase):
    def test_dynamic_report_routes_never_include_resource_identifiers(self):
        for path, expected in (
            ("/admin/users/private-user/reset-password", "/admin/users/{user_id}/reset-password"),
            ("/admin/users/private-user/runtime/pause", "/admin/users/{user_id}/runtime/pause"),
            ("/admin/models/private-model/test", "/admin/models/{model_id}/test"),
            ("/admin/plugins/private-plugin/9.4.1", "/admin/plugins/{plugin_id}/{version}"),
            ("/sessions/private-session/messages", "/sessions/{session_id}/messages"),
            ("/skills/private-skill/rollback", "/skills/{skill_id}/rollback"),
            ("/tokens/private-token", "/tokens/{token_id}"),
            ("/unknown/private-value", "/unrecognized-route"),
        ):
            self.assertEqual(acceptance.route_name(acceptance.PREFIX + path), expected)
        self.assertEqual(acceptance.route_name(acceptance.PREFIX + "/admin/users"), "/admin/users")

    def test_cleanup_attempts_every_resource_after_transport_failures(self):
        calls = []

        class Session:
            def patch(self, path, json):
                calls.append(path)
                if "first" in path or "/models/" in path:
                    raise httpx.ConnectError("synthetic disconnected transport")
                return httpx.Response(200)

        outcome = acceptance.cleanup_created(Session(), ["first-account", "second-account"], "private-model", "private-plugin", True)
        self.assertEqual(len(calls), 4)
        self.assertEqual(outcome, {"accounts_deactivated": False, "model_disabled": False, "plugin_disabled": True})
        self.assertNotIn("private", json.dumps(outcome))

    def failure_report(self, *, must_change, reserved):
        calls = []

        class Session:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def response(self, method, path, value):
                calls.append((method, path))
                return httpx.Response(200, json=value, request=httpx.Request(method, "http://fixture.invalid" + acceptance.PREFIX + path))

            def post(self, path, json):
                if path != "/auth/login":
                    raise AssertionError("must not mutate an existing password or create test accounts")
                return self.response("POST", path, {"csrf_token": "synthetic-csrf", "user": {"id": "private-existing-admin", "role": "super_admin", "must_change_password": must_change}})

            def get(self, path):
                if path == "/me":
                    return self.response("GET", path, {"user": {"id": "private-existing-admin", "role": "super_admin"}})
                if path == "/admin/users":
                    return self.response("GET", path, {"items": [], "capacity": {"maximum": 4, "reserved": reserved}})
                raise AssertionError("unexpected request")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".secrets").mkdir()
            (root / ".secrets/console-admin-current.password").write_text("synthetic-admin-password", encoding="utf-8")
            (root / "output").mkdir()
            target = root / "output/role-acceptance.json"
            target.write_text('{"status":"passed"}', encoding="utf-8")
            output = io.StringIO()
            with patch.object(acceptance, "ROOT", root), patch.object(sys, "argv", ["acceptance", "--execute"]), patch.object(acceptance.httpx, "Client", return_value=Session()), redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, "role_acceptance_check_failed"):
                    acceptance.main()
            report = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failed"], 1)
            self.assertNotIn("private-existing-admin", json.dumps(report))
            self.assertNotIn("synthetic-admin-password", output.getvalue())
            self.assertEqual((root / ".secrets/console-admin-current.password").read_text(), "synthetic-admin-password")
            return report, calls

    def test_existing_super_admin_must_change_password_is_not_mutated(self):
        report, calls = self.failure_report(must_change=True, reserved=0)
        self.assertIn("existing_super_admin_password_already_changed", report["error"])
        self.assertEqual(calls, [("POST", "/auth/login")])

    def test_capacity_is_checked_before_creating_any_synthetic_account(self):
        report, calls = self.failure_report(must_change=False, reserved=4)
        self.assertIn("runtime_capacity_available_before_test_creation", report["error"])
        self.assertEqual(calls, [("POST", "/auth/login"), ("GET", "/me"), ("GET", "/admin/users")])


if __name__ == "__main__":
    unittest.main()
