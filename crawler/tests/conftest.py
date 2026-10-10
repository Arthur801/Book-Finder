"""Shared fixtures: a throwaway pgvector PostgreSQL with the EF Core schema.

- The container is started with the Docker CLI (``pgvector/pgvector:pg17``) once per session
  and removed afterwards. Tests never use DATABASE_URL or any real/dev database.
- The schema is produced by EF Core: ``dotnet build`` + ``dotnet ef migrations script --idempotent``
  from the repository root. The crawler itself never runs DDL; this DDL is applied by the test setup.
- Each DB test starts from empty crawler tables (TRUNCATE).
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_IMAGE = "pgvector/pgvector:pg17"
CRAWLER_TABLES = "bestsellers, book_subjects, book_contributors, book_identifiers, book_sources, books"


def _wait_for_postgres(url: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"throwaway PostgreSQL did not become ready: {last_error}")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI not available; integration tests need a throwaway PostgreSQL")
    name = f"bf6-crawler-test-{uuid.uuid4().hex[:8]}"
    started = subprocess.run(
        [
            docker, "run", "-d", "--name", name,
            "-e", "POSTGRES_USER=crawler_test",
            "-e", "POSTGRES_PASSWORD=crawler_test",
            "-e", "POSTGRES_DB=crawler_test",
            "-p", "127.0.0.1::5432",
            PG_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        pytest.fail(f"docker run failed: {started.stderr.strip()}")
    try:
        port_lines = subprocess.run(
            [docker, "port", name, "5432/tcp"], capture_output=True, text=True, check=True
        ).stdout.strip().splitlines()
        port = port_lines[0].rsplit(":", 1)[-1]
        url = f"postgresql://crawler_test:crawler_test@127.0.0.1:{port}/crawler_test"
        _wait_for_postgres(url)
        yield url
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="session")
def ef_schema_sql(tmp_path_factory) -> str:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("dotnet SDK not available; cannot generate the EF Core schema")
    restore = subprocess.run([dotnet, "tool", "restore"], cwd=REPO_ROOT, capture_output=True, text=True)
    if restore.returncode != 0:
        pytest.fail(f"dotnet tool restore failed: {restore.stderr or restore.stdout}")
    build = subprocess.run([dotnet, "build", "Book-Finder.csproj"], cwd=REPO_ROOT, capture_output=True, text=True)
    if build.returncode != 0:
        pytest.fail(f"dotnet build failed: {build.stdout[-2000:]}")
    script = tmp_path_factory.mktemp("ef-schema") / "schema.sql"
    generated = subprocess.run(
        [dotnet, "ef", "migrations", "script", "--idempotent", "--no-build", "-o", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if generated.returncode != 0:
        pytest.fail(f"dotnet ef migrations script failed: {generated.stderr or generated.stdout}")
    return script.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="session")
def database(postgres_url: str, ef_schema_sql: str) -> str:
    with psycopg.connect(postgres_url, autocommit=True) as conn:
        conn.execute(ef_schema_sql)
    return postgres_url


@pytest.fixture
def db_url(database: str) -> str:
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {CRAWLER_TABLES} CASCADE")
    return database
