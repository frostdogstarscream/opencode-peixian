"""Protocol boundaries use deterministic host/model fixtures; no Docker access."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("r2_worker_tests", ROOT / "console-worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
runtime = worker.runtime


def fixture(tmp_path, *, busy=False, reject_applying=False, lose_complete=False, idle=False):
    uid, rid, jid = "1" * 32, "2" * 32, "3" * 32
    snapshot = {"uid": uid, "runtime_id": rid, "revision": 1,
                "private": {"runtime_key": "synthetic-runtime-key", "gateway_key": "synthetic-gateway-key"}}
    digest = hashlib.sha256(runtime.json_bytes(snapshot)).hexdigest()
    job = {"id": jid, "uid": uid, "runtime_id": rid, "action": "provision", "lease": "synthetic-lease",
           "revision": 1, "attempt": 1, "phase": "claimed", "recovery_required": False,
           "state_version": 1, "gate_epoch": 0, "spec_digest": digest, "reason": "normal"}
    if idle:
        job.update(action='pause',reason='idle_timeout',idle_activity_version=1,idle_gateway_boot_id='boot-before')
    records, receipts, observations = [], {}, {}
    state = {"protocol_version": 2, "runtime_id": rid, "boot_id": "boot-before", "gate_epoch": 0,
             "state_version": 1, "owner": "runtime:" + rid, "revision": 1, "gate": "open",
             "relay": {"boot_id": "relay-before", "gate": "open"}}
    active = busy

    class Manager:
        root = tmp_path

        def attach_control(self, runtime_id, uid):
            records.append(("attach", runtime_id))

        def reconcile(self, **kwargs):
            records.append(("reconcile", kwargs["batch"]))
            return []

        def runtime_request(self, snapshot, method, endpoint, body=None):
            if method == "POST":
                records.append(("gate", body["action"]))
                state.update({key: body[key] for key in ("owner", "gate_epoch", "state_version")})
                state["gate"] = "draining" if body["action"] == "drain" else "closed"
                if body["action"] == "close":
                    state["relay"]["gate"] = "closed"
            return json.loads(json.dumps(state))

        def observe(self, current, snapshot, host_boot_id):
            value = {"observation_id": str(len(observations) + 1), "runtime_id": rid,
                     "job_id": jid, "attempt": 1, "lease": "synthetic-lease",
                     "state_version": current["state_version"], "gate_epoch": current["gate_epoch"],
                     "complete": True, "mutation_state": "idle", "accepting": active and state["gate"] == "open",
                     "egress_closed": not active or state["relay"]["gate"] == "closed",
                     "activity_count": 1 if busy else 0, "applied_revision": 1 if active else 0,
                     "spec_digest": digest if active else None}
            observations[value["observation_id"]] = value
            return value, json.loads(json.dumps(state)) if active else None

        def apply(self, current, snapshot, download, heartbeat):
            nonlocal active
            assert current["phase"] == "applying" and current["mutation_authorized"] is True
            assert ("phase", "applying") in records
            active = True
            state.update(boot_id="boot-after", gate="closed", gate_epoch=0)
            state["relay"] = {"boot_id": "relay-after", "gate": "closed"}
            records.append(("mutation", "up"))
            return {"ok": True}

    def dispatch(request):
        assert request.headers.get("X-Peixian-Protocol") == "2"
        path = request.url.path
        if path.endswith("/reconcile"):
            records.append(("reconcile", 4))
            return httpx.Response(200, json={"protocol_version": 2, "items": []})
        if path.endswith("/claim"):
            return httpx.Response(200, json={"protocol_version": 2, "job": dict(job), "spec": snapshot})
        if request.method == "GET":
            return httpx.Response(200, json={"job": dict(job), "receipt": receipts.get(request.url.params.get("operation_id"))})
        body = json.loads(request.content)
        if path.endswith("/observations") or path.endswith("/heartbeat"):
            return httpx.Response(200, json={"ok": True})
        kind = path.rsplit("/", 1)[-1]
        if kind == "phase":
            if reject_applying and body["phase"] == "applying":
                return httpx.Response(409, json={"message": "blocked"})
            if body["phase"] == "applying":
                assert observations[body["observation_id"]]["egress_closed"] is True
            job["phase"] = body["phase"]
            job["state_version"] += 1
            if job["phase"] != "applying":
                job["gate_epoch"] += 1
            records.append((kind, job["phase"]))
        elif kind == "boot":
            job["state_version"] += 1
            job["gate_epoch"] += 1
            records.append((kind, body["gateway_boot_id"]))
        elif kind in ("complete", "cancel-idle"):
            records.append((kind, body))
            job["state_version"] += 1
            job["phase"] = "finished"
        receipt = {"receipt_status": "recorded", "job_id": jid, "attempt": 1, "operation_id": body["operation_id"],
                   "state_version": job["state_version"], "gate_epoch": job["gate_epoch"],
                   "phase_after_commit": job["phase"], "gate_action": "drain" if job["phase"] == "draining" else "close"}
        receipts[body["operation_id"]] = receipt
        if kind == "complete" and lose_complete:
            raise httpx.ReadError("synthetic dropped response", request=request)
        return httpx.Response(200, json=receipt)

    client = httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://127.0.0.1")
    return worker.Worker(client, Manager()), records, client


def test_idle_unknown_proof_cancels_without_mutation_or_failure_loop(tmp_path):
    runner,records,client=fixture(tmp_path,busy=True,idle=True)
    with client:
        assert runner.once()
    assert not [item for item in records if item[0] in ('mutation','complete')]
    assert len([item for item in records if item[0]=='cancel-idle'])==1


@pytest.mark.parametrize('component',['gateway','relay'])
def test_idle_tick_never_submits_recovery_as_complete(tmp_path,component):
    values=[]
    state={'boot_id':'boot','activity':{'complete':True,'total':0},'gate':'open',
           'permit_scopes':{'intake':True},'needs_reconcile':component=='gateway',
           'relay':{'needs_reconcile':component=='relay'},'idle_proof':{'complete':True,'sequence':1,'idle_seconds':600}}
    def dispatch(request):
        if request.url.path.endswith('/tick'):
            return httpx.Response(200,json={'protocol_version':2,'items':[{'uid':'user','runtime_id':'runtime','state_version':1,'spec':{}}]})
        values.append(json.loads(request.content));return httpx.Response(200,json={'accepted':False})
    manager=SimpleNamespace(root=tmp_path,runtime_request=lambda *args:state,mutation_state=lambda _: 'idle')
    with httpx.Client(transport=httpx.MockTransport(dispatch),base_url='http://127.0.0.1') as api:
        runner=worker.Worker(api,manager,idle_policy={'scheduler_batch':8})
        runner.idle_tick()
    assert len(values)==1 and values[0]['complete'] is False


def test_applying_ack_boot_registration_and_one_mutation_on_lost_complete(tmp_path):
    runner, records, client = fixture(tmp_path, lose_complete=True)
    output = io.StringIO()
    with client, contextlib.redirect_stdout(output):
        assert runner.once()
    assert [item for item in records if item[0] == "mutation"] == [("mutation", "up")]
    assert [item for item in records if item[0] == "phase"] == [
        ("phase", "draining"), ("phase", "closing"), ("phase", "applying")]
    assert records.index(("boot", "boot-after")) < records.index(("gate", "close"))
    assert len([item for item in records if item[0] == "complete"]) == 1
    assert "synthetic-lease" not in output.getvalue()
    saved = "".join(path.read_text() for path in (tmp_path / "receipts").rglob("*.json"))
    assert "synthetic-lease" not in saved and "synthetic-runtime-key" not in saved


def test_busy_runtime_defers_without_host_mutation_or_sleep(tmp_path):
    runner, records, client = fixture(tmp_path, busy=True)
    with client:
        assert runner.once()
    assert ("gate", "drain") in records
    assert not [item for item in records if item[0] == "mutation"]
    completed = [item[1] for item in records if item[0] == "complete"]
    assert completed[0]["deferred"] is True
    assert completed[0]["defer_reason"] == "runtime_busy"
    assert "not_before" not in completed[0] and "cleanup_confirmed" not in completed[0]


def test_rejected_applying_cannot_reach_host_mutation(tmp_path):
    runner, records, client = fixture(tmp_path, reject_applying=True)
    with client:
        assert runner.once()
    assert not [item for item in records if item[0] == "mutation"]


def test_reconcile_state_change_skips_old_observation_and_still_claims(tmp_path):
    requests = []
    candidates = [{"runtime_id": str(index) * 32, "uid": str(index + 2) * 32, "state_version": 3}
                  for index in (1, 2)]

    def dispatch(request):
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"protocol_version": 2, "items": candidates})
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"protocol_version": 2, "job": None})
        body = json.loads(request.content)
        return httpx.Response(409 if body["runtime_id"] == candidates[0]["runtime_id"] else 200,
                              json={"message": "synthetic superseded state"})

    manager = SimpleNamespace(root=tmp_path,
        components=lambda _: ({name: "running" for name in ("agent", "gateway", "relay")}, True),
        mutation_state=lambda _: "idle")
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://127.0.0.1") as api:
        runner = worker.Worker(api, manager)
        assert runner.once() is False
    assert requests == [("GET", "/internal/worker/reconcile"), ("POST", "/internal/worker/reconcile"),
                        ("POST", "/internal/worker/reconcile"), ("POST", "/internal/worker/claim")]


def test_config_v3_limits_and_runtime_secrets_do_not_reach_agent(tmp_path):
    path = ROOT / "platform-config.py"
    loaded = importlib.util.spec_from_file_location("orchestration_config_test", path)
    config = importlib.util.module_from_spec(loaded)
    sys.modules[loaded.name] = config
    loaded.loader.exec_module(config)
    raw = json.loads((ROOT / "server/platform.50-io.example.json").read_text(encoding="utf-8"))
    raw.update(version=3, profile="single-host-orchestration", max_runtimes=4, orchestration={})
    target = tmp_path / "config.json"
    target.write_text(json.dumps(raw), encoding="utf-8")
    cfg = config.load_config(target)
    assert cfg.orchestration["worker_lease_seconds"] == 90
    assert cfg.orchestration_environment["PX_R2_RECONCILE_BATCH"] == "4"
    raw["orchestration"] = {"worker_heartbeat_seconds": 60}
    target.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="inconsistent_orchestration"):
        config.load_config(target)
    snapshot = {"uid": "1" * 32, "runtime_id": "2" * 32, "revision": 1,
                "private": {"runtime_key": "synthetic", "relay_management_key": "synthetic"}}
    services = runtime.compose_spec(snapshot, tmp_path, agent_image="a:1", gateway_image="g:1")["services"]
    agent = json.dumps(services["agent"])
    assert "runtime-key" not in agent and "relay-management-key" not in agent
    assert "runtime-key" not in json.dumps(services["model-relay"])
    assert services["gateway"]["environment"]["PX_RUNTIME_PROTOCOL"] == "2"
    assert len(services) == 3


@pytest.mark.parametrize("lost_action", ["phase:draining", "phase:closing", "phase:applying", "boot", "complete"])
def test_real_v4_store_and_worker_complete_one_registered_revision(tmp_path, monkeypatch, lost_action, recovery=None):
    backend = ROOT.parents[1] / "services/peixian-control"
    monkeypatch.syspath_prepend(str(backend))
    from cryptography.fernet import Fernet
    from fastapi import HTTPException
    from control.store import Store
    from control.orchestration import Orchestration
    from control.worker_api import runtime_spec
    for name, data in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-key-12345678901234567890"),
                       ("admin", b"synthetic-admin-password-12345678")):
        (tmp_path / name).write_bytes(data)
    idle_recovery = recovery is not None and recovery.startswith('idle_')
    store = Store(tmp_path / "db", tmp_path / "key", tmp_path / "worker", tmp_path / "admin",
                  runtime_mode='on_demand' if idle_recovery else 'eager')
    if idle_recovery:
        store.pool_settings.update(idle_pause_enabled=True,idle_timeout_seconds=60,min_ready_seconds=0,resume_cooldown_seconds=0)
        with store.tx() as db:
            db.execute('UPDATE platform_state SET pool_policy_version=3,idle_pause_enabled=1')
    user, requested = store.create_user("synthetic-round2", "synthetic-user-password-12345678")
    if idle_recovery:
        from control.runtime_pool import start
        with store.tx() as db: requested = start(store, db, user['id'])['job']
    orchestration = Orchestration(store)

    class Manager(runtime.RuntimeManager):
        def __init__(self):
            self.root = tmp_path / "host"
            self.root.mkdir()
            self.active, self.count = False, 0
            self.current = None

        def attach_control(self, runtime_id, uid):
            assert len(runtime_id)==32 and len(uid)==32

        def components(self, snapshot):
            return {key: "running" if self.active else "stopped" for key in ("agent", "gateway", "relay")}, True

        def runtime_request(self, snapshot, method, endpoint, body=None):
            if method == "POST":
                self.current.update({key: body[key] for key in ("gate_epoch", "state_version", "owner")})
                self.current["gate"] = "draining" if body["action"] == "drain" else "closed"
                if recovery == 'idle_closing_changed' and body['action'] == 'close' and store.one('SELECT phase FROM jobs WHERE id=?',(requested['id'],))['phase'] == 'closing':
                    self.current['idle_proof']['sequence'] += 1
                if body["action"] == "close":
                    self.current["relay"]["gate"] = "closed"
            return json.loads(json.dumps(self.current))

        def apply(self, job, snapshot, download, heartbeat):
            assert store.one("SELECT phase FROM jobs WHERE id=?", (job["id"],))["phase"] == "applying"
            self.count += 1
            heartbeat()
            if job['action'] == 'pause':
                self.active = False
                return {'ok': True}
            release = self.directory(snapshot["runtime_id"]) / "releases/1"
            runtime.write_json(release / "publication.json", {"digest": job["spec_digest"]})
            runtime.write_json(self.directory(snapshot["runtime_id"]) / "state.json", {
                "uid": snapshot["uid"], "runtime_id": snapshot["runtime_id"], "revision": 1,
                "compose": str(release / "compose.json"), "paused": False})
            self.active = True
            self.current = {"protocol_version": 2, "runtime_id": snapshot["runtime_id"], "boot_id": "gateway-boot-new",
                "gate_epoch": 0, "state_version": 0, "owner": "bootstrap", "gate": "closed", "revision": 1,
                "relay": {"boot_id": "relay-boot-new", "gate": "closed"},
                "activity": {"complete": True, "unknown": False, "idle": True, "total": 0},
                'needs_reconcile':False,'idle_proof':{'complete':True,'sequence':4,'idle_seconds':61}}
            self.current['relay']['needs_reconcile'] = False
            return {"ok": True}

    lost = False
    def dispatch(request):
        nonlocal lost
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        try:
            if path.endswith("/reconcile"):
                value = orchestration.reconcile_candidates(4) if request.method == "GET" else orchestration.reconcile(body)
            elif path.endswith("/claim"):
                value = orchestration.claim(runtime_spec)
            elif path.endswith("/observations"):
                value = orchestration.observe(body)
            elif request.method == "GET":
                value = orchestration.query(requested["id"], int(request.url.params["attempt"]), request.url.params.get("operation_id"))
            else:
                action = path.rsplit("/", 1)[-1]
                value = getattr(orchestration, action)(requested["id"], body)
                marker = action + ":" + body["phase"] if action == "phase" else action
                if marker == lost_action and not lost:
                    lost = True
                    raise httpx.ReadError("synthetic response lost after DB commit", request=request)
            return httpx.Response(200, json=value)
        except HTTPException as exc:
            return httpx.Response(exc.status_code, headers={"X-Peixian-Worker-Code": getattr(exc, "worker_code", "worker_rejected")}, json={"detail": exc.detail})
    manager = Manager()
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://127.0.0.1") as client:
        assert worker.Worker(client, manager).once()
    row = store.one("SELECT * FROM runtimes WHERE uid=?", (user["id"],))
    assert row["revision"] == row["desired"] == 1 and row["status"] == "ready"
    assert row["gate_policy"] == "reopen_check"  # Only Control's authenticated reopen loop may open it.
    assert row["reserved"] == 1 and manager.count == 1
    assert store.one("SELECT status FROM jobs WHERE id=?", (requested["id"],))["status"] == "succeeded"
    if recovery is not None:
        import time
        current_time = int(time.time())
        orchestration.clock = lambda: current_time
        action = 'apply' if recovery == 'apply_running' else 'pause'
        if idle_recovery:
            from control.idle_pool import submit
            with store.tx() as db:
                db.execute("UPDATE runtimes SET gate_policy='open' WHERE uid=?",(user['id'],))
            row = store.one('SELECT * FROM runtimes WHERE uid=?',(user['id'],))
            result = submit(store, {'uid':user['id'],'state_version':row['state_version'],
                'gateway_boot_id':manager.current['boot_id'],'observed_at':current_time,
                'idle_proof':manager.current['idle_proof'],'activity_count':0,'complete':True})
            assert result['accepted']
            requested = store.one("SELECT * FROM jobs WHERE uid=? AND reason='idle_timeout'",(user['id'],))
        else:
            requested = store.queue(user['id'], action, bump_desired=False)
        claimed = orchestration.claim(runtime_spec)
        assert claimed['job']['phase'] == 'claimed'
        recovering = claimed['job']
        frozen = claimed['spec']
        with httpx.Client(transport=httpx.MockTransport(dispatch), base_url='http://127.0.0.1') as client:
            runner = worker.Worker(client, manager, idle_policy=store.pool_settings if idle_recovery else None)
            runner.next_idle = float('inf')
            receipt = runner.operation(recovering, 'phase', {'expected_phase':'claimed','phase':'draining'})
            runner.gate(recovering, frozen, receipt['gate_action'], manager.current, receipt['operation_id'])
            observation, _ = runner.observe(recovering, frozen)
            runner.operation(recovering, 'phase', {'expected_phase':'draining','phase':'closing','observation_id':observation['observation_id']})
            if recovery in ('stopped', 'idle_stopped'):
                manager.active = False
            if recovery in ('mixed', 'unknown'):
                original_components = manager.components
                manager.components = lambda snapshot: ({'agent':'stopped','gateway':'running','relay':'running'}, recovery != 'unknown')
            if recovery == 'idle_changed': manager.current['idle_proof']['sequence'] += 1
            current_time += 91
            # Time advances both leases and fresh observations; no state/lease is edited.
            monkeypatch.setattr(runtime.time, 'time', lambda: current_time)
            lost = False
            runner.next_reconcile = float('inf')
            assert runner.once()
        row = store.one('SELECT * FROM runtimes WHERE uid=?',(user['id'],))
        finished = store.one('SELECT * FROM jobs WHERE id=?',(requested['id'],))
        assert finished['attempts'] == 2
        if recovery in ('mixed','unknown','idle_changed','idle_closing_changed'):
            assert row['reserved'] == 1 and row['recovery_required'] == 1
            assert finished['status'] == 'failed' and manager.count == 1
        else:
            assert finished['status'] == 'succeeded'
            assert manager.count == (2 if recovery in ('running','idle_running') else 1)
            assert row['reserved'] == (1 if action == 'apply' else 0)
        return
    module_spec = importlib.util.spec_from_file_location("backup_r2_test", ROOT / "platform-backup.py")
    backup = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(backup)
    with store.tx() as db:
        db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
        db.execute("UPDATE runtimes SET security_blocked=1,stop_reason='admin_review' WHERE uid=?", (user["id"],))
    meta = backup.database_meta(store.root)
    assert meta["schema_version"] == 4 and meta["migration_identity"]
    assert meta["maintenance_mode"] == "frozen" and not meta["runtime_unsafe"]
    backup.pause_database(store.path)
    restored = store.one("SELECT * FROM runtimes WHERE uid=?", (user["id"],))
    assert restored["reserved"] == 0 and restored["gate_policy"] == "closed"
    assert restored["gateway_boot_id"] is None and restored["relay_boot_id"] is None
    assert restored["security_blocked"] == 1 and restored["stop_reason"] == "admin_review"
