import asyncio
import json
import os
import signal
from pathlib import Path
import re
import sys
import tempfile

from fastapi import HTTPException


def specification(managed_root, identity):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
        raise HTTPException(404, "Plugin test not found")
    root = Path(managed_root)
    try:
        config = json.loads((root / "plugin-tests.json").read_text(encoding="utf-8"))
        spec = config[identity]
        if not isinstance(spec, dict) or set(spec) != {"entry", "options"} or not isinstance(spec["options"], dict):
            raise ValueError()
        plugins = (root / "plugins").resolve(strict=True)
        entry = Path(spec["entry"])
        # Refuse symlinks anywhere below the managed plugin directory.
        if not entry.is_absolute() or not entry.is_relative_to(root / "plugins"):
            raise ValueError()
        current = root / "plugins"
        if current.is_symlink():
            raise ValueError()
        for part in entry.relative_to(root / "plugins").parts:
            current = current / part
            if current.is_symlink():
                raise ValueError()
        resolved = entry.resolve(strict=True)
        if not resolved.is_relative_to(plugins) or not resolved.is_file() or entry.name != "entry.mjs":
            raise ValueError()
        relative = resolved.relative_to(plugins)
        if len(relative.parts) != 3 or relative.parts[0] != identity:
            raise ValueError()
        return {"entry": str(resolved), "options": spec["options"]}
    except KeyError:
        raise HTTPException(404, "Plugin test not found") from None
    except (OSError, ValueError, TypeError):
        raise HTTPException(409, "Plugin test configuration is unavailable") from None


async def run_plugin_test(managed_root, identity):
    spec = specification(managed_root, identity)
    bun = os.environ.get("BUN_EXECUTABLE", "/usr/local/bin/bun")
    with tempfile.TemporaryDirectory(prefix="peixian-probe-") as temporary:
        env = {"PATH": os.defpath, "HOME": temporary, "TMPDIR": temporary, "TMP": temporary,
               "TEMP": temporary, "LANG": "C.UTF-8"}
        if os.name == "nt" and "SystemRoot" in os.environ:
            env["SystemRoot"] = os.environ["SystemRoot"]
        command = ([sys.executable, "-I", "-B", str(Path(__file__).with_name("plugin_launch.py")), bun]
                   if os.name == "posix" else [bun, str(Path(__file__).with_name("plugin_probe.mjs"))])
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, cwd=temporary, env=env, start_new_session=os.name == "posix",
            )
        except OSError:
            return {"supported": True, "ok": False, "message": "Plugin test runtime unavailable"}
        try:
            async def execute():
                process.stdin.write(json.dumps(spec).encode())
                await process.stdin.drain()
                process.stdin.close()
                output = bytearray()
                while chunk := await process.stdout.read(4096):
                    output.extend(chunk)
                    if len(output) > 8192:
                        raise ValueError()
                await process.wait()
                result = json.loads(output)
                if process.returncode != 0 or set(result) != {"supported", "ok", "message"}:
                    raise ValueError()
                if not isinstance(result["supported"], bool) or not isinstance(result["ok"], bool):
                    raise ValueError()
                # Do not trust free-form output even from an approved module.
                message = ("Plugin does not export a connection test" if not result["supported"] else
                           "Connection test passed" if result["ok"] else "Connection test failed")
                return {"supported": result["supported"], "ok": result["ok"] if result["supported"] else False,
                        "message": message}
            return await asyncio.wait_for(execute(), timeout=10)
        except TimeoutError:
            return {"supported": True, "ok": False, "message": "Connection test timed out"}
        except (ValueError, OSError):
            return {"supported": True, "ok": False, "message": "Connection test failed"}
        finally:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                process.kill()
            await process.wait()
