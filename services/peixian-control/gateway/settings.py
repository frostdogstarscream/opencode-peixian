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


def runtime_protocol_enabled():
    value = os.environ.get("PX_RUNTIME_PROTOCOL", "")
    if value not in ("", "2"):
        raise RuntimeError("Unsupported runtime protocol")
    return value == "2"


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
    runtime_protocol: bool = False
    runtime_id: str = ""
    revision: int = 0
    runtime_key: str = field(default="", repr=False)
    relay_management_key: str = field(default="", repr=False)
    control_url: str = "http://control:8080"
    relay_url: str = "http://model-relay:8081"
    activity_root: Path | None = None

    @classmethod
    def from_env(cls):
        return cls(
            workspace=Path(os.environ.get("WORKSPACE", "/workspace")),
            files_root=Path(os.environ.get("FILES_ROOT", "/files")),
            managed_root=Path(os.environ.get("MANAGED_ROOT", "/managed")),
            token=read_secret(os.environ.get("INTERNAL_TOKEN_FILE", "/run/secrets/gateway-token")),
            opencode_password=read_secret(os.environ.get("OPENCODE_PASSWORD_FILE", "/run/secrets/opencode-password")),
            opencode_url=os.environ.get("OPENCODE_URL", "http://agent:4096"),
            runtime_protocol=runtime_protocol_enabled(),
            runtime_id=os.environ.get("PX_RUNTIME_ID", ""),
            runtime_key=read_secret(os.environ.get("PX_RUNTIME_KEY_FILE", "/run/secrets/runtime-key")) if os.environ.get("PX_RUNTIME_PROTOCOL") == "2" else "",
            relay_management_key=read_secret(os.environ.get("PX_RELAY_MANAGEMENT_KEY_FILE", "/run/secrets/relay-management-key")) if os.environ.get("PX_RUNTIME_PROTOCOL") == "2" else "",
            control_url=os.environ.get("PX_CONTROL_URL", "http://control:8080"),
            relay_url=os.environ.get("PX_RELAY_URL", "http://model-relay:8081"),
            activity_root=Path(os.environ.get("PX_ACTIVITY_ROOT", "/files/.runtime-state")),
        )


@dataclass
class RelaySettings:
    runtime_id: str
    revision: int
    relay_management_key: str = field(repr=False)
    gateway_url: str = "http://gateway:8080"

    @classmethod
    def from_env(cls):
        import json
        revision = json.loads((Path(os.environ.get("MANAGED_ROOT", "/managed")) / "revision.json").read_text())
        runtime_id = os.environ.get("PX_RUNTIME_ID", "")
        if revision.get("runtime_id") != runtime_id or type(revision.get("revision")) is not int:
            raise RuntimeError("Relay revision identity is invalid")
        return cls(runtime_id, revision["revision"],
                   read_secret(os.environ.get("PX_RELAY_MANAGEMENT_KEY_FILE", "/run/secrets/relay-management-key")),
                   os.environ.get("PX_GATEWAY_URL", "http://gateway:8080"))
