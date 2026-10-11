"""Parser tests against the real pages saved by the user (crawler/tests/fixtures, 2026-10-11).

Expected values were read from the fixtures themselves. Negative cases are derived from the real
pages in code (see tests/fakes.py); no HTML structure is invented.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
from bs4 import BeautifulSoup

from books_crawler.models import Contributor, Identifier
from books_crawler.parsers import (
    RANKING_PAGE_URL,
    ParseError,
    RestrictedBookError,
    parse_detail_html,
    parse_ranking_html,
)
from books_crawler.ranking import RankingValidationError, validate_ranking
from tests.fakes import (
    RANKING_FIXTURE,
    detail_fixture_name,
    detail_with_extra_title_outside_container,
    detail_with_second_subject_group,
    detail_without_product_container,
    detail_without_row,
    detail_without_title,
    fixture_html,
    product_url,
    ranking_with_duplicate_url,
    ranking_without_last_item,
)


# ---------------------------------------------------------------------------
# Ranking page
# ---------------------------------------------------------------------------


def test_explicit_restricted_member_gate_is_recognized():
    html = '<script>alert("本商品為限制級商品，限18歲以上會員瀏覽，請先登入會員。");</script>'
    with pytest.raises(RestrictedBookError, match="requires member login"):
        parse_detail_html(html, product_url(1063006))


def test_restricted_words_inside_a_real_product_are_not_a_member_gate():
    html = '<div class="main_column"><h1>限制級商品與登入會員</h1></div>'
    assert parse_detail_html(html, product_url(1063006)).title == "限制級商品與登入會員"

def test_ranking_fixture_yields_exactly_100_rows_ranked_1_to_100():
    rows = parse_ranking_html(fixture_html(RANKING_FIXTURE))

    assert len(rows) == 100
    assert [row.rank for row in rows] == list(range(1, 101))
    assert len({row.url for row in rows}) == 100
    for row in rows:
        assert re.fullmatch(r"https://www\.books\.com\.tw/products/\d{10}", row.url), row.url


def test_ranking_fixture_passes_validation():
    rows = validate_ranking(parse_ranking_html(fixture_html(RANKING_FIXTURE)))

    assert len(rows) == 100


@pytest.mark.parametrize(
    "rank, product_id",
    [(1, "0011062550"), (8, "0010852315"), (12, "0011062863"), (17, "0011057581"), (100, "0011062168")],
)
def test_ranking_fixture_known_positions(rank, product_id):
    rows = {row.rank: row.url for row in parse_ranking_html(fixture_html(RANKING_FIXTURE))}

    assert rows[rank] == product_url(int(product_id))


def test_ranking_urls_drop_tracking_parameters():
    html = fixture_html(RANKING_FIXTURE)
    assert "loc=P_0003_001" in html  # the real page carries tracking query strings

    rows = parse_ranking_html(html)

    assert all("loc=" not in row.url and "?" not in row.url for row in rows)


def test_ranking_duplicate_detected_after_canonicalization():
    soup = BeautifulSoup(fixture_html(RANKING_FIXTURE), "html.parser")
    items = soup.select("ul.clearfix > li.item")
    first_link = items[0].find("a", href=re.compile("/products/"))["href"]
    second_link = items[1].find("a", href=re.compile("/products/"))
    second_link["href"] = first_link + "?loc=another_tracking_code"  # same product, different query

    rows = parse_ranking_html(str(soup))

    with pytest.raises(RankingValidationError, match="duplicate product URL at ranks 1 and 2"):
        validate_ranking(rows)


def test_ranking_item_without_product_link_is_a_parse_error():
    soup = BeautifulSoup(fixture_html(RANKING_FIXTURE), "html.parser")
    item = soup.select("ul.clearfix > li.item")[0]
    for link in item.find_all("a", href=re.compile("/products/")):
        link.decompose()

    with pytest.raises(ParseError, match="rank 1 has no product link"):
        parse_ranking_html(str(soup))


def test_ranking_page_must_be_the_7_day_chart():
    soup = BeautifulSoup(fixture_html(RANKING_FIXTURE), "html.parser")
    sub_list = soup.select_one("ul.sub_list")
    for item in sub_list.find_all("li"):
        item["class"] = []
    thirty_day = next(li for li in sub_list.find_all("li") if li.get_text(strip=True) == "30日暢銷榜")
    thirty_day["class"] = ["here"]

    with pytest.raises(ParseError, match="7日暢銷榜"):
        parse_ranking_html(str(soup))


def test_derived_ranking_with_99_rows_fails_validation():
    rows = parse_ranking_html(ranking_without_last_item(fixture_html(RANKING_FIXTURE)))

    assert len(rows) == 99
    with pytest.raises(RankingValidationError, match="expected 100"):
        validate_ranking(rows)


def test_derived_ranking_with_duplicate_product_url_fails_validation():
    rows = parse_ranking_html(ranking_with_duplicate_url(fixture_html(RANKING_FIXTURE)))

    with pytest.raises(RankingValidationError, match="duplicate product URL at ranks 1 and 2"):
        validate_ranking(rows)


def test_ranking_url_constant_is_the_user_confirmed_chart():
    assert RANKING_PAGE_URL == "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7"


# ---------------------------------------------------------------------------
# Product detail pages: concrete expectations per real fixture
# ---------------------------------------------------------------------------

CASES = {
    "0011062863": dict(
        title="政。望：前線五十年，從國安決策到世界現場的國家思考",
        publisher="聯經出版公司",
        published=(date(2026, 9, 17), "DAY"),
        language="zh-TW",
        page_count=320,
        identifiers=(Identifier("ISBN_13", "9789570881592"),),
        contributors=(Contributor(1, "李翔宙", "AUTHOR"),),
        subjects=("人文社科", "政治", "政治人物"),
        toc_startswith="序 五十年軍政生涯的省思",
        description_startswith="五十年軍政歷練，見證國家一路走來。",
        thumbnail_contains="0011062863.jpg",
    ),
    "0010852315": dict(
        title="臺灣漫遊錄",
        publisher="春山出版",
        published=(date(2020, 3, 31), "DAY"),
        language="zh-TW",
        page_count=368,
        identifiers=(Identifier("ISBN_13", "9789869866262"),),
        # The page's TOC text mentions 譯者, but there is no translator row: only the author is a contributor.
        contributors=(Contributor(1, "楊双子", "AUTHOR"),),
        subjects=("文學小說", "華文創作", "小說"),
        toc_startswith="推薦序 戛然而止的夢，異鄉的華麗島",
        # The section begins with award badges (國際布克獎得主 etc.); they are part of the source text.
        description_startswith="臺灣文學第一本",
        thumbnail_contains="0010852315.jpg",
    ),
    "0011062550": dict(
        title="與妳相戀到生命盡頭 (首刷限定版) 9",
        publisher="東立",
        published=(date(2026, 10, 2), "DAY"),
        language="zh-TW",
        page_count=148,
        identifiers=(Identifier("ISBN_13", "9786260284909"),),
        contributors=(Contributor(1, "あおのなち", "AUTHOR"), Contributor(2, "蔡夢芳", "TRANSLATOR")),
        subjects=("漫畫/圖文書", "GL"),
        toc_startswith=None,  # no 目錄 section on this page
        description_startswith="席娜等人升上了15班。",
        thumbnail_contains="0011062550.jpg",
    ),
    "0011057581": dict(
        title="花錢的藝術：打造富足人生的金錢心理學【博客來獨家附贈財富透析．互動金句透卡】",
        publisher="平安文化",
        published=(date(2026, 7, 27), "DAY"),
        language="zh-TW",
        page_count=352,
        identifiers=(Identifier("ISBN_13", "9786267859506"),),
        contributors=(Contributor(1, "摩根．豪瑟", "AUTHOR"), Contributor(2, "洪世民", "TRANSLATOR")),
        subjects=("商業理財", "投資理財", "投資學"),
        toc_startswith="【推薦序】了解錢的作用，賺錢才有意義／綠角",
        description_startswith="這本書寫盡了你從出生到離世，",
        thumbnail_contains="0011057581.jpg",
    ),
}


@pytest.mark.parametrize("product_id", sorted(CASES))
def test_detail_fixture_extracts_expected_values(product_id):
    expected = CASES[product_id]
    draft = parse_detail_html(
        fixture_html(detail_fixture_name(product_id)), product_url(int(product_id))
    )

    assert draft.source_url == product_url(int(product_id))
    assert draft.title == expected["title"]
    assert draft.publisher == expected["publisher"]
    assert (draft.published_date, draft.published_date_precision) == expected["published"]
    assert draft.language == expected["language"]
    assert draft.page_count == expected["page_count"]
    assert draft.identifiers == expected["identifiers"]
    assert draft.contributors == expected["contributors"]
    assert draft.subjects == expected["subjects"]
    assert draft.description is not None and draft.description.startswith(expected["description_startswith"])
    assert draft.thumbnail_url is not None and expected["thumbnail_contains"] in draft.thumbnail_url
    if expected["toc_startswith"] is None:
        assert draft.table_of_contents is None
    else:
        assert draft.table_of_contents is not None
        assert draft.table_of_contents.startswith(expected["toc_startswith"])


def test_detail_parser_accepts_tracking_url_and_canonicalizes_it():
    draft = parse_detail_html(
        fixture_html(detail_fixture_name("0011062550")),
        "https://www.books.com.tw/products/0011062550?loc=P_0003_001",
    )

    assert draft.source_url == product_url(11062550)


# ---------------------------------------------------------------------------
# Derived negative detail cases (built from 0011062863)
# ---------------------------------------------------------------------------

BASE_ID = "0011062863"


def _base_html() -> str:
    return fixture_html(detail_fixture_name(BASE_ID))


def test_derived_detail_without_title_is_a_parse_error():
    with pytest.raises(ParseError, match="title"):
        parse_detail_html(detail_without_title(_base_html()), product_url(int(BASE_ID)))


def test_missing_publication_date_is_null_not_guessed():
    draft = parse_detail_html(detail_without_row(_base_html(), "出版日期"), product_url(int(BASE_ID)))

    assert (draft.published_date, draft.published_date_precision) == (None, None)


def test_missing_language_row_is_null():
    draft = parse_detail_html(detail_without_row(_base_html(), "語言"), product_url(int(BASE_ID)))

    assert draft.language is None


def test_missing_spec_row_means_no_page_count():
    draft = parse_detail_html(detail_without_row(_base_html(), "規格"), product_url(int(BASE_ID)))

    assert draft.page_count is None


def test_missing_isbn_row_means_no_identifier():
    draft = parse_detail_html(detail_without_row(_base_html(), "ISBN"), product_url(int(BASE_ID)))

    assert draft.identifiers == ()


def test_invalid_isbn_checksum_is_not_stored():
    html = _base_html().replace("9789570881592", "9789570881593")  # wrong check digit

    draft = parse_detail_html(html, product_url(int(BASE_ID)))

    assert draft.identifiers == ()


def test_missing_toc_section_is_null():
    soup = BeautifulSoup(_base_html(), "html.parser")
    header = next(h3 for h3 in soup.find_all("h3") if h3.get_text(strip=True) == "目錄")
    header.parent.decompose()

    draft = parse_detail_html(str(soup), product_url(int(BASE_ID)))

    assert draft.table_of_contents is None
    assert draft.description is not None  # the other section is unaffected


def test_missing_cover_image_is_null():
    soup = BeautifulSoup(_base_html(), "html.parser")
    for img in soup.select("img.cover"):
        img.decompose()

    draft = parse_detail_html(str(soup), product_url(int(BASE_ID)))

    assert draft.thumbnail_url is None


# ---------------------------------------------------------------------------
# Scoping: nothing outside the product container is read (no whole-page fallback)
# ---------------------------------------------------------------------------

def test_missing_product_container_is_a_parse_error_not_a_whole_page_scan():
    html = detail_without_product_container(_base_html())

    with pytest.raises(ParseError, match=r"\.main_column not found"):
        parse_detail_html(html, product_url(int(BASE_ID)))


def test_title_comes_only_from_the_product_container():
    html = detail_with_extra_title_outside_container(_base_html())

    with pytest.raises(ParseError, match="title"):
        parse_detail_html(html, product_url(int(BASE_ID)))


# ---------------------------------------------------------------------------
# Subjects: every level of every 本書分類 group (Q1)
# ---------------------------------------------------------------------------

def test_subjects_from_all_groups_are_kept_once_in_page_order():
    html = detail_with_second_subject_group(_base_html(), ["歷史", "政治", "台灣史"])

    draft = parse_detail_html(html, product_url(int(BASE_ID)))

    assert draft.subjects == ("人文社科", "政治", "政治人物", "歷史", "台灣史")


# ---------------------------------------------------------------------------
# Description / TOC line breaks (Q3)
# ---------------------------------------------------------------------------

def test_inline_award_badges_stay_on_one_line_in_description():
    draft = parse_detail_html(
        fixture_html(detail_fixture_name("0010852315")), product_url(10852315)
    )

    lines = draft.description.split("\n")
    assert lines[0] == "臺灣文學第一本"
    assert lines[1] == "2026國際布克獎得主"  # <strong>2026</strong><strong>國際布克獎得主</strong> is one line
    assert lines[2] == "2024美國國家圖書獎翻譯文學大獎"
    assert lines[3] == "2024日本翻譯大賞"


@pytest.mark.parametrize("product_id", sorted(CASES))
def test_description_and_toc_have_no_runs_of_blank_lines(product_id):
    draft = parse_detail_html(fixture_html(detail_fixture_name(product_id)), product_url(int(product_id)))

    for text in (draft.description, draft.table_of_contents):
        if text is not None:
            assert "\n\n\n" not in text
            assert not text.startswith("\n") and not text.endswith("\n")
