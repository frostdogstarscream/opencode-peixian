"""Explicit httpx commands for Agent Workspace. No default model generation.

Configuration: PLATFORM_URL, PLATFORM_CA_FILE, PLATFORM_TOKEN, PLATFORM_USERNAME.
Tokens are read from the environment; passwords are entered with getpass -- never
pass either credential as a command argument. Use --login for a short-lived cookie
session instead of a personal token. TLS verification is always enabled.
"""
import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.parse import urlsplit

import httpx

PREFIX = "/api/console/v1"


class PlatformError(RuntimeError):
    pass


def origin(value):
    parts = urlsplit(value)
    if (parts.scheme not in ("https", "http") or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise PlatformError("PLATFORM_URL 必须为不含凭据、路径或参数的平台 HTTP/HTTPS 入口")
    try:
        loopback = parts.hostname == "localhost" or ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        loopback = False
    if parts.scheme == "http" and not loopback:
        raise PlatformError("服务器访问必须使用 HTTPS；HTTP 仅用于本机回环测试")
    return value.rstrip("/")


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise argparse.ArgumentTypeError("请使用平台返回的资源 ID，不接受路径或 URL")
    return value


class Platform:
    def __init__(self, base_url, *, ca_file=None, transport=None):
        self.origin = origin(base_url)
        self.client = httpx.Client(base_url=self.origin, verify=ssl.create_default_context(cafile=ca_file),
                                  trust_env=False, follow_redirects=False, transport=transport,
                                  timeout=httpx.Timeout(60, connect=10))
        self.cookie_login = False

    def request(self, method, path, **kwargs):
        return self.checked(self.client.request(method, path, **kwargs))

    @staticmethod
    def checked(response):
        if not response.is_success:
            # Do not include raw headers, credentials, URLs, or upstream bodies in exceptions.
            raise PlatformError(f"平台请求失败，HTTP {response.status_code}；请在界面检查权限、环境状态和配置")
        try:
            return response.json()
        except ValueError:
            raise PlatformError("平台返回了非 JSON 响应，请检查入口地址") from None

    def authenticate(self, *, token=None, username=None, password=None):
        if token:
            if any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise PlatformError("PLATFORM_TOKEN 格式无效")
            self.client.headers["Authorization"] = "Bearer " + token
        else:
            if not username or password is None:
                raise PlatformError("请设置 PLATFORM_TOKEN，或使用 --login 交互登录")
            self.client.headers["Origin"] = self.origin
            response = self.request("POST", PREFIX + "/auth/login", json={"username": username, "password": password})
            self.client.headers["X-CSRF-Token"] = response["csrf_token"]
            self.cookie_login = True
        identity = self.request("GET", PREFIX + "/me")
        if identity["user"]["must_change_password"]:
            raise PlatformError("账号必须先在网页修改初始密码，再使用 Python 接口")
        return identity

    def upload(self, path):
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 20 * 1024 * 1024:
            raise PlatformError("请选择不超过 20 MiB 的普通文件")
        with source.open("rb") as stream:
            return self.request("POST", PREFIX + "/files", files={"file": (source.name, stream, "application/octet-stream")})

    def events(self, *, seconds=60, session_id=None):
        """SSE is a change notification. Fetch history to recover and deduplicate.

        It is not a raw model token stream. Reconnects never resend a prompt.
        """
        end = time.monotonic() + seconds
        previous = None
        for attempt in range(3):
            if time.monotonic() >= end:
                return
            try:
                with self.client.stream("GET", PREFIX + "/events", timeout=httpx.Timeout(15, connect=10)) as response:
                    if not response.is_success:
                        raise PlatformError(f"事件订阅失败，HTTP {response.status_code}")
                    event, chunks = "", []
                    for line in response.iter_lines():
                        if time.monotonic() >= end:
                            return
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            chunks.append(line[5:].lstrip())
                        elif line == "":
                            if event == "change" and chunks:
                                yield {"event": "change", "data": json.loads("\n".join(chunks))}
                                if session_id:
                                    # Includes the initial connected event: missed updates are recovered after reconnect.
                                    history = self.request("GET", PREFIX + "/sessions/" + session_id + "/messages")
                                    fingerprint = hashlib.sha256(json.dumps(history, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                                    if fingerprint != previous:
                                        previous = fingerprint
                                        yield {"event": "history", "data": history}
                            event, chunks = "", []
                # A clean EOF also needs fresh authentication on the reconnect request.
            except httpx.TransportError:
                if attempt == 2:
                    raise PlatformError("事件连接中断；可重新运行 events，历史查询不会重复发送问题") from None
            time.sleep(min(1 + attempt, max(0, end - time.monotonic())))

    def close(self):
        try:
            if self.cookie_login:
                # Only this script's temporary cookie session is revoked. Personal tokens remain valid.
                self.client.post(PREFIX + "/auth/logout")
        except httpx.HTTPError:
            pass
        finally:
            self.client.close()


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("PLATFORM_URL", "http://127.0.0.1:14090"))
    parser.add_argument("--ca-file", default=os.getenv("PLATFORM_CA_FILE"), help="受信任的内部 CA PEM 文件，始终验证证书与主机名")
    parser.add_argument("--login", action="store_true", help="用隐藏密码输入登录，忽略环境中的个人令牌")
    parser.add_argument("--username", default=os.getenv("PLATFORM_USERNAME"))
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("health", "me", "models", "skills", "plugins", "files", "sessions"):
        sub.add_parser(action)
    create = sub.add_parser("create-session", help="创建空会话，不发起模型推理")
    create.add_argument("--title", default="Python 对话")
    upload = sub.add_parser("upload", help="上传并排队解析；不会向模型发送文件")
    upload.add_argument("path", type=Path)
    messages = sub.add_parser("messages")
    messages.add_argument("--session", required=True, type=identifier)
    send = sub.add_parser("send", help="明确向模型发送问题，可能产生模型调用费用")
    send.add_argument("--session", required=True, type=identifier)
    text = send.add_mutually_exclusive_group(required=True)
    text.add_argument("--text")
    text.add_argument("--text-file", type=Path, help="从本机 UTF-8 文本读取问题，避免出现在命令历史中")
    send.add_argument("--model", type=identifier, help="平台授权模型 ID，省略时使用授权默认模型")
    send.add_argument("--file-id", action="append", default=[], type=identifier)
    send.add_argument("--skill-id", action="append", default=[], type=identifier)
    stop = sub.add_parser("stop")
    stop.add_argument("--session", required=True, type=identifier)
    events = sub.add_parser("events", help="订阅变更，最多重连两次；不会发送问题")
    events.add_argument("--session", type=identifier, help="发生变更时读取并去重本会话历史")
    events.add_argument("--seconds", type=int, default=60)
    result = parser.parse_args(argv)
    if result.action == "events" and not 1 <= result.seconds <= 3600:
        parser.error("--seconds 应为 1 至 3600")
    return result


def main(argv=None):
    args = arguments(argv)
    platform = None
    try:
        platform = Platform(args.url, ca_file=args.ca_file)
        if args.action == "health":
            result = {"health": platform.request("GET", "/health"), "platform": platform.request("GET", PREFIX + "/platform")}
        else:
            token = None if args.login else os.getenv("PLATFORM_TOKEN")
            password = getpass.getpass("平台密码（输入不可见）: ") if args.login else None
            identity = platform.authenticate(token=token, username=args.username, password=password)
            if args.action == "me":
                result = {"user": identity["user"], "capabilities": identity["capabilities"]}
            elif args.action in ("models", "skills", "plugins", "files", "sessions"):
                result = platform.request("GET", PREFIX + "/" + args.action)
            elif args.action == "create-session":
                result = platform.request("POST", PREFIX + "/sessions", json={"title": args.title})
            elif args.action == "upload":
                result = platform.upload(args.path)
            elif args.action == "messages":
                result = platform.request("GET", PREFIX + "/sessions/" + args.session + "/messages")
            elif args.action == "send":
                content = args.text_file.read_text(encoding="utf-8") if args.text_file else args.text
                if len(args.file_id) > 5 or len(args.skill_id) > 5:
                    raise PlatformError("每次最多选择五个文件和五个技能")
                body = {"text": content, "file_ids": args.file_id, "skill_ids": args.skill_id}
                if args.model:
                    body["model_id"] = args.model
                result = platform.request("POST", PREFIX + "/sessions/" + args.session + "/messages", json=body)
            elif args.action == "stop":
                result = platform.request("POST", PREFIX + "/sessions/" + args.session + "/abort")
            else:
                for event in platform.events(seconds=args.seconds, session_id=args.session):
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PlatformError, httpx.HTTPError, OSError, ValueError) as exc:
        print(str(exc) if isinstance(exc, PlatformError) else "请求未完成，请检查本机文件、受信任 CA、网络和平台入口。", file=sys.stderr)
        return 1
    finally:
        if platform:
            platform.close()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
