"""Operator tool that builds the Eslite category page list (deploy/local/eslite_category_pages.py).

Offline: the tree fetch is replaced by a fake that records its calls, and ``--from-file`` feeds synthetic trees.
Nothing here touches the network.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eslite.page_list import MAX_PAGES, load_page_urls
from eslite.urls import canonical_list_url

CRAWLER = Path(__file__).resolve().parents[1]
TOOL = CRAWLER / "deploy" / "local" / "eslite_category_pages.py"
BASE = "https://www.eslite.com/category/3/"
TREE_URL = "https://athena.eslite.com/api/v1/categories"


def load_tool():
    spec = importlib.util.spec_from_file_location("eslite_category_pages", TOOL)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: dataclasses look the module up by name while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = load_tool()


def node(node_id, depth, description, children=None, *, link="", is_brand=False):
    """A tree node in the API's shape. ``children=None`` omits the key, as the real API does for some leaves."""
    item = {
        "id": node_id,
        "depth": depth,
        "description": description,
        "parent_id": None,
        "path": description,
        "is_brand": is_brand,
        "link": link,
    }
    if children is not None:
        item["children"] = children
    return item


def sample_tree():
    return [
        node(1057, 1, "品牌旗艦", [node(1058, 2, "品牌二級", [node(9001, 3, "品牌三級")])]),
        node(
            3,
            1,
            "中文書",
            [
                node(
                    100,
                    2,
                    "文學",
                    [
                        node(101, 3, "小說"),
                        node(102, 3, "散文", link="https://events.eslite.com/x"),
                        node(103, 3, "品牌書", is_brand=True),
                        node(104, 3, "詩"),
                    ],
                ),
                node(200, 2, "生活", [node(201, 3, "飲食"), node(202, 3, "旅遊"), node(101, 3, "小說重複")]),
                node(300, 2, "空白二級", []),
                node(301, 2, "無子節點"),
            ],
        ),
        node(42401, 1, "外文書", [node(42402, 2, "英文", [node(42403, 3, "English")])]),
    ]


SAMPLE_KEPT = [101, 104, 201, 202]


def oversized_tree(count):
    leaves = [node(5000 + i, 3, f"分類{i}") for i in range(count)]
    return [node(3, 1, "中文書", [node(77, 2, "大量", leaves)])]


class FakeResponse:
    def __init__(self, *, status_code=200, content_type="application/json; charset=utf-8", body=None):
        self.status_code = status_code
        self.headers = {} if content_type is None else {"content-type": content_type}
        self.content = json.dumps(sample_tree()).encode("utf-8") if body is None else body


class FakeRequests:
    """Stands in for ``curl_cffi.requests``; records every call and returns or raises what it was given."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else FakeResponse()
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def fake(monkeypatch):
    fake_requests = FakeRequests()
    monkeypatch.setattr(tool, "curl_requests", fake_requests)
    return fake_requests


def write_tree(tmp_path, tree, name="tree.json"):
    path = tmp_path / name
    path.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    return path


def urls_of(ids):
    return [f"{BASE}{i}" for i in ids]


# --- pure selection -----------------------------------------------------------------------------------------------


def test_only_level3_categories_under_the_top_id_are_kept_in_tree_order():
    categories = tool.select_categories(sample_tree())

    assert [c.id for c in categories] == SAMPLE_KEPT
    assert categories[0] == tool.Category(id=101, level2_id=100, names=("中文書", "文學", "小說"))
    assert categories[2].names == ("中文書", "生活", "飲食")


def test_other_top_level_categories_are_ignored_even_when_they_have_level3_nodes():
    tree = sample_tree()

    assert tool.select_categories(tree, top_id=42401) == [tool.Category(42403, 42402, ("外文書", "英文", "English"))]
    assert tool.select_categories(tree, top_id=1057) == [tool.Category(9001, 1058, ("品牌旗艦", "品牌二級", "品牌三級"))]


def test_external_links_and_brand_pages_are_skipped_and_counted():
    selection = tool.select(sample_tree())

    assert selection.seen == 7
    assert selection.skipped_link == 1
    assert selection.skipped_brand == 1
    assert selection.duplicates == 1
    assert selection.skipped_excluded == 0
    assert len(selection.categories) == 4


def test_an_empty_string_link_is_not_an_external_link():
    tree = [node(3, 1, "中文書", [node(10, 2, "二", [node(11, 3, "三", link="")])])]

    assert [c.id for c in tool.select_categories(tree)] == [11]


def test_exclude_level2_skips_every_level3_under_those_level2_ids_and_counts_them():
    categories = tool.select_categories(sample_tree(), exclude_level2=(200,))
    selection = tool.select(sample_tree(), exclude_level2=(100,))

    assert [c.id for c in categories] == [101, 104]
    # Exclusion runs before de-duplication, so the 101 under 200 is the first kept occurrence once 100 is excluded.
    assert [c.id for c in selection.categories] == [201, 202, 101]
    assert selection.duplicates == 0
    # Under 100: 101 and 104 are excluded, 102 is a link and 103 is a brand (checked before the exclude rule).
    assert selection.skipped_excluded == 2
    assert selection.skipped_link == 1
    assert selection.skipped_brand == 1


def test_duplicate_ids_are_dropped_keeping_the_first_in_tree_order():
    selection = tool.select(sample_tree())

    assert 101 in [c.id for c in selection.categories]
    assert [c.level2_id for c in selection.categories if c.id == 101] == [100]
    assert selection.duplicates == 1


def test_per_level2_counts_list_every_level2_under_the_top_including_empty_ones():
    selection = tool.select(sample_tree())

    assert selection.per_level2 == ((100, "文學", 2), (200, "生活", 2), (300, "空白二級", 0), (301, "無子節點", 0))


def test_a_missing_top_id_is_a_value_error():
    with pytest.raises(ValueError):
        tool.select_categories(sample_tree(), top_id=999)


def test_a_missing_top_id_inside_a_level2_is_not_a_top_match():
    tree = [node(1, 1, "其他", [node(3, 2, "不是頂層")])]

    with pytest.raises(ValueError):
        tool.select_categories(tree, top_id=3)


# --- rendering ----------------------------------------------------------------------------------------------------


def test_render_round_trips_through_load_page_urls_to_the_same_urls_in_order(tmp_path):
    categories = tool.select_categories(sample_tree())
    text = tool.render(categories, generated_at="2026-11-11T00:00:00Z", source=TREE_URL)
    path = tmp_path / "eslite-pages.txt"
    path.write_text(text, encoding="utf-8")

    urls = load_page_urls(path)

    assert urls == urls_of(SAMPLE_KEPT)
    assert all(canonical_list_url(url) == url for url in urls)
    assert text.endswith("\n")


def test_render_writes_the_header_and_a_name_comment_before_each_url():
    categories = tool.select_categories(sample_tree())
    text = tool.render(categories, generated_at="2026-11-11T00:00:00Z", source="/tmp/tree.json")
    lines = text.splitlines()

    assert all(line.startswith(("#", BASE)) or line == "" for line in lines)
    assert "2026-11-11T00:00:00Z" in text
    assert "/tmp/tree.json" in text
    assert "level-3 categories under 中文書, page 1 only, external links and brand pages skipped" in text
    assert "400" in text
    assert "run order" in text
    assert "--force" in text
    assert "# 中文書 › 文學 › 小說" in lines
    assert lines[lines.index("# 中文書 › 文學 › 小說") + 1] == f"{BASE}101"


def test_render_rejects_a_category_whose_url_is_not_canonical():
    with pytest.raises(ValueError):
        tool.render([tool.Category(id=0, level2_id=1, names=("a", "b", "c"))], generated_at="x", source="y")


def test_render_keeps_names_on_one_comment_line():
    categories = [tool.Category(id=101, level2_id=100, names=("中文\n書", "文學 ", "小說"))]
    text = tool.render(categories, generated_at="x", source="y")

    assert "# 中文 書 › 文學 › 小說" in text.splitlines()


# --- CLI ----------------------------------------------------------------------------------------------------------


def test_the_default_output_is_the_eslite_page_file_next_to_the_package():
    from eslite.page_list import DEFAULT_PAGES_FILE

    assert tool.DEFAULT_OUTPUT == DEFAULT_PAGES_FILE


def test_from_file_writes_the_list_and_fetches_nothing(tmp_path, fake, capsys):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"

    code = tool.main(["--from-file", str(tree), "--output", str(out)])

    assert code == 0
    assert fake.calls == []
    assert load_page_urls(out) == urls_of(SAMPLE_KEPT)
    stdout = capsys.readouterr().out
    assert "kept" in stdout and "文學" in stdout and "生活" in stdout


def test_a_fetch_run_makes_exactly_one_request_with_the_required_options(tmp_path, fake):
    out = tmp_path / "out.txt"

    code = tool.main(["--output", str(out)])

    assert code == 0
    assert len(fake.calls) == 1
    url, kwargs = fake.calls[0]
    assert url == TREE_URL
    assert kwargs["impersonate"] == "chrome"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 30
    assert kwargs["headers"] == {"Accept": "application/json", "Accept-Language": "zh-TW,zh;q=0.9"}
    assert load_page_urls(out) == urls_of(SAMPLE_KEPT)


def test_top_id_and_exclude_level2_flags_are_applied(tmp_path):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--exclude-level2", "200"]) == 0
    assert load_page_urls(out) == urls_of([101, 104])

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--top-id", "42401", "--force"]) == 0
    assert load_page_urls(out) == [f"{BASE}42403"]


def test_a_missing_top_id_exits_1_and_writes_nothing(tmp_path, capsys):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"

    code = tool.main(["--from-file", str(tree), "--output", str(out), "--top-id", "999"])

    assert code == 1
    assert not out.exists()
    assert "999" in capsys.readouterr().err


def test_more_than_max_pages_exits_2_and_leaves_the_file_untouched(tmp_path, capsys):
    tree = write_tree(tmp_path, oversized_tree(MAX_PAGES + 1))
    out = tmp_path / "out.txt"
    out.write_text("# hand comment\n", encoding="utf-8")

    code = tool.main(["--from-file", str(tree), "--output", str(out)])

    assert code == 2
    assert out.read_text(encoding="utf-8") == "# hand comment\n"
    assert str(MAX_PAGES) in capsys.readouterr().err


def test_exactly_max_pages_is_accepted(tmp_path):
    tree = write_tree(tmp_path, oversized_tree(MAX_PAGES))
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out)]) == 0
    assert len(load_page_urls(out)) == MAX_PAGES


def test_no_selected_categories_exits_2_and_writes_nothing(tmp_path):
    tree = write_tree(tmp_path, [node(3, 1, "中文書", [node(10, 2, "二", [node(11, 3, "三", is_brand=True)])])])
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out)]) == 2
    assert not out.exists()


def test_dry_run_prints_the_summary_and_first_five_urls_and_writes_nothing(tmp_path, capsys):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"

    code = tool.main(["--from-file", str(tree), "--output", str(out), "--dry-run"])

    assert code == 0
    assert not out.exists()
    stdout = capsys.readouterr().out
    assert "文學" in stdout
    assert "202" in stdout
    assert f"{BASE}101" in stdout


def test_dry_run_does_not_replace_or_check_an_existing_file(tmp_path):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"
    out.write_text(f"{BASE}999\n", encoding="utf-8")

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--dry-run"]) == 0
    assert out.read_text(encoding="utf-8") == f"{BASE}999\n"


def test_an_existing_url_list_is_not_overwritten_without_force(tmp_path, capsys):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"
    hand_made = f"# mine\n{BASE}999\n"
    out.write_text(hand_made, encoding="utf-8")

    code = tool.main(["--from-file", str(tree), "--output", str(out)])

    assert code == 2
    assert out.read_text(encoding="utf-8") == hand_made
    assert "--force" in capsys.readouterr().err


def test_an_existing_url_list_is_replaced_with_force(tmp_path):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"
    out.write_text(f"{BASE}999\n", encoding="utf-8")

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--force"]) == 0
    assert load_page_urls(out) == urls_of(SAMPLE_KEPT)


def test_a_comments_only_existing_file_is_replaced_without_force(tmp_path):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"
    out.write_text("# placeholder\n\n   \n# more\n", encoding="utf-8")

    assert tool.main(["--from-file", str(tree), "--output", str(out)]) == 0
    assert load_page_urls(out) == urls_of(SAMPLE_KEPT)


def test_a_successful_write_leaves_no_temporary_file_behind(tmp_path):
    tree = write_tree(tmp_path, sample_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt", "tree.json"]


def test_the_tool_runs_from_any_working_directory(tmp_path):
    tree = write_tree(tmp_path, sample_tree())

    result = subprocess.run(
        [sys.executable, str(TOOL), "--from-file", str(tree), "--dry-run"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert f"{BASE}101" in result.stdout


# --- default level-2 excludes (promotion lists) -------------------------------------------------------------------

PROMO_KEPT = [101, 104, 201, 202]  # sample_tree() without the promotion level-2 categories
PROMO_NO_DEFAULTS_KEPT = [101, 104, 201, 202, 44445, 15821, 15822]


def promo_tree():
    """The sample tree plus the two promotion level-2 categories under 中文書 (44444 and 1582)."""
    tree = sample_tree()
    top = next(item for item in tree if item["id"] == 3)
    top["children"] += [
        node(44444, 2, "📢雙11強檔推薦", [node(44445, 3, "雙11一")]),
        node(1582, 2, "編輯推薦", [node(15821, 3, "編推一"), node(15822, 3, "編推二")]),
    ]
    return tree


def test_the_default_excludes_are_the_two_promotion_level2_ids():
    assert tool.DEFAULT_EXCLUDED_LEVEL2 == (44444, 1582)


def test_the_default_excludes_are_applied_by_the_cli(tmp_path):
    tree = write_tree(tmp_path, promo_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out)]) == 0

    assert load_page_urls(out) == urls_of(PROMO_KEPT)


def test_exclude_level2_adds_to_the_default_excludes(tmp_path):
    tree = write_tree(tmp_path, promo_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--exclude-level2", "200"]) == 0

    assert load_page_urls(out) == urls_of([101, 104])


def test_no_default_excludes_turns_the_default_excludes_off(tmp_path):
    tree = write_tree(tmp_path, promo_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--no-default-excludes"]) == 0

    assert load_page_urls(out) == urls_of(PROMO_NO_DEFAULTS_KEPT)


def test_no_default_excludes_keeps_only_the_explicit_excludes(tmp_path):
    tree = write_tree(tmp_path, promo_tree())
    out = tmp_path / "out.txt"

    code = tool.main(["--from-file", str(tree), "--output", str(out), "--no-default-excludes", "--exclude-level2", "200"])

    assert code == 0
    assert load_page_urls(out) == urls_of([101, 104, 44445, 15821, 15822])


def test_the_summary_says_which_level2_ids_were_excluded_by_default_and_which_explicitly(tmp_path, capsys):
    tree = write_tree(tmp_path, promo_tree())

    assert tool.main(["--from-file", str(tree), "--dry-run", "--exclude-level2", "200"]) == 0

    stdout = capsys.readouterr().out
    assert "excluded level-2 by default: 44444, 1582" in stdout
    assert "excluded level-2 by --exclude-level2: 200" in stdout


def test_the_summary_says_no_default_excludes_when_they_are_turned_off(tmp_path, capsys):
    tree = write_tree(tmp_path, promo_tree())

    assert tool.main(["--from-file", str(tree), "--dry-run", "--no-default-excludes"]) == 0

    stdout = capsys.readouterr().out
    assert "excluded level-2 by default: none" in stdout
    assert "excluded level-2 by --exclude-level2: none" in stdout


def test_the_written_header_lists_the_excluded_level2_ids(tmp_path):
    tree = write_tree(tmp_path, promo_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--exclude-level2", "200"]) == 0

    header = [line for line in out.read_text(encoding="utf-8").splitlines() if "Excluded level-2" in line]
    assert header == ["# Excluded level-2 ids: 44444, 1582, 200"]


def test_the_header_says_none_when_no_level2_is_excluded(tmp_path):
    tree = write_tree(tmp_path, promo_tree())
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tree), "--output", str(out), "--no-default-excludes"]) == 0

    assert "# Excluded level-2 ids: none" in out.read_text(encoding="utf-8").splitlines()


def test_render_lists_the_given_excluded_level2_ids_in_the_header():
    categories = tool.select_categories(sample_tree())
    text = tool.render(categories, generated_at="x", source="y", excluded_level2=(44444, 1582))

    assert "# Excluded level-2 ids: 44444, 1582" in text.splitlines()


# --- fetch failures: exit 1, nothing written, exactly one request ------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status_code=403, body=b"forbidden"),
        FakeResponse(content_type="text/html; charset=utf-8", body=b"<html></html>"),
        FakeResponse(content_type=None, body=json.dumps(sample_tree()).encode()),
        FakeResponse(body=json.dumps({"id": 3}).encode()),
        FakeResponse(body=b"not json at all"),
        FakeResponse(body=b" " * (5 * 1024 * 1024 + 1)),
    ],
    ids=["status-403", "html", "no-content-type", "object-not-list", "invalid-json", "oversized"],
)
def test_a_bad_fetch_exits_1_writes_nothing_and_makes_one_request(tmp_path, monkeypatch, response):
    fake_requests = FakeRequests(response=response)
    monkeypatch.setattr(tool, "curl_requests", fake_requests)
    out = tmp_path / "out.txt"
    existing = "# placeholder\n"
    out.write_text(existing, encoding="utf-8")

    code = tool.main(["--output", str(out)])

    assert code == 1
    assert out.read_text(encoding="utf-8") == existing
    assert len(fake_requests.calls) == 1


def test_a_bad_fetch_with_force_leaves_an_existing_url_list_untouched(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(tool, "curl_requests", FakeRequests(response=FakeResponse(status_code=500, body=b"")))
    out = tmp_path / "out.txt"
    existing = f"{BASE}999\n"
    out.write_text(existing, encoding="utf-8")

    assert tool.main(["--output", str(out), "--force"]) == 1
    assert out.read_text(encoding="utf-8") == existing


def test_an_existing_url_list_refuses_before_any_fetch(tmp_path, fake):
    out = tmp_path / "out.txt"
    existing = f"{BASE}999\n"
    out.write_text(existing, encoding="utf-8")

    assert tool.main(["--output", str(out)]) == 2
    assert out.read_text(encoding="utf-8") == existing
    assert fake.calls == []


def test_a_network_exception_exits_1_writes_nothing_and_makes_one_request(tmp_path, monkeypatch, capsys):
    fake_requests = FakeRequests(error=ConnectionError("boom"))
    monkeypatch.setattr(tool, "curl_requests", fake_requests)
    out = tmp_path / "out.txt"

    code = tool.main(["--output", str(out)])

    assert code == 1
    assert not out.exists()
    assert len(fake_requests.calls) == 1
    assert "ConnectionError" in capsys.readouterr().err


def test_a_bad_from_file_exits_1_and_writes_nothing(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(bad), "--output", str(out)]) == 1
    assert not out.exists()


def test_a_missing_from_file_exits_1(tmp_path):
    out = tmp_path / "out.txt"

    assert tool.main(["--from-file", str(tmp_path / "nope.json"), "--output", str(out)]) == 1
    assert not out.exists()
