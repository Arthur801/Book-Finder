"""Eslite (誠品) URL grammar: list page canonicalization, list API URLs, detail API URLs and product URLs. Offline."""

import pytest

from eslite.urls import (
    API_HOST,
    GUID_RE,
    SITE_HOST,
    canonical_list_url,
    category_and_page,
    detail_api_url,
    guid_from_detail_api_url,
    is_list_api_url,
    list_api_url,
    product_url,
)

WWW = "https://www.eslite.com/category/3/101"
GUID = "1001136502682294792007"


def test_the_hosts_and_guid_pattern_are_the_contract_values():
    assert SITE_HOST == "www.eslite.com"
    assert API_HOST == "athena.eslite.com"
    assert GUID_RE.pattern == "^[0-9]{16,23}$"


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.eslite.com/category/3/101",
        "https://www.eslite.com/category/3/101?page=2",
        "https://www.eslite.com/category/3/34?page=1333",
        "https://www.eslite.com/category/3/9999999",
    ],
)
def test_canonical_urls_are_returned_unchanged(raw):
    assert canonical_list_url(raw) == raw


def test_page_one_is_omitted_from_the_canonical_form():
    assert canonical_list_url("https://www.eslite.com/category/3/101?page=1") == WWW


def test_page_one_and_no_page_are_the_same_canonical_url():
    assert canonical_list_url("https://www.eslite.com/category/3/101?page=1") == canonical_list_url(WWW)


@pytest.mark.parametrize(
    "raw",
    [
        "http://www.eslite.com/category/3/101",  # scheme
        "HTTPS://www.eslite.com/category/3/101",  # scheme case
        "https://eslite.com/category/3/101",  # host without www
        "https://athena.eslite.com/category/3/101",  # API host
        "https://WWW.ESLITE.COM/category/3/101",  # host case
        "https://www.eslite.com./category/3/101",  # trailing dot
        "https://user@www.eslite.com/category/3/101",  # userinfo
        "https://user:pw@www.eslite.com/category/3/101",  # userinfo with password
        "https://www.eslite.com:443/category/3/101",  # explicit port
        "https://www.kingstone.com.tw/category/3/101",  # other site
        "https://www.eslite.com/category/3/101/",  # trailing slash
        "https://www.eslite.com/category/3/0101",  # leading zero in id
        "https://www.eslite.com/category/3/0",  # zero id
        "https://www.eslite.com/category/3/101?page=0",  # page zero
        "https://www.eslite.com/category/3/101?page=01",  # leading zero in page
        "https://www.eslite.com/category/3/101?page=-1",  # negative page
        "https://www.eslite.com/category/3/101?page=",  # empty page
        "https://www.eslite.com/category/3/101?page=２",  # full-width digit
        "https://www.eslite.com/category/3/101?page=2&sort=date",  # extra query key
        "https://www.eslite.com/category/3/101?sort=date",  # no page key
        "https://www.eslite.com/category/3/101?page=2&page=3",  # repeated key
        "https://www.eslite.com/category/3/101?page=2#top",  # fragment
        "https://www.eslite.com/category/3/101#top",  # fragment without query
        "https://www.eslite.com/category/3/101?",  # empty query
        "https://www.eslite.com/category/3/101?page=2?",  # stray question mark
        "https://www.eslite.com/category/2/28",  # level 2 category
        "https://www.eslite.com/category/1/1",  # level 1 category
        "https://www.eslite.com/category/03/101",  # leading zero in depth
        "https://www.eslite.com/category/3/",  # no id
        "https://www.eslite.com/category/3/abc",  # non-numeric id
        "https://www.eslite.com/category/3/101/extra",  # extra path segment
        "https://www.eslite.com/product/1001136502682294792007",  # product page
        "https://www.eslite.com/category/3/101 ",  # whitespace
        "https://www.eslite.com/category/3/10 1",  # inner space
        "https://www.eslite.com/category/3/１０１",  # full-width digits
        "www.eslite.com/category/3/101",  # no scheme
        "/category/3/101",  # relative
        "",  # empty
    ],
)
def test_anything_outside_the_grammar_is_rejected(raw):
    assert canonical_list_url(raw) is None


@pytest.mark.parametrize("raw", [None, 5, b"https://www.eslite.com/category/3/101"])
def test_a_non_string_is_rejected(raw):
    assert canonical_list_url(raw) is None


def test_category_and_page_returns_id_and_page_of_a_canonical_url():
    assert category_and_page("https://www.eslite.com/category/3/101") == (101, 1)
    assert category_and_page("https://www.eslite.com/category/3/34?page=6") == (34, 6)


def test_category_and_page_rejects_a_non_canonical_url():
    with pytest.raises(ValueError):
        category_and_page("https://www.eslite.com/category/3/101?page=1")


def test_list_api_url_uses_the_fixed_parameter_order():
    assert list_api_url(WWW) == ("https://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true")


def test_list_api_url_carries_the_page_number():
    assert list_api_url("https://www.eslite.com/category/3/101?page=6") == (
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=6&sort_type=date&sort_order=desc&page_size=40&is_available=true"
    )


def test_list_api_url_rejects_a_non_canonical_url():
    with pytest.raises(ValueError):
        list_api_url("https://www.eslite.com/category/3/101?page=1")


@pytest.mark.parametrize(
    "url",
    [
        list_api_url(WWW),
        list_api_url("https://www.eslite.com/category/3/34?page=1333"),
    ],
)
def test_is_list_api_url_accepts_the_exact_shape(url):
    assert is_list_api_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true",
        "https://www.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true",
        "https://athena.eslite.com/api/v1/categories/101/products?sort_type=date&page_no=1&sort_order=desc&page_size=40&is_available=true",
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=20&is_available=true",
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=false",
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=0&sort_type=date&sort_order=desc&page_size=40&is_available=true",
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=01&sort_type=date&sort_order=desc&page_size=40&is_available=true",
        "https://athena.eslite.com/api/v1/categories/0101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true",
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true&extra=1",
        "https://athena.eslite.com/api/v1/categories/101/products?page_no=1&sort_type=date&sort_order=desc&page_size=40&is_available=true#x",
        "https://athena.eslite.com/api/v4/products/1001136502682294792007/description",
        "",
    ],
)
def test_is_list_api_url_rejects_other_shapes(url):
    assert is_list_api_url(url) is False


def test_detail_api_url_is_the_v4_description_endpoint():
    assert detail_api_url(GUID) == f"https://athena.eslite.com/api/v4/products/{GUID}/description"


@pytest.mark.parametrize("guid", ["1001114412021700", "1001136502682294792007", "10019999999999999999999"])
def test_guids_of_16_to_23_digits_are_accepted(guid):
    assert detail_api_url(guid).endswith(f"/products/{guid}/description")
    assert product_url(guid) == f"https://www.eslite.com/product/{guid}"


@pytest.mark.parametrize(
    "guid",
    [
        "",
        "123456789012345",  # 15 digits
        "100113650268229479200700",  # 24 digits
        "1001136502682294792007\n",  # trailing newline
        "100113650268229479200a",  # letter
        " 1001136502682294792007",  # leading space
        "１００１１３６５０２６８２２９４７９２００７",  # full-width digits
        None,
        1001136502682294792007,
    ],
)
def test_a_guid_outside_the_pattern_raises_for_both_builders(guid):
    with pytest.raises(ValueError):
        detail_api_url(guid)
    with pytest.raises(ValueError):
        product_url(guid)


def test_guid_is_recovered_from_a_detail_api_url():
    assert guid_from_detail_api_url(detail_api_url(GUID)) == GUID


@pytest.mark.parametrize(
    "url",
    [
        f"http://athena.eslite.com/api/v4/products/{GUID}/description",
        f"https://www.eslite.com/api/v4/products/{GUID}/description",
        f"https://athena.eslite.com/api/v4/products/{GUID}/description/",
        f"https://athena.eslite.com/api/v4/products/{GUID}/description?x=1",
        f"https://athena.eslite.com/api/v3/products/{GUID}/description",
        f"https://athena.eslite.com/api/v4/products/{GUID}",
        "https://athena.eslite.com/api/v4/products/123456789012345/description",
        f"https://athena.eslite.com/api/v4/products/{GUID}00/description",  # 24 digits
        f"https://athena.eslite.com/api/v4/products/{GUID}/description#x",
        f"https://www.eslite.com/product/{GUID}",
        "",
    ],
)
def test_a_url_outside_the_detail_api_shape_has_no_guid(url):
    assert guid_from_detail_api_url(url) is None


def test_guid_from_detail_api_url_rejects_a_non_string():
    assert guid_from_detail_api_url(None) is None


def test_product_url_is_the_web_product_page():
    assert product_url(GUID) == f"https://www.eslite.com/product/{GUID}"
