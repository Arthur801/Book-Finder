import subprocess
import sys
from pathlib import Path

import check_migrations

SCRIPT = Path(__file__).resolve().parents[1] / "check_migrations.py"
BUILD_MANIFEST = Path(__file__).resolve().parents[3] / "deploy" / "release" / "build-manifest.sh"
REAL_MIGRATIONS = Path(__file__).resolve().parents[3] / check_migrations.MIGRATIONS_DIR

FIRST = "20260101000000_First"
SECOND = "20260102000000_Second"
EARLIER = "20251231000000_Earlier"


def write_migration(migrations_dir: Path, migration_id: str, body: str = "class M {}", designer: str = "partial class D {}"):
    migrations_dir.mkdir(parents=True, exist_ok=True)
    (migrations_dir / f"{migration_id}.cs").write_text(body, encoding="utf-8", newline="\n")
    (migrations_dir / f"{migration_id}.Designer.cs").write_text(designer, encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path, *migration_ids: str) -> Path:
    root = tmp_path / "repo"
    migrations_dir = root / check_migrations.MIGRATIONS_DIR
    for migration_id in migration_ids:
        write_migration(migrations_dir, migration_id)
    return root


def run_check(root: Path, released: Path | None = None) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), str(root)]
    if released is not None:
        args += ["--released-manifest", str(released)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def write_released(tmp_path: Path, root: Path) -> Path:
    released = tmp_path / "released-migrations.txt"
    released.write_text("\n".join(check_migrations.manifest_lines(root / check_migrations.MIGRATIONS_DIR)) + "\n", encoding="utf-8")
    return released


def test_build_manifest_script_matches_python_on_real_migrations(tmp_path):
    out_dir = tmp_path / "release"
    result = subprocess.run(
        ["bash", str(BUILD_MANIFEST), str(REAL_MIGRATIONS), str(out_dir)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    expected = "\n".join(check_migrations.manifest_lines(REAL_MIGRATIONS)) + "\n"
    assert (out_dir / "migrations.txt").read_text(encoding="utf-8") == expected
    assert (out_dir / "RELEASE_API").read_text(encoding="utf-8") == "1\n"


def test_passes_when_released_manifest_matches(tmp_path):
    root = make_repo(tmp_path, FIRST, SECOND)

    result = run_check(root, write_released(tmp_path, root))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error::" not in result.stdout


def test_notice_when_no_released_manifest(tmp_path):
    root = make_repo(tmp_path, FIRST)

    result = run_check(root)

    assert result.returncode == 0
    assert "::notice::no released manifest; skipping immutability check" in result.stdout


def test_modified_released_migration_is_rejected(tmp_path):
    root = make_repo(tmp_path, FIRST, SECOND)
    released = write_released(tmp_path, root)
    write_migration(root / check_migrations.MIGRATIONS_DIR, FIRST, body="class M { int changed; }")

    result = run_check(root, released)

    assert result.returncode == 1
    assert f"released migration {FIRST} was modified; published migrations are immutable" in result.stdout


def test_designer_change_also_counts_as_modified(tmp_path):
    root = make_repo(tmp_path, FIRST)
    released = write_released(tmp_path, root)
    write_migration(root / check_migrations.MIGRATIONS_DIR, FIRST, designer="partial class D { int x; }")

    result = run_check(root, released)

    assert result.returncode == 1
    assert f"released migration {FIRST} was modified" in result.stdout


def test_migration_inserted_before_released_one_is_rejected(tmp_path):
    root = make_repo(tmp_path, FIRST)
    released = write_released(tmp_path, root)
    write_migration(root / check_migrations.MIGRATIONS_DIR, EARLIER)

    result = run_check(root, released)

    assert result.returncode == 1
    assert f"new migration {EARLIER} sorts before released migration {FIRST}" in result.stdout


def test_released_migration_missing_from_current_is_rejected(tmp_path):
    root = make_repo(tmp_path, FIRST, SECOND)
    released = write_released(tmp_path, root)
    (root / check_migrations.MIGRATIONS_DIR / f"{SECOND}.cs").unlink()
    (root / check_migrations.MIGRATIONS_DIR / f"{SECOND}.Designer.cs").unlink()

    result = run_check(root, released)

    assert result.returncode == 1
    assert f"released migration {SECOND} is missing from the current migrations" in result.stdout


def test_suppress_transaction_is_rejected(tmp_path):
    root = make_repo(tmp_path)
    write_migration(root / check_migrations.MIGRATIONS_DIR, FIRST, body='[Migration("x", suppressTransaction: true)]')

    result = run_check(root)

    assert result.returncode == 1
    assert f"{FIRST}.cs uses suppressTransaction" in result.stdout
    assert "its own transaction" in result.stdout


def test_concurrently_is_rejected_case_insensitively(tmp_path):
    root = make_repo(tmp_path)
    write_migration(root / check_migrations.MIGRATIONS_DIR, FIRST, body='migrationBuilder.Sql("create index concurrently x on y(z)");')

    result = run_check(root)

    assert result.returncode == 1
    assert f"{FIRST}.cs uses concurrently" in result.stdout


def test_crlf_and_lf_files_have_the_same_hash(tmp_path):
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    for root, newline in ((lf_root, "\n"), (crlf_root, "\r\n")):
        migrations_dir = root / check_migrations.MIGRATIONS_DIR
        migrations_dir.mkdir(parents=True)
        (migrations_dir / f"{FIRST}.cs").write_bytes(f"class M {{{newline}}}{newline}".encode())
        (migrations_dir / f"{FIRST}.Designer.cs").write_bytes(f"partial class D {{{newline}}}{newline}".encode())

    lf_lines = check_migrations.manifest_lines(lf_root / check_migrations.MIGRATIONS_DIR)
    crlf_lines = check_migrations.manifest_lines(crlf_root / check_migrations.MIGRATIONS_DIR)

    assert lf_lines == crlf_lines


def test_missing_designer_file_is_rejected(tmp_path):
    root = make_repo(tmp_path, FIRST)
    (root / check_migrations.MIGRATIONS_DIR / f"{FIRST}.Designer.cs").unlink()

    result = run_check(root)

    assert result.returncode == 1
    assert f"missing {FIRST}.Designer.cs for migration {FIRST}" in result.stdout


def test_missing_migration_file_for_designer_is_rejected(tmp_path):
    root = make_repo(tmp_path, FIRST)
    (root / check_migrations.MIGRATIONS_DIR / f"{FIRST}.cs").unlink()

    result = run_check(root)

    assert result.returncode == 1
    assert f"missing {FIRST}.cs for designer file {FIRST}.Designer.cs" in result.stdout
