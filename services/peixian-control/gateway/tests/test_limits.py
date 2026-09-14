import asyncio
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from gateway.app import create_app
from gateway.settings import Settings
from gateway.parse_queue import ParseQueue
from gateway.storage import FileStore
from gateway.plugin_test import run_plugin_test


def test_health_revision_is_snapshot_of_started_configuration(tmp_path):
    for name in ("workspace", "files", "managed"):
        (tmp_path / name).mkdir()
    revision = {"uid": "account-a", "runtime_id": "runtime-a", "revision": 4}
    marker = tmp_path / "managed" / "revision.json"
    marker.write_text(json.dumps(revision), encoding="utf-8")
    settings = Settings(tmp_path / "workspace", tmp_path / "files", tmp_path / "managed", "test-token", "test-password",
                        require_linux=False)
    with TestClient(create_app(settings), headers={"X-Peixian-Key": settings.token}) as client:
        assert client.get("/health").json() == {"ok": True, **revision}
        marker.write_text(json.dumps({**revision, "revision": 5}), encoding="utf-8")
        assert client.get("/health").json()["revision"] == 4


def test_restart_recovers_parse_queue_and_keeps_single_process(tmp_path):
    workspace, files = tmp_path / "workspace", tmp_path / "files"
    workspace.mkdir()
    store = FileStore(files, workspace, require_linux=False)
    ids = []
    for name in ("one.txt", "two.txt"):
        identity, handle, _ = store.begin_upload(name)
        with handle:
            handle.write(name.encode())
        store.finish_upload(identity, len(name))
        ids.append(identity)
    store.update(ids[0], status="parsing")

    async def run():
        queue = ParseQueue(store)
        await queue.start()
        # One task consumes the queue serially; completed files come from real
        # isolated parser processes, including recovery of interrupted parsing.
        await asyncio.wait_for(queue.queue.join(), timeout=15)
        assert all(store.metadata(identity)["status"] == "ready" for identity in ids)
        assert queue.process is None
        await queue.stop()

    try:
        asyncio.run(run())
    finally:
        store.close()


@pytest.mark.skipif(not os.environ.get("BUN_EXECUTABLE"), reason="Requires an explicitly supplied installed Bun test runtime")
def test_plugin_wall_timeout(tmp_path):
    directory = tmp_path / "plugins" / "sample" / "1.0.0"
    directory.mkdir(parents=True)
    entry = directory / "entry.mjs"
    entry.write_text("export async function test() { await new Promise(() => {}); }", encoding="utf-8")
    # Keep the event loop alive so Bun cannot finish a pending promise early.
    entry.write_text("export async function test() { setInterval(()=>{},1000); await new Promise(() => {}); }", encoding="utf-8")
    (tmp_path / "plugin-tests.json").write_text(json.dumps({
        "sample": {"entry": str(entry), "options": {}}}), encoding="utf-8")
    result = asyncio.run(run_plugin_test(tmp_path, "sample"))
    assert result == {"supported": True, "ok": False, "message": "Connection test timed out"}
