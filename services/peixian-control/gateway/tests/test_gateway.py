import base64
import json
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from gateway.app import create_app
from gateway.settings import MAX_UPLOAD, Settings
from gateway.safe_fs import SafeRoot, UnsafePath


@pytest.fixture
def config(tmp_path):
    for name in ("workspace", "files", "managed"):
        (tmp_path / name).mkdir()
    return Settings(tmp_path / "workspace", tmp_path / "files", tmp_path / "managed",
                    "synthetic-private-token", "synthetic-password", require_linux=False)


def wait_file(client, identity):
    for _ in range(100):
        result = client.get("/files/" + identity).json()
        if result["status"] not in ("queued", "parsing"):
            return result
        time.sleep(0.03)
    raise AssertionError("Parser did not finish")


def test_auth_and_file_lifecycle(config):
    with TestClient(create_app(config)) as client:
        assert client.get("/health").status_code == 401
        client.headers["X-Peixian-Key"] = config.token
        assert client.get("/health").json() == {"ok": True}
        response = client.post("/files", files={"file": ("case.txt", "synthetic case\nsecond line".encode())})
        assert response.status_code == 202
        item = response.json()
        identity = item["id"]
        assert "source" not in item and len(identity) == 32
        assert (config.files_root / identity / "source.txt").read_bytes() == b"synthetic case\nsecond line"
        assert list(config.workspace.iterdir()) == []
        assert wait_file(client, identity)["status"] == "ready"
        text = client.get(f"/files/{identity}/text").json()
        assert set(text) == {"text", "chunks", "truncated", "status", "name"}
        assert text["chunks"][0]["source"] == {"type": "text", "line_start": 1, "line_end": 2}
        assert client.get("/files").json()["items"][0]["id"] == identity
        assert client.get(f"/files/{identity}/download").content == b"synthetic case\nsecond line"
        assert client.patch(f"/files/{identity}", json={"name": "renamed.txt"}).json()["name"] == "renamed.txt"
        assert client.patch(f"/files/{identity}", json={"name": "../bad"}).status_code == 400
        assert client.post(f"/files/{identity}/parse").status_code == 202
        wait_file(client, identity)
        assert client.delete(f"/files/{identity}").status_code == 200
        assert client.get(f"/files/{identity}").status_code == 404
        assert client.get("/files").json() == {"items": []}


def test_unsupported_and_upload_bound(config):
    with TestClient(create_app(config), headers={"X-Peixian-Key": config.token}) as client:
        response = client.post("/files", files={"file": ("opaque.bin", b"data")})
        assert response.json()["status"] == "unsupported"
        identity = response.json()["id"]
        assert client.post(f"/files/{identity}/parse").status_code == 415
        assert client.get(f"/files/{identity}/download").content == b"data"
        response = client.post("/files", files={"file": ("too-big.txt", b"a" * (MAX_UPLOAD + 1))})
        assert response.status_code == 413
        assert len(client.get("/files").json()["items"]) == 1
        assert client.post("/files", files={"file": ("a.txt", b"a")}, headers={"Content-Length": str(MAX_UPLOAD * 2)}).status_code == 413
        assert client.get("/files/" + "f" * 32).status_code == 404


def test_results_hidden_and_paths(config, tmp_path):
    (config.workspace / "result.csv").write_text("one,two", encoding="utf-8")
    (config.workspace / ".private").write_text("hidden", encoding="utf-8")
    (config.workspace / "sub").mkdir()
    (config.workspace / "sub" / "result.txt").write_text("two", encoding="utf-8")
    with TestClient(create_app(config), headers={"X-Peixian-Key": config.token}) as client:
        items = client.get("/results").json()["items"]
        assert {item["relative_path"] for item in items} == {"result.csv", "sub/result.txt"}
        assert all(not Path(item["relative_path"]).is_absolute() for item in items)
        first = next(item for item in items if item["name"] == "result.csv")
        assert client.get("/results/" + first["id"] + "/download").content == b"one,two"
        assert client.get("/results/" + "a" * 64 + "/download").status_code == 404
    root = SafeRoot(config.workspace, require_linux=False)
    try:
        for value in ("../outside", "/absolute", "a//b", "a\\b", "a/../b", "C:x"):
            with pytest.raises(UnsafePath):
                root.open(value)
    finally:
        root.close()


def test_symlink_result_is_not_followed(config, tmp_path):
    external = tmp_path / "outside.txt"
    external.write_text("private", encoding="utf-8")
    try:
        (config.workspace / "link.txt").symlink_to(external)
        (config.workspace / "linked-dir").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Windows test host does not permit creating symlinks")
    with TestClient(create_app(config), headers={"X-Peixian-Key": config.token}) as client:
        assert client.get("/results").json()["items"] == []


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"data: one\n\n"
        yield b"data: two\n\n"


def test_native_allowlist_fixed_scope_and_sse(config):
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, stream=Chunks(), headers={"Content-Type": "text/event-stream"})
    app = create_app(config, transport=httpx.MockTransport(upstream))
    with TestClient(app, headers={"X-Peixian-Key": config.token}) as client:
        response = client.get("/global/event", headers={"Authorization": "Bearer caller", "x-opencode-directory": "/other"})
        assert response.content == b"data: one\n\ndata: two\n\n"
        assert seen[-1].url.host == "agent"
        assert seen[-1].url.params["directory"] == "/workspace"
        assert seen[-1].headers["x-opencode-directory"] == "/workspace"
        expected = base64.b64encode(b"opencode:synthetic-password").decode()
        assert seen[-1].headers["authorization"] == "Basic " + expected
        assert "x-peixian-key" not in seen[-1].headers
        assert client.get("/session?directory=/other").status_code == 400
        assert client.get("/session?workspaceID=foreign").status_code == 400
        for endpoint in ("/config", "/auth/provider", "/mcp", "/pty", "/session/a/shell", "/session/a/command", "/file/content"):
            assert client.post(endpoint, json={}).status_code == 404
        assert client.post("/session/a/message", json={"parts": [{"type": "file", "url": "file:///secret"}]}).status_code == 400
        assert client.post("/session", json={"directory": "/other"}).status_code == 400
        count = len(seen)
        assert client.post("/session/a/message", json={"parts": [{"type": "text", "text": "hello"}]}).status_code == 200
        assert len(seen) == count + 1


def test_native_redirect_and_error_redacted(config):
    for code in (302, 401):
        app = create_app(config, transport=httpx.MockTransport(lambda request: httpx.Response(
            code, text="synthetic-private-token upstream diagnostic", headers={"Location": "https://unrelated.invalid"})))
        with TestClient(app, headers={"X-Peixian-Key": config.token}) as client:
            response = client.get("/session")
            assert response.status_code == (502 if code == 302 else code)
            assert "synthetic" not in response.text
            assert "location" not in response.headers


def test_interrupted_native_stream_does_not_report_normal_completion(config):
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: partial\n\n"
            raise httpx.ReadError("synthetic private upstream diagnostic")
    app = create_app(config, transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Broken())))
    with TestClient(app, headers={"X-Peixian-Key": config.token}) as client:
        with pytest.raises(RuntimeError, match="^Upstream stream interrupted$"):
            client.get("/global/event")


def test_durable_receipt_route_is_private_fixed_and_sanitized(config):
    seen=[]
    rid='a'*32
    def upstream(request):
        seen.append(request)
        return httpx.Response(200,json={'boot_id':'demo-boot','capabilities':['durable_run_v1'],'receipt':{'id':rid,'session_id':'ses_demo','message_id':'msg_demo','state':'finished'},'internal':'not exposed'})
    with TestClient(create_app(config,transport=httpx.MockTransport(upstream))) as client:
        assert client.get('/internal/runtime/runs/'+rid).status_code==401
        client.headers['X-Peixian-Key']=config.token
        value=client.get('/internal/runtime/runs/'+rid)
        assert value.status_code==200,value.text
        assert value.json()['protocol']=='durable_run_v1'
        assert 'internal' not in value.json()
        assert seen[-1].url.params['run_id']==rid
        assert client.get('/internal/runtime/runs/bad').status_code==404
