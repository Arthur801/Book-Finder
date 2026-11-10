"""Offline contract checks for the Eslite (誠品) JSON fixtures (E0; see tests/fixtures/eslite/README.md).

Expected values were read from the fixtures themselves and frozen in crawler/docs/backlog.md
("CB-08 來源契約（E0 凍結）"). There is no Eslite parser yet, so these tests parse the
raw API bodies with json; they document what the future parser must follow.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eslite"
README = FIXTURE_DIR / "README.md"

LIST_TOP_LEVEL_KEYS = {"total", "page_no", "page_size", "products"}
CARD_REQUIRED_KEYS = {
    "guid",
    "name",
    "description",
    "image_url",
    "button_status",
    "manufacturer_sn",
    "manufacturer",
    "manufacturer_date",
    "is_book",
    "is_ebook",
    "is_age_restricted",
    "has_trial",
    "category_ids",
    "brand",
    "author",
    "compiler",
    "translator",
    "painter",
}
GUID_PATTERN = re.compile(r"^[0-9]{16,23}$")
MANUFACTURER_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00\.000\+08:00$")
PRODUCT_NOT_FOUND = {"message": "Product not found", "code": "404"}

# (file, total, page_no, page_size, len(products))
LIST_PAGES = [
    ("list_101_p1.json", 188, 1, 40, 40),
    ("list_34_p1.json", 1333, 1, 40, 40),
    ("list_101_p6.json", 188, 6, 40, 0),  # page beyond the last: legal empty page
    ("list_9999999_p1.json", 0, 1, 40, 0),  # category that does not exist
    ("list_28_p1.json", 0, 1, 40, 0),  # level-2 category lists nothing
]
NON_EMPTY_LIST_PAGES = [page[0] for page in LIST_PAGES if page[4] > 0]

# (list file, category id the cards must contain)
LIST_CATEGORY_MEMBERSHIP = [
    ("list_101_p1.json", 101),
    ("list_34_p1.json", 34),
]

# (guid, eslite_sn, isbn13, isbn10, ean, specs pages, specs language, description names, level3, translator)
DETAIL_PRODUCTS = [
    (
        "1001114412021700",
        "2680569866002",
        "9789577866004",
        "957786600X",
        "9789577866004",
        "272",
        "97:中/英/日 三國語言",
        ["內容簡介", "作者介紹"],
        101,
        "",
    ),
    (
        "1001124912682006780001",
        "2682006780001",
        "9789864415489",
        "9864415484",
        "9789864415489",
        "320",
        "1:中文/繁體",
        ["內容簡介", "產品目錄"],
        101,
        "",
    ),
    (
        "1001136502682294792007",
        "2682294792007",
        "9789888773701",
        "9888773704",
        "9789888773701",
        "1520",
        "1:中文/繁體",
        ["內容簡介"],
        101,
        "管燕紅/ 梁路/ 朱建中/ 等",
    ),
    (
        "10012016112683201069007",
        "2683201069007",
        "",
        None,
        "4719742187806",
        "784",
        "1:中文/繁體",
        ["內容簡介"],
        101,
        "",
    ),
    (
        "10012030392683263913003",
        "2683263913003",
        "9789863602408",
        None,
        "9789863602408",
        "320",
        "1:中文/繁體",
        ["內容簡介", "作者介紹"],
        34,
        "林水福",
    ),
]
DETAIL_GUIDS = [row[0] for row in DETAIL_PRODUCTS]
DETAIL_ROWS_WITH_SUFFIX_SN = [row for row in DETAIL_PRODUCTS if row[0] != "1001114412021700"]
ISBN_ROWS = [row for row in DETAIL_PRODUCTS if row[2]]


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _list_products(name: str) -> list[dict]:
    return _load(name)["products"]


def _detail(guid: str) -> dict:
    return _load(f"detail_{guid}.json")


def _ids_with_substring(obj: dict, needle: str) -> list[str]:
    return [key for key in obj if needle in key.lower()]


# ---------------------------------------------------------------------------
# List API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "total", "page_no", "page_size", "count"), LIST_PAGES)
def test_list_top_level_keys_and_scalar_types(name, total, page_no, page_size, count):
    body = _load(name)

    assert set(body) == LIST_TOP_LEVEL_KEYS
    assert isinstance(body["total"], int)
    assert isinstance(body["page_no"], int)
    assert isinstance(body["page_size"], int)
    assert isinstance(body["products"], list)


@pytest.mark.parametrize(("name", "total", "page_no", "page_size", "count"), LIST_PAGES)
def test_list_page_totals_and_card_count(name, total, page_no, page_size, count):
    body = _load(name)

    assert body["total"] == total
    assert body["page_no"] == page_no
    assert body["page_size"] == page_size
    assert len(body["products"]) == count


@pytest.mark.parametrize("name", NON_EMPTY_LIST_PAGES)
def test_card_has_required_keys(name):
    for card in _list_products(name):
        assert CARD_REQUIRED_KEYS <= set(card), card.get("guid")


@pytest.mark.parametrize("name", [page[0] for page in LIST_PAGES])
def test_cards_have_no_isbn_ean_or_eslite_sn_field(name):
    for card in _list_products(name):
        assert _ids_with_substring(card, "isbn") == []
        assert _ids_with_substring(card, "ean") == []
        assert "eslite_sn" not in card


@pytest.mark.parametrize("name", NON_EMPTY_LIST_PAGES)
def test_card_guid_is_digit_string_of_16_to_23_chars(name):
    for card in _list_products(name):
        assert isinstance(card["guid"], str)
        assert GUID_PATTERN.fullmatch(card["guid"]), card["guid"]


@pytest.mark.parametrize("name", NON_EMPTY_LIST_PAGES)
def test_card_guids_are_unique_within_page(name):
    guids = [card["guid"] for card in _list_products(name)]

    assert len(set(guids)) == len(guids)


@pytest.mark.parametrize("name", NON_EMPTY_LIST_PAGES)
def test_every_card_is_a_book_with_name_and_category_ids(name):
    for card in _list_products(name):
        assert card["is_book"] is True, card["guid"]
        assert isinstance(card["name"], str)
        assert card["name"].strip(), card["guid"]
        assert isinstance(card["category_ids"], list)
        assert card["category_ids"], card["guid"]
        assert all(isinstance(category_id, int) for category_id in card["category_ids"]), card["guid"]


def test_list_101_p1_guid_lengths_are_exactly_16_22_and_23():
    lengths = {len(card["guid"]) for card in _list_products("list_101_p1.json")}

    assert lengths == {16, 22, 23}


def test_list_34_p1_guids_are_all_23_digits():
    lengths = {len(card["guid"]) for card in _list_products("list_34_p1.json")}

    assert lengths == {23}


@pytest.mark.parametrize(("name", "category_id"), LIST_CATEGORY_MEMBERSHIP)
def test_every_card_belongs_to_listed_category(name, category_id):
    for card in _list_products(name):
        assert category_id in card["category_ids"], card["guid"]


# ---------------------------------------------------------------------------
# Detail API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guid", DETAIL_GUIDS)
def test_detail_product_guid_matches_filename(guid):
    assert _detail(guid)["product_guid"] == guid


@pytest.mark.parametrize(
    ("guid", "eslite_sn", "isbn13", "isbn10", "ean", "pages", "language", "descriptions", "level3", "translator"),
    DETAIL_PRODUCTS,
)
def test_detail_identifier_fields_match_table(guid, eslite_sn, isbn13, isbn10, ean, pages, language, descriptions, level3, translator):
    detail = _detail(guid)

    assert detail["eslite_sn"] == eslite_sn
    assert detail["isbn13"] == isbn13
    assert detail["isbn10"] == isbn10
    assert detail["ean"] == ean


@pytest.mark.parametrize(
    ("guid", "eslite_sn", "isbn13", "isbn10", "ean", "pages", "language", "descriptions", "level3", "translator"),
    DETAIL_PRODUCTS,
)
def test_detail_type_restriction_and_level(guid, eslite_sn, isbn13, isbn10, ean, pages, language, descriptions, level3, translator):
    detail = _detail(guid)

    assert detail["product_type"] == "book"
    assert detail["restricted"] is False
    assert detail["level3"] == level3
    assert level3 in detail["categories"]


@pytest.mark.parametrize(
    ("guid", "eslite_sn", "isbn13", "isbn10", "ean", "pages", "language", "descriptions", "level3", "translator"),
    DETAIL_PRODUCTS,
)
def test_detail_specifications_pages_language_and_rating(guid, eslite_sn, isbn13, isbn10, ean, pages, language, descriptions, level3, translator):
    specs = _detail(guid)["product_specifications"]

    assert isinstance(specs, list)
    assert all({"name", "tag_name", "tag"} <= set(spec) for spec in specs)
    by_tag = {spec["tag"]: spec for spec in specs}
    assert by_tag["pages"]["name"] == pages
    assert by_tag["language"]["name"] == language
    assert by_tag["rating"]["name"] == "N:無"


@pytest.mark.parametrize(
    ("guid", "eslite_sn", "isbn13", "isbn10", "ean", "pages", "language", "descriptions", "level3", "translator"),
    DETAIL_PRODUCTS,
)
def test_detail_description_names_in_order(guid, eslite_sn, isbn13, isbn10, ean, pages, language, descriptions, level3, translator):
    assert [item["name"] for item in _detail(guid)["descriptions"]] == descriptions


@pytest.mark.parametrize(
    ("guid", "eslite_sn", "isbn13", "isbn10", "ean", "pages", "language", "descriptions", "level3", "translator"),
    DETAIL_PRODUCTS,
)
def test_detail_translator_field_matches_table(guid, eslite_sn, isbn13, isbn10, ean, pages, language, descriptions, level3, translator):
    assert _detail(guid)["translator"] == translator


@pytest.mark.parametrize("guid", DETAIL_GUIDS)
def test_detail_product_name_is_non_empty_string(guid):
    name = _detail(guid)["product_name"]

    assert isinstance(name, str)
    assert name.strip()


@pytest.mark.parametrize("guid", DETAIL_GUIDS)
def test_detail_manufacturer_date_format(guid):
    assert MANUFACTURER_DATE_PATTERN.fullmatch(_detail(guid)["manufacturer_date"])


@pytest.mark.parametrize("guid", DETAIL_GUIDS)
def test_detail_default_photo_is_listed_with_eslite_original_path(guid):
    detail = _detail(guid)
    photos = detail["photos"]

    assert isinstance(photos, list)
    assert photos
    default = [photo for photo in photos if photo["id"] == detail["default_product_photo_id"]]
    assert len(default) == 1
    assert default[0]["original_path"].startswith("https://s.eslite.com/")


@pytest.mark.parametrize(("guid", "eslite_sn"), [(row[0], row[1]) for row in DETAIL_ROWS_WITH_SUFFIX_SN])
def test_eslite_sn_is_suffix_of_guid(guid, eslite_sn):
    assert guid.endswith(eslite_sn)


def test_guid_cannot_be_derived_from_eslite_sn():
    # 1001114412021700 is the exception: its eslite_sn is not a suffix of the guid.
    guid, eslite_sn = DETAIL_PRODUCTS[0][0], DETAIL_PRODUCTS[0][1]

    assert not guid.endswith(eslite_sn)


@pytest.mark.parametrize("row", ISBN_ROWS, ids=lambda row: row[0])
def test_isbn13_is_13_digits_starting_with_978_or_979(row):
    isbn13 = _detail(row[0])["isbn13"]

    assert re.fullmatch(r"\d{13}", isbn13), isbn13
    assert isbn13.startswith(("978", "979"))


def test_non_isbn_barcode_row_has_empty_isbn13_and_471_ean():
    detail = _detail("10012016112683201069007")

    assert detail["isbn13"] == ""
    assert detail["ean"].startswith("471")


def test_translated_novel_author_and_original_name():
    detail = _detail("10012030392683263913003")

    assert detail["author"] == "遠藤周作"
    assert detail["original_name"] == "ちんもく"


def test_detail_not_found_body_is_exact():
    assert _load("detail_10019999999999999999999.json") == PRODUCT_NOT_FOUND


# ---------------------------------------------------------------------------
# README consistency
# ---------------------------------------------------------------------------


def test_readme_exists():
    assert README.is_file()


def test_readme_mentions_every_fixture_filename():
    readme = README.read_text(encoding="utf-8")
    fixture_names = sorted(path.name for path in FIXTURE_DIR.glob("*.json"))

    assert fixture_names
    for name in fixture_names:
        assert name in readme, name
