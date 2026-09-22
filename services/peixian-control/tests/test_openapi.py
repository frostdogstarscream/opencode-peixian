"""Contract checks use only route metadata: no database, credentials or network."""
import ast
import inspect
import textwrap
import json

import jsonschema
import pytest
from fastapi import Request
from fastapi.openapi.models import OpenAPI
from fastapi.routing import APIRoute

from control.app import create_app
from control.openapi import build_openapi, install_openapi, HTTP_METHODS, P
from export_openapi import export_openapi


@pytest.fixture
def application(monkeypatch):
    def forbidden():
        raise AssertionError("OpenAPI must not initialize the configured store")
    monkeypatch.setattr("control.app.configured_store", forbidden)
    monkeypatch.setenv("CONSOLE_STATIC", "/nonexistent-contract-only-static")
    return create_app()


@pytest.fixture
def document(application):
    return build_openapi(application)


def validator(document, name):
    return jsonschema.Draft202012Validator({
        "$ref": "#/components/schemas/" + name, "components": document["components"],
    })


def test_openapi_is_valid_and_every_reference_resolves(document):
    OpenAPI.model_validate(document)
    for schema in document["components"]["schemas"].values():
        jsonschema.Draft202012Validator.check_schema(schema)

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/")
                target = document
                for segment in value["$ref"][2:].split("/"):
                    target = target[segment]
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(document)


def test_message_body_is_the_restricted_console_contract(document):
    body = document["components"]["schemas"]["MessageBody"]
    assert set(body["properties"]) == {"text", "model_id", "skill_ids", "file_ids", "plugin_ids", "mode", "client_request_id", "agent_id", "context_version", "provider_query", "analysis_task_id", "scope", "source_refs"}
    assert body["required"] == ["text"]
    assert body["additionalProperties"] is False
    valid = {"text": "A synthetic question", "model_id": "opaque-model-id", "skill_ids": ["own-skill"], "file_ids": ["own-file"]}
    validator(document, "MessageBody").validate(valid)
    for invalid in (
        {**valid, "parts": []}, {**valid, "directory": "caller-selected"},
        {**valid, "tenant_id": "other"}, {**valid, "text": "   "},
        {**valid, "file_ids": ["one"] * 6}, {**valid, "skill_ids": ["one"] * 6},
        {**valid, "file_ids": [123]}, {},
    ):
        assert list(validator(document, "MessageBody").iter_errors(invalid))
    operation = document["paths"][P + "/sessions/{sid}/messages"]["post"]
    assert set(operation["requestBody"]["content"]) == {"application/json"}
    assert operation["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("/RunAccepted")
    assert "run_id" in operation["description"]


def test_login_password_and_all_json_bodies_are_explicit(application, document):
    login = document["components"]["schemas"]["LoginBody"]
    assert set(login["properties"]) == {"username", "password"}
    assert set(login["required"]) == {"username", "password"}
    assert login["properties"]["password"]["writeOnly"] is True
    assert list(validator(document, "LoginBody").iter_errors({"username": "synthetic"}))
    assert list(validator(document, "PasswordBody").iter_errors({"current_password": "old", "password": "short"}))
    routes = {(r.path, method.lower()): r for r in application.routes if isinstance(r, APIRoute) for method in r.methods}
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            runtime_path = operation["x-runtime-route"]
            endpoint = routes[(runtime_path, method)].endpoint
            if "await request.json()" in inspect.getsource(endpoint):
                assert "requestBody" in operation, (path, method)
                assert operation["requestBody"]["required"] is True
                body_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
                documented = document["components"]["schemas"][body_ref.rsplit("/", 1)[1]]["properties"]
                tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "body_fields":
                        def literal_fields(value):
                            if isinstance(value,ast.Name):
                                fields=inspect.unwrap(endpoint).__globals__[value.id]
                                assert isinstance(fields,tuple) and all(isinstance(x,str) for x in fields)
                                return fields
                            if isinstance(value,ast.Tuple):
                                result=[]
                                for element in value.elts:
                                    if isinstance(element,ast.Starred):result.extend(literal_fields(element.value))
                                    else:result.append(ast.literal_eval(element))
                                return tuple(result)
                            return ast.literal_eval(value)
                        allowed = literal_fields(node.args[1])
                        assert set(allowed) == set(documented), (path, method)


def test_security_cookie_csrf_bearer_and_worker_are_not_interchangeable(document):
    paths = document["paths"]
    assert paths[P + "/auth/login"]["post"]["security"] == []
    assert paths["/health"]["get"]["security"] == []
    assert paths[P + "/sessions"]["get"]["security"] == [{"BearerToken": []}, {"SessionCookie": []}]
    assert paths[P + "/sessions"]["post"]["security"] == [{"BearerToken": []}, {"SessionCookie": [], "CsrfToken": []}]
    for path, item in paths.items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            if path.startswith("/internal/"):
                assert operation["security"] == [{"WorkerKey": []}]
                assert operation["x-internal"] is True
                assert operation["x-role"] == "worker"
            elif path.startswith(P + "/admin/"):
                assert operation["x-role"] in ("super_admin", "super_admin|admin")
                assert operation["x-roles"] in (["super_admin"], ["super_admin", "admin"])
            elif path.startswith(P + "/"):
                assert all("WorkerKey" not in alternative for alternative in operation["security"])
    assert document["components"]["securitySchemes"]["SessionCookie"]["name"] == "px_session"
    assert document["components"]["securitySchemes"]["CsrfToken"]["name"] == "X-CSRF-Token"


def test_multipart_downloads_sse_and_concrete_action_routes(document):
    paths = document["paths"]
    for path in (P + "/files", P + "/admin/plugins"):
        operation = paths[path]["post"]
        assert set(operation["requestBody"]["content"]) == {"multipart/form-data"}
        schema_name = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[1]
        schema = document["components"]["schemas"][schema_name]
        assert schema["required"] == ["file"]
        assert schema["properties"]["file"]["format"] == "binary"
    assert "text/event-stream" in paths[P + "/events"]["get"]["responses"]["200"]["content"]
    for path in (P + "/files/{fid}/download", P + "/results/{fid}/download"):
        assert "application/octet-stream" in paths[path]["get"]["responses"]["200"]["content"]
    assert P + "/files/{fid}/{action}" not in paths
    assert P + "/permissions/{rid}/reject" not in paths
    assert P + "/questions/{rid}/reject" in paths
    assert paths[P + "/questions/{rid}/reject"]["post"]["requestBody"]["required"] is True
    assert paths[P + "/admin/users/{uid}/runtime/{action}"]["post"]["parameters"][1]["schema"]["enum"] == ["pause", "resume", "retry", "apply"]


def test_all_routes_are_accounted_for_and_export_is_offline(application, document, tmp_path):
    covered = {(operation["x-runtime-route"], method) for item in document["paths"].values()
               for method, operation in item.items() if method in HTTP_METHODS}
    for route in application.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == "/health" or route.path.startswith((P + "/", "/internal/worker/")):
            for method in route.methods:
                assert (route.path, method.lower()) in covered
    assert not hasattr(application.state, "store")
    target = export_openapi(tmp_path / "contract.json")
    serialized = target.read_text(encoding="utf-8")
    saved = json.loads(serialized)
    assert saved == document
    assert "servers" not in saved
    for forbidden in ("127.0.0.1", "localhost", ".secrets", "console-test", "console-other", "api.deepseek.com"):
        assert forbidden not in serialized
    assert not hasattr(application.state, "store")


def test_install_uses_cache_and_unknown_api_routes_fail_closed(application):
    install_openapi(application)
    first = application.openapi()
    assert application.openapi() is first

    @application.post(P + "/future-unsupported-contract")
    async def future(request: Request):
        return await request.json()

    with pytest.raises(ValueError, match="Undocumented public API route"):
        build_openapi(application)


def test_plugin_version_schemas_and_nested_credential_state(document):
    from control.plugin_schema import redact
    form = {"type": "object", "properties": {
        "connection": {"type": "object", "properties": {
            "label": {"type": "string"},
            "password": {"type": "string", "writeOnly": True},
        }, "additionalProperties": False},
    }, "additionalProperties": False}
    safe, state = redact(form, {"connection": {"label": "synthetic", "password": "synthetic-private"}})
    plugin = {"id": "synthetic", "version": "2.0.0", "name": "Fixture", "description": "",
              "versions": ["2.0.0", "1.0.0"], "config_schema": form,
              "schemas": {"2.0.0": form, "1.0.0": form},
              "installed": {"version": "1.0.0", "enabled": True, "config": safe,
                            "credentials_configured": state, "state": "pending"}}
    validator(document, "Plugin").validate(plugin)
    assert "synthetic-private" not in json.dumps(plugin)
    assert state == {"connection": {"password": True}}
    assert list(validator(document, "Plugin").iter_errors({k: v for k, v in plugin.items() if k != "schemas"}))
    for invalid in ({"password": "secret"}, {"connection": {"password": None}}, {"connection": ["secret"]}):
        changed = {**plugin, "installed": {**plugin["installed"], "credentials_configured": invalid}}
        assert list(validator(document, "Plugin").iter_errors(changed))
    validator(document, "CredentialState").validate({"connection": {"nested": {"password": False}}})


def test_public_tool_details_use_filtered_scalar_maps(document):
    from control.app import public_messages
    raw = [{"info": {"id": "message", "role": "assistant"}, "parts": [{
        "type": "tool", "tool": "synthetic",
        "state": {"status": "completed", "input": {"query": "fixture", "nested": {"value": "hidden"}},
                  "output": json.dumps({"count": 3, "ok": True, "summary": "ready", "list": [1], "empty": None})},
    }]}]
    result = public_messages(raw, {"synthetic": {"input_fields": ["query", "nested"],
                                               "output_fields": ["count", "ok", "summary", "list", "empty"]}})[0]
    validator(document, "Message").validate(result)
    details = result["parts"][0]["details"]
    assert details == {"inputs": {"query": "fixture"}, "outputs": {"count": 3, "ok": True, "summary": "ready"}}
    for invalid in ({"nested": {}}, {"list": []}, {"empty": None}, {"text": "x" * 301}):
        changed = {**result, "parts": [{**result["parts"][0], "details": {**details, "outputs": invalid}}]}
        assert list(validator(document, "Message").iter_errors(changed))
