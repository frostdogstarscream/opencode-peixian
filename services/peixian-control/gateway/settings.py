from dataclasses import dataclass, field
import os
from pathlib import Path


MAX_UPLOAD = 20 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_TEXT = 1_000_000
PARSE_SECONDS = 60
PARSE_MEMORY = 384 * 1024 * 1024
MAX_ACCOUNT_UPLOADS = 1024 * 1024 * 1024


def read_secret(path):
    try:
        value = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        raise RuntimeError("Required private credential is unavailable") from None
    if not value or any(char in value for char in "\r\n\0"):
        raise RuntimeError("Required private credential is invalid")
    return value


@dataclass
class Settings:
    workspace: Path
    files_root: Path
    managed_root: Path
    token: str = field(repr=False)
    opencode_password: str = field(repr=False)
    opencode_url: str = "http://agent:4096"
    require_linux: bool = True
    upload_quota: int = MAX_ACCOUNT_UPLOADS

    @classmethod
    def from_env(cls):
        return cls(
            workspace=Path(os.environ.get("WORKSPACE", "/workspace")),
            files_root=Path(os.environ.get("FILES_ROOT", "/files")),
            managed_root=Path(os.environ.get("MANAGED_ROOT", "/managed")),
            token=read_secret(os.environ.get("INTERNAL_TOKEN_FILE", "/run/secrets/gateway-token")),
            opencode_password=read_secret(os.environ.get("OPENCODE_PASSWORD_FILE", "/run/secrets/opencode-password")),
            opencode_url=os.environ.get("OPENCODE_URL", "http://agent:4096"),
        )