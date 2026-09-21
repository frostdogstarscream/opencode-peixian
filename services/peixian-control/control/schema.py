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
    else:
        raise ValueError("Unsupported Control database schema")
    check(db)
