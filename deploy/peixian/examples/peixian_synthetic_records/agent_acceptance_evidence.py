"""Validate full per-request tool chains, not only the final assistant message."""
import json
import re


def current_turn(messages):
    indexes = [i for i, value in enumerate(messages) if value.get("info", {}).get("role") == "user"]
    if not indexes:
        return []
    return [x for x in messages[indexes[-1] + 1:] if x.get("info", {}).get("role") == "assistant"]


def validate_chain(raw_messages, public_messages, expected, skill_name):
    answers = current_turn(raw_messages)
    visible = current_turn(public_messages)
    if not answers or not visible or any(x["info"].get("error") for x in answers):
        raise ValueError("incomplete_or_failed_answer")
    if not answers[-1]["info"].get("time", {}).get("completed") or answers[-1]["info"].get("finish") not in ("stop", "end_turn"):
        raise ValueError("answer_not_finished")
    parts = [p for x in answers for p in x.get("parts", []) if p.get("type") == "tool"]
    target = "peixian_get_" + expected["module"] + "_records"
    if [p.get("tool") for p in parts] != ["skill", target]:
        raise ValueError("unexpected_tool_chain")
    if any(p.get("state", {}).get("status") != "completed" for p in parts):
        raise ValueError("tool_not_completed")
    if parts[0]["state"].get("input", {}).get("name") != skill_name or parts[1]["state"].get("input") != {}:
        raise ValueError("unexpected_tool_arguments")
    output = json.loads(parts[1]["state"]["output"])
    for field in ("module", "synthetic", "snapshot_id", "data_status", "returned_count", "total_count", "has_more", "rule_version", "rule_status"):
        if type(output.get(field)) is not type(expected[field]) or output.get(field) != expected[field]:
            raise ValueError("tool_output_mismatch:" + field)
    if output.get("items") != expected["records"]:
        raise ValueError("tool_records_mismatch")
    text = "".join(p.get("text", "") for p in visible[-1].get("parts", []) if p.get("type") == "text")
    # Match complete identifiers, including unknown prefixes, so fabricated IDs
    # cannot evade detection merely by differing from a known record prefix.
    mentioned = set(re.findall(r"(?<![A-Za-z0-9_-])DEMO-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?![A-Za-z0-9_-])", text))
    expected_ids = {x["record_id"] for x in expected["records"]}
    def identifiers(value):
        if isinstance(value, str):
            return {value} if value.startswith("DEMO-") else set()
        if isinstance(value, dict):
            return set().union(*(identifiers(x) for x in value.values()))
        if isinstance(value, list):
            return set().union(*(identifiers(x) for x in value))
        return set()
    allowed = identifiers(expected)
    if not expected_ids <= mentioned or not mentioned <= allowed:
        raise ValueError("answer_record_ids_mismatch")
    ids = mentioned & expected_ids
    if not all(str(value) in text for value in ("合成", expected["snapshot_id"], expected["data_status"])):
        raise ValueError("answer_source_markers_missing")
    return {"module": expected["module"], "synthetic": True, "snapshot_id": output["snapshot_id"],
            "data_status": output["data_status"], "returned_count": output["returned_count"],
            "tool_chain": ["skill", target], "cited_record_ids": sorted(ids), "answer": text}
