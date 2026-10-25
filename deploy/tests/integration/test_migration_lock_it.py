"""Real-docker checks of the deploy's migration lock (DEP-B20 to DEP-B23). Opt-in: BOOKFINDER_IT=1.

What is real: a throwaway PostgreSQL 17 container (pgvector image, the same one the psql lock session uses), the
RealLockHolder adapter with its psql container, and the web image's efbundle for the Npgsql connection-string check.
What is faked: the state machine's other effects (snapshot, compose, state files) in the race scenario, which reuses
the unit-test world from tests/host/test_machine.py with the real lock holder swapped in.

Every docker object is named bf-it-lock-* or bookfinder-deploy-lock-*; the module fixture removes them.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "deploy" / "host"))
sys.path.insert(0, str(REPO / "deploy" / "tests" / "host"))

import test_machine as tm
from bookfinder_host import adapters
from bookfinder_host.exit_codes import FAILED_MIGRATION, OK
from bookfinder_host.locks import CATALOG_MIGRATION_LOCK_KEY
from bookfinder_host.ports import EffectFailed, MigrationConnectionActive, SubprocessRunner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("BOOKFINDER_IT") != "1", reason="set BOOKFINDER_IT=1 to run the migration lock integration"),
]

KEY = CATALOG_MIGRATION_LOCK_KEY
DB_CONTAINER = "bf-it-lock-db"
DB_NAME = "bookfinder"
DB_USER = "bf"
PSQL_IMAGE = "pgvector/pgvector:0.8.7-pg17"
WEB_IMAGE = "book-finder-web:local"
LOCK_PREFIX = "bookfinder-deploy-lock-"
EFBUNDLE_APP = "bookfinder-efbundle"


def docker(*args: str, check: bool = True, timeout: float = 900, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check, env=env)


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout_s: float, interval_s: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return bool(predicate())


def lock_containers() -> list[str]:
    return [n for n in docker("ps", "-a", "--format", "{{.Names}}").stdout.split() if n.startswith(LOCK_PREFIX)]


class Db:
    def __init__(self, gateway: str, port: int, password: str) -> None:
        self.gateway = gateway
        self.port = port
        self.password = password

    @property
    def url(self) -> str:
        return f"postgres://{DB_USER}:{self.password}@{self.gateway}:{self.port}/{DB_NAME}"

    def _psql_args(self) -> list[str]:
        return ["psql", "-X", "-At", "-h", "127.0.0.1", "-U", DB_USER, "-d", DB_NAME]

    def run(self, sql: str) -> str:
        """One statement in its own session, run inside the database container; returns the printed output."""
        return docker("exec", "-e", f"PGPASSWORD={self.password}", DB_CONTAINER, *self._psql_args(), "-c", sql).stdout.strip()

    def session(self, app: str | None = None) -> subprocess.Popen:
        """A psql session that reads its commands from stdin and stays open until stdin closes."""
        env_args = ["-e", f"PGPASSWORD={self.password}"]
        if app is not None:
            env_args += ["-e", f"PGAPPNAME={app}"]
        return subprocess.Popen(
            ["docker", "exec", "-i", *env_args, DB_CONTAINER, *self._psql_args()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


class Ssm:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_parameter(self, name: str) -> str:
        return self.value


def make_holder(db: Db) -> adapters.RealLockHolder:
    return adapters.RealLockHolder(SubprocessRunner(), adapters.ProcessLauncher(SubprocessRunner()), Ssm(db.url), "/bf-it/db-url", PSQL_IMAGE)


@pytest.fixture(scope="module")
def db():
    gateway = docker("network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}").stdout.strip()
    port = free_port(gateway)
    local = free_port()
    password = os.urandom(12).hex()
    docker(
        "run",
        "-d",
        "--name",
        DB_CONTAINER,
        "-e",
        f"POSTGRES_DB={DB_NAME}",
        "-e",
        f"POSTGRES_USER={DB_USER}",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-p",
        f"127.0.0.1:{local}:5432",
        "-p",
        f"{gateway}:{port}:5432",
        PSQL_IMAGE,
    )
    database = Db(gateway, port, password)
    try:
        assert wait_for(lambda: _ready(database), 120), "the throwaway database did not accept connections"
        yield database
    finally:
        docker("rm", "-f", DB_CONTAINER, check=False)
        for name in lock_containers():
            docker("rm", "-f", name, check=False)


def _ready(database: Db) -> bool:
    return (
        docker(
            "exec",
            "-e",
            f"PGPASSWORD={database.password}",
            DB_CONTAINER,
            "psql",
            "-X",
            "-At",
            "-h",
            "127.0.0.1",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-c",
            "SELECT 1",
            check=False,
        ).returncode
        == 0
    )


@pytest.fixture
def holder(db):
    lock = make_holder(db)
    yield lock
    try:
        lock.release()
    except EffectFailed:
        pass
    assert lock_containers() == [], "a lock container was left behind"


def session_count(db: Db, app: str) -> int:
    return int(db.run(f"SELECT count(*) FROM pg_stat_activity WHERE application_name = '{app}'"))


def test_the_server_is_postgresql_17_and_libpq_accepts_the_lock_url_with_its_keepalive_options(db, holder):
    url = holder._database_url()  # the exact URL the lock session is started with
    env = dict(os.environ, DATABASE_URL=url)
    out = docker(
        "run",
        "--rm",
        "--pull=never",
        "-e",
        "DATABASE_URL",
        "--entrypoint",
        "/bin/sh",
        PSQL_IMAGE,
        "-c",
        "psql -X -At \"$DATABASE_URL\" -c \"SELECT current_setting('application_name') || '|' || current_setting('server_version')\"",
        env=env,
    ).stdout.strip()
    app, version = out.split("|")
    assert app == "bookfinder-deploy-lock"
    assert version.startswith("17."), version
    assert db.run("SHOW server_version_num") in {str(n) for n in range(170000, 180000)}


def test_exclusive_lock_blocks_other_sessions_until_release(db, holder):
    holder.acquire(KEY, 10.0)
    holder.heartbeat(10.0)
    assert holder.alive() is True
    assert db.run(f"SELECT pg_try_advisory_lock_shared({KEY})") == "f"
    assert db.run(f"SELECT pg_try_advisory_lock({KEY})") == "f"
    holder.release()
    assert holder.alive() is False
    assert db.run(f"SELECT pg_try_advisory_lock({KEY})") == "t"
    assert lock_containers() == []


def test_a_shared_session_makes_acquire_fail_within_the_server_lock_timeout(db, holder):
    crawler = db.session()
    crawler.stdin.write(f"SELECT pg_advisory_lock_shared({KEY});\nSELECT pg_sleep(600);\n")
    crawler.stdin.flush()
    try:
        assert wait_for(
            lambda: db.run("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted AND mode = 'ShareLock'") == "1",
            30,
        ), "the shared holder did not take the lock"
        started = time.monotonic()
        with pytest.raises(EffectFailed, match="migration lock not acquired") as info:
            holder.acquire(KEY, 3.0)
        elapsed = time.monotonic() - started
        assert elapsed < 30, f"acquire took {elapsed:.1f} s for a 3 s server timeout"
        assert "lock timeout" in str(info.value), str(info.value)
        assert holder.alive() is False
        assert session_count(db, "bookfinder-deploy-lock") == 0
        assert lock_containers() == []
    finally:
        db.run("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE '%pg_sleep(600)%' AND pid <> pg_backend_pid()")
        crawler.stdin.close()
        try:
            crawler.wait(timeout=10)
        except subprocess.TimeoutExpired:
            crawler.kill()
    # once the shared holder is gone, the exclusive lock is obtainable
    holder.acquire(KEY, 10.0)
    holder.heartbeat(10.0)


def test_a_terminated_lock_session_is_seen_dead_by_heartbeat_and_the_server_frees_the_lock(db, holder):
    holder.acquire(KEY, 10.0)
    holder.heartbeat(10.0)
    db.run("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'bookfinder-deploy-lock'")
    # psql notices a server-side close only when it sends its next command, so alive() can still be True here: the
    # heartbeat is the proof, and psql exits once that command has failed (ON_ERROR_STOP=1).
    with pytest.raises(EffectFailed):
        holder.heartbeat(5.0)
    assert wait_for(lambda: not holder.alive(), 30), "psql did not exit after the failed heartbeat"
    assert db.run(f"SELECT pg_try_advisory_lock({KEY})") == "t"
    holder.release()  # a dead session is still cleared without error


def test_a_killed_lock_holder_container_is_seen_dead_and_the_server_frees_the_lock(db, holder):
    holder.acquire(KEY, 10.0)
    holder.heartbeat(10.0)
    name = holder._name
    docker("kill", name)
    assert wait_for(lambda: not holder.alive(), 30), "the host still sees the killed lock holder alive"
    with pytest.raises(EffectFailed):
        holder.heartbeat(5.0)
    assert db.run(f"SELECT pg_try_advisory_lock({KEY})") == "t"


def test_the_connection_wait_sees_an_efbundle_named_session_and_returns_once_it_ends(db, holder):
    holder.acquire(KEY, 10.0)
    efbundle_like = db.session(app=EFBUNDLE_APP)
    efbundle_like.stdin.write("SELECT pg_sleep(600);\n")
    efbundle_like.stdin.flush()
    try:
        assert wait_for(lambda: session_count(db, EFBUNDLE_APP) == 1, 30)
        started = time.monotonic()
        with pytest.raises(MigrationConnectionActive):
            holder.wait_migration_connections_gone(EFBUNDLE_APP, 3.0)
        assert time.monotonic() - started < 30
        assert holder.alive() is True  # the check does not end the lock session
    finally:
        db.run(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = '{EFBUNDLE_APP}'")
        efbundle_like.stdin.close()
        try:
            efbundle_like.wait(timeout=10)
        except subprocess.TimeoutExpired:
            efbundle_like.kill()
    holder.wait_migration_connections_gone(EFBUNDLE_APP, 30.0)
    holder.heartbeat(10.0)


def efbundle_env(db: Db, connection_suffix: str) -> dict:
    connection = f"Host={db.gateway};Port={db.port};Database={DB_NAME};Username={DB_USER};Password={db.password};{connection_suffix}"
    return dict(os.environ, ConnectionStrings__DefaultConnection=connection)


def test_npgsql_accepts_the_application_name_and_options_in_the_efbundle_connection_string(db):
    # Logging each connection with its application name lets the test see what efbundle sent.
    db.run("ALTER SYSTEM SET log_connections = on")
    db.run("SELECT pg_reload_conf()")
    # Negative control: a bogus Options value must make the server refuse the connection, so Npgsql is shown to pass
    # Options on. Without this, a silently ignored Options key would look the same as an accepted one.
    bogus = docker(
        "run",
        "--rm",
        "--pull=never",
        "-e",
        "ConnectionStrings__DefaultConnection",
        "--entrypoint",
        "/app/efbundle",
        WEB_IMAGE,
        check=False,
        timeout=600,
        env=efbundle_env(db, f"Application Name={EFBUNDLE_APP};Options=-c client_connection_check_interval=bogus"),
    )
    assert bogus.returncode != 0
    assert "client_connection_check_interval" in (bogus.stdout + bogus.stderr)
    # The host's real string: Application Name, then Options with the check interval.
    run = docker(
        "run",
        "--rm",
        "--pull=never",
        "-e",
        "ConnectionStrings__DefaultConnection",
        "--entrypoint",
        "/app/efbundle",
        WEB_IMAGE,
        check=False,
        timeout=900,
        env=efbundle_env(db, f"Application Name={EFBUNDLE_APP};Options=-c client_connection_check_interval=10000"),
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    logs = docker("logs", DB_CONTAINER).stdout + docker("logs", DB_CONTAINER).stderr
    assert f"application_name={EFBUNDLE_APP}" in logs
    assert int(db.run('SELECT count(*) FROM "__EFMigrationsHistory"')) > 0


def _real_lock_world(tmp_path, db: Db):
    """The unit-test world with the real lock holder's methods on the fake's instance (the effects are bound once)."""
    world = tm.forward_world(tmp_path)
    real = make_holder(db)
    fake = world.fx.lock_holder
    for name in ("acquire", "heartbeat", "alive", "wait_migration_connections_gone", "release"):
        setattr(fake, name, getattr(real, name))
    return world, real


def test_forward_migration_with_the_real_lock_holder_succeeds_and_leaves_no_lock_behind(tmp_path, db):
    world, _real = _real_lock_world(tmp_path, db)
    code, _out, err = world.run_unit(tm.deploy_text(world, chain="forward", tag=tm.TAG2))
    assert code == OK, err
    assert db.run(f"SELECT pg_try_advisory_lock({KEY})") == "t"
    assert lock_containers() == []


def test_efbundle_exit_after_the_real_lock_session_was_terminated_is_not_accepted(tmp_path, db):
    world, real = _real_lock_world(tmp_path, db)
    world.fx.docker.efbundle_polls = 1  # one periodic heartbeat succeeds, then efbundle exits
    world.fx.docker.efbundle_rc = 0
    world.fx.docker.efbundle_db_ids = [tm.ID1, tm.ID2]  # the database reports the full target

    def terminate_session_as_efbundle_exits() -> None:
        db.run("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'bookfinder-deploy-lock'")
        wait_for(lambda: not real.alive(), 30)

    world.fx.docker.efbundle_on_exit = terminate_session_as_efbundle_exits
    code, _out, err = world.run_unit(tm.deploy_text(world, chain="forward", tag=tm.TAG2))
    assert code == FAILED_MIGRATION, err
    assert "lock session lost before the result was accepted" in err
    state = world.load_state()
    assert state.schema.dirty is True and state.crawler.paused is not None
    assert not any(t.startswith("compose.") for t in world.fx.trace)
    assert db.run(f"SELECT pg_try_advisory_lock({KEY})") == "t"
    assert lock_containers() == []
