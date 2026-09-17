from pathlib import Path
import os
import json

from .store import Store


def configured_store():
    return Store(
        os.getenv("CONTROL_DATA", "/data"),
        os.getenv("CONTROL_KEY_FILE", "/run/secrets/control-key"),
        os.getenv("WORKER_KEY_FILE", "/run/secrets/worker-key"),
        os.getenv("ADMIN_PASSWORD_FILE", "/run/secrets/admin-password"),
        runtime_mode=os.getenv("PX_RUNTIME_MODE", "eager"),
        runtime_pool=json.loads(os.environ['PX_RUNTIME_POOL_CONFIG']) if 'PX_RUNTIME_POOL_CONFIG' in os.environ else None,
    )
