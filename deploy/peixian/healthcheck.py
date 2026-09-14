#!/usr/bin/env python3
"""Authenticated, local-only health check. Never print credentials or responses."""

import base64
import http.client
import json
import os
from pathlib import Path
import sys


def main():
    password = Path(
        os.environ.get("OPENCODE_PASSWORD_FILE", "/run/secrets/opencode-password")
    ).read_text(encoding="utf-8").rstrip("\r\n")
    username = os.environ["OPENCODE_SERVER_USERNAME"]
    if not password or any(char in password for char in "\r\n\0"):
        return 1
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    connection = http.client.HTTPConnection("127.0.0.1", 4096, timeout=3)
    try:
        connection.request(
            "GET", "/global/health", headers={"Authorization": "Basic " + credentials}
        )
        response = connection.getresponse()
        if response.status != 200:
            return 1
        payload = json.loads(response.read(4096))
        return 0 if payload.get("healthy") is True and payload.get("version") == "1.18.30" else 1
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
