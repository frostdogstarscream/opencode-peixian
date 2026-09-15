"""Framework namespace tests stay inside temporary stores; no runtime requests."""
from fastapi import Request
from fastapi.testclient import TestClient
import pytest

from control.app import create_app, runtime
from control.openapi import build_openapi
from test_cookie_name import synthetic_store, PASSWORD


@pytest.mark.parametrize("namespace", [None, "project-one", "a123456789012345"])
def test_gateway_dns_uses_captured_namespace_or_legacy_default(tmp_path, monkeypatch, namespace):
    monkeypatch.delenv("RUNTIME_NAMESPACE", raising=False)
    if namespace is not None:
        monkeypatch.setenv("RUNTIME_NAMESPACE", namespace)
    store = synthetic_store(tmp_path/"routing")
    user, _ = store.create_user("synthetic-runtime-user", PASSWORD)
    with store.tx() as db:
        db.execute("UPDATE runtimes SET status='ready' WHERE uid=?", (user["id"],))
    app = create_app(store)
    monkeypatch.setenv("RUNTIME_NAMESPACE", "changed-later")
    with TestClient(app):
        request = Request({"type": "http", "app": app})
        address, headers = runtime(request, {"uid": user["id"]})
        assert address == f"http://{namespace or 'px'}-{user['runtime']['id']}-gateway:8080"
        assert app.state.runtime_namespace == namespace
        assert set(headers) == {"X-Peixian-Key"}


@pytest.mark.parametrize("namespace", ["", "Upper", "1project", "has_space", "has.dot", "two words",
                                       "a/b", "a\r\nb", "非英文", "a"*17, "a:8080"])
def test_invalid_namespace_refuses_application_creation(namespace, monkeypatch):
    monkeypatch.setenv("RUNTIME_NAMESPACE", namespace)
    with pytest.raises(ValueError, match="RUNTIME_NAMESPACE"):
        create_app()


@pytest.mark.parametrize("method,path", [
    ("POST", "/internal/worker/legacy-import"),
    ("GET", "/internal/worker/legacy-status/synthetic-uid"),
    ("POST", "/internal/worker/legacy-rollback"),
    ("POST", "/internal/worker/legacy-retry"),
])
def test_framework_namespace_blocks_all_legacy_routes_even_with_worker_key(tmp_path, monkeypatch, method, path):
    monkeypatch.setenv("RUNTIME_NAMESPACE", "demo-project")
    store = synthetic_store(tmp_path/"legacy-denied")
    app = create_app(store)
    with TestClient(app) as client:
        arguments = {"json": {}} if method == "POST" else {}
        response = client.request(method, path, headers={"X-Worker-Key": store.worker_key}, **arguments)
        assert response.status_code == 404
        assert response.json()["message"] == "框架项目不提供旧环境迁移接口"
        assert client.request(method, path, **arguments).status_code == 403
        assert store.rows("SELECT * FROM runtimes") == []
        assert store.rows("SELECT * FROM audit") == []
        # The independent worker contract still works for ordinary project jobs.
        assert client.post("/internal/worker/claim", headers={"X-Worker-Key": store.worker_key}).json() == {"job": None}
    document = build_openapi(app)
    legacy = [operation for route, item in document["paths"].items() if route.startswith("/internal/worker/legacy-")
              for operation in item.values()]
    assert len(legacy) == 4
    assert all(operation["x-legacy-disabled"] is True for operation in legacy)


def test_default_namespace_keeps_legacy_contract_enabled(monkeypatch):
    monkeypatch.delenv("RUNTIME_NAMESPACE", raising=False)
    app = create_app()
    assert app.state.runtime_namespace is None
    document = build_openapi(app)
    for path, item in document["paths"].items():
        if path.startswith("/internal/worker/legacy-"):
            assert all(operation["x-legacy-disabled"] is False for operation in item.values())
