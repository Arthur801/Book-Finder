-- P2（plan v12 §10）：crawler DB 帳號權限檢查。唯讀：只有 SELECT 與 SHOW，不改任何資料或權限。
-- 以 crawler 帳號連線執行：psql -X -v ON_ERROR_STOP=1 -f p2-crawler-privileges.sql
\pset pager off
BEGIN READ ONLY;

\echo '== 1. 帳號與伺服器 =='
SELECT current_user, session_user, current_database(), current_setting('server_version') AS server_version;

\echo '== 2. 角色屬性（預期全部 false） =='
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolinherit
FROM pg_roles WHERE rolname = current_user;

\echo '== 3. 所屬角色（rds_superuser 或 table owner 角色都不應出現） =='
SELECT r.rolname AS member_of, m.admin_option
FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = current_user)
ORDER BY 1;

\echo '== 4. 資料庫與 schema 的 DDL 權限（預期 create 皆 false） =='
SELECT has_database_privilege(current_user, current_database(), 'CREATE') AS db_create,
       has_database_privilege(current_user, current_database(), 'TEMP')   AS db_temp,
       has_schema_privilege(current_user, 'public', 'CREATE')            AS public_create,
       has_schema_privilege(current_user, 'public', 'USAGE')             AS public_usage;

\echo '== 5. crawler 擁有的物件（預期 0 列；owner 可以 ALTER／DROP） =='
SELECT n.nspname, c.relname, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE pg_has_role(current_user, c.relowner, 'USAGE') AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY 1, 2;

\echo '== 6. 各表權限（public schema 全部表；crawler 只需下方「需要」欄位） =='
WITH needed(tbl, need) AS (VALUES
    ('books',             'SELECT, INSERT, UPDATE'),
    ('book_sources',      'SELECT, INSERT, UPDATE'),
    ('book_identifiers',  'SELECT, INSERT'),
    ('book_contributors', 'SELECT, INSERT'),
    ('book_subjects',     'INSERT'),
    ('bestsellers',       'INSERT, DELETE'),
    ('source_providers',  'SELECT'))
SELECT c.relname AS tbl,
       has_table_privilege(current_user, c.oid, 'SELECT')     AS sel,
       has_table_privilege(current_user, c.oid, 'INSERT')     AS ins,
       has_table_privilege(current_user, c.oid, 'UPDATE')     AS upd,
       has_table_privilege(current_user, c.oid, 'DELETE')     AS del,
       has_table_privilege(current_user, c.oid, 'TRUNCATE')   AS trunc,
       has_table_privilege(current_user, c.oid, 'REFERENCES') AS refs,
       has_table_privilege(current_user, c.oid, 'TRIGGER')    AS trig,
       coalesce(nd.need, '（不需要）')                         AS need
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN needed nd ON nd.tbl = c.relname
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
ORDER BY nd.need IS NULL, c.relname;

\echo '== 7. sequence 權限（若有） =='
SELECT c.relname AS seq,
       has_sequence_privilege(current_user, c.oid, 'USAGE')  AS usage,
       has_sequence_privilege(current_user, c.oid, 'SELECT') AS sel,
       has_sequence_privilege(current_user, c.oid, 'UPDATE') AS upd
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'S'
ORDER BY 1;

\echo '== 8. advisory lock 函式可執行（migration lock 的 shared 側） =='
SELECT has_function_privilege(current_user, 'pg_try_advisory_lock_shared(bigint)', 'EXECUTE') AS lock_shared,
       has_function_privilege(current_user, 'pg_advisory_unlock_shared(bigint)', 'EXECUTE')   AS unlock_shared;

ROLLBACK;
