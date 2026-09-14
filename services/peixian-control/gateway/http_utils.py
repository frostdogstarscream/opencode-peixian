import json
from urllib.parse import urlsplit

from fastapi import HTTPException
import httpx
from starlette.responses import StreamingResponse


MAX_BODY = 20 * 1024 * 1024


def fixed_base(value):
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Invalid managed upstream URL")
    if parts.query or parts.fragment or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid managed upstream URL")
    return value.rstrip("/")


async def json_body(request, limit=MAX_BODY):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "Request body exceeds limit")
    try:
        value = json.loads(body) if body else {}
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "Invalid JSON body") from None
    if not isinstance(value, dict):
        raise HTTPException(400, "JSON body must be an object")
    return value


def reject_file_urls(value):
    # Attachments are supplied by the control layer as extracted text.
    pending = [value]
    examined = 0
    while pending:
        value = pending.pop()
        examined += 1
        if examined > 100000:
            raise HTTPException(400, "JSON structure exceeds limit")
        if isinstance(value, dict):
            if value.get("type") in ("file", "image_url", "input_image", "input_file") or any(
                key in value for key in ("file_url", "image_url", "fileURL")
            ):
                raise HTTPException(400, "Use a managed file text reference")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


async def upstream_response(client, request):
    try:
        response = await client.send(request, stream=True, follow_redirects=False)
    except httpx.HTTPError:
        raise HTTPException(502, "Upstream connection failed") from None
    if 300 <= response.status_code < 400:
        await response.aclose()
        raise HTTPException(502, "Upstream redirect rejected")
    # Upstream error bodies can include URLs, credentials, or echoed prompts.
    if response.status_code >= 400:
        status = response.status_code
        await response.aclose()
        raise HTTPException(status, "Upstream rejected request")
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    for key in ("content-type", "content-encoding"):
        if key in response.headers:
            headers[key] = response.headers[key]

    async def body():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        except httpx.HTTPError:
            # An interrupted stream must not look like a normal completed response.
            raise RuntimeError("Upstream stream interrupted") from None
        finally:
            await response.aclose()

    return StreamingResponse(body(), status_code=response.status_code, headers=headers)
