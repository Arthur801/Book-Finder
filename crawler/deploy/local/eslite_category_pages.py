"""Build the Eslite category page list (``crawler/eslite-pages.txt``) from Eslite's category tree.

Operator tool, not part of the crawler package: the crawler's fetch policy cannot read the tree. It makes ONE request
to the category tree API (or reads a saved copy with ``--from-file``), selects every level-3 category under the
top-level category (default id 3, 中文書), and writes the page-1 list URLs the crawler reads.

Run from ``crawler/`` as ``../.venv/bin/python deploy/local/eslite_category_pages.py [options]`` (any cwd works).
Exit codes: 0 ok (including --dry-run), 1 fetch, parse or internal-check failure, 2 usage or validation failure.
Nothing is written on any failure.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CRAWLER_DIR = Path(__file__).resolve().parents[2]
if str(CRAWLER_DIR) not in sys.path:
    sys.path.insert(0, str(CRAWLER_DIR))

from curl_cffi import requests as curl_requests

from eslite.page_list import DEFAULT_PAGES_FILE, MAX_PAGES, PageListError, load_page_urls
from eslite.urls import API_HOST, SITE_HOST, canonical_list_url

TREE_URL = f"https://{API_HOST}/api/v1/categories"
DEFAULT_TOP_ID = 3
DEFAULT_OUTPUT = DEFAULT_PAGES_FILE
RULE_SUMMARY = "level-3 categories under 中文書, page 1 only, external links and brand pages skipped"
FETCH_TIMEOUT = 30
MAX_TREE_BYTES = 5 * 1024 * 1024
FETCH_HEADERS = {"Accept": "application/json", "Accept-Language": "zh-TW,zh;q=0.9"}
PREVIEW_COUNT = 5


class ToolError(Exception):
    """A failure with a message that is safe to print. ``exit_code`` is the process exit status."""

    exit_code = 1


class RunError(ToolError):
    """Fetch, parse or internal-check failure (exit 1). Nothing is written."""

    exit_code = 1


class UsageError(ToolError):
    """Usage or validation failure (exit 2). Nothing is written."""

    exit_code = 2


@dataclass(frozen=True)
class Category:
    id: int
    level2_id: int
    names: tuple[str, str, str]  # level-1, level-2, level-3 descriptions

    @property
    def url(self) -> str:
        return f"https://{SITE_HOST}/category/3/{self.id}"


@dataclass(frozen=True)
class Selection:
    categories: list[Category]
    seen: int
    skipped_link: int
    skipped_brand: int
    skipped_excluded: int
    duplicates: int
    per_level2: tuple[tuple[int, str, int], ...]  # (id, name, kept), every level-2 under the top, in tree order


def _check_node(node: Any) -> None:
    if not isinstance(node, dict):
        raise TypeError("malformed category tree: a node is not an object")
    for key in ("id", "depth"):
        if not isinstance(node.get(key), int) or isinstance(node.get(key), bool):
            raise TypeError(f"malformed category tree: node {key} is not an integer")
    if not isinstance(node.get("description"), str):
        raise TypeError("malformed category tree: node description is not a string")
    children = node.get("children", [])
    if children is not None and not isinstance(children, list):
        raise TypeError("malformed category tree: node children is not a list")


def _children(node: dict[str, Any]) -> list[Any]:
    return node.get("children") or []


def _nodes_under(top: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Every descendant of ``top`` in tree (pre-)order, each with its depth-2 ancestor (None above depth 2)."""
    stack: list[tuple[Any, dict[str, Any] | None]] = [(child, None) for child in reversed(_children(top))]
    while stack:
        node, level2 = stack.pop()
        _check_node(node)
        if node["depth"] == 2:
            level2 = node
        yield node, level2
        stack.extend((child, level2) for child in reversed(_children(node)))


def _has_external_link(node: dict[str, Any]) -> bool:
    link = node.get("link")
    return isinstance(link, str) and link.strip() != ""


def select(tree: Sequence[Any], *, top_id: int = DEFAULT_TOP_ID, exclude_level2: Sequence[int] = ()) -> Selection:
    """Level-3 categories under the depth-1 node ``top_id``, in tree order, with the summary counts.

    A node is skipped (counted once, in this order) when its ``link`` is a non-empty string, when ``is_brand`` is
    true, or when its level-2 ancestor id is in ``exclude_level2``. Among the rest, the first occurrence of an id is
    kept and later ones are counted as duplicates. Raises ValueError for a malformed tree or a missing top id.
    """
    top = None
    for item in tree:
        _check_node(item)
        if item["depth"] == 1 and item["id"] == top_id:
            top = item
            break
    if top is None:
        raise ValueError(f"no depth-1 category with id {top_id} in the category tree")

    excluded = frozenset(exclude_level2)
    per_level2: dict[int, list[Any]] = {}
    categories: list[Category] = []
    kept_ids: set[int] = set()
    seen = skipped_link = skipped_brand = skipped_excluded = duplicates = 0
    for node, level2 in _nodes_under(top):
        if node["depth"] == 2:
            per_level2.setdefault(node["id"], [node["description"], 0])
        if node["depth"] != 3:
            continue
        seen += 1
        if level2 is None:
            raise ValueError("malformed category tree: a level-3 category has no level-2 parent")
        if _has_external_link(node):
            skipped_link += 1
        elif node.get("is_brand") is True:
            skipped_brand += 1
        elif level2["id"] in excluded:
            skipped_excluded += 1
        elif node["id"] in kept_ids:
            duplicates += 1
        else:
            kept_ids.add(node["id"])
            names = (top["description"], level2["description"], node["description"])
            categories.append(Category(id=node["id"], level2_id=level2["id"], names=names))
            per_level2[level2["id"]][1] += 1
    return Selection(
        categories=categories,
        seen=seen,
        skipped_link=skipped_link,
        skipped_brand=skipped_brand,
        skipped_excluded=skipped_excluded,
        duplicates=duplicates,
        per_level2=tuple((level2_id, name, count) for level2_id, (name, count) in per_level2.items()),
    )


def select_categories(tree: Sequence[Any], *, top_id: int = DEFAULT_TOP_ID, exclude_level2: Sequence[int] = ()) -> list[Category]:
    return select(tree, top_id=top_id, exclude_level2=exclude_level2).categories


def _comment_text(text: str) -> str:
    """Text that fits on one comment line: a line break in a name or source would end the comment."""
    return " ".join(text.splitlines()).strip()


def render(categories: Sequence[Category], *, generated_at: str, source: str, top_id: int = DEFAULT_TOP_ID) -> str:
    """The page list file text: a comment header, then a name comment and the URL for each category."""
    lines = [
        "# Eslite category list pages (eslite mode). Generated by deploy/local/eslite_category_pages.py; do not edit by hand.",
        f"# Generated (UTC): {_comment_text(generated_at)}",
        f"# Source: {_comment_text(source)}",
        f"# Top category id: {top_id}",
        f"# Rule: {RULE_SUMMARY}.",
        "# Regenerate from crawler/: ../.venv/bin/python deploy/local/eslite_category_pages.py (add --force to replace an existing list).",
        f"# List order is run order. At most {MAX_PAGES} URLs.",
        "",
    ]
    for category in categories:
        url = category.url
        if canonical_list_url(url) != url:
            raise ValueError(f"category id {category.id} does not give a canonical Eslite list page URL")
        names = " › ".join(_comment_text(name) for name in category.names)
        lines.append(f"# {names}")
        lines.append(url)
    return "\n".join(lines) + "\n"


def fetch_tree(url: str = TREE_URL, *, timeout: float = FETCH_TIMEOUT, max_bytes: int = MAX_TREE_BYTES) -> list[Any]:
    """The category tree: exactly one request, no retries. Raises RunError for anything but a JSON list."""
    try:
        response = curl_requests.get(
            url,
            impersonate="chrome",
            allow_redirects=False,
            timeout=timeout,
            headers=FETCH_HEADERS,
        )
    except Exception as exc:  # noqa: BLE001 - any transport failure is exit 1; the request is not retried
        raise RunError(f"tree request failed ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise RunError(f"tree request returned HTTP {response.status_code}")
    content_type = str(response.headers.get("content-type", "")).split(";")[0].strip().lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        raise RunError(f"tree response is not JSON (content-type: {content_type or 'missing'})")
    body = response.content
    if len(body) > max_bytes:
        raise RunError(f"tree response is larger than {max_bytes} bytes")
    try:
        tree = json.loads(body)
    except ValueError:
        raise RunError("tree response is not valid JSON") from None
    if not isinstance(tree, list):
        raise RunError("tree JSON top level is not a list")
    return tree


def _load_tree(from_file: Path | None) -> tuple[str, list[Any]]:
    if from_file is None:
        return TREE_URL, fetch_tree()
    try:
        tree = json.loads(from_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RunError(f"cannot read tree file {from_file} ({type(exc).__name__})") from None
    if not isinstance(tree, list):
        raise RunError(f"tree file {from_file} does not hold a JSON list")
    return str(from_file), tree


def _check_output(path: Path, *, force: bool) -> None:
    """Refuse to replace a hand-made list: an existing file with any URL line needs --force."""
    if path.is_dir():
        raise UsageError(f"output {path} is a directory")
    if not path.parent.is_dir():
        raise UsageError(f"output directory {path.parent} does not exist")
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError, UnicodeDecodeError:
        if force:
            return
        raise UsageError(f"cannot read existing output {path}; pass --force to replace it") from None
    has_urls = any(line.strip() and not line.strip().startswith("#") for line in text.splitlines())
    if has_urls and not force:
        raise UsageError(f"{path} already holds URL lines; pass --force to replace it (nothing written)")


def _write_list(path: Path, text: str, expected: list[str]) -> None:
    """Write ``text`` atomically, but only after the crawler's own loader reads back exactly ``expected``."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        try:
            parsed = load_page_urls(tmp)
        except PageListError as exc:
            raise RunError(f"rendered list failed the crawler's check: {exc}") from None
        if parsed != expected:
            raise RunError("rendered list does not match the selected categories (nothing written)")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _format_summary(selection: Selection, *, source: str, top_id: int) -> str:
    lines = [
        f"source: {source}",
        f"top category id: {top_id}",
        f"depth-3 categories seen under it: {selection.seen}",
        f"  skipped (external link): {selection.skipped_link}",
        f"  skipped (brand page): {selection.skipped_brand}",
        f"  skipped (excluded level-2): {selection.skipped_excluded}",
        f"  duplicate ids dropped: {selection.duplicates}",
        f"kept: {len(selection.categories)}",
        "",
        "level-2 (id, kept, name):",
    ]
    for level2_id, name, count in selection.per_level2:
        lines.append(f"  {level2_id:>8}  {count:>4}  {name}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build crawler/eslite-pages.txt from the Eslite category tree (one request, page 1 only).",
    )
    parser.add_argument("--from-file", type=Path, help="read the category tree JSON from this file instead of fetching")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"output list file (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--top-id", type=int, default=DEFAULT_TOP_ID, help="top-level category id (default: 3)")
    parser.add_argument(
        "--exclude-level2",
        type=int,
        action="append",
        default=[],
        metavar="ID",
        help="skip the level-3 categories under this level-2 id (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the summary and the first URLs; write nothing")
    parser.add_argument("--force", action="store_true", help="replace an existing output file that already holds URL lines")
    return parser


def _run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        _check_output(args.output, force=args.force)
    source, tree = _load_tree(args.from_file)
    try:
        selection = select(tree, top_id=args.top_id, exclude_level2=args.exclude_level2)
    except (ValueError, TypeError) as exc:
        raise RunError(str(exc)) from None
    print(_format_summary(selection, source=source, top_id=args.top_id))
    if not selection.categories:
        raise UsageError("no categories were selected; nothing written")
    count = len(selection.categories)
    if count > MAX_PAGES:
        raise UsageError(f"{count} categories exceed the limit of {MAX_PAGES} pages; nothing written")
    urls = [category.url for category in selection.categories]
    if args.dry_run:
        print()
        print(f"first {min(PREVIEW_COUNT, count)} URLs:")
        for url in urls[:PREVIEW_COUNT]:
            print(url)
        print("dry run: nothing written")
        return 0
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = render(selection.categories, generated_at=generated_at, source=source, top_id=args.top_id)
    except ValueError as exc:
        raise RunError(str(exc)) from None
    _write_list(args.output, text, urls)
    print()
    print(f"wrote {count} URLs to {args.output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return _run(args)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
