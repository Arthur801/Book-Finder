using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class EnablePgvector : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AlterDatabase()
                .Annotation("Npgsql:PostgresExtension:vector", ",,");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // Npgsql does not emit DROP EXTENSION for a removed annotation. No CASCADE: fails if vector columns remain.
            migrationBuilder.Sql("DROP EXTENSION IF EXISTS vector;");
        }
    }
}
