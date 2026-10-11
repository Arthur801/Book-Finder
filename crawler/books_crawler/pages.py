"""Import books from PAGE_URLS without updating bestsellers."""

from books_crawler.cli import main

if __name__ == "__main__":
    raise SystemExit(main(pages=True))