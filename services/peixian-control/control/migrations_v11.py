"""Lightweight task grouping; encrypted goals and source links, immutable Runs."""
import hashlib,os
from pathlib import Path
from .migrations_v4 import canonical,structure_digest
MIGRATION_ID='control.analysis-tasks.v11.1'
DDL=[
"CREATE TABLE analysis_tasks(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id),session_id TEXT NOT NULL,request_key TEXT NOT NULL,request_hash TEXT NOT NULL,environment TEXT NOT NULL CHECK(environment IN ('synthetic','acceptance_real')),context_version INTEGER NOT NULL CHECK(context_version>0),scope_version INTEGER NOT NULL CHECK(scope_version>0),payload_ciphertext TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL,UNIQUE(uid,session_id,request_key))",
"CREATE INDEX analysis_tasks_owner ON analysis_tasks(uid,session_id,created,id)",
"CREATE TABLE analysis_task_steps(id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES analysis_tasks(id),run_id TEXT NOT NULL UNIQUE REFERENCES business_runs(id),request_key TEXT NOT NULL,request_hash TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>0),payload_ciphertext TEXT NOT NULL,created INTEGER NOT NULL,UNIQUE(task_id,request_key),UNIQUE(task_id,sequence))",
"CREATE INDEX analysis_task_steps_order ON analysis_task_steps(task_id,sequence)"
]
NAMES=['analysis_tasks','analysis_tasks_owner','analysis_task_steps','analysis_task_steps_order']
SCRIPT_DIGEST=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def validate(db):
    from . import migrations_v10
    row=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone()
    if not row or (row['from_version'],row['to_version'],row['script_digest'])!=(10,11,SCRIPT_DIGEST):raise ValueError('v11 migration identity mismatch')
    for name,sql in zip(NAMES,DDL):
        actual=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
        if not actual or actual[0]!=sql:raise ValueError('v11 structure mismatch')
    if row['structure_digest']!=structure_digest(db):raise ValueError('v11 schema fingerprint mismatch')
    inherited=[tuple(x) for x in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name") if x['name'] not in NAMES]
    prior=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(migrations_v10.MIGRATION_ID,)).fetchone()
    if not prior or prior['script_digest']!=migrations_v10.SCRIPT_DIGEST or prior['structure_digest']!=hashlib.sha256(canonical(inherited).encode()).hexdigest():raise ValueError('v11 inherited schema mismatch')
    if db.execute('SELECT maintenance_mode FROM platform_state WHERE id=1').fetchone()[0] not in ('normal','frozen','repair_only'):raise ValueError('invalid maintenance policy')
def migrate(db,*,fresh,timestamp):
    from .migrations_v10 import validate as previous
    previous(db)
    if db.execute('PRAGMA user_version').fetchone()[0]!=10:raise ValueError('v11 requires schema v10')
    if not fresh:
        if os.getenv('PX_ALLOW_V11_MIGRATION')!='1' or db.execute('SELECT maintenance_mode FROM platform_state WHERE id=1').fetchone()[0]!='frozen':raise ValueError('v11 requires frozen offline approval and backup')
        if db.execute("SELECT 1 FROM business_runs WHERE status IN ('queued','running','cancelling','reconciling')").fetchone() or db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone() or db.execute('SELECT 1 FROM job_attempts WHERE outcome IS NULL').fetchone():raise ValueError('v11 requires resolved execution responsibilities')
    for sql in DDL:db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES(?,?,?,?,?,?)',(MIGRATION_ID,10,11,SCRIPT_DIGEST,structure_digest(db),timestamp))
    db.execute('PRAGMA user_version=11');validate(db)
