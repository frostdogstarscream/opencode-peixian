"""Single host worker for the Peixian control API. Never run in an app container."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import hashlib
import uuid
from urllib.parse import urlsplit

import httpx


module = importlib.util.spec_from_file_location("peixian_console_runtime", Path(__file__).with_name("console-runtime.py"))
runtime = importlib.util.module_from_spec(module)
module.loader.exec_module(runtime)

_settings_spec = importlib.util.spec_from_file_location("worker_orchestration_settings",
    Path(__file__).resolve().parents[2] / "services/peixian-control/shared/orchestration_config.py")
settings = importlib.util.module_from_spec(_settings_spec)
_settings_spec.loader.exec_module(settings)
_errors_spec = importlib.util.spec_from_file_location("worker_error_codes", _settings_spec.origin.replace("orchestration_config.py", "worker_errors.py"))
errors = importlib.util.module_from_spec(_errors_spec)
_errors_spec.loader.exec_module(errors)


class ControlFailure(runtime.RuntimeFailure):
    def __init__(self, code, status):
        super().__init__(code)
        self.status = status
        self.definite = 400 <= status < 500 and status not in (408, 429)



def host_boot_id():
    path = Path("/proc/sys/kernel/random/boot_id")
    if path.is_file():
        return path.read_text(encoding="ascii").strip()
    if os.name == "nt":
        import ctypes
        boot = int(time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000)
        return hashlib.sha256((os.environ.get("COMPUTERNAME", "windows") + ":" + str(boot)).encode()).hexdigest()
    raise runtime.RuntimeFailure("host_boot_identity_unavailable")


def report(state, job=None, code=None):
    event = {"state": state, "observed_at": int(time.time())}
    if job:
        event.update(job=job["id"], runtime_action=job["action"])
    if code:
        event["code"] = code
    print(json.dumps(event), flush=True)


@contextlib.contextmanager
def host_lock(root):
    path = Path(root) / "worker.lock"
    with path.open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise runtime.RuntimeFailure("another_host_worker_is_running") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Worker:
    def __init__(self, api, manager, *, orchestration=None, clock=time.monotonic, runtime_pool=False, idle_policy=None):
        self.api, self.manager = api, manager
        self.config = settings.validate(orchestration or {})
        self.clock = clock
        self.next_reconcile = 0
        self.runtime_pool = runtime_pool
        self.next_inventory = 0
        self.boot_id = host_boot_id()
        self.idle_policy = idle_policy
        self.next_idle = 0

    def request(self, method, path, **kwargs):
        allow_state_conflict = kwargs.pop("allow_state_conflict", False)
        kwargs["headers"] = {**kwargs.pop("headers", {}), "X-Peixian-Protocol": "2", "X-Peixian-Capabilities": "runtime_pool_v1,runtime_pool_wait_v1,idle_activity_v1", "X-Peixian-Runtime-Mode": "on_demand" if self.runtime_pool else "eager"}
        kwargs.setdefault("timeout", self.config["worker_heartbeat_timeout_seconds"])
        started = self.clock()
        transport = {"new_connection": False}
        def trace(name, info):
            if name == "connection.connect_tcp.started":
                transport["new_connection"] = True
        kwargs["extensions"] = {"trace": trace}
        try:
            response = self.api.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            category = path.rsplit("/", 1)[-1]
            if category not in {"claim", "heartbeat", "phase", "complete", "boot", "reconcile", "observations"}:
                category = "query"
            print(json.dumps({"state": "control_transport_failure", "operation": category,
                "method": method, "code": type(error).__name__,
                "new_connection": transport["new_connection"],
                "elapsed_ms": round((self.clock() - started) * 1000)}), flush=True)
            raise
        if response.status_code != 200:
            payload = kwargs.get("json", {})
            code = response.headers.get(errors.HEADER)
            code = code if code in errors.CODES else "worker_overloaded" if response.status_code in (429, 503) else "worker_rejected" if 400 <= response.status_code < 500 else "worker_api_unavailable"
            diagnostic = {"state": "worker_request_rejected", "http_status": response.status_code, "code": code}
            match = re.fullmatch(r"/internal/worker/jobs/([A-Za-z0-9_-]{1,100})(?:/(heartbeat|phase|boot|complete))?", path)
            if match:
                diagnostic.update(job_id=match[1], operation=match[2] or "query")
            if isinstance(payload, dict):
                for key in ("operation_id", "job_id", "phase", "expected_phase", "observation_id"):
                    value = payload.get(key)
                    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
                        diagnostic[key] = value
                for key in ("attempt", "state_version", "gate_epoch"):
                    if type(payload.get(key)) is int:
                        diagnostic[key] = payload[key]
                if type(payload.get("observed_at")) is int:
                    diagnostic["observation_age_seconds"] = max(0, int(time.time()) - payload["observed_at"])
            print(json.dumps(diagnostic), flush=True)
        if response.status_code == 409:
            if allow_state_conflict:
                return response
            code = response.headers.get(errors.HEADER)
            raise ControlFailure(code if code in errors.CODES else "worker_rejected", 409)
        if response.status_code != 200:
            # Fixed diagnostic codes distinguish transport/load failures without
            # exposing request URLs, response bodies, leases or credentials.
            report("control_request_failed", code="http_" + str(response.status_code))
            code = response.headers.get(errors.HEADER)
            if code not in errors.CODES:
                code = "worker_overloaded" if response.status_code in (429, 503) else "worker_rejected" if 400 <= response.status_code < 500 else "worker_api_unavailable"
            raise ControlFailure(code, response.status_code)
        return response

    def query(self, job, operation_id=None):
        params = {"attempt": job["attempt"]}
        if operation_id:
            params["operation_id"] = operation_id
        return self.request("GET", "/internal/worker/jobs/" + job["id"], params=params).json()

    def operation(self, job, kind, values):
        """Reconcile an unknown POST outcome before retrying its identical operation."""
        operation_id = uuid.uuid4().hex
        body = {"lease": job["lease"], "attempt": job["attempt"], "operation_id": operation_id, **values}
        path = "/internal/worker/jobs/" + job["id"] + "/" + kind
        journal = self.manager.root / "receipts" / job["id"] / str(job["attempt"]) / (operation_id + ".json")
        fingerprint = hashlib.sha256(runtime.json_bytes(values)).hexdigest()
        request_hash = hashlib.sha256(runtime.json_bytes({"kind": kind, "body": {k: v for k, v in body.items() if k != "lease"}})).hexdigest()
        def record(status, **detail):
            # Only fixed categories and server-generated opaque identities; never body/spec/lease.
            value = {"operation_id": operation_id, "kind": kind, "job_id": job["id"],
                "attempt": job["attempt"], "status": status, "request_digest": fingerprint,
                "phase": job["phase"], "state_version": job["state_version"], "gate_epoch": job["gate_epoch"], **detail}
            if type(job.get("last_observed_at")) is int:
                value["observation_age_seconds"] = max(0, int(time.time()) - job["last_observed_at"])
            runtime.write_json(journal, value)
            print(json.dumps({"state": "worker_operation", **{k: v for k, v in value.items() if k != "receipt"}}), flush=True)
        def category(error):
            if isinstance(error, ControlFailure):
                return error.code
            if isinstance(error, httpx.HTTPError):
                return "worker_transport_failure"
            return "worker_invalid_response"
        record("pending")
        uncertain_prior = False
        for attempt in range(2):
            failure = None
            try:
                receipt = self.request("POST", path, json=body).json()
            except (httpx.HTTPError, runtime.RuntimeFailure, ValueError) as error:
                failure = error
                try:
                    queried = self.query(job, operation_id)
                    if not isinstance(queried, dict) or "receipt" not in queried:
                        raise ValueError("invalid query response")
                    receipt = queried["receipt"]
                except (httpx.HTTPError, runtime.RuntimeFailure, ValueError) as query_error:
                    record("unknown", failure_code=category(error), query_code=category(query_error),
                           http_status=getattr(error, "status", None), receipt_hit=False)
                    raise runtime.RuntimeFailure("worker_operation_outcome_unknown") from None
                # A conflict receipt belongs to a different request; never accept it.
                if isinstance(error, ControlFailure) and error.code == "worker_receipt_conflict":
                    record("rejected", failure_code=error.code, http_status=error.status, receipt_hit=receipt is not None)
                    raise error
                if receipt is None:
                    if isinstance(error, ControlFailure) and error.definite:
                        record("unknown" if uncertain_prior else "rejected", failure_code=error.code, http_status=error.status, receipt_hit=False)
                        if uncertain_prior:
                            raise runtime.RuntimeFailure("worker_operation_outcome_unknown") from None
                        raise error
                    record("retry_pending" if attempt == 0 else "unknown", failure_code=category(error),
                           http_status=getattr(error, "status", None), receipt_hit=False)
                    if attempt == 0:
                        uncertain_prior = True
                        continue  # Only exact same body/identity; never repeat the host mutation.
                    raise runtime.RuntimeFailure("worker_operation_outcome_unknown") from None
            if (not isinstance(receipt, dict) or receipt.get("receipt_status") != "recorded"
                    or receipt.get("job_id") != job["id"] or receipt.get("attempt") != job["attempt"]
                    or receipt.get("operation_id") != operation_id
                    or receipt.get("request_hash", request_hash) != request_hash
                    or any(type(receipt.get(k)) is not int or receipt[k] < 0 for k in ("state_version", "gate_epoch"))
                    or receipt.get("phase_after_commit") not in ("claimed", "draining", "closing", "applying", "reconciling", "finished", "queued")):
                record("unknown", failure_code="worker_receipt_invalid", receipt_hit=receipt is not None)
                raise runtime.RuntimeFailure("invalid_worker_receipt")
            record("recorded", receipt=receipt, receipt_hit=True,
                   failure_code=category(failure) if failure is not None else None)
            for field in ("state_version", "gate_epoch"):
                job[field] = receipt[field]
            if receipt.get("gate_owner"):
                job["gate_owner"] = receipt["gate_owner"]
            job["phase"] = receipt["phase_after_commit"]
            return receipt
        raise runtime.RuntimeFailure("worker_operation_outcome_unknown")

    def gate(self, job, spec, action, state=None, operation_id=None):
        if state is None:
            state = self.manager.runtime_request(spec, "GET", "/internal/runtime/state")
        command = {"protocol_version": 2, "runtime_id": spec["runtime_id"], "boot_id": state["boot_id"],
                   "gate_epoch": job["gate_epoch"], "state_version": job["state_version"],
                   "owner": job.get("gate_owner") or "job:" + job["id"] + ":" + str(job["attempt"]),
                   "operation_id": operation_id or uuid.uuid4().hex, "action": action,
                   "reason": job.get("reason") or "lifecycle", "revision": state["revision"]}
        try:
            return self.manager.runtime_request(spec, "POST", "/internal/runtime/gate", command)
        except runtime.RuntimeFailure:
            current = self.manager.runtime_request(spec, "GET", "/internal/runtime/state")
            expected = "draining" if action == "drain" else "closed"
            if (any(current.get(key) != command[key] for key in ("boot_id", "gate_epoch", "state_version", "owner"))
                    or current.get("gate") != expected
                    or (action == "close" and (current.get("relay") or {}).get("gate") != "closed")):
                raise runtime.RuntimeFailure("runtime_gate_outcome_unknown") from None
            return current

    def observe(self, job, spec):
        observation, state = self.manager.observe(job, spec, self.boot_id)
        self.request("POST", "/internal/worker/observations", json=observation)
        job["last_observed_at"] = observation.get("observed_at")
        return observation, state

    def reconcile(self):
        if self.runtime_pool and self.clock() >= self.next_inventory:
            self.next_inventory = self.clock() + 60
            targets = self.request("GET", "/internal/worker/pool/inventory").json()
            started = int(time.time())
            resources, complete = self.manager.pool_inventory(targets["items"])
            self.request("POST", "/internal/worker/pool/inventory", json={
                "host_boot_id": self.boot_id, "observed_at": started, "registry_digest": targets["registry_digest"],
                "resources": resources, "complete": complete}, allow_state_conflict=True)
        selected = self.request("GET", "/internal/worker/reconcile", params={"limit": self.config["reconcile_batch"]}).json()
        if selected.get("protocol_version") != 2 or not isinstance(selected.get("items"), list):
            raise runtime.RuntimeFailure("worker_protocol_mismatch")
        if len(selected["items"]) > self.config["reconcile_batch"]:
            raise runtime.RuntimeFailure("invalid_reconcile_batch")
        for candidate in selected["items"]:
            states, complete = self.manager.components(candidate)
            value = {"observation_id": uuid.uuid4().hex, "runtime_id": candidate["runtime_id"],
                     "state_version": candidate["state_version"], "host_boot_id": self.boot_id,
                     "observed_at": int(time.time()), "components": states,
                     "mutation_state": self.manager.mutation_state(candidate["runtime_id"]),
                     "complete": complete, "evidence_ref": uuid.uuid4().hex}
            response = self.request("POST", "/internal/worker/reconcile", json=value, allow_state_conflict=True)
            if response.status_code == 409:
                # A background permit/open transition can supersede a selected
                # candidate. Fresh collection belongs to the next round-robin;
                # do not retry old evidence or delay the next queued job.
                report("reconcile_superseded")

    def download(self, digest):
        if not runtime.DIGEST.fullmatch(digest):
            raise runtime.RuntimeFailure("invalid_plugin_digest")
        output = bytearray()
        with self.api.stream("GET", "/internal/worker/packages/" + digest,
                             headers={"X-Peixian-Protocol": "2", "X-Peixian-Capabilities": "runtime_pool_v1,runtime_pool_wait_v1,idle_activity_v1", "X-Peixian-Runtime-Mode": "on_demand" if self.runtime_pool else "eager"}) as response:
            if response.status_code != 200:
                raise runtime.RuntimeFailure("plugin_download_unavailable")
            for chunk in response.iter_bytes():
                output.extend(chunk)
                if len(output) > runtime.MAX_PACKAGE:
                    raise runtime.RuntimeFailure("plugin_download_limit")
        return bytes(output)

    def idle_tick(self):
        selected=self.request('POST','/internal/worker/scheduler/tick').json()
        if selected.get('protocol_version')!=2 or not isinstance(selected.get('items'),list) or len(selected['items'])>self.idle_policy['scheduler_batch']:
            raise runtime.RuntimeFailure('worker_protocol_mismatch')
        deadline=self.clock()+2
        for candidate in selected['items']:
            if self.clock()>=deadline: break
            started=int(time.time())
            try:
                state=self.manager.runtime_request(candidate['spec'],'GET','/internal/runtime/state')
                self.request('POST','/internal/worker/scheduler/observe',json={
                    'uid':candidate['uid'],'state_version':candidate['state_version'],'gateway_boot_id':state['boot_id'],
                    'observed_at':started,'idle_proof':state.get('idle_proof'),
                    'activity_count':state.get('activity',{}).get('total'),
                    'complete':state.get('activity',{}).get('complete') is True and self.manager.mutation_state(candidate['runtime_id'])=='idle'},allow_state_conflict=True)
            except (runtime.RuntimeFailure,httpx.HTTPError,ValueError,KeyError):
                report('idle_observation_unavailable')

    def idle_changed(self, job, observation):
        proof=observation.get('idle_proof')
        return (job.get('reason')=='idle_timeout' and (not observation.get('complete') or observation.get('activity_count')!=0
            or not isinstance(proof,dict) or proof.get('complete') is not True
            or proof.get('sequence')!=job.get('idle_activity_version')
            or observation.get('gateway_boot_id')!=job.get('idle_gateway_boot_id')
            or type(proof.get('idle_seconds')) not in (int,float)
            or proof['idle_seconds']< (self.idle_policy or {}).get('idle_timeout_seconds',600)))

    def once(self):
        if self.clock() >= self.next_reconcile:
            self.next_reconcile = self.clock() + self.config["reconcile_seconds"]
            self.reconcile()
        if self.idle_policy and self.clock()>=self.next_idle:
            self.next_idle=self.clock()+self.idle_policy['scheduler_tick_seconds']
            self.idle_tick()
        payload = self.request("POST", "/internal/worker/claim").json()
        if payload.get("protocol_version") != 2:
            raise runtime.RuntimeFailure("worker_protocol_mismatch")
        job = payload.get("job")
        if job is None:
            return False
        required = {"id", "uid", "action", "lease", "revision", "attempt", "phase", "recovery_required",
                    "runtime_id", "state_version", "gate_epoch", "spec_digest"}
        if (not isinstance(job, dict) or not required <= set(job)
                or not all(isinstance(job.get(key), str) for key in ("id", "uid", "action", "lease", "spec_digest"))
                or any(type(job.get(key)) is not int for key in ("revision", "attempt", "state_version", "gate_epoch"))
                or job["phase"] not in ("claimed", "reconciling")):
            raise runtime.RuntimeFailure("invalid_job_envelope")
        runtime.check_id(job["id"])
        runtime.check_id(job["uid"])
        spec = payload.get("spec")
        if (not isinstance(spec, dict) or "runtime_key" not in spec.get("private", {})
                or spec.get("runtime_id") != job["runtime_id"]
                or hashlib.sha256(runtime.json_bytes(spec)).hexdigest() != job["spec_digest"]):
            raise runtime.RuntimeFailure("invalid_job_spec")
        stop, failed = threading.Event(), threading.Event()

        def heartbeat():
            if failed.is_set():
                raise runtime.RuntimeFailure("worker_heartbeat_failed")
            self.request("POST", "/internal/worker/jobs/" + job["id"] + "/heartbeat",
                         json={"lease": job["lease"], "attempt": job["attempt"]})

        def keepalive():
            while not stop.wait(self.config["worker_heartbeat_seconds"]):
                try:
                    heartbeat()
                except Exception:
                    failed.set()
                    return

        thread = threading.Thread(target=keepalive, daemon=True, name="peixian-worker-lease")
        thread.start()
        result, observation = {"ok": False}, None
        report("claimed", job)
        try:
            if job["phase"] == "claimed":
                receipt = self.operation(job, "phase", {"expected_phase": "claimed", "phase": "draining"})
                _, state = self.manager.observe(job, spec, self.boot_id)
                if state is not None:
                    self.gate(job, spec, receipt["gate_action"], state, receipt["operation_id"])
            elif job["phase"] == "reconciling":
                # Recovered attempts have a new authority epoch. Register the
                # actual boot before collecting evidence under that authority.
                raw, state = self.manager.observe(job, spec, self.boot_id)
                if state is not None and raw["mutation_state"] == "idle":
                    receipt = self.operation(job, "boot", {"runtime_id": spec["runtime_id"],
                        "gateway_boot_id": state["boot_id"], "relay_boot_id": (state.get("relay") or {}).get("boot_id")})
                    self.gate(job, spec, receipt["gate_action"], state, receipt["operation_id"])
            observation, _ = self.observe(job, spec)
            if self.idle_changed(job, observation):
                self.operation(job,'cancel-idle',{})
                report('idle_cancelled',job)
                return True
            if not observation["complete"] or observation["mutation_state"] != "idle":
                raise runtime.RuntimeFailure("runtime_observation_unknown")
            if observation["accepting"]:
                raise runtime.RuntimeFailure("runtime_gate_not_closed")
            if observation["activity_count"] != 0:
                if job["phase"] != "draining":
                    raise runtime.RuntimeFailure("runtime_recovery_requires_review")
                receipt = self.operation(job, "complete", {"deferred": True, "defer_reason": "runtime_busy",
                                                           "observation_id": observation["observation_id"]})
                report("deferred", job)
                return True
            if (job["phase"] == "reconciling" and observation["applied_revision"] == job["revision"]
                    and observation["spec_digest"] == job["spec_digest"]):
                result = {"ok": True}
            else:
                receipt = self.operation(job, "phase", {"expected_phase": job["phase"], "phase": "closing",
                                                         "observation_id": observation["observation_id"]})
                _, state = self.manager.observe(job, spec, self.boot_id)
                if state is not None:
                    self.gate(job, spec, receipt["gate_action"], state, receipt["operation_id"])
                observation, _ = self.observe(job, spec)
                if self.idle_changed(job, observation):
                    self.operation(job,'cancel-idle',{})
                    report('idle_cancelled',job)
                    return True
                if (not observation["complete"] or observation["activity_count"] != 0
                        or not observation["egress_closed"] or observation["accepting"]):
                    raise runtime.RuntimeFailure("runtime_egress_close_unconfirmed")
                self.operation(job, "phase", {"expected_phase": "closing", "phase": "applying",
                                               "observation_id": observation["observation_id"]})
                job["mutation_authorized"] = True
                result = self.manager.apply(job, spec, self.download, heartbeat)
            heartbeat()
        except runtime.RuntimeFailure as error:
            if job.get('reason')=='idle_timeout' and job['phase'] in ('claimed','draining','closing'):
                self.operation(job,'cancel-idle',{})
                report('idle_cancelled',job)
                return True
            result = {"ok": False, "error": error.code, "rolled_back": error.rolled_back,
                      }
            report("failed", job, error.code)
        except Exception:
            result = {"ok": False, "error": "worker_operation_failed"}
            report("failed", job, "worker_operation_failed")
        finally:
            stop.set()
            thread.join(timeout=self.config["worker_heartbeat_timeout_seconds"] + 1)
        if failed.is_set():
            raise runtime.RuntimeFailure("worker_heartbeat_failed")
        try:
            raw, state = self.manager.observe(job, spec, self.boot_id)
            if state is not None and raw["mutation_state"] == "idle":
                if job["phase"] in ("applying", "reconciling"):
                    receipt = self.operation(job, "boot", {"runtime_id": spec["runtime_id"],
                        "gateway_boot_id": state["boot_id"], "relay_boot_id": (state.get("relay") or {}).get("boot_id")})
                    self.gate(job, spec, receipt["gate_action"], state, receipt["operation_id"])
            observation, _ = self.observe(job, spec)
        except (runtime.RuntimeFailure, httpx.HTTPError, ValueError):
            observation = None
        if observation and observation.get("complete"):
            result["observation_id"] = observation["observation_id"]
        result.pop("cleanup_confirmed", None)
        self.operation(job, "complete", result)
        if result.get("ok"):
            report("succeeded", job)
        return True


def control_client(url, key):
    # Low-rate host management crosses Docker Desktop's published port. A peer
    # can close an idle socket while the pool still considers it reusable.
    # Fresh sockets avoid that ambiguous POST outcome; no transport retries.
    return httpx.Client(base_url=url.rstrip("/"), headers={"X-Worker-Key": key},
        timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10),
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
        trust_env=False, follow_redirects=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Use the same platform configuration as the server")
    parser.add_argument("--control-url", default="http://127.0.0.1:14090")
    parser.add_argument("--key-file", type=Path, default=Path(__file__).parent / ".secrets/console-worker.key")
    parser.add_argument("--state-root", type=Path, default=Path(__file__).parent / ".runtime/console")
    parser.add_argument("--control-container", default="peixian-console")
    parser.add_argument("--agent-image", default="peixian-opencode:1.18.30-managed-r1")
    parser.add_argument("--gateway-image", default="peixian-gateway:console-r1")
    parser.add_argument("--max-runtimes", type=int, default=4)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    manager_options = {}
    if args.config:
        spec = importlib.util.spec_from_file_location("peixian_platform_config", Path(__file__).with_name("platform-config.py"))
        shared = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = shared
        spec.loader.exec_module(shared)
        try:
            cfg = shared.load_config(args.config)
        except shared.ConfigError as error:
            raise runtime.RuntimeFailure(str(error)) from None
        args.control_url, args.key_file = cfg.control_url, cfg.secrets / "console-worker.key"
        args.state_root, args.control_container = cfg.worker_root, cfg.control_container
        args.agent_image, args.gateway_image = cfg.images["agent"], cfg.images["gateway"]
        args.max_runtimes = cfg.max_runtimes
        manager_options = {"resource_limits": cfg.resource_limits, "network_pool": cfg.network_pool,
                           "deployment_id": cfg.deployment_id, "config_version": cfg.version,
                           "control_resources": cfg.control_resources, "capacity_policy": cfg.capacity_policy,
                           "orchestration": cfg.orchestration}
    url = urlsplit(args.control_url)
    if (url.scheme not in ("http", "https") or url.hostname not in ("127.0.0.1", "localhost", "::1") or
            url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        raise runtime.RuntimeFailure("control_api_must_be_local")
    try:
        key = args.key_file.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        raise runtime.RuntimeFailure("worker_key_unavailable") from None
    if len(key) < 32 or any(c in key for c in "\r\n\0"):
        raise runtime.RuntimeFailure("worker_key_invalid")
    manager = runtime.RuntimeManager(args.state_root, control_container=args.control_container,
                                     agent_image=args.agent_image, gateway_image=args.gateway_image,
                                     maximum=args.max_runtimes, **manager_options)
    with host_lock(manager.root), control_client(args.control_url, key) as client:
        worker = Worker(client, manager, orchestration=manager_options.get("orchestration"), runtime_pool=bool(args.config and cfg.version == 4),
                        idle_policy=cfg.runtime_pool if args.config and cfg.version==4 else None)
        while True:
            try:
                found = worker.once()
                if args.once:
                    return
                if not found:
                    time.sleep(5)
            except (httpx.HTTPError, runtime.RuntimeFailure) as error:
                if isinstance(error, httpx.HTTPError):
                    report("control_transport_failed", code=type(error).__name__)
                report("retry", code=error.code if isinstance(error, runtime.RuntimeFailure) else "control_api_unavailable")
                if args.once:
                    raise SystemExit(1) from None
                time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        report("stopped")
    except runtime.RuntimeFailure as error:
        report("failed", code=error.code)
        raise SystemExit(1) from None
