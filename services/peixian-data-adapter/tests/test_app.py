import importlib
import logging
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


root = Path(__file__).parents[1]
sys.path.insert(0, str(root))
os.environ["PEIXIAN_ADAPTER_MODE"] = "mock"
app_module = importlib.import_module("app")
client = TestClient(app_module.app)


def request(path, body=None, headers=None):
    return client.post(path, json=body or {"certificate_no": "999999199001010001"}, headers=headers or {})


def test_health_and_all_mock_routes():
    assert client.get("/health").json() == {"ok": True, "mode": "mock", "schema_version": "1.0"}
    routes = [
        "/v1/person/profile/query", "/v1/person/houses/query", "/v1/person/companies/query",
        "/v1/person/family/query", "/v1/police/cases/query", "/v1/police/incidents/query",
        "/v1/police/disputes/query", "/v1/mobility/hotels/query", "/v1/mobility/railway/query",
        "/v1/mobility/netbar/query", "/v1/vehicle/motor/query", "/v1/vehicle/non-motor/query",
    ]
    for route in routes:
        response = request(route)
        assert response.status_code == 200, (route, response.text)
        result = response.json()
        assert result["schema_version"] == "1.0"
        assert result["returned_count"] == len(result["items"])
        assert result["trace_id"]
        assert result["warnings"]


def test_track_requires_valid_time_range():
    response = request("/v1/mobility/tracks/query", {
        "certificate_no": "999999199001010001",
        "begin_time": "2026-09-01T00:00:00+08:00",
        "end_time": "2026-09-17T23:59:59+08:00",
    })
    assert response.status_code == 200
    assert response.json()["returned_count"] == 2
    invalid = request("/v1/mobility/tracks/query", {
        "certificate_no": "999999199001010001",
        "begin_time": "2026-09-18T00:00:00+08:00",
        "end_time": "2026-09-17T23:59:59+08:00",
    })
    assert invalid.status_code == 422


def test_invalid_identifier_and_pagination_are_rejected():
    assert request("/v1/person/profile/query", {"certificate_no": "bad"}).status_code == 422
    assert request("/v1/person/profile/query", {"certificate_no": "999999199001010001", "page": {"number": 0, "size": 101}}).status_code == 422


def test_bearer_auth_when_configured(monkeypatch):
    monkeypatch.setenv("PEIXIAN_ADAPTER_TOKEN", "synthetic-adapter-token")
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer synthetic-adapter-token"}).status_code == 200
    monkeypatch.delenv("PEIXIAN_ADAPTER_TOKEN")


def test_secret_file_takes_precedence(monkeypatch, tmp_path):
    secret = tmp_path / "adapter-token"
    secret.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("PEIXIAN_ADAPTER_TOKEN", "environment-token")
    monkeypatch.setenv("PEIXIAN_ADAPTER_TOKEN_FILE", str(secret))
    assert client.get("/health", headers={"Authorization": "Bearer environment-token"}).status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer file-token"}).status_code == 200
    monkeypatch.delenv("PEIXIAN_ADAPTER_TOKEN_FILE")
    monkeypatch.delenv("PEIXIAN_ADAPTER_TOKEN")


def test_legacy_provider_never_falls_back_to_mock(monkeypatch):
    import asyncio
    from providers import LegacyProvider, ProviderError
    from models import PersonQuery

    monkeypatch.delenv("PEIXIAN_FAMILY_URL", raising=False)
    try:
        asyncio.run(LegacyProvider().query("family", PersonQuery(certificate_no="999999199001010001")))
    except ProviderError as error:
        assert error.code == "CONTRACT_NOT_READY"
    else:
        raise AssertionError("legacy mode must not fall back to mock data")


def test_audit_log_uses_irreversible_subject_digest(caplog):
    certificate_no = "999999199001010001"
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = request("/v1/person/profile/query", {"certificate_no": certificate_no})
    assert response.status_code == 200
    audit = next(record.message for record in caplog.records if "peixian_data_query" in record.message)
    assert response.json()["trace_id"] in audit
    assert certificate_no not in audit
    assert "subject_hash" in audit
