"""Small authenticated OpenCode HTTP client; no model request is made."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx


async def run(args):
    password_file = args.password_file or Path(__file__).resolve().parent / ".secrets" / f"{args.client}.password"
    password = password_file.read_text(encoding="utf-8").rstrip("\r\n")
    if len(password) < 16 or any(char in password for char in "\r\n\0"):
        raise ValueError("Password file must contain one value of at least 16 characters, with no internal CR/LF/NUL")
    url = args.url or f"http://127.0.0.1:{14091 if args.client == 'client-a' else 14092}"
    async with httpx.AsyncClient(base_url=url, auth=(args.client, password), trust_env=False, timeout=30) as client:
        response = await client.get("/global/health")
        response.raise_for_status()
        print(json.dumps({"health": response.json()}, ensure_ascii=False))
        params = {"directory": "/workspace"}
        if args.title:
            response = await client.post("/session", params=params, json={"title": args.title})
            response.raise_for_status()
            print(json.dumps({"created": response.json()}, ensure_ascii=False))
        response = await client.get("/session", params=params)
        response.raise_for_status()
        print(json.dumps({"sessions": response.json()}, ensure_ascii=False))
        if args.events_seconds > 0:
            async def events():
                async with client.stream("GET", "/global/event", timeout=None) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            print(line[5:].strip(), flush=True)
            try:
                await asyncio.wait_for(events(), timeout=args.events_seconds)
            except asyncio.TimeoutError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=["client-a", "client-b"], default="client-a")
    parser.add_argument("--url", help="Override the local instance URL")
    parser.add_argument("--password-file", type=Path, help="Read credentials from a file; never pass a password on the command line")
    parser.add_argument("--title", help="Create a synthetic session with this title")
    parser.add_argument("--events-seconds", type=float, default=0, help="Subscribe to SSE for a bounded number of seconds")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
