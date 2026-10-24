-- Reviewed against Docs/data/data-model.md 11.3 for 20261025120000_ContractMultiSourceCatalog (rewrite of book_identifiers).
-- compat.sh runs this after the upgrade and requires zero rows. compat_before.book_identifiers is the copy taken before it.
-- Each SELECT reports one violation of the conversion rules; the first column names the rule:
--   a  an ISBN_10, ISBN_13 or ISBN row before has no ISBN row with the same Book and value after
--   b  an OTHER row before is missing or changed after
--   c  a row after cannot be derived from a row before (an extra row, or a type the conversion never produces)
--   d  an ISBN_10 or ISBN_13 row is still present after
SELECT 'a', b.book_id::text, b.identifier_type, b.identifier_value
FROM compat_before.book_identifiers b
WHERE b.identifier_type IN ('ISBN_10', 'ISBN_13', 'ISBN')
  AND NOT EXISTS (
    SELECT 1 FROM book_identifiers a
    WHERE a.book_id = b.book_id AND a.identifier_type = 'ISBN' AND a.identifier_value = b.identifier_value)
UNION ALL
SELECT 'b', b.book_id::text, b.identifier_type, b.identifier_value
FROM compat_before.book_identifiers b
WHERE b.identifier_type = 'OTHER'
  AND NOT EXISTS (
    SELECT 1 FROM book_identifiers a
    WHERE a.book_id = b.book_id AND a.identifier_type = 'OTHER' AND a.identifier_value = b.identifier_value)
UNION ALL
SELECT 'c', a.book_id::text, a.identifier_type, a.identifier_value
FROM book_identifiers a
WHERE NOT EXISTS (
    SELECT 1 FROM compat_before.book_identifiers b
    WHERE b.book_id = a.book_id
      AND b.identifier_value = a.identifier_value
      AND ((a.identifier_type = 'ISBN' AND b.identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13'))
        OR (a.identifier_type = 'OTHER' AND b.identifier_type = 'OTHER')))
UNION ALL
SELECT 'd', a.book_id::text, a.identifier_type, a.identifier_value
FROM book_identifiers a
WHERE a.identifier_type IN ('ISBN_10', 'ISBN_13');
