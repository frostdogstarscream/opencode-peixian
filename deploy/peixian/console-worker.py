"""Single host worker for the Peixian control API. Never run in an app container."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

import httpx


module = importlib.util.spec_from_file_location("peixian_console_runtime", Path(__file__).with_name("console-runtime.py"))
runtime = importlib.util.module_from_spec(module)
module.loader.exec_module(runtime)


def report(state, job=None, code=None):
    event = {"state": state}
    if job:
        event.update(job=job["id"], runtime_action=job["action"])
    if code:
        event["code"] = code
    print(json.dumps(event), flush=True)


@contextlib.contextmanager
def host_lock(root):
    path = Path(root) / "worker.lock"
    with path.open("a+b") as handle:
        # Reading the byte itself fails on Windows while another worker owns it.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise runtime.RuntimeFailure("another_host_worker_is_running") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def budget_lock(namespace):
    if namespace is None:
        yield
        return
    runtime.check_namespace(namespace)
    # Fixed per OS user, independent of namespace/state root/checkout.
    identity = hashlib.sha256(runtime.host_identity().encode("utf-8")).hexdigest()[:24]
    root = Path(tempfile.gettempdir()) / ("peixian-framework-budget-" + identity)
    runtime.protect_root(root)
    with host_lock(root):
        yield


class Worker:
    def __init__(self, api, manager):
        self.api, self.manager = api, manager
        self.cooldown = {}

    def request(self, method, path, **kwargs):
        response = self.api.request(method, path, **kwargs)
        if response.status_code == 409:
            raise runtime.RuntimeFailure("worker_lease_lost")
        if response.status_code != 200:
            raise runtime.RuntimeFailure("control_api_unavailable")
        return response

    def download(self, digest):
        if not runtime.DIGEST.fullmatch(digest):
            raise runtime.RuntimeFailure("invalid_plugin_digest")
        output = bytearray()
        with self.api.stream("GET", "/internal/worker/packages/" + digest) as response:
            if response.status_code != 200:
                raise runtime.RuntimeFailure("plugin_download_unavailable")
            for chunk in response.iter_bytes():
                output.extend(chunk)
                if len(output) > runtime.MAX_PACKAGE:
                    raise runtime.RuntimeFailure("plugin_download_limit")
        return bytes(output)

    def once(self):
        for code in self.manager.reconcile():
            report("reconcile_failed", code=code)
        payload = self.request("POST", "/internal/worker/claim").json()
        job = payload.get("job")
        if job is None:
            return False
        if (not isinstance(job, dict) or set(job) != {"id", "uid", "action", "lease", "revision"} or
                not all(isinstance(job.get(key), str) for key in ("id", "uid", "action", "lease"))):
            raise runtime.RuntimeFailure("invalid_job_envelope")
        runtime.check_id(job["id"])
        runtime.check_id(job["uid"])
        spec = payload.get("spec")
        if not isinstance(spec, dict):
            raise runtime.RuntimeFailure("invalid_job_spec")
        stop, failed = threading.Event(), threading.Event()

        def heartbeat():
            if failed.is_set():
                raise runtime.RuntimeFailure("worker_heartbeat_failed")
            self.request("POST", "/internal/worker/jobs/" + job["id"] + "/heartbeat", json={"lease": job["lease"]})

        def keepalive():
            while not stop.wait(20):
                try:
                    heartbeat()
                except Exception:
                    failed.set()
                    return

        thread = threading.Thread(target=keepalive, daemon=True, name="peixian-worker-lease")
        thread.start()
        result = {"ok": False}
        report("claimed", job)
        try:
            remaining = self.cooldown.get(job["uid"], 0) - time.monotonic()
            if remaining > 0:
                # Keep a reclaimed lease alive without a hot claim/defer loop.
                # A future control API can use not_before for fair multi-job scheduling.
                if stop.wait(min(remaining, 300)):
                    raise runtime.Deferred()
            result = self.manager.apply(job, spec, self.download, heartbeat)
            heartbeat()
            self.cooldown.pop(job["uid"], None)
        except runtime.Deferred:
            result = {"ok": False, "deferred": True}
            self.cooldown[job["uid"]] = time.monotonic() + 300
            report("deferred", job)
        except runtime.RuntimeFailure as error:
            result = {"ok": False, "error": error.code, "rolled_back": error.rolled_back,
                      "cleanup_confirmed": error.cleanup_confirmed}
            report("failed", job, error.code)
        except Exception:
            result = {"ok": False, "error": "worker_operation_failed", "cleanup_confirmed": False}
            report("failed", job, "worker_operation_failed")
        finally:
            stop.set()
            thread.join(timeout=5)
        if failed.is_set():
            raise runtime.RuntimeFailure("worker_heartbeat_failed")
        self.request("POST", "/internal/worker/jobs/" + job["id"] + "/complete",
                     json={"lease": job["lease"], **result})
        if result.get("ok"):
            report("succeeded", job)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-url", default="http://127.0.0.1:14090")
    parser.add_argument("--key-file", type=Path, default=Path(__file__).parent / ".secrets/console-worker.key")
    parser.add_argument("--state-root", type=Path, default=Path(__file__).parent / ".runtime/console")
    parser.add_argument("--control-container", default="peixian-console")
    parser.add_argument("--agent-image", default="peixian-opencode:1.18.30-managed-r1")
    parser.add_argument("--gateway-image", default="peixian-gateway:console-r1")
    parser.add_argument("--max-runtimes", type=int, default=4)
    parser.add_argument("--namespace", help="Isolated deployment namespace; omitted keeps legacy px mode")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    url = urlsplit(args.control_url)
    if (url.scheme not in ("http", "https") or url.hostname not in ("127.0.0.1", "localhost", "::1") or
            url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        raise runtime.RuntimeFailure("control_api_must_be_local")
    try:
        key = args.key_file.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        raise runtime.RuntimeFailure("worker_key_unavailable") from None
    if len(key) < 32 or any(c in key for c in "\r\n\0"):
        raise runtime.RuntimeFailure("worker_key_invalid")
    with budget_lock(args.namespace):
        manager = runtime.RuntimeManager(args.state_root, control_container=args.control_container,
                                         agent_image=args.agent_image, gateway_image=args.gateway_image,
                                         maximum=args.max_runtimes, namespace=args.namespace)
        with host_lock(manager.root), httpx.Client(
            base_url=args.control_url.rstrip("/"), headers={"X-Worker-Key": key},
            timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10), trust_env=False, follow_redirects=False,
        ) as client:
            worker = Worker(client, manager)
            while True:
                try:
                    found = worker.once()
                    if args.once:
                        return
                    if not found:
                        time.sleep(5)
                except (httpx.HTTPError, runtime.RuntimeFailure) as error:
                    report("retry", code=error.code if isinstance(error, runtime.RuntimeFailure) else "control_api_unavailable")
                    if args.once:
                        raise SystemExit(1) from None
                    time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        report("stopped")
    except runtime.RuntimeFailure as error:
        report("failed", code=error.code)
        raise SystemExit(1) from None
