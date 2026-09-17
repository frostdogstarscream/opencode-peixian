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


def test_new_volume_labels_and_legacy_inventory(tmp_path):
    manager = object.__new__(runtime.RuntimeManager)
    manager.root, manager.deployment_id, manager.agent_image = tmp_path, 'synthetic-pool', 'test-agent'
    rid, uid = '1'*32, '2'*32
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        return ''
    manager.docker_run = docker
    manager.ensure_volumes({'runtime_id': rid, 'uid': uid}, {'volumes': {'home': {'name': 'px-'+rid+'-home'}}})
    created = next(c for c in calls if c[:2] == ('volume', 'create'))
    assert 'peixian.deployment=synthetic-pool' in created and 'peixian.uid='+uid in created
    def inventory(*args, **kwargs):
        if args[:2] == ('volume', 'ls'):
            return 'legacy-owned-home'
        if args[:2] == ('volume', 'inspect'):
            return json.dumps([{'Labels': {runtime.MANAGED: 'true', 'peixian.runtime_id': rid}}])
        return ''
    manager.docker_run = inventory
    records, complete = manager.pool_inventory([{'runtime_id': rid, 'uid': uid}])
    assert complete and records == [{'runtime_id': rid, 'uid': uid, 'running': False, 'mutation_state': 'idle'}]


def test_restore_rewrites_gateway_permit_endpoint(tmp_path):
    rid = '1'*32
    file = tmp_path/'worker'/'runtimes'/rid/'releases'/'000001'/'compose.json'
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps({'services': {'gateway': {'environment': {
        'PX_CONTROL_URL': 'http://source-console:8080', 'PX_RELAY_URL': 'http://model-relay:8081'}}}}))
    backup.rewrite_host(tmp_path, '/source', 'restored')
    env = json.loads(file.read_text())['services']['gateway']['environment']
    assert env['PX_CONTROL_URL'] == 'http://restored-console:8080'
    assert env['PX_RELAY_URL'] == 'http://model-relay:8081'


def test_release_cannot_reuse_old_profile_for_on_demand():
    release = load("release-check")
    manifest = {"control_schema_version": 5, "platform_config_version": 4,
                "worker_capabilities": ["runtime_pool_v1"], "effective_config": {"runtime_pool": {
                    "runtime_mode": "on_demand", "capacity_wait_enabled": False, "idle_pause_enabled": False}}}
    assert release.runtime_pool_blockers(manifest, {}) == ['pr7_required_profile_cases_missing']
    profile = {"required_cases": ['PR7A-2slot-5account', 'PR7A-v5-restore', 'PR7A-component-compatibility']}
    assert release.runtime_pool_blockers(manifest, profile) == []
    manifest['effective_config']['runtime_pool']['capacity_wait_enabled'] = True
    assert 'pr7_runtime_pool_contract_mismatch' in release.runtime_pool_blockers(manifest, profile)
    assert release.runtime_pool_blockers({"control_schema_version": 4, "platform_config_version": 3}, {}) == []


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
    for name in ("idle_pause_enabled",):
        changed = json.loads(json.dumps(data))
        changed["runtime_pool"][name] = True
        path = tmp_path / "config.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        configured=platform.config.load_config(path)
        assert configured.runtime_pool[name] is True
        with pytest.raises(ValueError):
            configured.verify_control_image(labels)


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
    with s.tx() as db:
        db.execute("UPDATE platform_state SET capacity_wait_enabled=1,pool_policy_version=2 WHERE id=1")
        db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated,capacity_expires_at) VALUES('synthetic-wait',?,'provision','waiting_capacity',1,1,1,9999999999)", (user['id'],))
    meta = backup.database_meta(s.root)
    assert meta['runtime_policy']['capacity_wait_enabled'] == 1
    assert s.one("SELECT status FROM jobs WHERE id='synthetic-wait'")['status']=='waiting_capacity'
    backup.pause_database(s.path)
    assert s.one("SELECT status,error FROM jobs WHERE id='synthetic-wait'")=={'status':'cancelled','error':'recovery_reconfirmation_required'}


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
