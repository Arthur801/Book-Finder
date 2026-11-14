using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddCanonicalCategories : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "canonical_categories",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    slug = table.Column<string>(type: "varchar(100)", nullable: false),
                    display_name = table.Column<string>(type: "varchar(100)", nullable: false),
                    sort_order = table.Column<int>(type: "int", nullable: false),
                    is_active = table.Column<bool>(type: "boolean", nullable: false, defaultValue: true),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    updated_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_canonical_categories", x => x.id);
                    table.CheckConstraint("ck_canonical_categories_slug", "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'");
                });

            migrationBuilder.CreateTable(
                name: "provider_category_mappings",
                columns: table => new
                {
                    source_code = table.Column<string>(type: "varchar(64)", nullable: false),
                    subject = table.Column<string>(type: "varchar(255)", nullable: false),
                    provider_root_subject = table.Column<string>(type: "varchar(255)", nullable: false),
                    canonical_category_id = table.Column<Guid>(type: "uuid", nullable: false),
                    mapping_method = table.Column<string>(type: "varchar(24)", nullable: false),
                    updated_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_provider_category_mappings", x => new { x.source_code, x.subject });
                    table.CheckConstraint("ck_provider_category_mappings_mapping_method", "mapping_method IN ('MANUAL', 'VERIFIED_RULE')");
                    table.ForeignKey(
                        name: "FK_provider_category_mappings_canonical_categories_category_id",
                        column: x => x.canonical_category_id,
                        principalTable: "canonical_categories",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_provider_category_mappings_source_providers_source_code",
                        column: x => x.source_code,
                        principalTable: "source_providers",
                        principalColumn: "code",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_book_subjects_source_code_subject",
                table: "book_subjects",
                columns: new[] { "source_code", "subject" });

            migrationBuilder.CreateIndex(
                name: "IX_canonical_categories_slug",
                table: "canonical_categories",
                column: "slug",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_provider_category_mappings_category_source_subject",
                table: "provider_category_mappings",
                columns: new[] { "canonical_category_id", "source_code", "subject" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "provider_category_mappings");

            migrationBuilder.DropTable(
                name: "canonical_categories");

            migrationBuilder.DropIndex(
                name: "IX_book_subjects_source_code_subject",
                table: "book_subjects");
        }
    }
}
