"""Bounded real-platform workflow probe for one or two SYNTHETIC accounts.

Use with an independently provisioned loadtest deployment and external cgroup
sampling. This client does not provision accounts, set limits, or read business
files. Every selected scenario runs once per account; failed writes are never
replayed. The private manifest has the same shape as platform_load.py, but only
one or two distinct loadtest users. Reports contain no endpoint or credentials.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.console_client import ConsoleClient, ConsoleError, PREFIX, sse_events


SCENARIOS = ("idle", "answers", "plugin-test", "tool", "files", "events")
PLUGIN_ID = "sample-records"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def write_synthetic_docx(path, lines):
    """Small text-only OOXML fixture; the load client needs no native parsers."""
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>' + ''.join('<w:p><w:r><w:t xml:space="preserve">' + escape(line)
                                     + '</w:t></w:r></w:p>' for line in lines)
                + '<w:sectPr/></w:body></w:document>')
    with ZipFile(path, "x", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '</Types>')
        archive.writestr("_rels/.rels",
                         '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                         '</Relationships>')
        archive.writestr("word/document.xml", document)


def load_manifest(path):
    if not path.is_file() or not 1 <= path.stat().st_size <= 16384:
        raise ValueError("small_private_manifest_required")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or set(value) != {"base_url", "deployment_id", "users"}
            or not matches(r"loadtest-[a-z0-9-]{1,40}", value.get("deployment_id"))):
        raise ValueError("synthetic_manifest_required")
    if not isinstance(value["base_url"], str):
        raise ValueError("console_origin_required")
    origin = urlsplit(value["base_url"])
    if (origin.scheme not in ("http", "https") or not origin.hostname or origin.username
            or origin.password or origin.query or origin.fragment or origin.path not in ("", "/")
            or (origin.scheme == "http" and origin.hostname not in ("127.0.0.1", "::1", "localhost"))):
        raise ValueError("verified_https_or_loopback_console_required")
    users = value["users"]
    if not isinstance(users, list) or not 1 <= len(users) <= 2:
        raise ValueError("one_or_two_synthetic_accounts_required")
    for item in users:
        if (not isinstance(item, dict) or set(item) != {"username", "token"}
                or not matches(r"loadtest-[A-Za-z0-9_.-]{1,30}", item.get("username"))
                or not matches(r"px_[A-Za-z0-9_-]{8,250}", item.get("token"))):
            raise ValueError("synthetic_account_manifest_invalid")
    if (len({item["username"] for item in users}) != len(users)
            or len({item["token"] for item in users}) != len(users)):
        raise ValueError("distinct_account_credentials_required")
    return value


def public_error(error):
    # Never serialize exception messages: HTTP errors can embed URLs or bodies.
    return {"type": type(error).__name__, "http_status": getattr(error, "status", None),
            "result_unknown": bool(getattr(error, "result_unknown", False))}


def new_message_evidence(values, prior_ids, plugin_version):
    messages = [item for item in values if item.get("info", {}).get("id") not in prior_ids
                and item.get("info", {}).get("role") == "assistant"]
    completed = [item for item in messages if item.get("info", {}).get("time", {}).get("completed")
                 and not item.get("info", {}).get("error")]
    tools = [part for item in messages for part in item.get("parts", [])
             if part.get("type") == "tool" and part.get("tool") == "调用已启用的插件"
             and part.get("state", {}).get("status") == "completed"]
    matched = 0
    for part in tools:
        output = part.get("details", {}).get("outputs", {})
        if (output.get("source") == "示例资料服务" and output.get("version") == plugin_version
                and type(output.get("count")) is int and 0 <= output["count"] <= 20):
            matched += 1
    return {"new_assistant_messages": len(messages), "new_completed_messages": len(completed),
            "new_answer_characters": sum(len(part.get("text", "")) for item in messages
                                         for part in item.get("parts", []) if part.get("type") == "text"),
            "new_completed_plugin_tools": len(tools), "matching_sample_records_outputs": matched}


async def event_probe(client, seconds):
    """Exactly one subscription, no reconnect loop; raw event data stays private."""
    count = 0
    connected = False
    client.stream_http.cookies.clear()
    client.stream_http.cookies.update(client.http.cookies)
    async with client.stream_http.stream("GET", PREFIX + "/events", headers=client.http.headers) as response:
        client.check(response)
        if not response.headers.get("content-type", "").startswith("text/event-stream"):
            raise ConsoleError("event_content_type_invalid")
        try:
            async with asyncio.timeout(seconds):
                async for event in sse_events(response.aiter_lines()):
                    if event["event"] == "change":
                        connected = True
                        count += 1
            raise ConsoleError("event_stream_closed_early")
        except TimeoutError:
            if not connected:
                raise ConsoleError("event_subscription_not_confirmed") from None
    return {"subscriptions": 1, "change_events": count, "seconds_observed": seconds,
            "reconnections": 0}


async def workflow(client, scenario, args, account_number):
    result = {"account_number": account_number, "started_at": utc_now(), "status": "failed"}
    started = time.monotonic()
    try:
        async with asyncio.timeout(args.task_timeout + 30):
            if scenario == "idle":
                await asyncio.sleep(args.observe_seconds)
                await client.me()
                result["seconds_observed"] = args.observe_seconds
            elif scenario == "events":
                result.update(await event_probe(client, args.observe_seconds))
            elif scenario == "plugin-test":
                reply = await client.request("POST", "/plugins/" + PLUGIN_ID + "/test", json={})
                if reply.get("ok") is not True:
                    raise ConsoleError("sample_plugin_connection_test_failed")
                result.update(connection_test_completed=True, model_tool_execution=False)
            elif scenario == "files":
                marker = "LOADTEST-SYNTHETIC-" + uuid.uuid4().hex
                with tempfile.TemporaryDirectory(prefix="agent-profile-") as directory:
                    path = Path(directory) / ("synthetic-profile." + args.file_type)
                    lines = [marker, "合成文件解析资源画像，不包含业务资料。"]
                    lines += [f"合成行 {index:03d}：示例数量 {index}，仅供平台解析验证。" for index in range(100)]
                    if args.file_type == "docx":
                        write_synthetic_docx(path, lines)
                    else:
                        path.write_text("\n".join(lines), encoding="utf-8")
                    uploaded = await client.upload(path)
                    parsed = await client.wait_for_file(uploaded["id"], timeout=min(90, args.task_timeout))
                    extracted = parsed.get("text", "") + "\n".join(chunk.get("text", "") for chunk in parsed.get("chunks", []))
                    if marker not in extracted:
                        raise ConsoleError("synthetic_file_marker_missing")
                    result.update(file_type=args.file_type, upload_bytes=path.stat().st_size,
                                  parsed_status=parsed["status"], marker_verified=True)
            else:
                session_id = (await client.create_session("loadtest-profile-" + uuid.uuid4().hex[:12]))["id"]
                prior = {item["info"]["id"] for item in await client.messages(session_id)}
                prompt = ("这是合成资源画像，不含业务资料。请用中文写出 80 项连续编号的办公学习建议，"
                          "每项至少 20 字，总长度不少于 1600 字。不调用工具，不读取文件。")
                if scenario == "tool":
                    prompt = ("这是合成资源画像。请实际调用已授权的 sample-records 示例资料查询插件的 "
                              "platform_sample_records 工具一次，再用一句话总结合成结果。不要读取文件或调用其他工具。")
                values = await client.run_message(session_id, prompt, model_id=args.model_id, timeout=args.task_timeout)
                evidence = new_message_evidence(values, prior, args.plugin_version)
                result.update(evidence)
                if not evidence["new_completed_messages"]:
                    raise ConsoleError("new_completed_model_message_missing")
                if scenario == "tool" and not evidence["matching_sample_records_outputs"]:
                    raise ConsoleError("sample_plugin_new_tool_evidence_missing")
                if scenario == "answers" and evidence["new_answer_characters"] < 1000:
                    result["status"] = "not_verified"
                    result["reason"] = "answer_too_short_for_long_answer_profile"
        if result["status"] != "not_verified":
            result["status"] = "passed"
    except Exception as error:
        result["error"] = public_error(error)
    finally:
        result.update(ended_at=utc_now(), elapsed_seconds=round(time.monotonic() - started, 3))
    return result


async def execute(args):
    if not args.synthetic_deployment:
        raise ValueError("synthetic_opt_in_required")
    manifest = load_manifest(args.credentials)
    if not 1 <= args.accounts <= len(manifest["users"]):
        raise ValueError("requested_synthetic_accounts_unavailable")
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    if any(scenario in ("answers", "tool") for scenario in scenarios) and not matches(r"[A-Za-z0-9_-]{1,100}", args.model_id):
        raise ValueError("explicit_authorized_model_id_required")
    report = {"format": 1, "profile": "one_or_two_real_platform_synthetic_accounts", "started_at": utc_now(),
              "deployment_fingerprint": hashlib.sha256(manifest["deployment_id"].encode()).hexdigest()[:16],
              "accounts": args.accounts, "stages": [], "status": "failed", "tls_verification": "enabled",
              "explicit_ca": args.ca_file is not None,
              "limits": {"task_timeout": args.task_timeout, "observe_seconds": args.observe_seconds,
                         "write_retries": 0, "iterations_per_account_per_scenario": 1},
              "evidence_boundary": "Client workflow timestamps only. Combine external cgroup peaks, container restarts and upstream evidence. Public tool output fingerprint is not a raw tool identity proof. No 50-account capacity claim."}
    async with AsyncExitStack() as stack:
        clients = []
        # Validate ALL identities and grants before the first remote mutation.
        for item in manifest["users"][:args.accounts]:
            client = await stack.enter_async_context(ConsoleClient(manifest["base_url"], token=item["token"], ca_file=args.ca_file))
            me = await client.me()
            if (me.get("username") != item["username"] or me.get("role") != "user"
                    or me.get("must_change_password") or (me.get("runtime") or {}).get("status") != "ready"):
                raise ValueError("synthetic_user_not_ready")
            if any(scenario in ("answers", "tool") for scenario in scenarios):
                if args.model_id not in {model["id"] for model in await client.models()}:
                    raise ValueError("selected_model_not_authorized")
            if any(scenario in ("plugin-test", "tool") for scenario in scenarios):
                plugins = (await client.request("GET", "/plugins"))["items"]
                installed = [plugin for plugin in plugins if (plugin.get("installed") or {}).get("enabled")]
                if (len(installed) != 1 or installed[0]["id"] != PLUGIN_ID
                        or installed[0]["installed"].get("version") != args.plugin_version
                        or installed[0]["installed"].get("state") != "active"):
                    raise ValueError("only_expected_sample_plugin_must_be_active")
            clients.append(client)
        for scenario in scenarios:
            stage = {"scenario": scenario, "started_at": utc_now()}
            stage["accounts"] = await asyncio.gather(*(workflow(client, scenario, args, index + 1)
                                                       for index, client in enumerate(clients)))
            stage["ended_at"] = utc_now()
            stage["status"] = "passed" if all(item["status"] == "passed" for item in stage["accounts"]) else "failed"
            report["stages"].append(stage)
            if stage["status"] != "passed":
                break
        report["status"] = "passed" if all(stage["status"] == "passed" for stage in report["stages"]) else "failed"
    report["ended_at"] = utc_now()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-deployment", action="store_true", required=True)
    parser.add_argument("--accounts", type=int, choices=(1, 2), default=2)
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    parser.add_argument("--model-id")
    parser.add_argument("--plugin-version", default="1.0.0")
    parser.add_argument("--file-type", choices=("txt", "docx"), default="txt")
    parser.add_argument("--observe-seconds", type=int, default=30)
    parser.add_argument("--task-timeout", type=int, default=300)
    parser.add_argument("--ca-file", type=Path, help="PEM CA trust bundle; no insecure TLS mode")
    args = parser.parse_args()
    if not (1 <= args.observe_seconds <= 300 and 10 <= args.task_timeout <= 900
            and args.observe_seconds <= args.task_timeout
            and matches(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", args.plugin_version)):
        parser.error("invalid bounded scenario configuration")
    # Refuse report overwrite before sending any mutation to the platform.
    with args.output.open("x", encoding="utf-8") as target:
        try:
            report = asyncio.run(execute(args))
        except (Exception, KeyboardInterrupt) as error:
            report = {"status": "failed", "error": public_error(error), "capacity_status": "not_verified"}
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print("Sanitized small-profile report written. Resource peaks require the independent sampler.")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
