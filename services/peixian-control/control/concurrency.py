"""Single-process resource budgets. No process-local counter is a business Run."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial, wraps
import inspect
import os
import time

from fastapi import HTTPException


DEFAULTS = {
    "http_connections": 64, "http_keepalive": 16,
    "sse_viewers": 128, "sse_per_account": 4, "sse_owners": 64,
    "sse_heartbeat_seconds": 15, "sse_renew_seconds": 5, "sse_owner_ttl_seconds": 20,
    "auth_recheck_seconds": 2, "downloads": 8,
    "db_workers": 8, "db_queue": 32, "db_queue_seconds": 1, "db_busy_ms": 1000,
    "crypto_workers": 2, "crypto_queue": 16, "crypto_queue_seconds": 2,
    "login_capacity": 4096, "login_ttl_seconds": 300,
    "login_rate": 10, "login_burst": 50, "login_source_rate": 5, "login_source_burst": 50,
}


def settings():
    result = {}
    for name, default in DEFAULTS.items():
        raw = os.getenv("PX_" + name.upper(), str(default))
        try:
            value = int(raw)
        except ValueError:
            raise ValueError("Invalid concurrency configuration: " + name) from None
        ceiling = 65536 if name == "login_capacity" else 1000 if name == "db_busy_ms" else 4096
        if not 1 <= value <= ceiling:
            raise ValueError("Invalid concurrency configuration: " + name)
        result[name] = value
    if (result["http_keepalive"] > result["http_connections"]
            or result["sse_per_account"] > result["sse_viewers"]
            or result["sse_renew_seconds"] * 2 >= result["sse_owner_ttl_seconds"]
            or result["auth_recheck_seconds"] > 2):
        raise ValueError("Inconsistent concurrency configuration")
    return result


def overloaded(message="服务繁忙，请稍后重试", seconds=1):
    return HTTPException(503, message, headers={"Retry-After": str(seconds)})


class WorkPool:
    """Bound both queued and running work; cancellation does not release a busy thread."""
    def __init__(self, workers, queue, wait_seconds, name):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="px-" + name)
        self.slots = asyncio.Semaphore(workers)
        self.capacity = workers + queue
        self.wait_seconds = wait_seconds
        self.outstanding = 0
        self.futures = set()
        self.closed = False
        self.rejected = 0

    async def run(self, fn, *args, **kwargs):
        if self.closed or self.outstanding >= self.capacity:
            self.rejected += 1
            raise overloaded()
        self.outstanding += 1
        try:
            await asyncio.wait_for(self.slots.acquire(), self.wait_seconds)
        except BaseException as exc:
            self.outstanding -= 1
            if isinstance(exc, TimeoutError):
                self.rejected += 1
                raise overloaded() from None
            raise
        if self.closed:
            self.slots.release()
            self.outstanding -= 1
            raise overloaded()
        try:
            future = asyncio.get_running_loop().run_in_executor(self.executor, partial(fn, *args, **kwargs))
        except BaseException:
            self.slots.release()
            self.outstanding -= 1
            raise
        self.futures.add(future)
        def finished(done):
            self.futures.discard(done)
            self.outstanding -= 1
            self.slots.release()
            # Consume an exception even if the HTTP request was cancelled.
            if not done.cancelled():
                done.exception()
        future.add_done_callback(finished)
        return await asyncio.shield(future)

    async def close(self):
        self.closed = True
        if self.futures:
            await asyncio.wait(tuple(self.futures), timeout=5)
        self.executor.shutdown(wait=False, cancel_futures=False)


def blocking_endpoint(app, *, json_body=False, upload=False, hash_password=False):
    """Read ASGI input on its loop, then execute the entire synchronous business block."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @wraps(fn)
        async def endpoint(*args, **kwargs):
            if json_body or upload:
                values = signature.bind(*args, **kwargs).arguments
                request = values["request"]
                if json_body:
                    request.state.json_body = await request.json()
                if hash_password:
                    from .app import password_valid, body_fields
                    data = request.state.json_body
                    if not isinstance(data, dict):
                        body_fields(data, ())
                    password = password_valid(data.get("password"))
                    request.state.password_hash = await app.state.crypto_work.run(app.state.store.passwords.hash, password)
                if upload:
                    request.state.upload_body = await values["file"].read(20 * 1024 * 1024 + 1)
            return await app.state.db_work.run(fn, *args, **kwargs)
        return endpoint
    return decorate


@dataclass
class Bucket:
    tokens: float
    touched: float


class LoginLimiter:
    """Loop-owned bounded state; active bans are never evicted to admit new keys."""
    def __init__(self, config, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.attempts = {}
        self.sources = {}
        self.global_bucket = Bucket(config["login_burst"], clock())

    def _take(self, bucket, rate, burst, current):
        bucket.tokens = min(burst, bucket.tokens + max(0, current - bucket.touched) * rate)
        bucket.touched = current
        if bucket.tokens < 1:
            raise HTTPException(429, "尝试次数过多，请稍后重试", headers={"Retry-After": "1"})
        bucket.tokens -= 1

    def check(self, source, username):
        current, config = self.clock(), self.config
        ttl = config["login_ttl_seconds"]
        # State is capped, so this scan has a fixed upper bound.
        for key, stamps in list(self.attempts.items()):
            active = [stamp for stamp in stamps if current - stamp < ttl]
            if active:
                self.attempts[key] = active
            else:
                del self.attempts[key]
        for key, bucket in list(self.sources.items()):
            if current - bucket.touched >= ttl:
                del self.sources[key]
        self._take(self.global_bucket, config["login_rate"], config["login_burst"], current)
        key = (source, username)
        if ((key not in self.attempts and len(self.attempts) >= config["login_capacity"])
                or (source not in self.sources and len(self.sources) >= config["login_capacity"])):
            raise overloaded(seconds=5)
        bucket = self.sources.setdefault(source, Bucket(config["login_source_burst"], current))
        self._take(bucket, config["login_source_rate"], config["login_source_burst"], current)
        stamps = self.attempts.setdefault(key, [])
        if len(stamps) >= 10:
            retry = max(1, int(ttl - (current - stamps[0])) + 1)
            raise HTTPException(429, "尝试次数过多，请稍后重试", headers={"Retry-After": str(retry)})
        stamps.append(current)

    def success(self, source, username):
        self.attempts.pop((source, username), None)
