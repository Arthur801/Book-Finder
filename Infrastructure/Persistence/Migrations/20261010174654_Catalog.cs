using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class Catalog : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "books",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    title = table.Column<string>(type: "varchar(500)", nullable: false),
                    subtitle = table.Column<string>(type: "varchar(500)", nullable: true),
                    publisher = table.Column<string>(type: "varchar(255)", nullable: true),
                    published_date = table.Column<DateOnly>(type: "date", nullable: true),
                    published_date_precision = table.Column<string>(type: "varchar(8)", nullable: true),
                    language = table.Column<string>(type: "varchar(16)", nullable: true),
                    description = table.Column<string>(type: "text", nullable: true),
                    table_of_contents = table.Column<string>(type: "text", nullable: true),
                    page_count = table.Column<int>(type: "integer", nullable: true),
                    thumbnail_url = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    updated_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_books", x => x.id);
                    table.CheckConstraint("ck_books_page_count", "page_count > 0");
                    table.CheckConstraint("ck_books_published_date_precision", "published_date_precision IN ('YEAR', 'MONTH', 'DAY')");
                });

            migrationBuilder.CreateTable(
                name: "book_contributors",
                columns: table => new
                {
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    contributor_order = table.Column<short>(type: "smallint", nullable: false),
                    name = table.Column<string>(type: "varchar(255)", nullable: false),
                    role = table.Column<string>(type: "varchar(32)", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_book_contributors", x => new { x.book_id, x.contributor_order });
                    table.CheckConstraint("ck_book_contributors_role", "role IN ('AUTHOR', 'ORIGINAL_AUTHOR', 'TRANSLATOR', 'EDITOR', 'ILLUSTRATOR', 'OTHER')");
                    table.ForeignKey(
                        name: "FK_book_contributors_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "book_identifiers",
                columns: table => new
                {
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    identifier_type = table.Column<string>(type: "varchar(16)", nullable: false),
                    identifier_value = table.Column<string>(type: "varchar(64)", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_book_identifiers", x => new { x.book_id, x.identifier_type, x.identifier_value });
                    table.CheckConstraint("ck_book_identifiers_identifier_type", "identifier_type IN ('ISBN_10', 'ISBN_13', 'OTHER')");
                    table.ForeignKey(
                        name: "FK_book_identifiers_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "book_sources",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    source_type = table.Column<string>(type: "varchar(32)", nullable: false),
                    external_id = table.Column<string>(type: "varchar(255)", nullable: true),
                    source_url = table.Column<string>(type: "text", nullable: false),
                    first_seen_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    last_seen_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_book_sources", x => x.id);
                    table.CheckConstraint("ck_book_sources_source_type", "source_type IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS')");
                    table.ForeignKey(
                        name: "FK_book_sources_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "book_subjects",
                columns: table => new
                {
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    subject = table.Column<string>(type: "varchar(255)", nullable: false),
                    source_type = table.Column<string>(type: "varchar(32)", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_book_subjects", x => new { x.book_id, x.subject, x.source_type });
                    table.CheckConstraint("ck_book_subjects_source_type", "source_type IN ('BOOKS_COM_TW', 'GOOGLE_BOOKS')");
                    table.ForeignKey(
                        name: "FK_book_subjects_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_book_identifiers_identifier_type_identifier_value",
                table: "book_identifiers",
                columns: new[] { "identifier_type", "identifier_value" },
                unique: true,
                filter: "identifier_type IN ('ISBN_10', 'ISBN_13')");

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_book_id",
                table: "book_sources",
                column: "book_id");

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_source_type_external_id",
                table: "book_sources",
                columns: new[] { "source_type", "external_id" },
                unique: true,
                filter: "external_id IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "IX_book_sources_source_type_source_url",
                table: "book_sources",
                columns: new[] { "source_type", "source_url" },
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "book_contributors");

            migrationBuilder.DropTable(
                name: "book_identifiers");

            migrationBuilder.DropTable(
                name: "book_sources");

            migrationBuilder.DropTable(
                name: "book_subjects");

            migrationBuilder.DropTable(
                name: "books");
        }
    }
}
