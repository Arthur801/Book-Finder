# Infrastructure 架構

> 非同步推薦 Job M6 補記：2026-11-14 更新；程式變更以 `54ad51b`、`0d3b3ac`、`93db136`、`11f86b4`、`c0ac2f6` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M4 補記：2026-11-14 更新；程式變更以 `4b31184`、`5d143b4`、`08d8c9a`、`1f36620`、`ef89755` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M2 補記：2026-11-14 更新；程式變更以 `6717d8f` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M5 補記：2026-11-14 更新；程式變更以 `38543fa`、`149c4e0`、`d181add`、`d82c1cc`、`a648a90`、`48b57e0` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M1 補記：2026-11-14 更新；程式變更以 `ad398b8`、`904baca`、`0a11483` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P5 補記：2026-11-14 更新；程式變更以 `a9b7ad1`、`c2d68a1`、`d43ea57` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P4 補記：2026-11-14 更新；程式變更以 `c2e5324`、`cec6bd7` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P1 補記：2026-11-14 更新；程式變更以 `e7a105b` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 查核日期：2026-10-24；基準 `91333c3`。本次只做文件靜態檢查，未執行 build、測試、migration、部署或外部服務。

## Authority 與邊界

[CONTEXT](../../CONTEXT.md) 定名詞；[system architecture](../../Docs/architecture/system-architecture.md) 定 service boundary；[ADRs](../../Docs/architecture/architecture-decisions.md) 定取捨；[data model](../../Docs/data/data-model.md) 定 schema。[Identity](../../Docs/modules/identity-auth.md)、[Recommendation](../../Docs/modules/recommendation.md)、[Catalog](../../Docs/modules/book-catalog.md)、[Library](../../Docs/modules/user-library.md)、[Bestseller](../../Docs/modules/bestseller.md) 定各業務 invariant。本文件描述程式現況，不另立產品 contract。

## Caller／callee contract

| Caller 與輸入 | Adapter／輸出 | 主要維護點 |
|---|---|---|
| AccountService／email、User | [EfUserStore](../Persistence/EfUserStore.cs)、[AspNetPasswordHashing](../Identity/AspNetPasswordHashing.cs) | lower(email) 比對配合 expression unique index；保留原 email |
| AccountController／User | [AuthTokenIssuer](../Identity/AuthTokenIssuer.cs)、[AuthCookie](../Identity/AuthCookie.cs) → token/cookie | signing key 注入、禁止 secret log |
| Web request pipeline | [auth registration](../Identity/AuthServiceCollectionExtensions.cs)、[API exception filter](../Identity/ApiExceptionProblemDetailsFilter.cs)、[CSRF filter](../Identity/AntiforgeryProblemDetailsFilter.cs) | cookie-only JWT、401/400/500 ProblemDetails；local returnUrl |
| Catalog services／SearchQuery、bookId | [EfBookSearch](../Persistence/EfBookSearch.cs)、[EfBookDetailReader](../Persistence/EfBookDetailReader.cs) → read models | Local DB only，公開內容排除來源簡介目錄 |
| BestsellerService | [EfBestsellerReader](../Persistence/EfBestsellerReader.cs) → 最新 snapshot | 保留 rank 缺號、共用 captured_at；#109 後 Web 無呼叫者，後端保留並由 DI 守衛測試 |
| BookBrowseService／page、pageSize、隨機樣本數 | [EfBookBrowse](../Persistence/EfBookBrowse.cs) → BookBrowsePage／items | 書庫列表依出版日排序後分頁（COUNT → 分頁 → 作者），由共用的 [BookBrowsePaging](../Persistence/BookBrowsePaging.cs) 執行；超出頁數不查列表；隨機樣本整表隨機排序 |
| CategoryBrowseService（經 [CachedCategoryBrowse](../Caching/CachedCategoryBrowse.cs)：側邊欄書數、來源清單、全部書籍數依來源分別快取 10 分鐘；書單不快取；slug／source 的存在判斷也用這份快取，最多延遲 10 分鐘） | [EfCategoryBrowse](../Persistence/EfCategoryBrowse.cs) → 分類與書數、來源、全部書籍數、BookBrowsePage | LINQ 轉成 EXISTS；分類以 `(source_code, subject)` 對應，不同來源的同名 Subject 互不套用；側邊欄書數以 DISTINCT book_id 計算（每個分類一個相關子查詢）；書單分頁沿用 BookBrowsePaging |
| LibraryService／userId、bookId、change | [EfLibraryStore](../Persistence/EfLibraryStore.cs) → Entry／null／List | 本人 filter、composite key、冪等新增、Book FK 特定轉譯 |
| RecommendationService／filters、vector | [EfCandidateSearch](../Persistence/EfCandidateSearch.cs) → CandidateBook | exact cosine、硬條件、description 只供 AI |
| RecommendationService／userId、成功 ranked items | [store](../Persistence/EfRecommendationStore.cs)、[usage](../Persistence/EfRecommendationUsage.cs) | 一次 SaveChanges；用量（M2）= 未由 Job 產生的已保存 Search ＋ 非 `FAILED` 的 Job（依 Job 的 `created_at`），兩個 count 依序執行（共用 DbContext） |
| History caller／userId、page 或 searchId | [EfRecommendationHistory](../Persistence/EfRecommendationHistory.cs) | 本人隔離、long offset、目前書目加保存 rank/reason |
| Application AI interfaces | [OpenAI registration](../OpenAi/OpenAiServiceCollectionExtensions.cs) → filters、vector、ranking、profile | SDK、strict schema、錯誤與 caller cancellation 區分 |
| EmbeddingBackfillService／pending vector | [EfEmbeddingStore](../Persistence/EfEmbeddingStore.cs) | hash、batch selection、單句 upsert |
| Profile scheduler | [queue](../BackgroundJobs/BookProfileQueue.cs)、[worker](../BackgroundJobs/BookProfileWorker.cs)、[store](../Persistence/EfBookProfileStore.cs) | bounded Channel、pending set、每書 scope、獨立 profile 表 |
| Program／configuration | [HostingSetup](../Hosting/HostingSetup.cs) | 額外可信 CIDR、key ring 路徑 |
| Multi-source（010 phase） | [MultiSourceCatalog](../Persistence/Migrations/20261024160045_MultiSourceCatalog.cs)：`source_providers`、`source_code`、雙向 trigger、`book_offers` | 010 的 `source_type` 與 trigger 由 011 移除；EF 不 mapping（data-model §11.4） |
| Multi-source contract（011） | [ContractMultiSourceCatalog](../Persistence/Migrations/20261025120000_ContractMultiSourceCatalog.cs)：`ISBN_10`／`ISBN_13` 轉 `ISBN`，移除 `source_type`、trigger、legacy partial unique；`book_subjects` PK 換成 `source_code`；Up 自我守衛（gate 4、5）；Down 還原 010 實體 schema | KINGSTONE／ESLITE 無 010 對應 source_type，Down 拒絕執行（data-model §11.3、§11.5） |
| 分類 schema（Canonical Category P1） | [AddCanonicalCategories](../Persistence/Migrations/20261114003848_AddCanonicalCategories.cs)：新增 `canonical_categories`、`provider_category_mappings` 與 `IX_book_subjects_source_code_subject`；[CanonicalCategoryConfiguration](../Persistence/Configurations/CanonicalCategoryConfiguration.cs)、[ProviderCategoryMappingConfiguration](../Persistence/Configurations/ProviderCategoryMappingConfiguration.cs) | 只 expand，不改既有欄位；`IX_book_subjects_source_code`（source_code FK 索引）在 [BookSubjectConfiguration](../Persistence/Configurations/BookSubjectConfiguration.cs) 明確宣告，避免 EF 視為重複而刪除；兩個預設名稱超過 PostgreSQL 63 bytes，改用明確名稱。P1 尚無 adapter 讀寫這兩張表（[分類計畫](../../Docs/plans/canonical-category-browse.md) P2 寫入、P4 讀取） |
| Recommendation Job schema（[Job 計畫](../../Docs/plans/async-recommendation-jobs.md) M1） | [AddRecommendationJobs](../Persistence/Migrations/20261114032619_AddRecommendationJobs.cs)：新增 `recommendation_jobs`；[RecommendationJobConfiguration](../Persistence/Configurations/RecommendationJobConfiguration.cs) | 只 expand，不改既有欄位，舊 release 不讀此表。狀態機由 5 個 CHECK 在 DB 端保證（status 詞彙、attempt ≥ 0、request_hash 小寫 hex、idempotency key 字元集、lease 只在 `RUNNING`、終態欄位）；index：`(status, run_after, created_at)` 供領取、`(status, lease_expires_at)` 供逾期恢復、`(user_id, created_at DESC)` 供列表與額度、`search_id` UNIQUE、`(user_id, idempotency_key)` 部分 UNIQUE。`search_id` FK 用 Cascade：刪除使用者同時 cascade 到 Search 與 Job，Restrict 會讓刪除失敗。M1 尚無 adapter 讀寫此表 |
| 推薦工作提交（Job 計畫 M4） | [EfRecommendationJobStore](../Persistence/EfRecommendationJobStore.cs) | 提交在一筆明確交易內：`SELECT id FROM users … FOR UPDATE` → 同使用者同 key 查詢（同 hash commit 回既有 Job；不同 hash rollback）→ `IRecommendationUsage`（同一個 scoped DbContext，所以在同一交易內）→ INSERT `QUEUED`。沒有設定 EF retry strategy，所以可以使用手動交易。列表 `created_at DESC, id DESC`，offset 以 long 計算；Get 以 user 過濾，他人與不存在都回 null |
| Domain entities | [AppDbContext](../Persistence/AppDbContext.cs)、[snapshot](../Persistence/Migrations/AppDbContextModelSnapshot.cs) | 12 application tables、snake_case、vector、constraints |

## 選型比較

「分析」為本次比較，不代表已核准新 ADR。

| 面向 | 現行選擇與依據 | 替代差異 | 代價／維護 |
|---|---|---|---|
| 模組邊界 | port adapters；ADR-001 monolith | 微服務可獨立擴縮，增加網路／交易複雜度 | Program 手動 DI；scoped DbContext 不可注入 singleton worker |
| schema ownership | EF migrations；ADR-002 | crawler 自有 DDL 會分裂 schema | schema 變更同步 crawler；expression index 必須看 SQL，不只 snapshot |
| AI ownership | C# Web；ADR-003 | crawler embedding 需跨語言共享 key/model contract | 新書等待 backfill 才可檢索 |
| 資料庫／vector | PostgreSQL + pgvector exact cosine；data-model §6.9 | ANN 或外部 vector DB 加速但需額外設計（分析） | 全掃成本；1536 維與 model 變更需 migration 及重建 |
| SQL | EF LINQ 與參數化 upsert | 字串拼接 SQL 缺輸入隔離（分析） | wildcard literal escape；保留 FK/unique 防競爭 |
| auth transport | HS256 JWT HttpOnly cookie；ADR-004 | localStorage/header 有不同 client 與 XSS 風險 | 持續 CSRF 防護；一天有效無 refresh |
| cache | process-local IMemoryCache；ADR-005 | Redis 跨 instance、增加服務成本 | detail 十分鐘、榜單一小時／空五分鐘；無 crawler invalidation |
| embedding schedule | PeriodicTimer，每輪 scope | persistent queue 可分散處理（分析） | 不重疊、startup 即執行；全量 hash scan 已暫緩改善 |
| profile queue | bounded Channel + pending dictionary；recommendation §9 | durable queue 可恢復重啟工作（分析） | process-local 單 reader；滿載回 false；失敗等下次結果再排 |
| 交易 | Search 與 Results 一次 SaveChanges；Library 單句 ON CONFLICT | 多次寫入需明確 transaction（分析） | FK 失敗不可留下半份 search；user FK 不誤報 BookNotFound |
| hosting | optional trusted CIDR／key ring path；deployment §3 | 任意信任 proxy 不符合邊界 | 保留 loopback；部署端核對 CIDR、volume、目錄權限 |

## 安全、時間與錯誤

`TimeProvider` 供 UTC 寫入與 JWT expiry 測試；每日 gate 在 Application 將 Taipei 日界轉 UTC，usage 只查 `created_at >= sinceUtc`。Usage count 與保存不是同一個原子預約操作；是否需要更嚴格併發 gate 必須回到產品規格，不能自行更改。

公開 detail／Library／History projections 不含 description／table_of_contents；Candidate、embedding、profile 內部才可讀。Cache 不包含 Library state、不 cache missing detail，也不保證 single-flight。書庫列表與隨機樣本不 cache（書庫頁無 cache，樣本每次重新抽取）。來源網址 UI 防護另由下游負責。

OpenAiCall 保留 caller cancellation，其餘轉 AiUnavailableException；SDK 有內建 retry。固定 60 秒 timeout 由 RecommendationService 控制。Search 已成功保存後，difficulty reader／scheduler 的一般例外會記 Warning 並降級，不回滾 search；兩者均保留已取消 caller token 的 OperationCanceledException，此時請求可取消但已保存資料仍存在。此階段使用 caller token，不使用 60 秒 timeout token。Profile worker 失敗與推薦保存失敗是不同邊界。

## 差距與 runtime 限制

Google Books fallback 尚未接入，store 固定 FallbackUsed=false。Recommendation 擁有 fallback orchestration；Catalog 擁有 normalization、cross-source identity 與 Book persistence 規則；Infrastructure 只實現 external API／EF adapter mechanics，不取得 Catalog 規則 ownership。登入限流、embedding 增量掃描依 [TODO](../../Docs/TODO.md) 明確暫緩。水平擴充前須重新評估 process-local cache／queue，不能直接宣稱多 instance 安全。

HostingSetup 支援設定不等於已驗證容器切換、公開 HTTPS、可信 nginx 位址或實際 key mount。Production secrets、IAM、TLS、migration 執行屬部署範圍；本次無 live 證據。

## 文件導航

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [案例](test-suite.md)

## 推薦工作 lease 與 fencing（Job 計畫 M5）

[EfRecommendationJobLeaseStore](../Persistence/EfRecommendationJobLeaseStore.cs)：

| 操作 | SQL 重點 |
|---|---|
| claim | CTE `SELECT … WHERE status='QUEUED' AND run_after <= now() ORDER BY run_after, created_at, id FOR UPDATE SKIP LOCKED LIMIT 1`，`UPDATE … RETURNING`；`attempt_count+1`、新 token（C# 產生）、`lease_expires_at = now() + make_interval(secs => …)` |
| fence | `id = … AND lease_token = … AND status='RUNNING' AND lease_expires_at > now()`；heartbeat、requeue、fail、release 都以它為 WHERE，回傳是否剛好改到 1 列 |
| commit | 明確交易：先以 fence 條件 `SELECT … FOR UPDATE` 鎖住 Job（沒有就拋 lease lost，什麼都不寫）→ [RecommendationSearchRows](../Persistence/RecommendationSearchRows.cs) 加入 Search 與 Results → SaveChanges → 更新 Job 為 `SUCCEEDED` → commit。任何例外（例如 Book FK）都整筆 rollback，Job 維持 `RUNNING` |
| release | `QUEUED`、`run_after = now()`、`attempt_count - 1`（正常停機不消耗次數），error_code 保留 |
| recover | 一條 `UPDATE … CASE WHEN attempt_count < max …`：逾期的 `RUNNING` 回 `QUEUED` 或 `FAILED`，error_code `WORKER_INTERRUPTED` |

- 狀態值以參數傳入（`StoredEnum.ToStored`），SQL 不另存一份詞彙。
- commit 失敗後，DbContext 的 change tracker 仍留著加入的 Search，所以呼叫端（M6 Worker）必須每個 Job 使用獨立的 scope。
- `RecommendationSearchRows` 由 [EfRecommendationStore](../Persistence/EfRecommendationStore.cs) 與本 store 共用，舊路徑的寫入行為不變。

## 推薦工作背景 Worker（Job 計畫 M6）

[RecommendationJobWorker](../BackgroundJobs/RecommendationJobWorker.cs)（`BackgroundService`，由 [AddRecommendationJobs](../BackgroundJobs/RecommendationJobServiceCollectionExtensions.cs) 註冊，啟動時驗證設定）不含商業規則：

- `RecommendationJobs:Enabled` 為 false（`appsettings.json` 的預設）時只記一行 log 就結束；
- 每輪在新的 scope 中先 `RecoverExpiredAsync`，再 `TryClaimNextAsync`；沒有 Job 就等 PollInterval，有 Job 就立刻接著領下一筆；
- 每筆 Job 在自己的 scope 執行 Runner：commit 失敗會在 DbContext 留下追蹤中的實體，不能帶到下一筆；
- heartbeat 迴圈每次續租都另開 scope（DbContext 不能同時被兩處使用）；被拒就取消 lease-lost token，續租出錯只記 log、下一次再試；
- 除了主機停止造成的取消之外，任何例外都記 log 後等 PollInterval 再繼續：未處理的例外會讓整個 web host 停止。
