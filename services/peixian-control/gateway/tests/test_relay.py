import json

from fastapi.testclient import TestClient
import httpx
import pytest

from gateway.model_relay import Model, create_app, load_models
from gateway.http_utils import fixed_base


class Stream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"data: synthetic\n\n"
        yield b"data: [DONE]\n\n"


def test_relay_authorized_model_and_fixed_destination():
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})
    model = Model("platform-model", "upstream-model", "http://intranet-model:8000/v1", "synthetic-api-key", "account-a")
    with TestClient(create_app(models={model.id: model}, transport=httpx.MockTransport(upstream))) as client:
        listing = client.get("/v1/models").json()
        assert listing["data"][0]["id"] == model.id
        assert "synthetic-api-key" not in json.dumps(listing)
        assert client.post("/v1/chat/completions", json={"model": "foreign"}).status_code == 403
        assert not seen
        for extra in ({"url": "http://other"}, {"allowed_user": "account-b"}, {"api_key": "override"}):
            assert client.post("/v1/chat/completions", json={"model": model.id, **extra}).status_code == 400
        response = client.post("/v1/chat/completions", json={
            "model": model.id, "messages": [{"role": "user", "content": "synthetic"}], "stream": True,
        }, headers={"Authorization": "Bearer ignored-caller-key", "X-Peixian-Key": "ignored"})
        assert response.content == b"data: synthetic\n\ndata: [DONE]\n\n"
        assert str(seen[0].url) == "http://intranet-model:8000/v1/chat/completions"
        assert json.loads(seen[0].content)["model"] == "upstream-model"
        assert seen[0].headers["Authorization"] == "Bearer synthetic-api-key"
        assert "x-peixian-key" not in seen[0].headers
        assert client.get("/config").status_code == 404


def test_relay_manifest_identity_and_url(tmp_path):
    entry = {"id": "platform-1", "upstream_model": "actual", "base_url": "https://model.invalid/v1",
             "api_key": "synthetic", "allowed_user": "account-a"}
    path = tmp_path / "model-relay.json"
    path.write_text(json.dumps({"models": [entry]}))
    models = load_models(path, "account-a")
    assert models["platform-1"].allowed_user == "account-a"
    assert "synthetic" not in repr(models)
    for account in ("", "account-b"):
        with pytest.raises(ValueError):
            load_models(path, account)
    path.write_text(json.dumps({"models": [entry, entry]}))
    with pytest.raises(ValueError):
        load_models(path, "account-a")
    for value in ("file:///tmp/model", "https://user:password@model/v1", "https://model/v1?target=a", "https://model/#x"):
        with pytest.raises(ValueError):
            fixed_base(value)


def test_relay_redirect_does_not_send_key_to_other_target():
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://other.invalid"}, text="private")
    model = Model("one", "actual", "https://model.invalid/v1", "synthetic", "account-a")
    with TestClient(create_app(models={"one": model}, transport=httpx.MockTransport(upstream))) as client:
        response = client.post("/v1/chat/completions", json={"model": "one"})
        assert response.status_code == 502
        assert len(seen) == 1
        assert "private" not in response.text


def test_authless_intranet_model_does_not_send_placeholder_authorization(tmp_path):
    path = tmp_path / "model-relay.json"
    path.write_text(json.dumps({"models": [{
        "id": "no-auth", "upstream_model": "local", "base_url": "http://vllm:8000/v1",
        "api_key": "", "allowed_user": "account-a",
    }]}), encoding="utf-8")
    models = load_models(path, "account-a")
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, stream=Stream())
    with TestClient(create_app(models=models, transport=httpx.MockTransport(upstream))) as client:
        assert client.post("/v1/chat/completions", json={"model": "no-auth"},
                           headers={"Authorization": "Bearer caller-placeholder"}).status_code == 200
    assert "authorization" not in seen[0].headers
