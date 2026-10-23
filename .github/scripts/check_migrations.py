"""Check EF Core migrations for rules that keep a failed deploy safe to retry.

Why: each migration must run in its own transaction, so a failed deploy stops on a migration boundary; suppressTransaction
and CONCURRENTLY break that. Published migrations are also immutable: a released database has already applied them, so
editing one or inserting a new one before it leaves environments that disagree with the code. The manifest format and
hash must match deploy/release/build-manifest.sh, which the Docker build uses to produce migrations.txt for each release.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

MIGRATIONS_DIR = "Infrastructure/Persistence/Migrations"
SNAPSHOT_FILE = "AppDbContextModelSnapshot.cs"
DESIGNER_SUFFIX = ".Designer.cs"
FORBIDDEN_IN_MIGRATION = re.compile(r"suppressTransaction|concurrently", re.IGNORECASE)
MANIFEST_LINE = re.compile(r"^(\S+) ([0-9a-f]{64})$")


class ManifestError(Exception):
    pass


def _migration_ids(migrations_dir: Path) -> tuple[list[str], list[str]]:
    """Return (migration ids, designer ids), each sorted ascending."""
    ids = sorted(path.name[: -len(".cs")] for path in migrations_dir.glob("*.cs") if not path.name.endswith(DESIGNER_SUFFIX) and path.name != SNAPSHOT_FILE)
    designer_ids = sorted(path.name[: -len(DESIGNER_SUFFIX)] for path in migrations_dir.glob(f"*{DESIGNER_SUFFIX}"))
    return ids, designer_ids


def source_hash(migration_id: str, migration_text: bytes, designer_text: bytes) -> str:
    # Same bytes as build-manifest.sh: CRs stripped, NUL between the two files.
    payload = migration_id.encode("utf-8") + b"\n" + migration_text.replace(b"\r", b"") + b"\0" + designer_text.replace(b"\r", b"")
    return hashlib.sha256(payload).hexdigest()


def pairing_errors(migrations_dir: Path) -> list[str]:
    ids, designer_ids = _migration_ids(migrations_dir)
    errors = [f"missing {mid}{DESIGNER_SUFFIX} for migration {mid}" for mid in ids if mid not in designer_ids]
    errors += [f"missing {mid}.cs for designer file {mid}{DESIGNER_SUFFIX}" for mid in designer_ids if mid not in ids]
    return errors


def manifest_lines(migrations_dir: Path) -> list[str]:
    problems = pairing_errors(migrations_dir)
    if problems:
        raise ManifestError("; ".join(problems))

    ids, _ = _migration_ids(migrations_dir)
    lines = []
    for mid in ids:
        migration_text = (migrations_dir / f"{mid}.cs").read_bytes()
        designer_text = (migrations_dir / f"{mid}{DESIGNER_SUFFIX}").read_bytes()
        lines.append(f"{mid} {source_hash(mid, migration_text, designer_text)}")
    return lines


def check_no_forbidden_transaction_settings(migrations_dir: Path) -> list[str]:
    errors = []
    for path in sorted(migrations_dir.glob("*.cs")):
        if path.name.endswith(DESIGNER_SUFFIX) or path.name == SNAPSHOT_FILE:
            continue
        match = FORBIDDEN_IN_MIGRATION.search(path.read_text(encoding="utf-8"))
        if match:
            errors.append(
                f"{path.name} uses {match.group(0)}; each migration must run in its own transaction so a failed deploy "
                "stops on a migration boundary, so remove it (run such statements in a separate, non-migration step)"
            )
    return errors


def check_released_manifest(current: list[str], released_text: str) -> list[str]:
    released = []
    for number, line in enumerate(released_text.splitlines(), start=1):
        match = MANIFEST_LINE.match(line)
        if not match:
            return [f"released manifest line {number} is malformed: {line!r}"]
        released.append((match.group(1), match.group(2)))

    current_pairs = [tuple(line.split(" ", 1)) for line in current]
    released_ids = {mid for mid, _ in released}

    errors = []
    for index, (released_id, released_hash) in enumerate(released):
        if index >= len(current_pairs):
            errors.append(f"released migration {released_id} is missing from the current migrations; published migrations are immutable — restore it")
            break
        current_id, current_hash = current_pairs[index]
        if current_id != released_id:
            if current_id in released_ids:
                errors.append(f"released migration {released_id} was reordered; published migrations are immutable")
            else:
                errors.append(f"new migration {current_id} sorts before released migration {released_id}; give the new migration a later timestamp")
            break
        if current_hash != released_hash:
            errors.append(f"released migration {released_id} was modified; published migrations are immutable — add a new migration instead")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", default=None, help="repository root (defaults to this script's repository)")
    parser.add_argument("--released-manifest", type=Path, help="migrations.txt from the latest published release")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    migrations_dir = root / MIGRATIONS_DIR

    errors = pairing_errors(migrations_dir) + check_no_forbidden_transaction_settings(migrations_dir)
    checks_run = 2

    if args.released_manifest is None:
        print("::notice::no released manifest; skipping immutability check")
    else:
        checks_run += 1
        try:
            current = manifest_lines(migrations_dir)
            released_text = args.released_manifest.read_text(encoding="utf-8")
        except (ManifestError, OSError) as error:
            errors.append(f"cannot compute migration manifest: {error}")
        else:
            errors += check_released_manifest(current, released_text)

    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1
    print(f"migrations OK ({checks_run} check(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
