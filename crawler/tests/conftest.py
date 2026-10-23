"""Shared fixtures: a throwaway pgvector PostgreSQL with the EF Core schema.

- The container is managed by Testcontainers (``testcontainers[postgres]``, image
  ``pgvector/pgvector:pg17``). It is removed when the session ends, and also when startup fails,
  because the context manager calls ``stop()`` on a failed ``start()``. Ryuk removes anything left
  behind if pytest is killed. Tests never use DATABASE_URL or any real/dev database.
- The EF schema is generated BEFORE the container starts, so a dotnet/EF failure never leaves a
  container running. Generation: ``dotnet build`` + ``dotnet ef migrations script --idempotent``
  from the repository root. The crawler itself never runs DDL; this DDL is applied by test setup.
- Each DB test starts from empty crawler tables (TRUNCATE).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_IMAGE = "pgvector/pgvector:pg17"
PG_USER = "crawler_test"
PG_PASSWORD = "crawler_test"
PG_DATABASE = "crawler_test"
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
def ef_schema_sql(tmp_path_factory) -> str:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("dotnet SDK not available; cannot generate the EF Core schema")
    restore = subprocess.run([dotnet, "tool", "restore"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if restore.returncode != 0:
        pytest.fail(f"dotnet tool restore failed: {restore.stderr or restore.stdout}")
    build = subprocess.run([dotnet, "build", "Book-Finder.csproj"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if build.returncode != 0:
        pytest.fail(f"dotnet build failed: {build.stdout[-2000:]}")
    script = tmp_path_factory.mktemp("ef-schema") / "schema.sql"
    generated = subprocess.run(
        [dotnet, "ef", "migrations", "script", "--idempotent", "--no-build", "-o", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if generated.returncode != 0:
        pytest.fail(f"dotnet ef migrations script failed: {generated.stderr or generated.stdout}")
    return script.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="session")
def postgres_url(ef_schema_sql: str) -> Iterator[str]:
    container = PostgresContainer(PG_IMAGE, username=PG_USER, password=PG_PASSWORD, dbname=PG_DATABASE, driver=None)
    with container:
        url = container.get_connection_url(driver=None)
        _wait_for_postgres(url)
        yield url


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
