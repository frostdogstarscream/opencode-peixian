"""Synthetic OpenAI-compatible HTTP fixture; this is not vLLM or a real model.

Only deterministic synthetic text is returned. Request prompts, authorization,
and bodies are never logged. FIXTURE_KEY_FILE supplies a private Bearer key.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import time

MODEL = "synthetic-openai-compatible"
TEXT = "【OpenAI 兼容接口测试桩】此回复仅验证平台的 OpenAI 兼容消息与流式协议，不代表真实 vLLM、DeepSeek 或业务分析结果。"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def authorized(self):
        key = Path(os.environ["FIXTURE_KEY_FILE"]).read_text().strip()
        return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + key)

    def reply(self, status, data):
        content = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"ok": True, "fixture": True})
        elif not self.authorized():
            self.reply(401, {"error": {"message": "unauthorized", "type": "authentication_error"}})
        elif self.path == "/v1/models":
            self.reply(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "created": 0, "owned_by": "synthetic-fixture"}]})
        else:
            self.reply(404, {"error": {"message": "not_found"}})

    def do_POST(self):
        if not self.authorized():
            self.reply(401, {"error": {"message": "unauthorized", "type": "authentication_error"}})
            return
        if self.path != "/v1/chat/completions":
            self.reply(404, {"error": {"message": "not_found"}})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4 * 1024 * 1024:
                self.reply(413, {"error": {"message": "request_too_large"}})
                return
            payload = json.loads(self.rfile.read(size))
            if payload.get("model") != MODEL or not isinstance(payload.get("messages"), list):
                raise ValueError()
        except (TypeError, ValueError):
            self.reply(400, {"error": {"message": "invalid_synthetic_request"}})
            return
        base = {"id": "synthetic-completion", "created": int(time.time()), "model": MODEL}
        if not payload.get("stream"):
            self.reply(200, {**base, "object": "chat.completion", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": TEXT}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
            return
        chunks = [
            {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
            {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": TEXT}, "finish_reason": None}]},
            {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
