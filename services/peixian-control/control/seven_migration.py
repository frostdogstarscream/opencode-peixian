"""Trusted operator migration. No browser endpoint and no database restore rollback.

Invoke inside the matching Control container after a full private deployment backup.
A receipt contains encrypted row images; it must live outside source control.
"""
import argparse,hashlib,io,json,os,zipfile
from pathlib import Path
from .store import encode,ident,now
from .official_methods import BY_ID,identify
from .scenario_context import REGISTRY
from .facts_runtime import MODULES,capability,tool
from shared.connection_policy import policy

OLD='peixian-synthetic-records'
VERSION='1.0.0'
def stable(value):return hashlib.sha256(value.encode()).hexdigest()[:28]
def fail(message):raise ValueError(message)
def fingerprint(value):return hashlib.sha256(encode(value).encode()).hexdigest()
def rows(db,sql,params=()):return [dict(x) for x in db.execute(sql,params)]
def publish(store,root):
    root=Path(root);out=[]
    with store.tx() as db:
        source=rows(db,"SELECT c.* FROM connections c JOIN plugin_connections b ON b.connection_id=c.id WHERE b.plugin=? AND b.version='1.5.1' AND b.alias='peixian_records'",(OLD,))
        if len(source)!=1:fail('legacy_connection_missing')
        source=source[0];base=json.loads(source['config'])
        if not base['enabled']:fail('legacy_connection_disabled')
        for module in MODULES:
            pid=capability(module);data=(root/(pid+'-'+VERSION+'.zip')).read_bytes();digest=hashlib.sha256(data).hexdigest()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if set(z.namelist())!={'manifest.json','entry.mjs'}:fail('unexpected_package_files')
                manifest=json.loads(z.read('manifest.json'))
                if manifest['id']!=pid or manifest['version']!=VERSION or manifest['tools']!=[tool(module)] or set(manifest['connections'])!={'records'}:fail('package_identity_mismatch')
            existing=db.execute('SELECT digest FROM plugins WHERE id=? AND version=?',(pid,VERSION)).fetchone()
            if existing and existing['digest']!=digest:fail('immutable_plugin_conflict')
            target=store.root/'packages'/(digest+'.zip');target.parent.mkdir(exist_ok=True)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:fail('package_hash_conflict')
            if not target.exists():target.write_bytes(data);target.chmod(0o644)
            db.execute('INSERT OR IGNORE INTO plugins VALUES(?,?,?,?,?,?,?,1)',(pid,VERSION,manifest['name'],manifest['description'],encode(manifest),str(target),digest))
            cid=stable('seven-connection-v1:'+module)
            config=policy({**base,'name':manifest['name']+'专属连接','allowed_methods':['GET','POST'],'allowed_paths':['/health','/v1/demo/records/query'],'request_rules':[{'method':'GET','path':'/health'},{'method':'POST','path':'/v1/demo/records/query','json':{'module':module}}]})
            old=db.execute('SELECT config,secret FROM connections WHERE id=?',(cid,)).fetchone()
            if old and (json.loads(old['config'])!=config or old['secret']!=source['secret']):fail('connection_modified')
            db.execute('INSERT OR IGNORE INTO connections VALUES(?,?,?,1)',(cid,encode(config),source['secret']))
            binding=db.execute("SELECT connection_id FROM plugin_connections WHERE plugin=? AND version=? AND alias='records'",(pid,VERSION)).fetchone()
            if binding and binding[0]!=cid:fail('binding_modified')
            db.execute('INSERT OR IGNORE INTO plugin_connections VALUES(?,?,?,?)',(pid,VERSION,'records',cid))
            out.append({'id':pid,'version':VERSION,'sha256':digest})
        for method in BY_ID.values():
            tid=stable(method['id']+':'+method['version'])
            old=db.execute('SELECT content FROM templates WHERE id=?',(tid,)).fetchone()
            if old and old[0]!=method['content']:fail('official_template_modified')
            db.execute('INSERT OR IGNORE INTO templates VALUES(?,?,?,?)',(tid,method['name'],'官方V3固定资料方法',method['content']))
        store.audit('operator','seven.plugins.publish','seven-v1',actor_role='super_admin')
    return out

def state(db,uid):
    values=[OLD]+[capability(m) for m in MODULES];marks=','.join('?' for _ in values)
    return {'installs':rows(db,'SELECT * FROM installs WHERE uid=? AND plugin IN ('+marks+') ORDER BY plugin',(uid,*values)),
       'grants':rows(db,"SELECT * FROM grants WHERE uid=? AND kind='plugin' AND resource IN ("+marks+') ORDER BY resource',(uid,*values)),
       'skills':rows(db,'SELECT * FROM skills WHERE uid=? ORDER BY id',(uid,)),
       'profiles':rows(db,'SELECT p.* FROM skill_profiles p JOIN skills s ON s.id=p.sid WHERE s.uid=? ORDER BY p.sid',(uid,))}

def idle(db,uid):
    user=db.execute('SELECT role FROM users WHERE id=?',(uid,)).fetchone()
    if not user or user['role']!='user':fail('ordinary_account_required')
    if db.execute("SELECT 1 FROM business_runs WHERE uid=? AND status NOT IN ('completed','failed','cancelled')",(uid,)).fetchone():fail('active_run_wait_required')
    if db.execute("SELECT 1 FROM jobs WHERE uid=? AND (status IN ('queued','running') OR recovery_required=1)",(uid,)).fetchone():fail('environment_job_wait_required')
    runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(uid,)).fetchone()
    if not runtime or runtime['status']!='ready' or runtime['revision']!=runtime['desired'] or runtime['recovery_required'] or runtime['security_blocked']:fail('ready_environment_required')
    return dict(runtime)

def write_receipt(store,path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as output:output.write(store.encrypt(value));output.flush();os.fsync(output.fileno())

def migrate(store,uid,path):
    path=Path(path)
    if path.exists():
        receipt=store.decrypt(path.read_text())
        if receipt['uid']!=uid:fail('receipt_owner_mismatch')
        if store.one('SELECT 1 FROM audit WHERE action=? AND target=?',(receipt['action'],uid)):return {'status':'already_applied','uid':uid}
        fail('prepared_receipt_requires_review')
    with store.tx() as db:
        runtime=idle(db,uid);before=state(db,uid)
        old=next((x for x in before['installs'] if x['plugin']==OLD),None)
        if not old or not any(x['resource']==OLD for x in before['grants']):fail('legacy_install_and_grant_required')
        if any(x['plugin']!=OLD for x in before['installs']):fail('independent_install_requires_manual_review')
        for module in MODULES:
            pid=capability(module)
            if not db.execute('SELECT 1 FROM plugins WHERE id=? AND version=? AND enabled=1',(pid,VERSION)).fetchone():fail('publish_first')
            db.execute("INSERT OR IGNORE INTO grants VALUES(?,'plugin',?)",(uid,pid))
            db.execute('INSERT INTO installs VALUES(?,?,?,?,?,NULL)',(uid,pid,VERSION,old['enabled'],store.encrypt({})))
        db.execute('DELETE FROM installs WHERE uid=? AND plugin=?',(uid,OLD));db.execute("DELETE FROM grants WHERE uid=? AND kind='plugin' AND resource=?",(uid,OLD))
        # Only exact official hashes are eligible. Never overwrite edited personal copies.
        recognized={scene:[] for scene in ('DEMO-CASE-GAMBLING','DEMO-CASE-THEFT')}
        for skill in before['skills']:
            scene=REGISTRY.get(hashlib.sha256(skill['content'].encode()).hexdigest())
            if scene:recognized[scene].append(skill)
        for method in BY_ID.values():
            candidates=recognized[method['scenario_id']] if method['method'] in ('gambling','theft') else []
            old_skill=max(candidates,key=lambda v:(v['version'],v['id'])) if candidates else None
            if old_skill:
                sid=old_skill['id'];history=json.loads(old_skill['history']);history.append({k:old_skill[k] for k in ('name','description','content','enabled','version')})
                db.execute('UPDATE skills SET content=?,description=?,version=version+1,history=? WHERE id=?',(method['content'],'官方V3固定资料方法',encode(history[-10:]),sid))
                for prior in candidates:
                    if prior['id']!=sid:db.execute('UPDATE skills SET enabled=0 WHERE id=?',(prior['id'],))
            else:
                sid=stable(uid+':'+method['id']);name=method['name']
                if db.execute('SELECT 1 FROM skills WHERE uid=? AND name=?',(uid,name)).fetchone():name+='-官方V3'
                db.execute("INSERT INTO skills VALUES(?,?,?,?,?,1,1,'[]')",(sid,uid,name,'官方V3固定资料方法',method['content']))
            db.execute("INSERT INTO skill_profiles(sid,dependencies,source_type,updated) VALUES(?,?,'official_v3',?) ON CONFLICT(sid) DO UPDATE SET dependencies=excluded.dependencies,source_type=excluded.source_type,updated=excluded.updated",(sid,encode(method['dependency_ids']),now()))
        after=state(db,uid);action='seven.migrate.'+ident()
        write_receipt(store,path,{'version':1,'uid':uid,'runtime_id':runtime['id'],'action':action,'before':before,'expected':fingerprint(after),'old_plugin_version':old['version']})
        job=store.queue_in_transaction(db,uid)
        store.audit('operator',action,uid,actor_role='super_admin')
        return {'status':'queued','uid':uid,'job':job['id'],'desired':job['revision']}

def rollback(store,uid,path):
    receipt=store.decrypt(Path(path).read_text())
    if receipt['uid']!=uid:fail('receipt_owner_mismatch')
    action=receipt['action']+'.rollback'
    with store.tx() as db:
        if db.execute('SELECT 1 FROM audit WHERE action=? AND target=?',(action,uid)).fetchone():return {'status':'already_rolled_back'}
        idle(db,uid)
        if fingerprint(state(db,uid))!=receipt['expected']:fail('configuration_changed_review_required')
        if not db.execute('SELECT 1 FROM plugins WHERE id=? AND version=? AND enabled=1',(OLD,receipt['old_plugin_version'])).fetchone():fail('restore_archived_version_first')
        # Only replace the domain rows covered by the exact receipt; never touch Runs/files.
        for table in ('installs','grants'):
            column='plugin' if table=='installs' else 'resource'
            values=[OLD]+[capability(m) for m in MODULES];marks=','.join('?' for _ in values)
            db.execute('DELETE FROM '+table+' WHERE uid=? AND '+column+' IN ('+marks+')',(uid,*values))
        db.execute('DELETE FROM skill_profiles WHERE sid IN (SELECT id FROM skills WHERE uid=?)',(uid,))
        db.execute('DELETE FROM skills WHERE uid=?',(uid,))
        for key,table in [('installs','installs'),('grants','grants'),('skills','skills'),('profiles','skill_profiles')]:
            for row in receipt['before'][key]:
                columns=list(row);db.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(row.values()))
        job=store.queue_in_transaction(db,uid);store.audit('operator',action,uid,actor_role='super_admin')
        return {'status':'queued','job':job['id'],'desired':job['revision']}

def archive(store):
    with store.tx() as db:
        if db.execute('SELECT 1 FROM installs WHERE plugin=?',(OLD,)).fetchone() or db.execute("SELECT 1 FROM grants WHERE kind='plugin' AND resource=?",(OLD,)).fetchone():fail('legacy_accounts_remain')
        for row in db.execute('SELECT applied_spec_ciphertext FROM runtimes'):
            if row[0] and any(p['id']==OLD for p in store.decrypt(row[0]).get('plugins',[])):fail('legacy_applied_runtime_remains')
        db.execute('UPDATE plugins SET enabled=0 WHERE id=?',(OLD,))
        for row in db.execute('SELECT DISTINCT connection_id FROM plugin_connections WHERE plugin=?',(OLD,)).fetchall():
            if db.execute('SELECT 1 FROM plugin_connections WHERE connection_id=? AND plugin<>?',(row[0],OLD)).fetchone():continue
            c=db.execute('SELECT config FROM connections WHERE id=?',(row[0],)).fetchone();config=json.loads(c[0]);config['enabled']=False
            db.execute('UPDATE connections SET config=?,revision=revision+1 WHERE id=?',(encode(config),row[0]))
        store.audit('operator','seven.legacy.archive',OLD,actor_role='super_admin')
    return {'status':'archived'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['publish','migrate','rollback','archive']);parser.add_argument('--packages',type=Path);parser.add_argument('--uid');parser.add_argument('--receipt',type=Path)
    args=parser.parse_args()
    from .settings import configured_store
    store=configured_store()
    if args.action=='publish':result=publish(store,args.packages)
    elif args.action=='archive':result=archive(store)
    else:result=globals()[args.action](store,args.uid,args.receipt)
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
