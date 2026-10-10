using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class Bestseller : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "bestsellers",
                columns: table => new
                {
                    rank = table.Column<short>(type: "smallint", nullable: false),
                    book_id = table.Column<Guid>(type: "uuid", nullable: false),
                    source_id = table.Column<Guid>(type: "uuid", nullable: false),
                    captured_at = table.Column<DateTime>(type: "timestamptz", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_bestsellers", x => x.rank);
                    table.CheckConstraint("ck_bestsellers_rank", "rank BETWEEN 1 AND 100");
                    table.ForeignKey(
                        name: "FK_bestsellers_book_sources_source_id",
                        column: x => x.source_id,
                        principalTable: "book_sources",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_bestsellers_books_book_id",
                        column: x => x.book_id,
                        principalTable: "books",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_bestsellers_book_id",
                table: "bestsellers",
                column: "book_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_bestsellers_source_id",
                table: "bestsellers",
                column: "source_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "bestsellers");
        }
    }
}
