"""Versioned orchestration contract additions; imports no runtime or database."""


def extend(s, obj, ref, array, ID, STRING, BOOL, INTEGER):
    identity = {"lease": {**STRING, "writeOnly": True}, "attempt": {**INTEGER, "minimum": 1}, "operation_id": ID}
    phases = {**STRING, "enum": ["claimed", "draining", "closing", "applying", "reconciling", "awaiting_action", "finished"]}
    components = obj({key: {**STRING, "enum": ["running", "stopped", "unknown"]} for key in ("agent", "gateway", "relay")}, ("agent", "gateway", "relay"))
    observation = {"observation_id": ID, "runtime_id": ID, "state_version": INTEGER,
                   "host_boot_id": ID, "observed_at": INTEGER, "components": components,
                   "mutation_state": {**STRING, "enum": ["idle", "running", "unknown"]}, "complete": BOOL, "evidence_ref": ID}
    s["Health"]["properties"].update(schema_version={**INTEGER, "enum": [4, 5]}, runtime_protocol_version={**INTEGER, "const": 2})
    s["RuntimeStartBody"] = obj({})
    inventory_resource = obj({"runtime_id": ID, "uid": ID, "running": BOOL, "mutation_state": {**STRING, "enum": ["idle", "running", "unknown"]}}, ("runtime_id", "uid", "running", "mutation_state"))
    s["PoolInventoryBody"] = obj({"host_boot_id": ID, "observed_at": INTEGER, "registry_digest": STRING, "complete": BOOL, "resources": array(inventory_resource, maxItems=10000)}, ("host_boot_id", "observed_at", "registry_digest", "complete", "resources"))
    s["RuntimeStopBody"] = obj({"expected_state_version": {**INTEGER, "minimum": 0}, "start_job_id": ID}, ("expected_state_version",))
    s["SelfRuntime"] = obj({"runtime_mode": {**STRING, "const": "on_demand"}, "status": STRING, "ready": BOOL,
        "state_version": INTEGER, "desired": INTEGER, "revision": INTEGER, "stop_reason": STRING,
        "manual_stop_reason": STRING, "allowed_actions": array({**STRING, "enum": ["start", "stop"]}),
        "job": {"anyOf": [ref("Job"), {"type": "null"}]}}, extra=True)
    s["SelfRuntimeResult"] = obj({"accepted": BOOL, "runtime": ref("SelfRuntime"), "job": {"anyOf": [ref("Job"), {"type": "null"}]}}, ("accepted", "runtime", "job"))
    s["Runtime"]["properties"].update(status=STRING, phase=phases, gate_policy=STRING,
        security_blocked=BOOL, recovery_required=BOOL, cancellation_confirmed=BOOL)
    s["Runtime"]["description"] += " revision 是实际验证的 applied；desired 是期望版本，可能尚未生效。安全阻断不证明外部操作已撤销。"
    s["Job"]["properties"].update(phase=phases, not_before=INTEGER, defer_count=INTEGER, recovery_required=BOOL)
    s["LeaseBody"] = obj(identity, identity)
    s["PhaseBody"] = obj({**identity, "expected_phase": phases, "phase": phases, "observation_id": ID}, (*identity, "expected_phase", "phase"))
    s["BootBody"] = obj({**identity, "runtime_id": ID, "gateway_boot_id": ID, "relay_boot_id": ID}, (*identity, "runtime_id", "gateway_boot_id", "relay_boot_id"))
    s["CompleteBody"] = obj({**identity, "ok": BOOL, "deferred": BOOL,
        "defer_reason": {**STRING, "enum": ["runtime_busy"]}, "error": STRING,
        "rolled_back": BOOL, "observation_id": ID, "cleanup_confirmed": BOOL}, identity,
        description="相同 operation_id 和内容返回原回执；内容冲突为409。defer仅可用于确认的runtime_busy，延后时间由Control计算。回执不证明当前仍可开放入口。")
    s["ObservationBody"] = obj({**observation, "job_id": ID, "attempt": INTEGER,
        "lease": identity["lease"], "gateway_boot_id": ID, "gate_epoch": INTEGER,
        "accepting": BOOL, "egress_closed": BOOL, "activity_count": {"type": ["integer", "null"]},
        "applied_revision": INTEGER, "spec_digest": {"type": ["string", "null"]}},
        (*observation, "job_id", "attempt", "lease", "gateway_boot_id", "gate_epoch", "accepting", "egress_closed", "activity_count", "applied_revision", "spec_digest"))
    s["ReconcileBody"] = obj({**observation, "orphan_resources": BOOL}, observation)
    s["WorkerReceipt"] = obj({"protocol_version": {**INTEGER, "const": 2}, "job_id": ID,
        "attempt": INTEGER, "phase": phases, "state_version": INTEGER, "gate_epoch": INTEGER,
        "operation_id": ID, "gate_action": STRING,
        "request_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, extra=True,
        description="脱敏的当前责任或历史操作结果；查询不返回明文租约、配置快照或服务凭据。")
    s["Maintenance"] = obj({"mode": {**STRING, "enum": ["normal", "frozen", "repair_only"]}, "maintenance_mode": STRING,
        "state_version": INTEGER, "capacity_healthy": BOOL, "recovery_required": INTEGER, "security_pending": INTEGER,
        "safety_sync_failures": INTEGER}, extra=True)
    s["MaintenanceBody"] = obj({"mode": {**STRING, "enum": ["normal", "frozen", "repair_only"]}, "state_version": INTEGER}, ("mode", "state_version"))
    s["WorkerMaintenanceBody"] = obj({"maintenance_mode": {**STRING, "enum": ["normal", "frozen", "repair_only"]}, "expected_state_version": INTEGER}, ("maintenance_mode", "expected_state_version"))
    s["RecoveryBody"] = obj({"action": {**STRING, "enum": ["continue", "cancel"]}}, ("action",))
    s["LegacyRollbackBody"]["properties"].update(observation_id=ID, expected_state_version=INTEGER, operation_id=ID)
    s["LegacyRollbackBody"]["required"] += ["observation_id", "expected_state_version", "operation_id"]
    claim = s["WorkerClaim"]["properties"]["job"]["anyOf"][0]["properties"]
    claim.update(attempt=INTEGER, phase=phases, state_version=INTEGER, gate_epoch=INTEGER, lease_until=INTEGER, spec_digest=STRING)
    s["Identity"]["properties"]["capabilities"]["items"]["enum"].append("connections.manage")
    return s
