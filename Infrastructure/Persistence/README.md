# Local PostgreSQL persistence

The schema follows `Docs/data/data-model.md`. EF Core owns migrations; the Python
crawler must not create tables or run DDL. Connection strings remain in development
User Secrets or deployment environment configuration.

## Apply to the local database

From the repository root, with `ConnectionStrings:DefaultConnection` pointing to
`localhost`, database `book_finder`:

```bash
docker compose up -d db
dotnet tool restore
dotnet build
dotnet ef migrations script
dotnet ef database update
dotnet ef migrations list
dotnet ef migrations has-pending-model-changes
```

The migrations enable pgvector and create 12 application tables. `book_embeddings`
stores one retrieval embedding per Book as `vector(1536)` (OpenAI
`text-embedding-3-small`), with a cascading FK to `books`. Required non-vector indexes
are already included; no ANN index is created (MVP uses exact vector search).

Expression indexes on `lower(email)` and `lower(name)` are implemented explicitly
in migration SQL, since they cannot be represented by ordinary EF property indexes.
Review these SQL statements when modifying the corresponding columns; a snapshot
comparison alone cannot validate expression indexes.

Catalog child rows (`book_identifiers`, `book_contributors`, `book_subjects`) cascade
on Book deletion. Bestseller references restrict deletion of Books and BookSources.
These deletion rules are specified in `Docs/data/data-model.md` §11.1.

This work establishes schema constraints, not application normalization or product
flows. ISBN checksum/normalization, source merging, Candidate Set membership, and
complete TOP 100 validation still belong in the relevant services/crawler tests.
Separate runtime DB roles and table permissions are not provisioned here; the
existing development account is used for migrations.

## Database tests

`tests/DatabaseIntegration` is an xUnit project. It needs only a running Docker
engine: Testcontainers starts a throwaway `pgvector/pgvector:0.8.7-pg17` container,
applies all migrations, and removes the container afterwards. No User Secrets or
local database are used.

```bash
dotnet test
```

- `StoredEnumTests` (no Docker): enum ↔ stored string mapping and generated CHECK SQL
  match the data-model vocabulary (`BOOKS_COM_TW`, `WANT_TO_READ`, ...).
- `ModelSnapshotTests` (no Docker): the EF model matches the migration snapshot;
  bestseller FKs restrict deletion.
- `SchemaTests`: all migrations applied; EF roundtrips for UUID/date/UTC/jsonb/
  arrays/nullable fields. Recommendation searches always belong to a user
  (`user_id` NOT NULL, no anonymous searches).
- `constraints.sql` (run by `SchemaTests`): required tables, vector operations,
  required and expression indexes, unique/composite/1:1 keys, enum/range/null/FK
  constraints, cascade/restrict deletion, and statement-level atomicity of a failed
  bestseller replacement. Fixtures are rolled back.

If Docker Hub returns `Unauthorized` while pulling `testcontainers/ryuk`, run
`docker pull` for that image once (or `docker logout`) to bypass stale credentials.
