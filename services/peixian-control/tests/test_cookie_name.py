"""Two in-process applications simulate one browser on two localhost ports."""
from http.cookiejar import CookieJar
import json

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from control.app import create_app
from control.openapi import build_openapi
from control.store import Store
from export_openapi import export_openapi

P = "/api/console/v1"
PASSWORD = "synthetic-cookie-configuration-password"


def synthetic_store(root):
    root.mkdir()
    for name, value in (("key", Fernet.generate_key()),
                        ("worker", b"synthetic-cookie-worker-key-123456789012345"),
                        ("admin", PASSWORD.encode())):
        (root/name).write_bytes(value)
    return Store(root/"data", root/"key", root/"worker", root/"admin")


def login(client):
    response = client.post(P + "/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def test_two_cookie_names_share_a_browser_without_overwriting_or_cross_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_COOKIE_NAME", "project_a_session")
    first = create_app(synthetic_store(tmp_path/"first"))
    monkeypatch.setenv("CONSOLE_COOKIE_NAME", "project_b_session")
    second = create_app(synthetic_store(tmp_path/"second"))
    jar = CookieJar()
    with TestClient(first, base_url="http://localhost:14101") as a, TestClient(second, base_url="http://localhost:14102") as b:
        a.cookies = jar
        b.cookies = jar
        response_a = login(a)
        token_a = a.cookies.get("project_a_session")
        assert response_a.headers["set-cookie"].startswith("project_a_session=")
        response_b = login(b)
        token_b = b.cookies.get("project_b_session")
        assert response_b.headers["set-cookie"].startswith("project_b_session=")
        assert a.cookies.get("project_a_session") == token_a
        assert b.cookies.get("project_b_session") == token_b
        assert {cookie.name for cookie in jar} == {"project_a_session", "project_b_session"}
        assert a.get(P + "/me").json()["user"]["id"] == response_a.json()["user"]["id"]
        assert b.get(P + "/me").json()["user"]["id"] == response_b.json()["user"]["id"]
        assert response_a.json()["user"]["id"] != response_b.json()["user"]["id"]
        # A valid token under a client-selected name is not recognized, even by A.
        assert a.get(P + "/me", headers={"Cookie": "project_b_session=" + token_a}).status_code == 401
        assert b.get(P + "/me", headers={"Cookie": "project_b_session=" + token_a}).status_code == 401
        assert a.get(P + "/me", headers={"Cookie": "project_a_session=" + token_b}).status_code == 401
        # Environment changes after create_app cannot switch either app's name.
        monkeypatch.setenv("CONSOLE_COOKIE_NAME", "late_environment_name")
        assert a.get(P + "/me").status_code == b.get(P + "/me").status_code == 200
        for app, name in ((first, "project_a_session"), (second, "project_b_session")):
            schema = build_openapi(app)
            assert schema["components"]["securitySchemes"]["SessionCookie"]["name"] == name
            description = schema["paths"][P + "/auth/login"]["post"]["responses"]["200"]["headers"]["Set-Cookie"]["description"]
            assert description.startswith(name + " ")
        logout = a.post(P + "/auth/logout")
        assert logout.status_code == 200
        assert len(logout.headers.get_list("set-cookie")) == 1
        assert logout.headers["set-cookie"].startswith("project_a_session=")
        assert "Max-Age=0" in logout.headers["set-cookie"]
        assert {cookie.name for cookie in jar} == {"project_b_session"}
        assert b.cookies.get("project_b_session") == token_b
        assert a.get(P + "/me").status_code == 401
        assert b.get(P + "/me").status_code == 200


def test_default_cookie_compatible_and_client_cannot_choose_name(tmp_path, monkeypatch):
    monkeypatch.delenv("CONSOLE_COOKIE_NAME", raising=False)
    app = create_app(synthetic_store(tmp_path/"default"))
    assert app.state.cookie_name == "px_session"
    with TestClient(app) as client:
        rejected = client.post(P + "/auth/login", json={"username": "admin", "password": PASSWORD, "cookie_name": "caller_name"})
        assert rejected.status_code == 400
        client.headers["X-Console-Cookie-Name"] = "caller_name"
        response = login(client)
        assert response.headers["set-cookie"].startswith("px_session=")
        assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
        assert client.get(P + "/me").status_code == 200
        assert client.post(P + "/auth/logout").headers["set-cookie"].startswith("px_session=")
        assert client.get(P + "/me").status_code == 401
    destination = export_openapi(tmp_path/"default-openapi.json")
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["components"]["securitySchemes"]["SessionCookie"]["name"] == "px_session"


@pytest.mark.parametrize("name", ["", "has space", "tab\tname", "line\r\nInjected", "nonascii_凭据",
                                  "a=b", "a;b", "a,b", "a:b", "a/b", 'a"b', "a\\b", "a(b)",
                                  "a[b]", "a{b}", "a?b", "a@b", "a"*129,
                                  "Path", "secure", "HttpOnly", "SameSite", "Max-Age"])
def test_invalid_cookie_name_refuses_app_creation_before_store_access(name, monkeypatch):
    monkeypatch.setenv("CONSOLE_COOKIE_NAME", name)
    def forbidden():
        raise AssertionError("Invalid cookie configuration must fail before opening a store")
    monkeypatch.setattr("control.app.configured_store", forbidden)
    with pytest.raises(ValueError, match="CONSOLE_COOKIE_NAME"):
        create_app()


@pytest.mark.parametrize("name", ["a", "project_1-session", "a"*128, "framework.!#$%&'*+-^_`|~"])
def test_valid_ascii_token_names_are_captured(name, monkeypatch):
    monkeypatch.setenv("CONSOLE_COOKIE_NAME", name)
    app = create_app()
    assert app.state.cookie_name == name
    assert not hasattr(app.state, "store")
    assert build_openapi(app)["components"]["securitySchemes"]["SessionCookie"]["name"] == name
