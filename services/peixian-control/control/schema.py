"""Version dispatch: the historical v4 global fingerprint is only valid on v4."""
def validate(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 4:
        from .migrations_v4 import validate as check
    elif version == 5:
        from .pool_schema import validate as check
    elif version == 6:
        from .migrations_v6 import validate as check
    elif version == 7:
        from .migrations_v7 import validate as check
    elif version == 8:
        from .migrations_v8 import validate as check
    elif version == 9:
        from .migrations_v9 import validate as check
    elif version == 10:
        from .migrations_v10 import validate as check
    elif version == 11:
        from .migrations_v11 import validate as check
    else:
        raise ValueError("Unsupported Control database schema")
    check(db)
    validate_chain(db, version)


def validate_chain(db,version):
    """Verify every recorded ancestor without changing historical migration bytes."""
    from . import migrations_v4,migrations_v5,migrations_v6,migrations_v7,migrations_v8,migrations_v9,migrations_v10,migrations_v11
    modules={4:migrations_v4,5:migrations_v5,6:migrations_v6,7:migrations_v7,8:migrations_v8,9:migrations_v9,10:migrations_v10,11:migrations_v11}
    cursor=version;seen=set()
    while cursor>=4:
        module=modules[cursor]
        row=db.execute('SELECT * FROM schema_migrations WHERE migration_id=?',(module.MIGRATION_ID,)).fetchone()
        allowed={4,5} if cursor==6 else {cursor-1}
        if (not row or row['to_version']!=cursor or row['from_version'] not in allowed
            or row['script_digest']!=module.SCRIPT_DIGEST):raise ValueError('historical migration chain mismatch')
        seen.add(cursor);cursor=row['from_version']
    if cursor!=3 or {r[0] for r in db.execute('SELECT to_version FROM schema_migrations')}!=seen:raise ValueError('unexpected migration chain')
