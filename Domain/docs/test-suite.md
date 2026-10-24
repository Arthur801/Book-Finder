# Domain 文字測試案例庫

查核：2026-10-24；HEAD `91333c3`。本次只做靜態查核，沒有執行下列測試。已有測試不表示本次已通過。Domain 無獨立測試專案，多數 invariant 在 DB integration 與 Application/contract tests 斷言。

## Fixture、隔離與操作邊界

[PostgresFixture](../../tests/DatabaseIntegration/PostgresFixture.cs) 使用 Testcontainers 的 `pgvector/pgvector:0.8.7-pg17`，每次 run 啟動 disposable DB 並套用 migration，不接 development/production。[constraints.sql](../../tests/DatabaseIntegration/constraints.sql) 的測資與 helpers 在 transaction 中 rollback。其他 store 測試依各自 fixture/transaction 隔離；不要將這份 SQL 套到真實資料庫。資料用 UUID、example.test URL、測試 email，時間用 FakeTimeProvider／UTC 固定值；不使用真實外部服務。

後續具備 .NET 10、Docker 與本機套件／image 時可執行（本文件任務未執行）：

```bash
dotnet test tests/DatabaseIntegration/DatabaseIntegration.csproj --filter 'FullyQualifiedName~SchemaTests|FullyQualifiedName~StoredEnumTests|FullyQualifiedName~ModelSnapshotTests'
dotnet test tests/DatabaseIntegration/DatabaseIntegration.csproj --filter 'FullyQualifiedName~EfLibraryStoreTests|FullyQualifiedName~EfRecommendationStoreTests|FullyQualifiedName~EfBookProfileStoreTests|FullyQualifiedName~EfEmbeddingStoreTests'
dotnet test tests/UnitTests/UnitTests.csproj --filter 'FullyQualifiedName~BookDetailContractTests|FullyQualifiedName~PublishedDateTextTests|FullyQualifiedName~ReadingStatusCodeTests'
```

這些命令會建立 build artifacts，container 可能需要 image pull，因此只作後續入口，不是本次授權操作。

## 案例

### DOM-T01 — nullable metadata 與映射

風險 L3；已有測試，本次未執行。來源：[data-model §6.2/6.8](../../Docs/data/data-model.md)、[SchemaTests](../../tests/DatabaseIntegration/SchemaTests.cs)。Given 新 Book 只給 Title、UTC timestamps，Profile 有 JSON framework、topics、difficulty 3；When Add/SaveChanges、Clear tracker、重讀；Then UUID 非空，DateOnly/UTC/jsonb/text[] roundtrip，缺 description 仍 null。擴充入口：`Ef_mapping_roundtrips_uuid_date_utc_jsonb_array_and_nullable`。不可聲稱 required 拒絕空白 Title；那不是現有斷言。

### DOM-T02 — enum 與 SQL vocabulary

風險 L3；已有測試，本次未執行。來源：[StoredEnum](../../Infrastructure/Persistence/StoredEnum.cs)、[StoredEnumTests](../../tests/DatabaseIntegration/StoredEnumTests.cs)。Given 五組 enum 全值及無效 stored code；When ToStored/FromStored；Then WANT_TO_READ、ISBN_13 等符合詞彙、全值 roundtrip，未知值丟 InvalidOperationException。DB CHECK 另由 DOM-T03 保護，不把 C# enum 型別當自動驗證。

### DOM-T03 — constraints、索引與刪除

風險 L3；已有測試，本次未執行。來源：[data-model §6/10/12](../../Docs/data/data-model.md)、[SchemaTests](../../tests/DatabaseIntegration/SchemaTests.cs)、[constraints.sql](../../tests/DatabaseIntegration/constraints.sql)、[ModelSnapshotTests](../../tests/DatabaseIntegration/ModelSnapshotTests.cs)。Given fixture 已套全部 migration；When 執行 `Schema_constraints_hold`、`Model_matches_migration_snapshot`、`Bestseller_foreign_keys_restrict_deletion`；Then PK/unique/enum/range/FK、expression index 與刪除政策符合 SQL 斷言，測資 rollback。來源和 ISBN unique 要區分 nullable ExternalId partial index 與 OTHER identifier 可跨書重複；不推斷 source/book 複合一致性已由 FK 保證。

### DOM-T04 — 書單冪等、隔離與時間

風險 L2；已有測試，本次未執行。來源：[書單](../../Docs/modules/user-library.md)、[EfLibraryStoreTests](../../tests/DatabaseIntegration/EfLibraryStoreTests.cs)、[LibraryServiceTests](../../tests/UnitTests/LibraryServiceTests.cs)。Given User A/B、Book 與固定 UTC；When A AddAsync 兩次及兩個 context 同時 add，更新 status/rating、空 change、B 更新／刪除 A 的 entry；Then 只一列，初始 WantToRead/null，重複新增不覆寫，AddedAt 不變，真實修改才更新時間，B 不碰 A；缺 Book 回 null、缺 User FK 不冒充 BookNotFound；remove 兩次無錯。對應 store tests 的方法名已逐項存在於 source。

### DOM-T05 — Search/results 原子性

風險 L3；已有測試，本次未執行。來源：[推薦 §8](../../Docs/modules/recommendation.md)、[EfRecommendationStoreTests](../../tests/DatabaseIntegration/EfRecommendationStoreTests.cs)。Given fake clock、合法 user/books，另準備不存在 Book；When SaveAsync 各存零本、正常 ranks、失效 Book result；Then 零本仍有 Search，時間固定，score 五位小數，失敗 result 不留 Search；兩次保存產生不同 ID。入口 `Zero_results_still_saves_the_search_without_result_rows`、`Failed_result_insert_leaves_no_search_row_behind`。Candidate membership 在 service/ranking tests，不是 FK 能驗證。

### DOM-T06 — Profile 與 Embedding 衍生資料

風險 L3；已有測試，本次未執行。來源：[推薦 §9–10](../../Docs/modules/recommendation.md)、[EfBookProfileStoreTests](../../tests/DatabaseIntegration/EfBookProfileStoreTests.cs)、[EfEmbeddingStoreTests](../../tests/DatabaseIntegration/EfEmbeddingStoreTests.cs)。Given Book、matching/stale/missing hash、Profile 可空 framework/topics；When FindStale/Upsert、FindPending/SaveAsync；Then 相同 hash 不重建、缺 Book 忽略、每書單列 upsert，framework 為 is_official_toc/sections，原 description/TOC 不變；embedding 1536 roundtrip、錯維度失敗後同 context 可保存下一本；pending scan 不讀 publisher/TOC。入口 `Upsert_never_changes_the_books_description_or_table_of_contents`、`Wrong_dimension_throws_and_the_same_context_still_saves_the_next_book`、`The_pending_scan_never_selects_publisher_or_table_of_contents`。

### DOM-T07 — 公開內容邊界

風險 L2；部分已有測試，本次未執行，跨其他 DTO 的守門待補強；關聯 DOM-B04。來源：[BOOK-05](../../Docs/requirements/product-requirements.md)、[BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs)。Given BookDetail namespace 下四個 BookDetail* 型別；When 反射公開 properties；Then 無 Description/TableOfContents。這只證明既有守門範圍；後續新增輸出 DTO 應逐個檢查，不直接 serialize entity，User.PasswordHash 也不得外流。

### DOM-T08 — 非匿名搜尋

風險 L3；既有 schema/型別證據，本次未執行；ERD 修正待辦 DOM-B01。來源：[RecommendationSearch](../Entities/RecommendationSearch.cs)、[data-model §6.13](../../Docs/data/data-model.md)、[constraints.sql](../../tests/DatabaseIntegration/constraints.sql)。Given disposable schema 與合法 user；When 試寫 user_id NULL 或不存在的 User；Then NOT NULL/FK 拒絕，合法 user 可保存；ERD 應標必有 User。確認 Guid.Empty 不是 NULL，仍須 FK 判定，不把非 nullable 等同使用者存在。

### DOM-T09 — 出版日期精度

風險 L3；顯示已有測試，本次未執行；DB 成對 policy 待決策／補強，關聯 DOM-B03。來源：[data-model §6.2](../../Docs/data/data-model.md)、[PublishedDateTextTests](../../tests/UnitTests/PublishedDateTextTests.cs)。Given year/month/day 精度與 nullable date；When 既有 PublishedDateText 格式化測試；Then 輸出不把補值日冒充來源確定日期。後續決策需定義 date/precision 各種 null 組合允許矩陣，再補 DB/ingestion 案例；不得先預設所有不成對資料都是既定 bug。

### DOM-T10 — fallback 與 flag

風險 L3；未實作的跨層目標，關聯 DOM-B02。來源：[推薦 §6](../../Docs/modules/recommendation.md)、[RecommendationServiceTests](../../tests/UnitTests/RecommendationServiceTests.cs) 擴充入口、[EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs)。Given fake Google Books 與候選數 4/5、重複 ISBN、低 similarity、外部失敗；When 未來完整推薦入口執行；Then 只有 4 本分支呼叫 fallback，normalize/persist/embed 後依同條件再檢索，重複 ISBN 不生新 Book，低 similarity 不入候選，保存真實 flag；核心推薦在保存前失敗不存 Search；保存後的 difficulty/profile 使用 caller token，取消可傳遞且不回滾已存 Search（詳見 [Application 流程](../../Application/docs/workflow-diagram.md)）。現況 store 固定 false，不能將此案標為已有測試通過。

明確暫緩：ANN 索引與 Work/Edition 雙層不是本次驗收，也沒有授權壓測。靜態、mock、disposable integration 與 production 證據須分開，本文件沒有 live 結果。

互參：[流程](workflow-diagram.md)、[架構](architecture.md)、[待辦](backlog.md)、[歷史](update-history.md)。
