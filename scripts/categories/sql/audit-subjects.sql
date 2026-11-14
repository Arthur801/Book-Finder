-- Canonical Category P0 盤點（Docs/plans/canonical-category-browse.md §5 P0）。唯讀，可在 read-only 連線執行；需要讀 books、book_sources、book_subjects。
-- 用法：psql -X [-v csv='<輸出檔>'] -f audit-subjects.sql
--   畫面輸出第 1～4 段（小）；第 5 段的完整 (source_code, subject) 清單寫成 CSV（預設 category-audit-subjects.csv，相對於執行時的目錄）。
-- 「上層候選」是推測：同一來源中，若另一個 Subject 出現在這個 Subject 的每一本書上、而且書更多，就視為它的上層。
-- book_subjects 沒有保存層級，所以這只是盤點用的線索，不是 Mapping 規則；規則由人審核後寫進規則檔。
\set ON_ERROR_STOP on
\pset pager off
\if :{?csv}
\else
\set csv category-audit-subjects.csv
\endif
BEGIN READ ONLY;

\echo '== 1. 各來源概況：有該來源 Source 的書、其中有 Subject 的書、沒有任何 Subject 的書、不同 Subject 數 =='
SELECT bs.source_code,
       count(DISTINCT bs.book_id) AS books_with_source,
       count(DISTINCT bs.book_id) FILTER (WHERE EXISTS (
           SELECT 1 FROM book_subjects sj WHERE sj.book_id = bs.book_id AND sj.source_code = bs.source_code)) AS books_with_subject,
       count(DISTINCT bs.book_id) FILTER (WHERE NOT EXISTS (
           SELECT 1 FROM book_subjects sj WHERE sj.book_id = bs.book_id AND sj.source_code = bs.source_code)) AS books_without_subject,
       (SELECT count(DISTINCT sj.subject) FROM book_subjects sj WHERE sj.source_code = bs.source_code) AS distinct_subjects
FROM book_sources bs GROUP BY bs.source_code ORDER BY bs.source_code;

\echo '== 2. 全書庫：書數、沒有任何來源 Subject 的書數 =='
SELECT count(*) AS books,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM book_subjects sj WHERE sj.book_id = b.id)) AS books_without_any_subject
FROM books b;

\echo '== 3. 異常（預期 0）：有某來源的 Subject、卻沒有該來源 Source 的 Subject 列數 =='
SELECT sj.source_code, count(*) AS subject_rows_without_source
FROM book_subjects sj
WHERE NOT EXISTS (SELECT 1 FROM book_sources bs WHERE bs.book_id = sj.book_id AND bs.source_code = sj.source_code)
GROUP BY sj.source_code ORDER BY sj.source_code;

\echo '== 4. 頂層候選（沒有上層候選的 Subject），依來源、書數排序。誠品每本書只有一個第 3 層 Subject，所以全部會列出 =='
WITH subject_books AS (
    SELECT source_code, subject, count(DISTINCT book_id) AS books
    FROM book_subjects GROUP BY source_code, subject
), subject_pairs AS (
    -- 同一本書、同一來源上一起出現的兩個 Subject；co = 兩者同時出現的書數。
    SELECT a.source_code, a.subject AS child, b.subject AS parent, count(*) AS co
    FROM book_subjects a
    JOIN book_subjects b ON b.book_id = a.book_id AND b.source_code = a.source_code AND b.subject <> a.subject
    GROUP BY a.source_code, a.subject, b.subject
), subject_parents AS (
    -- 上層候選：涵蓋這個 Subject 全部的書、書數更多者；有多個時取書數最少的（最接近的上層），同數依名稱。
    SELECT DISTINCT ON (s.source_code, s.subject)
           s.source_code, s.subject, s.books, sp.subject AS parent, sp.books AS parent_books
    FROM subject_books s
    LEFT JOIN subject_pairs p ON p.source_code = s.source_code AND p.child = s.subject AND p.co = s.books
    LEFT JOIN subject_books sp ON sp.source_code = p.source_code AND sp.subject = p.parent AND sp.books > s.books
    ORDER BY s.source_code, s.subject, (sp.books IS NULL), sp.books, sp.subject
)
SELECT source_code, subject, books
FROM subject_parents WHERE parent IS NULL
ORDER BY source_code, books DESC, subject;

\echo '== 5. 完整清單已寫入 CSV（source_code, subject, books, parent_candidate, parent_books） =='
\echo :csv
\o :csv
COPY (
    WITH subject_books AS (
        SELECT source_code, subject, count(DISTINCT book_id) AS books
        FROM book_subjects GROUP BY source_code, subject
    ), subject_pairs AS (
        -- 同一本書、同一來源上一起出現的兩個 Subject；co = 兩者同時出現的書數。
        SELECT a.source_code, a.subject AS child, b.subject AS parent, count(*) AS co
        FROM book_subjects a
        JOIN book_subjects b ON b.book_id = a.book_id AND b.source_code = a.source_code AND b.subject <> a.subject
        GROUP BY a.source_code, a.subject, b.subject
    ), subject_parents AS (
        -- 上層候選：涵蓋這個 Subject 全部的書、書數更多者；有多個時取書數最少的（最接近的上層），同數依名稱。
        SELECT DISTINCT ON (s.source_code, s.subject)
               s.source_code, s.subject, s.books, sp.subject AS parent, sp.books AS parent_books
        FROM subject_books s
        LEFT JOIN subject_pairs p ON p.source_code = s.source_code AND p.child = s.subject AND p.co = s.books
        LEFT JOIN subject_books sp ON sp.source_code = p.source_code AND sp.subject = p.parent AND sp.books > s.books
        ORDER BY s.source_code, s.subject, (sp.books IS NULL), sp.books, sp.subject
    )
    SELECT source_code, subject, books, parent AS parent_candidate, parent_books
    FROM subject_parents
    ORDER BY source_code, books DESC, subject
) TO STDOUT WITH (FORMAT csv, HEADER true);
\o

ROLLBACK;
