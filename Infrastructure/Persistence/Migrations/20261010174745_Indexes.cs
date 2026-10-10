using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class Indexes : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // EF Core does not model expression indexes; maintain them in migration SQL.
            migrationBuilder.Sql("CREATE INDEX ix_book_contributors_name_lower ON book_contributors (lower(name));");
            migrationBuilder.DropIndex(
                name: "IX_recommendation_searches_user_id",
                table: "recommendation_searches");

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_searches_user_id_created_at",
                table: "recommendation_searches",
                columns: new[] { "user_id", "created_at" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "IX_books_published_date",
                table: "books",
                column: "published_date");

            migrationBuilder.CreateIndex(
                name: "IX_books_publisher",
                table: "books",
                column: "publisher");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("DROP INDEX ix_book_contributors_name_lower;");
            migrationBuilder.DropIndex(
                name: "IX_recommendation_searches_user_id_created_at",
                table: "recommendation_searches");

            migrationBuilder.DropIndex(
                name: "IX_books_published_date",
                table: "books");

            migrationBuilder.DropIndex(
                name: "IX_books_publisher",
                table: "books");

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_searches_user_id",
                table: "recommendation_searches",
                column: "user_id");
        }
    }
}
