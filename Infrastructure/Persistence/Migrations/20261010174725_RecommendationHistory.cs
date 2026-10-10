using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class RecommendationHistory : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "recommendation_searches",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    user_id = table.Column<Guid>(type: "uuid", nullable: true),
                    requirement_text = table.Column<string>(type: "text", nullable: false),
                    fallback_used = table.Column<bool>(type: "boolean", nullable: false),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_recommendation_searches", x => x.id);
                    table.ForeignKey(
                        name: "FK_recommendation_searches_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "recommendation_results",
                columns: table => new
                {
                    search_id = table.Column<Guid>(type: "uuid", nullable: false),
                    rank = table.Column<short>(type: "smallint", nullable: false),
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    relevance_score = table.Column<decimal>(type: "numeric(6,5)", nullable: true),
                    reason = table.Column<string>(type: "text", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_recommendation_results", x => new { x.search_id, x.rank });
                    table.CheckConstraint("ck_recommendation_results_rank", "rank BETWEEN 1 AND 10");
                    table.ForeignKey(
                        name: "FK_recommendation_results_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_recommendation_results_recommendation_searches_search_id",
                        column: x => x.search_id,
                        principalTable: "recommendation_searches",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_results_book_id",
                table: "recommendation_results",
                column: "book_id");

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_results_search_id_book_id",
                table: "recommendation_results",
                columns: new[] { "search_id", "book_id" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_searches_user_id",
                table: "recommendation_searches",
                column: "user_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "recommendation_results");

            migrationBuilder.DropTable(
                name: "recommendation_searches");
        }
    }
}
