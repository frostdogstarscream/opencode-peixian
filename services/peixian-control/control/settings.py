from pathlib import Path
import os
import re
from http.cookies import CookieError, SimpleCookie

from .store import Store


def configured_store():
    return Store(
        os.getenv("CONTROL_DATA", "/data"),
        os.getenv("CONTROL_KEY_FILE", "/run/secrets/control-key"),
        os.getenv("WORKER_KEY_FILE", "/run/secrets/worker-key"),
        os.getenv("ADMIN_PASSWORD_FILE", "/run/secrets/admin-password"),
    )


def configured_cookie_name():
    """Capture a server-owned cookie name before the application can start."""
    name = os.getenv("CONSOLE_COOKIE_NAME", "px_session")
    if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", name):
        raise ValueError("CONSOLE_COOKIE_NAME must be an ASCII cookie token of 1 to 128 characters")
    try:
        cookie = SimpleCookie()
        cookie[name] = "validation"
    except CookieError:
        raise ValueError("CONSOLE_COOKIE_NAME must not be a reserved cookie attribute") from None
    return name


def configured_runtime_namespace():
    namespace = os.getenv("RUNTIME_NAMESPACE")
    if namespace is not None and not re.fullmatch(r"[a-z][a-z0-9-]{0,15}", namespace):
        raise ValueError("RUNTIME_NAMESPACE must match [a-z][a-z0-9-]{0,15}")
    return namespace
