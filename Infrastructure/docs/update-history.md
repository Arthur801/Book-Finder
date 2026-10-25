# Infrastructure 修改歷史

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

查核基準 `91333c3` 的 source history 如下；`Infrastructure/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

> 查核日期：2026-10-24；基準 `91333c3`。本次只做文件靜態檢查，未執行 build、測試、migration、部署或外部服務。

## 查核範圍與方法

來源 `Infrastructure/`，排除 `Infrastructure/docs/`；完整可見 Git 路徑歷史，不做時間截斷。下表按 `--reverse --topo-order`（拓樸由舊至新），日期為 **author date**，不代表部署日期或測試通過日期。merge 可能與分支事件重疊，不據此計算實作工作次數。subject 保留原文，右欄是實際目標路徑 diff 的檔案範圍，不能將整個 commit 的 subject 當成每個檔案的行為。

```bash
git log --reverse --topo-order --date=short --format='%H|%ad|%s' 91333c3 -- Infrastructure ':!Infrastructure/docs'
git show --format=fuller --stat <SHA> -- Infrastructure ':!Infrastructure/docs'
git show <SHA> -- Infrastructure
```

`git rev-parse --is-shallow-repository` 回 `false`，本地 repository 非 shallow；遠端未取得的歷史仍不在本次範圍。

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-10-11 | `6b19340b56c8` | Complete PostgreSQL db creation | `Persistence/AppDbContext.cs`、`Persistence/Configurations/BestsellerConfiguration.cs`、`Persistence/Configurations/BookAiProfileConfiguration.cs`、`Persistence/Configurations/BookConfiguration.cs`、`Persistence/Configurations/BookContributorConfiguration.cs`、`Persistence/Configurations/BookIdentifierConfiguration.cs`、`Persistence/Configurations/BookSourceConfiguration.cs`、`Persistence/Configurations/BookSubjectConfiguration.cs`、`Persistence/Configurations/RecommendationResultConfiguration.cs`、`Persistence/Configurations/RecommendationSearchConfiguration.cs`、`Persistence/Configurations/UserBookConfiguration.cs`、`Persistence/Configurations/UserConfiguration.cs`、`Persistence/Migrations/20261010174616_EnablePgvector.Designer.cs`、`Persistence/Migrations/20261010174616_EnablePgvector.cs`、`Persistence/Migrations/20261010174654_Catalog.Designer.cs`、`Persistence/Migrations/20261010174654_Catalog.cs`、`Persistence/Migrations/20261010174708_IdentityUserLibrary.Designer.cs`、`Persistence/Migrations/20261010174708_IdentityUserLibrary.cs`、`Persistence/Migrations/20261010174714_Bestseller.Designer.cs`、`Persistence/Migrations/20261010174714_Bestseller.cs`、`Persistence/Migrations/20261010174725_RecommendationHistory.Designer.cs`、`Persistence/Migrations/20261010174725_RecommendationHistory.cs`、`Persistence/Migrations/20261010174732_AiProfile.Designer.cs`、`Persistence/Migrations/20261010174732_AiProfile.cs`、`Persistence/Migrations/20261010174745_Indexes.Designer.cs`、`Persistence/Migrations/20261010174745_Indexes.cs`、`Persistence/Migrations/AppDbContextModelSnapshot.cs`、`Persistence/README.md`、`Persistence/SnakeCase.cs`、`Persistence/StoredEnum.cs` |
| 2026-10-11 | `be3cce92a3a6` | Require user on recommendation searches (#1) | `Persistence/Configurations/RecommendationSearchConfiguration.cs`、`Persistence/Migrations/20261010204611_RequireRecommendationUser.Designer.cs`、`Persistence/Migrations/20261010204611_RequireRecommendationUser.cs`、`Persistence/Migrations/AppDbContextModelSnapshot.cs`、`Persistence/README.md` |
| 2026-10-11 | `0c064f12b379` | Add book_embeddings table with vector(1536) (#2) | `Persistence/AppDbContext.cs`、`Persistence/Configurations/BookEmbeddingConfiguration.cs`、`Persistence/Migrations/20261010204858_Embedding.Designer.cs`、`Persistence/Migrations/20261010204858_Embedding.cs`、`Persistence/Migrations/AppDbContextModelSnapshot.cs`、`Persistence/README.md` |
| 2026-10-11 | `a19a7e297240` | Rename UserBook entity to LibraryEntry (#3) | `Persistence/AppDbContext.cs`、`Persistence/Configurations/LibraryEntryConfiguration.cs`、`Persistence/Configurations/UserBookConfiguration.cs`、`Persistence/Migrations/AppDbContextModelSnapshot.cs` |
| 2026-10-11 | `976d9fe01d83` | Add bestseller pages and web integration test harness (#5) | `Persistence/EfBestsellerReader.cs` |
| 2026-10-11 | `dc4a5703f0dd` | Address code review findings (#5) | `Caching/CachedBestsellerReader.cs` |
| 2026-10-11 | `83d36eb5fd9c` | Add Book detail query with per-Book cache | `Caching/CachedBookDetailReader.cs`、`Persistence/EfBookDetailReader.cs` |
| 2026-10-11 | `4855357afba0` | Address M4 code review: comments, cache key const, shared test cache | `Caching/CachedBookDetailReader.cs`、`Persistence/EfBookDetailReader.cs` |
| 2026-10-11 | `5310920b556f` | Add local-only catalog search query for issue #8 | `Persistence/EfBookSearch.cs`、`Persistence/LikePattern.cs` |
| 2026-10-11 | `7533f63dcb9f` | Apply code review fixes to the catalog search query | `Persistence/BookAuthors.cs`、`Persistence/EfBestsellerReader.cs`、`Persistence/EfBookSearch.cs`、`Persistence/LikePattern.cs` |
| 2026-10-20 | `c8ce8ba96faa` | Wrap PasswordHasher behind a password hashing port | `Identity/AspNetPasswordHashing.cs` |
| 2026-10-20 | `c1af3d645bce` | Add an EF user store with case-insensitive email lookup | `Persistence/EfUserStore.cs` |
| 2026-10-20 | `020ff1330caf` | Lowercase email lookups in PostgreSQL to match the unique index | `Persistence/EfUserStore.cs` |
| 2026-10-20 | `c13d8625ae43` | Issue HS256 auth tokens from the configured signing key | `Identity/AuthTokenIssuer.cs`、`Identity/JwtOptions.cs` |
| 2026-10-20 | `6a2dbc7147e6` | Add the auth cookie helper with its fixed attributes | `Identity/AuthCookie.cs` |
| 2026-10-20 | `40ec61a05862` | Authenticate requests from the auth cookie with cookie-aware challenges | `Identity/AuthServiceCollectionExtensions.cs` |
| 2026-10-20 | `2437ca77b80e` | Return a ProblemDetails 400 for API antiforgery failures | `Identity/AntiforgeryProblemDetailsFilter.cs`、`Identity/AuthServiceCollectionExtensions.cs` |
| 2026-10-20 | `88d06c5df002` | Detect antiforgery failures by their public result interface | `Identity/AntiforgeryProblemDetailsFilter.cs` |
| 2026-10-20 | `5d2113a15b57` | Resolve return URLs to local paths only | `Identity/SafeReturnUrl.cs` |
| 2026-10-20 | `e5307873094a` | Leave returnUrl out of challenges for non-GET page requests | `Identity/AuthServiceCollectionExtensions.cs` |
| 2026-10-20 | `3134b7acd927` | Share the API path check and name claim constant across auth code | `Identity/AntiforgeryProblemDetailsFilter.cs`、`Identity/ApiRequest.cs`、`Identity/AuthServiceCollectionExtensions.cs`、`Identity/AuthTokenIssuer.cs`、`Identity/JwtOptions.cs` |
| 2026-10-20 | `2981b0fba63e` | Add the embedding store that finds pending Books and saves vectors | `Persistence/EfEmbeddingStore.cs` |
| 2026-10-20 | `137e5fed12c6` | Add the OpenAI embedding generator and its service registration | `OpenAi/OpenAiEmbeddingGenerator.cs`、`OpenAi/OpenAiOptions.cs`、`OpenAi/OpenAiServiceCollectionExtensions.cs` |
| 2026-10-21 | `2db12b90009f` | Start the embedding backfill on a timer and wire it into the web app | `BackgroundJobs/EmbeddingBackfillWorker.cs` |
| 2026-10-21 | `a6f4a071118f` | Fail startup when an embedding setting is out of range | `OpenAi/OpenAiServiceCollectionExtensions.cs` |
| 2026-10-21 | `2b7a13e02436` | Tidy the embedding code: stale comments, shared constants, one pending item | `OpenAi/OpenAiServiceCollectionExtensions.cs`、`Persistence/EfEmbeddingStore.cs` |
| 2026-10-21 | `2ada37f060c4` | Implement the Candidate Set search over pgvector and the hard filters | `Persistence/EfCandidateSearch.cs` |
| 2026-10-21 | `682c156a7258` | Add the recommendation store port, its skeleton and failing database tests | `Persistence/EfRecommendationStore.cs` |
| 2026-10-21 | `12296ef84bbc` | Implement the recommendation store in one SaveChanges | `Persistence/EfRecommendationStore.cs` |
| 2026-10-21 | `6900a2bd339b` | Add the OpenAI requirement parser with a shared fake transport | `OpenAi/OpenAiChat.cs`、`OpenAi/OpenAiRequirementParser.cs` |
| 2026-10-21 | `df7084f940ca` | Add the OpenAI recommendation ranker | `OpenAi/OpenAiRecommendationRanker.cs` |
| 2026-10-21 | `7c331ad4b310` | Register the chat adapters and validate the recommendation settings | `OpenAi/OpenAiServiceCollectionExtensions.cs` |
| 2026-10-21 | `337fb21f2c8e` | Move PublishedDateText into the catalog application layer | `OpenAi/OpenAiRecommendationRanker.cs` |
| 2026-10-21 | `22542ca92be1` | Add the POST /api/recommendations endpoint | `Identity/ApiExceptionProblemDetailsFilter.cs`、`Identity/AuthServiceCollectionExtensions.cs` |
| 2026-10-21 | `8753589d25a4` | Reuse the exact language pattern for the regional match | `Persistence/EfCandidateSearch.cs` |
| 2026-10-21 | `9d5cb2ee3a86` | Make year boundaries in the parser prompt include the named year | `OpenAi/OpenAiRequirementParser.cs` |
| 2026-10-22 | `d0e1c85f084d` | Add EF Library store and DI registration (#11 M2) | `Persistence/EfLibraryStore.cs` |
| 2026-10-22 | `f2588808056b` | Add PUT /api/library/{bookId} add-to-library endpoint (#11 M3) | `Identity/CurrentUser.cs` |
| 2026-10-22 | `27ecea3c8c04` | Add library update and remove to the store and service (#12 M2) | `Persistence/EfLibraryStore.cs` |
| 2026-10-22 | `c12f2baaa54d` | Share the problem+json result helper across API controllers and filters (#12 M3) | `Identity/AntiforgeryProblemDetailsFilter.cs`、`Identity/ApiExceptionProblemDetailsFilter.cs`、`Identity/ApiProblemResults.cs` |
| 2026-10-22 | `249c3784f042` | Translate only the Book FK violation to not found in library add (#11 M2) | `Persistence/EfLibraryStore.cs` |
| 2026-10-22 | `532f2915478f` | Merge issue-11-m2-ef-library-store into issue-11-m3-put-endpoint (#48 FK fix) | `Persistence/EfLibraryStore.cs`、`Identity/CurrentUser.cs` |
| 2026-10-22 | `f5801fc4e1ab` | Merge issue-12-m1-patch-parsing into issue-12-m2-update-remove (#48 FK fix) | `Persistence/EfLibraryStore.cs` |
| 2026-10-22 | `e205264e6f71` | Merge issue-12-m2-update-remove into issue-12-m3-patch-delete-endpoints (#48 FK fix) | `Persistence/EfLibraryStore.cs`、`Identity/AntiforgeryProblemDetailsFilter.cs`、`Identity/ApiExceptionProblemDetailsFilter.cs`、`Identity/ApiProblemResults.cs` |
| 2026-10-22 | `5ee765fb2312` | Add Taipei day start and Recommendation DailyLimit setting | `OpenAi/OpenAiServiceCollectionExtensions.cs` |
| 2026-10-22 | `aeb12e2e9fc1` | Add the daily-limit usage count port (#15 M2) | `Persistence/EfRecommendationUsage.cs` |
| 2026-10-22 | `d32d41cbbba2` | Add the daily Recommendation limit gate (#15 M3) | `Identity/ApiProblemResults.cs` |
| 2026-10-22 | `75d710a2904c` | Map OpenAI failures to AI unavailable, 502 (#15 M4) | `Identity/ApiExceptionProblemDetailsFilter.cs`、`Identity/ApiProblemResults.cs`、`OpenAi/OpenAiCall.cs`、`OpenAi/OpenAiEmbeddingGenerator.cs`、`OpenAi/OpenAiRecommendationRanker.cs`、`OpenAi/OpenAiRequirementParser.cs` |
| 2026-10-22 | `ffbc063ac933` | Add the 60 s recommendation timeout to 504 (#15 M5) | `Identity/ApiExceptionProblemDetailsFilter.cs`、`Identity/ApiProblemResults.cs` |
| 2026-10-22 | `8268ccb52b2e` | Log each failed AI recommendation once in the service (#15 review) | `Identity/ApiExceptionProblemDetailsFilter.cs` |
| 2026-10-22 | `4ff2b169a2f2` | Correct the TaipeiTimeZone and OpenAiCall comments (#15 review) | `OpenAi/OpenAiCall.cs` |
| 2026-10-22 | `65fcac1157bc` | Add AI search history reader (#16 M1) | `Persistence/EfRecommendationHistory.cs` |
| 2026-10-22 | `fc9bcc3f7836` | Guard the history page offset against int overflow (#16) | `Persistence/EfRecommendationHistory.cs` |
| 2026-10-22 | `a0cd6ae0a124` | Name the history read models after the glossary (#16 review) | `Persistence/EfRecommendationHistory.cs` |
| 2026-10-22 | `f7ed7581094f` | Cite the right specs in the history reader and the page number (#16 review) | `Persistence/EfRecommendationHistory.cs` |
| 2026-10-22 | `9e26c4f13671` | Add OpenAI book profile generator (issue #18 M3) | `OpenAi/OpenAiBookProfileGenerator.cs`、`OpenAi/OpenAiServiceCollectionExtensions.cs` |
| 2026-10-22 | `d5e1589aa4e3` | Add book profile store (issue #18 M4) | `Persistence/EfBookProfileStore.cs` |
| 2026-10-22 | `d293dfa91cfb` | Add book profile queue and worker (issue #18 M5) | `BackgroundJobs/BookProfileQueue.cs`、`BackgroundJobs/BookProfileServiceCollectionExtensions.cs`、`BackgroundJobs/BookProfileWorker.cs` |
| 2026-10-22 | `8fc6c83c064b` | Share one loader for the Book metadata of the embedding and profile stores (issue #18) | `Persistence/BookMetadata.cs`、`Persistence/EfBookProfileStore.cs`、`Persistence/EfEmbeddingStore.cs` |
| 2026-10-22 | `09d4924b415a` | Register the Book AI profile services in one extension (issue #18) | `BackgroundJobs/BookProfileServiceCollectionExtensions.cs` |
| 2026-10-22 | `9ef23cc35b37` | Cite the recommendation spec instead of the plan in the AI profile code (issue #18) | `OpenAi/OpenAiServiceCollectionExtensions.cs`、`Persistence/EfBookProfileStore.cs` |
| 2026-10-22 | `a4c1fdc17d1b` | Keep the profile-only columns out of the embedding scan (issue #18) | `Persistence/BookMetadata.cs`、`Persistence/EfBookProfileStore.cs`、`Persistence/EfEmbeddingStore.cs` |
| 2026-10-23 | `dccad53544ce` | chore(deps): pgvector image 固定為 0.8.7-pg17 | `Persistence/README.md` |
| 2026-10-23 | `2a74705eec14` | feat(hosting): configurable forwarded-header networks and data protection key path (#92) | `Hosting/HostingSetup.cs` |

## 重要 diff 的語意查核

- `2ada37f`：EfCandidateSearch 以 cosine distance 排序、硬條件與門檻先篩，再三個批次補資料；不是套用 Bestseller rank。
- `12296ef`：原 skeleton 改為 Search 與 Results 一次 SaveChanges，relevance 先四捨五入五位小數；DB 失敗不留下半份 search。
- `249c378`：Library 新增只攔 Book FK 名稱，user FK 繼續傳播，不再所有 FK 都報 BookNotFound。
- `d293dfa`：bounded Channel／pending 去重持續到 Complete，worker 每書 scope、finally Complete，失敗不立即重試。
- `a4c1fdc`：BookMetadata loader 增 includeProfileFields，embedding scan 排除 publisher／table_of_contents，profile store 才讀取。
- `2a74705`：新增 HostingSetup，設定 CIDR 加到預設信任網路；KeysPath 空白維持 default，非空持久化且固定 application name。此 diff 不代表正式 nginx／volume 已驗證。

重要 commit 已查 `git show --format=fuller --stat` 與目前對應實作；12296ef、249c378、d293dfa、a4c1fdc、2a74705 另讀目標責任 diff。其餘表格完整列出路徑歷史與檔案，不冒稱逐行 review 全部過往 patch。

## 目錄外依賴

`Program.cs` 是 adapter 註冊與呼叫端，Application/Recommendation 控制每日 gate、timeout、成功後 enrichment；Domain entities 決定 EF mapping 輸入。這些外部依賴不併入上表的直接修改史。ADR-002 定 EF schema ownership，crawler 不執行 DDL。未根據 commit message 推定雲端部署或執行成功。

## #109 M1 書庫後端（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 提交 | Subject | 影響 |
|---|---|---|
| `7c369fd` | feat(catalog): implement EF book browse list and random sample | 新增 EfBookBrowse（COUNT → 分頁 → BookAuthors；隨機樣本）；Program 註冊 IBookBrowse 與 BookBrowseService（scoped），Bestseller 註冊不變；BookSeed 新增可選 Id（測試支援） |
| `b2c04ce` | test(bestseller): guard retained Bestseller backend through DI | 新增 Bestseller 後端 DI 守衛測試，無產品行為變更 |

## 文件導航

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [案例](test-suite.md)

## #109 M3 書庫查詢計畫基準（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 分支／提交 | Subject | 影響 |
|---|---|---|
| `7c14b09` | docs(browse): sync specs to 書庫 and suspended Bestseller Web | 規格同步；Infrastructure 程式無變更 |
| 本 M3 baseline commit | docs(browse): record 書庫 query plan baseline and implementation report | INF-B06 由「未量測」改為已量測（開發庫 2884 筆，EF 實際 SQL 的 EXPLAIN ANALYZE）；程式與 schema 無變更 |
| 2026-10-25 | `2c662f5` | feat(db): add expand migration 010 for multi-source catalog | `Persistence/Migrations/20261024160045_MultiSourceCatalog.cs`（手寫 operations 與雙向 trigger）、`Persistence/Migrations/20261024160045_MultiSourceCatalog.Designer.cs`、`Persistence/Migrations/AppDbContextModelSnapshot.cs`、`Persistence/Configurations/BookSourceConfiguration.cs`／`BookSubjectConfiguration.cs`（改用 SourceCode）、`Persistence/Configurations/SourceProviderConfiguration.cs`／`BookOfferConfiguration.cs`（新增）、`Persistence/AppDbContext.cs`、`Persistence/EfBookDetailReader.cs` |
| 2026-10-25 | `905c6fc` | test(db): cover migration 010 triggers, physical schema and backfill | `Infrastructure` 無變更（測試位於 `tests/DatabaseIntegration`，見 tests/docs） |
| 2026-10-25 | `d9d8948` | feat(catalog): read ISBN, ISBN-13 and ISBN-10 and provider names on detail | `Persistence/EfBookSearch.cs`（ISBN 模式三種類型）、`Persistence/EfBookDetailReader.cs`（三種 ISBN、來源 JOIN `source_providers`，不過濾 enabled） |
| 2026-10-25 | `df57cbf` | test(db): assert last_seen_at-only UPDATE passes the 010 trigger | `Persistence/Migrations/20261024160045_MultiSourceCatalog.cs`：僅新增註解，operations 未變 |
| 2026-10-25 | `bbe0a0a` | refactor(catalog): share ISBN-family types and display priority | `Persistence/EfBookSearch.cs`、`Persistence/EfBookDetailReader.cs` 改用 IsbnIdentifierTypes；reader 不再依優先序排序（改由 view model 負責）；`Persistence/Migrations/20261024160045_MultiSourceCatalog.cs` 僅註解補充 IX_book_subjects_source_code 為 EF FK 索引 |
| 2026-10-25 | `c3021e3` | fix(catalog): make the detail reader own ISBN identifier order | `Persistence/EfBookDetailReader.cs`：identifiers 依 DisplayPriority 再依值排序 |
| 2026-10-25 | `5052361` | feat(catalog): contract migration 011 and read only the ISBN type | `Persistence/Migrations/20261025120000_ContractMultiSourceCatalog.cs`（新增：自我守衛、ISBN 轉換、DROP source_type／trigger／legacy partial unique、book_subjects PK 換成 source_code；Down 還原 010）、`ContractMultiSourceCatalog.Designer.cs`、`AppDbContextModelSnapshot.cs`（移除 legacy partial unique 與 ISBN_10／13 check）、`Persistence/EfBookSearch.cs`（只查 `ISBN`）、`Persistence/EfBookDetailReader.cs`（只讀 `ISBN`，依值排序）、`Persistence/Configurations/BookIdentifierConfiguration.cs`、`Persistence/SnakeCase.cs`（註解例子） |
| 2026-10-25 | `d864acc` | test(db): cover migration 010 and 011 on their own databases | `Persistence/` 無變更（測試位於 `tests/DatabaseIntegration`，見 tests/docs） |
