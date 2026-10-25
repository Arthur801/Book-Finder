"""Kingstone (金石堂) URL grammar: list page canonicalization, detail URLs and card href parsing. Offline."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from kingstone.urls import SITE_ORIGIN, SORT_KEYS, canonical_list_url, detail_url, km_code_from_href

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kingstone"
LIST_CARD_SELECTOR = "section#allProducts #displayCSS > .productGrid > .mod_prod_card[data-prodno]"

BASE = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=93",
        "https://www.kingstone.com.tw/book/sj/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=pu_desc",
    ],
)
def test_the_list_urls_used_by_the_e0_fixtures_are_accepted(raw):
    assert canonical_list_url(raw) == raw


@pytest.mark.parametrize("sort", sorted(SORT_KEYS - {"sa_desc"}))
def test_each_non_default_sort_key_is_accepted_and_kept(sort):
    assert canonical_list_url(f"{BASE}&sort={sort}") == f"{BASE}&sort={sort}"


def test_the_five_sort_keys_are_exactly_the_contract_set():
    assert SORT_KEYS == frozenset({"sa_desc", "pu_desc", "pu_asc", "pr_desc", "pr_asc"})


def test_the_site_origin_is_the_www_host():
    assert SITE_ORIGIN == "https://www.kingstone.com.tw"


def test_an_uppercase_category_code_is_canonicalized_to_lowercase():
    assert canonical_list_url("https://www.kingstone.com.tw/book/JDC/?dis=list&page=3") == ("https://www.kingstone.com.tw/book/jdc/?dis=list&page=3")


def test_a_mixed_case_code_is_canonicalized_to_lowercase():
    assert canonical_list_url("https://www.kingstone.com.tw/book/Jd/?dis=list&page=2") == ("https://www.kingstone.com.tw/book/jd/?dis=list&page=2")


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.kingstone.com.tw/book/jdc/?page=2&dis=list",
        "https://www.kingstone.com.tw/book/jdc/?sort=pu_desc&page=2&dis=list",
        "https://www.kingstone.com.tw/book/jdc/?page=2&sort=pu_desc&dis=list",
    ],
)
def test_query_keys_in_any_order_produce_the_same_canonical_form(raw):
    expected = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=2"
    if "sort=" in raw:
        expected += "&sort=pu_desc"
    assert canonical_list_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "HTTPS://www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://www.books.com.tw/book/jdc/?dis=list&page=1",
        "https://WWW.KINGSTONE.COM.TW/book/jdc/?dis=list&page=1",
        "https://user@www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://user:pw@www.kingstone.com.tw/book/jdc/?dis=list&page=1",
        "https://www.kingstone.com.tw:443/book/jdc/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1#top",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1#",
        "https://www.kingstone.com.tw/normal/book/jd",
        "https://www.kingstone.com.tw/book/jdc?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/",
        "https://www.kingstone.com.tw/book/j/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdcab/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jd1/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/12/?dis=list&page=1",
        "https://www.kingstone.com.tw/book//?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/extra/?dis=list&page=1",
        "https://www.kingstone.com.tw/basic/2018630959191/?dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list",
        "https://www.kingstone.com.tw/book/jdc/?dis=pic&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=0",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=-1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=01",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=+1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=abc",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=１",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=sa_asc",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&lid=home",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&page=2",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&dis=list&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=pu_desc&sort=pr_asc",
        "https://www.kingstone.com.tw/book/jdc/?",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&&page=1",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&",
        "not a url",
        "",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&page=[1",
    ],
)
def test_anything_outside_the_grammar_is_rejected(raw):
    assert canonical_list_url(raw) is None


def test_detail_url_builds_the_basic_page_for_a_13_digit_km_code():
    assert detail_url("2018630959191") == "https://www.kingstone.com.tw/basic/2018630959191/"


@pytest.mark.parametrize("km_code", ["", "201863095919", "20186309591910", "201863095919a", "２０１８６３０９５９１９", " 2018630959191"])
def test_detail_url_rejects_a_km_code_that_is_not_13_ascii_digits(km_code):
    with pytest.raises(ValueError):
        detail_url(km_code)


@pytest.mark.parametrize(
    "href, expected",
    [
        ("/basic/2018630959191/", "2018630959191"),
        ("/basic/2028631022428/?lid=categoryranking_book_jdc&actid=", "2028631022428"),
        ("/basic/2018631022245/?lid=book_class3_jdc&actid=book_class3_jdc", "2018631022245"),
        ("https://www.kingstone.com.tw/basic/2018630959191/", "2018630959191"),
        ("https://www.kingstone.com.tw/basic/2018630959191/?lid=home_keyword", "2018630959191"),
    ],
)
def test_km_code_from_href_accepts_relative_and_same_origin_absolute_detail_links(href, expected):
    assert km_code_from_href(href) == expected


@pytest.mark.parametrize(
    "href",
    [
        "",
        "/basic/201863095919/",
        "/basic/20186309591910/",
        "/basic/201863095919a/",
        "/basic/2018630959191",
        "basic/2018630959191/",
        "/book/jdc/?dis=list&page=1",
        "/basic/2018630959191/#reviews",
        "/basic/2018630959191/?x=<script>",
        "//www.kingstone.com.tw/basic/2018630959191/",
        "http://www.kingstone.com.tw/basic/2018630959191/",
        "https://kingstone.com.tw/basic/2018630959191/",
        "https://www.books.com.tw/basic/2018630959191/",
        "https://user@www.kingstone.com.tw/basic/2018630959191/",
        "https://www.kingstone.com.tw:8443/basic/2018630959191/",
        "https://www.kingstone.com.tw/basic/2018630959191/extra/",
        "https://www.kingstone.com.tw/normal/basic/2018630959191/",
        "https://www.kingstone.com.tw/book/jdc/",
        "https://[::1/basic/2018630959191/",
    ],
)
def test_km_code_from_href_rejects_everything_else(href):
    assert km_code_from_href(href) is None


def test_every_card_href_in_the_jdc_list_fixture_resolves_to_its_data_prodno():
    soup = BeautifulSoup((FIXTURE_DIR / "list_jdc_p1.html").read_text(encoding="utf-8"), "html.parser")
    cards = soup.select(LIST_CARD_SELECTOR)

    assert len(cards) == 48
    for card in cards:
        links = [a["href"] for a in card.find_all("a", href=True) if "/basic/" in a["href"]]
        assert links, card["data-prodno"]
        for href in links:
            assert km_code_from_href(href) == card["data-prodno"], href


def test_sa_desc_is_the_default_sort_so_canonical_form_drops_it():
    expected = "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"
    assert canonical_list_url(f"{BASE}&sort=sa_desc") == expected
    assert canonical_list_url(BASE) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.kingstone.com.tw/book/jdc/?sort=sa_desc&page=1&dis=list",
        "https://www.kingstone.com.tw/book/jdc/?page=1&sort=sa_desc&dis=list",
        "https://www.kingstone.com.tw/book/jdc/?dis=list&sort=sa_desc&page=1",
    ],
)
def test_sa_desc_in_any_key_order_is_the_same_canonical_form_as_no_sort(raw):
    assert canonical_list_url(raw) == "https://www.kingstone.com.tw/book/jdc/?dis=list&page=1"


@pytest.mark.parametrize("sort", ["pu_desc", "pu_asc", "pr_desc", "pr_asc"])
def test_non_default_sort_keys_are_kept_in_the_canonical_form(sort):
    assert canonical_list_url(f"{BASE}&sort={sort}") == f"{BASE}&sort={sort}"


def test_an_unknown_sort_key_is_still_rejected_after_the_default_change():
    assert canonical_list_url(f"{BASE}&sort=sa_asc") is None
    assert canonical_list_url(f"{BASE}&sort=") is None
