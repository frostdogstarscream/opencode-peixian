"""Additive backend contract migration. Original migration scripts remain immutable."""
import hashlib
import os
import re
from pathlib import Path
from .migrations_v4 import canonical, structure_digest

MIGRATION_ID = "control.backend-contract.v6.1"
DDL = [
 "CREATE TABLE departments(id TEXT PRIMARY KEY,name TEXT NOT NULL,code TEXT NOT NULL UNIQUE,parent_id TEXT REFERENCES departments(id),sort_order INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL)",
 "CREATE TABLE user_profiles(uid TEXT PRIMARY KEY REFERENCES users(id),display_name TEXT NOT NULL DEFAULT '',police_no TEXT NOT NULL DEFAULT '',position TEXT NOT NULL DEFAULT '',department_id TEXT REFERENCES departments(id),last_login INTEGER)",
 "CREATE TABLE model_profiles(mid TEXT PRIMARY KEY REFERENCES models(id),provider TEXT NOT NULL DEFAULT 'openai-compatible',context_length INTEGER,access_mode TEXT NOT NULL DEFAULT 'api',supports_tools INTEGER NOT NULL DEFAULT 0,test_status TEXT NOT NULL DEFAULT 'untested',updated INTEGER NOT NULL)",
 "CREATE TABLE skill_profiles(sid TEXT PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,dependencies TEXT NOT NULL DEFAULT '[]',source_type TEXT NOT NULL DEFAULT 'manual',updated INTEGER NOT NULL)",
 "CREATE TABLE business_runs(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id),session_id TEXT NOT NULL,request_key TEXT NOT NULL,request_hash TEXT NOT NULL,message_id TEXT NOT NULL UNIQUE,assistant_id TEXT,parent_id TEXT REFERENCES business_runs(id),status TEXT NOT NULL,phase TEXT NOT NULL,model_id TEXT NOT NULL,revision INTEGER NOT NULL,auth_version INTEGER NOT NULL,request_ciphertext TEXT NOT NULL,created INTEGER NOT NULL,started INTEGER,completed INTEGER,updated INTEGER NOT NULL,error_code TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,evidence_ciphertext TEXT,result_ciphertext TEXT,UNIQUE(uid,session_id,request_key))",
 "CREATE UNIQUE INDEX runs_one_active ON business_runs(uid,session_id) WHERE status IN ('queued','running','cancelling','reconciling')",
 "CREATE INDEX runs_owner_created ON business_runs(uid,created,id)",
 "CREATE TABLE run_deliveries(run_id TEXT PRIMARY KEY REFERENCES business_runs(id),state TEXT NOT NULL,attempted INTEGER,receipt TEXT,next_check INTEGER NOT NULL DEFAULT 0)",
 "CREATE TABLE run_events(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES business_runs(id),event_key TEXT NOT NULL,sequence INTEGER NOT NULL,step_type TEXT NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL,started INTEGER,completed INTEGER,capability_id TEXT,input_summary TEXT NOT NULL DEFAULT '',output_summary TEXT NOT NULL DEFAULT '',record_count INTEGER NOT NULL DEFAULT 0,evidence_refs TEXT NOT NULL DEFAULT '[]',error_code TEXT,UNIQUE(run_id,event_key),UNIQUE(run_id,sequence))",
 "CREATE TABLE invocations(id TEXT PRIMARY KEY,run_id TEXT NOT NULL UNIQUE REFERENCES business_runs(id),uid TEXT NOT NULL,department_id TEXT,model_id TEXT NOT NULL,selected_skills TEXT NOT NULL,selected_plugins TEXT NOT NULL,actual_plugins TEXT NOT NULL DEFAULT '[]',query_summary TEXT NOT NULL,created INTEGER NOT NULL)",
 "CREATE INDEX invocations_filters ON invocations(uid,department_id,model_id,created)",
 "CREATE TABLE skill_drafts(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id),request_key TEXT NOT NULL,request_hash TEXT NOT NULL,session_id TEXT,source_type TEXT NOT NULL,status TEXT NOT NULL,content_ciphertext TEXT NOT NULL,run_id TEXT REFERENCES business_runs(id),saved_skill_id TEXT,created INTEGER NOT NULL,updated INTEGER NOT NULL,error_code TEXT,UNIQUE(uid,request_key))",
 "CREATE TABLE draft_trials(id TEXT PRIMARY KEY,uid TEXT NOT NULL,draft_id TEXT NOT NULL REFERENCES skill_drafts(id),request_key TEXT NOT NULL,request_hash TEXT NOT NULL,session_id TEXT,run_id TEXT REFERENCES business_runs(id),created INTEGER NOT NULL,UNIQUE(uid,request_key))",
]
NAMES = [re.search(r'CREATE (?:UNIQUE )?(?:TABLE|INDEX) (\w+)', sql).group(1) for sql in DDL]
SCRIPT_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def validate(db):
    row = db.execute('SELECT * FROM schema_migrations WHERE migration_id=?', (MIGRATION_ID,)).fetchone()
    if not row or row['from_version'] not in (4,5) or row['to_version']!=6 or row['script_digest']!=SCRIPT_DIGEST:
        raise ValueError('v6 migration identity mismatch')
    for name, sql in zip(NAMES, DDL):
        actual=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
        if not actual or actual[0]!=sql: raise ValueError('v6 structure mismatch')
    if row['structure_digest']!=structure_digest(db):raise ValueError('v6 schema fingerprint mismatch')
    # Verify the inherited structure without changing historical migration fingerprints.
    inherited=[tuple(x) for x in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name") if x['name'] not in NAMES]
    historical=db.execute('SELECT * FROM schema_migrations WHERE to_version=?',(row['from_version'],)).fetchone()
    from . import migrations_v4, migrations_v5
    digest=migrations_v5.SCRIPT_DIGEST if row['from_version']==5 else migrations_v4.SCRIPT_DIGEST
    if not historical or historical['script_digest']!=digest or historical['structure_digest']!=hashlib.sha256(canonical(inherited).encode()).hexdigest():
        raise ValueError('v6 inherited schema mismatch')
    policy=db.execute('SELECT * FROM platform_state WHERE id=1').fetchone()
    if not policy or policy['maintenance_mode'] not in ('normal','frozen','repair_only'):raise ValueError('Invalid maintenance policy')
    if 'runtime_mode' in policy.keys() and (policy['runtime_mode'] not in ('eager','on_demand')
            or (policy['pool_policy_version'],policy['capacity_wait_enabled']) not in ((1,0),(2,0),(2,1),(3,0),(3,1))
            or policy['idle_pause_enabled'] not in (0,1) or (policy['idle_pause_enabled'] and policy['pool_policy_version']<3)):
        raise ValueError('Invalid runtime policy')



def migrate(db, *, fresh, timestamp):
    from .schema import validate as previous
    previous(db)
    version=db.execute('PRAGMA user_version').fetchone()[0]
    if not fresh:
        if os.getenv('PX_ALLOW_V6_MIGRATION')!='1' or db.execute('SELECT maintenance_mode FROM platform_state WHERE id=1').fetchone()[0]!='frozen':
            raise ValueError('v6 requires an approved frozen offline migration')
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone() or db.execute('SELECT 1 FROM job_attempts WHERE outcome IS NULL').fetchone():
            raise ValueError('v6 requires resolved execution responsibilities')
    for sql in DDL: db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES(?,?,?,?,?,?)',(MIGRATION_ID,version,6,SCRIPT_DIGEST,structure_digest(db),timestamp))
    db.execute('PRAGMA user_version=6')
    validate(db)
