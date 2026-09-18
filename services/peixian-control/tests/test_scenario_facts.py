import copy
import json
import pytest
from control.scenario_facts import TABLES, PREPARE, CHECK, review
from control.scenario_evidence import project


def messages():
    table = next(t for t in TABLES if t["scenario_id"] == "DEMO-CASE-THEFT" and t["data_status"] == "complete")
    fact = next(f for f in table["facts"] if f["fact_id"] == "DEMO-NGT-001")
    claims = [{k: fact[k] for k in ("fact_id", "statement", "source_ids")}]
    def tool(name, args, output):
        return {"info": {"role": "assistant", "id": name}, "parts": [{"type": "tool", "tool": name, "state": {"status": "completed", "input": args, "output": json.dumps(output)}}]}
    return [{"info": {"role": "user", "id": "request"}}, tool(PREPARE, {"scenario_id": table["scenario_id"]}, table), tool(CHECK, {"scenario_id": table["scenario_id"], "claims": claims}, review(table, claims))]


def test_checked_claims_are_independently_reconstructed():
    result = project(messages(), True)
    assert result["status"] == "complete"
    assert result["summary_check"] == "checked"
    assert "无法判断" in result["verified_summary"][0]["statement"]
    assert not any(c["id"] == "DEMO-NGT-004" for c in result["cards"])


@pytest.mark.parametrize("corruption", ["false_claim", "wrong_source", "swapped_snapshot", "fabricated_table", "extra_claim_key", "old_turn", "revoked"])
def test_untrusted_assertions_never_become_verified(corruption):
    values = messages()
    part = values[-1]["parts"][0]["state"]
    if corruption == "false_claim": part["input"]["claims"][0]["statement"] = "独行作案"
    if corruption == "wrong_source": part["input"]["claims"][0]["source_ids"] = ["DEMO-NGT-007"]
    if corruption == "extra_claim_key": part["input"]["claims"][0]["verdict"] = "犯罪"
    if corruption == "swapped_snapshot":
        result = json.loads(part["output"]);result["scenario_snapshot_id"] = result["records_snapshot_id"];part["output"] = json.dumps(result)
    if corruption == "fabricated_table":
        state = values[1]["parts"][0]["state"]; result = json.loads(state["output"]);result["facts"][0]["statement"] = "fabricated";state["output"] = json.dumps(result)
    if corruption == "old_turn": values.append({"info": {"role": "user", "id": "new"}})
    result = project(values, corruption != "revoked")
    assert not result.get("verified_summary")


def test_changed_scenario_and_free_text_cannot_override_facts():
    values = messages()
    values[-1]["parts"][0]["state"]["input"]["scenario_id"] = "DEMO-CASE-GAMBLING"
    values.append({"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "已核验：<script>alert(1)</script>"}]})
    assert not project(values, True).get("verified_summary")


def test_partial_data_never_means_zero_or_alone():
    table = next(t for t in TABLES if t["scenario_id"] == "DEMO-CASE-THEFT" and not t["summary"])
    assert table["data_status"] == "partial"
    assert not any(f["fact_id"] == "DEMO-CTX-T02" for f in table["facts"])
    assert any("不将缺失视为零条" in m for m in table["missing"])
