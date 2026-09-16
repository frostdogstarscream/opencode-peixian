"""Control replacement network repair uses synthetic Docker records only."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("control_network_restore_tests", ROOT / "platform-manage.py")
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def environment(tmp_path, monkeypatch, *, paused=False, missing=False, attached=False):
    rid, uid = "a" * 32, "b" * 32
    cfg = SimpleNamespace(worker_root=tmp_path / "worker", control_container="synthetic-console",
                          deployment_id="synthetic")
    directory = cfg.worker_root / "runtimes" / rid
    directory.mkdir(parents=True)
    (directory / "state.json").write_text(json.dumps({"runtime_id": rid, "uid": uid,
        "compose": str(directory / "release/compose.json"), "paused": paused}))
    name = "px-" + rid + "-management"
    labels = {"peixian.console.managed": "true", "peixian.runtime_id": rid,
              "peixian.uid": uid, "peixian.deployment": "synthetic"}
    network = {"Id": "synthetic-network", "Name": name, "Internal": True, "Labels": dict(labels)}
    control = {"Id": "synthetic-control", "Name": "/synthetic-console", "State": {"Running": True},
               "Config": {"Labels": {"peixian.deployment": "synthetic"}}, "NetworkSettings": {"Networks": {}}}
    if attached:
        control["NetworkSettings"]["Networks"][name] = {"NetworkID": network["Id"]}
    containers = [{"Config": {"Labels": {**labels, "com.docker.compose.service": service}},
                   "State": {"Running": not paused, "Restarting": False, "Paused": False}}
                  for service in ("agent", "gateway", "model-relay")]
    commands = []

    def command(*args, **kwargs):
        commands.append(args)
        assert args[0] == "docker"
        if args[1:3] == ("network", "ls"):
            return "" if missing else name
        if args[1] == "ps":
            return "synthetic-runtime-container"
        if args[1:3] == ("inspect", "synthetic-runtime-container"):
            return json.dumps(containers)
        if args[1:3] == ("network", "inspect"):
            assert args[3] == name
            return json.dumps([network])
        if args[1:3] == ("network", "connect"):
            assert args[3:] == (network["Id"], control["Id"])
            control["NetworkSettings"]["Networks"][name] = {"NetworkID": network["Id"]}
            return ""
        if args[1] == "inspect" and args[2] in (cfg.control_container, control["Id"]):
            return json.dumps([control])
        raise AssertionError(args)

    monkeypatch.setattr(manage, "command", command)
    return cfg, network, control, containers, commands


def test_control_replacement_reconnects_registered_network_and_is_idempotent(tmp_path, monkeypatch):
    cfg, network, control, _, commands = environment(tmp_path, monkeypatch)
    assert manage.restore_control_networks(cfg) == {"registered": 1, "connected": 1, "paused_missing": 0}
    assert control["NetworkSettings"]["Networks"][network["Name"]]["NetworkID"] == network["Id"]
    assert manage.restore_control_networks(cfg)["connected"] == 1
    assert sum(args[1:3] == ("network", "connect") for args in commands) == 1


@pytest.mark.parametrize("field,value", [("peixian.uid", "c" * 32), ("peixian.deployment", "another-project"),
                                         ("peixian.runtime_id", "d" * 32), ("peixian.console.managed", "false")])
def test_foreign_network_never_connected(tmp_path, monkeypatch, field, value):
    cfg, network, _, _, commands = environment(tmp_path, monkeypatch)
    network["Labels"][field] = value
    with pytest.raises(manage.PlatformError, match="management_network_owner_mismatch"):
        manage.restore_control_networks(cfg)
    assert not any(args[1:3] == ("network", "connect") for args in commands)


def test_noninternal_network_and_foreign_control_are_rejected(tmp_path, monkeypatch):
    cfg, network, control, _, commands = environment(tmp_path, monkeypatch)
    network["Internal"] = False
    with pytest.raises(manage.PlatformError, match="management_network_owner_mismatch"):
        manage.restore_control_networks(cfg)
    network["Internal"] = True
    control["Config"]["Labels"]["peixian.deployment"] = "another-project"
    with pytest.raises(manage.PlatformError, match="management_control_owner_mismatch"):
        manage.restore_control_networks(cfg)
    assert not any(args[1:3] == ("network", "connect") for args in commands)


def test_only_confirmed_paused_history_may_skip_missing_network(tmp_path, monkeypatch):
    cfg, _, _, containers, commands = environment(tmp_path, monkeypatch, paused=True, missing=True)
    assert manage.restore_control_networks(cfg) == {"registered": 1, "connected": 0, "paused_missing": 1}
    containers[0]["State"]["Running"] = True
    with pytest.raises(manage.PlatformError, match="runtime_management_recovery_pending"):
        manage.restore_control_networks(cfg)
    containers[0]["State"]["Restarting"] = True
    with pytest.raises(manage.PlatformError, match="runtime_management_recovery_pending"):
        manage.restore_control_networks(cfg)
    assert not any(args[1:3] == ("network", "connect") for args in commands)


def test_up_cannot_report_started_before_network_repair(tmp_path, monkeypatch):
    events = []
    cfg = SimpleNamespace(root=tmp_path, compose_path=tmp_path / "compose.json", public_url="https://synthetic")
    monkeypatch.setattr(manage, "check", lambda _: {"images": {"control": "immutable"}})
    monkeypatch.setattr(manage, "render", lambda *_: None)
    monkeypatch.setattr(manage, "module", lambda _: SimpleNamespace(check=lambda *_: {"image_id": "immutable"}))
    monkeypatch.setattr(manage, "command", lambda *args, **kwargs: events.append("replacement"))
    def restore(_):
        events.append("management_repair")
        raise manage.PlatformError("runtime_management_recovery_pending")
    monkeypatch.setattr(manage, "restore_control_networks", restore)
    with pytest.raises(manage.PlatformError, match="runtime_management_recovery_pending"):
        manage.up(cfg)
    assert events == ["replacement", "management_repair"]
