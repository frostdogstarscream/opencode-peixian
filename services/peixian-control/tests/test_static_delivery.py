"""Real static files and HTTP responses; no Docker, runtime or model calls."""
import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from control.app import create_app
from shared.control_delivery import DeliveryError, generate, load, public_build, verify


@pytest.fixture
def frontend(tmp_path):
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<html><script type="module" src="/assets/index-ABCDEFGH.js"></script><link rel="stylesheet" href="/assets/index-ABCDEFGH.css"></html>', encoding="utf-8")
    (root / "assets/index-ABCDEFGH.js").write_text("console.log('synthetic')", encoding="utf-8")
    (root / "assets/index-ABCDEFGH.css").write_text("body{color:black}", encoding="utf-8")
    return root


def manifest(root):
    return generate(root, mode="release", source_commit="a" * 40, input_digest="b" * 64,
                    base_images={"frontend": "synthetic@sha256:" + "c" * 64, "runtime": "synthetic@sha256:" + "d" * 64})


def test_inventory_is_stable_and_public_fields_are_restricted(frontend):
    value = manifest(frontend)
    assert manifest(frontend) == value
    assert verify(frontend, value) == value
    assert set(public_build(value)) == {"mode", "source_commit", "build_id", "frontend_digest"}
    assert str(frontend) not in json.dumps(value)
    assert generate(frontend, mode="dev", source_commit="a" * 40)["source_commit"] is None


@pytest.mark.parametrize("change", ["index", "asset", "modified", "extra", "identity"])
def test_incomplete_or_modified_static_resources_are_rejected(frontend, change):
    value = manifest(frontend)
    if change == "index":
        (frontend / "index.html").unlink()
    elif change == "asset":
        (frontend / "assets/index-ABCDEFGH.js").unlink()
    elif change == "modified":
        (frontend / "assets/index-ABCDEFGH.js").write_text("altered")
    elif change == "extra":
        (frontend / "unexpected.txt").write_text("unexpected")
    else:
        value["build_id"] = "release-forged"
    with pytest.raises(DeliveryError):
        verify(frontend, value)


@pytest.mark.parametrize("reference", ["https://external.invalid/x.js", "//external.invalid/x.js", "/assets/missing.js", "/assets/%2e%2e/private.js"])
def test_missing_remote_or_escaping_entry_references_are_rejected(frontend, reference):
    (frontend / "index.html").write_text('<script src="' + reference + '"></script>')
    with pytest.raises(DeliveryError):
        manifest(frontend)


def test_required_static_failure_occurs_before_store_initialization(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSOLE_REQUIRE_STATIC", "1")
    monkeypatch.setenv("CONSOLE_BUILD_MANIFEST", str(tmp_path / "missing.json"))
    monkeypatch.setenv("CONSOLE_STATIC", str(tmp_path / "missing-static"))
    def forbidden():
        pytest.fail("The store must not open for an incomplete production image")
    monkeypatch.setattr("control.app.configured_store", forbidden)
    app = create_app()
    async def run():
        with pytest.raises(DeliveryError, match="manifest_missing"):
            async with app.router.lifespan_context(app):
                pytest.fail("Invalid image entered lifespan")
    asyncio.run(run())
    assert not hasattr(app.state, "db_work")


def test_backend_only_development_is_allowed_and_invalid_manifest_is_not(frontend, tmp_path):
    missing = tmp_path / "missing.json"
    assert load(tmp_path / "missing-static", missing, required=False) is None
    missing.write_text("not json")
    with pytest.raises(DeliveryError, match="manifest_unreadable"):
        load(frontend, missing, required=False)


def test_application_serves_frontend_and_health_from_same_validated_build(frontend, tmp_path, monkeypatch):
    value = manifest(frontend)
    path = tmp_path / "build-manifest.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("CONSOLE_REQUIRE_STATIC", "1")
    monkeypatch.setenv("CONSOLE_STATIC", str(frontend))
    monkeypatch.setenv("CONSOLE_BUILD_MANIFEST", str(path))
    monkeypatch.setattr("control.runtime_security.SafetyCoordinator.start", lambda self: None)
    store = SimpleNamespace(maintenance_status=lambda: {}, schema_version=lambda: 5)
    app = create_app(store)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        assert client.get("/settings").text == page.text
        for name in ("index-ABCDEFGH.js", "index-ABCDEFGH.css"):
            asset = client.get("/assets/" + name)
            assert asset.status_code == 200
            assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert client.get("/assets/" + name, headers={"If-None-Match": asset.headers["etag"]}).status_code == 304
        assert client.get("/api/console/v1/unknown").status_code == 401
        # The existing /{kind} API checks identity first. An authenticated unknown
        # kind must still be a 404, never an SPA response.
        from control.app import normal
        app.dependency_overrides[normal] = lambda: {"uid": "synthetic"}
        for path in ("/assets/missing.js", "/missing.js", "/api", "/internal", "/api/console/v1/unknown", "/internal/unknown"):
            response = client.get(path)
            assert response.status_code == 404
            assert "<html>" not in response.text
        health = client.get("/health").json()
        assert health["schema_version"] == 5 and health["build"] == public_build(value)


def test_release_requires_fixed_source_and_context_identity(frontend):
    for source, inputs in ((None, None), ("HEAD", "b" * 64), ("a" * 40, "unverified")):
        with pytest.raises(DeliveryError, match="release_identity_required"):
            generate(frontend, mode="release", source_commit=source, input_digest=inputs)
