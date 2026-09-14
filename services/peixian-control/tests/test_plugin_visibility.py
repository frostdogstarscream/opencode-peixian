"""HTTP regressions for installed-version plugin credential visibility."""
import io
import json
import zipfile

import pytest

from test_control import context, create_user, login_user, plugin_zip, P
from control.openapi import build_openapi
from test_openapi import validator


def second_version_package():
    archive_bytes = io.BytesIO()
    manifest = {"id": "synthetic-echo", "version": "2.0.0", "name": "Synthetic",
                "entry": "entry.mjs", "tools": ["synthetic_echo"],
                "config_schema": {"type": "object", "properties": {"label": {"type": "string"}},
                                  "required": ["label"], "additionalProperties": False}}
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("entry.mjs", "export default async () => ({});")
    return archive_bytes.getvalue()


@pytest.mark.parametrize("missing_manifest", [False, True], ids=["disabled_installed_version", "missing_installed_manifest"])
def test_plugin_secret_uses_installed_schema_or_fails_closed(context, missing_manifest):
    store, app, administrator = context
    account = create_user(administrator)
    assert administrator.post(P + "/admin/plugins", files={"file": ("old.zip", plugin_zip())}).status_code == 200
    assert administrator.patch(P + "/admin/users/" + account["id"], json={"plugin_ids": ["synthetic-echo"]}).status_code == 200
    client = login_user(app, "person-a")
    try:
        private = "synthetic-private-old-version-token"
        assert client.put(P + "/plugins/synthetic-echo",
                          json={"version": "1.0.0", "config": {"label": "fixture", "token": private}}).status_code == 200
        assert administrator.post(P + "/admin/plugins", files={"file": ("new.zip", second_version_package())}).status_code == 200
        if missing_manifest:
            # Simulate incomplete catalog recovery; never touch a real database.
            with store.tx() as database:
                database.execute("DELETE FROM plugins WHERE id=? AND version=?", ("synthetic-echo", "1.0.0"))
        else:
            assert administrator.patch(P + "/admin/plugins/synthetic-echo/1.0.0", json={"enabled": False}).status_code == 200
        response = client.get(P + "/plugins")
        assert response.status_code == 200
        assert private not in response.text
        plugin = response.json()["items"][0]
        assert set(plugin["schemas"]) == {"2.0.0"}
        assert plugin["installed"]["version"] == "1.0.0"
        assert plugin["installed"]["state"] == "unavailable"
        assert plugin["installed"]["config"] == ({} if missing_manifest else {"label": "fixture"})
        assert plugin["installed"]["credentials_configured"] == ({} if missing_manifest else {"token": True})
        validator(build_openapi(app), "Plugin").validate(plugin)
    finally:
        client.__exit__(None, None, None)
