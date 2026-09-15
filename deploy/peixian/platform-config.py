"""One validated, secret-free configuration shared by the server and host worker."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PROXY_IMAGE = "agent-platform-proxy:nginx-1.28.0"
PROXY_UPSTREAM = "nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284"
IMAGES = {"control": "agent-platform-control:1.0.0", "gateway": "agent-platform-gateway:1.0.0",
          "agent": "peixian-opencode:1.18.30-managed-r1", "proxy": PROXY_IMAGE}
LIMITS = {"agent": {"cpus": 2.0, "memory_mib": 2048}, "gateway": {"cpus": 0.5, "memory_mib": 512},
          "relay": {"cpus": 0.5, "memory_mib": 128}}
PRODUCT = {"name": "Agent 工作台", "short_name": "Agent", "description": "对话、文件、技能与插件，在一个工作台完成。"}


class ConfigError(ValueError):
    pass


def safe_path(value, parent):
    if not isinstance(value, str) or not value or any(c in value for c in "\0\r\n,"):
        raise ConfigError("invalid_platform_path")
    candidate = Path(value).expanduser()
    candidate = candidate if candidate.is_absolute() else parent / candidate
    if any(item.is_symlink() for item in (candidate, *candidate.parents)):
        raise ConfigError("platform_path_must_not_contain_links")
    return candidate.resolve()


@dataclass(frozen=True)
class PlatformConfig:
    source: Path
    deployment_id: str
    product: dict
    public_url: str
    bind_host: str
    https_port: int
    control_port: int
    root: Path
    certificate: Path
    private_key: Path
    network_pool: str
    max_runtimes: int
    resource_limits: dict
    images: dict

    @property
    def worker_root(self):
        return self.root / "worker"

    @property
    def secrets(self):
        return self.root / "secrets"

    @property
    def control_container(self):
        return self.deployment_id + "-console"

    @property
    def control_volume(self):
        return self.deployment_id + "-control-data"

    @property
    def control_url(self):
        return "http://127.0.0.1:" + str(self.control_port)

    @property
    def compose_path(self):
        return self.root / "generated" / "compose.server.json"

    @property
    def memory_budget_mib(self):
        return 1536 + self.max_runtimes * sum(v["memory_mib"] for v in self.resource_limits.values())

    @property
    def cpu_budget(self):
        return 1 + self.max_runtimes * sum(v["cpus"] for v in self.resource_limits.values())


def load_config(path):
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ConfigError("platform_configuration_unavailable") from None
    fields = {"version", "deployment_id", "product", "public_url", "bind_host", "https_port", "control_port",
              "data_root", "tls", "network_pool", "max_runtimes", "resource_limits", "images"}
    if not isinstance(raw, dict) or set(raw) - fields or type(raw.get("version")) is not int or raw["version"] != 1:
        raise ConfigError("invalid_platform_configuration_version_or_fields")
    identity = raw.get("deployment_id", "agent-platform")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", identity):
        raise ConfigError("invalid_deployment_id")
    try:
        if not isinstance(raw.get("public_url"), str):
            raise ValueError()
        public = urlsplit(raw["public_url"])
        public_port = public.port if public.port is not None else 443
        if (public.scheme != "https" or not public.hostname or public.username or public.password or public.query
                or public.fragment or public.path not in ("", "/") or any(c.isspace() for c in raw["public_url"])):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ConfigError("public_url_requires_https_origin") from None
    ports = [raw.get("https_port", public_port), raw.get("control_port", 14090)]
    if any(type(p) is not int or not 1 <= p <= 65535 for p in ports) or ports[0] == ports[1] or ports[0] != public_port:
        raise ConfigError("invalid_or_inconsistent_server_ports")
    try:
        host = str(ipaddress.ip_address(raw.get("bind_host", "0.0.0.0")))
        pool = ipaddress.ip_network(raw.get("network_pool", "10.240.0.0/16"), strict=True)
        if pool.version != 4 or not pool.is_private or not 16 <= pool.prefixlen <= 24:
            raise ValueError()
    except (TypeError, ValueError):
        raise ConfigError("invalid_bind_host_or_network_pool") from None
    maximum = raw.get("max_runtimes", 4)
    if type(maximum) is not int or not 1 <= maximum <= 32:
        raise ConfigError("invalid_runtime_capacity")
    limits = json.loads(json.dumps(LIMITS))
    given = raw.get("resource_limits", {})
    if not isinstance(given, dict) or set(given) - set(limits):
        raise ConfigError("invalid_resource_limits")
    for name, values in given.items():
        if not isinstance(values, dict) or set(values) - {"cpus", "memory_mib"}:
            raise ConfigError("invalid_resource_limits")
        limits[name].update(values)
    for name, values in limits.items():
        if (type(values["cpus"]) not in (float, int) or not 0.1 <= values["cpus"] <= 32
                or type(values["memory_mib"]) is not int or not 128 <= values["memory_mib"] <= 65536):
            raise ConfigError("invalid_resource_limits")
    product = raw.get("product", PRODUCT)
    if (not isinstance(product, dict) or set(product) != set(PRODUCT)
            or any(not isinstance(v, str) or not v.strip() or len(v) > 200 or any(c in v for c in "\0\r\n") for v in product.values())):
        raise ConfigError("invalid_product_identity")
    supplied_images = raw.get("images", {})
    if not isinstance(supplied_images, dict):
        raise ConfigError("invalid_image_configuration")
    images = {**IMAGES, **supplied_images}
    if set(images) != set(IMAGES) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:@_-]+", v)
                                         or v.endswith(":latest") or (":" not in v and "@" not in v) for v in images.values()):
        raise ConfigError("images_require_explicit_versions")
    tls = raw.get("tls", {})
    if not isinstance(tls, dict) or set(tls) != {"certificate", "private_key"}:
        raise ConfigError("tls_certificate_and_private_key_required")
    data_root = safe_path(raw.get("data_root", "./platform-data"), source.parent)
    if data_root == Path(data_root.anchor) or data_root == source.parent:
        raise ConfigError("data_root_requires_dedicated_directory")
    return PlatformConfig(source, identity, product, raw["public_url"].rstrip("/"), host, *ports,
                          data_root,
                          safe_path(tls["certificate"], source.parent), safe_path(tls["private_key"], source.parent),
                          str(pool), maximum, limits, images)
