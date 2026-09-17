from pathlib import Path
import os

from .store import Store


def configured_store():
    return Store(
        os.getenv("CONTROL_DATA", "/data"),
        os.getenv("CONTROL_KEY_FILE", "/run/secrets/control-key"),
        os.getenv("WORKER_KEY_FILE", "/run/secrets/worker-key"),
        os.getenv("ADMIN_PASSWORD_FILE", "/run/secrets/admin-password"),
        runtime_mode=os.getenv("PX_RUNTIME_MODE", "eager"),
    )
