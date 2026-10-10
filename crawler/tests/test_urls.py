import pytest

from books_crawler.urls import InvalidProductUrl, canonicalize_product_url


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
