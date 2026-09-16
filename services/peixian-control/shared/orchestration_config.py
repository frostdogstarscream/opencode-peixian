"""Versioned, non-secret single-host orchestration settings shared with deployment tools."""
import os


BOUNDS = {
    "worker_lease_seconds": (90, 30, 300),
    "worker_heartbeat_seconds": (20, 5, 60),
    "worker_heartbeat_timeout_seconds": (5, 1, 10),
    "defer_seconds": (15, 1, 60),
    "gate_probe_seconds": (2, 1, 2),
    "reconcile_seconds": (30, 5, 120),
    "reconcile_batch": (4, 1, 16),
    "observation_ttl_seconds": (60, 10, 120),
    "receipt_retention_seconds": (604800, 86400, 2592000),
    "apply_defer_max_seconds": (300, 15, 900),
    "drain_alert_seconds": (900, 60, 3600),
    "security_permit_ttl_seconds": (4, 2, 4),
    "security_renew_seconds": (1, 1, 2),
    "security_watchdog_ms": (100, 20, 250),
    "security_request_seconds": (1, 1, 2),
    "security_connections": (4, 1, 8),
    "cancel_observe_seconds": (10, 1, 30),
    "gate_observation_seconds": (3, 1, 5),
}
DEFAULTS = {name: item[0] for name, item in BOUNDS.items()}
ENV_PREFIX = "PX_R2_"


def validate(value):
    if not isinstance(value, dict) or set(value) - set(BOUNDS):
        raise ValueError("invalid_orchestration_configuration")
    result = {**DEFAULTS, **value}
    for name, number in result.items():
        if type(number) is not int or not BOUNDS[name][1] <= number <= BOUNDS[name][2]:
            raise ValueError("invalid_orchestration_configuration")
    if (result["worker_heartbeat_seconds"] * 3 > result["worker_lease_seconds"]
            or result["worker_heartbeat_timeout_seconds"] >= result["worker_heartbeat_seconds"]
            or result["security_renew_seconds"] + result["security_request_seconds"] >= result["security_permit_ttl_seconds"]
            or result["gate_observation_seconds"] >= result["observation_ttl_seconds"]
            or result["apply_defer_max_seconds"] > result["drain_alert_seconds"]):
        raise ValueError("inconsistent_orchestration_configuration")
    return result


def from_environment(environ=None):
    environ = os.environ if environ is None else environ
    supplied = {}
    for name in BOUNDS:
        raw = environ.get(ENV_PREFIX + name.upper())
        if raw is not None:
            if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
                raise ValueError("invalid_orchestration_environment")
            supplied[name] = int(raw)
    return validate(supplied)


def environment(value):
    return {ENV_PREFIX + key.upper(): str(number) for key, number in validate(value).items()}
