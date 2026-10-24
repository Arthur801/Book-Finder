-- Representative data for the schema at 20261024160045_MultiSourceCatalog (the latest migration).
-- Why: compat.sh loads this into a database migrated to the last applied migration, upgrades it, and checks that
-- every row survives. It covers every table, max-length strings, NULLs in each nullable column and check-constraint
-- boundaries. Data is fictional; password_hash is a placeholder, not a credential.
-- Old writers (v0.0.4) insert only source_type and new writers only source_code; both shapes are covered here, and the
-- 010 triggers fill the other column. source_providers is seeded by the migration itself, so it is not repeated here.
-- Maintenance: after a release with new migrations is deployed, add a seed named after the new last migration id.
BEGIN;

INSERT INTO books (id, title, subtitle, publisher, published_date, published_date_precision, language, description, table_of_contents, page_count, thumbnail_url, created_at, updated_at) VALUES
  ('10000000-0000-0000-0000-000000000001', repeat('長', 500), repeat('副', 500), repeat('出', 255), '2024-03-15', 'DAY', 'zh-TW', repeat('簡介文字。', 200), E'第一章 開始\n第二章 進階', 1, 'https://example.invalid/thumb/1.jpg', '2026-01-05 08:00:00+08', '2026-01-05 08:00:00+08'),
  ('10000000-0000-0000-0000-000000000002', '測試書籍二', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-01-05 08:00:00+08', '2026-01-05 08:00:00+08'),
  ('10000000-0000-0000-0000-000000000003', 'Clean Architecture 中譯本', NULL, '測試出版社', '2020-01-01', 'YEAR', 'en', '英文與中文混合 mixed text', '', 2147483647, NULL, '2026-01-06 09:00:00+08', '2026-01-06 09:00:00+08'),
  ('10000000-0000-0000-0000-000000000004', '第四本書', '副標', '博客來測試出版社', '2019-07-01', 'MONTH', 'zh-CN', NULL, E'目錄\n附錄', 320, 'https://example.invalid/thumb/4.jpg', '2026-01-07 10:00:00+08', '2026-01-07 10:00:00+08');

INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at) VALUES
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'BOOKS_COM_TW', 'DJ0000000001', 'https://www.books.com.tw/products/0010000001', '2026-01-05 08:00:00+08', '2026-01-05 08:00:00+08'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', 'GOOGLE_BOOKS', repeat('g', 255), 'https://books.google.invalid/books?id=' || repeat('g', 200), '2026-01-05 08:00:00+08', '2026-01-08 08:00:00+08'),
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', 'BOOKS_COM_TW', NULL, 'https://www.books.com.tw/products/0010000002', '2026-01-05 08:00:00+08', '2026-01-05 08:00:00+08');

INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at) VALUES
  ('20000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000003', 'GOOGLE_BOOKS', 'abc-XYZ-3', 'https://books.google.invalid/books?id=abc-XYZ-3', '2026-01-06 09:00:00+08', '2026-01-06 09:00:00+08'),
  ('20000000-0000-0000-0000-000000000005', '10000000-0000-0000-0000-000000000004', 'BOOKS_COM_TW', 'DJ0000000004', 'https://www.books.com.tw/products/0010000004', '2026-01-07 10:00:00+08', '2026-01-07 10:00:00+08');

INSERT INTO book_offers (source_id, currency, price, list_price, availability, captured_at) VALUES
  ('20000000-0000-0000-0000-000000000001', 'TWD', 320.00, 380.00, 'IN_STOCK', '2026-10-20 03:00:00+08'),
  ('20000000-0000-0000-0000-000000000005', NULL, NULL, NULL, 'UNKNOWN', '2026-10-20 03:00:00+08');

INSERT INTO bestsellers (rank, book_id, source_id, captured_at) VALUES
  (1, '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '2026-10-20 03:00:00+08'),
  (42, '10000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000005', '2026-10-20 03:00:00+08'),
  (100, '10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000003', '2026-10-20 03:00:00+08');

INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES
  ('10000000-0000-0000-0000-000000000001', 'ISBN_13', '9786263100001'),
  ('10000000-0000-0000-0000-000000000001', 'OTHER', repeat('o', 64)),
  ('10000000-0000-0000-0000-000000000003', 'ISBN_10', '0132350882'),
  ('10000000-0000-0000-0000-000000000004', 'ISBN', '9786263100002');

INSERT INTO book_subjects (book_id, subject, source_type) VALUES
  ('10000000-0000-0000-0000-000000000001', '程式設計', 'BOOKS_COM_TW'),
  ('10000000-0000-0000-0000-000000000003', repeat('主', 255), 'GOOGLE_BOOKS');

INSERT INTO book_subjects (book_id, subject, source_code) VALUES
  ('10000000-0000-0000-0000-000000000001', 'Programming', 'GOOGLE_BOOKS');

INSERT INTO book_contributors (book_id, contributor_order, name, role) VALUES
  ('10000000-0000-0000-0000-000000000001', 1, '作者甲', 'AUTHOR'),
  ('10000000-0000-0000-0000-000000000001', 2, '譯者乙', 'TRANSLATOR'),
  ('10000000-0000-0000-0000-000000000001', 3, 'Original Name', 'ORIGINAL_AUTHOR'),
  ('10000000-0000-0000-0000-000000000001', 4, '編輯丙', 'EDITOR'),
  ('10000000-0000-0000-0000-000000000001', 5, '繪者丁', 'ILLUSTRATOR'),
  ('10000000-0000-0000-0000-000000000001', 6, '其他戊', 'OTHER'),
  ('10000000-0000-0000-0000-000000000003', 32767, repeat('名', 255), 'AUTHOR');

INSERT INTO book_ai_profiles (book_id, summary, framework, key_topics, target_audience, difficulty, source_content_hash, model_name, prompt_version, updated_at) VALUES
  ('10000000-0000-0000-0000-000000000001', '適合入門的測試摘要。', '{"type":"lesson","steps":[1,2]}'::jsonb, ARRAY['測試', '架構'], '初學者', 1, repeat('a', 64), repeat('m', 100), repeat('v', 32), '2026-01-09 11:00:00+08'),
  ('10000000-0000-0000-0000-000000000002', NULL, NULL, NULL, NULL, NULL, repeat('b', 64), 'model-b', 'v1', '2026-01-09 11:00:00+08'),
  ('10000000-0000-0000-0000-000000000003', '進階摘要', NULL, '{}', NULL, 5, repeat('c', 64), 'model-c', 'v2', '2026-01-09 11:00:00+08');

INSERT INTO book_embeddings (book_id, embedding, model_name, source_content_hash, updated_at) VALUES
  ('10000000-0000-0000-0000-000000000001', (SELECT array_agg(sin(i)::real ORDER BY i) FROM generate_series(1, 1536) AS i)::vector, 'text-embedding-3-small', repeat('d', 64), '2026-01-10 12:00:00+08'),
  ('10000000-0000-0000-0000-000000000003', (SELECT array_agg(cos(i)::real ORDER BY i) FROM generate_series(1, 1536) AS i)::vector, repeat('e', 100), repeat('f', 64), '2026-01-10 12:00:00+08');

INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at) VALUES
  ('40000000-0000-0000-0000-000000000001', repeat('e', 64) || '@' || repeat('d', 239) || '.example.invalid', 'seed-placeholder-hash', repeat('名', 100), '2026-01-04 07:00:00+08', '2026-01-04 07:00:00+08'),
  ('40000000-0000-0000-0000-000000000002', 'user2@example.invalid', 'seed-placeholder-hash', '使用者二', '2026-01-04 07:00:00+08', '2026-01-04 07:00:00+08'),
  ('40000000-0000-0000-0000-000000000003', 'User3@Example.invalid', 'seed-placeholder-hash', 'User Three', '2026-01-04 07:00:00+08', '2026-01-04 07:00:00+08');

INSERT INTO user_books (user_id, book_id, reading_status, rating, added_at, updated_at) VALUES
  ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'FINISHED', 5, '2026-01-11 13:00:00+08', '2026-01-12 13:00:00+08'),
  ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002', 'WANT_TO_READ', NULL, '2026-01-11 13:00:00+08', '2026-01-11 13:00:00+08'),
  ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003', 'READING', 1, '2026-01-11 13:00:00+08', '2026-01-13 13:00:00+08'),
  ('40000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', 'READING', NULL, '2026-01-14 14:00:00+08', '2026-01-14 14:00:00+08'),
  ('40000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000004', 'FINISHED', 3, '2026-01-15 15:00:00+08', '2026-01-15 15:00:00+08');

INSERT INTO recommendation_searches (id, user_id, requirement_text, fallback_used, created_at) VALUES
  ('50000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', repeat('我想找一本關於架構的書。', 40), FALSE, '2026-01-16 16:00:00+08'),
  ('50000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000002', 'short', TRUE, '2026-01-16 17:00:00+08'),
  ('50000000-0000-0000-0000-000000000003', '40000000-0000-0000-0000-000000000001', E'多行\n需求', TRUE, '2026-01-16 18:00:00+08');

INSERT INTO recommendation_results (search_id, rank, book_id, relevance_score, reason) VALUES
  ('50000000-0000-0000-0000-000000000001', 1, '10000000-0000-0000-0000-000000000001', 9.99999, repeat('理由', 50)),
  ('50000000-0000-0000-0000-000000000001', 2, '10000000-0000-0000-0000-000000000004', 0.00001, '次之的理由'),
  ('50000000-0000-0000-0000-000000000001', 10, '10000000-0000-0000-0000-000000000003', NULL, '排名最後的理由'),
  ('50000000-0000-0000-0000-000000000002', 1, '10000000-0000-0000-0000-000000000002', NULL, 'fallback 理由');

COMMIT;
