"""New N1 application shutdown tests; dependencies are synthetic, no live deployment."""
import asyncio
from types import SimpleNamespace

import pytest

from control.app import shutdown_app
from control.shutdown import ShutdownError


def application(failed=None, block=None):
    calls = []
    release = asyncio.Event()
    class Component:
        def __init__(self, name):
            self.name = name
            self.futures = set()
        def stop_admission(self):
            calls.append("admission_stopped")
        async def close(self):
            calls.append(self.name)
            if self.name == block:
                await release.wait()
            if self.name == failed:
                raise ValueError("synthetic-secret-must-not-appear")
        aclose = close
    names = ("safety", "stream_registry", "http", "stream_http", "download_http", "crypto_work", "db_work")
    state = SimpleNamespace(**{name: Component(name) for name in names}, limits={"hub_shutdown_seconds": .05})
    return SimpleNamespace(state=state), calls, release


@pytest.mark.parametrize("failed", ["safety", "stream_registry", "http", "crypto_work"])
def test_failure_does_not_skip_independent_resources(failed):
    async def run():
        app, calls, _ = application(failed)
        with pytest.raises(ShutdownError):
            await shutdown_app(app)
        assert calls == ["admission_stopped", "safety", "stream_registry", "http", "stream_http", "download_http", "crypto_work", "db_work"]
        assert "synthetic-secret" not in str(app.state.shutdown.report)
        assert app.state.shutdown.report["unfinished"] == 0
    asyncio.run(run())


def test_cancellation_is_reported_after_bounded_cleanup():
    async def run():
        app, calls, release = application(block="safety")
        task = asyncio.create_task(shutdown_app(app))
        while "safety" not in calls:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "db_work" in calls
        assert app.state.shutdown.report["unfinished"] == 1
        assert not app.state.shutdown.tasks[0].done()
        release.set()
        await app.state.shutdown.tasks[0]
    asyncio.run(run())


def test_repeated_shutdown_uses_same_result_and_tasks():
    async def run():
        app, calls, _ = application()
        await asyncio.gather(shutdown_app(app), shutdown_app(app))
        assert calls.count("db_work") == 1
        assert app.state.shutdown.report["unfinished"] == 0
    asyncio.run(run())


def test_lifespan_preserves_original_error_and_attempts_cleanup(monkeypatch):
    from control.app import create_app
    from control.runtime_security import SafetyCoordinator
    monkeypatch.setattr(SafetyCoordinator, "start", lambda self: None)
    async def run():
        app = create_app(SimpleNamespace(maintenance_status=lambda: {}, schema_version=lambda: 4))
        original = LookupError("original application error")
        with pytest.raises(LookupError) as caught:
            async with app.router.lifespan_context(app):
                async def fail():
                    raise RuntimeError("synthetic component failure")
                app.state.safety.close = fail
                raise original
        assert caught.value is original
        assert app.state.http.is_closed and app.state.stream_http.is_closed and app.state.download_http.is_closed
        assert app.state.db_work.closed and app.state.crypto_work.closed
        assert app.state.shutdown.report["stages"][0]["errors"] == ["close_failed"]
        await app.state.safety.http.aclose()
    asyncio.run(run())
