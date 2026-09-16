"""Real loopback HTTP/1.1; synthetic credentials, no Docker or remote service."""
import importlib.util
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

spec = importlib.util.spec_from_file_location("r3_worker", Path(__file__).parents[1] / "console-worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_management_posts_use_fresh_sockets_and_never_replay_unknown_result():
    ports = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args):
            pass
        def do_POST(self):
            ports.append(self.client_address[1])
            if self.path == "/lost":
                self.close_connection = True
                return  # Models a committed operation whose response is lost.
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with worker.control_client("http://127.0.0.1:" + str(server.server_port), "synthetic-key") as client:
            for _ in range(3):
                assert client.post("/claim").status_code == 200
            assert len(set(ports)) == 3
            with pytest.raises(httpx.RemoteProtocolError):
                client.post("/lost")
            assert len(ports) == 4
            assert client.post("/claim").status_code == 200
            assert len(set(ports)) == 5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
