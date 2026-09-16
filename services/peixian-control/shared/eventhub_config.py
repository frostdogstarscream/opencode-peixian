"""One set of bounds for deployment and Control; no schema migration required."""
BOUNDS = {
    "hub_queue": (64, 1, 256),
    "hub_idle_seconds": (10, 1, 60),
    "hub_retention_seconds": (60, 1, 300),
    "hub_reconnect_seconds": (15, 1, 30),
    "hub_shutdown_seconds": (5, 1, 5),
}


def validate(values):
    for name, (default, minimum, maximum) in BOUNDS.items():
        value = values.get(name, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Invalid event hub configuration: " + name)
    if values.get("hub_idle_seconds", 10) > values.get("hub_retention_seconds", 60):
        raise ValueError("Hub idle grace exceeds retention")
