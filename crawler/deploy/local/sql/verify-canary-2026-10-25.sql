-- P5 canary 核對（run 2d933792，2026-10-25 16:33:56–16:40:05 UTC）。唯讀；以主帳號執行（需要讀 bestsellers、book_subjects）。其他 run 請改 t0／t1 與預期數字。
\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;
\set t0 '''2026-10-25 16:33:00+00'''
\set t1 '''2026-10-25 16:41:00+00'''

\echo '== 1. KINGSTONE Source（預期全部 39，且都在 run 時段內建立） =='
SELECT count(*) AS total,
       count(*) FILTER (WHERE first_seen_at BETWEEN :t0 AND :t1) AS in_run,
       count(*) FILTER (WHERE external_id IS NULL) AS no_external_id,
       count(DISTINCT external_id) AS distinct_external_id,
       count(DISTINCT source_url) AS distinct_url,
       count(DISTINCT book_id) AS distinct_books
FROM book_sources WHERE source_code = 'KINGSTONE';

\echo '== 2. 一本書有多個 KINGSTONE Source（預期 0 列） =='
SELECT book_id, count(*) FROM book_sources WHERE source_code = 'KINGSTONE' GROUP BY book_id HAVING count(*) > 1;

\echo '== 3. 新 Book（預期 39；其他 provider 的 Source 不應出現在這些書上） =='
SELECT count(DISTINCT b.id) AS new_books,
       count(*) FILTER (WHERE s.source_code <> 'KINGSTONE') AS other_provider_sources_on_them
FROM books b JOIN book_sources s ON s.book_id = b.id
WHERE b.created_at BETWEEN :t0 AND :t1;

\echo '== 4. 新書的 ISBN 是否與既有書重複（new-books-only 應已跳過；預期 0 列） =='
SELECT i.identifier_value, count(DISTINCT i.book_id) AS books
FROM book_identifiers i
WHERE i.identifier_type = 'ISBN'
  AND i.identifier_value IN (SELECT i2.identifier_value FROM book_identifiers i2 JOIN books b ON b.id = i2.book_id WHERE b.created_at BETWEEN :t0 AND :t1)
GROUP BY i.identifier_value HAVING count(DISTINCT i.book_id) > 1;

\echo '== 5. 新書的欄位覆蓋 =='
SELECT count(*) AS books,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_identifiers i WHERE i.book_id = b.id AND i.identifier_type = 'ISBN')) AS with_isbn,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_contributors c WHERE c.book_id = b.id AND c.role = 'AUTHOR')) AS with_author,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_subjects sj WHERE sj.book_id = b.id)) AS with_subject,
       count(*) FILTER (WHERE b.publisher IS NOT NULL) AS with_publisher,
       count(*) FILTER (WHERE b.published_date IS NOT NULL) AS with_date,
       count(*) FILTER (WHERE b.description IS NOT NULL) AS with_description,
       count(*) FILTER (WHERE b.thumbnail_url IS NOT NULL) AS with_thumbnail
FROM books b WHERE b.created_at BETWEEN :t0 AND :t1;

\echo '== 6. 博客來資料未被動到（預期 run 時段內 0） =='
SELECT count(*) FILTER (WHERE last_seen_at BETWEEN :t0 AND :t1) AS books_sources_touched_in_run,
       count(*) FILTER (WHERE first_seen_at BETWEEN :t0 AND :t1) AS books_sources_created_in_run
FROM book_sources WHERE source_code = 'BOOKS_COM_TW';
SELECT count(*) AS bestseller_rows, max(captured_at) AS last_captured,
       count(*) FILTER (WHERE captured_at BETWEEN :t0 AND :t1) AS captured_in_run
FROM bestsellers;

\echo '== 7. 抽樣 5 本 =='
SELECT b.title, b.publisher, b.published_date,
       (SELECT string_agg(identifier_value, ',') FROM book_identifiers i WHERE i.book_id = b.id) AS isbn,
       (SELECT string_agg(name, '、' ORDER BY contributor_order) FROM book_contributors c WHERE c.book_id = b.id AND c.role = 'AUTHOR') AS authors,
       s.source_url
FROM books b JOIN book_sources s ON s.book_id = b.id AND s.source_code = 'KINGSTONE'
WHERE b.created_at BETWEEN :t0 AND :t1
ORDER BY b.created_at LIMIT 5;

ROLLBACK;
