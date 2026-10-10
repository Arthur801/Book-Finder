using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class IdentityUserLibrary : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "users",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    email = table.Column<string>(type: "varchar(320)", nullable: false),
                    password_hash = table.Column<string>(type: "text", nullable: false),
                    display_name = table.Column<string>(type: "varchar(100)", nullable: false),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    updated_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_users", x => x.id);
                });

            migrationBuilder.CreateTable(
                name: "user_books",
                columns: table => new
                {
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    reading_status = table.Column<string>(type: "varchar(20)", nullable: false),
                    rating = table.Column<short>(type: "smallint", nullable: true),
                    added_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    updated_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_user_books", x => new { x.user_id, x.book_id });
                    table.CheckConstraint("ck_user_books_rating", "rating BETWEEN 1 AND 5");
                    table.CheckConstraint("ck_user_books_reading_status", "reading_status IN ('WANT_TO_READ', 'READING', 'FINISHED')");
                    table.ForeignKey(
                        name: "FK_user_books_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_user_books_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_user_books_book_id",
                table: "user_books",
                column: "book_id");
            migrationBuilder.Sql("CREATE UNIQUE INDEX ux_users_email_lower ON users (lower(email));");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "user_books");

            migrationBuilder.DropTable(
                name: "users");
        }
    }
}
