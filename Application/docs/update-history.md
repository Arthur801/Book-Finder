# Application Git 修改歷史

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。

查核基準 `91333c3` 的 source history 如下；`Application/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

> 查核日期：2026-10-24；Git 基準 `91333c3`。目標 `Application/`；本次僅靜態查核，未執行 build、測試、資料庫或外部服務。規格、實作與測試證據分開記錄。

## 範圍與日期語意

基準為`91333c3`；完整非shallow repository，查核所有可達的Application來源歷史（60筆），排除Application/docs，無日期截斷。下表按`git log --reverse`拓樸反向順序，非依author日期嚴格排序。日期為author ISO8601（含+08:00），author為Git author；不把co-author trailer當Git author。例`7533f63` author為13:21、committer為13:37，兩者不等同。

可重跑唯讀命令：

```sh
git rev-parse 91333c3
git rev-parse --is-shallow-repository
git log --reverse --format='%h|%aI|%an|%s' 91333c3 -- Application ':(exclude)Application/docs'
git show --format=fuller <sha> -- Application ':(exclude)Application/docs'
git show --format= --numstat <sha> -- Application ':(exclude)Application/docs'
```

表格subject保留原文作定位；目標內實際影響以限定路徑numstat列出的檔案與行數為準，不把整個commit的HTTP/worker subject誤稱全部發生在Application。新增/刪除行數不代表功能大小或品質。

| Author日期 | SHA | Author | Subject | Application內實際diff範圍與行數 |
|---|---|---|---|---|
| 2026-10-11T05:12:08+08:00 | `976d9fe` | Arthur801 | Add bestseller pages and web integration test harness (#5) | `Bestsellers/BestsellerService.cs` (+33/−0); `Bestsellers/BestsellerSnapshot.cs` (+12/−0); `Bestsellers/IBestsellerReader.cs` (+7/−0) |
| 2026-10-11T05:23:00+08:00 | `dc4a570` | Arthur801 | Address code review findings (#5) | `Bestsellers/BestsellerService.cs` (+6/−21) |
| 2026-10-11T13:08:12+08:00 | `83d36eb` | Arthur801 | Add Book detail query with per-Book cache | `Catalog/BookDetail.cs` (+24/−0); `Catalog/IBookDetailReader.cs` (+8/−0) |
| 2026-10-11T13:14:10+08:00 | `4855357` | Arthur801 | Address M4 code review: comments, cache key const, shared test cache | `Catalog/BookDetail.cs` (+4/−4) |
| 2026-10-11T13:10:44+08:00 | `5310920` | Arthur801 | Add local-only catalog search query for issue #8 | `Catalog/BookSearchPage.cs` (+20/−0); `Catalog/BookSearchService.cs` (+18/−0); `Catalog/IBookSearch.cs` (+8/−0); `Catalog/SearchQuery.cs` (+49/−0) |
| 2026-10-11T13:21:01+08:00 | `7533f63` | Arthur801 | Apply code review fixes to the catalog search query | `Catalog/BookSearchPage.cs` (+1/−1); `Catalog/BookSearchService.cs` (+1/−1); `Catalog/IBookSearch.cs` (+1/−1); `Catalog/SearchQuery.cs` (+24/−10) |
| 2026-10-20T20:54:42+08:00 | `e4c47e4` | Arthur801 | Add account input rules for registration and login | `Identity/AccountInputRules.cs` (+88/−0) |
| 2026-10-20T20:58:08+08:00 | `c8ce8ba` | Arthur801 | Wrap PasswordHasher behind a password hashing port | `Identity/IPasswordHashing.cs` (+16/−0) |
| 2026-10-20T21:00:04+08:00 | `c1af3d6` | Arthur801 | Add an EF user store with case-insensitive email lookup | `Identity/IUserStore.cs` (+23/−0) |
| 2026-10-20T21:03:37+08:00 | `65aa450` | Arthur801 | Add the account service for registration and login | `Identity/AccountService.cs` (+89/−0) |
| 2026-10-20T21:04:42+08:00 | `13abf86` | Arthur801 | Share the absent-user hash across account service instances | `Identity/AccountService.cs` (+9/−4) |
| 2026-10-20T23:42:30+08:00 | `9581a9e` | Arthur801 | Build the embedding input text and its hash for the backfill | `Recommendation/BookEmbeddingSource.cs` (+10/−0); `Recommendation/BookEmbeddingText.cs` (+76/−0) |
| 2026-10-20T23:44:17+08:00 | `ce0c811` | Arthur801 | Add the embedding generator port and a scripted fake for tests | `Recommendation/IEmbeddingGenerator.cs` (+10/−0) |
| 2026-10-20T23:48:23+08:00 | `2981b0f` | Arthur801 | Add the embedding store that finds pending Books and saves vectors | `Recommendation/IEmbeddingStore.cs` (+11/−0); `Recommendation/PendingEmbedding.cs` (+4/−0) |
| 2026-10-20T23:51:21+08:00 | `db566a2` | Arthur801 | Add the backfill round that generates and stores pending embeddings | `Recommendation/EmbeddingBackfillResult.cs` (+3/−0); `Recommendation/EmbeddingBackfillService.cs` (+69/−0); `Recommendation/EmbeddingOptions.cs` (+17/−0) |
| 2026-10-21T00:05:01+08:00 | `a6f4a07` | Arthur801 | Fail startup when an embedding setting is out of range | `Recommendation/EmbeddingOptions.cs` (+7/−0) |
| 2026-10-21T00:11:36+08:00 | `2b7a13e` | Arthur801 | Tidy the embedding code: stale comments, shared constants, one pending item | `Recommendation/EmbeddingBackfillService.cs` (+1/−1); `Recommendation/EmbeddingOptions.cs` (+2/−2); `Recommendation/IEmbeddingStore.cs` (+2/−2) |
| 2026-10-21T13:32:44+08:00 | `f2c76ac` | Arthur801 | Add requirement filter sanitizing and the parser port for #13 | `Recommendation/IRequirementParser.cs` (+8/−0); `Recommendation/ParsedRequirement.cs` (+4/−0); `Recommendation/RequirementFilters.cs` (+60/−0); `Recommendation/SanitizedFilters.cs` (+4/−0) |
| 2026-10-21T13:40:14+08:00 | `853d9a9` | Arthur801 | Add the Candidate Set port, its result record and similarity test vectors | `Recommendation/CandidateBook.cs` (+20/−0); `Recommendation/ICandidateSearch.cs` (+14/−0) |
| 2026-10-21T13:43:56+08:00 | `6e66254` | Arthur801 | Extract code point truncation into a shared CodePoints helper | `Recommendation/BookEmbeddingText.cs` (+1/−21); `Recommendation/CodePoints.cs` (+27/−0) |
| 2026-10-21T13:43:56+08:00 | `0be2251` | Arthur801 | Add ranking candidate numbering, validation rules and a fake ranker for #13 | `Recommendation/IRecommendationRanker.cs` (+11/−0); `Recommendation/RankedCandidate.cs` (+4/−0); `Recommendation/RankedItem.cs` (+4/−0); `Recommendation/RankingCandidate.cs` (+16/−0); `Recommendation/RankingRules.cs` (+80/−0) |
| 2026-10-21T13:44:38+08:00 | `fc6981f` | Arthur801 | Let only valid reasons claim a candidate number in ranking validation | `Recommendation/RankingRules.cs` (+5/−5) |
| 2026-10-21T13:46:55+08:00 | `682c156` | Arthur801 | Add the recommendation store port, its skeleton and failing database tests | `Recommendation/IRecommendationStore.cs` (+8/−0); `Recommendation/SavedRecommendationSearch.cs` (+4/−0) |
| 2026-10-21T13:49:20+08:00 | `82113fe` | Arthur801 | Add recommendation options with spec defaults and validators | `Recommendation/RecommendationOptions.cs` (+36/−0) |
| 2026-10-21T13:51:07+08:00 | `6a396eb` | Arthur801 | Add the recommendation service that orchestrates one search | `Recommendation/RecommendationOutcome.cs` (+4/−0); `Recommendation/RecommendationService.cs` (+93/−0) |
| 2026-10-21T13:57:30+08:00 | `337fb21` | Arthur801 | Move PublishedDateText into the catalog application layer | `Catalog/PublishedDateText.cs` (+25/−0) |
| 2026-10-21T14:03:01+08:00 | `9d1e38b` | Arthur801 | Add the recommendation requirement text rules | `Recommendation/RecommendationInputRules.cs` (+27/−0) |
| 2026-10-21T14:13:28+08:00 | `c143461` | Arthur801 | Remove the hard-coded chat model default | `Recommendation/RecommendationOptions.cs` (+2/−1) |
| 2026-10-21T14:14:06+08:00 | `cc73464` | Arthur801 | Measure ranking time only around the ranker call | `Recommendation/RecommendationService.cs` (+2/−2) |
| 2026-10-21T16:19:18+08:00 | `464cbd5` | Arthur801 | Lower the default similarity threshold to 0.45 | `Recommendation/RecommendationOptions.cs` (+1/−1) |
| 2026-10-22T07:47:33+08:00 | `2329eb8` | Arthur801 | Add Library core service and reading status codes (#11 M1) | `Library/ILibraryStore.cs` (+19/−0); `Library/LibraryItem.cs` (+14/−0); `Library/LibraryService.cs` (+42/−0); `Library/ReadingStatusCode.cs` (+47/−0) |
| 2026-10-22T09:41:48+08:00 | `0c11ea2` | Arthur801 | Run pending add-to-library after login and registration (#11 M5) | `Library/PendingLibraryAction.cs` (+21/−0) |
| 2026-10-22T09:53:44+08:00 | `e1809a4` | Arthur801 | Move pending add-to-library rule from AccountController into LibraryService | `Library/LibraryService.cs` (+26/−2) |
| 2026-10-22T09:54:36+08:00 | `efb7d4b` | Arthur801 | Accept only the canonical hyphenated Book id in pending add-to-library | `Library/PendingLibraryAction.cs` (+10/−2) |
| 2026-10-22T09:55:48+08:00 | `c961620` | Arthur801 | Build the Library login URL once and reuse it in library.js | `Library/PendingLibraryAction.cs` (+1/−1) |
| 2026-10-22T10:01:59+08:00 | `e5c57c8` | Arthur801 | Add PATCH body parser and library change model (#12 M1) | `Library/LibraryChange.cs` (+21/−0) |
| 2026-10-22T10:05:05+08:00 | `27ecea3` | Arthur801 | Add library update and remove to the store and service (#12 M2) | `Library/ILibraryStore.cs` (+7/−0); `Library/LibraryService.cs` (+13/−0) |
| 2026-10-22T10:27:09+08:00 | `217e035` | Arthur801 | Point the Library comments at the spec sections that hold the rules | `Library/LibraryChange.cs` (+1/−1); `Library/LibraryService.cs` (+1/−1) |
| 2026-10-22T10:27:53+08:00 | `4217ddc` | Arthur801 | Keep one list of reading statuses in ReadingStatusCode.All | `Library/ReadingStatusCode.cs` (+4/−0) |
| 2026-10-22T10:34:51+08:00 | `9b0a8a1` | Arthur801 | Move TaipeiTimeZone to Application/Common | `Common/TaipeiTimeZone.cs` (+27/−0) |
| 2026-10-22T10:36:04+08:00 | `5ee765f` | Arthur801 | Add Taipei day start and Recommendation DailyLimit setting | `Common/TaipeiTimeZone.cs` (+9/−0); `Recommendation/RecommendationOptions.cs` (+5/−0) |
| 2026-10-22T10:38:33+08:00 | `aeb12e2` | Arthur801 | Add the daily-limit usage count port (#15 M2) | `Recommendation/IRecommendationUsage.cs` (+9/−0) |
| 2026-10-22T10:43:43+08:00 | `d32d41c` | Arthur801 | Add the daily Recommendation limit gate (#15 M3) | `Recommendation/RecommendationAttempt.cs` (+10/−0); `Recommendation/RecommendationService.cs` (+17/−2) |
| 2026-10-22T10:49:10+08:00 | `75d710a` | Arthur801 | Map OpenAI failures to AI unavailable, 502 (#15 M4) | `Recommendation/AiUnavailableException.cs` (+5/−0); `Recommendation/IEmbeddingGenerator.cs` (+1/−0); `Recommendation/IRecommendationRanker.cs` (+1/−0); `Recommendation/IRequirementParser.cs` (+1/−0) |
| 2026-10-22T10:54:32+08:00 | `ffbc063` | Arthur801 | Add the 60 s recommendation timeout to 504 (#15 M5) | `Recommendation/AiTimeoutException.cs` (+5/−0); `Recommendation/RecommendationOptions.cs` (+4/−0); `Recommendation/RecommendationService.cs` (+79/−58) |
| 2026-10-22T11:01:45+08:00 | `8268ccb` | Arthur801 | Log each failed AI recommendation once in the service (#15 review) | `Recommendation/RecommendationService.cs` (+6/−0) |
| 2026-10-22T11:01:55+08:00 | `4ff2b16` | Arthur801 | Correct the TaipeiTimeZone and OpenAiCall comments (#15 review) | `Common/TaipeiTimeZone.cs` (+2/−1) |
| 2026-10-22T11:07:56+08:00 | `65fcac1` | Arthur801 | Add AI search history reader (#16 M1) | `Recommendation/HistoryModels.cs` (+20/−0); `Recommendation/IRecommendationHistory.cs` (+11/−0) |
| 2026-10-22T11:25:01+08:00 | `a0cd6ae` | Arthur801 | Name the history read models after the glossary (#16 review) | `Recommendation/HistoryModels.cs` (+0/−20); `Recommendation/IRecommendationHistory.cs` (+2/−2); `Recommendation/RecommendationSearchReadModels.cs` (+20/−0) |
| 2026-10-22T11:27:29+08:00 | `982ad1c` | Arthur801 | Format the history minute in TaipeiTimeZone, not in the list model (#16 review) | `Common/TaipeiTimeZone.cs` (+5/−0) |
| 2026-10-22T11:32:48+08:00 | `8569a1b` | Arthur801 | Add AI profile input text and hash (issue #18 M1) | `Recommendation/BookProfileSource.cs` (+13/−0); `Recommendation/BookProfileText.cs` (+66/−0) |
| 2026-10-22T11:33:39+08:00 | `f7345a5` | Arthur801 | Extract shared metadata text and hash helpers (issue #18 M1 refactor) | `Recommendation/BookEmbeddingText.cs` (+6/−38); `Recommendation/BookProfileText.cs` (+9/−41); `Recommendation/ContentHash.cs` (+14/−0); `Recommendation/MetadataLines.cs` (+35/−0) |
| 2026-10-22T11:37:22+08:00 | `0c02836` | Arthur801 | Add book AI profile generator port and normalisation (issue #18 M2) | `Recommendation/BookProfileRules.cs` (+87/−0); `Recommendation/GeneratedBookProfile.cs` (+18/−0); `Recommendation/IBookProfileGenerator.cs` (+14/−0) |
| 2026-10-22T11:46:03+08:00 | `d5e1589` | Arthur801 | Add book profile store (issue #18 M4) | `Recommendation/IBookProfileStore.cs` (+25/−0) |
| 2026-10-22T11:50:43+08:00 | `d293dfa` | Arthur801 | Add book profile queue and worker (issue #18 M5) | `Recommendation/AiProfileOptions.cs` (+16/−0); `Recommendation/BookProfileGenerationService.cs` (+38/−0); `Recommendation/IBookProfileQueue.cs` (+15/−0) |
| 2026-10-22T12:09:17+08:00 | `cda623f` | Arthur801 | Wire the Book AI profile into recommendations and history (issue #18 M6) | `Recommendation/BookProfileScheduler.cs` (+22/−0); `Recommendation/RecommendationOutcome.cs` (+5/−1); `Recommendation/RecommendationService.cs` (+28/−1) |
| 2026-10-22T12:14:43+08:00 | `cd17224` | Arthur801 | Show a dash instead of an error when the difficulty read fails (issue #18) | `Recommendation/BookDifficultyReader.cs` (+24/−0); `Recommendation/RecommendationService.cs` (+2/−16) |
| 2026-10-22T12:15:05+08:00 | `0fb9274` | Arthur801 | Do not queue Book profiles when AiProfile:Enabled is false (issue #18) | `Recommendation/BookProfileScheduler.cs` (+10/−1) |
| 2026-10-22T12:15:15+08:00 | `948330c` | Arthur801 | Reuse MetadataLines.Normalize in BookProfileRules (issue #18) | `Recommendation/BookProfileRules.cs` (+4/−10) |
| 2026-10-22T12:17:13+08:00 | `9ef23cc` | Arthur801 | Cite the recommendation spec instead of the plan in the AI profile code (issue #18) | `Recommendation/AiProfileOptions.cs` (+2/−2); `Recommendation/BookProfileRules.cs` (+1/−1); `Recommendation/BookProfileText.cs` (+1/−1); `Recommendation/GeneratedBookProfile.cs` (+1/−1); `Recommendation/RecommendationService.cs` (+1/−1) |

## 重要 diff 與維護轉折

已進一步閱讀`6a396eb`、`ffbc063`、`cda623f`、`7533f63`的Application patch，並對照其餘列出的numstat/現行來源。

| SHA | 目標內語意與查核結果 |
|---|---|
| `7533f63` | SearchQuery新增NFKC ISBN判定、無效Unicode降為keyword，Isbn帶原trim文字；SQL ILIKE修正在目標外Infrastructure，不歸入Application patch。 |
| `6a396eb` | 新RecommendationService依parse→sanitize→embed→search→rank→save；候選空仍保存；Google telemetry自此即固定false/0，不能說fallback已完成。 |
| `ffbc063` | 增加60秒linked cancellation與AiTimeoutException，caller取消維持原例外；HTTP 504 mapping是目標外filter責任。 |
| `cda623f` | 新增scheduler與difficulty outcome；保存後先讀difficulty再排工作、使用caller token；排序未引入profile。後續`cd17224`把讀取降級抽至BookDifficultyReader。 |
| `13abf86` | 現況AccountService以static LazyInitializer共享absent-user hash，避免每scope多一次hash；不是登入policy變更。 |
| `db566a2` | 背景backfill service與result/options進入本層；逐本處理、5次連續失敗中止，維度異常交store處理。 |
| `27ecea3` | ILibraryStore/LibraryService新增update/remove；空change轉FindAsync，非空帶目前時間。SQL隔離由adapter實作。 |
| `d32d41c` | RecommendationAttempt新增DailyLimitReached；service先quota再外部流程。count/save無鎖是已記錄選擇。 |
| `0fb9274` | scheduler新增Enabled早退；防止無worker仍填滿queue。這是已修歷史，不作待辦。 |

## 相關依賴與限制

[Program](../../Program.cs)、[EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs)、cache readers、OpenAI adapters與background workers是目前跨層證據。本表只完整枚舉Application路徑歷史；沒有宣稱完整追溯所有依賴目錄，也未用Implementation-Report當規格。

截至查核基準 `91333c3`，`Application/docs/` 尚不存在；本 PR 中新增及後續修正這五份文件的 commits 不納入上述 Application source history。不能由來源建立時間推定部署時間。Git commit記錄不代表測試在本次通過、功能已上線或production已驗證。

## #109 M1 書庫後端（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 分支／提交 | Subject | 影響 |
|---|---|---|
| `831fcee` | feat(catalog): add BookBrowse use case and port for 書庫 | 新增 BookBrowseService、IBookBrowse、BookBrowsePage／BookBrowseItem |
| `7c369fd` | feat(catalog): implement EF book browse list and random sample | Infrastructure 實作與 DI 註冊（Bestseller 註冊不變） |
| `b2c04ce` | test(bestseller): guard retained Bestseller backend through DI | 新增 Bestseller 後端 DI 守衛測試，無產品行為變更 |
| 本 commit | fix(catalog): compute 書庫 TotalPages in long so it cannot overflow | BookBrowsePage.TotalPages 改以 long 計算，避免 TotalCount 接近 int.MaxValue 時溢位；新增 BookBrowsePageTotalPagesTests |
| 2026-10-25 | `2a6966b` | feat(catalog): add ISBN normalization protocol and shared fixture | `Catalog/IsbnNormalizer.cs`（新增，data-model 7.1 写入端正規化）；測試 `tests/UnitTests/IsbnNormalizerTests.cs` 讀 `tests/Fixtures/isbn-normalization.json` |
| 2026-10-25 | `2c662f5` | feat(db): add expand migration 010 for multi-source catalog | `Catalog/BookDetail.cs`：`BookDetailSource` 的 `SourceType Type` 改為 `string SourceCode`（不再依賴 Domain enum） |

## 導覽

[流程](workflow-diagram.md)・[架構](architecture.md)・[待辦](backlog.md)・[歷史](update-history.md)・[案例](test-suite.md)
