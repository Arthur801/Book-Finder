"""Eslite detail API parser (eslite.parse_detail): fixtures are the source of truth; negatives are derived in code. Offline."""

import json
from pathlib import Path

import pytest

from catalog_core.models import BookDraft, Contributor, ContributorRole, Identifier, IdentifierType, PublishedDatePrecision
from eslite.models import EsliteParseError, ProductNotFound, RestrictedProduct
from eslite.parse_detail import parse_detail_json
from eslite.urls import product_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eslite"
NOT_FOUND_GUID = "10019999999999999999999"

G_DICT = "10012016112683201069007"  # 字典: no ISBN, 471 barcode, 吳美玉/ 編, painter
G_NAME16 = "1001114412021700"  # 16-digit guid, 謝敏華/ Favre, David, 97: language
G_TOC = "1001124912682006780001"  # 產品目錄
G_TRANS = "1001136502682294792007"  # translator 管燕紅/ 梁路/ 朱建中/ 等
G_NOVEL = "10012030392683263913003"  # 遠藤周作 / 林水福
ALL_GUIDS = [G_DICT, G_NAME16, G_TOC, G_TRANS, G_NOVEL]


def _text(guid: str) -> str:
    return (FIXTURE_DIR / f"detail_{guid}.json").read_text(encoding="utf-8")


def _body(guid: str) -> dict:
    return json.loads(_text(guid))


def _parse(guid: str, body: dict) -> BookDraft:
    return parse_detail_json(json.dumps(body, ensure_ascii=False), guid)


def _mutated(guid: str, mutate) -> BookDraft:
    body = _body(guid)
    mutate(body)
    return _parse(guid, body)


def _contrib(*pairs) -> tuple[Contributor, ...]:
    return tuple(Contributor(order=i, name=name, role=role) for i, (name, role) in enumerate(pairs, start=1))


A, E, T, O, I = (
    ContributorRole.AUTHOR,
    ContributorRole.EDITOR,
    ContributorRole.TRANSLATOR,
    ContributorRole.OTHER,
    ContributorRole.ILLUSTRATOR,
)


def _isbn(value: str) -> Identifier:
    return Identifier(IdentifierType.ISBN, value)


# ---------------------------------------------------------------------------
# Fixture: identity, publisher, date, thumbnail, subjects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guid", ALL_GUIDS)
def test_every_fixture_maps_identity_title_publisher_date_and_source_url(guid):
    draft = parse_detail_json(_text(guid), guid)
    body = _body(guid)

    assert isinstance(draft, BookDraft)
    assert draft.external_id == guid
    assert draft.source_url == product_url(guid)
    assert draft.title == body["product_name"]
    assert draft.publisher == body["manufacturer"]
    assert draft.published_date is not None
    assert draft.published_date_precision is PublishedDatePrecision.DAY
    assert draft.published_date.isoformat() == body["manufacturer_date"][:10]


def test_the_title_is_the_product_name_without_the_sub_title():
    body = _body(G_NAME16)
    body["sub_title"] = "副標題"

    draft = _parse(G_NAME16, body)

    assert draft.title == "日英中生活用語字典"


def test_the_fixture_thumbnail_is_the_default_photo_original_path():
    draft = parse_detail_json(_text(G_NOVEL), G_NOVEL)
    body = _body(G_NOVEL)
    default = next(photo for photo in body["photos"] if photo["id"] == body["default_product_photo_id"])

    assert draft.thumbnail_url == default["original_path"]
    assert draft.thumbnail_url.startswith("https://")


@pytest.mark.parametrize("guid", ALL_GUIDS)
def test_subjects_are_the_level3_name_only(guid):
    assert parse_detail_json(_text(guid), guid).subjects == (_body(guid)["level3_name"],)


def test_the_novel_is_in_the_japanese_literature_subject():
    assert parse_detail_json(_text(G_NOVEL), G_NOVEL).subjects == ("日本文學",)


# ---------------------------------------------------------------------------
# Fixture: language, page count, description, table of contents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("guid", "language", "pages"),
    [
        (G_DICT, "zh-TW", 784),
        (G_NAME16, None, 272),  # 97:中/英/日 三國語言 is not mapped
        (G_TOC, "zh-TW", 320),
        (G_TRANS, "zh-TW", 1520),
        (G_NOVEL, "zh-TW", 320),
    ],
)
def test_language_and_page_count_follow_the_product_specifications(guid, language, pages):
    draft = parse_detail_json(_text(guid), guid)

    assert draft.language == language
    assert draft.page_count == pages


def test_the_description_is_the_内容簡介_text_with_line_breaks_and_no_html():
    draft = parse_detail_json(_text(G_DICT), G_DICT)

    assert draft.description is not None
    assert "<" not in draft.description
    assert draft.description.startswith("本字典依教育部頒布")


def test_the_table_of_contents_is_the_產品目錄_entry():
    draft = parse_detail_json(_text(G_TOC), G_TOC)

    assert draft.table_of_contents is not None
    assert "\n" in draft.table_of_contents
    assert "<" not in draft.table_of_contents


@pytest.mark.parametrize("guid", [G_DICT, G_TRANS, G_NOVEL, G_NAME16])
def test_a_book_without_a_產品目錄_entry_has_no_table_of_contents(guid):
    assert parse_detail_json(_text(guid), guid).table_of_contents is None


def test_the_table_of_contents_falls_back_to_the_目錄_entry_name():
    def mutate(body):
        for entry in body["descriptions"]:
            if entry["name"] == "產品目錄":
                entry["name"] = "目錄"

    draft = _mutated(G_TOC, mutate)

    assert draft.table_of_contents is not None


def test_the_description_falls_back_to_the_short_description_when_内容簡介_is_missing():
    def mutate(body):
        body["descriptions"] = [entry for entry in body["descriptions"] if entry["name"] != "內容簡介"]

    draft = _mutated(G_NAME16, mutate)

    assert draft.description == " ".join(_body(G_NAME16)["short_description"].split())


def test_the_description_is_none_when_both_the_entry_and_the_short_description_are_missing():
    def mutate(body):
        body["descriptions"] = []
        body["short_description"] = None

    assert _mutated(G_TRANS, mutate).description is None


def test_a_blank_内容簡介_falls_back_to_the_short_description():
    def mutate(body):
        for entry in body["descriptions"]:
            if entry["name"] == "內容簡介":
                entry["description"] = "  "
        body["short_description"] = "簡短介紹"

    assert _mutated(G_TRANS, mutate).description == "簡短介紹"


def test_html_block_and_br_tags_become_line_breaks():
    def mutate(body):
        for entry in body["descriptions"]:
            if entry["name"] == "內容簡介":
                entry["description"] = "<div>第一行<br/>第二行</div><p>第三行</p>"

    # Adjacent block boundaries (</div><p>) give one blank line between the blocks, as text_with_line_breaks does.
    assert _mutated(G_TRANS, mutate).description == "第一行\n第二行\n\n第三行"


# ---------------------------------------------------------------------------
# Fixture: identifiers
# ---------------------------------------------------------------------------


def test_a_book_with_isbn13_and_isbn10_yields_both_in_that_order():
    assert parse_detail_json(_text(G_TRANS), G_TRANS).identifiers == (
        _isbn("9789888773701"),
        _isbn("9888773704"),
    )


def test_a_book_with_isbn13_only_yields_one_identifier():
    assert parse_detail_json(_text(G_NOVEL), G_NOVEL).identifiers == (_isbn("9789863602408"),)


def test_a_dictionary_with_empty_isbn13_and_a_471_barcode_has_no_identifiers():
    assert parse_detail_json(_text(G_DICT), G_DICT).identifiers == ()


def test_a_471_barcode_in_ean_is_never_an_isbn_even_when_isbn13_is_empty():
    draft = parse_detail_json(_text(G_DICT), G_DICT)

    assert all(identifier.identifier_value != "4719742187806" for identifier in draft.identifiers)


def test_ean_is_used_when_isbn13_is_empty_and_it_is_a_978_or_979_code():
    def mutate(body):
        body["isbn13"] = ""
        body["ean"] = "9789577866004"

    assert _mutated(G_DICT, mutate).identifiers == (_isbn("9789577866004"),)


def test_ean_is_not_used_when_isbn13_is_present_even_if_ean_differs():
    def mutate(body):
        body["ean"] = "9789999999999"

    assert _mutated(G_TRANS, mutate).identifiers == (_isbn("9789888773701"), _isbn("9888773704"))


def test_a_978_ean_with_wrong_length_is_not_an_isbn():
    def mutate(body):
        body["isbn13"] = None
        body["ean"] = "97895778660"

    assert _mutated(G_DICT, mutate).identifiers == ()


def test_identifiers_are_normalized_through_catalog_core_and_deduplicated():
    def mutate(body):
        body["isbn13"] = "978-988-8773-70-1"
        body["isbn10"] = "9888773704"
        body["ean"] = None

    assert _mutated(G_TRANS, mutate).identifiers == (_isbn("9789888773701"), _isbn("9888773704"))


def test_an_isbn10_equal_to_isbn13_is_kept_once():
    def mutate(body):
        body["isbn10"] = "9789888773701"

    assert _mutated(G_TRANS, mutate).identifiers == (_isbn("9789888773701"),)


def test_an_isbn10_with_lowercase_x_is_uppercased():
    def mutate(body):
        body["isbn13"] = ""
        body["ean"] = "4719742187806"  # not an ISBN, so the isbn10 is the only identifier
        body["isbn10"] = "957786600x"

    assert _mutated(G_NAME16, mutate).identifiers == (_isbn("957786600X"),)


# ---------------------------------------------------------------------------
# Fixture: contributors
# ---------------------------------------------------------------------------


def test_the_dictionary_author_role_word_makes_the_name_an_editor_and_the_painter_an_illustrator():
    draft = parse_detail_json(_text(G_DICT), G_DICT)

    assert draft.contributors == _contrib(("吳美玉", E), ("世一文化", I))


def test_slash_separated_authors_are_two_authors_including_the_western_name():
    draft = parse_detail_json(_text(G_NAME16), G_NAME16)

    assert draft.contributors == _contrib(("謝敏華", A), ("Favre, David", A))


def test_a_multi_translator_field_with_trailing_等_yields_three_translators_after_the_author():
    draft = parse_detail_json(_text(G_TRANS), G_TRANS)

    assert draft.contributors == _contrib(
        ("培生教育出版亞洲有限公司", A),
        ("管燕紅", T),
        ("梁路", T),
        ("朱建中", T),
    )


def test_the_novel_has_an_author_and_a_translator():
    draft = parse_detail_json(_text(G_NOVEL), G_NOVEL)

    assert draft.contributors == _contrib(("遠藤周作", A), ("林水福", T))


def test_contributor_order_is_one_based_and_gap_free():
    draft = parse_detail_json(_text(G_TRANS), G_TRANS)

    assert [c.order for c in draft.contributors] == [1, 2, 3, 4]


def test_a_book_without_contributor_fields_has_no_contributors():
    def mutate(body):
        for key in ("author", "translator", "compiler", "painter"):
            body[key] = ""

    assert _mutated(G_DICT, mutate).contributors == ()


def test_null_contributor_fields_contribute_nothing():
    def mutate(body):
        body["author"] = None
        body["translator"] = None
        body["compiler"] = None
        body["painter"] = None

    assert _mutated(G_DICT, mutate).contributors == ()


def test_the_compiler_field_is_an_editor_and_splits_on_slash():
    def mutate(body):
        body["author"] = ""
        body["compiler"] = "甲/ 乙"

    assert _mutated(G_DICT, mutate).contributors == _contrib(("甲", E), ("乙", E), ("世一文化", I))


def test_the_painter_field_is_an_illustrator():
    def mutate(body):
        body["painter"] = "丙"

    assert _mutated(G_NOVEL, mutate).contributors == _contrib(("遠藤周作", A), ("林水福", T), ("丙", I))


def test_the_contributor_order_is_author_then_translator_then_compiler_then_painter():
    def mutate(body):
        body["author"] = "甲"
        body["translator"] = "乙"
        body["compiler"] = "丙"
        body["painter"] = "丁"

    assert _mutated(G_NOVEL, mutate).contributors == _contrib(("甲", A), ("乙", T), ("丙", E), ("丁", I))


@pytest.mark.parametrize(
    ("author", "expected"),
    [
        ("甲/ 編", [("甲", E)]),  # role word after the name
        ("甲/乙/編", [("甲", E), ("乙", E)]),  # role word covers the contiguous names before it
        ("甲/策劃", [("甲", O)]),  # OTHER vocabulary
        ("甲/總策劃", [("甲", O)]),
        ("甲/編著", [("甲", E)]),
        ("甲/編者", [("甲", E)]),
        ("甲/主編", [("甲", E)]),
        ("甲/編/乙", [("甲", E), ("乙", A)]),  # names after a role word stay AUTHOR
        ("甲;乙/編", [("甲", A), ("乙", E)]),  # a role word applies inside its own group only
        ("甲/乙", [("甲", A), ("乙", A)]),
        ("甲/甲", [("甲", A)]),  # exact duplicate (name, role) kept once
    ],
)
def test_role_words_set_the_role_of_the_names_before_them_in_their_group(author, expected):
    def mutate(body):
        body["author"] = author
        body["translator"] = ""
        body["painter"] = ""

    draft = _mutated(G_DICT, mutate)

    assert draft.contributors == _contrib(*expected)


def test_a_role_word_with_no_name_before_it_is_a_parse_error():
    def mutate(body):
        body["author"] = "編"

    with pytest.raises(EsliteParseError):
        _mutated(G_DICT, mutate)


def test_a_role_word_after_a_separator_with_no_name_is_a_parse_error():
    def mutate(body):
        body["author"] = "甲;編"

    with pytest.raises(EsliteParseError):
        _mutated(G_DICT, mutate)


def test_the_same_name_as_author_and_translator_is_kept_twice_with_different_roles():
    def mutate(body):
        body["author"] = "甲"
        body["translator"] = "甲"

    assert _mutated(G_NOVEL, mutate).contributors == _contrib(("甲", A), ("甲", T))


def test_a_bare_等_piece_is_never_a_name():
    def mutate(body):
        body["author"] = "甲/等"

    assert _mutated(G_NOVEL, mutate).contributors[0] == Contributor(order=1, name="甲", role=A)
    assert all(c.name != "等" for c in _mutated(G_NOVEL, mutate).contributors)


@pytest.mark.parametrize("field", ["author", "translator", "compiler", "painter"])
@pytest.mark.parametrize("value", [123, ["甲"], {"name": "甲"}, True])
def test_a_contributor_field_of_the_wrong_json_type_is_a_parse_error(field, value):
    def mutate(body):
        body[field] = value

    with pytest.raises(EsliteParseError):
        _mutated(G_DICT, mutate)


# ---------------------------------------------------------------------------
# Fixture: 404 and structure errors
# ---------------------------------------------------------------------------


def test_the_404_body_is_product_not_found():
    with pytest.raises(ProductNotFound):
        parse_detail_json(_text(NOT_FOUND_GUID), NOT_FOUND_GUID)


def test_product_not_found_is_not_a_parse_error():
    assert not issubclass(ProductNotFound, EsliteParseError)


def test_a_different_error_body_without_product_guid_is_a_parse_error():
    with pytest.raises(EsliteParseError):
        parse_detail_json('{"message": "Internal error", "code": "500"}', G_TRANS)


def test_a_404_message_with_a_product_guid_is_parsed_as_a_product_not_as_not_found():
    body = {"message": "Product not found", "code": "404", "product_guid": G_TRANS}

    with pytest.raises(EsliteParseError):
        _parse(G_TRANS, body)


@pytest.mark.parametrize("text", ["{not json", ""])
def test_invalid_json_is_a_parse_error(text):
    with pytest.raises(EsliteParseError):
        parse_detail_json(text, G_TRANS)


@pytest.mark.parametrize("text", ["[]", '"text"', "null", "7"])
def test_a_top_level_that_is_not_an_object_is_a_parse_error(text):
    with pytest.raises(EsliteParseError):
        parse_detail_json(text, G_TRANS)


def test_a_missing_product_guid_is_a_parse_error():
    def mutate(body):
        del body["product_guid"]

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


@pytest.mark.parametrize("value", [None, 1001136502682294792007, "1001136502682294792008"])
def test_a_product_guid_that_is_not_the_requested_guid_is_a_parse_error(value):
    def mutate(body):
        body["product_guid"] = value

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


@pytest.mark.parametrize("name", [None, "", "   ", 5])
def test_a_missing_blank_or_non_string_product_name_is_a_parse_error(name):
    def mutate(body):
        body["product_name"] = name

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


def test_a_missing_product_name_is_a_parse_error():
    def mutate(body):
        del body["product_name"]

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


def test_a_restricted_product_raises_restricted_product_and_is_not_a_parse_error():
    def mutate(body):
        body["restricted"] = True

    with pytest.raises(RestrictedProduct) as info:
        _mutated(G_TRANS, mutate)
    assert not isinstance(info.value, EsliteParseError)
    assert not isinstance(info.value, ProductNotFound)


@pytest.mark.parametrize("value", ["false", 0, None])
def test_a_restricted_flag_that_is_not_a_bool_is_a_parse_error(value):
    def mutate(body):
        body["restricted"] = value

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


@pytest.mark.parametrize("field", ["descriptions", "photos", "product_specifications"])
@pytest.mark.parametrize("value", ["text", {}, 3])
def test_a_list_field_of_the_wrong_type_is_a_parse_error(field, value):
    def mutate(body):
        body[field] = value

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


def test_a_description_entry_that_is_not_an_object_is_a_parse_error():
    def mutate(body):
        body["descriptions"].append("內容簡介")

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


@pytest.mark.parametrize("field", ["manufacturer", "manufacturer_date", "short_description", "isbn13", "isbn10", "ean"])
@pytest.mark.parametrize("value", [123, ["x"], True])
def test_a_text_field_of_the_wrong_json_type_is_a_parse_error(field, value):
    def mutate(body):
        body[field] = value

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


@pytest.mark.parametrize("field", ["manufacturer", "manufacturer_date", "short_description", "isbn13", "isbn10", "ean", "level3_name"])
def test_a_null_optional_text_field_becomes_none_not_an_error(field):
    def mutate(body):
        body[field] = None

    draft = _mutated(G_TRANS, mutate)

    if field == "manufacturer":
        assert draft.publisher is None
    if field == "manufacturer_date":
        assert draft.published_date is None
    if field == "level3_name":
        assert draft.subjects == ()


def test_a_non_string_guid_argument_is_a_value_error():
    with pytest.raises(ValueError):
        parse_detail_json(_text(G_TRANS), "abc")


# ---------------------------------------------------------------------------
# Derived rules: published date, language, page count, thumbnail, subjects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["2023-09-30", "2023-09-30T00:00:00.000Z", "2023-02-30T00:00:00.000+08:00", "", "not a date"])
def test_a_manufacturer_date_of_any_other_shape_or_an_invalid_day_has_no_date_and_no_precision(raw):
    draft = _mutated(G_TRANS, lambda body: body.update(manufacturer_date=raw))

    assert draft.published_date is None
    assert draft.published_date_precision is None


def test_the_manufacturer_date_pattern_yields_a_day_precision_date():
    draft = _mutated(G_TRANS, lambda body: body.update(manufacturer_date="2019-01-05T00:00:00.000+08:00"))

    assert draft.published_date.isoformat() == "2019-01-05"
    assert draft.published_date_precision is PublishedDatePrecision.DAY


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("1:中文/繁體", "zh-TW"),
        ("1:中文/簡體", "zh-CN"),
        ("中文/繁體", "zh-TW"),
        ("97:中/英/日 三國語言", None),
        ("2:英文", None),
        ("", None),
    ],
)
def test_the_language_tag_maps_only_the_two_chinese_values(language, expected):
    def mutate(body):
        for spec in body["product_specifications"]:
            if spec["tag"] == "language":
                spec["name"] = language

    assert _mutated(G_TRANS, mutate).language == expected


def test_a_book_without_a_language_tag_has_no_language():
    def mutate(body):
        body["product_specifications"] = [spec for spec in body["product_specifications"] if spec["tag"] != "language"]

    assert _mutated(G_TRANS, mutate).language is None


@pytest.mark.parametrize(("pages", "expected"), [("0", None), ("abc", None), ("", None), ("320", 320)])
def test_page_count_is_a_positive_integer_or_none(pages, expected):
    def mutate(body):
        for spec in body["product_specifications"]:
            if spec["tag"] == "pages":
                spec["name"] = pages

    assert _mutated(G_TRANS, mutate).page_count == expected


def test_a_specification_entry_that_is_not_an_object_is_a_parse_error():
    def mutate(body):
        body["product_specifications"].append("pages")

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


def test_the_thumbnail_falls_back_to_the_first_photo_when_the_default_id_is_absent():
    def mutate(body):
        body["default_product_photo_id"] = 1

    draft = _mutated(G_NOVEL, mutate)

    assert draft.thumbnail_url == _body(G_NOVEL)["photos"][0]["original_path"]


def test_a_thumbnail_that_is_not_https_is_none_and_does_not_fall_back():
    def mutate(body):
        body["photos"][0]["original_path"] = "http://s.eslite.com/x.jpg"

    assert _mutated(G_TRANS, mutate).thumbnail_url is None


def test_a_book_without_photos_has_no_thumbnail():
    assert _mutated(G_TRANS, lambda body: body.update(photos=[])).thumbnail_url is None


def test_a_photo_that_is_not_an_object_is_a_parse_error():
    def mutate(body):
        body["photos"] = ["https://s.eslite.com/x.jpg"]

    with pytest.raises(EsliteParseError):
        _mutated(G_TRANS, mutate)


def test_a_blank_level3_name_gives_no_subjects():
    assert _mutated(G_TRANS, lambda body: body.update(level3_name="  ")).subjects == ()


def test_level2_names_are_never_subjects():
    draft = _mutated(G_TRANS, lambda body: body.update(level2_name="📌文學館79折起", level3_name="字典"))

    assert draft.subjects == ("字典",)


def test_a_draft_is_a_book_draft_with_no_subtitle_field():
    draft = parse_detail_json(_text(G_TRANS), G_TRANS)

    assert not hasattr(draft, "subtitle")
