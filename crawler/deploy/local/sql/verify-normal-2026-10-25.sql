-- P5 normal 核對（run cab53f56，2026-10-25 16:50:15–16:52:18 UTC）。唯讀；以主帳號執行（需要讀 book_subjects）。其他 run 請改 t0／t1／c0 與預期數字。
\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;
\set t0 '''2026-10-25 16:50:00+00'''
\set t1 '''2026-10-25 16:53:00+00'''
\set c0 '''2026-10-25 16:33:00+00'''

\echo '== 1. KINGSTONE Source（預期 48：39 筆舊的 last_seen 前進、9 筆本次新增） =='
SELECT count(*) AS total,
       count(*) FILTER (WHERE first_seen_at BETWEEN :t0 AND :t1) AS created_in_run,
       count(*) FILTER (WHERE first_seen_at < :t0 AND last_seen_at BETWEEN :t0 AND :t1) AS touched_in_run,
       count(*) FILTER (WHERE first_seen_at < :t0 AND last_seen_at < :t0) AS not_touched
FROM book_sources WHERE source_code = 'KINGSTONE';

\echo '== 2. 本次新增的 9 筆掛到既有書（預期 9 列：book 建立早於 canary、有其他 provider 的 Source、只有 1 個 KINGSTONE Source） =='
SELECT b.title,
       b.created_at < :c0 AS book_existed_before,
       (SELECT string_agg(DISTINCT s2.source_code, ',') FROM book_sources s2 WHERE s2.book_id = b.id AND s2.source_code <> 'KINGSTONE') AS other_sources,
       (SELECT count(*) FROM book_sources s3 WHERE s3.book_id = b.id AND s3.source_code = 'KINGSTONE') AS kingstone_sources,
       b.updated_at BETWEEN :t0 AND :t1 AS enriched_in_run
FROM book_sources s JOIN books b ON b.id = s.book_id
WHERE s.source_code = 'KINGSTONE' AND s.first_seen_at BETWEEN :t0 AND :t1
ORDER BY b.title;

\echo '== 3. 這 9 本的欄位現況與金石堂補上的資料 =='
SELECT b.title,
       b.publisher IS NOT NULL AS publisher, b.published_date IS NOT NULL AS pub_date, b.description IS NOT NULL AS description,
       b.thumbnail_url IS NOT NULL AS thumbnail, b.page_count IS NOT NULL AS pages, b.language IS NOT NULL AS lang,
       (SELECT count(*) FROM book_contributors c WHERE c.book_id = b.id AND c.role = 'AUTHOR') AS authors,
       (SELECT count(*) FROM book_identifiers i WHERE i.book_id = b.id) AS isbns,
       (SELECT count(*) FROM book_subjects sj WHERE sj.book_id = b.id AND sj.source_code = 'KINGSTONE') AS kingstone_subjects,
       (SELECT count(*) FROM book_subjects sj WHERE sj.book_id = b.id AND sj.source_code <> 'KINGSTONE') AS other_subjects
FROM book_sources s JOIN books b ON b.id = s.book_id
WHERE s.source_code = 'KINGSTONE' AND s.first_seen_at BETWEEN :t0 AND :t1
ORDER BY b.title;

\echo '== 4. 重複檢查（預期 0 列） =='
SELECT book_id, count(*) FROM book_sources WHERE source_code = 'KINGSTONE' GROUP BY book_id HAVING count(*) > 1;
SELECT i.identifier_value, count(DISTINCT i.book_id) FROM book_identifiers i
WHERE i.book_id IN (SELECT book_id FROM book_sources WHERE source_code = 'KINGSTONE')
  AND EXISTS (SELECT 1 FROM book_identifiers j WHERE j.identifier_value = i.identifier_value AND j.book_id <> i.book_id)
GROUP BY i.identifier_value;

\echo '== 5. 沒有新增書、博客來與 Bestseller 未變動（預期 0、0、0） =='
SELECT (SELECT count(*) FROM books WHERE created_at BETWEEN :t0 AND :t1) AS books_created_in_run,
       (SELECT count(*) FROM book_sources WHERE source_code = 'BOOKS_COM_TW' AND last_seen_at BETWEEN :t0 AND :t1) AS books_sources_touched,
       (SELECT count(*) FROM bestsellers WHERE captured_at BETWEEN :t0 AND :t1) AS bestsellers_in_run;

ROLLBACK;
