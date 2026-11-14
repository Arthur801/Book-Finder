using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddRecommendationJobs : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "recommendation_jobs",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    requirement_text = table.Column<string>(type: "text", nullable: false),
                    status = table.Column<string>(type: "varchar(20)", nullable: false),
                    search_id = table.Column<Guid>(type: "uuid", nullable: true),
                    attempt_count = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    run_after = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    lease_token = table.Column<Guid>(type: "uuid", nullable: true),
                    lease_expires_at = table.Column<DateTime>(type: "timestamptz", nullable: true),
                    idempotency_key = table.Column<string>(type: "varchar(128)", nullable: true),
                    request_hash = table.Column<string>(type: "char(64)", nullable: false),
                    error_code = table.Column<string>(type: "varchar(64)", nullable: true),
                    created_at = table.Column<DateTime>(type: "timestamptz", nullable: false),
                    started_at = table.Column<DateTime>(type: "timestamptz", nullable: true),
                    completed_at = table.Column<DateTime>(type: "timestamptz", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_recommendation_jobs", x => x.id);
                    table.CheckConstraint("ck_recommendation_jobs_attempt_count", "attempt_count >= 0");
                    table.CheckConstraint("ck_recommendation_jobs_idempotency_key", "idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$'");
                    table.CheckConstraint("ck_recommendation_jobs_lease", "(status = 'RUNNING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'RUNNING' AND lease_token IS NULL AND lease_expires_at IS NULL)");
                    table.CheckConstraint("ck_recommendation_jobs_outcome", "(status = 'SUCCEEDED' AND search_id IS NOT NULL AND completed_at IS NOT NULL AND error_code IS NULL) OR (status = 'FAILED' AND search_id IS NULL AND completed_at IS NOT NULL AND error_code IS NOT NULL) OR (status IN ('QUEUED', 'RUNNING') AND search_id IS NULL AND completed_at IS NULL)");
                    table.CheckConstraint("ck_recommendation_jobs_request_hash", "request_hash ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("ck_recommendation_jobs_status", "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')");
                    table.ForeignKey(
                        name: "FK_recommendation_jobs_recommendation_searches_search_id",
                        column: x => x.search_id,
                        principalTable: "recommendation_searches",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_recommendation_jobs_users_user_id",
                        column: x => x.user_id,
                        principalTable: "users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_jobs_search_id",
                table: "recommendation_jobs",
                column: "search_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_jobs_status_lease_expires_at",
                table: "recommendation_jobs",
                columns: new[] { "status", "lease_expires_at" });

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_jobs_status_run_after_created_at",
                table: "recommendation_jobs",
                columns: new[] { "status", "run_after", "created_at" });

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_jobs_user_id_created_at",
                table: "recommendation_jobs",
                columns: new[] { "user_id", "created_at" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "IX_recommendation_jobs_user_id_idempotency_key",
                table: "recommendation_jobs",
                columns: new[] { "user_id", "idempotency_key" },
                unique: true,
                filter: "idempotency_key IS NOT NULL");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "recommendation_jobs");
        }
    }
}
