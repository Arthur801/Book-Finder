"""Fixtures for the database tests: a throwaway pgvector PostgreSQL with the EF Core schema.

Same approach as crawler/tests/conftest.py. The container is managed by Testcontainers and removed when the session ends.
The EF schema is generated BEFORE the container starts (``dotnet build`` + ``dotnet ef migrations script --idempotent``),
so a dotnet failure never leaves a container running. Tests never use DATABASE_URL or any real database: every
integration test gets its own fresh database, created from the same schema script and dropped afterwards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
PG_IMAGE = "pgvector/pgvector:0.8.7-pg17"
PG_USER = "categories_test"
PG_PASSWORD = "categories_test"
PG_DATABASE = "categories_test"


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
    # The script only reads the model and never connects, so a placeholder satisfies Program.cs on CI.
    env = {**os.environ, "ConnectionStrings__DefaultConnection": "Host=placeholder;Database=placeholder"}
    generated = subprocess.run(
        [dotnet, "ef", "migrations", "script", "--idempotent", "--no-build", "-o", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if generated.returncode != 0:
        pytest.fail(f"dotnet ef migrations script failed: {generated.stderr or generated.stdout}")
    return script.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="session")
def postgres_url(ef_schema_sql: str) -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip("docker not available; cannot start the throwaway PostgreSQL")
    container = PostgresContainer(PG_IMAGE, username=PG_USER, password=PG_PASSWORD, dbname=PG_DATABASE, driver=None)
    with container:
        url = container.get_connection_url(driver=None)
        _wait_for_postgres(url)
        yield url


@pytest.fixture
def fresh_db(postgres_url: str, ef_schema_sql: str) -> Iterator[str]:
    """A new database with the EF schema and no categories or books; dropped after the test."""
    name = f"cat_{uuid.uuid4().hex[:16]}"
    admin = psycopg.connect(postgres_url, autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{name}"')
        url = urlsplit(postgres_url)._replace(path=f"/{name}").geturl()
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(ef_schema_sql)
        yield url
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()
