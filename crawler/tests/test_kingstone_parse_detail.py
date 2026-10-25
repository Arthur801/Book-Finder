"""Kingstone product detail parser (CB-07 詳細頁解析), offline: real fixtures plus synthetic negative cases."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from catalog_core.models import (
    BookDraft,
    Contributor,
    ContributorRole,
    Identifier,
    IdentifierType,
    PublishedDatePrecision,
)
from kingstone.models import KingstoneParseError, ProductNotFound
from kingstone.parse_detail import parse_detail_html
from kingstone.urls import detail_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "kingstone"
AUTHOR = ContributorRole.AUTHOR
TRANSLATOR = ContributorRole.TRANSLATOR
OTHER = ContributorRole.OTHER


def _fixture(km_code: str) -> str:
    return (FIXTURE_DIR / f"detail_{km_code}.html").read_text(encoding="utf-8")


def _parse_fixture(km_code: str) -> BookDraft:
    return parse_detail_html(_fixture(km_code), detail_url(km_code))


def _isbn(value: str) -> tuple[Identifier, ...]:
    return (Identifier(IdentifierType.ISBN, value),)


# ---------------------------------------------------------------------------
# The seven real fixtures: every field asserted against the observed value
# ---------------------------------------------------------------------------

REAL_BOOKS = [
    pytest.param(
        "2018630959191",
        {
            "title": "我的黑道姑姑：教我的99件事",
            "isbn": "9786263589612",
            "publisher": "三采",
            "published_date": date(2026, 5, 29),
            "language": "zh-TW",
            "page_count": 296,
            "contributors": (Contributor(1, "黃山料", AUTHOR),),
            "subjects": ("文學", "現代華文創作", "現代小說"),
            "description_start": "【網書大標】\n\n世界上你最喜歡的人是誰？",
            "toc_start": "第一部 我看見的姑姑\n\n故事01",
        },
        id="general-with-toc",
    ),
    pytest.param(
        "2018564008187",
        {
            "title": "雨中的卡米洛（全二冊）",
            "isbn": "9786267718537",
            "publisher": "大旗",
            "published_date": date(2026, 8, 1),
            "language": "zh-TW",
            "page_count": 768,
            "contributors": (Contributor(1, "韋恆安", AUTHOR),),
            "subjects": ("文學", "現代華文創作", "現代小說"),
            "description_start": "【內容簡介】你們就是在等這場雨嗎？",
            "toc_start": None,
        },
        id="multi-volume-set",
    ),
    pytest.param(
        "2018741206573",
        {
            "title": "昨年（昨年映像經典版）：讓安‧海瑟薇一口氣讀到天黑的小說！年度話題神作，席捲歐美文壇！",
            "isbn": "9789573344674",
            "publisher": "皇冠文化",
            "published_date": date(2026, 9, 4),
            "language": "zh-TW",
            "page_count": 416,
            "contributors": (
                Contributor(1, "卡蘿．克萊兒．柏克", AUTHOR),
                Contributor(2, "劉曉樺", TRANSLATOR),
            ),
            "subjects": ("文學", "現代翻譯文學", "美國現代文學"),
            "description_start": "讓安‧海瑟薇一口氣讀到天黑的小說！",
            "toc_start": None,
        },
        id="translation",
    ),
    pytest.param(
        "2028594173144",
        {
            "title": "FOOD超人-萬聖節創意派對",
            "isbn": "4711664071805",
            "publisher": "風車",
            "published_date": date(2026, 10, 16),
            "language": "zh-TW",
            "page_count": 1,
            "contributors": (Contributor(1, "風車編輯群", AUTHOR),),
            "subjects": ("童書/青少年", "學習玩教具", "黏土/動力沙"),
            "description_start": "搗蛋玩創意，萬聖節更有趣！",
            "toc_start": None,
        },
        id="non-book-product-with-general-barcode",
    ),
    pytest.param(
        "2018250016458",
        {
            "title": "昨夜，你在我的夢裡（簡體中文版）",
            "isbn": "9781647840143",
            "publisher": "漢世紀數位",
            "published_date": date(2020, 5, 1),
            "language": "zh-CN",
            "page_count": 182,
            "contributors": (Contributor(1, "高覠罄", AUTHOR),),
            "subjects": ("文學", "簡體版-文學小說", "中文現代"),
            "description_start": "本書集結作家高覠罄141篇新詩與1短篇文章。\n\n",
            # Publisher text kept verbatim, including the leading 作者簡介／內容簡介／目錄 lines.
            "toc_start": "作者簡介\n內容簡介\n目錄\n1．又雪\n",
        },
        id="simplified-with-verbatim-toc",
    ),
    pytest.param(
        "2018630844053",
        {
            "title": "停跡坪：16處國定古蹟的文學跨界書寫",
            "isbn": "9786263952232",
            "publisher": "文訊",
            "published_date": date(2025, 9, 18),
            "language": "zh-TW",
            "page_count": 332,
            "contributors": tuple(
                Contributor(order, name, AUTHOR)
                for order, name in enumerate(
                    [
                        "李秉樺",
                        "邱常婷",
                        "徐禎苓",
                        "張郅忻",
                        "陳育萱",
                        "陳顥仁",
                        "奧崴尼．卡勒盛",
                        "楊富閔",
                        "葉淳之",
                        "廖振富",
                        "蕭詒徽",
                        "謝鑫佑",
                    ],
                    start=1,
                )
            ),
            "subjects": ("文學", "現代華文創作", "近代文學"),
            "description_start": "12位作家針對16處古蹟的文學創作",
            "toc_start": "一趟古蹟的時光行旅／文化部長 李遠\n",
        },
        id="multiple-authors-split-on-enumeration-comma",
    ),
    pytest.param(
        "2028870033469",
        {
            "title": "Between我們之間：Little Secrets of Relationships【中英雙語對照】",
            "isbn": "9786267791806",
            "publisher": "字畝文化",
            "published_date": date(2026, 5, 6),
            "language": "zh-TW",
            "page_count": 40,
            "contributors": (
                Contributor(1, "安娜．沃克", AUTHOR),
                Contributor(2, "張素惠", OTHER),
                Contributor(3, "黃筱茵", TRANSLATOR),
            ),
            "subjects": ("童書/青少年", "繪本", "同儕相處"),
            "description_start": "❤是不是有那麼一點可能，我們可以不再是陌生人？❤",
            "toc_start": None,
        },
        id="role-prefix-and-bracketed-original-name",
    ),
]


@pytest.mark.parametrize(("km_code", "expected"), REAL_BOOKS)
def test_real_fixture_fields(km_code, expected):
    draft = _parse_fixture(km_code)

    assert draft.source_url == detail_url(km_code)
    assert draft.external_id == km_code
    assert draft.title == expected["title"]
    assert draft.identifiers == _isbn(expected["isbn"])
    assert draft.publisher == expected["publisher"]
    assert draft.published_date == expected["published_date"]
    assert draft.published_date_precision is PublishedDatePrecision.DAY
    assert draft.language == expected["language"]
    assert draft.page_count == expected["page_count"]
    assert draft.contributors == expected["contributors"]
    assert draft.subjects == expected["subjects"]
    assert draft.description is not None and draft.description.startswith(expected["description_start"])
    if expected["toc_start"] is None:
        assert draft.table_of_contents is None
    else:
        assert draft.table_of_contents is not None and draft.table_of_contents.startswith(expected["toc_start"])
    assert draft.thumbnail_url is not None and draft.thumbnail_url.startswith("https://assets.kingstone.com.tw/")


@pytest.mark.parametrize(
    "km_code",
    ["2018630959191", "2018564008187", "2018741206573", "2028594173144", "2018250016458", "2018630844053", "2028870033469"],
)
def test_real_fixture_description_keeps_line_breaks(km_code):
    description = _parse_fixture(km_code).description

    assert description is not None
    assert "\n" in description
    assert "\n\n\n" not in description
    assert description == description.strip()


def test_general_book_contributors_are_all_authors():
    draft = _parse_fixture("2018630959191")

    assert all(contributor.role is AUTHOR for contributor in draft.contributors)


def test_real_fixture_description_has_no_adjacent_section_text():
    # The 活動、相關主題、作者介紹 blocks are outside `.pdintro`/`.catalog` and must not leak in.
    for km_code in ["2018630959191", "2028870033469", "2018741206573"]:
        draft = _parse_fixture(km_code)
        assert draft.description is not None
        assert "相關主題" not in draft.description
        assert "立即結帳" not in draft.description
        assert "GO享" not in draft.description


# ---------------------------------------------------------------------------
# Soft 404 and structural failures
# ---------------------------------------------------------------------------


def test_soft_404_fixture_is_product_not_found():
    with pytest.raises(ProductNotFound):
        parse_detail_html(_fixture("2099999999999"), detail_url("2099999999999"))


def test_product_not_found_is_not_a_parse_error():
    assert not issubclass(ProductNotFound, KingstoneParseError)


# ---------------------------------------------------------------------------
# Synthetic pages for negative and boundary cases
# ---------------------------------------------------------------------------

KM = "2018630959191"
URL = detail_url(KM)


def _product(**overrides) -> dict:
    product = {
        "@context": "https://schema.org/",
        "@type": ["Product", "Book"],
        "sku": KM,
        "gtin13": "9786263589612",
        "name": "合成測試書",
        "image": ["https://assets.kingstone.com.tw/prodassets/test.jpg"],
        "publisher": {"@type": "Organization", "name": "  測試出版  "},
        "isbn": "9786263589612",
        "datePublished": "2026-05-29",
    }
    product.update(overrides)
    return product


def _page(
    product: object = None,
    *,
    title: str = "金石堂",
    raw_script: str | None = None,
    spec: dict[str, str] | None = None,
    basic_units: str = "",
    breadcrumb: tuple[str, ...] = ("中文書", "文學", "現代小說"),
    description: str | None = "合成簡介第一行<br>第二行",
) -> str:
    if raw_script is not None:
        script = raw_script
    else:
        script = json.dumps(_product() if product is None else product, ensure_ascii=False)
    rows = "".join(f'<li class="table_th">{key}</li><li class="table_td">{value}</li>' for key, value in (spec or {}).items())
    crumbs = "".join(f'<a href="/book/x/">{name}</a>' for name in breadcrumb)
    desc = f'<div class="pdintro"><div class="panelCon">{description}</div></div>' if description is not None else ""
    return f"""<!doctype html>
<html><head><title>{title}</title>
<script type="application/ld+json">{script}</script>
</head><body>
<div class="basic-category-breadcrumb">{crumbs}</div>
<ul class="spec"><li><ul class="table_2col">{rows}</ul></li></ul>
<ul class="info">{basic_units}</ul>
{desc}
</body></html>"""


def _author_unit(links: str) -> str:
    return f'<li class="basicunit"><span class="title_basic">作者：</span>{links}</li>'


def _link(text: str) -> str:
    return f"<a href=\"javascript:location.href=SearchLink('{text}','','au');\">{text}</a>"


def test_synthetic_baseline_page_parses():
    draft = parse_detail_html(_page(spec={"語言": "中文繁體", "頁數": "12"}), URL)

    assert draft.title == "合成測試書"
    assert draft.external_id == KM
    assert draft.publisher == "測試出版"
    assert draft.published_date == date(2026, 5, 29)
    assert draft.subjects == ("文學", "現代小說")
    assert draft.description == "合成簡介第一行\n第二行"


def test_json_ld_as_list_is_accepted():
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": []}
    script = json.dumps([breadcrumb, _product()], ensure_ascii=False)

    assert parse_detail_html(_page(raw_script=script), URL).title == "合成測試書"


def test_sku_that_differs_from_url_is_parse_error():
    with pytest.raises(KingstoneParseError):
        parse_detail_html(_page(_product(sku="2018000000000")), URL)


def test_missing_sku_is_parse_error():
    product = _product()
    del product["sku"]

    with pytest.raises(KingstoneParseError):
        parse_detail_html(_page(product), URL)


@pytest.mark.parametrize("name", [None, "", "   "])
def test_missing_or_blank_name_is_parse_error(name):
    product = _product()
    if name is None:
        del product["name"]
    else:
        product["name"] = name

    with pytest.raises(KingstoneParseError):
        parse_detail_html(_page(product), URL)


def test_broken_product_json_is_parse_error_not_soft_404():
    with pytest.raises(KingstoneParseError):
        parse_detail_html(_page(raw_script='{"@type": ["Product", "Book"], "sku": '), URL)


def test_no_product_json_ld_with_site_title_is_product_not_found():
    page = _page(raw_script='{"@context": "https://schema.org/", "@type": "BreadcrumbList", "itemListElement": []}')

    with pytest.raises(ProductNotFound):
        parse_detail_html(page, URL)


def test_no_product_json_ld_with_other_title_is_parse_error():
    # A challenge or error page without a product must fail closed, not be skipped as a soft 404.
    page = _page(raw_script='{"@type": "BreadcrumbList", "itemListElement": []}', title="Access Denied")

    with pytest.raises(KingstoneParseError):
        parse_detail_html(page, URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.kingstone.com.tw/basic/2018630959191/",
        "https://www.kingstone.com.tw/basic/2018630959191",
        "https://www.kingstone.com.tw/basic/2018630959191/?lid=basic_related",
        "https://www.kingstone.com.tw/normal/basic/2018630959191/",
        "https://www.kingstone.com.tw/basic/201863095919/",
        "https://www.kingstone.com.tw/basic/20186309591901/",
        "https://example.com/basic/2018630959191/",
        "",
    ],
)
def test_non_canonical_detail_url_is_value_error(url):
    with pytest.raises(ValueError):
        parse_detail_html(_page(), url)


def test_gtin13_is_used_when_isbn_is_missing():
    product = _product()
    del product["isbn"]
    draft = parse_detail_html(_page(product), URL)

    assert draft.identifiers == _isbn("9786263589612")


def test_gtin13_is_used_when_isbn_is_empty():
    product = _product(isbn="")
    draft = parse_detail_html(_page(product), URL)

    assert draft.identifiers == _isbn("9786263589612")


def test_isbn_is_normalized_by_the_shared_rule():
    draft = parse_detail_html(_page(_product(isbn="978-6263 589612")), URL)

    assert draft.identifiers == _isbn("9786263589612")


def test_no_identifier_when_both_isbn_fields_are_absent():
    product = _product()
    del product["isbn"]
    del product["gtin13"]
    draft = parse_detail_html(_page(product), URL)

    assert draft.identifiers == ()


def test_no_identifier_when_isbn_has_no_value_after_normalization():
    draft = parse_detail_html(_page(_product(isbn=" - ", gtin13="")), URL)

    assert draft.identifiers == ()


@pytest.mark.parametrize("raw_date", ["2026/05/29", "2026-02-30", "2026-5-1", "", "abc"])
def test_unparseable_published_date_is_none_not_error(raw_date):
    draft = parse_detail_html(_page(_product(datePublished=raw_date)), URL)

    assert draft.published_date is None
    assert draft.published_date_precision is None


def test_missing_published_date_is_none():
    product = _product()
    del product["datePublished"]
    draft = parse_detail_html(_page(product), URL)

    assert draft.published_date is None
    assert draft.published_date_precision is None


def test_missing_publisher_is_none():
    product = _product()
    del product["publisher"]

    assert parse_detail_html(_page(product), URL).publisher is None


def test_thumbnail_is_first_image_or_the_string_itself():
    assert parse_detail_html(_page(_product(image=["https://assets.kingstone.com.tw/a.jpg", "https://assets.kingstone.com.tw/b.jpg"])), URL).thumbnail_url == (
        "https://assets.kingstone.com.tw/a.jpg"
    )
    assert parse_detail_html(_page(_product(image="https://assets.kingstone.com.tw/c.jpg")), URL).thumbnail_url == ("https://assets.kingstone.com.tw/c.jpg")


@pytest.mark.parametrize(
    ("language", "expected"),
    [("中文繁體", "zh-TW"), ("中文簡體", "zh-CN"), ("英文", None), ("", None)],
)
def test_language_comes_from_the_spec_table(language, expected):
    draft = parse_detail_html(_page(_product(inLanguage="zh-TW"), spec={"語言": language}), URL)

    assert draft.language == expected


def test_language_is_none_when_spec_row_is_missing_even_if_json_ld_says_zh_tw():
    draft = parse_detail_html(_page(_product(inLanguage="zh-TW")), URL)

    assert draft.language is None


@pytest.mark.parametrize(("pages", "expected"), [("12", 12), ("0", None), ("abc", None), ("", None), ("12頁", None)])
def test_page_count_must_be_a_positive_integer(pages, expected):
    assert parse_detail_html(_page(spec={"頁數": pages}), URL).page_count == expected


def test_page_count_is_none_when_row_is_missing():
    assert parse_detail_html(_page(), URL).page_count is None


def test_bracketed_author_link_is_original_name_and_skipped():
    units = _author_unit(_link("奧崴尼") + _link("(Gao Junqing)") + '<span class="followfield">追蹤</span><a href="/events/track/">?</a>')
    draft = parse_detail_html(_page(basic_units=units), URL)

    assert draft.contributors == (Contributor(1, "奧崴尼", AUTHOR),)


def test_author_link_with_only_a_bracketed_name_yields_no_contributors():
    units = _author_unit(_link("(Gao Junqing)"))

    assert parse_detail_html(_page(basic_units=units), URL).contributors == ()


def test_author_link_with_fullwidth_brackets_is_skipped_too():
    units = _author_unit(_link("奧崴尼") + _link("（Gao Junqing）"))

    assert parse_detail_html(_page(basic_units=units), URL).contributors == (Contributor(1, "奧崴尼", AUTHOR),)


def test_enumeration_comma_splits_names_inside_one_link():
    units = _author_unit(_link("甲、乙、丙"))
    draft = parse_detail_html(_page(basic_units=units), URL)

    assert draft.contributors == (
        Contributor(1, "甲", AUTHOR),
        Contributor(2, "乙", AUTHOR),
        Contributor(3, "丙", AUTHOR),
    )


def test_every_role_prefix_is_other_because_kingstone_does_not_use_the_books_role_vocabulary():
    # Only 審訂/ is observed (E0); even a label the Books.com.tw table knows (繪者) is not mapped here.
    units = _author_unit(_link("繪者/林小畫") + _link("顧問/王五") + _link("李四"))
    draft = parse_detail_html(_page(basic_units=units), URL)

    assert draft.contributors == (
        Contributor(1, "林小畫", OTHER),
        Contributor(2, "王五", OTHER),
        Contributor(3, "李四", AUTHOR),
    )


def test_translator_row_is_plain_text_split_on_enumeration_comma():
    units = _author_unit(_link("甲")) + '<li class="basicunit"><span class="title_basic">譯者：</span>丁、戊</li>'
    draft = parse_detail_html(_page(basic_units=units), URL)

    assert draft.contributors == (
        Contributor(1, "甲", AUTHOR),
        Contributor(2, "丁", TRANSLATOR),
        Contributor(3, "戊", TRANSLATOR),
    )


def test_order_follows_document_order_across_rows():
    units = _author_unit(_link("甲")) + '<li class="basicunit"><span class="title_basic">譯者：</span>丙</li>' + _author_unit(_link("乙"))
    draft = parse_detail_html(_page(basic_units=units), URL)

    assert [(c.order, c.name) for c in draft.contributors] == [(1, "甲"), (2, "丙"), (3, "乙")]


def test_no_author_row_yields_no_contributors():
    assert parse_detail_html(_page(), URL).contributors == ()


def test_subjects_are_deduplicated_in_order_and_drop_root():
    draft = parse_detail_html(_page(breadcrumb=("中文書", "童書/青少年", "繪本", "童書/青少年", "中文書", "繪本")), URL)

    assert draft.subjects == ("童書/青少年", "繪本")


def test_missing_description_and_toc_are_none():
    draft = parse_detail_html(_page(description=None), URL)

    assert draft.description is None
    assert draft.table_of_contents is None


def test_missing_title_is_parse_error_by_book_draft_or_kingstone():
    product = _product()
    product["name"] = "　"

    with pytest.raises((KingstoneParseError, ValueError)):
        parse_detail_html(_page(product), URL)
