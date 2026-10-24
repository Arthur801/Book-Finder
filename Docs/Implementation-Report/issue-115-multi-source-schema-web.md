# Issue #115：Multi-source schema 與 Web 讀取端（PR2 phase A、B）

## 背景

- #113 規格定義 multi-source catalog：以 `source_providers` registry 取代 closed `SourceType` enum，ISBN 統一為 `ISBN` 類型，並以 expand（010）→ contract（011）兩階段遷移（`Docs/data/data-model.md` §6、§7、§11）。
- 本次為 PR2 的 Schema 與 Web 部分：migration 010、Domain／EF 改用 `source_code`、Web 讀取三種 ISBN 類型與 provider 顯示名稱。crawler（PR3）與 migration 011（PR4）不在本次範圍。
- 規格依據：`Docs/data/data-model.md` §6.1、§6.5、§7.1、§11.2、§11.4；`Docs/modules/book-catalog.md` §3.2、§4、§4.1；`Docs/testing/test-plan.md` §7。
- 本次沒有 production 部署；CD compat 與 production forward migration 尚未執行。

## 變更檔案

以下 commit hash 取自 `git log --oneline ee29e02..HEAD`。

### Phase A：正規化、schema 與 migration 010

- `2a6966b` feat(catalog): add ISBN normalization protocol and shared fixture
  - `Application/Catalog/IsbnNormalizer.cs`（新增）；`tests/Fixtures/isbn-normalization.json`（新增，73 組 vector）；`tests/UnitTests/IsbnNormalizerTests.cs`（新增）。
- `2c662f5` feat(db): add expand migration 010 for multi-source catalog
  - `Domain/Entities/`：刪除 `SourceType.cs`；新增 `SourceCodes.cs`、`SourceProvider.cs`、`ProviderKind.cs`、`BookOffer.cs`、`OfferAvailability.cs`；`BookSource.cs`、`BookSubject.cs` 改為必填 `SourceCode`；`IdentifierType.cs` 新增 `Isbn`。
  - `Infrastructure/Persistence/Configurations/`：`BookSourceConfiguration.cs`、`BookSubjectConfiguration.cs` 改用 `SourceCode`，不 mapping `source_type`；新增 `SourceProviderConfiguration.cs`、`BookOfferConfiguration.cs`。
  - `Infrastructure/Persistence/Migrations/20261024160045_MultiSourceCatalog.cs`（手寫 operations）、`.Designer.cs`、`AppDbContextModelSnapshot.cs`。
  - `AppDbContext.cs`、`EfBookDetailReader.cs`、`Application/Catalog/BookDetail.cs`、`Models/BookDetailViewModel.cs`（最小編譯修改）。
  - `tests/WebIntegration/CatalogSeed*.cs`、`BookDetailPageTests.cs`、`WebFixture.cs`；`tests/DatabaseIntegration/` 既有測試改用 `SourceCodes`。
- `905c6fc` test(db): cover migration 010 triggers, physical schema and backfill
  - `tests/DatabaseIntegration/MultiSourceCatalogSchemaTests.cs`、`MultiSourceBackfillTests.cs`（新增）；`constraints.sql` 增加 book_offers 與 provider 案例。
- `22bebf5` test(deploy): add CD compat seed for migration 010
  - `deploy/migration-test/seeds/20261024160045_MultiSourceCatalog.sql`（新增）。
- `1be0ace` docs: sync module docs for PR2 phase A multi-source schema（各模組 `docs/`）。

### Phase B：Search 與 Detail 讀取端

- `df57cbf` test(db): assert last_seen_at-only UPDATE passes the 010 trigger（僅在 migration 加註解；新增 DB 測試）。
- `d9d8948` feat(catalog): read ISBN, ISBN-13 and ISBN-10 and provider names on detail
  - `Infrastructure/Persistence/EfBookSearch.cs`：ISBN 模式比對三種類型。
  - `Infrastructure/Persistence/EfBookDetailReader.cs`：讀三種 ISBN 類型；來源以 `source_providers` inner join 取得 `DisplayName`，不以 `enabled` 過濾。
  - `Application/Catalog/BookDetail.cs`：`BookDetailSource` 為 `{Id, SourceCode, ProviderDisplayName, Url, FirstSeenAt}`。
  - `Models/BookDetailViewModel.cs`：ISBN 去重、標籤、連結規則。
  - `tests/UnitTests/BookDetailViewModelTests.cs`（新增）；`tests/WebIntegration/BookDetailPageTests.cs`、`SearchPageTests.cs` 新增案例。
- `5ce9bc3` docs: record PR2 phase B detail and search status。
- `bbe0a0a` refactor(catalog): share ISBN-family types and display priority
  - `Domain/Entities/IsbnIdentifierTypes.cs`（新增）：ISBN 家族與顯示優先序的唯一定義。
  - `EfBookSearch.cs`、`EfBookDetailReader.cs`、`BookDetailViewModel.cs` 改用此定義；`MultiSourceCatalogSchemaTests.cs` 新增 `Physical_constraints_match_the_expand_contract`；migration 標頭註解說明 `IX_book_subjects_source_code` 為 EF 要求的 FK 索引。
- `144802f` docs: fix stale detail and ISBN descriptions and mark test-plan 7 status
  - `Models/docs/`、`Controllers/docs/workflow-diagram.md`、`Docs/testing/test-plan.md` §7 狀態。

## 實作思路

### Migration 010（expand，手寫）

依 R8 與 `data-model.md` §11.4，010 的實體 schema 刻意比 EF runtime model 多出 database-only 的物件，EF 的 `has-pending-model-changes` 只比對 model 與 snapshot，無法證明實體 schema，因此 migration 每一個 operation 都手寫並人工 review：

1. 建立 `source_providers`，寫入四筆（BOOKS_COM_TW、GOOGLE_BOOKS 啟用；KINGSTONE、ESLITE 停用）。`base_url` 使用公開首頁。
2. `book_sources`：新增 `source_code` 為 NULL → 以 `source_type` 回填 → `SET NOT NULL` → FK（RESTRICT）→ 三個索引（`(source_code, source_url)` unique、`(source_code, external_id)` partial unique、`(book_id, source_code)`）。`source_type`、其 check 與舊 unique index 保留。
3. `book_subjects`：同樣的 `source_code` 流程，加上 UNIQUE `(book_id, subject, source_code)`；實體 PK 保留為 `(book_id, subject, source_type)`。另建立 `IX_book_subjects_source_code`，這是 EF 為 source_code FK 要求的索引，保留。
4. 單一 trigger function `multi_source_sync_source_codes()`，掛在兩張表的 BEFORE INSERT OR UPDATE：
   - `source_code` 為 NULL → 由 `source_type` 補上；
   - `source_type` 為 NULL 且 `source_code` 為 `BOOKS_COM_TW` 或 `GOOGLE_BOOKS` → 由 `source_code` 補上；
   - 兩者皆非 NULL 且不同 → `RAISE EXCEPTION ... USING ERRCODE = 'check_violation'`（SQLSTATE 23514）。
   - 其他情況保留 NULL，由 NOT NULL 拒絕（KINGSTONE、ESLITE 在 011 前只能以 source_code 寫入，因此回 SQLSTATE 23502）。
5. `book_identifiers`：check 改為 `identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13', 'OTHER')`；legacy ISBN_10／ISBN_13 partial unique 保留。
6. `book_offers`：建表、FK CASCADE、price 與 list_price 為 `> 0` 或 NULL、availability check。

**Trigger 語意**：舊版 writer（v0.0.4）只寫 `source_type`，新版 writer 只寫 `source_code`，兩者都由 trigger 補齊。source code 在 010 階段不可變：沒有 writer 會更新它；若 UPDATE 改了 source_code 而 source_type 保留舊值，會被拒絕（見 migration 註解）。只更新 `last_seen_at` 的 UPDATE（PR3 的 touch）會通過，由 DB 測試驗證。

**Down() 拒絕執行**：若 `book_identifiers` 內已有 `ISBN` 類型資料，Down 以 `RAISE EXCEPTION` 停止，不刪除資料。這是 best-effort 的反向操作，不是自動 rollback。

### Read model（phase B）

- **一般搜尋**：輸入判定（§3.1，NFKC、去除連字號與空白、長度 10 或 13）不變，仍與寫入端正規化分開。只有 SQL 的 identifier 類型改為三種 ISBN 類型。`ABC123` 不會進入 ISBN 模式。
- **Detail reader**：只讀 ISBN 家族；不排序、不去重。來源以 inner join `source_providers` 取得 `ProviderDisplayName`；join 條件不過濾 `enabled`，disabled provider 既有的來源照常顯示。
- **View model**：擁有去重與排序。同值的 identifier 只顯示優先度最高的標籤（ISBN > ISBN-13 > ISBN-10）；不同值全部保留，排序為優先度後依值；OTHER 不顯示。標籤為「ISBN」「ISBN-13」「ISBN-10」。

## 決策

- **連結順序**：博客來來源在前，第一筆為主要按鈕（文字「在博客來查看完整介紹」），其餘為次要連結（「在博客來查看」）；其他 provider 依讀取順序排在後面，文字為「在 {ProviderDisplayName} 查看」。沒有博客來時，第一個合格來源（任何 provider）為主要按鈕。合格指絕對 http／https URL。
- **去重的擁有者**：只在 view model。reader 不排序，避免兩層都做同一件事。
- **`IsbnIdentifierTypes`**（Domain）：ISBN 家族的唯一定義。`All` 是陣列，搭配 `Contains` 讓 EF 轉換為 SQL `IN`，不需要在 IQueryable 外另外比較。
- **WebFixture reset 排除 `source_providers`**：provider 是 migration 010 寫入的參考資料，`book_sources` 以 FK 依賴它；清空後會使後續測試失敗。`CatalogSeedTests` 改為驗證該表仍有 4 筆。
- **Down() 拒絕執行**：見上。
- **ProductVersion 10.0.13**：snapshot 的 `ProductVersion` 從 10.0.12 變為 10.0.13，因為 `dotnet-tools.json` 固定的 dotnet-ef 為 10.0.13，由工具產生，未手改。

## 執行紀錄（Log）

1. 讀取 #113 規格（data-model §6、§7、§11；book-catalog §3、§4）與 plan 的 PR2 章節。
2. Phase A：先寫 fixture 與 normalizer 測試（red），再實作 normalizer；其後建立 Domain／EF 變更與 migration，並以 `dotnet ef migrations add` 產生骨架後手寫 Up／Down。
3. 發現 WebFixture 的 reset 會清空 `source_providers`，改為排除該表並更新 `CatalogSeedTests`。
4. Phase B：先寫 `BookDetailViewModelTests` 與 WebIntegration 案例（red，編譯失敗），再實作 reader、view model 與 search。
5. 修正一處測試期望：兩個同為 ISBN 類型的值依值排序，而非依輸入順序。
6. Review 後的修正：抽出 `IsbnIdentifierTypes`，補 physical 約束斷言，修正過期的 workflow 圖與 Models 文件，更新 test-plan §7 狀態。

## 驗證結果

| 項目 | 結果 |
|---|---|
| `dotnet build Book-Finder.slnx` | 0 warnings、0 errors（最後一次執行） |
| UnitTests | 813 通過 |
| DatabaseIntegration | 122 通過（含 migration 010 的 9 項：trigger、physical schema、physical constraints、backfill、last_seen_at-only UPDATE） |
| WebIntegration | 281 通過 |
| `dotnet ef migrations has-pending-model-changes` | No changes |
| `dotnet format Book-Finder.slnx --verify-no-changes --no-restore` | 通過（修正一處 `EfBookDetailReader.cs` 縮排後） |
| `.github/scripts/check_migrations.py` | migrations OK（2 項） |
| crawler `../.venv/bin/python -m pytest -q` | 395 通過（最後一次於 phase A 執行；之後未修改 Python） |
| `deploy/tests`（pytest 9.1.1） | 632 通過、7 略過（最後一次於 phase A 執行） |

crawler 的 DB 測試以 `dotnet ef migrations script --idempotent` 產生 schema，因此這 395 項同時證明 crawler 仍寫入 `source_type` 時，trigger 能讓插入成功（v0.0.4 相容）。

## 未解決事項

- **PR3（crawler）**：crawler 仍寫入 `source_type` 與 `ISBN_10`／`ISBN_13`；尚未改為 `source_code`、R1 正規化、last_seen_at、touch 失敗處理、R5 log 計數與 Source identity 衝突處理。`Docs/modules/crawler.md` 的 PR3 列仍為規劃。
- **PR4（migration 011）**：未實作；包括 ISBN 轉換、DROP trigger 與 `source_type`、PK 改為 `(book_id, subject, source_code)`、preflight、gate 與 manual recovery compatibility 測試。
- **同一 release 部署**：PR2 與 PR3 必須以同一個 release tag 部署（`data-model.md` §14）。本次只完成 PR2。
- **第一次 production forward migration**：010 將是 production 第一次執行的 forward migration。執行前需要 CD compat 證據、RDS snapshot 與回滾計畫（`Docs/deployment/deployment.md` §6.1）；本次未執行 production 操作。
- **未重新審查**：Application、Controllers、Views 的 module docs 只更新了與本次變更直接相關的段落；`workflow-diagram.md` 中未描述 ISBN 的部分未逐段檢查。

## Code Review 與修正

依兩軸審查（Standards、Spec）的意見修正：

### Standards

- **ISBN 優先序與判斷式重複**：EfBookSearch、EfBookDetailReader 與 BookDetailViewModel 各自寫了一份 ISBN 類型判斷與優先序。已抽出 `IsbnIdentifierTypes`（Domain），三處共用；reader 移除排序，去重與排序只留在 view model。
- **過期的文件圖與描述**：`Models/docs/workflow-diagram.md`（連結規則與 ISBN 去重）、`Controllers/docs/workflow-diagram.md`（ISBN 三種類型）、`Models/docs/architecture.md`、`Models/docs/test-suite.md` 已更新，並新增 M-T05b 對應 `BookDetailViewModelTests`。

### Spec

- **實體 schema 斷言不足**：新增 `Physical_constraints_match_the_expand_contract`，檢查 source_type 與 source_code 的 NOT NULL、舊 check 保留、source_code FK 為 RESTRICT、identifier check 接受 `ISBN`、book_offers FK 為 CASCADE 與其三項 check。
- **test-plan §7 狀態不正確**：原文寫「目前尚未實作」。已改為逐列標示：PR2 的 #9、#10（010 部分）、#12、#16、#18（C# 部分）與 disabled provider 案例已實作並列出測試位置；PR3、PR4 列仍為規劃。
- **ADR 與 deployment R7／R8**：已於 PR1（#114）完成，本次不需修改。
- **`IX_book_subjects_source_code`**：保留為 EF 要求的 FK 索引，並在 migration 標頭註解說明。
