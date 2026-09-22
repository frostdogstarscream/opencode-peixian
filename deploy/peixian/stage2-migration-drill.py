"""Copy-only schema rehearsal. Never opens the source database for writing."""
import argparse,hashlib,json,os,sqlite3,sys
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'services/peixian-control'))
FLAGS={'PX_BACKEND_V6':'1','PX_TASK_CONTEXT_V1':'1','PX_TASK_CLARIFICATION_V1':'1','PX_TRUSTED_RESULT_V2':'1','PX_ALLOW_V7_MIGRATION':'1','PX_ALLOW_V8_MIGRATION':'1','PX_ALLOW_V9_MIGRATION':'1'}

def require(ok,code):
    if not ok:raise ValueError(code)

def read(path):return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
def copy_database(source,destination):
    destination=Path(destination)
    require(not destination.exists() and not destination.is_symlink(),'restore_target_exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with closing(read(source)) as src,closing(sqlite3.connect(destination)) as dst:src.backup(dst)
    os.chmod(destination,0o600)

def inventory(path):
    with closing(read(path)) as db:
        result={}
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            escaped=table.replace('"','""')
            rows=[json.dumps(list(row),ensure_ascii=False,separators=(',',':'),default=lambda x:{'bytes':x.hex()}) for row in db.execute('SELECT * FROM "'+escaped+'"')]
            result[table]={'count':len(rows),'sha256':hashlib.sha256(('\n'.join(sorted(rows))).encode()).hexdigest()}
        return {'schema':db.execute('PRAGMA user_version').fetchone()[0],'tables':result}

def drill(source,destination,key,worker,admin):
    from control.store import Store
    from control.schema import validate
    source,destination=Path(source).resolve(),Path(destination).absolute()
    require(source.is_file() and not destination.exists() and not destination.is_symlink(),'new_rehearsal_directory_required')
    require(not destination.is_relative_to(source.parent),'rehearsal_must_be_outside_source')
    destination.mkdir(parents=True,mode=0o700)
    before=destination/'original/control.sqlite3';copy_database(source,before);initial=inventory(before)
    require(initial['schema'] in (6,7,8,9),'unsupported_rehearsal_schema')
    current=destination/'migrated/control.sqlite3';copy_database(before,current)
    with closing(sqlite3.connect(current)) as db,db:
        require(not db.execute("SELECT 1 FROM business_runs WHERE status IN ('queued','running','cancelling','reconciling')").fetchone(),'unresolved_runs')
        require(not db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone(),'unresolved_jobs')
        require(not db.execute('SELECT 1 FROM job_attempts WHERE outcome IS NULL').fetchone(),'unresolved_attempts')
        db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
    prior={k:os.environ.get(k) for k in FLAGS}
    try:
        os.environ.update(FLAGS)
        store=Store(current.parent,key,worker,admin)
        require(store.schema_version()==9,'migration_not_v9')
        with store.read() as db:validate(db)
        after=inventory(current)
        protected={k:v for k,v in initial['tables'].items() if k not in ('platform_state','schema_migrations')}
        require(all(after['tables'].get(k)==v for k,v in protected.items()),'protected_content_changed')
        Store(current.parent,key,worker,admin)
        require(inventory(current)==after,'repeat_migration_changed_data')
        for label,path in [('before',before),('after',current)]:
            target=destination/('restored-'+label)/'control.sqlite3';copy_database(path,target)
            require(inventory(target)==inventory(path),'restore_content_changed')
        require(inventory(before)==initial,'backup_changed')
        receipt={'status':'passed','source_schema':initial['schema'],'target_schema':9,'source_opened_read_only':True,'source_is_full_stopped_backup':False,'repeated_start_unchanged':True,'protected_tables':len(protected),'protected_content_unchanged':True,'before_and_after_restored_to_empty_directories':True,'runtime_restore_executed':False,'tables':{k:v['count'] for k,v in after['tables'].items()}}
        (destination/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        return receipt
    finally:
        for k,v in prior.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','destination','key','worker','admin'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    try:print(json.dumps(drill(a.source,a.destination,a.key,a.worker,a.admin)))
    except (ValueError,OSError,sqlite3.Error) as exc:
        # Never include a source path, SQL row or encrypted credential in output.
        print(json.dumps({'status':'failed','code':str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'migration_rehearsal_failed'}));raise SystemExit(1)
