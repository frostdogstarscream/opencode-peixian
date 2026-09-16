import asyncio
import io

import httpx
import pytest

from gateway.app import download
from gateway.http_utils import upstream_response


class Stream(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield b"synthetic"

    async def aclose(self):
        self.closed = True


def test_upstream_closed_when_response_start_fails_before_body_enters():
    async def scenario():
        stream = Stream()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))) as client:
            response = await upstream_response(client, client.build_request("GET", "http://synthetic"))
            async def send(message):
                raise RuntimeError("synthetic response start failure")
            with pytest.raises(RuntimeError):
                await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send)
            assert stream.closed
    asyncio.run(scenario())


def test_download_handle_closed_when_cancelled_before_body_enters():
    async def scenario():
        handle = io.BytesIO(b"synthetic")
        response = download(handle, "synthetic.txt")
        async def send(message):
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send)
        assert handle.closed
    asyncio.run(scenario())
