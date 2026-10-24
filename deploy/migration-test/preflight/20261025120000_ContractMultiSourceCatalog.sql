-- Gate 7 preflight for 20261025120000_ContractMultiSourceCatalog (Docs/data/data-model.md 11.3).
-- Run by the operator against production BEFORE the 011 deploy, while the database is still at 010:
--   psql "$DATABASE_URL" -X -f deploy/migration-test/preflight/20261025120000_ContractMultiSourceCatalog.sql
-- Read-only: the whole script runs in one READ ONLY transaction and ends with ROLLBACK. It writes nothing and does not
-- touch __EFMigrationsHistory. Needs the 010 schema (source_type still exists); after 011 it fails on purpose.
-- Output: one row per metric with columns check, value and ok. Every ok must be true before 011 is deployed.
-- Rows marked INFO are always ok: they report facts, they are not failures.
BEGIN READ ONLY;

WITH counts AS (
  SELECT
    count(*) FILTER (WHERE identifier_type = 'ISBN_10') AS isbn10,
    count(*) FILTER (WHERE identifier_type = 'ISBN_13') AS isbn13,
    count(*) FILTER (WHERE identifier_type = 'ISBN') AS isbn,
    count(*) FILTER (WHERE identifier_type = 'OTHER') AS other,
    count(*) FILTER (WHERE identifier_type NOT IN ('ISBN', 'ISBN_10', 'ISBN_13', 'OTHER')) AS unknown_types,
    count(*) AS total
  FROM book_identifiers
),
distinct_isbn AS (
  SELECT count(*) AS n
  FROM (
    SELECT DISTINCT book_id, identifier_value
    FROM book_identifiers
    WHERE identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13')
  ) d
),
shared_isbn AS (
  SELECT count(*) AS n
  FROM (
    SELECT identifier_value
    FROM book_identifiers
    WHERE identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13')
    GROUP BY identifier_value
    HAVING count(DISTINCT book_id) > 1
  ) s
),
gate4 AS (
  SELECT
    (SELECT count(*) FROM book_sources WHERE source_code IS NULL) AS sources_null,
    (SELECT count(*) FROM book_subjects WHERE source_code IS NULL) AS subjects_null
),
-- The same mapping as the migration guard (gate 5): a source_code without a 010 source_type must have source_type NULL.
gate5 AS (
  SELECT
    (SELECT count(*) FROM book_sources WHERE source_type IS DISTINCT FROM (CASE source_code
        WHEN 'BOOKS_COM_TW' THEN 'BOOKS_COM_TW' WHEN 'GOOGLE_BOOKS' THEN 'GOOGLE_BOOKS' ELSE NULL END)) AS sources_mismatch,
    (SELECT count(*) FROM book_subjects WHERE source_type IS DISTINCT FROM (CASE source_code
        WHEN 'BOOKS_COM_TW' THEN 'BOOKS_COM_TW' WHEN 'GOOGLE_BOOKS' THEN 'GOOGLE_BOOKS' ELSE NULL END)) AS subjects_mismatch
),
metrics AS (
  SELECT 1 AS ord, 'legacy ISBN_10 rows (INFO)' AS "check", c.isbn10 AS value, true AS ok FROM counts c
  UNION ALL SELECT 2, 'legacy ISBN_13 rows (INFO)', c.isbn13, true FROM counts c
  UNION ALL SELECT 3, 'legacy ISBN rows (INFO)', c.isbn, true FROM counts c
  UNION ALL SELECT 4, 'legacy OTHER rows (INFO)', c.other, true FROM counts c
  UNION ALL SELECT 5, 'rows participating in the conversion (ISBN_10 + ISBN_13) (INFO)', c.isbn10 + c.isbn13, true FROM counts c
  UNION ALL SELECT 6, 'estimated ISBN rows after: distinct (book_id, value) over ISBN, ISBN_10, ISBN_13 (INFO)', d.n, true FROM distinct_isbn d
  UNION ALL SELECT 7, 'expected rows removed by ON CONFLICT: same Book, same value (INFO)', (c.isbn10 + c.isbn13 + c.isbn) - d.n, true FROM counts c, distinct_isbn d
  UNION ALL SELECT 8, 'book_identifiers rows before (INFO)', c.total, true FROM counts c
  UNION ALL SELECT 9, 'estimated book_identifiers rows after: estimated ISBN + OTHER (INFO)', d.n + c.other, true FROM counts c, distinct_isbn d
  UNION ALL SELECT 10, 'identifier types outside ISBN, ISBN_10, ISBN_13, OTHER (must be 0)', c.unknown_types, c.unknown_types = 0 FROM counts c
  UNION ALL SELECT 11, 'gate 4: book_sources rows with NULL source_code (must be 0)', g.sources_null, g.sources_null = 0 FROM gate4 g
  UNION ALL SELECT 12, 'gate 4: book_subjects rows with NULL source_code (must be 0)', g.subjects_null, g.subjects_null = 0 FROM gate4 g
  UNION ALL SELECT 13, 'gate 5: book_sources rows whose source_type differs from source_code (must be 0)', m.sources_mismatch, m.sources_mismatch = 0 FROM gate5 m
  UNION ALL SELECT 14, 'gate 5: book_subjects rows whose source_type differs from source_code (must be 0)', m.subjects_mismatch, m.subjects_mismatch = 0 FROM gate5 m
  UNION ALL SELECT 15, 'INFO: ISBN values shared by different Books (allowed, not a failure)', s.n, true FROM shared_isbn s
)
SELECT "check", value, ok
FROM metrics
ORDER BY ord;

ROLLBACK;
