using System;
using System.Text.Json;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AiProfile : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "book_ai_profiles",
                columns: table => new
                {
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    summary = table.Column<string>(type: "text", nullable: true),
                    framework = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    key_topics = table.Column<string[]>(type: "text[]", nullable: true),
                    target_audience = table.Column<string>(type: "text", nullable: true),
                    difficulty = table.Column<short>(type: "smallint", nullable: true),
                    source_content_hash = table.Column<string>(type: "char(64)", nullable: false),
                    model_name = table.Column<string>(type: "varchar(100)", nullable: false),
                    prompt_version = table.Column<string>(type: "varchar(32)", nullable: false),
                    updated_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_book_ai_profiles", x => x.book_id);
                    table.CheckConstraint("ck_book_ai_profiles_difficulty", "difficulty BETWEEN 1 AND 5");
                    table.ForeignKey(
                        name: "FK_book_ai_profiles_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "book_ai_profiles");
        }
    }
}
