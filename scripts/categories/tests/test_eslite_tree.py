"""Eslite level-3 derivation from a saved category tree (eslite_tree.py). No network."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from category_config import ConfigError
from eslite_tree import (
    HEADER,
    Level3Row,
    build_level3_rows,
    read_level3_tsv,
    write_level3_tsv,
)


def node(node_id: int, depth: int, description: str, children: list | None = None, **extra) -> dict:
    data = {"id": node_id, "depth": depth, "description": description, "children": children or [], "link": ""}
    data.update(extra)
    return data


def synthetic_tree() -> list[dict]:
    literature = node(
        28,
        2,
        "📌文學館79折起",
        [
            node(1001, 3, "小說"),
            node(1002, 3, "散文", link="https://www.eslite.com/exhibitions/CU202206-00348"),  # external link: skipped
            node(1003, 3, "品牌推薦", is_brand=True),  # brand page: skipped
            node(1004, 3, "  科幻 \t 小說\n"),  # whitespace is collapsed
        ],
    )
    promo = node(44444, 2, "📢雙11強檔推薦", [node(2001, 3, "雙11小說")])  # excluded level-2
    philosophy = node(61, 2, "人文史哲", [node(3001, 3, "哲學"), node(3002, 3, "小說")])  # 小說 also under 28
    return [
        node(1057, 1, "品牌旗艦", [node(5001, 2, "藝術在線", [node(5002, 3, "畫廊簡介")])]),
        node(3, 1, "中文書", [literature, promo, philosophy]),
    ]


def test_builds_level3_rows_in_tree_order_with_exclusions() -> None:
    rows, selection = build_level3_rows(synthetic_tree())

    assert rows == [
        Level3Row(level2_id=28, level2_name="📌文學館79折起", level3_id=1001, level3_name="小說"),
        Level3Row(level2_id=28, level2_name="📌文學館79折起", level3_id=1004, level3_name="科幻 小說"),
        Level3Row(level2_id=61, level2_name="人文史哲", level3_id=3001, level3_name="哲學"),
        Level3Row(level2_id=61, level2_name="人文史哲", level3_id=3002, level3_name="小說"),
    ]
    assert selection.skipped_link == 1
    assert selection.skipped_brand == 1
    assert selection.skipped_excluded == 1


def test_default_excluded_level2_ids_are_skipped() -> None:
    tree = synthetic_tree()
    rows, _ = build_level3_rows(tree)

    assert all(row.level2_id not in {44444, 1582} for row in rows)


def test_missing_top_category_is_an_error() -> None:
    tree = [node(1057, 1, "品牌旗艦")]

    with pytest.raises(ValueError, match="id 3"):
        build_level3_rows(tree)


def test_empty_name_after_collapse_is_an_error() -> None:
    tree = [node(3, 1, "中文書", [node(28, 2, "文學", [node(1001, 3, " \t ")])])]

    with pytest.raises(ValueError, match="empty"):
        build_level3_rows(tree)


def test_tsv_roundtrip(tmp_path: Path) -> None:
    rows, _ = build_level3_rows(synthetic_tree())
    target = tmp_path / "eslite_level3.tsv"

    write_level3_tsv(target, rows)

    assert target.read_text(encoding="utf-8").splitlines()[0] == HEADER
    assert read_level3_tsv(target) == rows


def test_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "eslite_level3.tsv"
    target.write_text("previous content\n", encoding="utf-8")
    rows, _ = build_level3_rows(synthetic_tree())

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        write_level3_tsv(target, rows)

    assert target.read_text(encoding="utf-8") == "previous content\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["eslite_level3.tsv"]


def write_tsv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "header"),
        ("level2_id\tlevel2_name\tlevel3_id\n", "header"),
        ("level2_id\tlevel2_name\tlevel3_id\tlevel3_name\n28\t文學\t1001\n", "4 columns"),
        ("level2_id\tlevel2_name\tlevel3_id\tlevel3_name\nabc\t文學\t1001\t小說\n", "level2_id"),
        ("level2_id\tlevel2_name\tlevel3_id\tlevel3_name\n28\t文學\t0\t小說\n", "level3_id"),
        ("level2_id\tlevel2_name\tlevel3_id\tlevel3_name\n28\t文學\t1001\t\n", "empty"),
        ("level2_id\tlevel2_name\tlevel3_id\tlevel3_name\n28\t文學\t1001\t" + "書" * 256 + "\n", "255"),
    ],
)
def test_reading_malformed_tsv_is_a_config_error(tmp_path: Path, text: str, message: str) -> None:
    path = write_tsv(tmp_path / "eslite_level3.tsv", text)

    with pytest.raises(ConfigError, match=message):
        read_level3_tsv(path)


def test_reading_missing_tsv_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="eslite_level3.tsv"):
        read_level3_tsv(tmp_path / "eslite_level3.tsv")
