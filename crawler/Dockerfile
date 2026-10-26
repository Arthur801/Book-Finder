# Two targets. The Kingstone target (HTTP-only, no Playwright or browser) is built with `--target kingstone`.
# The last stage is the default target (博客來 image), so a plain `docker build` still produces it.
FROM python:3.15-slim-bookworm AS kingstone

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/crawler
# requirements-runtime.txt is the HTTP-only set (psycopg, curl_cffi, beautifulsoup4); no browser stack is installed.
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 crawler \
    && useradd --uid 10001 --gid crawler --no-create-home crawler

COPY catalog_core/ ./catalog_core/
COPY kingstone/ ./kingstone/
COPY kingstone-pages.txt ./kingstone-pages.txt

USER 10001:10001
ENTRYPOINT ["python", "-m"]
CMD ["kingstone"]

FROM python:3.15-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CRAWLER_FETCHER=curl

WORKDIR /app/crawler
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 crawler \
    && useradd --uid 10001 --gid crawler --no-create-home crawler

COPY catalog_core/ ./catalog_core/
COPY books_crawler/ ./books_crawler/
COPY category-pages.txt ./category-pages.txt
RUN mkdir -p artifacts/challenges && chown -R crawler:crawler artifacts

USER 10001:10001
ENTRYPOINT ["python", "-m"]
CMD ["books_crawler"]
