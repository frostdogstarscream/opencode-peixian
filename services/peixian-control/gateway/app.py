"""Private, per-account OpenCode gateway; run one uvicorn worker per account."""
from contextlib import asynccontextmanager
import asyncio
import base64
import hmac
import hashlib
import json
import os
import re
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
import httpx
from starlette.responses import JSONResponse, StreamingResponse

from .http_utils import ClosingStreamingResponse, fixed_base, json_body, reject_file_urls, upstream_response
from .parse_queue import ParseQueue
from .safe_fs import UnsafePath
from .settings import MAX_UPLOAD, Settings
from .storage import FileStore, QuotaExceeded, SUPPORTED, display_name
from .plugin_test import run_plugin_test
from .admission import ActivityMiddleware
from .runtime_management import RuntimeManagement, register_management


# Explicit method/path pairs. Config, shell, command, PTY, auth, MCP and native
# file endpoints are intentionally absent.
NATIVE = (
    ("GET", r"/global/(health|event)"),
    ("GET", r"/(skill|permission|question)"),
    ("GET", r"/session"),
    ("POST", r"/session"),
    ("GET", r"/session/status"),
    ("GET", r"/session/[A-Za-z0-9_-]+"),
    ("PATCH", r"/session/[A-Za-z0-9_-]+"),
    ("DELETE", r"/session/[A-Za-z0-9_-]+"),
    ("GET", r"/session/[A-Za-z0-9_-]+/(message|children|todo|diff)"),
    ("GET", r"/session/[A-Za-z0-9_-]+/message/[A-Za-z0-9_-]+"),
    ("POST", r"/session/[A-Za-z0-9_-]+/(message|prompt_async|abort)"),
    ("POST", r"/permission/[A-Za-z0-9_-]+/reply"),
    ("POST", r"/question/[A-Za-z0-9_-]+/(reply|reject)"),
)


class RequestGuard:
    def __init__(self, app, owner):
        self.app, self.owner = app, owner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = getattr(self.owner.state, "settings", None)
        key = dict(scope.get("headers", [])).get(b"x-peixian-key", b"")
        relay_permit = scope.get("path") == "/internal/runtime/relay-permit"
        if relay_permit and settings is not None:
            key = dict(scope.get("headers", [])).get(b"x-relay-management-key", b"")
        expected = settings.relay_management_key if relay_permit and settings else settings.token if settings else ""
        if scope.get("path") == "/internal/facts/execute" and settings:
            key = dict(scope.get("headers", [])).get(b"x-facts-key", b"")
            expected = hmac.new(settings.token.encode(), b"facts-agent-v1", hashlib.sha256).hexdigest()

        if settings is None or not expected or not hmac.compare_digest(key, expected.encode()):
            return await JSONResponse({"detail": "Unauthorized"}, 401)(scope, receive, send)
        # Count actual bytes, including chunked requests. Upload gets 1 MiB for
        # multipart framing, while the stored file itself is limited to 20 MiB.
        maximum = MAX_UPLOAD + 1024 * 1024
        length = dict(scope.get("headers", [])).get(b"content-length")
        if length:
            try:
                if int(length) < 0 or int(length) > maximum:
                    return await JSONResponse({"detail": "Request body exceeds limit"}, 413)(scope, receive, send)
            except ValueError:
                return await JSONResponse({"detail": "Invalid content length"}, 400)(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise HTTPException(413, "Request body exceeds limit")
            return message

        await self.app(scope, bounded_receive, send)


def download(handle, name):
    async def body():
        try:
            while chunk := handle.read(65536):
                yield chunk
        finally:
            handle.close()

    async def close():
        handle.close()

    return ClosingStreamingResponse(body(), close=close, media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })


def create_app(settings=None, *, transport=None, management_transport=None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        config.opencode_url = fixed_base(config.opencode_url)
        store = FileStore(config.files_root, config.workspace, require_linux=config.require_linux, quota_bytes=config.upload_quota)
        queue = ParseQueue(store)
        app.state.settings, app.state.store, app.state.queue = config, store, queue
        app.state.plugin_lock = asyncio.Lock()
        try:
            revision = json.loads((config.managed_root / "revision.json").read_text(encoding="utf-8"))
            if not isinstance(revision, dict) or not isinstance(revision.get("uid"), str) or not isinstance(revision.get("runtime_id"), str) or not isinstance(revision.get("revision"), (str, int)):
                raise ValueError()
            app.state.revision = {key: revision[key] for key in ("uid", "runtime_id", "revision")}
        except FileNotFoundError:
            app.state.revision = {}
        except (OSError, ValueError):
            store.close()
            raise RuntimeError("Managed revision is invalid") from None
        async with httpx.AsyncClient(transport=transport, trust_env=False,
                                    timeout=httpx.Timeout(connect=10, read=None, write=30, pool=10)) as client:
            app.state.client = client
            manager = None
            if config.runtime_protocol:
                if (app.state.revision.get("runtime_id") != config.runtime_id or not config.runtime_key or not config.relay_management_key):
                    raise RuntimeError("Runtime protocol identity is invalid")
                config.revision = app.state.revision["revision"]
                config.activity_root = config.activity_root or config.files_root / ".runtime-state"
                manager = RuntimeManagement(app, config, transport=management_transport)
                app.state.runtime_management = manager
                queue.admission = manager.gate
                await manager.start()
            await queue.start()
            try:
                yield
            finally:
                if manager:
                    await manager.stop()
                await queue.stop()
                store.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(ActivityMiddleware, owner=app)
    app.add_middleware(RequestGuard, owner=app)
    register_management(app)
    from .facts_execution import register as register_facts
    register_facts(app)
    from .planning import register as register_planning
    register_planning(app)

    @app.exception_handler(QuotaExceeded)
    async def quota_exceeded(request, exception):
        return JSONResponse({"detail": "Account upload quota exceeded"}, 413)

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exception):
        return JSONResponse({"detail": "File not found"}, 404)

    @app.exception_handler(UnsafePath)
    async def unsafe(request, exception):
        return JSONResponse({"detail": "Invalid file path"}, 400)

    @app.exception_handler(OSError)
    async def filesystem_error(request, exception):
        return JSONResponse({"detail": "File operation unavailable"}, 409)

    @app.get("/health")
    async def health():
        return {"ok": True, **app.state.revision}

    @app.get("/files")
    async def files():
        return {"items": app.state.store.list()}

    @app.post("/files", status_code=202)
    async def upload(request: Request):
        store, identity, handle = app.state.store, None, None
        try:
            async with request.form(max_files=1, max_fields=0, max_part_size=MAX_UPLOAD) as form:
                file = form.get("file")
                if not file or not hasattr(file, "read") or len(form) != 1:
                    raise HTTPException(400, "Exactly one file field is required")
                # Multipart parsing has counted actual bytes. Inspect the
                # completed spool file, never a caller-supplied Content-Length.
                actual_size = file.file.seek(0, os.SEEK_END)
                await file.seek(0)
                if actual_size > MAX_UPLOAD:
                    raise HTTPException(413, "File exceeds 20 MiB")
                try:
                    identity, handle, _ = store.begin_upload(file.filename or "upload.bin", expected_size=actual_size)
                except ValueError:
                    raise HTTPException(400, "Invalid file name") from None
                size = 0
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "File exceeds 20 MiB")
                    store.write_upload(identity, handle, chunk)
                handle.flush()
                os.fsync(handle.fileno())
                handle.close()
                handle = None
                metadata = store.finish_upload(identity, size)
                if metadata["status"] == "queued":
                    app.state.queue.enqueue(identity)
                return store.public(metadata)
        except BaseException:
            if handle:
                handle.close()
            if identity:
                store.delete(identity, incomplete=True)
            raise

    @app.get("/files/{identity}")
    async def file_metadata(identity: str):
        return app.state.store.public(app.state.store.metadata(identity))

    @app.patch("/files/{identity}")
    async def rename(identity: str, request: Request):
        body = await json_body(request, 4096)
        if set(body) != {"name"}:
            raise HTTPException(400, "Only a display name can be changed")
        try:
            name = display_name(body["name"])
        except ValueError:
            raise HTTPException(400, "Invalid file name") from None
        return app.state.store.public(app.state.store.update(identity, name=name))

    @app.delete("/files/{identity}")
    async def delete(identity: str):
        try:
            app.state.store.delete(identity)
        except ValueError:
            raise HTTPException(409, "File is being parsed") from None
        return {"ok": True}

    @app.post("/files/{identity}/parse", status_code=202)
    async def parse(identity: str):
        metadata = app.state.store.metadata(identity)
        if metadata["extension"] not in SUPPORTED:
            raise HTTPException(415, "File format is not supported for parsing")
        if metadata["status"] != "parsing":
            metadata = app.state.store.update(identity, status="queued", error=None)
            app.state.queue.enqueue(identity)
        return app.state.store.public(metadata)

    @app.get("/files/{identity}/text")
    async def text(identity: str):
        return app.state.store.text(identity)

    @app.get("/files/{identity}/preview")
    async def preview(identity: str):
        result = app.state.store.text(identity)
        result["truncated"] = result["truncated"] or len(result["text"]) > 20000 or len(result["chunks"]) > 100
        result["text"], result["chunks"] = result["text"][:20000], result["chunks"][:100]
        # Individual chunks may be large (a PDF page); preview has its own bound.
        budget = 20000
        chunks = []
        for chunk in result["chunks"]:
            if budget <= 0:
                break
            part = dict(chunk)
            part["text"] = part["text"][:budget]
            budget -= len(part["text"])
            chunks.append(part)
        result["chunks"] = chunks
        return result

    @app.get("/files/{identity}/download")
    async def file_download(identity: str):
        item = app.state.store.metadata(identity)
        return download(app.state.store.files.open(item["source"]), item["name"])

    @app.get("/results")
    async def results():
        return app.state.store.results()

    @app.get("/results/{identity}/download")
    async def result_download(identity: str):
        item = app.state.store.result(identity)
        return download(app.state.store.workspace.open(item["relative_path"]), item["name"])

    @app.post("/plugins/{identity}/test")
    async def plugin_test(identity: str):
        if app.state.plugin_lock.locked():
            raise HTTPException(429, "A plugin test is already running")
        async with app.state.plugin_lock:
            return await run_plugin_test(app.state.settings.managed_root, identity)

    @app.get("/internal/runtime/runs/{run_id}")
    async def run_receipt(run_id: str):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):raise HTTPException(404, "Receipt not found")
        config=app.state.settings
        headers={"Authorization":"Basic "+base64.b64encode(("opencode:"+config.opencode_password).encode()).decode("ascii"),"x-opencode-directory":"/workspace"}
        response=await app.state.client.get(config.opencode_url+"/internal/peixian/activity",params={"run_id":run_id,"directory":"/workspace"},headers=headers,timeout=5)
        response.raise_for_status();value=response.json()
        if 'durable_run_v1' not in value.get('capabilities',[]):raise HTTPException(409,"Runtime upgrade required")
        return {"protocol":"durable_run_v1","receipt":value.get('receipt'),"boot_id":value['boot_id']}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    async def native(path: str, request: Request):
        path = "/" + path
        if not any(request.method == method and re.fullmatch(pattern, path) for method, pattern in NATIVE):
            raise HTTPException(404, "Endpoint is not exposed")
        if any(value != "/workspace" for value in request.query_params.getlist("directory")):
            raise HTTPException(400, "Workspace selection is fixed")
        if any(key.lower() in ("workspace", "workspaceid", "tenant", "tenant_id") for key in request.query_params):
            raise HTTPException(400, "Account routing is fixed")
        query = [(key, value) for key, value in request.query_params.multi_items() if key != "directory"]
        query.append(("directory", "/workspace"))
        body = None
        if request.method in ("POST", "PATCH", "PUT"):
            body = await json_body(request)
            reject_file_urls(body)
            if any(key in body for key in ("directory", "workspace", "workspaceID", "tenant", "tenant_id")):
                raise HTTPException(400, "Workspace selection is fixed")
        config = app.state.settings
        upstream = app.state.client.build_request(
            request.method, config.opencode_url + path, params=query, json=body,
            headers={"Accept": request.headers.get("accept", "application/json"), "Accept-Encoding": "identity",
                     "x-opencode-directory": "/workspace"},
        )
        upstream.headers["Authorization"] = "Basic " + base64.b64encode(("opencode:" + config.opencode_password).encode()).decode("ascii")
        run_id=request.headers.get('x-peixian-run-id')
        if run_id:
            if not re.fullmatch(r'[a-f0-9]{32}',run_id) or request.method!='POST' or not path.endswith('/prompt_async'):
                raise HTTPException(400,'Invalid run identity')
            upstream.headers['X-Peixian-Run-ID']=run_id
        gate = getattr(app.state, "admission", None)
        identity = None
        if gate and request.method == "POST" and path.endswith(("/message", "/prompt_async")):
            identity = gate.register("pending_start", resource=path.split("/")[2])
            upstream.headers["X-Peixian-Activity-ID"] = identity
        try:
            response=await upstream_response(app.state.client, upstream)
            if identity and 400<=response.status_code<500:gate.finish(identity)
            return response
        except BaseException:
            if identity:
                gate.unknown(identity)
            raise

    return app


app = create_app()
