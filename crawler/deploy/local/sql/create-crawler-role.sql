-- 建立 crawler 專用帳號（plan v12 §10 P2）。以 bookfinder_admin 執行；只新增角色與授權，不改資料、不改其他角色。
-- 權限依 crawler 程式實際的 SQL 整理（catalog_core/persistence.py、books_crawler/db.py）。
\set ON_ERROR_STOP on
\pset pager off

BEGIN;
CREATE ROLE bookfinder_crawler LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 5;
GRANT CONNECT ON DATABASE book_finder TO bookfinder_crawler;
GRANT USAGE ON SCHEMA public TO bookfinder_crawler;
GRANT SELECT, INSERT, UPDATE ON books, book_sources TO bookfinder_crawler;
GRANT SELECT, INSERT ON book_identifiers, book_contributors TO bookfinder_crawler;
GRANT INSERT ON book_subjects TO bookfinder_crawler;
GRANT INSERT, DELETE ON bestsellers TO bookfinder_crawler;
GRANT SELECT ON source_providers TO bookfinder_crawler;
COMMIT;

-- 設定密碼：psql 會提示輸入兩次，送出的是 SCRAM 雜湊，明文不會出現在 SQL 或伺服器 log。
\password bookfinder_crawler

-- 確認：應看到 bookfinder_crawler，所有 rol* 屬性為 f（rolinherit 除外），無所屬角色
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolconnlimit
FROM pg_roles WHERE rolname = 'bookfinder_crawler';
SELECT count(*) AS member_of_count FROM pg_auth_members WHERE member = 'bookfinder_crawler'::regrole;
