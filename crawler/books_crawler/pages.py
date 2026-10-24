"""Import the category 7-day ranking pages into the Catalog without updating bestsellers (crawler.md §15).

Run from crawler/: python -m books_crawler.pages. The page list is crawler/category-pages.txt
(or the path in CRAWLER_PAGES_FILE).
"""

from books_crawler.cli import CrawlerMode, main

if __name__ == "__main__":
    raise SystemExit(main(mode=CrawlerMode.PAGES))
