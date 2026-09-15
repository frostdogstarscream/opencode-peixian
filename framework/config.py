"""Public project profile. No credentials, host paths or executable configuration."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"schema_version", "project_id", "display_name", "tagline", "console_port", "max_runtimes"}

def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("Project profile fields do not match schema version 1")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported project profile version")
    if not isinstance(value["project_id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,15}", value["project_id"]):
        raise ValueError("project_id must be 1-16 lowercase letters, numbers or hyphens, starting with a letter")
    for key, maximum in (("display_name", 60), ("tagline", 180)):
        text = value[key]
        if (not isinstance(text, str) or not text.strip() or len(text) > maximum
                or any(ord(c) < 32 or ord(c) == 127 for c in text)):
            raise ValueError(f"{key} must be a nonempty single-line display string")
    if type(value["console_port"]) is not int or not 1024 <= value["console_port"] <= 65535:
        raise ValueError("console_port must be an integer from 1024 to 65535")
    if type(value["max_runtimes"]) is not int or not 1 <= value["max_runtimes"] <= 4:
        raise ValueError("max_runtimes must be an integer from 1 to 4")
    return dict(value)

def load(root=ROOT):
    return validate(json.loads((Path(root) / "framework/project.json").read_text(encoding="utf-8")))

def names(profile):
    prefix = profile["project_id"]
    return {"console": prefix + "-console", "cookie": prefix.replace("-", "_") + "_session",
            "control_image": prefix + "-control:0.1.0",
            "gateway_image": prefix + "-gateway:0.1.0",
            "agent_image": prefix + "-opencode:1.18.30-managed-r1",
            "data_volume": prefix + "-control-data"}
