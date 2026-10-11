import pytest

from books_crawler.urls import InvalidProductUrl, canonicalize_product_url, is_category_ranking_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://www.books.com.tw/products/0011032989", "https://www.books.com.tw/products/0011032989"),
        ("https://www.books.com.tw/products/0011032989?loc=P_0007_001", "https://www.books.com.tw/products/0011032989"),
        ("https://www.books.com.tw/products/0011032989/", "https://www.books.com.tw/products/0011032989"),
        ("https://www.books.com.tw/products/0011032989#reviews", "https://www.books.com.tw/products/0011032989"),
        ("http://books.com.tw/products/0011032989", "https://www.books.com.tw/products/0011032989"),
        ("//www.books.com.tw/products/0011032989", "https://www.books.com.tw/products/0011032989"),
        ("/products/0011032989", "https://www.books.com.tw/products/0011032989"),
        ("  https://www.books.com.tw/products/0011032989  ", "https://www.books.com.tw/products/0011032989"),
    ],
)
def test_canonicalizes_product_urls(raw, expected):
    assert canonicalize_product_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7",
        "https://www.books.com.tw/products/",
        "https://www.books.com.tw/products/001/extra",
        "https://example.com/products/0011032989",
        "ftp://www.books.com.tw/products/0011032989",
    ],
)
def test_rejects_non_product_urls(raw):
    with pytest.raises(InvalidProductUrl):
        canonicalize_product_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002",
        "https://www.books.com.tw/web/sys_saletopb/books/24/?attribute=7",
        "https://www.books.com.tw/web/sys_saletopb/books/13/?attribute=7&loc=P_0002_015#top",
    ],
)
def test_accepts_category_seven_day_ranking_urls(raw):
    assert is_category_ranking_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.books.com.tw/web/sys_saletopb/books/?attribute=7",  # the overall 7-day ranking, not a category
        "https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=6&loc=P_0002_002",  # not the 7-day list
        "https://www.books.com.tw/web/sys_saletopb/books/01/",  # attribute missing
        "https://www.books.com.tw/web/sys_saletopb/books/01?attribute=7",  # no trailing slash
        "https://www.books.com.tw/web/sys_saletopb/books/001/?attribute=7",  # not two digits
        "http://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7",  # not https
        "https://books.com.tw/web/sys_saletopb/books/01/?attribute=7",  # not www
        "https://www.books.com.tw:8443/web/sys_saletopb/books/01/?attribute=7",  # port
        "https://example.com/web/sys_saletopb/books/01/?attribute=7",
        "https://www.books.com.tw/products/0011032989",  # a product, not a ranking page
        "",
        "https://[",  # unparseable: rejected, not an exception
    ],
)
def test_rejects_urls_that_are_not_category_seven_day_ranking_pages(raw):
    assert not is_category_ranking_url(raw)
