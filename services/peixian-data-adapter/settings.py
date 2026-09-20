import os
from pathlib import Path


def setting(name: str, default: str = ""):
    path = os.environ.get(name + "_FILE")
    if path:
        value = Path(path).read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError(name + " secret file is empty")
        return value
    return os.environ.get(name, default)
