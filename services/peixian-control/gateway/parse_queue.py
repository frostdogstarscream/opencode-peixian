import asyncio
import json
import os
import signal
from pathlib import Path
import sys
import tempfile

from .settings import PARSE_SECONDS
from .storage import SUPPORTED


class ParseQueue:
    def __init__(self, store):
        self.store = store
        self.queue = asyncio.Queue()
        self.pending = set()
        self.task = None
        self.process = None
        self.admission = None
        self.activities = {}

    async def start(self):
        for item in self.store.list():
            if item["status"] in ("queued", "parsing"):
                self.store.update(item["id"], status="queued")
                self.enqueue(item["id"])
        self.task = asyncio.create_task(self.run())

    def enqueue(self, identity):
        if identity not in self.pending:
            self.pending.add(identity)
            self.queue.put_nowait(identity)
            if self.admission:
                self.activities[identity] = self.admission.register("parse_queued", resource=identity)

    async def cancel(self):
        identities = list(self.pending)
        await self.stop()
        for identity in identities:
            try:
                self.store.update(identity, status="failed", error="runtime_cancelled")
            except FileNotFoundError:
                pass
            if self.admission:
                self.admission.finish(self.activities.pop(identity, None))
        self.pending.clear()
        self.queue = asyncio.Queue()
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.process and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()

    async def bounded_output(self, process):
        output = bytearray()
        while chunk := await process.stdout.read(65536):
            output.extend(chunk)
            if len(output) > 12 * 1024 * 1024:
                raise ValueError("parser_output_limit")
        await process.wait()
        if process.returncode != 0:
            raise ValueError("parser_failed")
        return json.loads(output)

    async def parse_one(self, identity):
        metadata = self.store.metadata(identity)
        if metadata["extension"] not in SUPPORTED:
            self.store.update(identity, status="unsupported")
            return
        self.store.update(identity, status="parsing", error=None)
        source = self.store.source_path(identity)
        with tempfile.TemporaryDirectory(prefix="peixian-parse-") as temporary:
            env = {
                "PATH": os.defpath, "LANG": "C.UTF-8", "HOME": temporary,
                "TMPDIR": temporary, "TMP": temporary, "TEMP": temporary,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            # Required for Python subprocess startup on Windows test hosts only.
            if os.name == "nt" and "SystemRoot" in os.environ:
                env["SystemRoot"] = os.environ["SystemRoot"]
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-B", str(Path(__file__).with_name("parser.py")), str(source), metadata["extension"],
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL, cwd=temporary, env=env, start_new_session=os.name == "posix",
            )
            try:
                result = await asyncio.wait_for(self.bounded_output(self.process), PARSE_SECONDS)
                if not isinstance(result, dict) or result.get("status") not in ("ready", "partial", "no_text", "unsupported", "failed"):
                    raise ValueError("invalid_parser_output")
                self.store.write_json(identity + "/result.json", result)
                self.store.update(
                    identity, status=result["status"], truncated=bool(result.get("truncated")),
                    error=result.get("error"), warnings=result.get("warnings", []),
                )
            finally:
                if os.name == "posix":
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif self.process.returncode is None:
                    self.process.kill()
                await self.process.wait()
                self.process = None

    async def run(self):
        while True:
            identity = await self.queue.get()
            activity = self.activities.get(identity)
            if self.admission and activity in self.admission.activities:
                self.admission.activities[activity].kind = "parse_running"
                self.admission.activities[activity].task = asyncio.current_task()
            try:
                await self.parse_one(identity)
            except asyncio.CancelledError:
                try:
                    self.store.update(identity, status="queued")
                except FileNotFoundError:
                    pass
                raise
            except FileNotFoundError:
                pass
            except TimeoutError:
                self.store.update(identity, status="failed", error="parse_timeout")
            except Exception:
                try:
                    self.store.update(identity, status="failed", error="parse_error")
                except FileNotFoundError:
                    pass
            finally:
                self.pending.discard(identity)
                if self.admission:
                    self.admission.finish(self.activities.pop(identity, None))
                self.queue.task_done()
