"""Bounded idle candidates. Only trusted worker observations can propose a pause."""
import math
from .store import now, ident
from .orchestration import request_fields, integer, opaque, reject


def proof_valid(proof):
    return (isinstance(proof, dict) and set(proof) == {'complete', 'sequence', 'idle_seconds'}
            and proof['complete'] is True and type(proof['sequence']) is int
            and 0 <= proof['sequence'] <= 2**53-1 and type(proof['idle_seconds']) in (int, float)
            and math.isfinite(proof['idle_seconds']) and 0 <= proof['idle_seconds'] <= 2**53-1)


def eligible(store, db, row):
    policy = store.maintenance_status(db)
    return (policy.get('idle_pause_enabled') and policy['maintenance_mode'] == 'normal' and policy['capacity_healthy']
            and row['active'] and row['reserved'] and row['status'] == 'ready' and row['gate_policy'] == 'open'
            and not row['security_blocked'] and not row['recovery_required'] and row['manual_stop_reason'] == 'none'
            and row['stop_reason'] == 'none' and row['desired'] == row['revision']
            and not db.execute("SELECT 1 FROM jobs WHERE uid=? AND (status IN ('queued','running','waiting_capacity') OR recovery_required=1)", (row['uid'],)).fetchone())


def candidates(store):
    # Rotation is advisory; authority remains in the conditional write transaction.
    cursor = getattr(store, '_idle_cursor', '')
    with store.read(snapshot=True) as db:
        policy = store.maintenance_status(db)
        if not policy.get('idle_pause_enabled') or policy['maintenance_mode'] != 'normal':
            return {'items': [], 'protocol_version': 2}
        # One candidate per host tick keeps the total probe budget independent
        # of account count; rotation resumes after exactly the returned candidate.
        rows = db.execute("SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.reserved=1 AND r.status='ready' ORDER BY (r.uid<=?),r.uid LIMIT 1", (cursor,)).fetchall()
        result=[]
        for row in rows:
            store._idle_cursor=row['uid']
            if not eligible(store, db, row): continue
            # Never send freshly generated desired configuration to an observation.
            if not row['applied_spec_ciphertext']: continue
            result.append({'uid':row['uid'], 'runtime_id':row['id'], 'state_version':row['state_version'],
                           'gateway_boot_id':row['gateway_boot_id'], 'spec':store.decrypt(row['applied_spec_ciphertext'])})
        return {'items':result, 'protocol_version':2}


def submit(store, data):
    request_fields(data, ('uid','state_version','gateway_boot_id','observed_at','idle_proof','activity_count','complete'),
                   ('uid','state_version','gateway_boot_id','observed_at','idle_proof','activity_count','complete'))
    opaque(data['uid']); integer(data['state_version'],'state'); integer(data['observed_at'],'observation time')
    stamp=now()
    if not 0 <= stamp-data['observed_at'] <= 3: reject('Idle observation expired')
    with store.tx() as db:
        row=db.execute('SELECT r.*,u.active FROM runtimes r JOIN users u ON u.id=r.uid WHERE r.uid=?',(data['uid'],)).fetchone()
        if not row or row['state_version']!=data['state_version'] or row['gateway_boot_id']!=data['gateway_boot_id'] or not eligible(store,db,row):
            return {'accepted':False}
        proof=data['idle_proof']
        valid=data['complete'] is True and type(data['activity_count']) is int and data['activity_count']==0 and proof_valid(proof)
        if not valid:
            db.execute('UPDATE runtimes SET last_activity=?,activity_boot_id=NULL WHERE uid=?',(stamp,row['uid']))
            return {'accepted':False}
        db.execute('UPDATE runtimes SET last_activity=?,activity_version=?,activity_boot_id=? WHERE uid=?',
                   (stamp-int(proof['idle_seconds']),proof['sequence'],data['gateway_boot_id'],row['uid']))
        cfg=store.pool_settings
        if (proof['idle_seconds'] < cfg['idle_timeout_seconds'] or row['ready_since'] is None
                or not max(cfg['min_ready_seconds'],cfg['resume_cooldown_seconds']) <= stamp-row['ready_since']
                or stamp-getattr(store,'_idle_started',stamp) < cfg['resume_cooldown_seconds']):
            return {'accepted':False}
        jid=ident()
        db.execute("INSERT INTO jobs(id,uid,action,status,revision,reason,idle_activity_version,idle_gateway_boot_id,idle_observed_at,created,updated) VALUES(?,?,'pause','queued',?,'idle_timeout',?,?,?,?,?)",
                   (jid,row['uid'],row['revision'],proof['sequence'],data['gateway_boot_id'],stamp,stamp,stamp))
        db.execute("UPDATE runtimes SET stop_reason='idle_timeout',state_version=state_version+1 WHERE uid=?",(row['uid'],))
        return {'accepted':True,'job_id':jid}


def final_valid(store, job, runtime, proof, boot, complete, count):
    return (complete is True and type(count) is int and count==0 and proof_valid(proof)
            and proof['sequence']==job['idle_activity_version'] and boot==job['idle_gateway_boot_id']
            and proof['idle_seconds']>=store.pool_settings['idle_timeout_seconds']
            and not runtime['security_blocked'] and runtime['manual_stop_reason']=='none'
            and runtime['stop_reason']=='idle_timeout')
