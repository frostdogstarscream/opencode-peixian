"""Append-only owner reviews; immutable Run results are never updated."""
import hashlib,os
from pathlib import Path
from .migrations_v4 import canonical,structure_digest
MIGRATION_ID='control.owner-reviews.v10.1'
DDL=["CREATE TABLE run_reviews(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES business_runs(id),uid TEXT NOT NULL REFERENCES users(id),result_digest TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('consistent','needs_information','inconsistent')),payload_ciphertext TEXT NOT NULL,supersedes TEXT REFERENCES run_reviews(id),created INTEGER NOT NULL)","CREATE INDEX run_reviews_owner ON run_reviews(uid,run_id,created,id)"]
NAMES=['run_reviews','run_reviews_owner']
SCRIPT_DIGEST=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def validate(db):
    from . import migrations_v9
    row=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(MIGRATION_ID,)).fetchone()
    if not row or (row['from_version'],row['to_version'],row['script_digest'])!=(9,10,SCRIPT_DIGEST):raise ValueError('v10 migration identity mismatch')
    for name,sql in zip(NAMES,DDL):
        actual=db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
        if not actual or actual[0]!=sql:raise ValueError('v10 structure mismatch')
    if row['structure_digest']!=structure_digest(db):raise ValueError('v10 schema fingerprint mismatch')
    inherited=[tuple(x) for x in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name") if x['name'] not in NAMES]
    prior=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(migrations_v9.MIGRATION_ID,)).fetchone()
    if not prior or prior['script_digest']!=migrations_v9.SCRIPT_DIGEST or prior['structure_digest']!=hashlib.sha256(canonical(inherited).encode()).hexdigest():raise ValueError('v10 inherited schema mismatch')
    if db.execute('SELECT maintenance_mode FROM platform_state WHERE id=1').fetchone()[0] not in ('normal','frozen','repair_only'):raise ValueError('invalid maintenance policy')
def migrate(db,*,fresh,timestamp):
    from .migrations_v9 import validate as previous
    previous(db)
    if db.execute('PRAGMA user_version').fetchone()[0]!=9:raise ValueError('v10 requires schema v9')
    if not fresh:
        if os.getenv('PX_ALLOW_V10_MIGRATION')!='1' or db.execute('SELECT maintenance_mode FROM platform_state WHERE id=1').fetchone()[0]!='frozen':raise ValueError('v10 requires frozen offline approval and backup')
        if db.execute("SELECT 1 FROM business_runs WHERE status IN ('queued','running','cancelling','reconciling')").fetchone() or db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone() or db.execute('SELECT 1 FROM job_attempts WHERE outcome IS NULL').fetchone():raise ValueError('v10 requires resolved execution responsibilities')
    for sql in DDL:db.execute(sql)
    db.execute('INSERT INTO schema_migrations VALUES(?,?,?,?,?,?)',(MIGRATION_ID,9,10,SCRIPT_DIGEST,structure_digest(db),timestamp))
    db.execute('PRAGMA user_version=10');validate(db)
