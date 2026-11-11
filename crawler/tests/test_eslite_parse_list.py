"""Eslite list API parser (eslite.parse_list): fixtures are the source of truth; negatives are derived in code. Offline."""

import json
from pathlib import Path

import pytest

from eslite.models import EmptyCategory, EsliteParseError, ListedItem, ListPage
from eslite.parse_list import parse_list_json
from eslite.urls import canonical_list_url, product_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eslite"
WWW_101 = "https://www.eslite.com/category/3/101"


def _text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _body(name: str) -> dict:
    return json.loads(_text(name))


def _with(name: str, mutate, url: str = WWW_101) -> ListPage:
    body = _body(name)
    mutate(body)
    return parse_list_json(json.dumps(body, ensure_ascii=False), url)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def test_list_101_p1_yields_40_items_in_card_order_with_canonical_urls():
    page = parse_list_json(_text("list_101_p1.json"), WWW_101)
    cards = _body("list_101_p1.json")["products"]

    assert page.url == WWW_101
    assert page.empty is False
    assert page.total_count == 188
    assert page.total_pages == 5
    assert [item.external_id for item in page.items] == [card["guid"] for card in cards]
    assert len(page.items) == 40
    for item in page.items:
        assert isinstance(item, ListedItem)
        assert item.source_url == product_url(item.external_id)
        assert item.list_url == WWW_101


def test_list_34_p1_total_pages_is_rounded_up():
    page = parse_list_json(_text("list_34_p1.json"), "https://www.eslite.com/category/3/34")

    assert page.total_count == 1333
    assert page.total_pages == 34
    assert len(page.items) == 40


def test_list_101_p6_is_a_legal_empty_page_when_the_url_names_page_six():
    page = parse_list_json(_text("list_101_p6.json"), "https://www.eslite.com/category/3/101?page=6")

    assert page == ListPage(
        url="https://www.eslite.com/category/3/101?page=6",
        items=(),
        total_pages=5,
        total_count=188,
        empty=True,
    )


def test_list_9999999_p1_is_an_empty_category_failure():
    with pytest.raises(EmptyCategory):
        parse_list_json(_text("list_9999999_p1.json"), "https://www.eslite.com/category/3/9999999")


def test_list_28_p1_is_an_empty_category_failure_when_requested_as_a_list_page():
    with pytest.raises(EmptyCategory):
        parse_list_json(_text("list_28_p1.json"), "https://www.eslite.com/category/3/28")


def test_empty_category_is_a_parse_error_subclass():
    assert issubclass(EmptyCategory, EsliteParseError)
    assert issubclass(EsliteParseError, ValueError)


def test_the_page_one_url_is_the_canonical_no_page_url_in_the_result():
    page = parse_list_json(_text("list_101_p1.json"), WWW_101)

    assert page.url == canonical_list_url("https://www.eslite.com/category/3/101?page=1")


# ---------------------------------------------------------------------------
# Caller contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.eslite.com/category/3/101?page=1",  # not canonical: page 1 is omitted
        "https://www.eslite.com/category/2/101",
        "http://www.eslite.com/category/3/101",
        "https://athena.eslite.com/api/v1/categories/101/products",
    ],
)
def test_a_non_canonical_list_url_is_a_caller_error(url):
    with pytest.raises(ValueError):
        parse_list_json(_text("list_101_p1.json"), url)


def test_a_page_number_that_differs_from_the_url_is_a_parse_error():
    with pytest.raises(EsliteParseError, match="page_no"):
        parse_list_json(_text("list_101_p1.json"), "https://www.eslite.com/category/3/101?page=2")


# ---------------------------------------------------------------------------
# Structure errors (derived from the fixtures)
# ---------------------------------------------------------------------------


def test_invalid_json_is_a_parse_error():
    with pytest.raises(EsliteParseError):
        parse_list_json("{not json", WWW_101)


@pytest.mark.parametrize("text", ["[]", '"text"', "null", "42"])
def test_a_top_level_that_is_not_an_object_is_a_parse_error(text):
    with pytest.raises(EsliteParseError):
        parse_list_json(text, WWW_101)


@pytest.mark.parametrize("key", ["total", "page_no", "page_size", "products"])
def test_a_missing_top_level_key_is_a_parse_error(key):
    with pytest.raises(EsliteParseError):
        _with("list_101_p1.json", lambda body: body.pop(key))


@pytest.mark.parametrize("key", ["total", "page_no", "page_size"])
@pytest.mark.parametrize("value", ["188", 188.0, None, True, [188]])
def test_a_count_field_that_is_not_an_int_is_a_parse_error(key, value):
    def mutate(body):
        body[key] = value

    with pytest.raises(EsliteParseError):
        _with("list_101_p1.json", mutate)


@pytest.mark.parametrize("value", [{}, None, "[]", 0])
def test_products_that_is_not_a_list_is_a_parse_error(value):
    def mutate(body):
        body["products"] = value

    with pytest.raises(EsliteParseError):
        _with("list_101_p6.json", mutate, "https://www.eslite.com/category/3/101?page=6")


def test_a_negative_total_is_a_parse_error():
    def mutate(body):
        body["total"] = -1

    with pytest.raises(EsliteParseError):
        _with("list_101_p1.json", mutate)


def test_a_total_of_zero_is_an_empty_category_even_when_products_are_present():
    def mutate(body):
        body["total"] = 0

    with pytest.raises(EmptyCategory):
        _with("list_101_p1.json", mutate)


def test_total_above_zero_with_no_products_is_a_legal_empty_page_for_a_later_page():
    def mutate(body):
        body["page_no"] = 7

    page = _with("list_101_p6.json", mutate, "https://www.eslite.com/category/3/101?page=7")

    assert page.empty is True
    assert page.items == ()


@pytest.mark.parametrize(
    ("page_size", "expected"),
    [(40, 5), (20, 10), (41, 5), (1, 188), (0, None), (-40, None)],
)
def test_total_pages_is_ceil_of_total_over_page_size_or_none(page_size, expected):
    def mutate(body):
        body["page_size"] = page_size

    page = _with("list_101_p1.json", mutate)

    assert page.total_pages == expected


def test_total_pages_rounds_up_past_an_exact_multiple():
    def mutate(body):
        body["total"] = 41

    page = _with("list_101_p1.json", mutate)

    assert page.total_pages == 2


def test_a_card_that_is_not_an_object_is_a_parse_error():
    def mutate(body):
        body["products"][3] = "10012016112683201069007"

    with pytest.raises(EsliteParseError):
        _with("list_101_p1.json", mutate)


def test_a_card_without_guid_is_a_parse_error():
    def mutate(body):
        del body["products"][0]["guid"]

    with pytest.raises(EsliteParseError):
        _with("list_101_p1.json", mutate)


@pytest.mark.parametrize(
    "guid",
    [
        12345678901234567,  # int
        None,
        ["1001136502682294792007"],
        "123456789012345",  # 15 digits
        "100113650268229479200700",  # 24 digits
        "10011365026822947920a7",  # letter
        "1001136502682294792007\n",  # trailing newline
        " 1001136502682294792007",  # leading space
    ],
)
def test_a_card_guid_outside_the_pattern_is_a_parse_error(guid):
    def mutate(body):
        body["products"][0]["guid"] = guid

    with pytest.raises(EsliteParseError):
        _with("list_101_p1.json", mutate)


def test_guids_of_16_and_23_digits_are_accepted():
    def mutate(body):
        body["products"][0]["guid"] = "1001114412021700"
        body["products"][1]["guid"] = "10012030392683263913003"

    page = _with("list_101_p1.json", mutate)

    assert page.items[0].external_id == "1001114412021700"
    assert page.items[1].external_id == "10012030392683263913003"


def test_a_duplicate_guid_within_the_page_is_kept_once_and_the_first_wins():
    def mutate(body):
        first = body["products"][0]
        body["products"].insert(1, dict(first, name="second copy"))
        body["products"].append(dict(first))

    page = _with("list_101_p1.json", mutate)
    first_guid = _body("list_101_p1.json")["products"][0]["guid"]

    assert [item.external_id for item in page.items].count(first_guid) == 1
    assert page.items[0].external_id == first_guid
    assert len(page.items) == 40


def test_a_card_that_is_not_a_book_is_still_listed_because_is_book_is_not_used_to_filter():
    def mutate(body):
        body["products"][0]["is_book"] = False

    page = _with("list_101_p1.json", mutate)

    assert len(page.items) == 40
    assert page.items[0].external_id == _body("list_101_p1.json")["products"][0]["guid"]


# ---------------------------------------------------------------------------
# Age-restricted cards (is_age_restricted): skipped and counted, never items
# ---------------------------------------------------------------------------


def _set_restricted(body: dict, flags: list) -> None:
    for card, flag in zip(body["products"], flags, strict=False):
        card["is_age_restricted"] = flag


def test_a_card_flagged_restricted_is_not_an_item_and_is_counted():
    def mutate(body):
        _set_restricted(body, [True] + [False] * 39)

    page = _with("list_101_p1.json", mutate)
    cards = _body("list_101_p1.json")["products"]

    assert page.excluded_count == 1
    assert len(page.items) == 39
    assert cards[0]["guid"] not in [item.external_id for item in page.items]


def test_a_card_flagged_not_restricted_is_kept():
    def mutate(body):
        _set_restricted(body, [False] * 40)

    page = _with("list_101_p1.json", mutate)

    assert page.excluded_count == 0
    assert len(page.items) == 40


def test_a_card_without_the_flag_is_kept():
    page = parse_list_json(_text("list_101_p1.json"), WWW_101)

    assert page.excluded_count == 0
    assert len(page.items) == 40


@pytest.mark.parametrize("value", ["true", 1, 0, None, "false"])
def test_a_restricted_flag_that_is_not_a_bool_is_a_parse_error(value):
    def mutate(body):
        body["products"][2]["is_age_restricted"] = value

    with pytest.raises(EsliteParseError, match="product card 3 has an is_age_restricted that is not a boolean"):
        _with("list_101_p1.json", mutate)


def test_a_page_whose_every_card_is_restricted_has_no_items_and_is_not_empty():
    def mutate(body):
        _set_restricted(body, [True] * 40)

    page = _with("list_101_p1.json", mutate)

    assert page.items == ()
    assert page.empty is False
    assert page.excluded_count == 40
    assert page.total_count == 188


def test_restricted_cards_are_dropped_and_the_rest_keep_their_order():
    def mutate(body):
        _set_restricted(body, [False, True, False, True, False] + [False] * 35)

    page = _with("list_101_p1.json", mutate)
    cards = _body("list_101_p1.json")["products"]
    expected = [card["guid"] for index, card in enumerate(cards) if index not in (1, 3)]

    assert page.excluded_count == 2
    assert [item.external_id for item in page.items] == expected
