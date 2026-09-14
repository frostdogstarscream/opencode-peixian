import asyncio
import json
import os
from pathlib import Path

from fastapi import HTTPException
import pytest

from gateway.plugin_test import run_plugin_test, specification


def manifest(tmp_path, source, *, identity="sample"):
    directory = tmp_path / "plugins" / identity / "1.0.0"
    directory.mkdir(parents=True, exist_ok=True)
    entry = directory / "entry.mjs"
    entry.write_text(source, encoding="utf-8")
    (tmp_path / "plugin-tests.json").write_text(json.dumps({
        identity: {"entry": str(entry), "options": {"credential": "synthetic-private-key"}}}), encoding="utf-8")
    return entry


def test_plugin_specification_scope(tmp_path):
    entry = manifest(tmp_path, "export const value = 1;")
    assert specification(tmp_path, "sample")["entry"] == str(entry.resolve())
    with pytest.raises(HTTPException) as caught:
        specification(tmp_path, "../bad")
    assert caught.value.status_code == 404
    (tmp_path / "plugin-tests.json").write_text(json.dumps({
        "sample": {"entry": str(tmp_path / "outside.mjs"), "options": {}}}))
    with pytest.raises(HTTPException) as caught:
        specification(tmp_path, "sample")
    assert caught.value.status_code == 409


@pytest.mark.skipif(not os.environ.get("BUN_EXECUTABLE"), reason="Requires an explicitly supplied installed Bun test runtime")
def test_plugin_real_bun_export_and_output_redaction(tmp_path):
    manifest(tmp_path, """
        export async function test(options) {
            console.log("synthetic-private-key https://private.example");
            return {ok: options.credential === "synthetic-private-key",
                    message: "synthetic-private-key https://private.example"};
        }
    """)
    result = asyncio.run(run_plugin_test(tmp_path, "sample"))
    assert result == {"supported": True, "ok": True, "message": "Connection test passed"}
    assert "synthetic" not in json.dumps(result)
    manifest(tmp_path, "export const value = 1;")
    assert asyncio.run(run_plugin_test(tmp_path, "sample"))["supported"] is False


@pytest.mark.skipif(not os.environ.get("BUN_EXECUTABLE"), reason="Requires an explicitly supplied installed Bun test runtime")
def test_plugin_invalid_result_and_clean_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_SECRET", "must-not-be-inherited")
    manifest(tmp_path, """
        export async function test() {
            return {ok: process.env.SYNTHETIC_SECRET === undefined, message: "done"};
        }
    """)
    assert asyncio.run(run_plugin_test(tmp_path, "sample"))["ok"] is True
    manifest(tmp_path, "export async function test() { return {ok:'yes',message:'invalid'}; }")
    assert asyncio.run(run_plugin_test(tmp_path, "sample"))["ok"] is False
