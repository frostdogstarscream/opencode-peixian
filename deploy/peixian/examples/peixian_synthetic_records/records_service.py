#!/usr/bin/env python3
"""Private, read-only synthetic records service for the Peixian Agent plugin."""

from __future__ import annotations

import copy
import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MODULES = ("funds", "calls", "portrait", "composite", "night", "vehicle", "lookup")
SOURCE = "沛县七项合成资料服务"
MAX_BODY_BYTES = 4096

FIXTURES = {
    "funds": [
        {"record_id": "DEMO-E1", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-A", "member_ref": "DEMO-MEMBER-1", "amount_minor": 10000},
        {"record_id": "DEMO-E2", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-A", "member_ref": "DEMO-MEMBER-1", "amount_minor": 2500},
        {"record_id": "DEMO-E3", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-A", "member_ref": "DEMO-MEMBER-2", "amount_minor": 5000},
        {"record_id": "DEMO-E4", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-B", "member_ref": "DEMO-MEMBER-3", "amount_minor": 900},
        {"record_id": "DEMO-E1", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-A", "member_ref": "DEMO-MEMBER-1", "amount_minor": 10000},
    ],
    "calls": [
        {"record_id": "DEMO-E11", "source_type": "calls", "group_ref": "DEMO-NUMBER-A", "member_ref": "DEMO-MEMBER-1"},
        {"record_id": "DEMO-E12", "source_type": "calls", "group_ref": "DEMO-NUMBER-A", "member_ref": "DEMO-MEMBER-1"},
        {"record_id": "DEMO-E13", "source_type": "calls", "group_ref": "DEMO-NUMBER-A", "member_ref": "DEMO-MEMBER-2"},
        {"record_id": "DEMO-E14", "source_type": "calls", "group_ref": "DEMO-NUMBER-B", "member_ref": "DEMO-MEMBER-3"},
    ],
    "portrait": [
        {"record_id": "DEMO-E21", "source_type": "portrait", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-MEMBER-1", "kind": "same_frame"},
        {"record_id": "DEMO-E22", "source_type": "portrait", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-MEMBER-2", "kind": "same_frame"},
        {"record_id": "DEMO-E23", "source_type": "portrait", "group_ref": "DEMO-OBJECT-B", "member_ref": "DEMO-MEMBER-1", "kind": "same_trip"},
        {"record_id": "DEMO-E24", "source_type": "portrait", "group_ref": "DEMO-OBJECT-C", "member_ref": "DEMO-MEMBER-2", "kind": "same_ride"},
    ],
    "composite": [
        {"record_id": "DEMO-E31", "source_type": "funds", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-MEMBER-1"},
        {"record_id": "DEMO-E32", "source_type": "calls", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-MEMBER-1"},
        {"record_id": "DEMO-E33", "source_type": "portrait", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-MEMBER-2"},
        {"record_id": "DEMO-E34", "source_type": "funds", "group_ref": "DEMO-OBJECT-B", "member_ref": "DEMO-MEMBER-3"},
    ],
    "night": [
        {"record_id": "DEMO-E41", "source_type": "night", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-EVENT-1", "kind": "person", "occurred_at": "2026-01-01T22:00:00+08:00"},
        {"record_id": "DEMO-E42", "source_type": "night", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-EVENT-2", "kind": "person", "occurred_at": "2026-01-02T05:59:00+08:00"},
        {"record_id": "DEMO-E43", "source_type": "night", "group_ref": "DEMO-CAR-A", "member_ref": "DEMO-EVENT-3", "kind": "vehicle", "occurred_at": "2026-01-02T01:30:00+08:00"},
        {"record_id": "DEMO-E44", "source_type": "night", "group_ref": "DEMO-SITE-A", "member_ref": "DEMO-EVENT-4", "kind": "site", "occurred_at": "2026-01-02T02:00:00+08:00"},
        {"record_id": "DEMO-E45", "source_type": "night", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-EVENT-5", "kind": "person", "occurred_at": "2026-01-02T06:00:00+08:00"},
    ],
    "vehicle": [
        {"record_id": "DEMO-E51", "source_type": "vehicle", "group_ref": "DEMO-CAR-A", "member_ref": "DEMO-MEMBER-1"},
        {"record_id": "DEMO-E52", "source_type": "vehicle", "group_ref": "DEMO-CAR-A", "member_ref": "DEMO-MEMBER-1"},
        {"record_id": "DEMO-E53", "source_type": "vehicle", "group_ref": "DEMO-CAR-A", "member_ref": "DEMO-MEMBER-2"},
        {"record_id": "DEMO-E54", "source_type": "vehicle", "group_ref": "DEMO-CAR-B", "member_ref": "DEMO-MEMBER-3"},
        {"record_id": "DEMO-E51", "source_type": "vehicle", "group_ref": "DEMO-CAR-A", "member_ref": "DEMO-MEMBER-1"},
    ],
    "lookup": [
        {"record_id": "DEMO-E61", "source_type": "lookup", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-ACCOUNT-A", "kind": "correspondence"},
        {"record_id": "DEMO-E62", "source_type": "lookup", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-NUMBER-A", "kind": "correspondence"},
        {"record_id": "DEMO-E63", "source_type": "lookup", "group_ref": "DEMO-OBJECT-A", "member_ref": "DEMO-OBJECT-B", "kind": "record_intersection"},
    ],
}


def load_key():
    path = os.environ.get("PEIXIAN_RECORDS_KEY_FILE")
    if not path:
        raise RuntimeError("PEIXIAN_RECORDS_KEY_FILE is required")
    key = Path(path).read_text(encoding="utf-8").strip()
    if len(key) < 16:
        raise RuntimeError("records service key is invalid")
    return key


def response_for(module):
    records = copy.deepcopy(FIXTURES[module])
    return {
        "schema_version": "1.0",
        "synthetic": True,
        "module": module,
        "snapshot_id": "DEMO-SNAPSHOT-001",
        "scope": {"material_batch": "DEMO-BATCH-001", "timezone": "Asia/Shanghai", "query_scope": "embedded_fixture_only"},
        "data_status": "complete",
        "records": records,
        "returned_count": len(records),
        "total_count": len(records),
        "has_more": False,
        "missing_sources": [],
        "errors": [],
        "rule_version": "demo-v1",
        "rule_status": "demo_only",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "PeixianSyntheticRecords/1.0"

    def log_message(self, *_):
        pass

    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + load_key())

    def require_authorization(self):
        if self.authorized():
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def do_GET(self):
        if not self.require_authorization():
            return
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, {"ok": True, "synthetic": True})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if not self.require_authorization():
            return
        if self.path != "/v1/demo/records/query":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if content_type != "application/json" or length < 1 or length > MAX_BODY_BYTES:
                raise ValueError
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request, dict) or set(request) != {"module"} or request["module"] not in MODULES:
                raise ValueError
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        self.send_json(HTTPStatus.OK, response_for(request["module"]))

    def method_not_allowed(self):
        if not self.require_authorization():
            return
        self.send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

    do_PUT = method_not_allowed
    do_PATCH = method_not_allowed
    do_DELETE = method_not_allowed


def main():
    load_key()
    host = os.environ.get("PEIXIAN_RECORDS_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("PEIXIAN_RECORDS_PORT", "19462"))
    if host in ("0.0.0.0", "::"):
        raise RuntimeError("public bind addresses are forbidden")
    print("Peixian synthetic records service listening on %s:%d" % (host, port), flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
