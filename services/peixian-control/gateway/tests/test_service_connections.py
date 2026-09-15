import json

from fastapi.testclient import TestClient
import httpx
import pytest

from gateway.model_relay import create_app
from gateway.service_connections import load_connections


def binding(**changes):
    return {"id": "binding-one", "plugin_id": "fixture", "alias": "records", "allowed_user": "account-a", "token": "a" * 64,
            "headers": {"Authorization": "Bearer synthetic-service-secret"}, "base_url": "http://internal:8000/api", "allowed_methods": ["GET", "POST"],
            "allowed_paths": ["/health", "/records/*"], "timeout_seconds": 2, "max_response_bytes": 1024, **changes}


def test_loaded_config_is_account_bound_and_invalid_is_fail_closed(tmp_path):
    file = tmp_path / "connections.json"
    assert load_connections(file, "account-a") == {}
    file.write_text(json.dumps({"account_id": "account-a", "connections": [binding()]}))
    assert len(load_connections(file, "account-a")) == 1
    for account in ("account-b", ""):
        with pytest.raises(ValueError):
            load_connections(file, account)
    for changed in (binding(allowed_user="account-b"), binding(token="short"), binding(base_url="http://user:password@internal/api"),
                    binding(allowed_paths=["/../admin"]), binding(headers={"Host": "other"})):
        file.write_text(json.dumps({"account_id": "account-a", "connections": [changed]}))
        with pytest.raises(ValueError):
            load_connections(file, "account-a")
    file.write_text(json.dumps({"account_id": "account-a", "connections": [binding(), binding()]}))
    with pytest.raises(ValueError):
        load_connections(file, "account-a")


def test_relay_fixed_destination_credential_and_response_envelope():
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={"records": ["synthetic"]})
    with TestClient(create_app(models={}, connections={"binding-one": binding()}, transport=httpx.MockTransport(upstream))) as client:
        path = "/platform/connections/binding-one/request"
        for headers in ({}, {"Authorization": "Bearer " + "b" * 64}):
            assert client.post(path, headers=headers, json={"path": "/health"}).status_code == 403
        assert not seen
        headers = {"Authorization": "Bearer " + "a" * 64, "X-Caller-Secret": "ignored"}
        response = client.post(path, headers=headers, json={"method": "GET", "path": "/records/item", "query": {"q": "a&b", "page": 2}})
        assert response.json() == {"status": 200, "data": {"records": ["synthetic"]}}
        assert len(seen) == 1
        assert seen[0].url.host == "internal" and seen[0].url.path == "/api/records/item"
        assert seen[0].url.params["q"] == "a&b"
        assert seen[0].headers["authorization"] == "Bearer synthetic-service-secret"
        assert "x-caller-secret" not in seen[0].headers
        assert client.post("/platform/connections/foreign/request", headers=headers, json={"path": "/health"}).status_code == 403


@pytest.mark.parametrize("value", [
    {"path": "http://evil/health"}, {"path": "//evil/health"}, {"path": "/records/../secret"},
    {"path": "/records/%2e%2e/secret"}, {"path": "/records/%252e%252e/secret"},
    {"path": "/records\\secret"}, {"path": "/health?target=other"}, {"path": "/records//admin"},
    {"path": "/other"}, {"path": "/health", "url": "http://other"}, {"path": "/health", "headers": {"Authorization": "caller"}},
    {"path": "/health", "method": "DELETE"}, {"path": "/health", "query": {"nested": {"url": "other"}}},
])
def test_disallowed_targets_never_issue_upstream_request(value):
    def forbidden(request):
        raise AssertionError("Disallowed service request reached upstream")
    with TestClient(create_app(models={}, connections={"binding-one": binding()}, transport=httpx.MockTransport(forbidden))) as client:
        response = client.post("/platform/connections/binding-one/request", headers={"Authorization": "Bearer " + "a"*64}, json=value)
        assert response.status_code in (400, 403)


@pytest.mark.parametrize("kind", ["redirect", "error", "large", "non_json", "invalid_json", "credential_echo", "timeout"])
def test_upstream_failures_are_bounded_and_sanitized(kind):
    seen = []
    def upstream(request):
        seen.append(request)
        if kind == "redirect":
            return httpx.Response(307, headers={"location": "http://other/synthetic-service-secret"})
        if kind == "error":
            return httpx.Response(500, text="synthetic-service-secret")
        if kind == "large":
            return httpx.Response(200, json={"text": "x" * 2048})
        if kind == "non_json":
            return httpx.Response(200, text="synthetic-service-secret")
        if kind == "invalid_json":
            return httpx.Response(200, content=b"{broken", headers={"content-type": "application/json"})
        if kind == "credential_echo":
            return httpx.Response(200, json={"echo": "synthetic-service-secret"})
        raise httpx.ReadTimeout("private diagnostic")
    with TestClient(create_app(models={}, connections={"binding-one": binding()}, transport=httpx.MockTransport(upstream))) as client:
        response = client.post("/platform/connections/binding-one/request", headers={"Authorization": "Bearer " + "a"*64}, json={"path": "/health"})
        assert response.status_code in (413, 502)
        assert len(seen) == 1
        assert all(value not in response.text for value in ("synthetic-service-secret", "private diagnostic", "http://other"))


def test_request_size_limit_and_model_only_compatibility():
    def forbidden(request):
        raise AssertionError("Large request reached upstream")
    with TestClient(create_app(models={}, connections={"binding-one": binding()}, transport=httpx.MockTransport(forbidden))) as client:
        response = client.post("/platform/connections/binding-one/request", headers={"Authorization": "Bearer " + "a"*64},
                               json={"method": "POST", "path": "/health", "json": {"text": "x" * 1048576}})
        assert response.status_code == 413
    with TestClient(create_app(models={})) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/models").json()["data"] == []
