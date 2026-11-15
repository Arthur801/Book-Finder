using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddEmailVerificationAndAccountTokens : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<int>(
                name: "auth_version",
                table: "users",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<DateTime>(
                name: "email_verified_at",
                table: "users",
                type: "timestamptz",
                nullable: true);

            // U-01: every account that exists before verification is treated as verified. Accounts created later are set by the code.
            migrationBuilder.Sql("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL;");

            migrationBuilder.CreateTable(
                name: "account_action_tokens",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    purpose = table.Column<string>(type: "varchar(32)", nullable: false),
                    token_hash = table.Column<string>(type: "char(64)", nullable: false),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    expires_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    consumed_at = table.Column<DateTime>(type: "timestamptz", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_account_action_tokens", x => x.id);
                    table.CheckConstraint("ck_account_action_tokens_purpose", "purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET')");
                    table.CheckConstraint("ck_account_action_tokens_token_hash", "token_hash ~ '^[0-9a-f]{64}$'");
                    table.ForeignKey(
                        name: "FK_account_action_tokens_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_account_action_tokens_token_hash",
                table: "account_action_tokens",
                column: "token_hash",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_account_action_tokens_user_id_purpose_created_at",
                table: "account_action_tokens",
                columns: new[] { "user_id", "purpose", "created_at" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "account_action_tokens");

            migrationBuilder.DropColumn(
                name: "auth_version",
                table: "users");

            migrationBuilder.DropColumn(
                name: "email_verified_at",
                table: "users");
        }
    }
}
