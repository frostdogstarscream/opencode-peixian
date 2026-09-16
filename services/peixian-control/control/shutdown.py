"""Bounded observation of owned cleanup; timeout never means resources were released."""
import asyncio
import time


class ShutdownError(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__("shutdown_incomplete")


async def join_owned(task):
    cancellation = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except Exception:
            break
    if cancellation is not None:
        # Retrieve any cleanup failure, but preserve the caller's cancellation.
        if not task.cancelled():
            task.exception()
        raise cancellation
    return task.result()


class Shutdown:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds
        self.tasks = []
        self.report = {"stages": [], "unfinished": 0}

    async def stage(self, name, tasks, seconds):
        tasks = list(dict.fromkeys(tasks))
        self.tasks.extend(tasks)
        # Retrieve late exceptions without removing the owned task reference.
        for task in tasks:
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        if tasks:
            await asyncio.wait(tasks, timeout=max(0, min(seconds, self.deadline - time.monotonic())))
        pending = sum(not task.done() for task in tasks)
        errors = []
        for task in tasks:
            if not task.done():
                continue
            if task.cancelled():
                errors.append("cancelled")
            elif task.exception() is not None:
                errors.append("timeout" if isinstance(task.exception(), TimeoutError) else "close_failed")
        self.report["stages"].append({"resource": name, "pending": pending,
            "errors": sorted(set(errors)), "result": "incomplete" if pending or errors else "done"})

    def finish(self):
        self.report["unfinished"] = sum(not task.done() for task in set(self.tasks))
        if any(stage["result"] != "done" for stage in self.report["stages"]):
            raise ShutdownError(self.report)
        return self.report
