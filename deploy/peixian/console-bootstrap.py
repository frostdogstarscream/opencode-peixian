"""Initialize local control credentials without printing or replacing secrets."""
import argparse
import os
from pathlib import Path
import secrets
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent

def initialize(root=ROOT):
    private = root / ".secrets"
    private.mkdir(exist_ok=True)
    files = {
        "console-control.key": lambda: Fernet.generate_key().decode(),
        "console-worker.key": lambda: secrets.token_urlsafe(48),
        "console-admin.password": lambda: secrets.token_urlsafe(24),
    }
    for name, generate in files.items():
        path = private / name
        if path.is_symlink():
            raise ValueError("Credential path cannot be a link")
        if path.exists():
            if len(path.read_text().strip()) < 24:
                raise ValueError("Existing credential is invalid; it was preserved")
            continue
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(generate() + "\n")
    (root / ".runtime/console").mkdir(parents=True, exist_ok=True)
    print("Console credentials initialized; existing credentials preserved.")
    print("Administrator username: admin")
    print("Initial password file: " + str(private / "console-admin.password"))

if __name__ == "__main__":
    initialize()
