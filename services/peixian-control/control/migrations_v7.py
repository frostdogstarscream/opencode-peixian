"""Transactional context pointers. Never rewrites existing Run snapshots."""
import hashlib
import os
from pathlib import Path
from .migrations_v4 import canonical,structure_digest

MIGRATION_ID='control.session-context.v7.1'
DDL=["CREATE TABLE session_task_contexts(uid TEXT NOT NULL REFERENCES users(id),session_id TEXT NOT NULL,agent_id TEXT NOT NULL,agent_profile_sha256 TEXT NOT NULL,generation INTEGER NOT NULL CHECK(generation>0),version INTEGER NOT NULL CHECK(version>0),last_completed_run_id TEXT,last_data_run_id TEXT,confirmed_targets_ciphertext TEXT,pending_clarification_id TEXT,updated REAL NOT NULL,PRIMARY KEY(uid,session_id))"]
NAMES=['session_task_contexts']
SCRIPT_DIGEST=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def validate(db):
    from . import migrations_v6
    row=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone()
    if not row or (row['from_version'],row['to_version'],row['script_digest'])!=(6,7,SCRIPT_DIGEST):raise ValueError('v7 migration identity mismatch')
    for name,sql in zip(NAMES,DDL):
        actual=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
        if not actual or actual[0]!=sql:raise ValueError('v7 structure mismatch')
    if row['structure_digest']!=structure_digest(db):raise ValueError('v7 schema fingerprint mismatch')
    inherited=[tuple(x) for x in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name") if x['name'] not in NAMES]
    prior=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(migrations_v6.MIGRATION_ID,)).fetchone()
    if not prior or prior['script_digest']!=migrations_v6.SCRIPT_DIGEST or prior['structure_digest']!=hashlib.sha256(canonical(inherited).encode()).hexdigest():raise ValueError('v7 inherited schema mismatch')

    policy=db.execute('SELECT * FROM platform_state WHERE id=1').fetchone()
    if not policy or policy['maintenance_mode'] not in ('normal','frozen','repair_only'):raise ValueError('Invalid maintenance policy')
    if 'runtime_mode' in policy.keys() and (policy['runtime_mode'] not in ('eager','on_demand') or (policy['pool_policy_version'],policy['capacity_wait_enabled']) not in ((1,0),(2,0),(2,1),(3,0),(3,1)) or policy['idle_pause_enabled'] not in (0,1) or (policy['idle_pause_enabled'] and policy['pool_policy_version']<3)):raise ValueError('Invalid runtime policy')

def migrate(db,*,fresh,timestamp):
    from .migrations_v6 import validate as previous
    previous(db)
    if db.execute('PRAGMA user_version').fetchone()[0]!=6:raise ValueError('v7 requires schema v6')
    if not fresh:
        if os.getenv('PX_ALLOW_V7_MIGRATION')!='1' or db.execute('SELECT maintenance_mode FROM platform_state WHERE id=1').fetchone()[0]!='frozen':raise ValueError('v7 requires frozen offline approval and backup')
        if db.execute("SELECT 1 FROM business_runs WHERE status IN ('queued','running','cancelling','reconciling')").fetchone() or db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone() or db.execute('SELECT 1 FROM job_attempts WHERE outcome IS NULL').fetchone():raise ValueError('v7 requires resolved execution responsibilities')
    for sql in DDL:db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES(?,?,?,?,?,?)',(MIGRATION_ID,6,7,SCRIPT_DIGEST,structure_digest(db),timestamp))
    db.execute('PRAGMA user_version=7');validate(db)
