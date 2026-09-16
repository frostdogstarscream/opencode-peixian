"""Real temporary SQLite files exercise the v3 read/write and auth boundaries."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import time

from cryptography.fernet import Fernet
import pytest

from control.store import Store, SCHEMA_VERSION, digest, now

PASSWORD = "Synthetic-database-password-2026"


@pytest.fixture
def store_args(tmp_path, monkeypatch):
    monkeypatch.delenv("PX_DB_BUSY_MS", raising=False)
    monkeypatch.setenv("MAX_RUNTIMES", "4")
    for name, value in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-credential-00000000000"),
                        ("admin", PASSWORD.encode())):
        (tmp_path / name).write_bytes(value)
    return tmp_path / "data", tmp_path / "key", tmp_path / "worker", tmp_path / "admin"


@pytest.fixture
def store(store_args):
    return Store(*store_args)


def track_connections(store, monkeypatch):
    connect = store._connect
    connections, statements = [], []

    def tracked(**kwargs):
        db = connect(**kwargs)
        connections.append(db)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(store, "_connect", tracked)
    return connections, statements


def assert_closed(connection):
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_normal_reads_are_readonly_and_do_not_request_write_transactions(store, monkeypatch):
    connections, statements = track_connections(store, monkeypatch)
    assert store.one("SELECT count(*) AS n FROM users")["n"] == 1
    assert len(store.rows("SELECT role FROM users")) == 1
    assert store.schema_version() == SCHEMA_VERSION == 3
    uid = store.one("SELECT id FROM users")["id"]
    assert store.user(uid)["runtime"] is None
    assert "BEGIN IMMEDIATE" not in statements
    assert not any("JOURNAL_MODE=" in sql.upper() for sql in statements)
    assert "BEGIN" in statements  # The user + runtime pair uses one read snapshot.
    for db in connections:
        assert_closed(db)
    with store.read() as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("UPDATE users SET active=0")
        # URI mode=ro remains a second boundary if a caller changes query_only.
        db.execute("PRAGMA query_only=OFF")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("UPDATE users SET active=0")


def test_fifty_reads_continue_during_uncommitted_write(store):
    ready = threading.Barrier(50)

    def read():
        ready.wait(timeout=10)
        return store.one("SELECT active FROM users")["active"]

    with store.tx() as db:
        db.execute("UPDATE users SET active=0")
        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(read) for _ in range(50)]
            assert [future.result(timeout=10) for future in futures] == [1] * 50
    assert store.one("SELECT active FROM users")["active"] == 0


def test_snapshot_keeps_one_view_but_normal_reads_see_new_commits(store):
    with store.read(snapshot=True) as snapshot:
        assert snapshot.execute("SELECT active FROM users").fetchone()[0] == 1
        with store.tx() as writer:
            writer.execute("UPDATE users SET active=0")
        assert snapshot.execute("SELECT active FROM users").fetchone()[0] == 1
        assert store.one("SELECT active FROM users")["active"] == 0
    with store.read() as plain:
        assert plain.execute("SELECT active FROM users").fetchone()[0] == 0
        with store.tx() as writer:
            writer.execute("UPDATE users SET active=1")
        assert plain.execute("SELECT active FROM users").fetchone()[0] == 1


def test_busy_begin_is_bounded_and_failed_connection_closed(store, monkeypatch):
    store.busy_timeout_ms = 75
    connections, _ = track_connections(store, monkeypatch)
    with store.tx():
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            with store.tx():
                pytest.fail("A second writer must not acquire the existing write lock")
        elapsed = time.monotonic() - started
        assert elapsed < 0.8
        assert_closed(connections[-1])
    with store.tx() as db:
        db.execute("UPDATE users SET active=0")


def test_business_and_real_commit_failure_rollback_close_and_preserve_errors(store, monkeypatch):
    connections, _ = track_connections(store, monkeypatch)
    with pytest.raises(RuntimeError, match="synthetic business failure"):
        with store.tx() as db:
            db.execute("UPDATE users SET active=0")
            raise RuntimeError("synthetic business failure")
    assert_closed(connections[-1])
    assert store.one("SELECT active FROM users")["active"] == 1
    with store.tx() as db:
        db.execute("CREATE TABLE parent_test(id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE child_test(id INTEGER REFERENCES parent_test(id) DEFERRABLE INITIALLY DEFERRED)")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        with store.tx() as db:
            db.execute("INSERT INTO child_test VALUES(9)")
    assert_closed(connections[-1])
    assert store.one("SELECT count(*) AS n FROM child_test")["n"] == 0


@pytest.mark.parametrize("failure", ["PRAGMA foreign_keys=ON", "PRAGMA busy_timeout=1000", "PRAGMA query_only=ON", "BEGIN"])
def test_connection_configuration_and_read_begin_failures_close(store, monkeypatch, failure):
    original_connect = sqlite3.connect
    connections = []

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == failure:
                raise sqlite3.OperationalError("synthetic setup failure")
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=FaultConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="synthetic setup failure"):
        with store.read(snapshot=True):
            pytest.fail("Setup must fail before exposing a connection")
    assert len(connections) == 1
    assert_closed(connections[0])


def test_read_business_error_closes_snapshot(store, monkeypatch):
    connections, _ = track_connections(store, monkeypatch)
    with pytest.raises(RuntimeError, match="synthetic read failure"):
        with store.read(snapshot=True) as db:
            db.execute("SELECT active FROM users").fetchone()
            raise RuntimeError("synthetic read failure")
    assert_closed(connections[0])


@pytest.mark.parametrize("value", ["0", "-1", "1001", "1.5", " 100", "infinite", "１２"])
def test_busy_setting_rejects_invalid_or_unbounded_values(store_args, monkeypatch, value):
    monkeypatch.setenv("PX_DB_BUSY_MS", value)
    with pytest.raises(ValueError, match="PX_DB_BUSY_MS"):
        Store(*store_args)


def test_wal_and_schema_are_preserved_across_reopen(store, store_args):
    with store.read() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    reopened = Store(*store_args)
    assert reopened.schema_version() == 3
    assert reopened.one("SELECT count(*) AS n FROM users")["n"] == 1
    assert len(reopened.rows("SELECT * FROM audit WHERE action='schema.migrate'")) == 2


def test_last_runtime_slot_is_reserved_atomically(store, monkeypatch):
    monkeypatch.setenv("MAX_RUNTIMES", "1")
    password_hash = store.passwords.hash(PASSWORD)
    ready = threading.Barrier(2)

    def create(name):
        ready.wait(timeout=5)
        try:
            return store.create_user_prehashed(name, password_hash)[0]["id"]
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(create, ["synthetic-a", "synthetic-b"]))
    assert sum(uid is not None for uid in result) == 1
    assert store.one("SELECT count(*) AS n FROM runtimes WHERE reserved=1")["n"] == 1
    assert store.one("SELECT count(*) AS n FROM jobs")["n"] == 1


def test_create_user_hashing_does_not_hold_write_transaction(store, monkeypatch):
    original_hash = store.passwords.hash

    def hash_password(hasher, password):
        # An independent writer can run during crypto; this fails if crypto is in tx.
        with store.tx() as db:
            db.execute("UPDATE users SET active=active")
        return original_hash(password)

    monkeypatch.setattr(type(store.passwords), "hash", hash_password)
    user, _ = store.create_user("synthetic", PASSWORD)
    assert user["username"] == "synthetic"


def test_login_commit_rechecks_snapshot_and_account_enablement(store):
    user = store.one("SELECT * FROM users")
    kwargs = dict(expected_password=user["password"], expected_auth_version=user["auth_version"],
                  token_hash=digest("synthetic-login"), csrf="synthetic-csrf", expires=now() + 600)
    with store.tx() as db:
        db.execute("UPDATE users SET active=0")
    assert not store.create_browser_auth(user["id"], **kwargs)
    with store.tx() as db:
        db.execute("UPDATE users SET active=1,auth_version=auth_version+1")
    assert not store.create_browser_auth(user["id"], **kwargs)
    kwargs["expected_auth_version"] += 1
    with store.tx() as db:
        db.execute("UPDATE users SET password='synthetic-changed-hash'")
    assert not store.create_browser_auth(user["id"], **kwargs)
    assert store.rows("SELECT * FROM auth") == []


def test_password_commit_preserves_only_current_auth_and_rejects_old_snapshot(store):
    user = store.one("SELECT * FROM users")
    for token in ("current", "other"):
        assert store.create_browser_auth(user["id"], expected_password=user["password"],
                                         expected_auth_version=user["auth_version"], token_hash=digest(token),
                                         csrf="synthetic", expires=now() + 600)
    new_hash = store.passwords.hash("Synthetic-new-password-2026")
    kwargs = dict(expected_password=user["password"], expected_auth_version=user["auth_version"],
                  session_hash=digest("current"), new_password_hash=new_hash)
    assert store.change_password(user["id"], **kwargs)
    assert not store.change_password(user["id"], **kwargs)
    auth = store.rows("SELECT * FROM auth")
    assert len(auth) == 1 and auth[0]["hash"] == digest("current")
    assert auth[0]["version"] == user["auth_version"] + 1
    current = store.one("SELECT * FROM users")
    assert current["password"] == new_hash and current["must_change"] == 0


@pytest.mark.parametrize("mutation", ["DELETE FROM auth", "UPDATE auth SET expires=0", "UPDATE auth SET version=0", "UPDATE users SET active=0"])
def test_password_commit_rejects_revoked_or_stale_auth(store, mutation):
    user = store.one("SELECT * FROM users")
    assert store.create_browser_auth(user["id"], expected_password=user["password"],
                                     expected_auth_version=user["auth_version"], token_hash=digest("current"),
                                     csrf="synthetic", expires=now() + 600)
    with store.tx() as db:
        db.execute(mutation)
    assert not store.change_password(user["id"], expected_password=user["password"],
                                     expected_auth_version=user["auth_version"], session_hash=digest("current"),
                                     new_password_hash=store.passwords.hash("Synthetic-new-password-2026"))
    assert store.one("SELECT password FROM users")["password"] == user["password"]


def test_cleanup_errors_do_not_replace_original_transaction_error(store, monkeypatch):
    original_connect = sqlite3.connect
    connections = []

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "ROLLBACK":
                raise sqlite3.OperationalError("synthetic rollback failure")
            return super().execute(sql, *args, **kwargs)

        def close(self):
            super().close()
            raise sqlite3.OperationalError("synthetic close failure")

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=FaultConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(RuntimeError, match="original business error"):
        with store.tx() as db:
            db.execute("UPDATE users SET active=0")
            raise RuntimeError("original business error")
    assert_closed(connections[0])
    with original_connect(store.path) as db:
        assert db.execute("SELECT active FROM users").fetchone()[0] == 1
