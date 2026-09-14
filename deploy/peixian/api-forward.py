"""Per-client, fixed-destination DeepSeek HTTPS gateway for local testing."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import ssl
import threading


UPSTREAM_HOST = "api.deepseek.com"
UPSTREAM_PORT = 443
MODEL = "deepseek-flash"
MAX_BODY = 8 * 1024 * 1024
CONNECT_TIMEOUT = 10
UPSTREAM_IDLE_TIMEOUT = 300
CLIENT_TIMEOUT = 15
MAX_CONNECTIONS = 4


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, api_key):
        self.api_key = api_key
        self.tls_context = ssl.create_default_context()
        self.tls_context.set_alpn_protocols(["http/1.1"])
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, GatewayHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # The default implementation writes a traceback and client details.
        logging.warning("DeepSeek gateway request failed")


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PeixianGateway"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(CLIENT_TIMEOUT)

    def log_message(self, format, *args):
        # Never log request lines, headers, bodies, or credentials.
        pass

    def handle_expect_100(self):
        self.reject(417, "Expect is not supported")
        return False

    def reject(self, status, message):
        body = json.dumps({"error": {"message": message, "type": "gateway_error"}}).encode()
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def do_CONNECT(self):
        self.reject(405, "Method is not allowed")

    def do_HEAD(self):
        self.reject(405, "Method is not allowed")

    def do_OPTIONS(self):
        self.reject(405, "Method is not allowed")

    def do_PUT(self):
        self.reject(405, "Method is not allowed")

    def do_PATCH(self):
        self.reject(405, "Method is not allowed")

    def do_DELETE(self):
        self.reject(405, "Method is not allowed")

    def forward(self):
        self.close_connection = True
        if (self.command, self.path) not in (
            ("GET", "/v1/models"),
            ("POST", "/v1/chat/completions"),
        ):
            self.reject(403, "Endpoint is not allowed")
            return
        # Reject ambiguous request framing; the SDK sends a finite JSON body.
        if self.headers.get_all("Transfer-Encoding"):
            self.reject(400, "Transfer-Encoding is not supported")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            self.reject(400, "Multiple Content-Length headers are not allowed")
            return
        length_text = lengths[0] if lengths else "0"
        if not length_text.isascii() or not length_text.isdecimal() or len(length_text) > 10:
            self.reject(400, "Content-Length is invalid")
            return
        length = int(length_text)
        if length > MAX_BODY:
            self.reject(413, "Request body exceeds the gateway limit")
            return
        if self.command == "GET" and length:
            self.reject(400, "GET body is not allowed")
            return

        body = None
        if self.command == "POST":
            if not lengths:
                self.reject(411, "Content-Length is required")
                return
            if self.headers.get_content_type() != "application/json":
                self.reject(415, "Content-Type must be application/json")
                return
            try:
                body = self.rfile.read(length)
            except TimeoutError:
                self.reject(408, "Request body timed out")
                return
            if len(body) != length:
                self.reject(400, "Request body is incomplete")
                return
            try:
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict) or payload.get("model") != MODEL:
                    self.reject(403, "Only deepseek-flash is allowed")
                    return
                # Reserialization ensures validation and upstream use the same JSON values.
                body = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            except (ValueError, UnicodeError, RecursionError):
                self.reject(400, "Request body must be valid JSON")
                return

        upstream = http.client.HTTPSConnection(
            UPSTREAM_HOST,
            UPSTREAM_PORT,
            timeout=CONNECT_TIMEOUT,
            context=self.server.tls_context,
        )
        response_started = False
        try:
            # No client header, path fragment, query, or body field controls this destination.
            upstream.connect()
            upstream.sock.settimeout(UPSTREAM_IDLE_TIMEOUT)
            upstream.request(
                self.command,
                self.path,
                body=body,
                headers={
                    "Authorization": "Bearer " + self.server.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = upstream.getresponse()
            # http.client does not follow redirects; do not pass Location to callers either.
            if 300 <= response.status < 400:
                self.reject(502, "Upstream redirect is not allowed")
                return
            if response.status < 200 or response.status > 599:
                self.reject(502, "Upstream status is invalid")
                return
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            response_started = True
            # read1 returns available bytes without waiting to fill a large buffer.
            # Reframe upstream chunked or Content-Length bodies into downstream chunks.
            while chunk := response.read1(65536):
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (OSError, http.client.HTTPException) as error:
            logging.warning("DeepSeek upstream failure (%s)", type(error).__name__)
            # After streaming starts, close without a final chunk so clients see truncation.
            if not response_started:
                self.reject(502, "Upstream connection failed")
        finally:
            upstream.close()


def main():
    path = os.environ.get("DEEPSEEK_API_KEY_FILE", "/run/secrets/deepseek-api-key")
    try:
        api_key = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        raise SystemExit("DeepSeek key file is missing or unreadable") from None
    if not api_key or len(api_key) > 4096 or any(char.isspace() for char in api_key):
        raise SystemExit("DeepSeek key file is invalid")
    if not api_key.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in api_key):
        raise SystemExit("DeepSeek key file is invalid")
    with GatewayServer(("0.0.0.0", 8080), api_key) as server:
        logging.info("DeepSeek gateway ready")
        server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
