-- Run only against a disposable database. All fixtures and helpers are rolled back.
BEGIN;
CREATE FUNCTION pg_temp.expect_failure(statement text, expected_state text)
RETURNS void LANGUAGE plpgsql AS $fn$
BEGIN
    BEGIN
        EXECUTE statement;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = expected_state THEN RETURN; END IF;
        RAISE EXCEPTION 'Expected SQLSTATE %, got %: %', expected_state, SQLSTATE, SQLERRM;
    END;
    RAISE EXCEPTION 'Expected SQLSTATE %, but statement succeeded: %', expected_state, statement;
END;
$fn$;
CREATE FUNCTION pg_temp.assert_true(condition boolean, label text)
RETURNS void LANGUAGE plpgsql AS $fn$
BEGIN
    IF condition IS DISTINCT FROM TRUE THEN RAISE EXCEPTION 'Assertion failed: %', label; END IF;
END;
$fn$;
SELECT pg_temp.assert_true(
    (SELECT bool_and(to_regclass(name) IS NOT NULL) FROM unnest(ARRAY[
      'books', 'book_sources', 'book_identifiers', 'book_contributors', 'book_subjects', 'book_ai_profiles',
      'users', 'user_books', 'bestsellers', 'recommendation_searches', 'recommendation_results', 'book_embeddings']) AS name),
    'required application tables');
SELECT pg_temp.assert_true(EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector'), 'vector enabled');
SELECT pg_temp.assert_true('[1,2,3]'::vector <-> '[1,2,3]'::vector = 0, 'vector distance');
SELECT pg_temp.assert_true(
    (SELECT count(*) = 5 FROM pg_indexes WHERE schemaname = 'public' AND indexname IN
     ('ux_users_email_lower', 'ix_book_contributors_name_lower', 'IX_books_publisher',
      'IX_books_published_date', 'IX_recommendation_searches_user_id_created_at')), 'required indexes');
SELECT pg_temp.assert_true(
    EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = 'IX_recommendation_searches_user_id_created_at'
           AND indexdef LIKE '%created_at DESC%'), 'history descending index');
SELECT pg_temp.assert_true(
    EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = 'ux_users_email_lower'
           AND indexdef LIKE 'CREATE UNIQUE INDEX%lower((email)::text)%'), 'unique lower(email) expression index');
SELECT pg_temp.assert_true(
    EXISTS(SELECT 1 FROM pg_indexes WHERE indexname = 'ix_book_contributors_name_lower'
           AND indexdef LIKE '%lower((name)::text)%'), 'lower(name) expression index');
SELECT pg_temp.assert_true(
    (SELECT count(*) = 2 AND bool_and(confdeltype = 'r') FROM pg_constraint
      WHERE conrelid = 'bestsellers'::regclass AND contype = 'f'), 'bestseller FKs restrict deletion');
INSERT INTO books(id, title, page_count, created_at, updated_at) VALUES
 ('00000000-0000-0000-0000-000000000001', 'Test One', 1, now(), now()),
 ('00000000-0000-0000-0000-000000000002', 'Test Two', NULL, now(), now()),
 ('00000000-0000-0000-0000-000000000003', 'Cascade Test', NULL, now(), now()),
 ('00000000-0000-0000-0000-000000000004', 'Bestseller Only', NULL, now(), now());
INSERT INTO users(id, email, password_hash, display_name, created_at, updated_at) VALUES
 ('00000000-0000-0000-0000-000000000101', 'Test@example.test', 'fixture', 'Test', now(), now()),
 ('00000000-0000-0000-0000-000000000102', 'cascade@example.test', 'fixture', 'Cascade', now(), now());
INSERT INTO book_sources(id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at) VALUES
 ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000001', 'BOOKS_COM_TW', NULL, 'https://example.test/1', now(), now()),
 ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-000000000002', 'GOOGLE_BOOKS', 'volume-2', 'https://example.test/2', now(), now()),
 ('00000000-0000-0000-0000-000000000303', '00000000-0000-0000-0000-000000000003', 'BOOKS_COM_TW', NULL, 'https://example.test/3', now(), now()),
 ('00000000-0000-0000-0000-000000000304', '00000000-0000-0000-0000-000000000004', 'BOOKS_COM_TW', NULL, 'https://example.test/4', now(), now());
INSERT INTO book_identifiers(book_id, identifier_type, identifier_value) VALUES
 ('00000000-0000-0000-0000-000000000001', 'ISBN_13', '9780132350884'),
 ('00000000-0000-0000-0000-000000000001', 'ISBN_10', '0132350882'),
 ('00000000-0000-0000-0000-000000000001', 'OTHER', 'shared'),
 ('00000000-0000-0000-0000-000000000002', 'OTHER', 'shared'),
 ('00000000-0000-0000-0000-000000000003', 'OTHER', 'cascade');
INSERT INTO book_contributors(book_id, contributor_order, name, role) VALUES ('00000000-0000-0000-0000-000000000003', 1, 'Test Author', 'AUTHOR');
INSERT INTO book_subjects(book_id, subject, source_type) VALUES ('00000000-0000-0000-0000-000000000003', 'Test', 'BOOKS_COM_TW');
INSERT INTO book_ai_profiles(book_id, difficulty, source_content_hash, model_name, prompt_version, updated_at)
 VALUES ('00000000-0000-0000-0000-000000000003', NULL, repeat('a', 64), 'fixture', 'v1', now());
INSERT INTO book_embeddings(book_id, embedding, model_name, source_content_hash, updated_at)
 VALUES ('00000000-0000-0000-0000-000000000003', array_fill(0.2::real, ARRAY[1536])::vector, 'text-embedding-3-small', repeat('c', 64), now());
-- Each bestseller row uses the same Book's BOOKS_COM_TW source (Docs/modules/crawler.md §9).
INSERT INTO bestsellers(rank, book_id, source_id, captured_at) VALUES
 (1, '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000301', now()),
 (100, '00000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000304', now());
INSERT INTO user_books(user_id, book_id, reading_status, rating, added_at, updated_at) VALUES
 ('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000001','WANT_TO_READ',NULL,now(),now()),
 ('00000000-0000-0000-0000-000000000101','00000000-0000-0000-0000-000000000002','READING',1,now(),now()),
 ('00000000-0000-0000-0000-000000000102','00000000-0000-0000-0000-000000000003','FINISHED',5,now(),now());
INSERT INTO recommendation_searches(id, user_id, requirement_text, fallback_used, created_at) VALUES
 ('00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000101','fixture',false,now()),
 ('00000000-0000-0000-0000-000000000202','00000000-0000-0000-0000-000000000102','cascade',false,now());
INSERT INTO recommendation_results(search_id, book_id, rank, relevance_score, reason) VALUES
 ('00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000001',1,0.12345,'fixture'),
 ('00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000002',10,NULL,'fixture'),
 ('00000000-0000-0000-0000-000000000202','00000000-0000-0000-0000-000000000003',1,NULL,'fixture');
-- unique URL
SELECT pg_temp.expect_failure($stmt$UPDATE book_sources SET source_url='https://example.test/1' WHERE id='00000000-0000-0000-0000-000000000303'$stmt$, '23505');
-- unique external ID
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_sources(id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at) VALUES(gen_random_uuid(),'00000000-0000-0000-0000-000000000001','GOOGLE_BOOKS','volume-2','https://example.test/new',now(),now())$stmt$, '23505');
-- source enum
SELECT pg_temp.expect_failure($stmt$UPDATE book_sources SET source_type='INVALID'$stmt$, '23514');
-- ISBN13 across books
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_identifiers(book_id, identifier_type, identifier_value) VALUES('00000000-0000-0000-0000-000000000002','ISBN_13','9780132350884')$stmt$, '23505');
-- ISBN10 across books
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_identifiers(book_id, identifier_type, identifier_value) VALUES('00000000-0000-0000-0000-000000000002','ISBN_10','0132350882')$stmt$, '23505');
-- identifier enum
SELECT pg_temp.expect_failure($stmt$UPDATE book_identifiers SET identifier_type='INVALID'$stmt$, '23514');
-- case insensitive email
SELECT pg_temp.expect_failure($stmt$INSERT INTO users(id, email, password_hash, display_name, created_at, updated_at) VALUES(gen_random_uuid(),'test@EXAMPLE.test','fixture','Test',now(),now())$stmt$, '23505');
-- rating below boundary
SELECT pg_temp.expect_failure($stmt$UPDATE user_books SET rating=0$stmt$, '23514');
-- rating above boundary
SELECT pg_temp.expect_failure($stmt$UPDATE user_books SET rating=6$stmt$, '23514');
-- reading status
SELECT pg_temp.expect_failure($stmt$UPDATE user_books SET reading_status='INVALID'$stmt$, '23514');
-- user book composite key
SELECT pg_temp.expect_failure($stmt$INSERT INTO user_books SELECT * FROM user_books LIMIT 1$stmt$, '23505');
-- bestseller rank zero
SELECT pg_temp.expect_failure($stmt$UPDATE bestsellers SET rank=0 WHERE rank=1$stmt$, '23514');
-- bestseller rank 101
SELECT pg_temp.expect_failure($stmt$UPDATE bestsellers SET rank=101 WHERE rank=100$stmt$, '23514');
-- bestseller unique book
SELECT pg_temp.expect_failure($stmt$INSERT INTO bestsellers(rank, book_id, source_id, captured_at) VALUES(2,'00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000301',now())$stmt$, '23505');
-- bestseller unique rank (different book, same rank)
SELECT pg_temp.expect_failure($stmt$INSERT INTO bestsellers(rank, book_id, source_id, captured_at) VALUES(1,'00000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000303',now())$stmt$, '23505');
-- result rank zero
SELECT pg_temp.expect_failure($stmt$UPDATE recommendation_results SET rank=0 WHERE rank=1$stmt$, '23514');
-- result rank eleven
SELECT pg_temp.expect_failure($stmt$UPDATE recommendation_results SET rank=11 WHERE rank=10$stmt$, '23514');
-- result unique book
SELECT pg_temp.expect_failure($stmt$INSERT INTO recommendation_results(search_id, book_id, rank, relevance_score, reason) VALUES('00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000001',2,NULL,'duplicate')$stmt$, '23505');
-- result unique rank (different book, same rank)
SELECT pg_temp.expect_failure($stmt$INSERT INTO recommendation_results(search_id, book_id, rank, relevance_score, reason) VALUES('00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000003',1,NULL,'duplicate rank')$stmt$, '23505');
-- AI profile is 1:1 with Book
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_ai_profiles(book_id, difficulty, source_content_hash, model_name, prompt_version, updated_at) VALUES('00000000-0000-0000-0000-000000000003',NULL,repeat('b',64),'fixture','v2',now())$stmt$, '23505');
-- embedding dimension must be exactly 1536 (Docs/data/data-model.md §5.7)
INSERT INTO book_embeddings(book_id, embedding, model_name, source_content_hash, updated_at)
 VALUES ('00000000-0000-0000-0000-000000000001', array_fill(0.1::real, ARRAY[1536])::vector, 'text-embedding-3-small', repeat('c', 64), now());
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_embeddings(book_id, embedding, model_name, source_content_hash, updated_at) VALUES('00000000-0000-0000-0000-000000000002','[1,2,3]'::vector,'text-embedding-3-small',repeat('c',64),now())$stmt$, '22000');
-- one embedding row per Book
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_embeddings(book_id, embedding, model_name, source_content_hash, updated_at) VALUES('00000000-0000-0000-0000-000000000001',array_fill(0.3::real, ARRAY[1536])::vector,'text-embedding-3-small',repeat('d',64),now())$stmt$, '23505');
-- cosine distance operator works on the stored embedding (identical vectors have distance ~0)
SELECT pg_temp.assert_true(
    abs((SELECT embedding FROM book_embeddings WHERE book_id='00000000-0000-0000-0000-000000000001') <=> array_fill(0.1::real, ARRAY[1536])::vector) < 1e-6,
    'cosine distance of identical embeddings is zero');
-- contributor order unique per book
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_contributors(book_id, contributor_order, name, role) VALUES('00000000-0000-0000-0000-000000000003',1,'Other Author','EDITOR')$stmt$, '23505');
-- subject unique per book and source
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_subjects(book_id, subject, source_type) VALUES('00000000-0000-0000-0000-000000000003','Test','BOOKS_COM_TW')$stmt$, '23505');
-- invalid foreign key
SELECT pg_temp.expect_failure($stmt$INSERT INTO book_subjects(book_id, subject, source_type) VALUES('99999999-0000-0000-0000-000000000001','Missing','BOOKS_COM_TW')$stmt$, '23503');
-- null required title
SELECT pg_temp.expect_failure($stmt$UPDATE books SET title=NULL$stmt$, '23502');
-- page count zero
SELECT pg_temp.expect_failure($stmt$UPDATE books SET page_count=0$stmt$, '23514');
-- date precision enum
SELECT pg_temp.expect_failure($stmt$UPDATE books SET published_date_precision='INVALID'$stmt$, '23514');
-- contributor enum
SELECT pg_temp.expect_failure($stmt$UPDATE book_contributors SET role='INVALID'$stmt$, '23514');
-- subject source enum
SELECT pg_temp.expect_failure($stmt$UPDATE book_subjects SET source_type='INVALID'$stmt$, '23514');
-- difficulty zero
SELECT pg_temp.expect_failure($stmt$UPDATE book_ai_profiles SET difficulty=0$stmt$, '23514');
-- difficulty six
SELECT pg_temp.expect_failure($stmt$UPDATE book_ai_profiles SET difficulty=6$stmt$, '23514');
-- bestseller restricts deleting a Book that only the bestseller list references
SELECT pg_temp.expect_failure($stmt$DELETE FROM books WHERE id='00000000-0000-0000-0000-000000000004'$stmt$, '23503');
-- source delete restrict
SELECT pg_temp.expect_failure($stmt$DELETE FROM book_sources WHERE id='00000000-0000-0000-0000-000000000301'$stmt$, '23503');
-- a failing statement during list replacement leaves the previous rows intact (statement/savepoint
-- atomicity only; the crawler's full replace transaction belongs in crawler tests)
SELECT pg_temp.expect_failure($stmt$DELETE FROM bestsellers; INSERT INTO bestsellers(rank, book_id, source_id, captured_at) VALUES(101,'00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000301',now())$stmt$, '23514');
SELECT pg_temp.assert_true((SELECT count(*)=2 FROM bestsellers), 'previous snapshot retained');
UPDATE user_books SET rating=5 WHERE rating IS NULL;
UPDATE books SET published_date_precision='YEAR';
UPDATE book_ai_profiles SET difficulty=1;
UPDATE book_ai_profiles SET difficulty=5;
DELETE FROM users WHERE id='00000000-0000-0000-0000-000000000102';
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM user_books WHERE user_id='00000000-0000-0000-0000-000000000102'), 'user book cascade');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM recommendation_results WHERE search_id='00000000-0000-0000-0000-000000000202'), 'history cascade');
DELETE FROM books WHERE id='00000000-0000-0000-0000-000000000003';
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM book_sources WHERE book_id='00000000-0000-0000-0000-000000000003'), 'source cascade');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM book_identifiers WHERE book_id='00000000-0000-0000-0000-000000000003'), 'identifier cascade');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM book_contributors WHERE book_id='00000000-0000-0000-0000-000000000003'), 'contributor cascade');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM book_subjects WHERE book_id='00000000-0000-0000-0000-000000000003'), 'subject cascade');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM book_ai_profiles WHERE book_id='00000000-0000-0000-0000-000000000003'), 'AI profile cascade');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM book_embeddings WHERE book_id='00000000-0000-0000-0000-000000000003'), 'embedding cascade');
DELETE FROM bestsellers;
-- recommendation search requires a user (data-model 5.11, invariant 16)
SELECT pg_temp.expect_failure($stmt$INSERT INTO recommendation_searches(id, user_id, requirement_text, fallback_used, created_at) VALUES(gen_random_uuid(),NULL,'anonymous',false,now())$stmt$, '23502');
-- recommendation results still restrict deleting a referenced Book
SELECT pg_temp.expect_failure($stmt$DELETE FROM books WHERE id='00000000-0000-0000-0000-000000000001'$stmt$, '23503');
-- with no bestseller reference left, the bestseller-only Book can be deleted
DELETE FROM books WHERE id='00000000-0000-0000-0000-000000000004';
ROLLBACK;
