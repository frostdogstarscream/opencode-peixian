"""Fixed-destination OpenAI-compatible relay, isolated to one account network."""
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException, Request
import httpx

from .http_utils import fixed_base, json_body, reject_file_urls, upstream_response
from .service_connections import load_connections, invoke
from .admission import ActivityMiddleware
from .runtime_management import RuntimeManagement, register_management
from .settings import RelaySettings, runtime_protocol_enabled


@dataclass(frozen=True)
class Model:
    id: str
    upstream_model: str
    base_url: str
    api_key: str = field(repr=False)
    allowed_user: str = ""


def load_models(path, account_id):
    if not account_id:
        raise ValueError("ACCOUNT_ID must identify this model relay")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = payload["models"]
        if not isinstance(entries, list):
            raise ValueError()
        models = {}
        for item in entries:
            if not isinstance(item, dict) or set(item) != {"id", "upstream_model", "base_url", "api_key", "allowed_user"}:
                raise ValueError()
            if not all(isinstance(value, str) and (value or key == "api_key") for key, value in item.items()):
                raise ValueError()
            if item["allowed_user"] != account_id or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", item["id"]):
                raise ValueError()
            if item["id"] in models or any(char in item["api_key"] for char in "\r\n\0"):
                raise ValueError()
            models[item["id"]] = Model(**{**item, "base_url": fixed_base(item["base_url"])})
        return models
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Invalid account model relay configuration") from None


def create_app(*, models=None, connections=None, transport=None, runtime_settings=None, management_transport=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.models = models if models is not None else load_models(
            Path(os.environ.get("MANAGED_ROOT", "/managed")) / "model-relay.json", os.environ.get("ACCOUNT_ID", "")
        )
        app.state.connections = connections if connections is not None else load_connections(
            Path(os.environ.get("MANAGED_ROOT", "/managed")) / "connections.json", os.environ.get("ACCOUNT_ID", "")
        )
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, verify=True,
            timeout=httpx.Timeout(connect=10, read=300, write=60, pool=10),
        ) as client:
            app.state.client = client
            config = runtime_settings or (RelaySettings.from_env() if runtime_protocol_enabled() else None)
            manager = RuntimeManagement(app, config, relay=True, transport=management_transport) if config else None
            if manager:
                app.state.runtime_management = manager
                await manager.start()
            try:
                yield
            finally:
                if manager:
                    await manager.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(ActivityMiddleware, owner=app, relay=True)
    register_management(app, relay=True)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/platform/connections/{cid}/request")
    async def connection_request(cid: str, request: Request):
        return await invoke(request, cid)

    @app.get("/v1/models")
    async def list_models():
        return {"object": "list", "data": [
            {"id": model.id, "object": "model", "owned_by": "managed"}
            for model in app.state.models.values()
        ]}

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        body = await json_body(request)
        model = app.state.models.get(body.get("model")) if isinstance(body.get("model"), str) else None
        if model is None:
            raise HTTPException(403, "Model is not authorized for this account")
        reject_file_urls(body)
        if any(key in body for key in ("base_url", "api_key", "url", "allowed_user", "tenant_id", "account_id")):
            raise HTTPException(400, "Upstream selection is fixed")
        gate = getattr(app.state, "admission", None)
        if gate:
            gate.require_egress()
        body["model"] = model.upstream_model
        headers = {"Content-Type": "application/json",
                   "Accept": "text/event-stream" if body.get("stream") else "application/json",
                   "Accept-Encoding": "identity"}
        if model.api_key:
            headers["Authorization"] = "Bearer " + model.api_key
        upstream = app.state.client.build_request(
            "POST", model.base_url + "/chat/completions", json=body, headers=headers,
        )
        return await upstream_response(app.state.client, upstream)

    return app


app = create_app()
