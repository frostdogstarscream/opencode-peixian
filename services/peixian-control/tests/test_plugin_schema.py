from control.plugin_schema import validate_form, redact, merge_secrets
import pytest

SCHEMA={"type":"object","properties":{"connection":{"type":"object","properties":{"label":{"type":"string"},"password":{"type":"string","writeOnly":True}},"additionalProperties":False},"tags":{"type":"array","items":{"type":"string"}}},"additionalProperties":False}


def test_nested_secret_never_returns_and_blank_retains():
    validate_form(SCHEMA)
    original={"connection":{"label":"synthetic","password":"private-synthetic-value"},"tags":["one"]}
    safe,status=redact(SCHEMA,original)
    assert safe=={"connection":{"label":"synthetic"},"tags":["one"]}
    assert status=={"connection":{"password":True}}
    merged=merge_secrets(SCHEMA,{"connection":{"label":"changed"},"tags":[]},original)
    assert merged["connection"]=={"label":"changed","password":"private-synthetic-value"}
    assert original["connection"]["label"]=="synthetic"


@pytest.mark.parametrize("schema",[
 {"type":"object"},
 {"type":"object","properties":{},"additionalProperties":True},
 {"type":"array","items":{"type":"object","properties":{}}},
 {"type":"array","items":{"type":"string","format":"password"}},
])
def test_unrenderable_or_secret_array_schemas_cannot_be_published(schema):
    with pytest.raises(ValueError):
        validate_form(schema)


def test_tool_display_fields_hide_private_details():
    from control.app import public_messages
    parts=public_messages([{"info":{"id":"m","role":"assistant"},"parts":[{"type":"tool","tool":"sample","state":{"status":"completed","input":{"query":"synthetic","password":"private"},"output":'{"count":3,"url":"https://private.invalid","path":"/run/secrets/key","summary":"ready"}'}}]}],{"sample":{"input_fields":["query","password"],"output_fields":["count","url","path","summary"]}})
    details=parts[0]["parts"][0]["details"]
    assert details=={"inputs":{"query":"synthetic"},"outputs":{"count":3,"summary":"ready"}}
