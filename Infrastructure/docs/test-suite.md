# Infrastructure AI 文字測試案例庫

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 查核日期：2026-10-24；基準 `91333c3`。本次只做文件靜態檢查，未執行 build、測試、migration、部署或外部服務。

## 共用 fixture 與隔離

Authority：[test plan](../../Docs/testing/test-plan.md)、[data model](../../Docs/data/data-model.md)、[Identity](../../Docs/modules/identity-auth.md)、[Recommendation](../../Docs/modules/recommendation.md)、[Catalog](../../Docs/modules/book-catalog.md)、[Library](../../Docs/modules/user-library.md)、[Bestseller](../../Docs/modules/bestseller.md)、[Deployment](../../Docs/deployment/deployment.md)。

以下「已有測試」均指檔案有可執行斷言，**本次未執行**。不代表 live OpenAI、production DB 或 TLS 證據。測資使用 A/B 兩個 GUID 使用者與不重疊 BookIds；固定 UTC TimeProvider；測試獨立資料前後清理，不能連開發／production DB。

- [PostgresFixture](../../tests/DatabaseIntegration/PostgresFixture.cs)：Testcontainers `pgvector/pgvector:0.8.7-pg17`、UseVector、MigrateAsync；可掛 SQL interceptor 計數／查 projection；拋棄容器，無 User Secrets。
- [WebFixture](../../tests/WebIntegration/WebFixture.cs)：WebApplicationFactory、拋棄 DB、fake AI；停用背景 backfill／profile 自動外呼，精確測例主動觸發。
- [OpenAiTestTransport](../../tests/UnitTests/OpenAiTestTransport.cs)：攔截 SDK HTTP，提供 JSON／拒答／錯誤，不能使用真 key。
- vector fixture 為 1536 維非零向量，明確設計 threshold 正好命中／略低於；不用隨機浮點猜相似度。Cache 使用新 MemoryCache／RecordingMemoryCache；worker 以可控 clock 與 cancellation 結束，不用實際等待十分鐘。

## INF-T01 — Schema 與 mapping

- 責任／風險／狀態：EF schema，L3，已有測試本次未執行。
- 規格：data-model §6、§10–12。
- Given：全新 disposable pgvector DB；無任何應用表。
- When：fixture 執行 `db.Database.MigrateAsync()`，執行 SchemaTests／ModelSnapshotTests／StoredEnumTests。
- Then：12 application tables、vector extension、vector(1536)、required／expression indexes、enum／range／NULL／unique／FK／cascade-restrict 均符合；錯誤維度或 rating 越界寫入被拒；不存在 model snapshot drift。Expression indexes 需 constraints.sql，不能只驗 snapshot。
- 入口：[SchemaTests](../../tests/DatabaseIntegration/SchemaTests.cs)、[constraints.sql](../../tests/DatabaseIntegration/constraints.sql)、[ModelSnapshotTests](../../tests/DatabaseIntegration/ModelSnapshotTests.cs)。

## INF-T02 — Cookie JWT、雜湊與使用者 lookup

- 責任／風險／狀態：Identity adapter，L3，已有測試本次未執行；規格 Identity §3–5、ADR-004。
- Given：固定 time、測試 signing key 至少 32 bytes；User A 儲存混合大小寫 email；測試 password 僅 fixture。
- When：Issue(A)、驗證 token claims／signature；以不同大小寫查 email；Hash／Verify 密碼；Append／Delete cookie；將 clock 前進到 exp。
- Then：sub=A、HS256、一日 expiry、無 skew；expiry 時失效；email 查到同人且 lower(email) unique 防重複；hash 非明碼、錯密碼失敗；cookie HttpOnly/Secure/Lax/Path=/，delete 屬性匹配。
- 入口：[AuthTokenIssuerTests](../../tests/UnitTests/AuthTokenIssuerTests.cs)、[AuthCookieTests](../../tests/UnitTests/AuthCookieTests.cs)、[AspNetPasswordHashingTests](../../tests/UnitTests/AspNetPasswordHashingTests.cs)、[EfUserStoreTests](../../tests/DatabaseIntegration/EfUserStoreTests.cs)。

## INF-T03 — 認證 challenge、CSRF 與 returnUrl

- 責任／風險／狀態：middleware／filters，L3，已有測試本次未執行；規格 Identity §5–6、api-spec 錯誤格式。
- Given：匿名或過期 bf_auth；另備只有 Authorization header、合法 auth cookie 但無 antiforgery token、外站 returnUrl。
- When：對受保護 API 與 GET／POST 頁面送 request；以 `SafeReturnUrl.Resolve` 判定 URL。
- Then：header-only 不認證；API 401 problem+json；GET/HEAD login redirect 帶 returnUrl，其他 page method 無 returnUrl；已登入狀態變更 API 缺 CSRF 回 400；推薦 parser／embedding／ranker Calls 為零與 Library Entry 的特定資料不變另由 production endpoint 案例斷言，不能泛稱所有 service 均已 spy 驗證；外站／空 returnUrl 回 `/`，合法本地路徑保留。
- 入口：[AuthPipelineTests](../../tests/WebIntegration/AuthPipelineTests.cs)、[SafeReturnUrlTests](../../tests/UnitTests/SafeReturnUrlTests.cs)、[ApiExceptionProblemDetailsFilterTests](../../tests/UnitTests/ApiExceptionProblemDetailsFilterTests.cs)、[RecommendationApiTests](../../tests/WebIntegration/RecommendationApiTests.cs) 的 `Signed_in_request_without_antiforgery_header_returns_400_and_calls_no_external_service`、[LibraryApiTests](../../tests/WebIntegration/LibraryApiTests.cs) 的 `Signed_in_add_without_antiforgery_header_returns_400_and_saves_nothing` 與 `Patch_and_delete_without_antiforgery_header_return_400_and_change_nothing`。前者查 AI Calls；後兩者分別查 Entry count／既有 rating，不涵蓋任意副作用。

## INF-T04 — Catalog／Bestseller cache 隔離與空值

- 責任／風險／狀態：read/cache，L2，已有測試本次未執行；規格 Catalog §3–5、Bestseller §6。
- Given：Book A 存在、B 不存在；inner spy；獨立 cache；榜單分空／非空；兩使用者 Library 狀態不同。
- When：同 bookId 連讀兩次、讀不同 id；不存在後新增再讀；讀榜單並檢查 entry TTL；一般搜尋讀空結果。
- Then：存在 detail 十分鐘快取、同 key inner 一次、不同 key 隔離；null 不 cache；榜單非空一小時、空五分鐘、原 rank 缺號保留；Library state 不在 detail；一般搜尋無 cache／外部服務呼叫，公開結果無 description／table_of_contents。
- 入口：[CachedBookDetailReaderTests](../../tests/UnitTests/CachedBookDetailReaderTests.cs)、[CachedBestsellerReaderTests](../../tests/UnitTests/CachedBestsellerReaderTests.cs)、[SearchPageTests](../../tests/WebIntegration/SearchPageTests.cs)、[BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs)。

## INF-T05 — Library 冪等與本人隔離

- 責任／風險／狀態：EF Library，L2（隔離 regression L3），已有測試本次未執行；規格 Library §2–3、data-model §6.12。
- Given：A/B、同 Book、A 已有 Entry；另備不存在 Book 與不存在 user。
- When：同 composite key 併發 AddIfMissingAsync；依序 UpdateAsync 的 rating keep/clear/set 與 status；用 B 查／改 A Entry；重複 RemoveAsync。
- Then：只一 row、已存在資料不被新增覆寫；AddedAt 保留、UpdatedAt 更新；B 無法讀改 A；刪除可重複；Book FK 回 null、user FK 仍拋 DB exception，不能誤報 BookNotFound；List 不含私有來源內容。
- 入口：[EfLibraryStoreTests](../../tests/DatabaseIntegration/EfLibraryStoreTests.cs)。

## INF-T06 — Candidate Set 門檻與硬條件

- 責任／風險／狀態：pgvector，L3，已有測試本次未執行；規格 Recommendation §4–5。
- Given：有／無 embedding Books、threshold 正好命中及略低者；語言 zh／zh-TW／zh-CN、NULL 年與頁、含 `%`／`_` 名稱；Bestseller rank 和 profile 與 similarity 刻意相反。
- When：`FindAsync(filters, vector, threshold, topK, ct)`，先空 filters 再逐一設定邊界／文字 literal；掛 interceptor。
- Then：只有硬條件 AND similarity >= threshold 入選；NULL 不符合已指定範圍；含端點；zh 可含地區、指定地區只匹配自身；wildcard 當 literal；依 distance、BookId 排序並 Take；無候選一個 SQL，非空四個；不讀 Bestseller/profile、不外呼。
- 入口：[EfCandidateSearchTests](../../tests/DatabaseIntegration/EfCandidateSearchTests.cs)。

## INF-T07 — Embedding hash、batch、upsert 與 worker

- 責任／風險／狀態：backfill，L3，已有測試本次未執行；規格 Recommendation §10。
- Given：缺 embedding、hash 相同、hash stale 三組 Books；固定時間；fake generator 可成功／失敗／錯維度；includeProfileFields=false。
- When：FindPendingAsync(limit)、RunOnceAsync、SaveAsync；worker 啟動後推進 fake time，最後取消。
- Then：缺向量優先、各組新到舊與穩定 tie-break，hash 相同不呼叫 generator；SQL 不選 publisher／table_of_contents、不讀 vector 本體；upsert 同 Book 一 row；錯維度由 DB 拒絕且可後續繼續使用 context；startup 即一輪、interval 循序無重疊、停用零 rounds、取消正常停止。單書 failure 計數由 Application service tests 判定，不把 worker catch 當全部規則。
- 入口：[EfEmbeddingStoreTests](../../tests/DatabaseIntegration/EfEmbeddingStoreTests.cs)、[EmbeddingBackfillWorkerTests](../../tests/UnitTests/EmbeddingBackfillWorkerTests.cs)、[EmbeddingBackfillServiceTests](../../tests/UnitTests/EmbeddingBackfillServiceTests.cs)。

## INF-T08 — Profile queue、生成與失敗恢復

- 責任／風險／狀態：profile，L3，已有測試本次未執行；規格 Recommendation §9。
- Given：QueueCapacity=1；Book A 在 pending／processing，B 嘗試入列；store 有 unchanged／stale／不存在資料，fake generator 可失敗。
- When：TryEnqueue(A) 兩次、ReadAllAsync 取 A 後尚未 Complete 再排 A；填滿後排 B；Complete 後重試；worker 執行並取消。
- Then：處理中仍去重；滿 queue 不留 pending B；空位釋出 B 可重入；finally 在成功／失敗／停機都 Complete；每書 scope；失敗不立即 retry、後續書仍可處理；unchanged／不存在不外呼；upsert 只改 profile、不改 books 簡介目錄；Enabled=false 不生成。此測例不證明跨 process 去重。
- 入口：[BookProfileQueueTests](../../tests/UnitTests/BookProfileQueueTests.cs)、[BookProfileWorkerTests](../../tests/UnitTests/BookProfileWorkerTests.cs)、[EfBookProfileStoreTests](../../tests/DatabaseIntegration/EfBookProfileStoreTests.cs)。

## INF-T09 — OpenAI 輸出、錯誤與取消

- 責任／風險／狀態：SDK adapters，L3，已有測試本次未執行；規格 Recommendation §4、7、9–10、13。
- Given：fake SDK transport 回合法 strict JSON、null google_queries、缺欄位／malformed JSON／refusal／length、HTTP 500；另備已取消 token。
- When：分別呼叫 requirement parser、embedding generator、ranker、profile generator。
- Then：合法欄位映射正確、未明示 filter 保持 null、null queries 空集合；invalid output／SDK failure 包 AiUnavailableException 且不在 message 回顯 key／需求；caller cancellation 保留 OperationCanceledException；model 取設定；不設定不支持的 sampling parameters。Application 再驗候選，不單靠 schema 信任 LLM。
- 入口：[OpenAiRequirementParserTests](../../tests/UnitTests/OpenAiRequirementParserTests.cs)、[OpenAiRecommendationRankerTests](../../tests/UnitTests/OpenAiRecommendationRankerTests.cs)、[OpenAiEmbeddingGeneratorTests](../../tests/UnitTests/OpenAiEmbeddingGeneratorTests.cs)、[OpenAiBookProfileGeneratorTests](../../tests/UnitTests/OpenAiBookProfileGeneratorTests.cs)。

## INF-T10 — Trusted proxy、keys 與設定負面案例

- 責任／風險／狀態：hosting，L3 模擬已有測試本次未執行；實際部署 L4 待驗證；規格 Deployment §3、5。
- Given：無 networks、有效／無效 CIDR、trusted／untrusted remote IP、KeysPath 空白或 temporary directory；有效／缺失 key 與無效 interval/batch/threshold。
- When：CreateForwardedHeadersOptions；建測試 pipeline 送 forwarded headers；同 key directory 重建 Data Protection provider，unprotect 舊 payload；觸發 Options validation。
- Then：loopback 持續可信，未設定的 container gateway 不可信；untrusted headers 忽略；無效 CIDR 拋例外；空 KeysPath 不額外註冊；非空持久化且同 application name 能讀舊 payload；缺 key／非法設定啟動失敗且不外呼。實際 mount／nginx IP／公開 TLS 另依 INF-B04 授權驗證。
- 入口：[HostingSetupTests](../../tests/UnitTests/HostingSetupTests.cs)、[ForwardedHeadersTests](../../tests/WebIntegration/ForwardedHeadersTests.cs)、[OpenAiServiceCollectionExtensionsTests](../../tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs)、[JwtOptionsTests](../../tests/UnitTests/JwtOptionsTests.cs)。

## INF-T11 — Google Books fallback（未實作）

- 責任／風險／狀態：external／EF adapter mechanics（依 Catalog-owned normalization／identity／persistence 規則），L3，未實作；對應 INF-B01；規格 Recommendation §6、Catalog §6。
- Given：本地候選恰 5 或 4；fake volumes 含重複 ISBN、無 ISBN、不相關書、外部失敗。
- When：未來 RecommendationService 透過 Catalog capability port 編排 fallback，Catalog 呼叫 Infrastructure external／EF adapters。
- Then：5 不外呼；4 才外呼，normalize／持久化／embedding 後重跑同門檻；ISBN 命中不重複 Book；外部失敗保留本地候選，已寫 Book 不因未推薦而 rollback；FallbackUsed 反映流程。
- 入口：Google Books adapter tests 待建；擴充 EfCandidateSearchTests、EfRecommendationStoreTests；不可現在宣稱已通過。

## INF-T12 — 增量掃描（明確暫緩）

- 責任／風險／狀態：embedding，L3，明確暫緩；INF-B02；來源 TODO、Recommendation §10。
- Given：相同基準資料量、未變更／任一 metadata writer 改動、contributors／subjects 改動。
- When：恢復後比較全量版與增量版 pending 集合及掃描成本。
- Then：pending 完全一致、不漏子表變動、未變更不送 OpenAI、輸出優先序不變；以 rows/bytes/time/memory 比較改善。
- 入口：EfEmbeddingStoreTests 擴充待建；現有 hash 測試不是增量化已實作證據。

## INF-T13 — IP 限流（明確暫緩）

- 責任／風險／狀態：Identity，L3，明確暫緩；INF-B03；來源 Identity §7／TODO。
- Given：未來 fake clock、同 IP 多次 login／register、不同 IP、可信與偽造 forwarded headers。
- When：依 authority 設定視窗內送至上限後再一次，推進視窗後重送。
- Then：依規格 429、視窗恢復、不同 IP 不互相限流、spoofed header 不繞過限制。
- 入口：AuthPipelineTests 待補 limiter cases；現況不可期望限流測試通過。

## INF-T14 — 多 instance queue（改善提案）

- 責任／風險／狀態：profile/cache，L3，待補強且需 ADR；INF-B05；來源 system architecture §7、ADR-005。
- Given：未來兩 worker、同一 Book、processing 中 restart；共享 adapter 依核准設計。
- When：同 Book 併發 claim／upsert，終止一 worker 再恢復。
- Then：不出未處理 PK race、可恢復、重送冪等，無使用者 Library state 汙染共用 cache。
- 入口：分散式測試待建；現有 process-local tests 不能證明此案。

## INF-T15 — 成功保存、用量與本人歷史

- 責任／風險／狀態：Recommendation persistence，L3，已有測試本次未執行；規格 Recommendation §8、11–13。
- Given：A/B、固定 Taipei 日界的 UTC 時間、前日與今日 searches；ranked results 含合法 Book 或不存在 FK；另備零結果與巨大頁碼。
- When：CountSinceAsync、SaveAsync、ListAsync、GetAsync；成功保存後讓 profile enrichment 失敗；保存前讓 OpenAI 或 timeout 失敗。
- Then：只計 A 日界以後已保存 search；成功含零結果保存；relevance 五位小數；Result FK 失敗 Search/Results 一起 rollback；B 讀 A search 回 null；巨大 offset 不溢位且空頁；保存後 enrichment 一般失敗降級，caller 取消仍傳播取消但已保存 search 不回滾；保存前 AI failure／timeout 不保存。每日已達上限不呼叫任何外部 adapter（Application gate regression）。
- 入口：[EfRecommendationStoreTests](../../tests/DatabaseIntegration/EfRecommendationStoreTests.cs)、[EfRecommendationUsageTests](../../tests/DatabaseIntegration/EfRecommendationUsageTests.cs)、[EfRecommendationHistoryTests](../../tests/DatabaseIntegration/EfRecommendationHistoryTests.cs)、[RecommendationServiceTests](../../tests/UnitTests/RecommendationServiceTests.cs)。

## INF-T16 — 書庫列表、隨機樣本與組裝守衛

- 責任／風險／狀態：Catalog browse 與 DI，L3，**測試實作：Implemented**；執行結果見 #109 實作報告；規格 Catalog §3.6 書庫瀏覽。
- Given：固定 Id 的三本同出版日書、無日期與新舊日期混合書、25 本書、空庫、15 本與 3 本書；作者含 AUTHOR 與 TRANSLATOR 且 contributor_order 打亂。
- When：從 DI scope 解析 BookBrowseService，呼叫 ListAsync 與 SampleHomeAsync；頁碼為 int.MaxValue。
- Then：同日依 Id 升冪；有日期者新到舊且在無日期者前；25 本分 20 與 5 且無重複、TotalPages 2；超出頁數回空 items 且 TotalCount 保留（不溢位）；空庫 TotalPages 0；樣本 15 本回 10 個不重複既有書、3 本回 3 本；作者只含 AUTHOR 並依 contributor_order。
- 入口：[BookBrowseIntegrationTests](../../tests/WebIntegration/BookBrowseIntegrationTests.cs)；seed 的 `BookSeed.Id` 見 [CatalogSeed](../../tests/WebIntegration/CatalogSeed.cs)。

## INF-T17 — Migration 010 的實體 schema、trigger 與回填

- Given：已 migrate 到 head 的 pgvector container；另一個 container 先停在 `20261010204858_Embedding` 並寫入 v0.0.4 形式的 rows。
- When：查 `information_schema`、`pg_constraint`、`pg_indexes`、`pg_trigger`，並以 `source_type`-only、`source_code`-only、不一致值、KINGSTONE 寫入；再 migrate 到 010。
- Then：兩欄都存在；`source_type` 與 `source_code` 皆 NOT NULL，舊 check 仍在；兩個 `source_code` FK 指向 source_providers 且 RESTRICT；`book_subjects` 實體 PK 仍為 `(book_id, subject, source_type)` 且 UNIQUE `(book_id, subject, source_code)` 存在；`book_identifiers` check 接受 `ISBN`；`book_offers` FK 指向 book_sources 且 CASCADE，price、list_price、availability check 存在；雙向 trigger 生效，不一致回 23514，KINGSTONE 未到 011 前回 23502；回填後 `source_code = source_type`。
- 來源與執行狀態：[MultiSourceCatalog010SchemaTests](../../tests/DatabaseIntegration/MultiSourceCatalog010SchemaTests.cs)（每個 test 自己的 database，migrate 到 010）、[MultiSourceBackfillTests](../../tests/DatabaseIntegration/MultiSourceBackfillTests.cs)（停在 010）；`d864acc` 之後以 DatabaseIntegration 通過（見 update-history）。


## INF-T20 — Migration 011 的轉換、自我守衛與 Down

- Given：每個 test 有自己的空 database，先 migrate 到 `20261024160045_MultiSourceCatalog`（010）並寫入 ISBN_13／ISBN_10／ISBN 列；守衛案例以 `DISABLE TRIGGER` 與 `DROP NOT NULL` 製造 010 無法產生的不一致。
- When：migrate 到 `20261025120000_ContractMultiSourceCatalog`；守衛案例 migrate 到 011；Down 案例先到 011 再回 010，並另測含 KINGSTONE 來源的 Down。
- Then：row 8 的案例只剩一筆 `ISBN X`、ISBN_10 Y 變 `ISBN Y`、共用值 Z 兩本都保留；無 ISBN_10／ISBN_13 列。gate 5 與 gate 4 拋錯，資料庫仍在 010（`source_type` 存在、history 最後一筆是 010）。Down 還原 010 的 PK、check、legacy partial unique、trigger 與 function；含 KINGSTONE 時拒絕 Down。
- 來源：[ContractMigration011Tests](../../tests/DatabaseIntegration/ContractMigration011Tests.cs)、[MultiSourceCatalogSchemaTests](../../tests/DatabaseIntegration/MultiSourceCatalogSchemaTests.cs)、[MigrationServer](../../tests/DatabaseIntegration/MigrationServer.cs)。`d864acc` 與 `5052361` 之後通過。

## 可執行入口（僅記錄，本次未執行）

在 repository root，具對應 .NET SDK；DB/Web projects 另需 Docker、可取得測試 image。所有資料庫只能用 fixture disposable container，AI transport／ports 必須 fake。

```bash
dotnet test tests/UnitTests/UnitTests.csproj
dotnet test tests/DatabaseIntegration/DatabaseIntegration.csproj
dotnet test tests/WebIntegration/WebIntegration.csproj
```

以上命令可能產生 build artifacts，本文件任務沒有執行。靜態檢查只核對來源／連結／fences／history；Mermaid 僅結構檢查，沒有 renderer 執行證據。

## 文件導航

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [案例](test-suite.md)

## INF-T18 — Detail reader 的 ISBN 順序

- Given：同一本書含兩個 ISBN（值亂序）與 OTHER。
- When：`EfBookDetailReader.ReadAsync`。
- Then：只有 ISBN，依值排序；OTHER 不出現。這是 Application `BookDetail` contract 的順序，由 reader 負責。
- 來源：[EfBookDetailReaderTests](../../tests/DatabaseIntegration/EfBookDetailReaderTests.cs)（DatabaseIntegration）。`d864acc`／`5052361` 後通過。
