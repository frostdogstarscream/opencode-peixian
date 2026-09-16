import asyncio

import httpx
import pytest

from examples.console_client import ConsoleClient, ConsoleError, retry_seconds


def test_retry_after_is_exposed_and_mutations_are_never_replayed():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(503, headers={"Retry-After": "3"}, json={"message": "busy"})
    async def run():
        async with ConsoleClient("http://fixture", transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ConsoleError) as caught:
                await client.send_message("session", "synthetic")
            assert caught.value.status == 503
            assert caught.value.retry_after == 3
    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("network_failure", [False, True])
def test_unknown_submission_does_not_become_a_retry_or_a_durable_run(network_failure):
    calls = []
    def respond(request):
        calls.append(request)
        if network_failure:
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(504, json={"message": "unknown"})
    async def run():
        async with ConsoleClient("http://fixture", transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ConsoleError) as caught:
                await client.send_message("session", "synthetic")
            assert caught.value.result_unknown
            assert "unknown" in str(caught.value)
    asyncio.run(run())
    assert len(calls) == 1


def test_sse_auth_failure_stops_instead_of_reconnecting():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(401, json={"message": "expired"})
    async def run():
        async with ConsoleClient("http://fixture", transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ConsoleError) as caught:
                await anext(client.events())
            assert caught.value.status == 401
    asyncio.run(run())
    assert len(calls) == 1
    assert retry_seconds("untrusted value") is None
