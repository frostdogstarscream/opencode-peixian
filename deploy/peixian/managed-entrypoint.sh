#!/bin/sh
set -eu
exec python3 - <<'PY'
import json
import os
from pathlib import Path
import sys

def fail():
    print("Managed runtime configuration is unavailable", file=sys.stderr)
    raise SystemExit(1)

try:
    if os.getuid() != 10001 or os.getgid() != 10001:
        fail()
    root = Path("/managed")
    config = json.loads((root / "opencode.json").read_text(encoding="utf-8"))
    revision = json.loads((root / "revision.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(revision["revision"], int) or revision["revision"] < 1:
        fail()
    password = Path("/run/secrets/opencode-password").read_text(encoding="utf-8").rstrip("\r\n")
    if len(password) < 16 or any(c in password for c in "\r\n\0"):
        fail()
    for directory in ("/home/opencode/.config", "/home/opencode/.local/share", "/home/opencode/.cache", "/home/opencode/.local/state"):
        Path(directory).mkdir(parents=True, exist_ok=True)
except (OSError, ValueError, KeyError, TypeError):
    fail()

for key in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT", "OPENCODE_PERMISSION"):
    os.environ.pop(key, None)
os.environ["PEIXIAN_MANAGED_ROOT"] = "/managed"
os.environ["OPENCODE_SERVER_USERNAME"] = "opencode"
os.environ["OPENCODE_SERVER_PASSWORD"] = password
os.chdir("/workspace")
os.execv("/usr/local/bin/opencode", ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"])
PY
