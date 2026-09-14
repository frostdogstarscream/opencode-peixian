#!/bin/sh
set -eu
umask 077

exec python3 - "$@" <<'PY'
import json
import os
from pathlib import Path
import shutil
import sys


def fail(message):
    print("Peixian startup: " + message, file=sys.stderr)
    raise SystemExit(1)


if os.getuid() != 10001 or os.getgid() != 10001:
    fail("the runtime must use UID/GID 10001:10001")

secret_file = Path(os.environ.get("OPENCODE_PASSWORD_FILE", "/run/secrets/opencode-password"))
try:
    password = secret_file.read_text(encoding="utf-8").rstrip("\r\n")
except (OSError, UnicodeError):
    fail("the read-only password file is missing or unreadable")
if len(password) < 16 or any(char in password for char in "\r\n\0"):
    fail("the password file must contain one line with at least 16 characters")

username = os.environ.get("OPENCODE_SERVER_USERNAME", "")
if username not in ("client-a", "client-b"):
    fail("OPENCODE_SERVER_USERNAME must identify client-a or client-b")

home = Path("/home/opencode")
config_dir = home / ".config/opencode"
for directory in (
    config_dir,
    home / ".local/share/opencode",
    home / ".cache/opencode",
    home / ".local/state/opencode",
    Path("/workspace"),
):
    directory.mkdir(parents=True, exist_ok=True)
    if not os.access(directory, os.W_OK):
        fail("the instance directories are not writable by UID 10001")

# Keep the package manifest and lock beside the preinstalled dependency tree.
# OpenCode checks all three before deciding whether to install dependencies.
dependency_dir = Path("/opt/peixian/config-deps")
for name in ("package.json", "package-lock.json"):
    shutil.copyfile(dependency_dir / name, config_dir / name)
node_modules = config_dir / "node_modules"
expected_target = dependency_dir / "node_modules"
if node_modules.is_symlink():
    if node_modules.resolve() != expected_target.resolve():
        fail("the existing dependency symlink does not match this image")
elif node_modules.exists():
    fail("an unexpected dependency directory requires explicit migration")
else:
    node_modules.symlink_to(expected_target, target_is_directory=True)

# This first-stage fixture deliberately remains in no-model mode on restart.
runtime_config = Path("/opt/peixian/config/opencode.json").read_text(encoding="utf-8")
json.loads(runtime_config)
os.environ["OPENCODE_CONFIG_CONTENT"] = runtime_config
os.environ["OPENCODE_SERVER_PASSWORD"] = password
os.environ["OPENCODE_SERVER_USERNAME"] = username
os.chdir("/workspace")

arguments = sys.argv[1:]
if not arguments:
    arguments = ["serve", "--hostname", "0.0.0.0", "--port", "4096"]
os.execv("/usr/local/bin/opencode", ["/usr/local/bin/opencode", *arguments])
PY
