"""Offline contract checks for the Kingstone (金石堂) fixtures (E0; see tests/fixtures/kingstone/README.md).

Expected values were read from the fixtures themselves and frozen in crawler/docs/architecture.md
("金石堂（KINGSTONE）source contract"). There is no Kingstone parser yet, so these tests parse the
fixtures directly with BeautifulSoup and json; they document what the future parser must follow.
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kingstone"
README = FIXTURE_DIR / "README.md"

LIST_CARD_SELECTOR = "section#allProducts #displayCSS > .productGrid > .mod_prod_card[data-prodno]"
PRODUCT_NOT_FOUND_TITLE = "金石堂"

# (file, cards selected, input#totalPages value, 共計 total)
LIST_PAGES = [
    ("list_jdc_p1.html", 48, "93", "4455"),
    ("list_jdc_p1_pu_desc.html", 48, "93", "4455"),
    ("list_jdc_p93.html", 39, "93", "4455"),
    ("list_sj_p1.html", 6, "1", "6"),
]

# (sku from filename, isbn, 規格表 語言, 規格表 頁數, has .catalog)
DETAIL_PAGES = [
    ("2018630959191", "9786263589612", "中文繁體", "296", True),
    ("2018564008187", "9786267718537", "中文繁體", "768", False),
    ("2018741206573", "9789573344674", "中文繁體", "416", False),
    ("2028594173144", "4711664071805", "中文繁體", "1", False),
    ("2018250016458", "9781647840143", "中文簡體", "182", True),
    ("2018630844053", "9786263952232", "中文繁體", "332", True),
    ("2028870033469", "9786267791806", "中文繁體", "40", False),
]


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup(_read(name), "html.parser")


def _list_cards(soup: BeautifulSoup) -> list[Tag]:
    return soup.select(LIST_CARD_SELECTOR)


def _product_ld(soup: BeautifulSoup) -> dict | None:
    """Return the JSON-LD object whose @type contains "Product", or None."""
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.string or script.get_text())
        for item in data if isinstance(data, list) else [data]:
            types = item.get("@type")
            if types is not None and "Product" in (types if isinstance(types, list) else [types]):
                return item
    return None


def _spec_table(soup: BeautifulSoup) -> dict[str, str]:
    """Pair each li.table_th with the following li.table_td, in document order."""
    headers = [li.get_text(strip=True) for li in soup.select("li.table_th")]
    values = [li.get_text(strip=True) for li in soup.select("li.table_td")]
    assert len(headers) == len(values)
    return dict(zip(headers, values, strict=True))


def _basic_units(soup: BeautifulSoup, title: str) -> list[Tag]:
    return [li for li in soup.select("li.basicunit") if (t := li.select_one(".title_basic")) is not None and t.get_text(strip=True) == title]


def _author_links(soup: BeautifulSoup) -> list[str]:
    (unit,) = _basic_units(soup, "作者：")
    texts = [a.get_text(strip=True) for a in unit.select("a")]
    return [text for text in texts if text not in ("追蹤", "?")]


def _breadcrumb_names(soup: BeautifulSoup) -> list[str]:
    return [a.get_text(strip=True) for a in soup.select(".basic-category-breadcrumb a")]


def _subjects(soup: BeautifulSoup) -> list[str]:
    """Breadcrumb names, deduplicated in order, with the root 中文書 removed."""
    names: list[str] = []
    for name in _breadcrumb_names(soup):
        if name not in names:
            names.append(name)
    return [name for name in names if name != "中文書"]


# ---------------------------------------------------------------------------
# List pages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "cards", "total_pages", "total"), LIST_PAGES)
def test_list_page_selector_count_and_totals(name, cards, total_pages, total):
    soup = _soup(name)
    raw = _read(name)

    assert len(_list_cards(soup)) == cards
    assert soup.select_one("input#totalPages")["value"] == total_pages
    assert re.search(rf"共計\s*<span>\s*{total}\s*</span>\s*筆", raw)


@pytest.mark.parametrize("name", [page[0] for page in LIST_PAGES])
def test_list_page_has_product_grid_and_no_empty_category(name):
    soup = _soup(name)

    assert soup.select("#displayCSS > .productGrid")
    assert soup.select("#displayCSS > .emptyCategory") == []


@pytest.mark.parametrize("name", [page[0] for page in LIST_PAGES])
def test_card_prodno_is_13_digits_unique_and_matches_cover_link(name):
    cards = _list_cards(_soup(name))
    prodnos = [card["data-prodno"] for card in cards]

    assert all(re.fullmatch(r"\d{13}", prodno) for prodno in prodnos)
    assert len(set(prodnos)) == len(prodnos)
    for card in cards:
        href = card.select_one(".coverbox a")["href"]
        match = re.search(r"/basic/(\d+)/\?lid=", href)
        assert match is not None, href
        assert match.group(1) == card["data-prodno"]


def test_p93_card_count_follows_total_and_page_size():
    assert len(_list_cards(_soup("list_jdc_p93.html"))) == 4455 - 92 * 48


def test_empty_page_has_no_totals_and_no_product_grid():
    soup = _soup("list_jdc_p94.html")

    assert soup.select_one("input#totalPages") is None
    assert re.search(r"共計", _read("list_jdc_p94.html")) is None
    assert soup.select("#displayCSS > .productGrid") == []
    empty = soup.select_one("#displayCSS > .emptyCategory")
    assert empty is not None
    assert "此分類沒有相關商品唷！" in empty.get_text()


def test_empty_page_has_recommendation_cards_that_the_selector_excludes():
    soup = _soup("list_jdc_p94.html")

    recommendation_cards = soup.select("section#allProducts section.prodSlider .mod_prod_card[data-prodno]")
    assert len(recommendation_cards) == 24
    assert soup.select(".mod_prod_card[data-prodno]")
    assert _list_cards(soup) == []


@pytest.mark.parametrize("name", [page[0] for page in LIST_PAGES])
def test_list_cards_have_no_isbn_field(name):
    # Promotional text may contain ISBN-like digits (a free-reading PDF link), so only the label is checked.
    for card in _list_cards(_soup(name)):
        assert "ISBN" not in card.get_text(), card["data-prodno"]


def test_list_page_has_carousel_cards_outside_the_selector():
    soup = _soup("list_jdc_p1.html")

    assert len(soup.select(".mod_prod_card[data-prodno]")) > len(_list_cards(soup))


def test_pu_desc_list_is_ordered_by_publish_date_descending():
    dates = []
    for card in _list_cards(_soup("list_jdc_p1_pu_desc.html")):
        text = card.select_one(".pubdate").get_text()
        match = re.match(r"\d{4}/\d{2}/\d{2}", text)
        assert match is not None, text
        dates.append(match.group(0))

    assert len(dates) == 48
    assert all(newer >= older for newer, older in itertools.pairwise(dates))


# ---------------------------------------------------------------------------
# Detail pages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("sku", "isbn", "language", "pages", "has_catalog"), DETAIL_PAGES)
def test_detail_product_json_ld_identity(sku, isbn, language, pages, has_catalog):
    soup = _soup(f"detail_{sku}.html")
    product = _product_ld(soup)

    assert product is not None
    assert product["@type"] == ["Product", "Book"]
    assert product["sku"] == sku
    assert product["isbn"] == isbn
    assert product["gtin13"] == isbn
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", product["datePublished"])


@pytest.mark.parametrize(("sku", "isbn", "language", "pages", "has_catalog"), DETAIL_PAGES)
def test_detail_spec_table_language_pages_and_catalog(sku, isbn, language, pages, has_catalog):
    soup = _soup(f"detail_{sku}.html")
    spec = _spec_table(soup)

    assert spec["語言"] == language
    assert spec["頁數"] == pages
    assert (soup.select_one(".catalog") is not None) is has_catalog


@pytest.mark.parametrize(("sku", "isbn", "language", "pages", "has_catalog"), DETAIL_PAGES)
def test_detail_json_ld_in_language_is_zh_tw_even_for_simplified(sku, isbn, language, pages, has_catalog):
    product = _product_ld(_soup(f"detail_{sku}.html"))

    assert product["inLanguage"] == "zh-TW"


def test_simplified_book_spec_language_differs_from_json_ld_language():
    soup = _soup("detail_2018250016458.html")

    assert _spec_table(soup)["語言"] == "中文簡體"
    assert _product_ld(soup)["inLanguage"] == "zh-TW"


def test_publisher_name_has_trailing_spaces_and_strips_to_name():
    name = _product_ld(_soup("detail_2018630959191.html"))["publisher"]["name"]

    assert name != name.strip()
    assert name.strip() == "三采"


@pytest.mark.parametrize(
    ("sku", "expected"),
    [
        ("2018250016458", ["高覠罄", "(Gao Junqing)"]),
        ("2018741206573", ["卡蘿．克萊兒．柏克", "(Caro Claire Burke)"]),
        ("2018630844053", ["李秉樺、邱常婷、徐禎苓、張郅忻、陳育萱、陳顥仁", "奧崴尼．卡勒盛、楊富閔、葉淳之、廖振富、蕭詒徽、謝鑫佑"]),
        ("2028870033469", ["安娜．沃克", "(Anna Walker)", "審訂/張素惠"]),
        ("2018630959191", ["黃山料"]),
    ],
)
def test_author_links_exclude_follow_and_question_mark(sku, expected):
    assert _author_links(_soup(f"detail_{sku}.html")) == expected


@pytest.mark.parametrize(
    ("sku", "expected"),
    [
        ("2018630844053", "李秉樺、邱常婷、徐禎苓、張郅忻、陳育萱、陳顥仁"),
        ("2028870033469", "安娜．沃克"),
    ],
)
def test_json_ld_author_is_only_the_first_author_link(sku, expected):
    author = _product_ld(_soup(f"detail_{sku}.html"))["author"]

    assert isinstance(author, dict)
    assert author["name"] == expected


@pytest.mark.parametrize(
    ("sku", "translator"),
    [
        ("2018741206573", "劉曉樺"),
        ("2028870033469", "黃筱茵"),
    ],
)
def test_translator_is_plain_text_without_link(sku, translator):
    (unit,) = _basic_units(_soup(f"detail_{sku}.html"), "譯者：")

    assert unit.select("a") == []
    assert unit.get_text(strip=True).removeprefix("譯者：") == translator


@pytest.mark.parametrize("sku", ["2018630959191", "2018564008187", "2028594173144", "2018250016458", "2018630844053"])
def test_books_without_translator_row(sku):
    assert _basic_units(_soup(f"detail_{sku}.html"), "譯者：") == []


@pytest.mark.parametrize("sku", [page[0] for page in DETAIL_PAGES])
def test_breadcrumb_names_are_first_half_repeated_twice(sku):
    names = _breadcrumb_names(_soup(f"detail_{sku}.html"))
    half = len(names) // 2

    assert names
    assert len(names) % 2 == 0
    assert names == names[:half] * 2


@pytest.mark.parametrize(
    ("sku", "expected"),
    [
        ("2028870033469", ["童書/青少年", "繪本", "同儕相處"]),
        ("2018630959191", ["文學", "現代華文創作", "現代小說"]),
    ],
)
def test_subjects_are_breadcrumb_names_deduplicated_in_order_without_root(sku, expected):
    assert _subjects(_soup(f"detail_{sku}.html")) == expected


@pytest.mark.parametrize("sku", [page[0] for page in DETAIL_PAGES])
def test_detail_json_ld_name_is_non_empty_string(sku):
    name = _product_ld(_soup(f"detail_{sku}.html"))["name"]

    assert isinstance(name, str)
    assert name.strip()


def test_detail_json_ld_name_for_2018630959191():
    assert _product_ld(_soup("detail_2018630959191.html"))["name"] == "我的黑道姑姑：教我的99件事"


@pytest.mark.parametrize("sku", [page[0] for page in DETAIL_PAGES])
def test_detail_json_ld_image_is_non_empty_list_of_kingstone_assets(sku):
    image = _product_ld(_soup(f"detail_{sku}.html"))["image"]

    assert isinstance(image, list)
    assert image
    assert image[0].startswith("https://assets.kingstone.com.tw/")


@pytest.mark.parametrize("sku", [page[0] for page in DETAIL_PAGES])
def test_detail_spec_table_rating_is_general(sku):
    assert _spec_table(_soup(f"detail_{sku}.html"))["分級"] == "普通級"


def test_soft_404_has_only_site_title_and_no_product_json_ld():
    soup = _soup("detail_2099999999999.html")

    assert soup.title is not None
    assert soup.title.get_text().strip() == PRODUCT_NOT_FOUND_TITLE
    assert _product_ld(soup) is None


# ---------------------------------------------------------------------------
# README consistency
# ---------------------------------------------------------------------------


def test_every_html_fixture_is_listed_in_readme():
    readme = README.read_text(encoding="utf-8")
    html_files = sorted(path.name for path in FIXTURE_DIR.glob("*.html"))

    assert html_files
    for name in html_files:
        assert f"`{name}`" in readme, name


def test_every_listed_list_or_detail_fixture_exists():
    readme = README.read_text(encoding="utf-8")
    named = set(re.findall(r"`((?:list|detail)_[^`]*\.html)`", readme))

    assert named
    for name in named:
        assert (FIXTURE_DIR / name).is_file(), name
