import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import pytest

from examples.console_client import ConsoleClient


@pytest.fixture
def tls_fixture(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic local fixture")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                   .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "ca.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            events = self.path.endswith("/events")
            payload = b"event: change\ndata: {}\n\n" if events else json.dumps({"user": {"role": "user"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if events else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port, cert_path
    server.shutdown()
    server.server_close()
    thread.join(2)


def test_default_tls_verification_rejects_untrusted_certificate(tls_fixture):
    port, _ = tls_fixture
    async def run():
        async with ConsoleClient(f"https://127.0.0.1:{port}") as client:
            with pytest.raises(httpx.ConnectError):
                await client.me()
    asyncio.run(run())


def test_explicit_ca_validates_http_and_sse_connections(tls_fixture):
    port, ca_file = tls_fixture
    async def run():
        async with ConsoleClient(f"https://127.0.0.1:{port}", ca_file=ca_file) as client:
            assert (await client.me())["role"] == "user"
            events = client.events()
            try:
                event = await asyncio.wait_for(anext(events), 2)
                assert event["event"] == "change"
            finally:
                await events.aclose()
    asyncio.run(run())


def test_explicit_ca_does_not_disable_hostname_check(tls_fixture):
    port, ca_file = tls_fixture
    async def run():
        async with ConsoleClient(f"https://localhost:{port}", ca_file=ca_file) as client:
            with pytest.raises(httpx.ConnectError):
                await client.me()
    asyncio.run(run())


def test_ca_option_requires_https_and_a_real_bundle(tmp_path):
    with pytest.raises(ValueError):
        ConsoleClient("https://localhost", ca_file=tmp_path / "missing.pem")
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("synthetic")
    with pytest.raises(ValueError):
        ConsoleClient("http://localhost", ca_file=ca_file)
    with pytest.raises(ssl.SSLError):
        ConsoleClient("https://localhost", ca_file=ca_file)
