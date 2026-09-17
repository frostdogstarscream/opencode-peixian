"""PR7 policy contract; future schedulers are deliberately unavailable."""
CAPABILITY = "runtime_pool_v1"
WAIT_CAPABILITY = "runtime_pool_wait_v1"
BOUNDS = {
    "max_waiting_requests": (1000, 1, 10000),
    "capacity_wait_ttl_seconds": (1800, 30, 86400),
    "scheduler_tick_seconds": (10, 1, 60),
    "scheduler_batch": (8, 1, 64),
    "idle_timeout_seconds": (600, 60, 86400),
    "min_ready_seconds": (60, 0, 3600),
    "resume_cooldown_seconds": (60, 0, 3600),
}


def validate(value):
    fixed = {"runtime_mode": "on_demand", "capacity_wait_enabled": False, "idle_pause_enabled": False}
    if not isinstance(value, dict) or set(value) - (set(fixed) | set(BOUNDS)):
        raise ValueError("invalid_runtime_pool_policy")
    for key, expected in fixed.items():
        actual = value.get(key, expected)
        if key == "capacity_wait_enabled" and type(actual) is bool:
            continue
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError("unsupported_runtime_pool_policy")
    result = dict(fixed)
    result['capacity_wait_enabled'] = value.get('capacity_wait_enabled', False)
    for name, (default, low, high) in BOUNDS.items():
        actual = value.get(name, default)
        if type(actual) is not int or not low <= actual <= high:
            raise ValueError("invalid_runtime_pool_policy")
        result[name] = actual
    return result
