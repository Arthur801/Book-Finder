"""Import the current ranking's first book into the catalog, without replacing bestsellers.

Run from crawler/: python -m books_crawler.first_book
Uses the same DATABASE_URL and CRAWLER_FETCHER settings as the daily crawler (default: curl).
"""

from books_crawler.cli import CrawlerMode, main

if __name__ == "__main__":
    raise SystemExit(main(mode=CrawlerMode.FIRST_BOOK))
