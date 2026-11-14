"""Derive the Eslite level-3 list from a saved category tree, and read/write ``eslite_level3.tsv``.

The tree walk is NOT reimplemented: ``select()`` and the default top id and excluded level-2 ids come from the crawler's
operator tool ``crawler/deploy/local/eslite_category_pages.py``, so the list here and the crawler's page list use one rule.
Nothing in this module touches the database or the network. The tree is data; it is never executed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from category_config import SUBJECT_MAX, ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
CRAWLER_LOCAL_DIR = REPO_ROOT / "crawler" / "deploy" / "local"
if str(CRAWLER_LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(CRAWLER_LOCAL_DIR))

from eslite_category_pages import DEFAULT_EXCLUDED_LEVEL2, DEFAULT_TOP_ID, Selection, select

HEADER = "level2_id\tlevel2_name\tlevel3_id\tlevel3_name"
DEFAULT_TSV = Path(__file__).resolve().parent / "config" / "eslite_level3.tsv"


@dataclass(frozen=True)
class Level3Row:
    level2_id: int
    level2_name: str
    level3_id: int
    level3_name: str


def collapse(text: str) -> str:
    """Single-spaced, tab- and newline-free form of a display name."""
    return " ".join(text.split())


def build_level3_rows(tree: list) -> tuple[list[Level3Row], Selection]:
    """Level-3 rows under the default top category, in tree order, plus the crawler's selection summary.

    Raises ValueError for a malformed tree, a missing top category, or a name that is empty after whitespace collapse.
    """
    selection = select(tree, top_id=DEFAULT_TOP_ID, exclude_level2=DEFAULT_EXCLUDED_LEVEL2)
    rows: list[Level3Row] = []
    for category in selection.categories:
        _level1, level2_name, level3_name = category.names
        row = Level3Row(
            level2_id=category.level2_id,
            level2_name=collapse(level2_name),
            level3_id=category.id,
            level3_name=collapse(level3_name),
        )
        if not row.level2_name or not row.level3_name:
            raise ValueError(f"category {category.id} has an empty name after whitespace is collapsed")
        rows.append(row)
    return rows, selection


def write_level3_tsv(path: Path, rows: list[Level3Row]) -> None:
    """Write the TSV atomically: a temporary file in the same directory, then ``os.replace``."""
    lines = [HEADER]
    lines.extend(f"{r.level2_id}\t{r.level2_name}\t{r.level3_id}\t{r.level3_name}" for r in rows)
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def read_level3_tsv(path: Path) -> list[Level3Row]:
    """Read and validate the TSV. Any malformed content raises ConfigError."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name}: cannot read eslite level-3 TSV ({exc})") from exc
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0].rstrip("\r") != HEADER:
        raise ConfigError(f"{path.name}: missing or wrong header (expected {HEADER!r})")
    rows: list[Level3Row] = []
    for number, raw in enumerate(lines[1:], start=2):
        line = raw.rstrip("\r")
        if line == "":
            continue
        where = f"{path.name} line {number}"
        fields = line.split("\t")
        if len(fields) != 4:
            raise ConfigError(f"{where}: expected 4 columns, found {len(fields)}")
        level2_id = _positive_int(fields[0], "level2_id", where)
        level2_name = _name(fields[1], "level2_name", where)
        level3_id = _positive_int(fields[2], "level3_id", where)
        level3_name = _name(fields[3], "level3_name", where)
        rows.append(Level3Row(level2_id, level2_name, level3_id, level3_name))
    return rows


def _positive_int(text: str, column: str, where: str) -> int:
    if not text.isascii() or not text.isdigit() or text.startswith("0"):
        raise ConfigError(f"{where}: {column} must be a positive integer, found {text!r}")
    return int(text)


def _name(text: str, column: str, where: str) -> str:
    if text.strip() == "":
        raise ConfigError(f"{where}: {column} is empty")
    if len(text) > SUBJECT_MAX:
        raise ConfigError(f"{where}: {column} is longer than {SUBJECT_MAX} characters")
    return text
