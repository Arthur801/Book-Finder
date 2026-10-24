// Expand step of the multi-source catalog (Docs/data/data-model.md 11.2 and 11.4). The physical schema below is
// written by hand and reviewed operation by operation: the EF snapshot describes the runtime target model, not this
// database-only state. source_type stays in the database, and EF does not map it, until migration 011 removes it.
// Old writers (v0.0.4) insert only source_type and new writers only source_code; the triggers fill the other column.
using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class MultiSourceCatalog : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // 1. Provider registry (11.2). Rows are seeded here; the crawler only reads them.
            migrationBuilder.CreateTable(
                name: "source_providers",
                columns: table => new
                {
                    code = table.Column<string>(type: "varchar(64)", nullable: false),
                    display_name = table.Column<string>(type: "varchar(100)", nullable: false),
                    provider_kind = table.Column<string>(type: "varchar(24)", nullable: false),
                    base_url = table.Column<string>(type: "text", nullable: true),
                    enabled = table.Column<bool>(type: "boolean", nullable: false, defaultValue: true),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_source_providers", x => x.code);
                    table.CheckConstraint("ck_source_providers_provider_kind", "provider_kind IN ('RETAILER', 'BIBLIOGRAPHIC')");
                });

            migrationBuilder.Sql("""
                INSERT INTO source_providers (code, display_name, provider_kind, base_url, enabled, created_at) VALUES
                  ('BOOKS_COM_TW', '博客來', 'RETAILER', 'https://www.books.com.tw/', true, now()),
                  ('GOOGLE_BOOKS', 'Google Books', 'BIBLIOGRAPHIC', 'https://books.google.com/', true, now()),
                  ('KINGSTONE', '金石堂', 'RETAILER', 'https://www.kingstone.com.tw/', false, now()),
                  ('ESLITE', '誠品', 'RETAILER', 'https://www.eslite.com/', false, now());
                """);

            // 2. book_sources (11.2): add source_code, backfill it from source_type, then make it NOT NULL and add the
            //    foreign key and the indexes. source_type, its check constraint and its old unique indexes are kept.
            migrationBuilder.AddColumn<string>(
                name: "source_code",
                table: "book_sources",
                type: "varchar(64)",
                nullable: true);

            migrationBuilder.Sql("UPDATE book_sources SET source_code = source_type WHERE source_code IS NULL;");

            migrationBuilder.Sql("ALTER TABLE book_sources ALTER COLUMN source_code SET NOT NULL;");

            migrationBuilder.AddForeignKey(
                name: "FK_book_sources_source_providers_source_code",
                table: "book_sources",
                column: "source_code",
                principalTable: "source_providers",
                principalColumn: "code",
                onDelete: ReferentialAction.Restrict);

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_source_code_source_url",
                table: "book_sources",
                columns: new[] { "source_code", "source_url" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_source_code_external_id",
                table: "book_sources",
                columns: new[] { "source_code", "external_id" },
                unique: true,
                filter: "external_id IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_book_id_source_code",
                table: "book_sources",
                columns: new[] { "book_id", "source_code" });

            // 3. book_subjects (11.2): the physical primary key stays (book_id, subject, source_type). The new
            //    runtime key is enforced by UNIQUE (book_id, subject, source_code).
            migrationBuilder.AddColumn<string>(
                name: "source_code",
                table: "book_subjects",
                type: "varchar(64)",
                nullable: true);

            migrationBuilder.Sql("UPDATE book_subjects SET source_code = source_type WHERE source_code IS NULL;");

            migrationBuilder.Sql("ALTER TABLE book_subjects ALTER COLUMN source_code SET NOT NULL;");

            migrationBuilder.AddForeignKey(
                name: "FK_book_subjects_source_providers_source_code",
                table: "book_subjects",
                column: "source_code",
                principalTable: "source_providers",
                principalColumn: "code",
                onDelete: ReferentialAction.Restrict);

            migrationBuilder.AddUniqueConstraint(
                name: "UX_book_subjects_book_id_subject_source_code",
                table: "book_subjects",
                columns: new[] { "book_id", "subject", "source_code" });

            migrationBuilder.CreateIndex(
                name: "IX_book_subjects_source_code",
                table: "book_subjects",
                column: "source_code");

            // 4. Two-way sync triggers (11.4). Both tables have source_type and source_code, so one function serves both.
            //    A missing value is filled from the other column; a source_type-only row is only mapped for the two
            //    legacy codes, so KINGSTONE and ESLITE rows stay NULL in source_type and NOT NULL rejects them until 011.
            //    A mismatch raises check_violation (SQLSTATE 23514). BEFORE triggers run before NOT NULL and CHECK.
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

            // 5. book_identifiers (11.2): allow ISBN. The legacy ISBN_10 / ISBN_13 partial unique index is kept as is.
            migrationBuilder.DropCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers");

            migrationBuilder.AddCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers",
                sql: "identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13', 'OTHER')");

            // 6. book_offers (11.2, 6.4): current snapshot table for retailer sources. No writer yet.
            migrationBuilder.CreateTable(
                name: "book_offers",
                columns: table => new
                {
                    source_id = table.Column<Guid>(type: "uuid", nullable: false),
                    currency = table.Column<string>(type: "char(3)", nullable: true),
                    price = table.Column<decimal>(type: "numeric(12,2)", nullable: true),
                    list_price = table.Column<decimal>(type: "numeric(12,2)", nullable: true),
                    availability = table.Column<string>(type: "varchar(24)", nullable: false),
                    captured_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_book_offers", x => x.source_id);
                    table.CheckConstraint("ck_book_offers_availability", "availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'PREORDER', 'UNKNOWN')");
                    table.CheckConstraint("ck_book_offers_list_price", "list_price > 0");
                    table.CheckConstraint("ck_book_offers_price", "price > 0");
                    table.ForeignKey(
                        name: "FK_book_offers_book_sources_source_id",
                        column: x => x.source_id,
                        principalTable: "book_sources",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // Best-effort reverse of Up. It refuses to run when rows exist that the pre-010 schema cannot represent
            // (ISBN identifiers written by the new runtime), so it never deletes data silently.
            migrationBuilder.Sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM book_identifiers WHERE identifier_type = 'ISBN') THEN
                        RAISE EXCEPTION 'cannot reverse 010: book_identifiers contains ISBN rows';
                    END IF;
                END;
                $$;
                """);

            migrationBuilder.DropTable(
                name: "book_offers");

            migrationBuilder.DropCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers");

            migrationBuilder.AddCheckConstraint(
                name: "ck_book_identifiers_identifier_type",
                table: "book_identifiers",
                sql: "identifier_type IN ('ISBN_10', 'ISBN_13', 'OTHER')");

            migrationBuilder.Sql("""
                DROP TRIGGER IF EXISTS trg_book_subjects_sync_source_codes ON book_subjects;
                DROP TRIGGER IF EXISTS trg_book_sources_sync_source_codes ON book_sources;
                DROP FUNCTION IF EXISTS multi_source_sync_source_codes();
                """);

            migrationBuilder.DropIndex(
                name: "IX_book_subjects_source_code",
                table: "book_subjects");

            migrationBuilder.DropUniqueConstraint(
                name: "UX_book_subjects_book_id_subject_source_code",
                table: "book_subjects");

            migrationBuilder.DropForeignKey(
                name: "FK_book_subjects_source_providers_source_code",
                table: "book_subjects");

            migrationBuilder.DropColumn(
                name: "source_code",
                table: "book_subjects");

            migrationBuilder.DropIndex(
                name: "IX_book_sources_book_id_source_code",
                table: "book_sources");

            migrationBuilder.DropIndex(
                name: "IX_book_sources_source_code_external_id",
                table: "book_sources");

            migrationBuilder.DropIndex(
                name: "IX_book_sources_source_code_source_url",
                table: "book_sources");

            migrationBuilder.DropForeignKey(
                name: "FK_book_sources_source_providers_source_code",
                table: "book_sources");

            migrationBuilder.DropColumn(
                name: "source_code",
                table: "book_sources");

            migrationBuilder.DropTable(
                name: "source_providers");
        }
    }
}
