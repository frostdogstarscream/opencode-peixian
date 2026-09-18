import copy
import json
import pytest
from agent_acceptance_evidence import current_turn, validate_chain
from fixture_profiles import load_profile


def chain(profile="legacy", module="funds"):
    expected = load_profile(profile)[0][module]
    output = {**expected, "items": expected["records"]}
    values = [{"info":{"role":"user"},"parts":[]},
        {"info":{"role":"assistant","finish":"tool-calls"},"parts":[{"type":"tool","tool":"skill","state":{"status":"completed","input":{"name":"synthetic"},"output":"instructions"}}]},
        {"info":{"role":"assistant","finish":"tool-calls"},"parts":[{"type":"tool","tool":"peixian_get_"+module+"_records","state":{"status":"completed","input":{},"output":json.dumps(output)}}]},
        {"info":{"role":"assistant","finish":"stop","time":{"completed":1}},"parts":[{"type":"text","text":"合成演示资料 "+expected["snapshot_id"]+" complete "+" ".join(row["record_id"] for row in expected["records"])}]}]
    return expected, values


def test_tool_calls_in_prior_assistant_messages_are_counted():
    expected, values = chain()
    assert validate_chain(values,values,expected,"synthetic")["returned_count"] == 5


def test_old_turn_cannot_satisfy_current_turn():
    expected, values = chain()
    values += [{"info":{"role":"user"},"parts":[]}, copy.deepcopy(values[-1])]
    with pytest.raises(ValueError, match="unexpected_tool_chain"):
        validate_chain(values,values,expected,"synthetic")


@pytest.mark.parametrize("failure",["no_tool","wrong_module","wrong_id","wrong_snapshot","failed_tool","extra_tool","wrong_skill","nonempty_args"])
def test_invalid_evidence_is_rejected(failure):
    expected, values = chain()
    if failure=="no_tool":values=values[:1]+values[-1:]
    if failure=="wrong_module":values[2]["parts"][0]["tool"]="peixian_get_calls_records"
    if failure=="wrong_id":values[-1]["parts"][0]["text"]+=" DEMO-E999"
    if failure=="wrong_snapshot":expected["snapshot_id"]="unexpected"
    if failure=="failed_tool":values[2]["parts"][0]["state"]["status"]="error"
    if failure=="extra_tool":values.insert(3,copy.deepcopy(values[2]))
    if failure=="wrong_skill":values[1]["parts"][0]["state"]["input"]["name"]="other"
    if failure=="nonempty_args":values[2]["parts"][0]["state"]["input"]={"limit":1}
    with pytest.raises(ValueError):validate_chain(values,values,expected,"synthetic")


@pytest.mark.parametrize("profile", ["legacy", "enhanced"])
@pytest.mark.parametrize("module_name,function_name",[("accept_agent_behavior","evidence"),("accept_agent_behavior_with_template","safe_evidence")])
def test_legacy_entrypoints_accept_full_public_chain(module_name,function_name,profile):
    import importlib
    expected, values = chain(profile)
    public = copy.deepcopy(values)
    public[1]["parts"][0]["tool"]="使用技能"
    part=public[2]["parts"][0]
    part["tool"]="调用已启用的插件"
    part["details"]={"outputs":expected}
    evidence=getattr(importlib.import_module(module_name),function_name)
    assert evidence(current_turn(public),"funds",profile)["returned_count"]==expected["returned_count"]
    with pytest.raises(RuntimeError):evidence([public[-1]],"funds",profile)


@pytest.mark.parametrize("module", ["funds", "calls", "portrait", "composite", "night", "vehicle", "lookup"])
def test_enhanced_complete_chain_and_source_references(module):
    expected, values = chain("enhanced", module)
    references = {ref for row in expected["records"] for ref in row.get("source_record_ids", [])}
    values[-1]["parts"][0]["text"] += " " + " ".join(references)
    result = validate_chain(values, values, expected, "synthetic")
    assert result["snapshot_id"] == "DEMO-SNAPSHOT-20260918-01"
    assert result["returned_count"] == len(expected["records"])


@pytest.mark.parametrize("failure", ["old_snapshot", "old_rule", "missing_record", "invented_reference", "altered_items", "boolean_as_number"])
def test_enhanced_rejects_mixed_or_incomplete_evidence(failure):
    expected, values = chain("enhanced", "lookup")
    state = values[2]["parts"][0]["state"]
    output = json.loads(state["output"])
    if failure == "old_snapshot": output["snapshot_id"] = "DEMO-SNAPSHOT-001"
    if failure == "old_rule": output["rule_version"] = "demo-v1"
    if failure == "missing_record":
        text = values[-1]["parts"][0]
        text["text"] = text["text"].replace(expected["records"][-1]["record_id"], "")
    if failure == "invented_reference": values[-1]["parts"][0]["text"] += " DEMO-FND-999"
    if failure == "altered_items": output["items"][0]["source_record_ids"] = ["DEMO-FND-999"]
    if failure == "boolean_as_number": output["synthetic"] = 1
    state["output"] = json.dumps(output)
    with pytest.raises(ValueError): validate_chain(values, values, expected, "synthetic")


def test_profile_loading_does_not_mutate_legacy_fixture():
    before, identity = load_profile("legacy")
    enhanced, enhanced_identity = load_profile("enhanced")
    after, _ = load_profile("legacy")
    assert before == after
    assert sum(len(x["records"]) for x in before.values()) == 30
    assert sum(len(x["records"]) for x in enhanced.values()) == 50
    assert identity["snapshot_id"] != enhanced_identity["snapshot_id"]
