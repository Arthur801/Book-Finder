FROM python:3.14-slim-bookworm

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
