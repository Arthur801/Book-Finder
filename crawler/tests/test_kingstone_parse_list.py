"""Kingstone category list page parser (CB-07 列表頁解析), offline: real fixtures plus synthetic HTML."""

from __future__ import annotations

from pathlib import Path

import pytest

from kingstone.models import KingstoneParseError, ListPage
from kingstone.parse_list import parse_list_html
from kingstone.urls import detail_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kingstone"

JDC_P1 = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
JDC_P1_PU_DESC = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=pu_desc"
JDC_P93 = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=93"
JDC_P94 = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=94"
SJ_P1 = "https://www.kingstone.com.tw/book/sj/?dis=list&page=1"

EMPTY_TEXT = "此分類沒有相關商品唷！"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Real fixtures
# ---------------------------------------------------------------------------


def test_jdc_p1_reads_48_cards_in_page_order() -> None:
    page = parse_list_html(_fixture("list_jdc_p1.html"), JDC_P1)

    assert isinstance(page, ListPage)
    assert len(page.items) == 48
    assert page.items[0].external_id == "2018630959191"
    assert page.items[-1].external_id == "2018564008187"
    assert page.total_pages == 93
    assert page.total_count == 4455
    assert page.empty is False
    assert page.url == JDC_P1


def test_items_carry_detail_source_url_and_list_url() -> None:
    page = parse_list_html(_fixture("list_jdc_p1.html"), JDC_P1)

    first = page.items[0]
    assert first.source_url == "https://www.kingstone.com.tw/basic/2018630959191/"
    assert first.source_url == detail_url(first.external_id)
    assert first.list_url == JDC_P1
    assert all(item.list_url == JDC_P1 for item in page.items)
    assert len({item.external_id for item in page.items}) == 48


def test_jdc_p1_pu_desc_reads_48_cards() -> None:
    page = parse_list_html(_fixture("list_jdc_p1_pu_desc.html"), JDC_P1_PU_DESC)

    assert len(page.items) == 48
    assert page.items[0].external_id == "2018631011676"
    assert page.items[-1].external_id == "2018630999739"
    assert page.total_pages == 93
    assert page.total_count == 4455
    assert page.items[0].list_url == JDC_P1_PU_DESC


def test_jdc_p93_last_page_reads_39_cards() -> None:
    page = parse_list_html(_fixture("list_jdc_p93.html"), JDC_P93)

    assert len(page.items) == 39
    assert page.items[0].external_id == "2018570497548"
    assert page.items[-1].external_id == "2018570036860"
    assert page.total_pages == 93
    assert page.total_count == 4455
    assert page.empty is False


def test_jdc_p94_is_a_legal_empty_page_and_ignores_recommendation_cards() -> None:
    html = _fixture("list_jdc_p94.html")
    # The page has 24 recommendation cards inside a nested prodSlider; none of them may be listed.
    assert html.count("mod_prod_card") > 0

    page = parse_list_html(html, JDC_P94)

    assert page.items == ()
    assert page.empty is True
    assert page.total_pages is None
    assert page.total_count is None


def test_sj_p1_reads_6_cards() -> None:
    page = parse_list_html(_fixture("list_sj_p1.html"), SJ_P1)

    assert len(page.items) == 6
    assert page.items[0].external_id == "2018250016458"
    assert page.items[-1].external_id == "2018577356633"
    assert page.total_pages == 1
    assert page.total_count == 6
    assert page.empty is False


def test_list_page_does_not_parse_card_fields_beyond_the_km_code() -> None:
    page = parse_list_html(_fixture("list_sj_p1.html"), SJ_P1)

    for item in page.items:
        assert set(vars(item)) == {"external_id", "source_url", "list_url"}


# ---------------------------------------------------------------------------
# Synthetic HTML helpers
# ---------------------------------------------------------------------------

KM_A = "2018630959191"
KM_B = "2018564008187"
KM_C = "2018741206573"


def _card(prodno: str = KM_A, href: str | None = None, *, coverbox_link: bool = True) -> str:
    href = f"/basic/{prodno}/?lid=book_class3_jdc&actid=book_class3_jdc" if href is None else href
    link = f'<a href="{href}">書名</a>' if coverbox_link else ""
    return f'<div class="mod_prod_card" data-prodno="{prodno}"><div class="coverbox">{link}</div></div>'


def _page(
    cards: str = "",
    *,
    grid: bool = True,
    empty: str | None = None,
    total_pages: str | None = "2",
    count: str | None = "96",
    all_products: bool = True,
    display: bool = True,
) -> str:
    grid_html = f'<div class="productGrid">{cards}</div>' if grid else ""
    empty_html = f'<div class="emptyCategory">{empty}</div>' if empty is not None else ""
    pages_html = f'<input type="hidden" id="totalPages" value="{total_pages}" />' if total_pages is not None else ""
    count_html = f"共計<span>{count}</span>筆" if count is not None else ""
    display_html = f'<div id="displayCSS">{grid_html}{empty_html}</div>' if display else ""
    all_html = f'<section id="allProducts"><div class="searchResultTitle">{count_html}</div>{pages_html}{display_html}</section>'
    return f"<html><body>{all_html}</body></html>"


URL = JDC_P1


def _parse(html: str, url: str = URL):
    return parse_list_html(html, url)


# ---------------------------------------------------------------------------
# Synthetic positive rules
# ---------------------------------------------------------------------------


def test_synthetic_page_reads_cards_and_totals() -> None:
    page = _parse(_page(_card(KM_A) + _card(KM_B)))

    assert [item.external_id for item in page.items] == [KM_A, KM_B]
    assert page.total_pages == 2
    assert page.total_count == 96
    assert page.empty is False


def test_absolute_same_origin_href_is_accepted() -> None:
    page = _parse(_page(_card(KM_A, href=f"https://www.kingstone.com.tw/basic/{KM_A}/")))

    assert [item.external_id for item in page.items] == [KM_A]


def test_carousel_cards_outside_all_products_are_ignored() -> None:
    carousel = (
        '<section class="carousel"><div id="displayCSS"><div class="productGrid"><div class="mod_prod_card" data-prodno="123">no link</div></div></div></section>'
    )
    html = carousel + _page(_card(KM_A))

    page = _parse(html)

    assert [item.external_id for item in page.items] == [KM_A]


def test_card_outside_product_grid_is_ignored() -> None:
    # A recommendation-style card in a prodSlider (no productGrid) must not be read as a listed product.
    slider = f'<section class="prodSlider"><div class="mod_prod_card" data-prodno="{KM_B}">{_card(KM_B)}</div></section>'
    html = _page(grid=False, empty=EMPTY_TEXT).replace('<div id="displayCSS">', '<div id="displayCSS">' + slider)

    page = _parse(html)

    assert page.items == ()
    assert page.empty is True


def test_duplicate_km_code_keeps_first_occurrence_in_page_order() -> None:
    page = _parse(_page(_card(KM_A) + _card(KM_B) + _card(KM_A)))

    assert [item.external_id for item in page.items] == [KM_A, KM_B]


def test_exactly_48_cards_is_accepted() -> None:
    cards = "".join(_card(f"{2018000000000 + i}") for i in range(48))

    page = _parse(_page(cards))

    assert len(page.items) == 48


def test_missing_total_pages_and_count_are_none() -> None:
    page = _parse(_page(_card(KM_A), total_pages=None, count=None))

    assert page.total_pages is None
    assert page.total_count is None


def test_empty_page_with_totals_still_reports_them() -> None:
    page = _parse(_page(grid=False, empty=EMPTY_TEXT, total_pages="3", count="5"))

    assert page.items == ()
    assert page.empty is True
    assert page.total_pages == 3
    assert page.total_count == 5


def test_empty_category_text_is_compared_after_cleaning_whitespace() -> None:
    page = _parse(_page(grid=False, empty=f"\n   {EMPTY_TEXT}  \n"))

    assert page.empty is True
    assert page.items == ()


# ---------------------------------------------------------------------------
# Synthetic negative cases
# ---------------------------------------------------------------------------


def test_data_prodno_not_matching_link_km_code_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(KM_A, href=f"/basic/{KM_B}/")))


def test_card_without_coverbox_link_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(KM_A, coverbox_link=False)))


def test_card_with_invalid_href_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(KM_A, href=f"https://example.com/basic/{KM_A}/")))


@pytest.mark.parametrize("prodno", ["201863095919", "20186309591911", "201863095919A", " 2018630959191", ""])
def test_non_13_digit_prodno_is_rejected(prodno: str) -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(prodno, href=f"/basic/{prodno}/")))


def test_duplicate_cards_are_still_validated() -> None:
    bad = _card(KM_A, href=f"/basic/{KM_B}/")

    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(KM_A) + _card(KM_A) + bad))


def test_more_than_48_cards_is_rejected() -> None:
    cards = "".join(_card(f"{2018000000000 + i}") for i in range(49))

    with pytest.raises(KingstoneParseError):
        _parse(_page(cards))


def test_product_grid_without_cards_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(""))


def test_no_grid_and_no_empty_category_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(grid=False))


def test_empty_category_with_other_text_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(grid=False, empty="此分類沒有相關商品"))


def test_grid_without_cards_and_wrong_empty_text_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page("", empty="別的文字"))


def test_missing_all_products_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse("<html><body><div id='displayCSS'></div></body></html>")


def test_missing_display_css_is_rejected() -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(KM_A), display=False))


@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5", "", " 2 ", "01"])
def test_total_pages_that_is_not_a_positive_integer_is_rejected(value: str) -> None:
    with pytest.raises(KingstoneParseError):
        _parse(_page(_card(KM_A), total_pages=value))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=01",
        "https://www.kingstone.com.tw/book/JDC/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?page=1&dis=list&sort=bogus",
        "https://www.kingstone.com.tw/normal/book/jdc/?dis=list&page=1",
        "/book/jdc/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&lid=x",
        "https://www.kingstone.com.tw/basic/2018630959191/",
    ],
)
def test_non_canonical_url_is_a_value_error_not_a_parse_error(url: str) -> None:
    with pytest.raises(ValueError) as info:
        _parse(_page(_card(KM_A)), url)
    assert not isinstance(info.value, KingstoneParseError)
