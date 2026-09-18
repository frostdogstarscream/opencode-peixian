import copy
import json
import pytest
from control.scenario_evidence import DATA, project, night


def messages(scenario="DEMO-CASE-GAMBLING"):
    context = DATA["scenarios"][scenario]
    values = [{"info": {"role": "user", "id": "msg_user"}, "parts": []}]
    def add(tool, args, output):
        values.append({"info": {"role": "assistant", "id": "msg_"+str(len(values))}, "parts": [{"type": "tool", "tool": tool, "state": {"status": "completed", "input": args, "output": json.dumps(output)}}]})
    add("peixian_get_scenario_context", {"scenario_id": scenario}, context)
    for module in context["required_modules"]:
        data = DATA["records"][module]
        add("peixian_get_"+module+"_records", {}, {**data, "items": data["records"]})
    return values


@pytest.mark.parametrize("scenario", list(DATA["scenarios"]))
def test_complete_projection_preserves_sources(scenario):
    result = project(messages(scenario), True)
    assert result["status"] == "complete"
    assert result["scenario"]["scenario_id"] == scenario
    assert result["cards"] and result["summary"]
    allowed = {row["record_id"] for v in DATA["records"].values() for row in v["records"]}
    allowed.update(f["record_id"] for c in DATA["scenarios"].values() for f in c["facts"])
    assert all(card["id"] in allowed for card in result["cards"])


def test_revoked_grant_and_old_turn_never_display_records():
    values = messages()
    assert project(values, False)["cards"] == []
    values += [{"info": {"role": "user", "id": "new"}, "parts": [{"type": "text", "text": "DEMO-FND-999"}]}]
    assert project(values, True)["cards"] == []


@pytest.mark.parametrize("mutation", ["snapshot", "fabricated", "failed", "wrong_args", "secret", "no_context"])
def test_invalid_evidence_is_not_projected(mutation):
    values = messages()
    part = values[2]["parts"][0]
    if mutation == "snapshot":
        data = json.loads(part["state"]["output"]); data["snapshot_id"] = "old"; part["state"]["output"] = json.dumps(data)
    if mutation == "fabricated":
        data = json.loads(part["state"]["output"]); data["items"][0]["record_id"] = "DEMO-X999"; part["state"]["output"] = json.dumps(data)
    if mutation == "failed": part["state"]["status"] = "error"
    if mutation == "wrong_args": part["state"]["input"] = {"url": "http://private"}
    if mutation == "secret": part["state"]["output"] = "secret-token-in-error"
    if mutation == "no_context": values.pop(1)
    result = project(values, True)
    assert result["status"] == "partial"
    assert not any(card["id"].startswith("DEMO-NGT") for card in result["cards"])
    assert "secret-token" not in json.dumps(result)


def test_model_prose_and_html_never_become_cards():
    values = [{"info": {"role": "user"}}, {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "<script>alert(1)</script> DEMO-FND-999 已完成取数"}]}]
    assert project(values, True)["cards"] == []


@pytest.mark.parametrize("time,expected", [("2026-09-14T21:59:00+08:00",False),("2026-09-14T22:00:00+08:00",True),("2026-09-15T05:59:00+08:00",True),("2026-09-15T06:00:00+08:00",False),("2026-09-14T16:00:00+00:00",True)])
def test_night_boundary(time, expected):
    assert night(time) is expected


def test_no_same_frame_promotion_or_transaction_pairing():
    result = project(messages(), True)
    row = next(c for c in result["cards"] if c["id"] == "DEMO-POR-001")
    assert {"label": "记录类型", "value": "same_frame"} in row["fields"]
    assert len([c for c in result["cards"] if c["id"].startswith("DEMO-FND")]) == 3


def test_missing_observation_stays_unknown():
    result = project(messages("DEMO-CASE-THEFT"), True)
    unknown = next(c for c in result["cards"] if c["id"] == "DEMO-CTX-T04")
    assert "无法判断" in unknown["description"]
    assert "不证明作案" in next(c for c in result["cards"] if c["id"] == "DEMO-CTX-T02")["description"]


def test_applied_version_and_current_grants(context):
    from test_control import create_user
    from control.scenario_evidence import permitted
    store, app, admin = context
    user = create_user(admin)
    plugin = {"id": "peixian-synthetic-records", "manifest": {"version": "1.1.0", "tools": ["peixian_get_scenario_context"]}}
    with store.tx() as db:
        db.execute("UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?", (store.encrypt({"plugins": [plugin]}), user["id"]))
    assert not permitted(store, user["id"])
    with store.tx() as db:
        db.execute("INSERT INTO grants(uid,kind,resource) VALUES(?,?,?)", (user["id"], "plugin", "peixian-synthetic-records"))
    assert permitted(store, user["id"])
    with store.tx() as db:
        db.execute("UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?", (store.encrypt({"plugins": [plugin, {"id": "other", "manifest": {"tools": ["peixian_get_scenario_context"]}}]}), user["id"]))
    assert not permitted(store, user["id"])


def test_evidence_management_and_anonymous_denied(context):
    from test_control import P
    from client_helpers import TestClient
    store, app, admin = context
    assert admin.get(P + "/sessions/ses_any/evidence").status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.get(P + "/sessions/ses_any/evidence").status_code == 401

from test_control import context


def test_projected_response_matches_public_contract():
    from jsonschema import Draft202012Validator
    from control.openapi import schemas
    validator = Draft202012Validator(schemas()["ScenarioEvidence"])
    for scenario in DATA["scenarios"]:
        validator.validate(project(messages(scenario), True))
    validator.validate(project([], False))
