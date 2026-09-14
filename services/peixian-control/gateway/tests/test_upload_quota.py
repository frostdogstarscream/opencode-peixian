import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import uuid

from fastapi.testclient import TestClient
import pytest

from gateway.app import create_app
from gateway.settings import Settings
from gateway.storage import FileStore, QuotaExceeded


def make_store(tmp_path, quota=10):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return FileStore(tmp_path / "files", workspace, require_linux=False, quota_bytes=quota)


def complete(store, name, content):
    identity, handle, _ = store.begin_upload(name, expected_size=len(content))
    with handle:
        store.write_upload(identity, handle, content)
        handle.flush()
        os.fsync(handle.fileno())
    store.finish_upload(identity, len(content))
    return identity


def test_concurrent_full_size_reservations_cannot_overcommit(tmp_path):
    store = make_store(tmp_path, quota=10)
    barrier = threading.Barrier(3)

    def attempt():
        barrier.wait()
        try:
            return store.begin_upload("synthetic.bin", expected_size=6)
        except QuotaExceeded:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(attempt) for _ in range(2)]
            barrier.wait()
            results = [task.result() for task in tasks]
        admitted = [value for value in results if value is not None]
        assert len(admitted) == 1
        assert store.quota() == {"limit": 10, "used": 0, "reserved": 6}
        identity, handle, _ = admitted[0]
        with handle:
            store.write_upload(identity, handle, b"123456")
            handle.flush()
        store.finish_upload(identity, 6)
        assert store.quota() == {"limit": 10, "used": 6, "reserved": 0}
        assert len(store.list()) == 1
        with pytest.raises(QuotaExceeded):
            store.begin_upload("too-large.bin", expected_size=5)
        pending, handle, _ = store.begin_upload("aborted.bin", expected_size=4)
        handle.close()
        store.delete(pending, incomplete=True)
        assert store.quota()["reserved"] == 0 and store.quota()["used"] == 6
        store.delete(identity)
        assert store.quota()["used"] == 0
    finally:
        store.close()


def test_restart_counts_real_source_size_not_metadata_and_keeps_existing_data(tmp_path):
    store = make_store(tmp_path, quota=10)
    identity = complete(store, "saved.bin", b"123456")
    store.update(identity, size=0)  # Synthetic stale metadata must not bypass quota.
    store.close()
    store = make_store(tmp_path, quota=5)
    try:
        assert store.quota() == {"limit": 5, "used": 6, "reserved": 0}
        with pytest.raises(QuotaExceeded):
            store.begin_upload("new.bin", expected_size=1)
        with store.files.open(store.metadata(identity)["source"]) as handle:
            assert handle.read() == b"123456"
        store.delete(identity)
        assert store.quota()["used"] == 0
        complete(store, "fits.bin", b"12345")
    finally:
        store.close()


def test_restart_cleans_only_explicitly_interrupted_upload(tmp_path):
    store = make_store(tmp_path)
    saved = complete(store, "saved.bin", b"1234")
    interrupted, handle, _ = store.begin_upload("partial.bin", expected_size=6)
    with handle:
        store.write_upload(interrupted, handle, b"123")
    store.close()
    store = make_store(tmp_path)
    try:
        assert [item["id"] for item in store.list()] == [saved]
        assert store.quota() == {"limit": 10, "used": 4, "reserved": 0}
        assert not (store.files.path / interrupted).exists()
    finally:
        store.close()


def test_orphan_sources_are_conservatively_counted_without_deleting_unknown_data(tmp_path):
    store = make_store(tmp_path)
    identity = uuid.uuid4().hex
    store.files.mkdir(identity)
    with store.files.open(identity + "/source.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL) as handle:
        handle.write(b"123456")
    store.close()
    store = make_store(tmp_path)
    try:
        assert store.quota()["used"] == 6
        with pytest.raises(QuotaExceeded):
            store.begin_upload("new.bin", expected_size=5)
        assert (store.files.path / identity / "source.bin").is_file()
    finally:
        store.close()


def test_failed_source_delete_does_not_release_capacity(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    identity = complete(store, "saved.bin", b"123456")
    source = store.metadata(identity)["source"]
    original = store.files.unlink
    def fail(relative):
        if relative == source:
            raise PermissionError("synthetic deletion failure")
        return original(relative)
    monkeypatch.setattr(store.files, "unlink", fail)
    try:
        with pytest.raises(PermissionError):
            store.delete(identity)
        assert store.quota()["used"] == 6
        with pytest.raises(QuotaExceeded):
            store.begin_upload("new.bin", expected_size=5)
        monkeypatch.setattr(store.files, "unlink", original)
        store.delete(identity)
        assert store.quota()["used"] == 0
    finally:
        store.close()


def test_chunked_multipart_without_content_length_obeys_total_quota_and_delete_releases(tmp_path):
    for name in ("workspace", "files", "managed"):
        (tmp_path / name).mkdir()
    settings = Settings(tmp_path / "workspace", tmp_path / "files", tmp_path / "managed",
                        "synthetic-token", "synthetic-password", require_linux=False, upload_quota=8)
    app = create_app(settings)
    with TestClient(app, headers={"X-Peixian-Key": settings.token}) as client:
        boundary = "synthetic-boundary"
        pieces = [
            (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="source.bin"\r\n'
             'Content-Type: application/octet-stream\r\n\r\n').encode(),
            b"1234", b"5678", f"\r\n--{boundary}--\r\n".encode(),
        ]
        response = client.post("/files", content=iter(pieces),
                               headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        assert response.status_code == 202
        identity = response.json()["id"]
        assert app.state.store.quota() == {"limit": 8, "used": 8, "reserved": 0}
        response = client.post("/files", files={"file": ("extra.bin", b"x")})
        assert response.status_code == 413
        assert len(client.get("/files").json()["items"]) == 1
        assert client.delete("/files/" + identity).status_code == 200
        assert client.post("/files", files={"file": ("now-fits.bin", b"12345678")}).status_code == 202


def test_upload_write_failure_removes_source_and_releases_reservation(tmp_path, monkeypatch):
    for name in ("workspace", "files", "managed"):
        (tmp_path / name).mkdir()
    settings = Settings(tmp_path / "workspace", tmp_path / "files", tmp_path / "managed",
                        "synthetic-token", "synthetic-password", require_linux=False, upload_quota=8)
    app = create_app(settings)
    with TestClient(app, headers={"X-Peixian-Key": settings.token}) as client:
        original = app.state.store.write_upload
        def fail(*args):
            raise OSError("synthetic write failure")
        monkeypatch.setattr(app.state.store, "write_upload", fail)
        assert client.post("/files", files={"file": ("fail.bin", b"12345678")}).status_code == 409
        assert app.state.store.quota() == {"limit": 8, "used": 0, "reserved": 0}
        assert list(settings.files_root.iterdir()) == []
        monkeypatch.setattr(app.state.store, "write_upload", original)
        assert client.post("/files", files={"file": ("fits.bin", b"12345678")}).status_code == 202
