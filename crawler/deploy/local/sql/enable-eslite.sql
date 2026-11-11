-- 誠品計畫 G3 controlled enable（Docs/plans/eslite-category-crawler.md §11）：啟用 ESLITE provider。以主帳號執行；只改 source_providers 一列。
-- 回復：把 true 改成 false 再執行一次（crawler 會以 exit 2 拒絕執行，網頁不再顯示誠品連結）。
\set ON_ERROR_STOP on
\pset pager off
BEGIN;
SELECT code, enabled FROM source_providers ORDER BY code;
UPDATE source_providers SET enabled = true WHERE code = 'ESLITE' AND enabled = false RETURNING code, enabled;
SELECT count(*) AS eslite_sources FROM book_sources WHERE source_code = 'ESLITE';
COMMIT;
