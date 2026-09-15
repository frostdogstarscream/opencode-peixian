"""Offline contract checks; no account, file upload or model is created remotely."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

source = Path(__file__).resolve().parents[1] / "examples/platform-python.py"
spec = importlib.util.spec_from_file_location("platform_python_example", source)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class PlatformExampleTests(unittest.TestCase):
    def test_remote_http_credentials_and_non_origin_urls_are_rejected(self):
        self.assertEqual(example.origin("https://agent.example.internal/"), "https://agent.example.internal")
        self.assertEqual(example.origin("http://127.0.0.1:14090"), "http://127.0.0.1:14090")
        for url in ("http://intranet:14090", "https://user:password@host", "https://host/api", "https://host?token=secret", "file:///workspace"):
            with self.assertRaises(example.PlatformError):
                example.origin(url)

    def test_no_default_action_can_send_a_model_message(self):
        with patch.object(example, "Platform", side_effect=AssertionError("Unexpected network initialization")):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                example.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_health_requires_no_credentials_and_only_reads_public_resources(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True})
        client = example.Platform("https://agent.example.internal", transport=httpx.MockTransport(handler))
        with patch.object(example, "Platform", return_value=client), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(example.main(["--url", "https://agent.example.internal", "health"]), 0)
        self.assertEqual([(r.method, r.url.path) for r in seen], [("GET", "/health"), ("GET", "/api/console/v1/platform")])
        self.assertTrue(all("authorization" not in r.headers for r in seen))

    def test_token_is_only_in_header_and_close_does_not_revoke_it(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"user": {"must_change_password": False}, "capabilities": []})
        client = example.Platform("https://agent.example.internal", transport=httpx.MockTransport(handler))
        try:
            client.authenticate(token="synthetic-personal-token")
        finally:
            client.close()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].headers["authorization"], "Bearer synthetic-personal-token")
        self.assertNotIn(b"synthetic-personal-token", seen[0].content)

    def test_cookie_login_uses_origin_and_csrf_then_logs_out_only_itself(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path.endswith("/auth/login"):
                return httpx.Response(200, json={"csrf_token": "synthetic-csrf"}, headers={"set-cookie": "px_session=synthetic-cookie; Path=/; Secure; HttpOnly"})
            if request.url.path.endswith("/me"):
                return httpx.Response(200, json={"user": {"must_change_password": False}})
            return httpx.Response(200, json={"ok": True})
        client = example.Platform("https://agent.example.internal", transport=httpx.MockTransport(handler))
        client.authenticate(username="synthetic-user", password="synthetic-password")
        client.close()
        self.assertEqual(seen[-1].url.path, "/api/console/v1/auth/logout")
        self.assertEqual(seen[-1].headers["origin"], "https://agent.example.internal")
        self.assertEqual(seen[-1].headers["x-csrf-token"], "synthetic-csrf")
        self.assertNotIn("authorization", seen[-1].headers)

    def test_sse_requeries_history_and_deduplicates_without_resending_prompt(self):
        class Events(httpx.SyncByteStream):
            def __iter__(self):
                yield b'event: change\ndata: {"type":"connected"}\n\n'
                yield b'event: change\ndata: {"type":"updated"}\n\n'
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path.endswith("/events"):
                return httpx.Response(200, stream=Events(), headers={"content-type": "text/event-stream"})
            return httpx.Response(200, json={"items": [{"id": "synthetic-message"}]})
        client = example.Platform("https://agent.example.internal", transport=httpx.MockTransport(handler))
        try:
            with patch.object(example.time, "sleep"):
                values = list(client.events(seconds=60, session_id="synthetic-session"))
        finally:
            client.close()
        self.assertEqual(sum(v["event"] == "history" for v in values), 1)
        self.assertEqual(sum(v["event"] == "change" for v in values), 6)
        self.assertTrue(all(request.method == "GET" for request in seen))

    def test_error_message_does_not_echo_server_body_or_credentials(self):
        response = httpx.Response(502, text="Bearer synthetic-secret https://internal.invalid/private")
        with self.assertRaises(example.PlatformError) as raised:
            example.Platform.checked(response)
        self.assertNotIn("synthetic-secret", str(raised.exception))
        self.assertNotIn("internal.invalid", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
