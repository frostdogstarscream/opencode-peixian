import asyncio
import json

import httpx
import pytest

from examples.console_client import ConsoleClient, ConsoleError, sse_events


def test_console_example_cookie_csrf_files_and_public_account_binding(tmp_path):
    seen = []
    user = {"id": "account-id", "role": "user", "must_change_password": False}
    def handle(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"user": user, "csrf_token": "synthetic-csrf"},
                                  headers={"set-cookie": "px_session=synthetic-cookie; Path=/; HttpOnly"})
        if path.endswith("/me/password"):
            assert request.headers["x-csrf-token"] == "synthetic-csrf"
            assert request.headers["cookie"] == "px_session=synthetic-cookie"
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/me"):
            return httpx.Response(200, json={"user": user, "csrf_token": "synthetic-csrf"})
        if path.endswith("/files") and request.method == "POST":
            assert b"synthetic bytes" in request.content
            return httpx.Response(202, json={"id": "file-id", "status": "queued"})
        if path.endswith("/files/file-id/text"):
            return httpx.Response(200, json={"text": "synthetic", "chunks": [], "status": "ready",
                                           "truncated": False, "name": "input.txt"})
        if path.endswith("/sessions"):
            assert json.loads(request.content) == {"title": "Python analysis"}
            return httpx.Response(200, json={"id": "session-id"})
        if path.endswith("/sessions/session-id/messages"):
            assert json.loads(request.content)["file_ids"] == ["file-id"]
            return httpx.Response(202, json={"accepted": True, "run_id": "receipt-id"})
        if path.endswith("/sessions/session-id/abort"):
            return httpx.Response(200, json={"ok": True})
        raise AssertionError("Unexpected path")

    async def run():
        source = tmp_path / "input.txt"
        source.write_text("synthetic bytes", encoding="utf-8")
        async with ConsoleClient("http://console.test", transport=httpx.MockTransport(handle)) as client:
            assert await client.login("synthetic-user", "synthetic-password") == user
            await client.change_password("synthetic-password", "synthetic-new-password")
            assert await client.me() == user
            file = await client.upload(source)
            assert (await client.wait_for_file(file["id"]))["status"] == "ready"
            session = await client.create_session()
            assert (await client.send_message(session["id"], "synthetic", file_ids=[file["id"]]))["accepted"]
            await client.abort(session["id"])
    asyncio.run(run())
    assert all(request.url.host == "console.test" for request in seen)
    assert all("x-peixian-key" not in request.headers and "x-worker-key" not in request.headers for request in seen)
    assert all("tenant" not in request.url.params and "directory" not in request.url.params for request in seen)


def test_sse_decoder_handles_comments_and_multiline_data():
    async def lines():
        for line in (": heartbeat", "", "event: change", "data: first", "data: second", "", "data: unfinished"):
            yield line

    async def run():
        return [event async for event in sse_events(lines())]
    assert asyncio.run(run()) == [{"event": "change", "data": "first\nsecond"}]


def test_example_requires_completion_and_aborts_on_timeout():
    class Simulated(ConsoleClient):
        def __init__(self, complete=True):
            super().__init__("http://console.test")
            self.accepted, self.complete, self.aborts = False, complete, 0

        async def events(self):
            yield {"event": "change", "data": '{"type":"connected"}'}
            await asyncio.Event().wait()

        async def messages(self, session_id):
            if self.accepted and self.complete:
                return [{"info": {"id": "new-answer", "role": "assistant", "time": {"completed": 123}},
                         "parts": [{"type": "text", "text": "synthetic answer"}]}]
            return []

        async def send_message(self, *args, **kwargs):
            self.accepted = True
            return {"accepted": True, "run_id": "not-a-message-id"}

        async def sessions(self):
            return [{"id": "session", "status": "idle" if self.complete else "busy"}]

        async def abort(self, session_id):
            self.aborts += 1
            return {"ok": True}

    async def run():
        async with Simulated() as client:
            result = await client.run_message("session", "question")
            assert result[0]["info"]["id"] == "new-answer" and client.aborts == 0
        async with Simulated(complete=False) as client:
            with pytest.raises(TimeoutError):
                await client.run_message("session", "question", timeout=0.01)
            assert client.aborts == 1
    asyncio.run(run())


@pytest.mark.parametrize(("status", "truncated"), [("partial", True), ("partial", False), ("ready", True)])
def test_example_rejects_incomplete_file_before_reference(status, truncated):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path.endswith("/files/file-id/text")
        return httpx.Response(200, json={"status": status, "truncated": truncated,
                                       "text": "synthetic excerpt", "chunks": [], "name": "fixture.txt"})
    async def run():
        async with ConsoleClient("http://console.test", transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(ConsoleError, match="extraction is incomplete"):
                await client.wait_for_file("file-id")
    asyncio.run(run())
    assert len(requests) == 1
