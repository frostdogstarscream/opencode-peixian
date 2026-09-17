"""PR7A deployment contracts, synthetic files and host-command substitutes only."""
import json
from pathlib import Path
import sys

import pytest
from cryptography.fernet import Fernet

from test_platform_delivery import load

platform = load("platform-manage")
backup = load("platform-backup")
runtime = load("console-runtime")


def test_v4_configuration_and_image_capability(tmp_path):
    source = Path(__file__).resolve().parents[1] / "server/platform.on-demand.example.json"
    cfg = platform.config.load_config(source)
    assert cfg.version == 4 and cfg.runtime_pool["runtime_mode"] == "on_demand"
    assert cfg.max_runtimes == 2
    assert platform.compose_config(cfg)["services"]["console"]["environment"]["PX_RUNTIME_MODE"] == "on_demand"
    labels = {"org.peixian.runtime.protocol": "2", "org.peixian.worker.protocol": "2", "org.peixian.control.schema.max": "4"}
    with pytest.raises(ValueError):
        platform.config.image_supports_orchestration(labels, "control", 4)
    labels.update({"org.peixian.control.schema.max": "5", "org.peixian.worker.capabilities": "runtime_pool_v1"})
    platform.config.image_supports_orchestration(labels, "control", 4)
    data = json.loads(source.read_text(encoding="utf-8"))
    for name in ("capacity_wait_enabled", "idle_pause_enabled"):
        changed = json.loads(json.dumps(data))
        changed["runtime_pool"][name] = True
        path = tmp_path / "config.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError):
            platform.config.load_config(path)


def test_metadata_backup_and_restore_does_not_fabricate_volumes(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/peixian-control"))
    from control.store import Store
    from control.schema import validate
    for name, value in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-credential-123456789"), ("admin", b"synthetic-administrator-password")):
        (tmp_path / name).write_bytes(value)
    s = Store(tmp_path / "db", tmp_path / "key", tmp_path / "worker", tmp_path / "admin", runtime_mode="on_demand")
    user, _ = s.create_user("synthetic", "synthetic-password-for-testing")
    meta = backup.database_meta(s.root)
    assert meta["schema_version"] == 5
    assert meta["runtime_metadata"][0]["never_provisioned"] == 1
    assert not (tmp_path / "worker").is_dir()
    backup.pause_database(s.path)
    assert s.user(user["id"])["runtime"]["status"] == "unprovisioned"
    assert s.maintenance_status()["maintenance_mode"] == "frozen"
    with s.read() as db:
        validate(db)


def test_host_inventory_retained_resources_and_orphans(tmp_path):
    manager = object.__new__(runtime.RuntimeManager)
    manager.root, manager.deployment_id = tmp_path, "synthetic-pool"
    rid, uid = "1"*32, "2"*32
    labels = {runtime.MANAGED: "true", "peixian.deployment": "synthetic-pool", "peixian.runtime_id": rid, "peixian.uid": uid}
    def docker(*args, **kwargs):
        if args[0] == "ps":
            return "synthetic-container"
        if args[0] == "inspect":
            return json.dumps([{"Config": {"Labels": labels}, "State": {"Running": True}}])
        return ""
    manager.docker_run = docker
    records, complete = manager.pool_inventory([{"runtime_id": rid, "uid": uid}])
    assert complete and records[0]["running"]
    _, complete = manager.pool_inventory([])
    assert not complete
    (tmp_path / "runtimes" / ("3"*32)).mkdir(parents=True)
    _, complete = manager.pool_inventory([{"runtime_id": rid, "uid": uid}])
    assert not complete
