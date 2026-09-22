"""Run-owned durable facts state. Source reads are never retried after ambiguity.

State lives inside the existing encrypted Run snapshot; no second task system.
All mutations and the corresponding public event commit in the same transaction.
"""
import copy
import hashlib
import json
import secrets
from fastapi import HTTPException
from .store import now, encode
from . import business_runs as runs

VERSION = "facts-coordinator-v1"
METHODS = {"night": ["night"], "companions": ["portrait"], "funds": ["funds"],
           "relations": ["lookup", "composite"], "calls": ["calls"], "vehicles": ["vehicle"]}
LABELS = {"night":"夜间活动","portrait":"人像共现","funds":"资金","lookup":"关联互查","composite":"综合关联","calls":"话单","vehicle":"车辆"}
MODULES = tuple(dict.fromkeys(m for values in METHODS.values() for m in values))

def capability(module): return "peixian-records-" + module

def tool(module): return "peixian_get_" + module + "_records"

def reject(code): raise HTTPException(409, {"code": code, "message": "本轮资料操作无法继续，请查看执行状态。"})

class FactsState:
    def __init__(self, store, boot_id=None):
        self.store = store
        self.boot_id = boot_id or secrets.token_hex(16)

    def _load(self, db, uid, rid, revision):
        row = db.execute("SELECT * FROM business_runs WHERE id=? AND uid=?", (rid, uid)).fetchone()
        if not row: raise HTTPException(404, "执行记录不存在")
        if type(revision) is not int or row["revision"] != revision: reject("facts_revision_changed")
        snapshot = self.store.decrypt(row["request_ciphertext"])
        if snapshot.get("facts_plan", {}).get("coordinator_version") != VERSION: reject("facts_plan_missing")
        state = snapshot.setdefault("facts_state", {"modules": {}, "table": None, "checked": None, "operation": None})
        return row, snapshot, state

    def _save(self, db, rid, snapshot):
        db.execute("UPDATE business_runs SET request_ciphertext=?,updated=? WHERE id=?", (self.store.encrypt(snapshot), now(), rid))

    def read(self, uid, rid, revision):
        with self.store.read(snapshot=True) as db:
            _, snapshot, state = self._load(db, uid, rid, revision)
            return copy.deepcopy({"plan": snapshot["facts_plan"], "state": state})

    def begin(self, uid, rid, revision, gateway_boot_id=None):
        with self.store.tx() as db:
            row, snapshot, state = self._load(db, uid, rid, revision)
            self.authorize(db, row, snapshot)
            operation = state.get("operation")
            current_boot = db.execute("SELECT gateway_boot_id FROM runtimes WHERE uid=?", (uid,)).fetchone()[0]
            if gateway_boot_id is not None and gateway_boot_id != current_boot:
                reject("facts_gateway_changed")
            if (operation and operation.get("control_boot_id", operation.get("boot_id")) == self.boot_id
                    and operation.get("gateway_boot_id") == current_boot):
                reject("facts_operation_busy")
            # Only registered component identity changes reclaim an owner. A stale
            # heartbeat alone does not prove an external query has stopped.
            for module, value in state["modules"].items():
                if value["status"] == "pending":
                    value["status"] = "unknown"
                    self._event(rid, module, "unknown")
            token = secrets.token_hex(16)
            state["operation"] = {"id": token, "control_boot_id": self.boot_id,
                                  "gateway_boot_id": current_boot, "last_heartbeat": now()}
            self._save(db, rid, snapshot)
            return token

    def _owned(self, db, uid, rid, revision, operation):
        row, snapshot, state = self._load(db, uid, rid, revision)
        owner = state.get("operation") or {}
        current_boot = db.execute("SELECT gateway_boot_id FROM runtimes WHERE uid=?", (uid,)).fetchone()[0]
        if (owner.get("id") != operation or owner.get("control_boot_id", owner.get("boot_id")) != self.boot_id
                or owner.get("gateway_boot_id") != current_boot):
            reject("facts_operation_changed")
        return row, snapshot, state

    def finish(self, uid, rid, revision, operation):
        with self.store.tx() as db:
            _, snapshot, state = self._owned(db, uid, rid, revision, operation)
            for module, value in state["modules"].items():
                if value["status"] == "pending":
                    value["status"] = "unknown"
                    self._event(rid, module, "unknown")
            state["operation"] = None
            self._save(db, rid, snapshot)

    def authorize(self, db, row, snapshot, module=None):
        from .agents.runtime import validate_execution
        validate_execution(snapshot)
        if row["cancel_requested"] or row["status"] not in ("queued", "running"): reject("facts_run_not_active")
        runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (row["uid"],)).fetchone()
        user = db.execute("SELECT * FROM users WHERE id=?", (row["uid"],)).fetchone()
        if (not user or not user["active"] or user["auth_version"] != row["auth_version"] or not runtime
                or runtime["revision"] != row["revision"] or runtime["security_blocked"] or runtime["recovery_required"]
                or runtime["status"] not in ("ready", "draining") or runtime["gate_policy"] == "closed_all"):
            reject("facts_authority_changed")
        if self.store.maintenance_status(db)["maintenance_mode"] not in ("normal", "frozen"): reject("facts_maintenance")
        plan=snapshot['facts_plan']
        if snapshot.get('registry_snapshot')!=plan.get('registry'):reject('registry_snapshot_mismatch')
        if 'registry' in plan:
            from .developer_registry.registry import REGISTRY
            applied=self.store.decrypt(runtime['applied_spec_ciphertext']) if runtime['applied_spec_ciphertext'] else {}
            try: REGISTRY.validate(plan['registry'],plan['registry']['agent_id'],plan['methods'],applied.get('plugins',[]))
            except ValueError as exc: reject(str(exc))
        if module is None: return
        plan = snapshot["facts_plan"]
        if module not in plan["modules"] or capability(module) not in plan["allowed_capabilities"] or tool(module) not in plan["allowed_tools"]:
            reject("facts_unplanned_capability")
        expected = next((p for p in snapshot["plugins"] if p["id"] == capability(module)), None)
        installed = db.execute("SELECT i.version,i.enabled,p.enabled AS published FROM installs i JOIN plugins p ON p.id=i.plugin AND p.version=i.version WHERE i.uid=? AND i.plugin=?", (row["uid"], capability(module))).fetchone()
        grant = db.execute("SELECT 1 FROM grants WHERE uid=? AND kind='plugin' AND resource=?", (row["uid"], capability(module))).fetchone()
        applied = self.store.decrypt(runtime["applied_spec_ciphertext"]) if runtime["applied_spec_ciphertext"] else {}
        current = next((p for p in applied.get("plugins", []) if p["id"] == capability(module)), None)
        if not expected or not grant or not installed or not installed["enabled"] or not installed["published"] or installed["version"] != expected["version"] or not current or current["version"] != expected["version"]:
            reject("facts_plugin_unavailable")

    def check(self, uid, rid, revision, operation, module=None):
        with self.store.tx() as db:
            row, snapshot, state = self._owned(db, uid, rid, revision, operation)
            self.authorize(db, row, snapshot, module)
            state["operation"]["last_heartbeat"] = now()
            self._save(db, rid, snapshot)

    def reserve(self, uid, rid, revision, operation, module):
        with self.store.tx() as db:
            row, snapshot, state = self._owned(db, uid, rid, revision, operation)
            self.authorize(db, row, snapshot, module)
            if module in state["modules"]:
                if state['modules'][module]['status']=='completed':
                    state['reuse_count']=state.get('reuse_count',0)+1
                    self._save(db,rid,snapshot)
                return False
            state["modules"][module] = {"status": "pending", "started": now(), "plugin_version": next(p["version"] for p in snapshot["plugins"] if p["id"] == capability(module))}
            self._event(rid, module, "pending")
            self._audit(db,rid,module,"allowed",snapshot["facts_plan"])
            prior = db.execute("SELECT actual_plugins FROM invocations WHERE run_id=?", (rid,)).fetchone()
            if prior: db.execute("UPDATE invocations SET actual_plugins=? WHERE run_id=?", (encode(sorted(set(json.loads(prior[0])) | {capability(module)})), rid))
            self._save(db, rid, snapshot)
            return True

    def complete(self, uid, rid, revision, operation, module, status, response=None):
        if status not in ("completed", "rejected", "unknown", "cancelled"): reject("facts_invalid_status")
        with self.store.tx() as db:
            row, snapshot, state = self._owned(db, uid, rid, revision, operation)
            value = state["modules"].get(module)
            if not value or value["status"] != "pending": reject("facts_not_pending")
            if status == "completed":
                expected = snapshot["facts_plan"]["records"][module]
                fields = ("module", "synthetic", "snapshot_id", "data_status", "returned_count", "total_count", "has_more", "rule_version", "rule_status")
                if not isinstance(response, dict) or any(type(response.get(k)) is not type(expected[k]) or response.get(k) != expected[k] for k in fields) or response.get("items") != expected["records"]:
                    status = "rejected"
                else:
                    try:self.authorize(db,row,snapshot,module)
                    except HTTPException:
                        # A known response remains an encrypted audit artifact, but
                        # revoked/cancelled authority never publishes it as usable facts.
                        status='rejected';value['withheld_response']=response
                        value['reason']='authority_changed_after_response'
                    else:value["response"] = response
            value.update(status=status, completed=now())
            self._event(rid, module, status, len(response["items"]) if status == "completed" else 0)
            self._audit(db,rid,module,"allowed" if status=="completed" else status,snapshot["facts_plan"],response if status=="completed" else None)
            if status == "completed":
                prior = db.execute("SELECT actual_plugins FROM invocations WHERE run_id=?", (rid,)).fetchone()
                if prior: db.execute("UPDATE invocations SET actual_plugins=? WHERE run_id=?", (encode(sorted(set(json.loads(prior[0])) | {capability(module)})), rid))
            self._save(db, rid, snapshot)
            return status

    def save_table(self, uid, rid, revision, operation, table):
        with self.store.tx() as db:
            row, snapshot, state = self._owned(db, uid, rid, revision, operation)
            self.authorize(db, row, snapshot)
            for module,value in state["modules"].items():
                if value["status"] == "completed": self.authorize(db, row, snapshot, module)
            if plan_registry := snapshot['facts_plan'].get('registry'):
                from .developer_registry.registry import rule_bindings
                expected=[b for b in rule_bindings(plan_registry) if state['modules'].get(b['module'],{}).get('status')=='completed']
                if not isinstance(table,dict) or table.get('rule_executions')!=expected:reject('rule_execution_mismatch')
            state["table"] = table; state["checked"] = None; state["compiled_at"] = now()
            from .record_checks import verify
            proof=verify(snapshot,self.store.rows('SELECT * FROM run_events WHERE run_id=? ORDER BY sequence',(rid,)))
            if proof is not None:
                state['record_checked']=proof
                runs.event(self.store,rid,'facts.vehicle-check','record_check','核对车辆记录与来源',
                           'failed' if proof['rejected'] else 'completed',started=now(),completed=now(),count=len(proof['approved']))
            self._save(db,rid,snapshot)
            runs.event(self.store,rid,"facts.compile","facts","整理资料事实", "completed",completed=now())

    def check_claims(self, uid, rid, revision, operation, claims):
        from .scenario_facts import review
        with self.store.tx() as db:
            row, snapshot, state = self._owned(db,uid,rid,revision,operation)
            self.authorize(db,row,snapshot)
            if state["table"] is None: reject("facts_prepare_required")
            for module,value in state["modules"].items():
                if value["status"] == "completed": self.authorize(db,row,snapshot,module)
            result = review(state["table"],claims)
            state["checked"] = result; state["checked_at"] = now(); self._save(db,rid,snapshot)
            runs.event(self.store,rid,"facts.check","claim_check","核对摘要来源","failed" if result["rejected"] else "completed",completed=now())
            return result

    def _event(self, rid, module, status, count=0):
        runs.event(self.store,rid,"facts."+module,"plugin","查询"+LABELS.get(module,"所选")+"资料",status,started=now() if status=="pending" else None,completed=now() if status!="pending" else None,capability=capability(module),count=count)

    def _audit(self, db, rid, module, decision, plan, response=None):
        value={"step_id":"prepare-"+module,"method_ids":[m for m in plan["methods"] if module in METHODS[m]],"module":module,"capability_id":capability(module),"tool_id":tool(module),"authorization_result":decision,"request_contract_version":"1.0","response_contract_version":"source-row-v1"}
        if response:value.update(snapshot_id=response["snapshot_id"],record_count=len(response["items"]))
        db.execute("UPDATE run_events SET output_summary=? WHERE run_id=? AND event_key=?",(encode(value),rid,"facts."+module))

    def terminate(self, uid, rid, revision):
        # No call is retried. A local abort does not prove a remote request was undone.
        with self.store.tx() as db:
            row,snapshot,state=self._load(db,uid,rid,revision)
            for module in snapshot['facts_plan']['modules']:
                value=state['modules'].get(module)
                if value and value['status']=='pending':
                    value.update(status='unknown',completed=now());self._event(rid,module,'unknown')
                elif not value and row['cancel_requested']:
                    state['modules'][module]={'status':'cancelled','completed':now()};self._event(rid,module,'cancelled')
            state['operation']=None;self._save(db,rid,snapshot)
