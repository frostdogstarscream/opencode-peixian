"""Ephemeral real Control for browser auth acceptance, no Worker or model service.
Run only inside an isolated test container with a loopback host port.
All keys/database are generated in a temporary directory and removed on exit.
"""
import os
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet
import uvicorn
from control.store import Store
from control.app import create_app

PASSWORD = "synthetic-alignment-password-123"

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="alignment-auth-") as folder:
        root = Path(folder)
        for name, value in (("key", Fernet.generate_key()), ("worker", os.urandom(48).hex().encode()), ("admin", PASSWORD.encode())):
            (root / name).write_bytes(value)
            (root / name).chmod(0o600)
        store = Store(root / "db", root / "key", root / "worker", root / "admin", runtime_mode="on_demand")
        store.create_user("alignment-manager", PASSWORD, role="admin")
        store.create_user("alignment-user", PASSWORD)
        app = create_app(store)
        uvicorn.run(app, host="0.0.0.0", port=8080, access_log=False)
