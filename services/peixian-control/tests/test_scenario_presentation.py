import copy
import json
from control.scenario_evidence import project
from control.scenario_presentation import presentation
from test_scenario_facts import messages


def view(values=None):
    values = values or messages()
    return presentation(project(values, True), values)


def test_four_cards_deduplicate_real_relations_and_no_fake_times():
    result = view()
    assert [x["value"] for x in result["evidence"]] == [2, 1, 1, 1]
    assert len(result["process"]) == 5
    assert all(x["time"] == "—" for x in result["process"])
    assert all(x["source_ids"] for x in result["conclusions"])
    for word in ("合成", "代码核对", "风险", "频繁", "42"):
        assert word not in json.dumps(result, ensure_ascii=False)


def test_trace_is_bounded_and_whitelisted():
    values = messages(); state=values[1]["parts"][0]["state"]
    start=1789700000000;state["time"]={"start":start,"end":start+1000}
    output=json.loads(state["output"]);output["execution_trace"]=[{"code":"night","status":"completed","at":start+500},{"code":"secret-url","status":"completed","at":start+600},{"code":"portrait","status":"completed","at":start+999999}]
    state["output"]=json.dumps(output)
    result=view(values)
    assert result["process"][1]["time"] != "—"
    assert result["process"][2]["time"] == "—"
    assert "secret-url" not in json.dumps(result)


def test_fabricated_text_has_no_presentation_and_unknown_is_not_zero():
    assert presentation(project([],True),[]) is None
    values=messages();state=values[1]["parts"][0]["state"];output=json.loads(state["output"])
    output["facts"][0]["statement"]="invented";state["output"]=json.dumps(output)
    result=view(values)
    assert not result["conclusions"]
    assert result["evidence"][3]["value"] == "无法核对"
    assert result["evidence"][0]["value"] == "未获取"


def test_pending_then_complete_and_repeated_projection_is_stable():
    values=messages();values=values[:2];values[1]["parts"][0]["state"]={"status":"running","input":{"scenario_id":"DEMO-CASE-THEFT"}}
    result=view(values)
    assert result["process"][0]["status"]=="running"
    assert all(x["status"]=="pending" for x in result["process"][1:])
    assert result==view(values)


def test_current_turn_and_declined_summary():
    values=messages();values.append({"info":{"role":"user","id":"next"}})
    assert view(values) is None
    values=messages();values[-1]["parts"][0]["state"]["status"]="error"
    assert not view(values)["conclusions"]
    assert view(values)["process"][-1]["status"]=="failed"


def test_presentation_public_contract_and_malformed_inputs():
    from jsonschema import Draft202012Validator
    from control.openapi import schemas
    Draft202012Validator(schemas()["ScenarioPresentation"]).validate(view())
    values=messages();values[1]["parts"][0]["state"]["input"]={"scenario_id":{}}
    assert presentation({"status":"empty"},values) is None
    values=[{"info":{"role":"user","id":"x"}},{"info":{"role":"assistant"},"parts":[{"type":"analysis_result","data":{"conclusions":["fabricated"]}}]}]
    assert presentation(project(values,True),values) is None
