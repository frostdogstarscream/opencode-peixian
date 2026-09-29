"""Code-owned Chinese answers. Input is an authorized, frozen Result V2, never prose."""
import copy
import html
import json
from .display_identity import mapping
from .live_prose import COMPOSING, Pushes, visible
from .live_text import completed, valid_id
from .trusted_results import LABELS, local

VERSION = "controlled-zh-v1"
MODES = {"new_query", "explain_existing", "clarify"}


def enabled(snapshot):
    return snapshot.get("answer_policy_version") == VERSION or snapshot.get("table_answer_policy", {}).get("version") in ("person-tables-v1", "person-tables-v2", "person-tables-v3")


def freeze(snapshot, payload):
    task = snapshot.get("task_spec") or {}
    if (snapshot.get("trusted_result_version") == "2.0" and task.get("query_mode") in MODES
            and snapshot.get("agent_profile", {}).get("id") in ("gambling-assistant", "theft-assistant")):
        snapshot["answer_policy_version"] = VERSION
        payload["system"] = payload.get("system", "") + "\n资料回答由平台基于已核验事实生成中文说明。请仅选择本轮允许的事实，摘要核对使用原事实句及引用；不要补造关联，不为翻译或说明再次取数。"


def text(claim):
    """Whitelist template semantics; no re-use of a model or source description."""
    fields = claim.get("protected_fields", {})
    template = claim.get("template_id", "")
    module = template.split(".")[0]
    if module not in LABELS or claim.get("verification_status") != "approved":
        return None
    subject = "、".join(str(x) for x in fields.get("subject_refs", [])) or "当前对象"
    if template == module + ".summary.v1" and claim["type"] == "computed":
        count, days, nights = (fields.get(k) for k in ("record_count", "date_count", "night_count"))
        if any(type(x) is not int or x < 0 for x in (count, days, nights)):
            return None
        return f"{subject}：本次范围内{LABELS[module]}共 {count} 条原始记录，涉及 {days} 个北京时间自然日，其中夜间记录 {nights} 条（22:00至次日06:00）。"
    if template != module + ".record.v1" or claim["type"] != "fact" or fields.get("record_id") not in claim.get("source_ids", []):
        return None
    timestamp = fields.get("occurred_at")
    try:
        when = local(timestamp).strftime("%Y-%m-%d %H:%M:%S") + "（北京时间）" if timestamp else "时间未提供"
    except (ValueError, TypeError):
        return None
    if module == "vehicle":
        direction = {"inbound": "驶入", "outbound": "驶出"}.get(fields.get("direction"), "方向未明确")
        detail = f"车辆引用 {fields.get('group_ref', '未提供')}，{direction}，设备引用 {fields.get('device_ref', '未提供')}"
    elif module == "funds":
        amount = fields.get("amount_minor")
        if type(amount) is not int:
            return None
        units = ("-" if amount < 0 else "") + str(abs(amount) // 100) + "." + str(abs(amount) % 100).zfill(2)
        direction = {"in": "收入", "out": "支出", "income": "收入", "expense": "支出", "credit": "收入", "debit": "支出"}.get(fields.get("direction"), "收支方向未明确")
        detail = f"原始资金流水，{direction}，金额 {units} 元，对手账户引用 {fields.get('counterparty_ref', '未提供')}"
    elif module == "portrait":
        detail = {"same_frame": "同框记录", "same_trip": "明确同行记录", "same_vehicle": "明确同乘记录"}.get(fields.get("observation"), "共同出现方式无法判断")
        detail += "，共同出现对象引用 " + str(fields.get("co_member_ref", "未提供"))
    elif module == "night":
        detail = {"alone": "明确独行观测", "accompanied": "明确同行观测"}.get(fields.get("observation"), "同行状态无法判断")
    else:
        detail = LABELS[module] + "，记录引用 " + str(fields["record_id"])
    return f"{subject}，{when}：{detail}。"


def build(result, snapshot, row):
    use = result.get("data_usage", {}); task = snapshot.get("task_spec") or {}
    selected = {f.get("fact_id") for f in (snapshot.get("facts_state", {}).get("checked") or {}).get("approved", [])}
    candidates = [c for c in result.get("claims", []) if c.get("verification_status") == "approved"]
    # Summaries first; valid model-selected records next; deterministic fallback last.
    candidates.sort(key=lambda c: (0 if c["type"] == "computed" else 1 if c.get("protected_fields", {}).get("record_id") in selected else 2, c["claim_id"]))
    items = []
    for claim in candidates:
        sentence = text(claim)
        if sentence:
            items.append({"text": sentence, "claim_id": claim["claim_id"], "source_run_id": claim["source_run_id"], "source_ids": copy.deepcopy(claim["source_ids"])})
        if len(items) == 5:
            break
    missing = list(dict.fromkeys(result.get("missing", [])))
    ready_records = {c.get("protected_fields", {}).get("record_id") for c in candidates if c["type"] == "fact"}
    unchecked = sum(r["record_id"] not in ready_records for r in result.get("records", []))
    if unchecked:
        missing.append(f"{unchecked} 条来源记录尚无逐条核对结果，未作为事实说明。")
    history = use.get("status") == "historical_evidence"
    steps = []
    if task.get("query_mode") == "clarify":
        status = "needs_input"
        summary = (snapshot.get("task_response") or {}).get("message", "请补充当前对象或资料范围，本轮尚未查询。")
        # Existing local router responses specify supported scope without launching a query.
        steps = ["请按提示补充对象或范围；若继续已有对象，请明确说明沿用当前对象。"]
        items = []
    elif use.get("status") in ("unknown", "in_flight"):
        status, summary = "unavailable", "资料调用结果尚未确认，当前不能给出完整说明。"
        steps = ["请刷新原执行状态，不要重复发送同一查询。"]
    elif items:
        status = "partial" if unchecked or use.get("status") in ("partial", "rejected") or row["status"] != "completed" else "ready"
        summary = "本次解释已有的可信资料，没有重新查询。" if history else "已整理本次范围内取得并核对的资料。"
        if status == "partial":
            summary += "以下保留可采用的事实，尚缺的资料见下方。"
        steps = ["可展开本轮依据查看完整记录和来源。", "可导出本轮报告，保留资料范围与版本。"]
    else:
        status = "unavailable"
        summary = "当前没有可供说明的已核验事实；这不表示没有相关记录或没有发生。"
        steps = ["请查看执行步骤和资料缺口，再决定补充信息或发起新的明确请求。"]
    return {"version": VERSION, "status": status, "summary": summary, "items": items, "missing": missing, "next_steps": steps[:2]}


def markdown(answer):
    if answer.get("version") != VERSION:
        return "当前说明版本暂不受支持，请查看已有事实卡片。"
    def escape(value):
        value = html.escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")
        for char in ("\\", "`", "*", "_", "[", "]", "#", ">"):
            value = value.replace(char, "\\" + char)
        return value
    lines = [escape(answer["summary"])]
    if answer["items"]:
        lines += ["", "**相关事实**"]
        lines += ["- " + escape(x["text"]) + "（来源：" + escape("、".join(x["source_ids"]) or "本次已确认查询统计") + "）" for x in answer["items"]]
        lines += ["", "摘要最多展示五条，完整记录见本轮依据。"]
    if answer["missing"]:
        lines += ["", "**资料缺口与范围说明**"] + ["- " + escape(x) for x in answer["missing"]]
    if answer["next_steps"]:
        lines += ["", "**可以继续**"] + ["- " + escape(x) for x in answer["next_steps"]]
    return "\n".join(lines)


def public_result(result):
    if "answer" not in result:
        return result
    value = copy.deepcopy(result)
    value["narrative"] = {**value["narrative"], "text": None, "coverage": "原模型说明仅保留内部诊断；用户回答来自受控中文事实投影。"}
    return value


TABLE_VERSIONS = ("person-tables-v1", "person-tables-v2", "person-tables-v3")
LIVE_STATUSES = ("queued", "running")
_PUSHES = Pushes()


def live_prose(store, row, snapshot):
    """Table runs show their pre-JSON prose until the platform answer exists."""
    return ((snapshot.get("table_answer_policy") or {}).get("version") in TABLE_VERSIONS
            and row["status"] in LIVE_STATUSES and final_body(store, row, snapshot) is None)


def message_target(store, uid, sid, info):
    """(blocked, live target) for one assistant message."""
    rows = store.rows("SELECT * FROM business_runs WHERE uid=? AND session_id=?", (uid, sid))
    for row in rows:
        snapshot = store.decrypt(row["request_ciphertext"])
        if (info.get("parentID") == row["message_id"] or info.get("id") == row["assistant_id"]
                or info.get("id") in snapshot.get("observed_message_ids", [])):
            if not enabled(snapshot):
                return False, None
            if live_prose(store, row, snapshot):
                return False, {"run_id": row["id"], "identities": mapping(snapshot)}
            return True, None
    # An unbound assistant must not expose text while a controlled run exists.
    controlled = [r for r in rows if enabled(store.decrypt(r["request_ciphertext"]))]
    created = info.get("time", {}).get("created")
    if controlled and isinstance(created, (int, float)) and created < min(r["created"] for r in controlled) * 1000:
        return False, None
    return bool(controlled), None


def message_policy(store, uid, sid, info):
    return message_target(store, uid, sid, info)[0]


def push_prose(app, uid, payload):
    """Append-only delta of the filtered prose; the frontend falls back to /messages on any gap."""
    props = payload.get("properties") or {}
    if payload.get("type") == "message.part.updated":
        part = props.get("part") or {}
        if part.get("type") != "text" or part.get("synthetic") is True or part.get("ignored") is True:
            return
        sid, mid, pid = part.get("sessionID"), part.get("messageID"), part.get("id")
        timing = part.get("time")
        open_part = not (isinstance(timing, dict) and timing.get("end") is not None)
        text = app.state.live_text.text(uid, sid, mid, pid) if open_part else part.get("text")
    elif payload.get("type") == "message.part.delta" and props.get("field") == "text":
        sid, mid, pid = props.get("sessionID"), props.get("messageID"), props.get("partID")
        open_part, text = True, app.state.live_text.text(uid, sid, mid, pid)
    else:
        return
    target = _PUSHES.target(uid, mid)
    if not target or not isinstance(text, str) or not all(valid_id(x) for x in (sid, mid, pid)):
        return
    body, composing = visible(text, target["identities"], open_part)
    step = _PUSHES.advance(uid, mid, pid, body, composing)
    if not step:
        return
    offset, added, started = step
    from .live_push import MAX_EVENT_TEXT, VERSION as LIVE_VERSION, progress_notice, push
    if added and len(json.dumps(added)) <= MAX_EVENT_TEXT:
        push(uid, {"type": "answer.delta", "version": LIVE_VERSION, "session_id": sid, "run_id": target["run_id"],
                   "message_id": mid, "part_id": pid, "offset": offset, "text": added})
    if started:
        push(uid, progress_notice({"session_id": sid, "id": target["run_id"]}, *COMPOSING))


async def observe(app, uid, envelope, stream_id):
    payload = envelope.get("payload", {}) if isinstance(envelope, dict) else {}
    if payload.get("type") == "message.updated":
        props = payload.get("properties") or {}; info = props.get("info") or {}
        if info.get("role") == "assistant":
            try:
                blocked, target = await app.state.db_work.run(message_target, app.state.store, uid, props.get("sessionID") or info.get("sessionID"), info)
            except Exception:
                blocked, target = True, None  # Never retain unverified text when policy lookup fails.
            if target and not completed(info):
                _PUSHES.target(uid, info.get("id"), target)
            else:
                _PUSHES.forget(uid, info.get("id"))
            if blocked:
                app.state.live_text.discard_message(uid, info.get("sessionID"), info.get("id"))
                return
    app.state.live_text.observe(uid, envelope, stream_id)
    push_prose(app, uid, payload)


def messages(store, uid, sid, values):
    rows = store.rows("SELECT * FROM business_runs WHERE uid=? AND session_id=?", (uid, sid))
    snapshots = {r["id"]: store.decrypt(r["request_ciphertext"]) for r in rows}
    managed = [r for r in rows if enabled(snapshots[r["id"]])]
    if not managed:
        return values
    live = {r["id"]: live_prose(store, r, snapshots[r["id"]]) for r in managed}
    for message in values:
        info = message["info"]
        if info.get("role") != "assistant":
            continue
        row = next((r for r in rows if info.get("run_id") == r["id"] or info.get("parentID") == r["message_id"] or info.get("id") == r["assistant_id"] or info.get("id") in snapshots[r["id"]].get("observed_message_ids", [])), None)
        if row and not enabled(snapshots[row["id"]]):
            continue
        created = info.get("time", {}).get("created")
        if not row and isinstance(created, (int, float)) and created < min(r["created"] for r in managed) * 1000:
            continue
        if row and live[row["id"]]:
            identities = mapping(snapshots[row["id"]])
            parts = []
            for part in message.get("parts", []):
                if part.get("type") == "reasoning":
                    continue
                if part.get("type") == "text":
                    timing = part.get("time")
                    open_part = not (isinstance(timing, dict) and timing.get("end") is not None)
                    body, _ = visible(part.get("text"), identities, open_part)
                    if body and part.get("synthetic") is not True and part.get("ignored") is not True:
                        parts.append({**part, "text": body})
                    continue
                parts.append(part)
            message["parts"] = parts
            continue
        message["parts"] = [p for p in message.get("parts", []) if p.get("type") not in ("text", "reasoning")]
        if not row or info.get("id") != row["assistant_id"]:
            continue
        body = final_body(store, row, snapshots[row["id"]])
        if body is not None:
            message["parts"].append({"id": "part_answer_" + row["id"], "type": "text", "origin": "controlled_answer", "visibility": "user", "display_kind": "final_answer", "content_revision": 1, "final": True, "run_id": row["id"], "text": body})

    return values


def final_body(store, row, snapshot):
    """Platform-rendered final answer for a finalized controlled run; None before a result is saved."""
    from .trusted_results import checked_result
    saved = store.one("SELECT * FROM run_results WHERE run_id=?", (row["id"],))
    if not saved:
        return None
    result = checked_result(store, saved)
    if snapshot.get('table_answer_policy'):
        from .table_answer import markdown as table_markdown, selection
        view = result.get('answer_view')
        raw = snapshot.get('model_final_text', '')
        return (view.get('markdown') or table_markdown(view)) if view and view.get('version') in ('person-tables-v1','person-tables-v2','person-tables-v3') else ('当前表格版本暂不受支持，请查看已有来源。' if view else ('请说明希望核对的人员或资料范围。' if selection(raw) else raw))
    return markdown(result.get("answer", {}))
