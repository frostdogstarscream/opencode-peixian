"""Python client for the Peixian console API (requires httpx==0.28.1).

Examples:
    python console_client.py --username client-a --file evidence.xlsx --message "Summarize the uploaded data."
    python console_client.py --session-id SESSION_ID --message "Continue the analysis."
    python console_client.py --abort-only SESSION_ID

An existing personal token can be supplied in PEIXIAN_CONSOLE_TOKEN. Otherwise
the program asks for the account password using getpass and keeps the session
cookie and CSRF token only in memory. Initial-password changes are interactive.
Do not pass passwords or tokens as command-line arguments.

This client connects only to the public console, never to a tenant gateway or
the native Agent. Account binding comes from login/token authentication.
SSE events are invalidation notifications; refresh /messages to obtain text.
Use a dedicated session or keep a single writer per session while run_message runs.
"""
import argparse
import asyncio
from contextlib import suppress
import getpass
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

PREFIX = "/api/console/v1"


class ConsoleError(RuntimeError):
    pass


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("Invalid resource ID")
    return value


async def sse_events(lines):
    """Decode SSE frames, including comments and multiline data fields."""
    event, data = "message", []
    async for line in lines:
        if not line:
            if data:
                yield {"event": event, "data": "\n".join(data)}
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)


class ConsoleClient:
    def __init__(self, base_url="http://127.0.0.1:14090", *, token=None, transport=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("base_url must be the HTTP/HTTPS console origin")
        self.origin = base_url.rstrip("/")
        headers = {"Origin": self.origin}
        if token:
            headers["Authorization"] = "Bearer " + token
        self.http = httpx.AsyncClient(
            base_url=self.origin, headers=headers, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(60, connect=10), transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    @staticmethod
    def check(response):
        if not 200 <= response.status_code < 300:
            # Avoid echoing response bodies, URLs, cookies or credentials in logs.
            raise ConsoleError(f"Console request failed (HTTP {response.status_code})")

    async def request(self, method, path, **kwargs):
        response = await self.http.request(method, PREFIX + path, **kwargs)
        self.check(response)
        return response.json()

    async def login(self, username, password):
        self.http.headers.pop("Authorization", None)
        result = await self.request("POST", "/auth/login", json={"username": username, "password": password})
        self.http.headers["X-CSRF-Token"] = result["csrf_token"]
        return result["user"]

    async def change_password(self, current_password, new_password):
        return await self.request("POST", "/me/password", json={
            "current_password": current_password, "password": new_password,
        })

    async def me(self):
        return (await self.request("GET", "/me"))["user"]

    async def logout(self):
        result = await self.request("POST", "/auth/logout")
        self.http.cookies.clear()
        self.http.headers.pop("Authorization", None)
        self.http.headers.pop("X-CSRF-Token", None)
        return result

    async def create_token(self, name="Python client"):
        """The returned token is private. Store it in a secret manager, never print it."""
        return await self.request("POST", "/tokens", json={"name": name})

    async def revoke_token(self, token_id):
        return await self.request("DELETE", "/tokens/" + resource_id(token_id))

    async def models(self):
        return (await self.request("GET", "/models"))["items"]

    async def files(self):
        return (await self.request("GET", "/files"))["items"]

    async def upload(self, path):
        path = Path(path)
        if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Upload must be an existing file of at most 20 MiB")
        with path.open("rb") as handle:
            return await self.request("POST", "/files", files={"file": (path.name, handle, "application/octet-stream")})

    async def text(self, file_id):
        return await self.request("GET", "/files/" + resource_id(file_id) + "/text")

    async def wait_for_file(self, file_id, timeout=90):
        async with asyncio.timeout(timeout):
            while True:
                result = await self.text(file_id)
                if result["status"] == "partial" or result.get("truncated") is True:
                    raise ConsoleError("File extraction is incomplete; split the file and upload again before referencing it")
                if result["status"] == "ready":
                    return result
                if result["status"] not in ("uploading", "queued", "parsing"):
                    raise ConsoleError("File cannot be referenced: " + result["status"])
                await asyncio.sleep(0.5)

    async def download(self, file_id, destination, *, result=False):
        """Write to an explicit local destination without trusting server filenames."""
        path = ("/results/" if result else "/files/") + resource_id(file_id) + "/download"
        destination = Path(destination)
        # Refuse to overwrite an existing file.
        with destination.open("xb") as handle:
            try:
                async with self.http.stream("GET", PREFIX + path) as response:
                    self.check(response)
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
            except BaseException:
                handle.close()
                destination.unlink(missing_ok=True)
                raise

    async def delete_file(self, file_id):
        return await self.request("DELETE", "/files/" + resource_id(file_id))

    async def sessions(self):
        return (await self.request("GET", "/sessions"))["items"]

    async def create_session(self, title="Python analysis"):
        return await self.request("POST", "/sessions", json={"title": title})

    async def messages(self, session_id):
        return (await self.request("GET", "/sessions/" + resource_id(session_id) + "/messages"))["items"]

    async def send_message(self, session_id, text, *, model_id=None, file_ids=(), skill_ids=()):
        payload = {"text": text, "file_ids": list(file_ids), "skill_ids": list(skill_ids)}
        if model_id:
            payload["model_id"] = model_id
        return await self.request("POST", "/sessions/" + resource_id(session_id) + "/messages", json=payload)

    async def abort(self, session_id):
        return await self.request("POST", "/sessions/" + resource_id(session_id) + "/abort")

    async def events(self):
        async with self.http.stream("GET", PREFIX + "/events", timeout=None) as response:
            self.check(response)
            async for event in sse_events(response.aiter_lines()):
                yield event

    async def run_message(self, session_id, text, *, timeout=180, on_update=None, **options):
        """Subscribe before sending; use persisted messages + idle state for completion.

        The returned run_id from POST is an acceptance receipt. It is not a native
        message ID and must not be used as proof that the model finished.
        Timeout or cancellation sends abort to this session before closing SSE.
        """
        prior = {value["info"]["id"] for value in await self.messages(session_id)}
        changed, connected = asyncio.Event(), asyncio.Event()
        stream_failure = []
        submitted = False

        async def listen():
            try:
                async for event in self.events():
                    if event["event"] == "change":
                        connected.set()
                        changed.set()
            except (httpx.HTTPError, ConsoleError) as error:
                stream_failure.append(type(error).__name__)
            finally:
                connected.set()

        listener = asyncio.create_task(listen())
        try:
            await asyncio.wait_for(connected.wait(), timeout=10)
            if listener.done():
                raise ConsoleError("Could not subscribe to console events")
            receipt = await self.send_message(session_id, text, **options)
            submitted = True
            if receipt.get("accepted") is not True:
                raise ConsoleError("Message was not accepted")
            async with asyncio.timeout(timeout):
                while True:
                    # Polling also recovers missed invalidation events; SSE never
                    # carries the actual message text in this console contract.
                    with suppress(TimeoutError):
                        await asyncio.wait_for(changed.wait(), timeout=1)
                    changed.clear()
                    values = await self.messages(session_id)
                    new = [value for value in values if value["info"]["id"] not in prior and value["info"]["role"] == "assistant"]
                    if on_update:
                        on_update(new)
                    if any(value["info"].get("error") for value in new):
                        raise ConsoleError("The model reported an incomplete request")
                    sessions = await self.sessions()
                    state = next((value for value in sessions if value["id"] == session_id), None)
                    if state is None:
                        raise ConsoleError("Session is no longer available")
                    completed = any(value["info"].get("time", {}).get("completed") for value in new)
                    if new and completed and state.get("status") == "idle":
                        return values
                    await asyncio.sleep(0.25)
        except BaseException:
            if submitted:
                with suppress(Exception):
                    await self.abort(session_id)
            raise
        finally:
            listener.cancel()
            with suppress(asyncio.CancelledError):
                await listener


async def main(args):
    token = os.environ.get("PEIXIAN_CONSOLE_TOKEN")
    async with ConsoleClient(args.base_url, token=token) as client:
        if token:
            user = await client.me()
        else:
            username = args.username or input("Account: ").strip()
            password = getpass.getpass("Password: ")
            user = await client.login(username, password)
            if user.get("must_change_password"):
                new_password = getpass.getpass("New password (12+ characters): ")
                if new_password != getpass.getpass("Repeat new password: "):
                    raise ConsoleError("Passwords do not match")
                await client.change_password(password, new_password)
            password = None
        if args.abort_only:
            await client.abort(args.abort_only)
            print("Abort requested.")
            return
        available = await client.models()
        if not available:
            raise ConsoleError("No administrator-authorized model is available")
        model_id = args.model_id or available[0]["id"]
        if model_id not in {model["id"] for model in available}:
            raise ConsoleError("Selected model is not authorized")
        file_ids = []
        for path in args.file:
            uploaded = await client.upload(path)
            parsed = await client.wait_for_file(uploaded["id"])
            file_ids.append(uploaded["id"])
            print("Uploaded file parsed; status:", parsed["status"])
        session_id = args.session_id or (await client.create_session())["id"]
        print("Session ID:", session_id)
        messages = await client.run_message(
            session_id, args.message, model_id=model_id, file_ids=file_ids, skill_ids=args.skill_id, timeout=args.timeout,
        )
        for message in messages:
            if message["info"]["role"] == "assistant":
                for part in message["parts"]:
                    if part["type"] == "text":
                        print(part["text"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:14090")
    parser.add_argument("--username")
    parser.add_argument("--model-id")
    parser.add_argument("--session-id")
    parser.add_argument("--file", action="append", default=[], type=Path)
    parser.add_argument("--skill-id", action="append", default=[])
    parser.add_argument("--message", default="Summarize the supplied data and cite its sources.")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--abort-only")
    arguments = parser.parse_args()
    try:
        asyncio.run(main(arguments))
    except KeyboardInterrupt:
        print("Cancelled; an accepted run was asked to stop.")
    except (ConsoleError, TimeoutError, ValueError, OSError, httpx.HTTPError) as error:
        # Exception details from HTTP clients may include URLs; log only safe types.
        print("Request did not complete:", str(error) if isinstance(error, ConsoleError) else type(error).__name__)
        raise SystemExit(1) from None
