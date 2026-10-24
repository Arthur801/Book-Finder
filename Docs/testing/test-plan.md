# Test Plan

> Path: `Docs/testing/test-plan.md`
> Authority: 測試分層、工具、外部依賴處理、各風險等級的最低測試要求
> 各模組的具體驗證項目見該模組文件的 Validation 章節。

## 1. 原則

1. **測試中絕不呼叫真實外部服務**：OpenAI、Google Books、博客來一律以 fake / fixture 取代。
2. 測試絕不連線開發或 production 資料庫；整合測試使用 Testcontainers 拋棄式資料庫。
3. 測試名稱使用 `CONTEXT.md` 的詞彙；可引用需求編號（例：`REC_06_drops_books_outside_candidate_set`）。

## 2. 分層

| 層 | 工具 | 範圍 | 位置 |
|---|---|---|---|
| Unit | xUnit | 純規則：ISBN 判定與正規化、filter JSON → 查詢條件、排序結果驗證、評分 / 狀態驗證、returnUrl 檢查 | `tests/UnitTests` |
| Integration | xUnit + Testcontainers（`pgvector/pgvector:0.8.7-pg17`） | Schema / constraint、Repository、一般搜尋 SQL、向量檢索與門檻、Bestseller 讀取、Library CRUD、Recommendation 全流程（搭配 fake adapter） | `tests/DatabaseIntegration`（已存在）及後續整合測試 project |
| Web | xUnit + `WebApplicationFactory` + Testcontainers | 認證 cookie、antiforgery、401 / 404 / 429、ProblemDetails 格式、PRG 重導；目前已覆蓋首頁、暢銷榜頁與共用版面 | `tests/WebIntegration`（骨架已建立，其餘項目後續補上） |
| Crawler | pytest + 存下來的博客來 HTML fixtures + 拋棄式 PostgreSQL | 排行榜與詳細頁解析、重試 / 跳過 / 上限、Bestseller 替換 transaction | `crawler/tests/` |
| E2E 瀏覽器 | — | MVP 不做 | |

## 3. 外部服務替身

| 服務 | 替身 | 要求 |
|---|---|---|
| OpenAI | 實作 Application 層介面的 fake，回傳預設的解析 / 排序 / embedding / profile 結果 | 可設定回傳非候選編號、超過 10 筆、拋出錯誤、逾時；可斷言是否被呼叫 |
| Google Books | 同上 | 可設定回傳含 / 不含 ISBN 的 volume、拋出錯誤；可斷言是否被呼叫 |
| 博客來 | `crawler/tests/fixtures/*.html` | 至少包含：完整排行榜、不足 100 筆的排行榜、有 / 無目錄與頁數的詳細頁、缺 title 的詳細頁 |

Embedding fake 回傳可控向量（例：固定維度 1536、由測試指定相似度），以驗證門檻邏輯。

WebIntegration 以 `Embedding:BackfillEnabled=false` 關閉背景補齊，以 `FakeEmbeddingGenerator` 取代 generator，並由測試直接呼叫 `EmbeddingBackfillService.RunOnceAsync` 觸發一輪。

## 4. 依風險等級的最低要求

對應 `AGENTS.md` §4.1。

| Risk | 最低測試 |
|---|---|
| L1 | build 通過；改到的頁面可渲染 |
| L2 | build + 受影響模組 unit + 相關 integration |
| L3 | 上述 + 負面 / 邊界案例（見各模組 Validation）+ contract 對照（`data-model.md` / `api-spec.md`） |
| L4 | 上述 + staging / dry run + rollback 計畫（見 `deployment.md`） |

## 5. 必須永遠成立的測試（regression guard）

| 規則 | 測試 |
|---|---|
| SEARCH-01 | 一般搜尋查無結果時 Google Books fake 未被呼叫 |
| REC-01 | 未登入時所有外部 fake 未被呼叫 |
| REC-03 | Candidate Set ≥ 5 時 Google Books fake 未被呼叫 |
| REC-06 | 排序結果不含 Candidate Set 外的 Book，且 ≤ 10 |
| REC-11 | 達上限時所有外部 fake 未被呼叫 |
| CRAWL-05 | 計數規則以 `RunLedger` 單元測試涵蓋（`crawler/tests/test_ledger.py`，不需資料庫）：連續錯誤計數只由 `RankingDecision` 決定（`crawler.md` §14.2、§14.3）——`ERROR_SKIP` 與 `DUPLICATE_BOOK` +1，`ADMITTED` 與 `RESTRICTED_SKIP` 歸零；連續 20 本仍繼續、21 本立即中止（含第 21 本落在 rank 100）；累計錯誤無上限；上限 0（first_book）。資料保護以 DB 整合測試涵蓋：中止時 Bestseller 不變、之後的排名不再請求、中止前已 commit 的 Catalog 寫入保留（含既有 Source 的 `last_seen_at` touch，不回滾）；交錯 50 本錯誤仍替換；重試後成功只計一次結果。PR3 前的現行測試仍斷言舊規則（中止時既有 `last_seen_at` 不變），由 PR3 改寫 |
| data-model §12 | constraint 測試（`tests/DatabaseIntegration/constraints.sql`） |

## 6. 執行

```text
dotnet test                 # 需本機 Docker（Testcontainers）
cd crawler && pytest

# 與 CI 的 Lint and format 相同
dotnet format Book-Finder.slnx --verify-no-changes
cd crawler && ruff check . && ruff format --check .
```

CI 由 `.github/workflows/` 定義，PR 與 push 到 `main` 時執行；CD（`cd.yml`）只在 `v*` tag 與手動 dispatch 時執行：

- `CI` workflow（同時以 `workflow_call` 被 CD 呼叫，於發布前測試同一個 tag）：
  - `.NET build and tests`：build 後執行所有 .NET 測試（整合測試以 Testcontainers 啟動 pgvector），trx 結果上傳為 artifact。
  - `Crawler tests`：安裝 .NET SDK 以產生 EF schema（`crawler/tests/conftest.py`），安裝 Playwright Chromium 後執行 pytest，JUnit XML 上傳為 artifact。
  - `Lint and format`：
    - `dotnet format --verify-no-changes`；
    - `check_version_sync.py`（dotnet-ef 與 EF Core、測試 pgvector image 與 `compose.yaml` 必須一致；`Dockerfile` 的 `DOTNET_SDK_VERSION` 必須等於 `global.json`）；
    - `check_migrations.py --released-manifest`：已發布的 migration 原始檔不能修改（以最新 release 的 `migrations.txt` 比對，N5）；禁止 `suppressTransaction` 與 `CONCURRENTLY`；
    - ruff：`crawler`；`.github/scripts`（與 crawler 共用 `crawler/ruff.toml`）；`deploy`（`deploy/ruff.toml`，目標 py312）；
    - `pytest .github/scripts/tests deploy/tests -q`（Python 3.14）與 `python -m pytest deploy/tests -q`（Python 3.12，對應 Ubuntu 24.04 的 host 環境）；
    - `shellcheck` 覆蓋 `deploy/release`、`deploy/smoke`、`deploy/lib` 與 `deploy/migration-test/compat.sh`。
  - `Docker image`：以 `docker build` 建置 web image（不推送），執行 `deploy/smoke/web-smoke.sh`，並以 `--control-no-keys` 作為對照組（移除共用的 data protection keys 後，antiforgery 必須失敗）。同一 job 再執行 `deploy/integration/imagetools-roundtrip.sh`：以本機 registry（`127.0.0.1`，無 mock）驗證 CD 的 release tag 步驟（`docker buildx imagetools create --prefer-index=false`）保留 digest，並含對照組（不加旗標時單一 manifest 來源會被包成新 index）；log 的 `INFO source shape` 顯示 GitHub runner 產生的 image 形式（index 或 manifest）。
  - `Migration compat check`（僅 PR）：`Infrastructure/Persistence/Migrations/`、`deploy/migration-test`、`deploy/lib`、`deploy/smoke`、`deploy/release`、`Dockerfile`、`.dockerignore` 有變動時才執行，見 §6.1。
- `CodeQL` workflow：對 csharp、python、actions 做程式碼掃描，於 PR、push 到 `main` 與每週一排程時執行。
- `CD` workflow（`.github/workflows/cd.yml`）：
  - 觸發：`v*` tag push（commit 必須在 `origin/main` 上）建置並發布；`workflow_dispatch`（只能從 `main`，指定已發布的 `release_tag`，可加 `cutover`）只部署、不建置。
  - Job：`guard` → `test`（呼叫 `ci.yml`）→ `build`（image、attestation、Immutable Release）或 `resolve`（驗證已發布的 `release.json` 與 attestation）→ `plan`（`production-plan` environment，唯讀）→ `compat` → `deploy`（`production` environment，required reviewer 核准後才連到 host）。
  - 失敗的 job 不會被自動重試；`indeterminate` 結果需人工處理（`deploy/README.md` §5.1）。
- .NET SDK 由根目錄 `global.json` 固定在 10.0.1xx feature band（`version: 10.0.113`、`rollForward: latestPatch`）：CI 的 setup-dotnet 安裝該 band 的最新 patch；本機須為 10.0.1xx 且不低於 10.0.113。升 band 需手動修改 `global.json`；Dependabot 不管理此檔，以免本機 apt 安裝的 SDK 落後而無法建置。
- Dependabot 每週更新 nuget、pip、github-actions、docker、docker-compose 與根目錄 `Dockerfile` 的依賴。
- `main` 由 ruleset 保護：必須經 PR 合併，且 `.NET build and tests`、`Crawler tests`、`Lint and format` 通過、CodeQL 無 high 以上告警才能合併。
- CI 不使用任何 secret。CD 使用 environment secret（SSH key 與 `SSH_KNOWN_HOSTS`）與 GitHub Token，設定見 `deploy/README.md` §2.8。

### 6.1 Migration compat check

目的：證明目標版本能在 production 目前已套用的資料庫上運作。實作：`deploy/migration-test/compat.sh`，分支規則：`deploy/lib/compat_plan.sh`。

依 A（production 已套用的 migration）與目標 T 的關係分類（`manifest.sh` 的 chain 規則）：

| 分類 | 條件 | 執行內容 | 不執行的內容（report 中標為 skip，附理由） |
|---|---|---|---|
| `in-sync` / `forward` | A 等於或是 T 的前綴 | 以 `schema.rebuild` 的 bundle 重建 A、載入 seed、用 T 的 bundle 升級 | — |
| `schema-ahead` | T 是 A 的前綴（DB 比目標新） | 不執行 T 的 bundle（會降級）；確認 history 與 schema 不被 T 的 web 改動 | 「目標升級」、「升級後 history 等於 T」、「與全新安裝比對」 |
| `divergent` | 其他情況 | 在任何資料庫操作前失敗 | — |

forward / in-sync 的檢查：

| 檢查名稱 | 驗證內容 |
|---|---|
| `applied manifest valid` / `rebuild image manifest valid` / `target image manifest valid` | 三份 manifest 格式正確 |
| `applied vs target classification` | 分類結果 |
| `applied is a prefix of the rebuild manifest` | A 是 rebuild release 的前綴（in-sync / forward） |
| `rebuild reproduces applied history` | 重建後的 `__EFMigrationsHistory` 與 A 相同（A 為空時 skip） |
| `seed loaded` | `deploy/migration-test/seeds/` 的測試資料載入成功 |
| `target upgrade applied` | T 的 efbundle 完成；列出套用的 migration 數 |
| `upgraded history equals target manifest` | 升級後的 history 與 T 相同 |
| `data preserved` | 升級前的每個 table 與 column 在升級後仍存在，且 seed 資料未被改變 |
| `schema matches a fresh install` | 升級後的 schema 與空資料庫用 T 安裝的 schema 相同（pg_dump 正規化後比對，失敗時不會因空輸出而相等） |

schema-ahead 的檢查：`applied history unchanged by target`（T 的 web 啟動後，history 仍等於 A）、`data preserved`、`schema unchanged by target`（dump 前後相同）。

所有分類共同的 smoke（mandatory，失敗會讓整次 compat 失敗）：

| 檢查名稱 | 驗證內容 |
|---|---|
| `forward: container starts` | container 啟動 |
| `forward: GET / with X-Forwarded-Proto: https -> 200` | 帶 `X-Forwarded-Proto: https` 回 200（不跟隨 HTTPS redirect） |
| `forward: GET /account/login issued antiforgery cookie and form token` | 登入頁發出 antiforgery cookie 與表單 token |
| `forward: POST /account/login with bad credentials -> 200` | 錯誤密碼回 200（表單 POST 與 antiforgery 正常） |
| `forward: container logs have no unhandled exception or startup failure` | 容器 log 沒有未處理例外或 host 啟動失敗 |

Runtime smoke（目前在 production 運行的版本，對升級後的 DB 執行）對所有分類都只是 INFO，不會讓 compat 失敗。它的結果寫入 report 的 `runtime_smoke`，供 reviewer 參考。

Report：`compat-report.json`（`schema_version: 1`）包含 `classification`、`pending`、`checks`（每項的 `name`、`result`、`detail`）、`forward_ok` 與 `runtime_smoke`。CI 與 CD 都會在 job summary 顯示逐項結果，並上傳為 artifact。

### 6.2 本機整合測試（`BOOKFINDER_IT=1`）

- 位置：`deploy/tests/integration/test_local_integration.py`，執行：`bash deploy/integration/run-local.sh`（需要本機 Docker；使用 `uv` 時以 Python 3.12 執行）。
- 預設跳過（`BOOKFINDER_IT` 未設為 `1` 時）；**不在 CI 執行**，屬於需要人工執行的檢查。
- 真實的部分：unit body（`deploy-entry --unit-body`，帶 `INVOCATION_ID`）、plan 與 status 入口、`book-finder-admin`、docker、pgvector container、以 `127.0.0.1` 為 registry（image 以真實的 `repository@sha256:` digest 參照）、由本 checkout 建置的 image（加上兩個拋棄式的新增 migration）。
- 替身的部分：AWS（一個回答 SSM 與記錄 RDS snapshot 的可執行檔）、nginx（`deploy/integration/edge_stub.py`）。
- 不涵蓋：`systemd-run` 與 systemd runtime（只能在 EC2 上驗證，見 `deploy/README.md` §7）。
- 所有 docker 物件命名為 `bf-it-*`，module fixture 結束後移除。

| 情境 | 驗證內容 |
|---|---|
| a | forward 升級：snapshot、crawler pause、成功後 crawler 恢復 |
| b | schema-ahead 部署：rebuild 與 target 保留，crawler digest 不變 |
| c | 壞掉的 web image：切換後回滾（exit 1），runtime 恢復 |
| d | migration 失敗：dirty 與 paused 保留，直到 reconcile 與 resume |
| e | 中斷的 run：判定為 indeterminate（exit 8），直到 `resolve-run` |
| probe | `docker compose config` 把 `format: raw` 的 env file 原樣輸出（含 `$`、引號、`#`），不啟動任何服務 |

## 7. Multi-source Catalog 規劃覆蓋（#113）

以下是 #113 系列 PR 必須新增的測試；**目前尚未實作**。「PR」欄為負責實作的 PR（PR2：migration 010 與 Web；PR3：crawler；PR4：migration 011 與 cutover）。規則來源見 `Docs/data/data-model.md` §7、§11 與 `Docs/modules/crawler.md` §6、§10、§14。

| # | 案例 | 層 | PR |
|---|---|---|---|
| 1 | ISBN 對到 0 本 Book 時建立新 Book | Crawler（DB） | PR3 |
| 2 | 對到 1 本時附加 Source 並補 NULL：日期與精度成對補；Book 沒有 AUTHOR 才補 AUTHOR；`updated_at` 只在 books 欄位真的補了值時更新 | Crawler（DB） | PR3 |
| 3 | 對到 2 本以上，或 draft 的兩個 ISBN 各對到不同 Book：建立新 Book，`new_book`、`new_source`、`ambiguous_isbn` 各 +1 | Crawler（DB） | PR3 |
| 4 | 既有 `ISBN_13` 資料與新 draft 的 `ISBN` 對到同一本 Book | Crawler（DB） | PR3 |
| 5 | 附加之後才發現同榜重複：`existing_book`、`attached_source`、`new_source`、`skipped`、`error` 各 +1 | Crawler（ledger + DB） | PR3 |
| 6 | Existing Source 同榜重複：`existing_source`、`skipped`、`error`、consecutive 各 +1，不 reset | Crawler（ledger） | PR3 |
| 7 | 連續 10 個 `ERROR_SKIP`、1 個 `RESTRICTED_SKIP`、再 1 個 `ERROR_SKIP` → `consecutive_error_count = 1` | Crawler（ledger） | PR3 |
| 8 | 011：同一本 Book 同時有 `ISBN_13 X` 與 `ISBN X`，跑完只剩一筆 `ISBN X`，migration 不失敗 | Integration（DB） | PR4 |
| 9 | 010 trigger：只帶 `source_type` 的 INSERT 成功（v0.0.4 寫法）；只帶 `source_code` 的 INSERT 成功；兩值不一致被拒絕；原本的 ISBN_10／13 unique 仍有效 | Integration（DB） | PR2 |
| 10 | 實體 schema（查 `pg_constraint`、`pg_indexes`、`information_schema`）：010 之後 `source_type` 與 `source_code` 並存、`book_subjects` PK 為 `(book_id, subject, source_type)`、UNIQUE `(book_id, subject, source_code)`；011 之後 `source_type` 不存在、PK 為 `(book_id, subject, source_code)` | Integration（DB） | PR2／PR4 |
| 11 | `last_seen_at`：Existing Source 在 abort 或 snapshot 失敗後更新仍保留；New Source 失敗時不寫任何資料；分類榜與 first_book 也會更新 | Crawler（DB） | PR3 |
| 12 | Search 與 Detail：三種 ISBN 類型都讀得到；輸入 `ABC123` 不走 ISBN 搜尋；使用共用 test vectors | Unit + Web | PR2 |
| 13 | PR3 runtime 在 011 上相容：PR3 Web 的 Search、Detail（含去重）、health；PR3 crawler 的 Existing Source 查詢與 touch、ISBN 查詢、寫入新 Source、Bestseller 驗證與替換 | Integration / compat | PR4（gate） |
| 14 | Manual recovery compatibility：011 的 DB 搭配上一個 release 的 Web 與 crawler，手動恢復所需的 smoke 全部通過（CD compat 的 runtime smoke 依 I5 仍只供參考） | Integration / compat | PR4（gate） |
| 15 | Stale 偵測依欄位（`Infrastructure/Persistence/BookMetadata.cs` 的 hash 輸入）：補 AUTHOR、subject 或 description → embedding FindPending 與 profile FindStale 都 stale；補 publisher 或 table_of_contents → 只有 profile stale；只補 published_date、page_count、thumbnail 或 ISBN → 都不要求 stale | Integration（DB） | PR3 |
| 16 | Detail 去重：同一本 Book 有 `ISBN_13 X` 與 `ISBN X` 只顯示一次 `ISBN X`；值不同的 ISBN 全部顯示 | Unit + Web | PR2 |
| 17 | touch 失敗：暫時性錯誤重試後成功；最後仍失敗時每日榜單為 `ERROR_SKIP` + `database_error` 且 run 繼續、分類榜只有該筆失敗、first_book FAILED exit 1；三種模式 `existing_source_count` 不加 1、`last_seen_at` 維持原值 | Crawler（DB） | PR3 |
| 18 | C# 與 Python 讀同一份 `tests/Fixtures/isbn-normalization.json`（完整 `White_Space` 與反例），結果逐 byte 一致 | Unit + Crawler | PR2（C# 與 fixture）／PR3（Python） |
| 19 | Source identity 衝突：`external_id` 與 `source_url` 對到不同 Source 時回報 `source_identity_conflict` 且沒有寫入；URL 漂移時保留既有 URL、記 WARNING、照常 touch | Crawler（DB） | PR3 |
| 20 | 011 ISBN conversion preflight：不同 Book 有相同 ISBN 時仍通過、只回報統計；同一本 Book 的重複值正確去重，預估 row 數與實際一致 | Integration（DB） | PR4 |
| 21 | 每個 PR：`dotnet build`、`dotnet test`、crawler pytest（含 DB integration）、`deploy/tests`、CI compat | 全部 | PR2／PR3／PR4 |

另外：disabled provider 的既有 Book Source 仍出現在 Detail（PR2）；crawler 對 disabled provider 啟動 job 時 exit 2（PR3）。
