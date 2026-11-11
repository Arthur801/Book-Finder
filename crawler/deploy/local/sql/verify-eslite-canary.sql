-- 誠品 canary 核對（CB-08 G4，Docs/plans/eslite-category-crawler.md §11）。唯讀；以主帳號執行（需要讀 book_subjects、bestsellers）。
-- 用法：psql -X -v t0='<run 開始前的 UTC 時間>' -v t1='<run 結束後的 UTC 時間>' -f verify-eslite-canary.sql
--   例：-v t0='2026-11-12T01:00:00Z' -v t1='2026-11-12T01:10:00Z'（時段請前後各留幾秒）。
-- 每段的「預期」是 1 頁 normal canary 的預期；完整清單 run 時以 last-run.json 的計數對照。
\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;

\echo '== 1. ESLITE Source（created_in_run 應等於 last-run.json 的 imported + isbn_attached + ambiguous_created；第一次 run 時 touched_in_run 應為 0） =='
SELECT count(*) AS total,
       count(*) FILTER (WHERE first_seen_at BETWEEN :'t0' AND :'t1') AS created_in_run,
       count(*) FILTER (WHERE first_seen_at < :'t0' AND last_seen_at BETWEEN :'t0' AND :'t1') AS touched_in_run,
       count(DISTINCT book_id) AS distinct_books,
       count(*) FILTER (WHERE external_id IS NULL) AS no_external_id
FROM book_sources WHERE source_code = 'ESLITE';

\echo '== 2. Identity 格式（預期 0、0）：external_id 是 16～23 位 guid，source_url 是 www 商品網址 =='
SELECT count(*) FILTER (WHERE external_id !~ '^[0-9]{16,23}$') AS bad_guid,
       count(*) FILTER (WHERE source_url <> 'https://www.eslite.com/product/' || external_id) AS bad_source_url
FROM book_sources WHERE source_code = 'ESLITE';

\echo '== 3. 本次新增的 Source：掛到既有書（isbn_attached）與新建書的分布 =='
SELECT (b.created_at < :'t0') AS book_existed_before,
       count(*) AS sources,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_sources o WHERE o.book_id = b.id AND o.source_code <> 'ESLITE')) AS with_other_provider
FROM book_sources s JOIN books b ON b.id = s.book_id
WHERE s.source_code = 'ESLITE' AND s.first_seen_at BETWEEN :'t0' AND :'t1'
GROUP BY 1 ORDER BY 1;

\echo '== 4. 掛到既有書的 Source（最多 20 列）：其他 provider、ESLITE Source 數（應為 1）、是否在本次補了 NULL 欄位 =='
SELECT b.title,
       (SELECT string_agg(DISTINCT o.source_code, ',') FROM book_sources o WHERE o.book_id = b.id AND o.source_code <> 'ESLITE') AS other_sources,
       (SELECT count(*) FROM book_sources e WHERE e.book_id = b.id AND e.source_code = 'ESLITE') AS eslite_sources,
       b.updated_at BETWEEN :'t0' AND :'t1' AS enriched_in_run
FROM book_sources s JOIN books b ON b.id = s.book_id
WHERE s.source_code = 'ESLITE' AND s.first_seen_at BETWEEN :'t0' AND :'t1' AND b.created_at < :'t0'
ORDER BY b.title LIMIT 20;

\echo '== 5. 本次新建的書：欄位覆蓋（books 應等於 imported + ambiguous_created） =='
SELECT count(*) AS books,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_identifiers i WHERE i.book_id = b.id AND i.identifier_type = 'ISBN')) AS with_isbn,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_contributors c WHERE c.book_id = b.id AND c.role = 'AUTHOR')) AS with_author,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM book_subjects sj WHERE sj.book_id = b.id AND sj.source_code = 'ESLITE')) AS with_eslite_subject,
       count(*) FILTER (WHERE b.publisher IS NOT NULL) AS with_publisher,
       count(*) FILTER (WHERE b.published_date IS NOT NULL) AS with_date,
       count(*) FILTER (WHERE b.language IS NOT NULL) AS with_language,
       count(*) FILTER (WHERE b.page_count IS NOT NULL) AS with_pages,
       count(*) FILTER (WHERE b.description IS NOT NULL) AS with_description,
       count(*) FILTER (WHERE b.thumbnail_url IS NOT NULL) AS with_thumbnail
FROM books b WHERE b.created_at BETWEEN :'t0' AND :'t1';

\echo '== 6. 半寫入檢查（預期 0）：本次新建、卻沒有 ESLITE Source 的書 =='
SELECT count(*) AS books_without_eslite_source
FROM books b
WHERE b.created_at BETWEEN :'t0' AND :'t1'
  AND NOT EXISTS (SELECT 1 FROM book_sources s WHERE s.book_id = b.id AND s.source_code = 'ESLITE');

\echo '== 7. 重複檢查（預期 0 列、0 列） =='
SELECT book_id, count(*) AS eslite_sources FROM book_sources WHERE source_code = 'ESLITE' GROUP BY book_id HAVING count(*) > 1;
SELECT external_id, count(*) AS rows FROM book_sources WHERE source_code = 'ESLITE' GROUP BY external_id HAVING count(*) > 1;

\echo '== 8. 本次新建的書，ISBN 是否與其他書重複（預期 0；>0 時應是 ISBN 命中 ≥2 本的 ambiguous_created，請對照 last-run.json） =='
SELECT count(DISTINCT i.identifier_value) AS shared_isbns
FROM book_identifiers i JOIN books b ON b.id = i.book_id
WHERE b.created_at BETWEEN :'t0' AND :'t1' AND i.identifier_type = 'ISBN'
  AND EXISTS (SELECT 1 FROM book_identifiers j WHERE j.identifier_type = 'ISBN' AND j.identifier_value = i.identifier_value AND j.book_id <> i.book_id);

\echo '== 9. 其他 provider 與 Bestseller 未變動（預期 0、0、0、0、0） =='
SELECT (SELECT count(*) FROM book_sources WHERE source_code = 'BOOKS_COM_TW' AND first_seen_at BETWEEN :'t0' AND :'t1') AS books_sources_created,
       (SELECT count(*) FROM book_sources WHERE source_code = 'BOOKS_COM_TW' AND last_seen_at BETWEEN :'t0' AND :'t1') AS books_sources_touched,
       (SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE' AND first_seen_at BETWEEN :'t0' AND :'t1') AS kingstone_sources_created,
       (SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE' AND last_seen_at BETWEEN :'t0' AND :'t1') AS kingstone_sources_touched,
       (SELECT count(*) FROM bestsellers WHERE captured_at BETWEEN :'t0' AND :'t1') AS bestsellers_in_run;

\echo '== 10. 抽樣 5 本新建的書 =='
SELECT b.title, b.publisher, b.published_date,
       (SELECT string_agg(i.identifier_value, ',') FROM book_identifiers i WHERE i.book_id = b.id) AS isbn,
       (SELECT string_agg(c.name, '、' ORDER BY c.contributor_order) FROM book_contributors c WHERE c.book_id = b.id AND c.role = 'AUTHOR') AS authors,
       s.source_url
FROM books b JOIN book_sources s ON s.book_id = b.id AND s.source_code = 'ESLITE'
WHERE b.created_at BETWEEN :'t0' AND :'t1'
ORDER BY b.created_at LIMIT 5;

ROLLBACK;
