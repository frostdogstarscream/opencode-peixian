"""Provider calls reuse durable Run storage and Gateway-owned operation leases."""
import copy,json
from .facts_runtime import FactsState,reject
from .business_runs import event
from .store import now,encode
from .theft_provider_flow import availability,pid
from shared.theft_provider import parse_response,ContractError,CATALOG
from shared import theft_provider_v2 as v2
class ProviderState(FactsState):
    def _load(self,db,uid,rid,revision):
        row=db.execute('SELECT * FROM business_runs WHERE id=? AND uid=?',(rid,uid)).fetchone()
        if not row or row['revision']!=revision:reject('provider_execution_identity')
        snapshot=self.store.decrypt(row['request_ciphertext'])
        if not snapshot.get('provider_plan'):reject('provider_plan_missing')
        state=snapshot.setdefault('provider_state',{'modules':{},'operation':None})
        return row,snapshot,state
    def read(self,uid,rid,revision):
        with self.store.read(snapshot=True) as db:
            row,snap,state=self._load(db,uid,rid,revision)
            value=copy.deepcopy({'plan':snap['provider_plan'],'state':state})
            if value['plan'].get('version')==v2.VERSION:
                value['plan'].pop('identities',None)
                for entry in value['state']['modules'].values():
                    if 'response' in entry:entry['response']=v2.public_result(entry['response'],self.store.worker_key.encode(),uid+'/'+row['session_id'])
            return value
    def authorize(self,db,row,snapshot,module=None):
        from .agents.runtime import validate_execution
        validate_execution(snapshot)
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(row['uid'],)).fetchone();user=db.execute('SELECT * FROM users WHERE id=?',(row['uid'],)).fetchone()
        if not user or not user['active'] or user['auth_version']!=row['auth_version'] or row['cancel_requested'] or row['status'] not in ('queued','running'):reject('provider_authority_changed')
        if not runtime or runtime['revision']!=row['revision'] or runtime['security_blocked'] or runtime['recovery_required'] or runtime['gate_policy']=='closed_all' or runtime['status'] not in ('ready','draining'):reject('provider_runtime_changed')
        if self.store.maintenance_status(db)['maintenance_mode'] not in ('normal','frozen'):reject('provider_maintenance')
        plan=snapshot['provider_plan']
        if snapshot.get('provider_followup'):reject('provider_followup_read_only')
        if module is not None and module!=plan['kind']:reject('provider_method_changed')
        if snapshot.get('task_spec',{}).get('schema_version')!='task-spec-v4' or snapshot.get('agent_profile',{}).get('id')!='theft-assistant':reject('provider_agent_changed')
        applied=self.store.decrypt(runtime['applied_spec_ciphertext'])
        if plan.get('version')==v2.VERSION:
            from .provider_contracts import validate
            validate(self.store,row['uid'],plan,applied)
            return
        p=availability(self.store,row['uid'],plan['kind'],applied)
        if p['version']!=plan['plugin_version']:reject('provider_plugin_changed')
    def _event(self,rid,module,status):
        event(self.store,rid,'provider.'+module,'plugin',(v2.CATALOG.get(module) or CATALOG[module])[0],{'pending':'running','unknown':'failed'}.get(status,status),completed=now() if status!='pending' else None,capability=pid(module))
    def reserve(self,uid,rid,revision,operation,module):
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)
            if module in state['modules']:return False
            state['modules'][module]={'status':'pending','started':now(),'reservation_count':1,'dispatch_attempts':0,'response_count':0,'may_have_sent':False}
            self._save(db,rid,snap);self._event(rid,module,'pending')
            prior=db.execute('SELECT actual_plugins FROM invocations WHERE run_id=?',(rid,)).fetchone()
            if prior:db.execute('UPDATE invocations SET actual_plugins=? WHERE run_id=?',(encode(sorted(set(json.loads(prior[0]))|{pid(module)})),rid))
            return True
    def dispatch(self,uid,rid,revision,operation,module):
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)
            value=state['modules'].get(module)
            if not value or value['status']!='pending' or value.get('dispatch_attempts',0):reject('provider_dispatch_already_reserved')
            # This is a durable send-boundary attempt, not proof the supplier received HTTP.
            value.update(dispatch_attempts=1,may_have_sent=True)
            self._save(db,rid,snap)

    def complete(self,uid,rid,revision,operation,module,status,response=None):
        if status not in ('completed','unknown','cancelled'):reject('provider_invalid_status')
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)
            value=state['modules'].get(module)
            if not value or value['status']!='pending':reject('provider_not_pending')
            if status=='completed':
                value['response_count']=1
                value['may_have_sent']=True
                try:
                    plan=snap['provider_plan']
                    value['response']=(v2.parse_response(module,plan['query'],response,plan['limits'],plan['identities']) if plan.get('version')==v2.VERSION else parse_response(module,plan['query'],response))
                    if plan.get('version')==v2.VERSION:
                        value['public_response']=v2.public_result(value['response'],self.store.worker_key.encode(),uid+'/'+row['session_id'])
                except (ContractError,ValueError,TypeError,KeyError):status='rejected'
            value.update(status=status,completed=now());self._save(db,rid,snap);self._event(rid,module,status)
            return status
    def check(self,uid,rid,revision,operation,module=None):
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)

    def terminate(self,uid,rid,revision):
        with self.store.tx() as db:
            _,snap,state=self._load(db,uid,rid,revision)
            for kind,value in state['modules'].items():
                if value['status']=='pending':
                    value.update(status='unknown',completed=now());self._event(rid,kind,'unknown')
            self._save(db,rid,snap)
