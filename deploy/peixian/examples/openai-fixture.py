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
import threading
import re
import math
from urllib.parse import urlsplit, parse_qs

MODEL = "synthetic-openai-compatible"
TEXT = "【OpenAI 兼容接口测试桩】此回复仅验证平台的 OpenAI 兼容消息与流式协议，不代表真实 vLLM、DeepSeek 或业务分析结果。"
LOCK = threading.RLock()
MODES = {}
COUNTERS = {"accepted": 0, "active": 0, "completed": 0, "disconnected": 0, "peak_active": 0,
            "record_queries": 0, "tool_calls": 0}


def configure(marker, value):
    if not re.fullmatch(r"r2-[a-f0-9]{32}", marker) or not isinstance(value, dict) or set(value) - {"seconds", "release", "tool"}:
        raise ValueError("invalid_fixture_mode")
    seconds = value.get("seconds", 0)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 600:
        raise ValueError("invalid_fixture_seconds")
    if "release" in value and type(value["release"]) is not bool:
        raise ValueError("invalid_fixture_release")
    if "tool" in value and type(value["tool"]) is not bool:
        raise ValueError("invalid_fixture_tool")
    with LOCK:
        for key, item in tuple(MODES.items()):
            if item["expires"] < time.monotonic():
                MODES.pop(key)
        if marker not in MODES and len(MODES) >= 64:
            raise ValueError("fixture_mode_capacity")
        MODES[marker] = {"seconds": seconds, "release": value.get("release", False),
                        "tool": value.get("tool", False), "expires": time.monotonic() + 900}


def selected_mode(payload):
    text = json.dumps(payload.get("messages", []), ensure_ascii=False)
    with LOCK:
        return next((key for key in reversed(MODES) if key in text and MODES[key]["expires"] >= time.monotonic()), None)


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
        elif self.path == "/internal/fixture/stats":
            with LOCK:
                self.reply(200, {"fixture": True, "protocol_version": 2, **COUNTERS})
        elif urlsplit(self.path).path == "/records":
            query = parse_qs(urlsplit(self.path).query)
            try:
                limit = max(1, min(20, int(query.get("limit", ["5"])[0])))
            except ValueError:
                self.reply(400, {"error": "invalid_limit"})
                return
            with LOCK:
                COUNTERS["record_queries"] += 1
            self.reply(200, {"items": [{"id": "synthetic-" + str(i), "name": "合成资料",
                                       "content": "仅用于独立验收。"} for i in range(min(limit, 3))]})
        else:
            self.reply(404, {"error": {"message": "not_found"}})

    def do_POST(self):
        if not self.authorized():
            self.reply(401, {"error": {"message": "unauthorized", "type": "authentication_error"}})
            return
        if self.path.startswith("/internal/fixture/modes/"):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024:
                    raise ValueError()
                configure(self.path.rsplit("/", 1)[-1], json.loads(self.rfile.read(size)))
                self.reply(200, {"fixture": True, "configured": True})
            except (ValueError, TypeError):
                self.reply(400, {"error": "invalid_fixture_mode"})
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
            if (not isinstance(payload, dict) or payload.get("model") != MODEL
                    or not isinstance(payload.get("messages"), list)
                    or any(not isinstance(item, dict) for item in payload["messages"])
                    or not isinstance(payload.get("tools", []), list)
                    or any(not isinstance(item, dict) or not isinstance(item.get("function", {}), dict)
                           for item in payload.get("tools", []))):
                raise ValueError()
        except (TypeError, ValueError):
            self.reply(400, {"error": {"message": "invalid_synthetic_request"}})
            return
        base = {"id": "synthetic-completion", "created": int(time.time()), "model": MODEL}
        marker = selected_mode(payload)
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
        with LOCK:
            tool = bool(marker and MODES[marker].get("tool"))
        # Only a configured marker may trigger this one fixed read-only tool;
        # the next model turn, which contains its tool result, returns text.
        marker_index = max((index for index, item in enumerate(payload["messages"])
                            if marker and marker in json.dumps(item, ensure_ascii=False)), default=-1)
        if tool and not any(item.get("role") == "tool" for item in payload["messages"][marker_index + 1:]):
            names = [item.get("function", {}).get("name", "") for item in payload.get("tools", [])]
            name = next((value for value in names if isinstance(value, str)
                         and value.endswith("platform_sample_records")), None)
            if name is None:
                self.reply(400, {"error": "synthetic_tool_not_loaded"})
                return
            chunks[1]["choices"][0]["delta"] = {"tool_calls": [{"index": 0, "id": "call_synthetic_records",
                "type": "function", "function": {"name": name, "arguments": "{}"}}]}
            chunks[2]["choices"][0]["finish_reason"] = "tool_calls"
            with LOCK:
                COUNTERS["tool_calls"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with LOCK:
            COUNTERS["accepted"] += 1
            COUNTERS["active"] += 1
            COUNTERS["peak_active"] = max(COUNTERS["peak_active"], COUNTERS["active"])
        try:
            def emit(chunk):
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
            emit(chunks[0])
            started = time.monotonic()
            if marker:
                while True:
                    with LOCK:
                        mode = MODES.get(marker, {"seconds": 0, "release": True})
                    if mode["release"] or time.monotonic() - started >= mode["seconds"]:
                        break
                    emit({**base, "object": "chat.completion.chunk", "choices": [{"index": 0,
                        "delta": {"content": "合成。"}, "finish_reason": None}]})
                    time.sleep(0.25)
            for chunk in chunks[1:]:
                emit(chunk)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            with LOCK:
                COUNTERS["completed"] += 1
        except (BrokenPipeError, ConnectionResetError):
            with LOCK:
                COUNTERS["disconnected"] += 1
        finally:
            with LOCK:
                COUNTERS["active"] -= 1


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
