#!/usr/bin/env python3
"""Publish and provision the isolated synthetic-records plugin on one deployment.

Run this only on the deployment host after the separate records service has
passed its direct contract checks.  The script deliberately reads secrets only
from the deployment's private key files and never prints them.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


PLUGIN_ID = "peixian-synthetic-records"
VERSION = "1.0.0"
CONNECTION_NAME = "沛县七项合成资料服务"
CONNECTION_BASE_URL = "http://172.17.0.1:19462"
TEMPLATE_NAME = "沛县七项合成资料研判（合成演示）"


def acceptance_class(deployment_root: Path):
    source = deployment_root / "source" / "deploy" / "peixian" / "alignment-live-acceptance.py"
    if not source.is_file():
        source = Path("/root/PeiXianDB/frontend-alignment/deploy/peixian/alignment-live-acceptance.py")
    spec = importlib.util.spec_from_file_location("peixian_acceptance", source)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load the deployment acceptance helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Acceptance


def request(api, client, method: str, path: str, **kwargs):
    return api.request(client, method, path, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-root", type=Path, required=True)
    parser.add_argument("--plugin-zip", type=Path, required=True)
    parser.add_argument("--skill-template", type=Path, required=True)
    parser.add_argument("--service-key", type=Path, required=True)
    arguments = parser.parse_args()

    root = arguments.deployment_root.resolve()
    if not arguments.plugin_zip.is_file() or not arguments.skill_template.is_file() or not arguments.service_key.is_file():
        raise RuntimeError("the plugin package, skill template, or service key is missing")
    template = arguments.skill_template.read_text(encoding="utf-8")
    key = arguments.service_key.read_text(encoding="utf-8").strip()
    if len(key) < 16:
        raise RuntimeError("service key is invalid")

    api = acceptance_class(root)(root)
    try:
        administrator = api.login("admin")
        published = request(api, administrator, "GET", "/admin/plugins")["items"]
        matching_plugins = [item for item in published if item["id"] == PLUGIN_ID and item["version"] == VERSION]
        if len(matching_plugins) > 1:
            raise RuntimeError("duplicate plugin version is unsafe")
        if not matching_plugins:
            response = request(api, administrator, "POST", "/admin/plugins", files={
                "file": ("peixian-synthetic-records-1.0.0.zip", arguments.plugin_zip.read_bytes(), "application/zip")
            })
            if response.get("id") != PLUGIN_ID or response.get("version") != VERSION:
                raise RuntimeError("published plugin identity does not match the requested version")
            plugin_action = "published"
        else:
            plugin_action = "already_published"

        connections = request(api, administrator, "GET", "/admin/connections")["items"]
        matching_connections = [item for item in connections if item.get("name") == CONNECTION_NAME]
        if len(matching_connections) > 1:
            raise RuntimeError("duplicate named connection is unsafe")
        expected_connection = {
            "base_url": CONNECTION_BASE_URL,
            "auth_type": "bearer",
            "allowed_methods": ["GET", "POST"],
            "allowed_paths": ["/health", "/v1/demo/records/query"],
            "timeout_seconds": 10,
            "max_response_bytes": 1048576,
            "enabled": True,
        }
        if matching_connections:
            connection = matching_connections[0]
            if any(connection.get(field) != value for field, value in expected_connection.items()):
                raise RuntimeError("existing named connection does not match the fixed private-service policy")
            if not connection.get("secret_configured"):
                raise RuntimeError("existing named connection has no configured secret")
            connection_action = "already_present"
        else:
            connection = request(api, administrator, "POST", "/admin/connections", json={
                "name": CONNECTION_NAME,
                **expected_connection,
                "secret": key,
            })
            connection_action = "created"
        connection_id = connection["id"]

        check = request(api, administrator, "POST", f"/admin/connections/{connection_id}/test", json={
            "method": "GET", "path": "/health"
        })
        if not check.get("ok") or check.get("status") != 200:
            raise RuntimeError("platform connection health test did not pass")

        request(api, administrator, "PUT", f"/admin/plugins/{PLUGIN_ID}/{VERSION}/connections", json={
            "bindings": {"peixian_records": connection_id}
        })

        templates = request(api, administrator, "GET", "/admin/templates")["items"]
        template_matches = [item for item in templates if item.get("name") == TEMPLATE_NAME]
        if len(template_matches) > 1:
            raise RuntimeError("duplicate named skill template is unsafe")
        if template_matches:
            if template_matches[0].get("content") != template:
                raise RuntimeError("existing named skill template differs and will not be overwritten")
            template_action = "already_present"
        else:
            request(api, administrator, "POST", "/admin/templates", json={
                "name": TEMPLATE_NAME,
                "description": "七项只读合成资料工具的可复制个人 Skill 模板。",
                "content": template,
            })
            template_action = "created"

        users = request(api, administrator, "GET", "/admin/users")["items"]
        ordinary_users = [item for item in users if item.get("role") == "user" and item.get("active") is True]
        if not ordinary_users:
            raise RuntimeError("no active ordinary users were found")
        grants_changed = 0
        for user in ordinary_users:
            grants = sorted(set(user.get("plugin_ids", [])) | {PLUGIN_ID})
            if grants != sorted(user.get("plugin_ids", [])):
                request(api, administrator, "PATCH", f"/admin/users/{user['id']}", json={"plugin_ids": grants})
                grants_changed += 1

        tests = 0
        for user in ordinary_users:
            username = user["username"]
            client = api.login(username)
            request(api, client, "PUT", f"/plugins/{PLUGIN_ID}", json={"version": VERSION, "enabled": True, "config": {}})
            state = request(api, client, "GET", "/me/runtime")
            if not state.get("ready") and "start" in state.get("allowed_actions", []):
                request(api, client, "POST", "/me/runtime/start", json={})
            api.ready(client, seconds=420)
            result = request(api, client, "POST", f"/plugins/{PLUGIN_ID}/test", json={})
            if result.get("ok") is not True:
                raise RuntimeError("plugin health test failed for an active ordinary user")
            tests += 1

        print(json.dumps({
            "plugin": plugin_action,
            "connection": connection_action,
            "skill_template": template_action,
            "active_ordinary_users": len(ordinary_users),
            "grants_changed": grants_changed,
            "plugin_connection_tests": tests,
        }, ensure_ascii=False, sort_keys=True))
    finally:
        api.clients.close()


if __name__ == "__main__":
    main()
