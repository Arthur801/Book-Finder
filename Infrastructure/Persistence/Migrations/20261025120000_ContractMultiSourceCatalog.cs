// Contract step of the multi-source catalog (Docs/data/data-model.md 11.3). Written by hand after the EF scaffold: the
// EF diff only sees the runtime model, so the book_subjects primary key and the source_type removal are spelled out here.
// Up runs in the migration transaction. Its guard raises before any change, so a failed gate leaves the database at 010.
using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class ContractMultiSourceCatalog : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // 0. Self-guard (11.3 gates 4 and 5, and the identifier vocabulary). Nothing has changed yet, so a RAISE here
            //    rolls the whole migration back and the database stays at 010.
            migrationBuilder.Sql("""
                DO $$
                DECLARE
                    bad bigint;
                BEGIN
                    SELECT count(*) INTO bad FROM book_sources WHERE source_code IS NULL;
                    IF bad > 0 THEN
                        RAISE EXCEPTION 'migration 011 gate 4 failed: % book_sources rows have a NULL source_code', bad;
                    END IF;

                    SELECT count(*) INTO bad FROM book_subjects WHERE source_code IS NULL;
                    IF bad > 0 THEN
                        RAISE EXCEPTION 'migration 011 gate 4 failed: % book_subjects rows have a NULL source_code', bad;
                    END IF;

                    -- Gate 5: the source_type that the 010 trigger maps for each source_code. Other codes have no legacy value,
                    -- so any source_type on them is a mismatch.
                    SELECT count(*) INTO bad FROM book_sources
                    WHERE source_type IS DISTINCT FROM (CASE source_code
                        WHEN 'BOOKS_COM_TW' THEN 'BOOKS_COM_TW'
                        WHEN 'GOOGLE_BOOKS' THEN 'GOOGLE_BOOKS'
                        ELSE NULL END);
                    IF bad > 0 THEN
                        RAISE EXCEPTION 'migration 011 gate 5 failed: % book_sources rows have source_type different from source_code', bad;
                    END IF;

                    SELECT count(*) INTO bad FROM book_subjects
                    WHERE source_type IS DISTINCT FROM (CASE source_code
                        WHEN 'BOOKS_COM_TW' THEN 'BOOKS_COM_TW'
                        WHEN 'GOOGLE_BOOKS' THEN 'GOOGLE_BOOKS'
                        ELSE NULL END);
                    IF bad > 0 THEN
                        RAISE EXCEPTION 'migration 011 gate 5 failed: % book_subjects rows have source_type different from source_code', bad;
                    END IF;

                    SELECT count(*) INTO bad FROM book_identifiers
                    WHERE identifier_type NOT IN ('ISBN', 'ISBN_10', 'ISBN_13', 'OTHER');
                    IF bad > 0 THEN
                        RAISE EXCEPTION 'migration 011 failed: % book_identifiers rows have an unknown identifier_type', bad;
                    END IF;
                END;
                $$;
                """);

            // 1. book_identifiers (11.3): convert ISBN_10 / ISBN_13 to ISBN. ON CONFLICT DO NOTHING removes the duplicates
            //    that appear when one Book already has the same value as ISBN. Different Books may share an ISBN value.
            migrationBuilder.Sql("""
                INSERT INTO book_identifiers (book_id, identifier_type, identifier_value)
                SELECT book_id, 'ISBN', identifier_value FROM book_identifiers
                WHERE identifier_type IN ('ISBN_10', 'ISBN_13')
                ON CONFLICT DO NOTHING;

                DELETE FROM book_identifiers WHERE identifier_type IN ('ISBN_10', 'ISBN_13');
                """);

            // 2. book_identifiers: the legacy partial unique index covered only ISBN_10 / ISBN_13 and is now empty of
            //    meaning; the check narrows to the target vocabulary.
            migrationBuilder.DropIndex(
                name: "IX_book_identifiers_identifier_type_identifier_value",
                table: "book_identifiers");

            migrationBuilder.DropCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers");

            migrationBuilder.AddCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers",
                sql: "identifier_type IN ('ISBN', 'OTHER')");

            // 3. Sync triggers and their function go first, so nothing writes source_type while it is removed.
            migrationBuilder.Sql("""
                DROP TRIGGER IF EXISTS trg_book_subjects_sync_source_codes ON book_subjects;
                DROP TRIGGER IF EXISTS trg_book_sources_sync_source_codes ON book_sources;
                DROP FUNCTION IF EXISTS multi_source_sync_source_codes();
                """);

            // 4. book_sources: the legacy indexes and check reference source_type, so they go before the column does.
            migrationBuilder.DropIndex(
                name: "IX_book_sources_source_type_external_id",
                table: "book_sources");

            migrationBuilder.DropIndex(
                name: "IX_book_sources_source_type_source_url",
                table: "book_sources");

            migrationBuilder.DropCheckConstraint(
                name: "ck_book_sources_source_type",
                table: "book_sources");

            migrationBuilder.DropColumn(
                name: "source_type",
                table: "book_sources");

            // 5. book_subjects: the key moves from (book_id, subject, source_type) to (book_id, subject, source_code). The
            //    UNIQUE (book_id, subject, source_code) from 010 becomes the primary key, so it is dropped as redundant.
            migrationBuilder.DropUniqueConstraint(
                name: "UX_book_subjects_book_id_subject_source_code",
                table: "book_subjects");

            migrationBuilder.DropPrimaryKey(
                name: "PK_book_subjects",
                table: "book_subjects");

            migrationBuilder.DropCheckConstraint(
                name: "ck_book_subjects_source_type",
                table: "book_subjects");

            migrationBuilder.DropColumn(
                name: "source_type",
                table: "book_subjects");

            migrationBuilder.AddPrimaryKey(
                name: "PK_book_subjects",
                table: "book_subjects",
                columns: new[] { "book_id", "subject", "source_code" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // Restores the 010 physical schema (data-model 11.2, 11.4). Converted ISBN rows cannot be turned back into
            // ISBN_10 or ISBN_13 (the 010 Book had both values as one row each, and the 011 Up merged them), so they stay as
            // ISBN. Rows whose source_code has no 010 source_type (KINGSTONE, ESLITE) cannot be represented and refuse the reverse.
            migrationBuilder.Sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM book_sources WHERE source_code NOT IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS'))
                       OR EXISTS (SELECT 1 FROM book_subjects WHERE source_code NOT IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS')) THEN
                        RAISE EXCEPTION 'cannot reverse 011: a source_code has no 010 source_type (KINGSTONE or ESLITE)';
                    END IF;
                END;
                $$;
                """);

            // 5 (reverse). book_subjects: source_type back in front of the 010 primary key and its UNIQUE.
            migrationBuilder.DropPrimaryKey(
                name: "PK_book_subjects",
                table: "book_subjects");

            migrationBuilder.AddColumn<string>(
                name: "source_type",
                table: "book_subjects",
                type: "varchar(32)",
                nullable: true);

            migrationBuilder.Sql("UPDATE book_subjects SET source_type = source_code;");

            migrationBuilder.AlterColumn<string>(
                name: "source_type",
                table: "book_subjects",
                type: "varchar(32)",
                nullable: false,
                oldClrType: typeof(string),
                oldType: "varchar(32)",
                oldNullable: true);

            migrationBuilder.AddCheckConstraint(
                name: "ck_book_subjects_source_type",
                table: "book_subjects",
                sql: "source_type IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS')");

            migrationBuilder.AddPrimaryKey(
                name: "PK_book_subjects",
                table: "book_subjects",
                columns: new[] { "book_id", "subject", "source_type" });

            migrationBuilder.AddUniqueConstraint(
                name: "UX_book_subjects_book_id_subject_source_code",
                table: "book_subjects",
                columns: new[] { "book_id", "subject", "source_code" });

            // 4 (reverse). book_sources: source_type, its check and the two 010 unique indexes.
            migrationBuilder.AddColumn<string>(
                name: "source_type",
                table: "book_sources",
                type: "varchar(32)",
                nullable: true);

            migrationBuilder.Sql("UPDATE book_sources SET source_type = source_code;");

            migrationBuilder.AlterColumn<string>(
                name: "source_type",
                table: "book_sources",
                type: "varchar(32)",
                nullable: false,
                oldClrType: typeof(string),
                oldType: "varchar(32)",
                oldNullable: true);

            migrationBuilder.AddCheckConstraint(
                name: "ck_book_sources_source_type",
                table: "book_sources",
                sql: "source_type IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS')");

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_source_type_source_url",
                table: "book_sources",
                columns: new[] { "source_type", "source_url" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_source_type_external_id",
                table: "book_sources",
                columns: new[] { "source_type", "external_id" },
                unique: true,
                filter: "external_id IS NOT NULL");

            // 3 (reverse). The 010 sync triggers and their function, as created by 010.
            migrationBuilder.Sql("""
                CREATE FUNCTION multi_source_sync_source_codes() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.source_code IS NULL THEN
                        NEW.source_code := NEW.source_type;
                    END IF;
                    IF NEW.source_type IS NULL AND NEW.source_code IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS') THEN
                        NEW.source_type := NEW.source_code;
                    END IF;
                    IF NEW.source_type IS NOT NULL AND NEW.source_code IS NOT NULL AND NEW.source_type <> NEW.source_code THEN
                        RAISE EXCEPTION 'source_type % does not match source_code %', NEW.source_type, NEW.source_code
                            USING ERRCODE = 'check_violation';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                """);

            migrationBuilder.Sql("""
                CREATE TRIGGER trg_book_sources_sync_source_codes BEFORE INSERT OR UPDATE ON book_sources
                    FOR EACH ROW EXECUTE FUNCTION multi_source_sync_source_codes();
                CREATE TRIGGER trg_book_subjects_sync_source_codes BEFORE INSERT OR UPDATE ON book_subjects
                    FOR EACH ROW EXECUTE FUNCTION multi_source_sync_source_codes();
                """);

            // 2 (reverse). book_identifiers: the 010 check and the legacy partial unique index. The index is empty here, since
            //    the Up removed every ISBN_10 / ISBN_13 row and the reverse does not bring them back.
            migrationBuilder.DropCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers");

            migrationBuilder.AddCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers",
                sql: "identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13', 'OTHER')");

            migrationBuilder.CreateIndex(
                name: "IX_book_identifiers_identifier_type_identifier_value",
                table: "book_identifiers",
                columns: new[] { "identifier_type", "identifier_value" },
                unique: true,
                filter: "identifier_type IN ('ISBN_10', 'ISBN_13')");
        }
    }
}
