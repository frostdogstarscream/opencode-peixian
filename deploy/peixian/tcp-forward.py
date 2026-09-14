"""Forward opaque TCP streams to the one deployment-configured OpenCode instance."""

import asyncio
from functools import partial
import logging
import os
import socket


async def copy_stream(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    # Preserve TCP half-close so an upstream response can finish after request EOF.
    if writer.can_write_eof():
        writer.write_eof()
        await writer.drain()


async def relay(reader, writer, *, upstream_host, upstream_port):
    upstream_writer = None
    tasks = []
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(upstream_host, upstream_port, family=socket.AF_INET),
            timeout=10,
        )
        # No stream idle timeout: SSE and WebSocket connections may be quiet.
        tasks = [
            asyncio.create_task(copy_stream(reader, upstream_writer)),
            asyncio.create_task(copy_stream(upstream_reader, writer)),
        ]
        await asyncio.gather(*tasks)
    except (OSError, TimeoutError) as error:
        # Do not record payloads, URLs, headers, credentials, or peer addresses.
        logging.warning("TCP forwarding failed (%s)", type(error).__name__)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writers = [writer] if upstream_writer is None else [writer, upstream_writer]
        for stream in writers:
            stream.close()
        await asyncio.gather(
            *(asyncio.wait_for(stream.wait_closed(), timeout=3) for stream in writers),
            return_exceptions=True,
        )


async def main():
    # Only deployment configuration selects the destination; client bytes never do.
    upstream_host = os.environ.get("UPSTREAM_HOST", "")
    if upstream_host not in ("client-a", "client-b"):
        raise SystemExit("UPSTREAM_HOST must name the assigned client-a or client-b service")
    if os.environ.get("UPSTREAM_PORT", "4096") != "4096":
        raise SystemExit("UPSTREAM_PORT must be 4096")
    if os.environ.get("LISTEN_PORT", "4096") != "4096":
        raise SystemExit("LISTEN_PORT must be 4096")
    server = await asyncio.start_server(
        partial(relay, upstream_host=upstream_host, upstream_port=4096),
        host="0.0.0.0",
        port=4096,
        family=socket.AF_INET,
    )
    logging.info("TCP entry ready")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main())
