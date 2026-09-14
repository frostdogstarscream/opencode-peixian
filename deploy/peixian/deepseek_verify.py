"""Bounded, real DeepSeek acceptance through OpenCode. Uses only synthetic data.

Per client: one short answer and one read-tool task, without model-request retries.
The live relay must already be deployed. This script never configures or starts it.
"""

import argparse
import asyncio
import hashlib
import json
import posixpath
import re
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

import httpx

from verify import NAMES, PORTS, ROOT, Verification


class LiveVerification(Verification):
    def __init__(self, args):
        super().__init__(argparse.Namespace(version="1.18.30", lifecycle=False))
        self.live_args = args
        self.keys = [(ROOT / ".secrets" / f"{name}.deepseek-key").read_text(encoding="utf-8").rstrip("\r\n") for name in NAMES]
        if not all(self.keys) or any(any(char in key for char in "\r\n\0") for key in self.keys):
            raise ValueError("Both per-client DeepSeek key files must contain one nonempty line")
        self.report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "run_id": uuid.uuid4().hex,
            "provider_id": args.provider,
            "model_id": args.model,
            "status": "failed",
            "checks": [],
            "prompt_requests": {name: 0 for name in NAMES},
            "per_client_prompt_budget": 2,
            "scope": "One short answer and one synthetic-file read task per client; model requests are not retried by this script.",
            "not_verified": ["Self-hosted vLLM", "Business data or analysis skills", "Production workload, sustained concurrency or long-context quality"],
            "config_sha256": {},
        }
        for relative in ("compose.yaml", "compose.deepseek.yaml", "config/deepseek.json"):
            path = ROOT / relative
            if path.is_file():
                self.report["config_sha256"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()

    def redact(self, value):
        value = super().redact(value)
        for key in getattr(self, "keys", []):
            value = value.replace(key, "[REDACTED]")
        return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", value)

    def no_key_leak(self, label, data):
        serialized = json.dumps(data, ensure_ascii=False)
        self.check(label, not any(key in serialized for key in self.keys))

    async def run_live(self):
        model_ref = {"providerID": self.live_args.provider, "modelID": self.live_args.model}
        expected_model = f"{self.live_args.provider}/{self.live_args.model}"
        async with AsyncExitStack() as stack:
            clients = {name: await stack.enter_async_context(httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{PORTS[name]}", auth=(name, self.passwords[name]),
                trust_env=False, timeout=httpx.Timeout(self.live_args.timeout, connect=10),
            )) for name in NAMES}
            sessions = {}
            contents = {name: f"FILE_{name.replace('-', '_')}_{uuid.uuid4().hex[:16]}" for name in NAMES}
            answers = {name: f"REPLY_{name.replace('-', '_')}_{uuid.uuid4().hex[:16]}" for name in NAMES}
            file_path = f"/workspace/.peixian-deepseek/{self.report['run_id']}/marker.txt"
            self.report["synthetic_records"] = {}
            for name in NAMES:
                await self.health(clients[name])
                configuration = await self.request(clients[name], "GET", "/config", params={"directory": "/workspace"})
                providers = await self.request(clients[name], "GET", "/provider", params={"directory": "/workspace"})
                self.no_key_leak(f"{name}: config response contains no real DeepSeek key", configuration)
                self.no_key_leak(f"{name}: provider response contains no real DeepSeek key", providers)
                self.check(f"{name}: default model is configured DeepSeek Flash", configuration.get("model") == expected_model and configuration.get("small_model") == expected_model, {"model": configuration.get("model"), "small_model": configuration.get("small_model")})
                provider = next((entry for entry in providers.get("all", []) if entry.get("id") == self.live_args.provider), {})
                self.check(f"{name}: configured provider/model are available and connected", self.live_args.provider in providers.get("connected", []) and self.live_args.model in provider.get("models", {}))
                for other in NAMES:
                    if other == name:
                        continue
                    response = await clients[name].get("/session", params={"directory": "/workspace"}, auth=(other, self.passwords[other]))
                    self.check(f"{name}: rejects other client's credentials in live mode", response.status_code in (401, 403), {"status": response.status_code})
                for label, auth in (("anonymous", None), ("wrong password", (name, "synthetic-wrong-password"))):
                    response = await clients[name].get("/session", params={"directory": "/workspace"}, auth=auth)
                    self.check(f"{name}: rejects {label} in live mode", response.status_code in (401, 403))
                container = await asyncio.to_thread(self.container, name)
                result = await asyncio.to_thread(self.python, container["Id"],
                    "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(sys.argv[2],encoding='utf-8'); print(json.dumps({'written':True}))", file_path, contents[name])
                self.check(f"{name}: own synthetic tool file created", result.get("written"))
                locations = await self.request(clients[name], "GET", "/path", params={"directory": "/workspace"})
                relative = posixpath.relpath(file_path, locations.get("worktree", "/workspace"))
                rules = [{"permission": "*", "pattern": "*", "action": "deny"}]
                sessions[name] = {}
                for task in ("answer", "tool"):
                    permission = rules if task == "answer" else rules + [
                        {"permission": "read", "pattern": relative, "action": "allow"},
                        {"permission": "read", "pattern": file_path, "action": "allow"},
                    ]
                    session = await self.request(clients[name], "POST", "/session", params={"directory": "/workspace"}, json={
                        "title": f"SYNTHETIC-DEEPSEEK-{name}-{task}-{self.report['run_id']}",
                        "permission": permission,
                    })
                    sessions[name][task] = session["id"]
                self.report["synthetic_records"][name] = {"sessions": sessions[name], "file": file_path, "content_sha256": hashlib.sha256(contents[name].encode()).hexdigest()}

            ready = {name: asyncio.Event() for name in NAMES}
            events = {name: [] for name in NAMES}
            known_ids = {identifier for group in sessions.values() for identifier in group.values()}
            async def collect(name):
                async with clients[name].stream("GET", "/global/event", timeout=None) as response:
                    response.raise_for_status()
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise RuntimeError("Expected SSE response")
                    ready[name].set()
                    data = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        if not line and data:
                            event = json.loads("\n".join(data))
                            data = []
                            serialized = json.dumps(event, ensure_ascii=False)
                            if any(identifier in serialized for identifier in known_ids):
                                events[name].append(event)
            tasks = {name: asyncio.create_task(collect(name)) for name in NAMES}
            try:
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready.values())), timeout=30)
                self.report["responses"] = {}
                for name in NAMES:
                    self.report["responses"][name] = {}
                    for task in ("answer", "tool"):
                        if task == "answer":
                            prompt = f"Reply with exactly this verification token and nothing else: {answers[name]}. Do not use any tools."
                        else:
                            prompt = f"Call the read tool exactly once for the file {file_path}, then reply with only its text contents. Do not read other files, use other tools, or guess the contents."
                        identifier = sessions[name][task]
                        self.report["prompt_requests"][name] += 1
                        self.check(f"{name}: prompt budget respected ({task})", self.report["prompt_requests"][name] <= 2)
                        print(f"MODEL {name} {task}: one request, no script retry", flush=True)
                        try:
                            response = await clients[name].post(f"/session/{identifier}/message", params={"directory": "/workspace"}, json={
                                "model": model_ref, "parts": [{"type": "text", "text": prompt}],
                            })
                            response.raise_for_status()
                            result = response.json()
                            self.no_key_leak(f"{name}: {task} response contains no real key", result)
                            if result.get("info", {}).get("error"):
                                error = result["info"]["error"]
                                raise RuntimeError(f"Model returned an error ({self.redact(json.dumps(error))[:500]})")
                        except Exception:
                            try:
                                abort = await clients[name].post(f"/session/{identifier}/abort", params={"directory": "/workspace"}, timeout=10)
                                self.report.setdefault("aborts", []).append({"client": name, "session_id": identifier, "status": abort.status_code})
                            except httpx.HTTPError:
                                self.report.setdefault("aborts", []).append({"client": name, "session_id": identifier, "status": "request_failed"})
                            raise
                        history = await self.request(clients[name], "GET", f"/session/{identifier}/message", params={"directory": "/workspace"})
                        self.no_key_leak(f"{name}: {task} history contains no real key", history)
                        assistant = [message for message in history if message.get("info", {}).get("role") == "assistant"]
                        self.check(f"{name}: {task} uses requested model without reported error", bool(assistant) and all(message["info"].get("providerID") == self.live_args.provider and message["info"].get("modelID") == self.live_args.model and not message["info"].get("error") for message in assistant))
                        parts = [part for message in assistant for part in message.get("parts", [])]
                        texts = [part.get("text", "") for part in parts if part.get("type") == "text"]
                        text = "\n".join(texts).strip()
                        target = answers[name] if task == "answer" else contents[name]
                        other = "client-b" if name == "client-a" else "client-a"
                        self.check(f"{name}: {task} has a real short answer with its own marker", target in text and len(text) <= 600 and answers[other] not in text and contents[other] not in text)
                        tool_parts = [part for part in parts if part.get("type") == "tool"]
                        if task == "answer":
                            self.check(f"{name}: short answer executed no tools", not tool_parts)
                        if task == "tool":
                            self.check(f"{name}: exactly one read tool completed on its own file", len(tool_parts) == 1 and tool_parts[0].get("tool") == "read" and tool_parts[0].get("state", {}).get("status") == "completed" and tool_parts[0]["state"].get("input", {}).get("filePath") == file_path)
                            self.check(f"{name}: completed read output contains own file marker", contents[name] in tool_parts[0]["state"].get("output", "") and contents[other] not in tool_parts[0]["state"].get("output", ""))
                        self.report["responses"][name][task] = {
                            "session_id": identifier, "text": text,
                            "assistant_message_ids": [message["info"]["id"] for message in assistant],
                            "tokens": [message["info"].get("tokens") for message in assistant],
                            "tool_parts": [{"id": part.get("id"), "call_id": part.get("callID"), "tool": part.get("tool"), "status": part.get("state", {}).get("status"), "input": part.get("state", {}).get("input"), "output_sha256": hashlib.sha256(part.get("state", {}).get("output", "").encode()).hexdigest(), "output_contains_expected_marker": contents[name] in part.get("state", {}).get("output", "")} for part in tool_parts],
                        }
                await asyncio.sleep(3)
                for task in tasks.values():
                    if task.done():
                        await task
                        raise RuntimeError("SSE ended before acceptance completed")
                self.report["sse"] = {}
                for name in NAMES:
                    other = "client-b" if name == "client-a" else "client-a"
                    raw = json.dumps(events[name], ensure_ascii=False)
                    self.no_key_leak(f"{name}: observed test events contain no real key", events[name])
                    self.check(f"{name}: SSE excludes the other client's test session IDs and markers", not any(identifier in raw for identifier in sessions[other].values()) and answers[other] not in raw and contents[other] not in raw)
                    counts = {}
                    for kind, identifier in sessions[name].items():
                        deltas = []
                        for event in events[name]:
                            payload = event.get("payload", event)
                            properties = payload.get("properties", {})
                            if payload.get("type") == "message.part.delta" and properties.get("sessionID") == identifier and properties.get("field") == "text":
                                deltas.append(properties.get("delta", ""))
                        target = answers[name] if kind == "answer" else contents[name]
                        self.check(f"{name}: {kind} streamed real text deltas", bool(deltas) and target in "".join(deltas))
                        counts[kind] = len(deltas)
                    self.report["sse"][name] = {"observed_test_events": len(events[name]), "text_delta_counts": counts, "post_response_window_seconds": 3}
                    listing = await self.request(clients[name], "GET", "/session", params={"directory": "/workspace"})
                    ids = {entry["id"] for entry in listing}
                    self.check(f"{name}: lists its live sessions and excludes foreign sessions", set(sessions[name].values()).issubset(ids) and not (set(sessions[other].values()) & ids))
                    for foreign in sessions[other].values():
                        response = await clients[name].get(f"/session/{foreign}", params={"directory": "/workspace"})
                        self.check(f"{name}: foreign live session ID is unavailable", response.status_code in (403, 404), {"status": response.status_code})
            finally:
                for task in tasks.values():
                    task.cancel()
                await asyncio.gather(*tasks.values(), return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--timeout", type=float, default=180, help="Per-model-request timeout; no retries")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "deepseek-live.json")
    args = parser.parse_args()
    verifier = None
    report = {"status": "failed", "checks": []}
    try:
        verifier = LiveVerification(args)
        report = verifier.report
        asyncio.run(verifier.run_live())
        report["status"] = "passed"
    except Exception as error:
        message = verifier.redact(error) if verifier else type(error).__name__ + ": setup failed; check local credential/config files"
        report["error"] = {"type": type(error).__name__, "message": message}
        print("FAILED: " + message, file=sys.stderr)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        args.output.write_text((verifier.redact(serialized) if verifier else serialized) + "\n", encoding="utf-8")
        print("Evidence: " + str(args.output), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
