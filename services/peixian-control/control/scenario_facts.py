"""Validate fixed synthetic fact tables and exact supported claims, never prose."""
import json
from pathlib import Path

TABLES = json.loads(Path(__file__).with_name("scenario_fact_tables.json").read_text())
PREPARE = "peixian_prepare_scenario_facts"
CHECK = "peixian_check_scenario_summary"


def review(table, claims):
    if not isinstance(claims, list) or len(claims) > 40:
        raise ValueError()
    approved, rejected, seen = [], [], set()
    for i, claim in enumerate(claims):
        fact = next((f for f in table["facts"] if isinstance(claim, dict) and f["fact_id"] == claim.get("fact_id")), None)
        if (not isinstance(claim, dict) or set(claim) != {"fact_id", "statement", "source_ids"} or not fact or fact["fact_id"] in seen
                or claim["statement"] != fact["statement"] or claim["source_ids"] != fact["source_ids"]):
            rejected.append({"index": i, "reason": "表述或来源不与事实表精确对应，未核验。"})
            continue
        seen.add(fact["fact_id"])
        approved.append(fact)
    return {"schema_version": "checked-summary-v1", "scenario_id": table["scenario_id"], "scenario_snapshot_id": table["scenario_snapshot_id"],
            "records_snapshot_id": table["records_snapshot_id"], "data_status": table["data_status"], "approved": approved, "rejected": rejected,
            "missing": table["missing"], "notice": "仅 approved 中的固定表述经过代码核对；其他文字和改写未核验，不判定违法犯罪。"}


def project_facts(turn, result, data):
    parts = [(p, m.get("info", {}).get("id", "")) for m in turn if m.get("info", {}).get("role") == "assistant" for p in m.get("parts", []) if p.get("type") == "tool" and p.get("tool") in (PREPARE, CHECK)]
    if not parts:
        return None
    table, mid, checked = None, "", None
    for part, message_id in parts:
        state = part.get("state", {})
        status = state.get("status")
        step = {"label": "代码整理事实" if part["tool"] == PREPARE else "摘要来源核对", "status": status if status in ("pending", "running", "completed", "error") else "pending"}
        result["steps"].append(step)
        if status != "completed":
            continue
        try:
            raw = state.get("output")
            if not isinstance(raw, str) or len(raw) > 1048576:
                raise ValueError()
            output = json.loads(raw)
            args = state.get("input", {})
            if part["tool"] == PREPARE:
                if not isinstance(args, dict) or set(args) != {"scenario_id"} or output.get("scenario_id") != args["scenario_id"] or output not in TABLES:
                    raise ValueError()
                if table is not None and output != table:
                    return {**result, "status": "unavailable", "cards": [], "missing": ["本轮事实表不一致，请分别核对。"]}
                table, mid, checked = output, message_id, None
            else:
                if table is None or not isinstance(args, dict) or set(args) != {"scenario_id", "claims"} or args["scenario_id"] != table["scenario_id"] or output != review(table, args["claims"]):
                    raise ValueError()
                checked = output
        except (ValueError, TypeError, AttributeError, KeyError):
            step["status"] = "error"
            result["missing"].append(step["label"] + "未通过固定事实与来源核对。")
    if table is None:
        return {**result, "status": "partial"}
    context = data["scenarios"][table["scenario_id"]]
    result["scenario"] = {k: context[k] for k in ("scenario_id", "title", "subject_ref", "snapshot_id", "records_snapshot_id", "rule_version", "timezone", "night_window", "case_window")}
    result["summary"] = [{k: row[k] for k in ("label", "count", "dates", "night_count")} for row in table["summary"]]
    result["missing"] += table["missing"]
    result["cards"] = [{"id": f["fact_id"], "title": "代码事实 · " + f["fact_id"], "description": f["statement"], "time": f["time"], "source_ids": f["source_ids"], "fields": [], "message_id": mid, "snapshot_id": table["scenario_snapshot_id"] if f["kind"] == "context" else table["records_snapshot_id"]} for f in table["facts"]]
    result["cards"].sort(key=lambda c: (c["time"], c["id"]))
    result["verified_summary"] = [{"fact_id": f["fact_id"], "statement": f["statement"], "source_ids": f["source_ids"]} for f in checked["approved"]] if checked else []
    result["summary_check"] = "rejected" if checked and checked["rejected"] else "checked" if checked and checked["approved"] else "pending"
    result["status"] = "complete" if table["data_status"] == "complete" and all(s["status"] == "completed" for s in result["steps"]) else "partial"
    return result
