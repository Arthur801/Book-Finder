# tests 修改歷史

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。

查核基準 `91333c3` 的 source history 如下；`tests/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

> 查核 2026-10-24；HEAD `91333c3`。日期採 author date，不代表部署日或本次測試結果。作者以 Git author 記錄；committer date 未用於排序。

## 範圍與可重跑命令

直接來源為 `tests`，排除 `tests/docs`。查核全量可達歷史；下表以 `--reverse --no-merges` 呈現非 merge commits，merge 的來源變更已由其原 commit 表示，避免重複計數。沒有執行測試。

```sh
git log --reverse --no-merges --date=short --format='%h|%ad|%an|%s' 91333c3 -- tests ':(exclude)tests/docs'
git show --format= --stat <SHA> -- tests ':(exclude)tests/docs'
git show <SHA> -- tests
```

Git 歷史不證明 runtime 或 CI 已通過。

## 維護轉折（已閱讀重要 diff）

- `6b19340`：建立 DB schema／mapping／constraint 測試與 PostgresFixture，不是部署證據。
- `976d9fe`：建立 WebIntegration project、WebFixture、Bestseller 與首頁／layout HTTP 測試；後續測資改為 CatalogSeed。
- `f233b9d`：WebFixture 關閉 config reload，diff 為 static constructor 設定環境變數；commit 說明 inotify 耗盡，屬已修問題。
- `6a396eb`、`22542ca`：service 編排與 HTTP API 測試逐步分層，不將 service fake 成功等同完整外部整合。
- `cda623f`：擴充 scheduler、service、API 與 history 測試以支援 difficulty 與非同步 profile 行為。
- `dccad53`：兩個 .NET fixtures 的 image 字串固定為 `0.8.7-pg17`；commit 說明 digest 不變，非 runtime 驗證。
- `2a74705`：tests 內實際新增 HostingSetupTests 驗證 trusted network 與 key path；不能從整個 commit subject 推成 production proxy 已驗證。

## 全量非 merge 直接歷史

每列附實際受影響測試檔案；subject 保留為查核索引，不拿它替代目標內 diff。檔案多於四個時以數量揭露截斷，完整清單可用上方 git show 重現。

| Author 日期 | SHA | Author | Subject | tests 內變更檔案 |
|---|---|---|---|---|
| 2026-10-11 | `6b19340` | Arthur801 | Complete PostgreSQL db creation | `tests/DatabaseIntegration/DatabaseIntegration.csproj`, `tests/DatabaseIntegration/ModelSnapshotTests.cs`, `tests/DatabaseIntegration/PostgresFixture.cs`, `tests/DatabaseIntegration/SchemaTests.cs`（共 6 檔，列前 4） |
| 2026-10-11 | `be3cce9` | Arthur801 | Require user on recommendation searches (#1) | `tests/DatabaseIntegration/SchemaTests.cs`, `tests/DatabaseIntegration/constraints.sql` |
| 2026-10-11 | `0c064f1` | Arthur801 | Add book_embeddings table with vector(1536) (#2) | `tests/DatabaseIntegration/SchemaTests.cs`, `tests/DatabaseIntegration/constraints.sql` |
| 2026-10-11 | `976d9fe` | Arthur801 | Add bestseller pages and web integration test harness (#5) | `tests/WebIntegration/BestsellerCacheTests.cs`, `tests/WebIntegration/BestsellerPageTests.cs`, `tests/WebIntegration/BestsellerSeed.cs`, `tests/WebIntegration/HttpAssertions.cs`（共 7 檔，列前 4） |
| 2026-10-11 | `dc4a570` | Arthur801 | Address code review findings (#5) | `tests/UnitTests/BestsellerServiceTests.cs`, `tests/UnitTests/CachedBestsellerReaderTests.cs`, `tests/UnitTests/TaipeiTimeZoneTests.cs`, `tests/UnitTests/UnitTests.csproj`（共 10 檔，列前 4） |
| 2026-10-11 | `8e46749` | Arthur801 | Replace BestsellerSeed with a full Catalog seed for web tests | `tests/WebIntegration/BestsellerPageTests.cs`, `tests/WebIntegration/BestsellerSeed.cs`, `tests/WebIntegration/CatalogSeed.cs`, `tests/WebIntegration/CatalogSeedTests.cs`（共 6 檔，列前 4） |
| 2026-10-11 | `b5f9a34` | Arthur801 | Add catalog display rules for publish dates and contributors | `tests/UnitTests/ContributorDisplayTests.cs`, `tests/UnitTests/PublishedDateTextTests.cs` |
| 2026-10-11 | `cf26eb6` | Arthur801 | Address code review of catalog display rules | `tests/UnitTests/ContributorDisplayTests.cs`, `tests/UnitTests/PublishedDateTextTests.cs` |
| 2026-10-11 | `83d36eb` | Arthur801 | Add Book detail query with per-Book cache | `tests/UnitTests/BookDetailContractTests.cs`, `tests/UnitTests/CachedBookDetailReaderTests.cs` |
| 2026-10-11 | `4855357` | Arthur801 | Address M4 code review: comments, cache key const, shared test cache | `tests/UnitTests/BookDetailContractTests.cs`, `tests/UnitTests/CachedBestsellerReaderTests.cs`, `tests/UnitTests/CachedBookDetailReaderTests.cs`, `tests/UnitTests/RecordingMemoryCache.cs` |
| 2026-10-11 | `b4d2aaf` | Arthur801 | Add Book detail page at /books/{id} | `tests/WebIntegration/BookDetailPageTests.cs`, `tests/WebIntegration/CatalogSeed.cs` |
| 2026-10-11 | `668d0fb` | Arthur801 | Address M5 code review: safe links, blank subjects, titles, test helpers | `tests/WebIntegration/BookDetailPageTests.cs`, `tests/WebIntegration/HtmlPage.cs` |
| 2026-10-11 | `5310920` | Arthur801 | Add local-only catalog search query for issue #8 | `tests/UnitTests/BookSearchServiceTests.cs`, `tests/UnitTests/SearchQueryTests.cs` |
| 2026-10-11 | `7533f63` | Arthur801 | Apply code review fixes to the catalog search query | `tests/UnitTests/BookSearchServiceTests.cs`, `tests/UnitTests/SearchQueryTests.cs` |
| 2026-10-11 | `8684513` | Arthur801 | Add pagination window for catalog search results | `tests/UnitTests/PageWindowTests.cs` |
| 2026-10-11 | `0efed0b` | Arthur801 | Add the general search results page at /search | `tests/WebIntegration/SearchPageTests.cs` |
| 2026-10-11 | `f233b9d` | Arthur801 | Turn off config reload in web integration hosts | `tests/WebIntegration/WebFixture.cs` |
| 2026-10-11 | `53c0391` | Arthur801 | Redirect search pages past the last page to the last page | `tests/UnitTests/PageWindowTests.cs`, `tests/WebIntegration/HtmlPage.cs`, `tests/WebIntegration/SearchPageTests.cs` |
| 2026-10-11 | `795d77a` | Arthur801 | Remove the unused CountOccurrences test helper | `tests/WebIntegration/HtmlPage.cs` |
| 2026-10-12 | `11190ed` | Arthur801 | Test deployment | `tests/WebIntegration/ForwardedHeadersTests.cs` |
| 2026-10-20 | `e4c47e4` | Arthur801 | Add account input rules for registration and login | `tests/UnitTests/AccountInputRulesTests.cs` |
| 2026-10-20 | `c8ce8ba` | Arthur801 | Wrap PasswordHasher behind a password hashing port | `tests/UnitTests/AspNetPasswordHashingTests.cs` |
| 2026-10-20 | `c1af3d6` | Arthur801 | Add an EF user store with case-insensitive email lookup | `tests/DatabaseIntegration/EfUserStoreTests.cs` |
| 2026-10-20 | `020ff13` | Arthur801 | Lowercase email lookups in PostgreSQL to match the unique index | `tests/DatabaseIntegration/EfUserStoreTests.cs` |
| 2026-10-20 | `65aa450` | Arthur801 | Add the account service for registration and login | `tests/UnitTests/AccountServiceTests.cs` |
| 2026-10-20 | `13abf86` | Arthur801 | Share the absent-user hash across account service instances | `tests/UnitTests/AccountServiceTests.cs` |
| 2026-10-20 | `c13d862` | Arthur801 | Issue HS256 auth tokens from the configured signing key | `tests/UnitTests/AuthTokenIssuerTests.cs`, `tests/UnitTests/JwtOptionsTests.cs` |
| 2026-10-20 | `6a2dbc7` | Arthur801 | Add the auth cookie helper with its fixed attributes | `tests/UnitTests/AuthCookieTests.cs` |
| 2026-10-20 | `40ec61a` | Arthur801 | Authenticate requests from the auth cookie with cookie-aware challenges | `tests/WebIntegration/AuthPipelineTests.cs`, `tests/WebIntegration/TestOnlyAuthController.cs`, `tests/WebIntegration/WebFixture.cs`, `tests/WebIntegration/WebIntegration.csproj` |
| 2026-10-20 | `2437ca7` | Arthur801 | Return a ProblemDetails 400 for API antiforgery failures | `tests/WebIntegration/AuthPipelineTests.cs` |
| 2026-10-20 | `5d2113a` | Arthur801 | Resolve return URLs to local paths only | `tests/UnitTests/SafeReturnUrlTests.cs` |
| 2026-10-20 | `482f16d` | Arthur801 | Cover decoded control characters in return URL tests | `tests/UnitTests/SafeReturnUrlTests.cs` |
| 2026-10-20 | `6faf1e2` | Arthur801 | Add login, registration and logout pages | `tests/WebIntegration/AccountPagesTests.cs`, `tests/WebIntegration/HtmlPage.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-20 | `0b60633` | Arthur801 | Show the signed-in user and a logout button in the navbar | `tests/WebIntegration/NavbarTests.cs` |
| 2026-10-20 | `e530787` | Arthur801 | Leave returnUrl out of challenges for non-GET page requests | `tests/WebIntegration/AuthPipelineTests.cs`, `tests/WebIntegration/TestOnlyAuthController.cs` |
| 2026-10-20 | `3134b7a` | Arthur801 | Share the API path check and name claim constant across auth code | `tests/WebIntegration/AuthPipelineTests.cs` |
| 2026-10-20 | `a57d58d` | Arthur801 | Share the account form helpers between web tests | `tests/WebIntegration/AccountFlow.cs`, `tests/WebIntegration/AccountPagesTests.cs`, `tests/WebIntegration/NavbarTests.cs` |
| 2026-10-20 | `9581a9e` | Arthur801 | Build the embedding input text and its hash for the backfill | `tests/UnitTests/BookEmbeddingTextTests.cs` |
| 2026-10-20 | `ce0c811` | Arthur801 | Add the embedding generator port and a scripted fake for tests | `tests/Shared/FakeEmbeddingGenerator.cs`, `tests/UnitTests/FakeEmbeddingGeneratorTests.cs`, `tests/UnitTests/UnitTests.csproj`, `tests/WebIntegration/WebIntegration.csproj` |
| 2026-10-20 | `2981b0f` | Arthur801 | Add the embedding store that finds pending Books and saves vectors | `tests/DatabaseIntegration/EfEmbeddingStoreTests.cs` |
| 2026-10-20 | `db566a2` | Arthur801 | Add the backfill round that generates and stores pending embeddings | `tests/UnitTests/EmbeddingBackfillServiceTests.cs` |
| 2026-10-20 | `137e5fe` | Arthur801 | Add the OpenAI embedding generator and its service registration | `tests/UnitTests/OpenAiEmbeddingGeneratorTests.cs`, `tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs` |
| 2026-10-21 | `2db12b9` | Arthur801 | Start the embedding backfill on a timer and wire it into the web app | `tests/UnitTests/EmbeddingBackfillWorkerTests.cs`, `tests/UnitTests/UnitTests.csproj`, `tests/WebIntegration/EmbeddingBackfillTests.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-21 | `a6f4a07` | Arthur801 | Fail startup when an embedding setting is out of range | `tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs` |
| 2026-10-21 | `2b7a13e` | Arthur801 | Tidy the embedding code: stale comments, shared constants, one pending item | `tests/DatabaseIntegration/EfEmbeddingStoreTests.cs`, `tests/Shared/FakeEmbeddingGenerator.cs`, `tests/UnitTests/EmbeddingBackfillServiceTests.cs`, `tests/UnitTests/EmbeddingBackfillWorkerTests.cs` |
| 2026-10-21 | `5cd00d8` | Arthur801 | Cover the embedding round with several books and a changed title | `tests/WebIntegration/EmbeddingBackfillTests.cs` |
| 2026-10-21 | `f2c76ac` | Arthur801 | Add requirement filter sanitizing and the parser port for #13 | `tests/Shared/FakeRequirementParser.cs`, `tests/UnitTests/FakeRequirementParserTests.cs`, `tests/UnitTests/RequirementFiltersTests.cs`, `tests/UnitTests/UnitTests.csproj`（共 5 檔，列前 4） |
| 2026-10-21 | `853d9a9` | Arthur801 | Add the Candidate Set port, its result record and similarity test vectors | `tests/DatabaseIntegration/DatabaseIntegration.csproj`, `tests/Shared/SimilarityVectors.cs`, `tests/UnitTests/SimilarityVectorsTests.cs`, `tests/UnitTests/UnitTests.csproj`（共 5 檔，列前 4） |
| 2026-10-21 | `2ada37f` | Arthur801 | Implement the Candidate Set search over pgvector and the hard filters | `tests/DatabaseIntegration/EfCandidateSearchTests.cs`, `tests/DatabaseIntegration/PostgresFixture.cs` |
| 2026-10-21 | `6e66254` | Arthur801 | Extract code point truncation into a shared CodePoints helper | `tests/UnitTests/CodePointsTests.cs` |
| 2026-10-21 | `0be2251` | Arthur801 | Add ranking candidate numbering, validation rules and a fake ranker for #13 | `tests/Shared/FakeRecommendationRanker.cs`, `tests/UnitTests/FakeRecommendationRankerTests.cs`, `tests/UnitTests/RankingRulesTests.cs`, `tests/UnitTests/UnitTests.csproj`（共 5 檔，列前 4） |
| 2026-10-21 | `fc6981f` | Arthur801 | Let only valid reasons claim a candidate number in ranking validation | `tests/UnitTests/RankingRulesTests.cs` |
| 2026-10-21 | `682c156` | Arthur801 | Add the recommendation store port, its skeleton and failing database tests | `tests/DatabaseIntegration/DatabaseIntegration.csproj`, `tests/DatabaseIntegration/EfRecommendationStoreTests.cs` |
| 2026-10-21 | `82113fe` | Arthur801 | Add recommendation options with spec defaults and validators | `tests/UnitTests/RecommendationOptionsTests.cs` |
| 2026-10-21 | `6a396eb` | Arthur801 | Add the recommendation service that orchestrates one search | `tests/UnitTests/RecommendationServiceTests.cs` |
| 2026-10-21 | `6900a2b` | Arthur801 | Add the OpenAI requirement parser with a shared fake transport | `tests/UnitTests/OpenAiEmbeddingGeneratorTests.cs`, `tests/UnitTests/OpenAiRequirementParserTests.cs`, `tests/UnitTests/OpenAiTestTransport.cs` |
| 2026-10-21 | `df7084f` | Arthur801 | Add the OpenAI recommendation ranker | `tests/UnitTests/OpenAiRecommendationRankerTests.cs` |
| 2026-10-21 | `7c331ad` | Arthur801 | Register the chat adapters and validate the recommendation settings | `tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs` |
| 2026-10-21 | `337fb21` | Arthur801 | Move PublishedDateText into the catalog application layer | `tests/UnitTests/PublishedDateTextTests.cs` |
| 2026-10-21 | `9d1e38b` | Arthur801 | Add the recommendation requirement text rules | `tests/UnitTests/RecommendationInputRulesTests.cs` |
| 2026-10-21 | `22542ca` | Arthur801 | Add the POST /api/recommendations endpoint | `tests/WebIntegration/RecommendationApiTests.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-21 | `4081d41` | Arthur801 | Add the /ai page and its WebIntegration tests | `tests/WebIntegration/AiPageTests.cs`, `tests/WebIntegration/LayoutAndHomeTests.cs` |
| 2026-10-21 | `c143461` | Arthur801 | Remove the hard-coded chat model default | `tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs`, `tests/UnitTests/RecommendationOptionsTests.cs` |
| 2026-10-21 | `88cfa89` | Arthur801 | Prove the ranked statement adds SQL only for set filters | `tests/DatabaseIntegration/EfCandidateSearchTests.cs` |
| 2026-10-21 | `464cbd5` | Arthur801 | Lower the default similarity threshold to 0.45 | `tests/UnitTests/RecommendationOptionsTests.cs`, `tests/UnitTests/RecommendationServiceTests.cs`, `tests/WebIntegration/RecommendationApiTests.cs` |
| 2026-10-21 | `9d5cb2e` | Arthur801 | Make year boundaries in the parser prompt include the named year | `tests/UnitTests/OpenAiRequirementParserTests.cs` |
| 2026-10-22 | `2329eb8` | Arthur801 | Add Library core service and reading status codes (#11 M1) | `tests/UnitTests/LibraryServiceTests.cs`, `tests/UnitTests/ReadingStatusCodeTests.cs` |
| 2026-10-22 | `d0e1c85` | Arthur801 | Add EF Library store and DI registration (#11 M2) | `tests/DatabaseIntegration/EfLibraryStoreTests.cs` |
| 2026-10-22 | `f258880` | Arthur801 | Add PUT /api/library/{bookId} add-to-library endpoint (#11 M3) | `tests/WebIntegration/LibraryApiTests.cs` |
| 2026-10-22 | `becc5e2` | Arthur801 | Add Library section to the Book detail page (#11 M4) | `tests/WebIntegration/BookDetailPageTests.cs`, `tests/WebIntegration/BookLibrarySectionTests.cs`, `tests/WebIntegration/HtmlPage.cs` |
| 2026-10-22 | `0c11ea2` | Arthur801 | Run pending add-to-library after login and registration (#11 M5) | `tests/UnitTests/PendingLibraryActionTests.cs`, `tests/WebIntegration/AccountFlow.cs`, `tests/WebIntegration/PendingLibraryActionTests.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-22 | `7f61fcc` | Arthur801 | Add /library page with filter tabs and read-only rows (#11 M6) | `tests/WebIntegration/LibraryPageTests.cs` |
| 2026-10-22 | `e1809a4` | Arthur801 | Move pending add-to-library rule from AccountController into LibraryService | `tests/UnitTests/LibraryServiceTests.cs` |
| 2026-10-22 | `efb7d4b` | Arthur801 | Accept only the canonical hyphenated Book id in pending add-to-library | `tests/UnitTests/PendingLibraryActionTests.cs` |
| 2026-10-22 | `c961620` | Arthur801 | Build the Library login URL once and reuse it in library.js | `tests/WebIntegration/BookLibrarySectionTests.cs` |
| 2026-10-22 | `5a827b1` | Arthur801 | Share the UTC to Taipei conversion between library and recommendation responses | `tests/UnitTests/TaipeiTimeZoneTests.cs` |
| 2026-10-22 | `e5c57c8` | Arthur801 | Add PATCH body parser and library change model (#12 M1) | `tests/UnitTests/LibraryPatchParserTests.cs` |
| 2026-10-22 | `27ecea3` | Arthur801 | Add library update and remove to the store and service (#12 M2) | `tests/DatabaseIntegration/EfLibraryStoreTests.cs`, `tests/UnitTests/LibraryServiceTests.cs`, `tests/WebIntegration/PendingLibraryActionTests.cs` |
| 2026-10-22 | `7a310f7` | Arthur801 | Add PATCH and DELETE for library entries (#12 M3) | `tests/WebIntegration/LibraryApiTests.cs` |
| 2026-10-22 | `249c378` | Arthur801 | Translate only the Book FK violation to not found in library add (#11 M2) | `tests/DatabaseIntegration/EfLibraryStoreTests.cs` |
| 2026-10-22 | `66ecf55` | Arthur801 | Add shared library controls to the Book page and /library (#12 M4) | `tests/WebIntegration/BookLibrarySectionTests.cs`, `tests/WebIntegration/HtmlPage.cs`, `tests/WebIntegration/LibraryPageTests.cs` |
| 2026-10-22 | `ef2b929` | Arthur801 | Show 未評分 next to the stars for an unrated entry | `tests/WebIntegration/BookLibrarySectionTests.cs`, `tests/WebIntegration/HtmlPage.cs`, `tests/WebIntegration/LibraryPageTests.cs` |
| 2026-10-22 | `0a70d42` | Arthur801 | Parse the PATCH library body as JSON whatever its Content-Type | `tests/WebIntegration/LibraryApiTests.cs` |
| 2026-10-22 | `4217ddc` | Arthur801 | Keep one list of reading statuses in ReadingStatusCode.All | `tests/UnitTests/ReadingStatusCodeTests.cs` |
| 2026-10-22 | `704c9e8` | Arthur801 | Build the login link in one helper for the Library pages | `tests/UnitTests/LoginLinkTests.cs` |
| 2026-10-22 | `9b0a8a1` | Arthur801 | Move TaipeiTimeZone to Application/Common | `tests/UnitTests/TaipeiTimeZoneTests.cs` |
| 2026-10-22 | `5ee765f` | Arthur801 | Add Taipei day start and Recommendation DailyLimit setting | `tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs`, `tests/UnitTests/RecommendationOptionsTests.cs`, `tests/UnitTests/TaipeiTimeZoneTests.cs` |
| 2026-10-22 | `aeb12e2` | Arthur801 | Add the daily-limit usage count port (#15 M2) | `tests/DatabaseIntegration/EfRecommendationUsageTests.cs` |
| 2026-10-22 | `d32d41c` | Arthur801 | Add the daily Recommendation limit gate (#15 M3) | `tests/UnitTests/RecommendationServiceTests.cs`, `tests/WebIntegration/RecommendationApiTests.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-22 | `75d710a` | Arthur801 | Map OpenAI failures to AI unavailable, 502 (#15 M4) | `tests/UnitTests/EmbeddingBackfillServiceTests.cs`, `tests/UnitTests/OpenAiEmbeddingGeneratorTests.cs`, `tests/UnitTests/OpenAiRecommendationRankerTests.cs`, `tests/UnitTests/OpenAiRequirementParserTests.cs`（共 6 檔，列前 4） |
| 2026-10-22 | `ffbc063` | Arthur801 | Add the 60 s recommendation timeout to 504 (#15 M5) | `tests/Shared/CallGate.cs`, `tests/Shared/FakeRecommendationRanker.cs`, `tests/Shared/FakeRequirementParser.cs`, `tests/UnitTests/RecommendationServiceTests.cs`（共 7 檔，列前 4） |
| 2026-10-22 | `8268ccb` | Arthur801 | Log each failed AI recommendation once in the service (#15 review) | `tests/UnitTests/ApiExceptionProblemDetailsFilterTests.cs`, `tests/UnitTests/RecommendationServiceTests.cs` |
| 2026-10-22 | `65fcac1` | Arthur801 | Add AI search history reader (#16 M1) | `tests/DatabaseIntegration/EfRecommendationHistoryTests.cs` |
| 2026-10-22 | `b6bf8ea` | Arthur801 | Move the page number parsing into PageNumber (#16) | `tests/UnitTests/PageNumberTests.cs` |
| 2026-10-22 | `fc9bcc3` | Arthur801 | Guard the history page offset against int overflow (#16) | `tests/DatabaseIntegration/EfRecommendationHistoryTests.cs` |
| 2026-10-22 | `852591c` | Arthur801 | Show the AI search history list on /ai (#16 M2) | `tests/WebIntegration/AiHistoryListTests.cs`, `tests/WebIntegration/AiPageTests.cs` |
| 2026-10-22 | `ddb4f9a` | Arthur801 | Show a saved AI search on /ai/history/{id} (#16 M3) | `tests/WebIntegration/AiHistoryDetailTests.cs` |
| 2026-10-22 | `894883b` | Arthur801 | Share one pager between /search and the AI history list (#16 review) | `tests/WebIntegration/HtmlPage.cs` |
| 2026-10-22 | `982ad1c` | Arthur801 | Format the history minute in TaipeiTimeZone, not in the list model (#16 review) | `tests/UnitTests/TaipeiTimeZoneTests.cs` |
| 2026-10-22 | `8569a1b` | Arthur801 | Add AI profile input text and hash (issue #18 M1) | `tests/UnitTests/BookProfileTextTests.cs` |
| 2026-10-22 | `0c02836` | Arthur801 | Add book AI profile generator port and normalisation (issue #18 M2) | `tests/Shared/FakeBookProfileGenerator.cs`, `tests/UnitTests/BookProfileRulesTests.cs`, `tests/UnitTests/FakeBookProfileGeneratorTests.cs`, `tests/UnitTests/UnitTests.csproj`（共 5 檔，列前 4） |
| 2026-10-22 | `9e26c4f` | Arthur801 | Add OpenAI book profile generator (issue #18 M3) | `tests/UnitTests/OpenAiBookProfileGeneratorTests.cs`, `tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-22 | `d5e1589` | Arthur801 | Add book profile store (issue #18 M4) | `tests/DatabaseIntegration/EfBookProfileStoreTests.cs` |
| 2026-10-22 | `d293dfa` | Arthur801 | Add book profile queue and worker (issue #18 M5) | `tests/UnitTests/AiProfileOptionsTests.cs`, `tests/UnitTests/BookProfileGenerationServiceTests.cs`, `tests/UnitTests/BookProfileQueueTests.cs`, `tests/UnitTests/BookProfileWorkerTests.cs` |
| 2026-10-22 | `cda623f` | Arthur801 | Wire the Book AI profile into recommendations and history (issue #18 M6) | `tests/UnitTests/BookProfileSchedulerTests.cs`, `tests/UnitTests/RecommendationServiceTests.cs`, `tests/WebIntegration/AiHistoryDetailTests.cs`, `tests/WebIntegration/RecommendationApiTests.cs` |
| 2026-10-22 | `cd17224` | Arthur801 | Show a dash instead of an error when the difficulty read fails (issue #18) | `tests/UnitTests/BookDifficultyReaderTests.cs`, `tests/UnitTests/RecommendationServiceTests.cs`, `tests/WebIntegration/AiHistoryDetailTests.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-22 | `0fb9274` | Arthur801 | Do not queue Book profiles when AiProfile:Enabled is false (issue #18) | `tests/UnitTests/BookProfileSchedulerTests.cs`, `tests/UnitTests/RecommendationServiceTests.cs` |
| 2026-10-22 | `09d4924` | Arthur801 | Register the Book AI profile services in one extension (issue #18) | `tests/UnitTests/AiProfileOptionsTests.cs` |
| 2026-10-22 | `9ef23cc` | Arthur801 | Cite the recommendation spec instead of the plan in the AI profile code (issue #18) | `tests/DatabaseIntegration/EfBookProfileStoreTests.cs`, `tests/UnitTests/RecommendationServiceTests.cs` |
| 2026-10-22 | `a4c1fdc` | Arthur801 | Keep the profile-only columns out of the embedding scan (issue #18) | `tests/DatabaseIntegration/EfEmbeddingStoreTests.cs` |
| 2026-10-23 | `b6dd82a` | Arthur801 | style: 修正 SchemaTests.cs 空白格式（dotnet format） | `tests/DatabaseIntegration/SchemaTests.cs` |
| 2026-10-23 | `289ceb2` | dependabot[bot] | deps: Bump the nuget-minor-patch group with 5 updates | `tests/DatabaseIntegration/DatabaseIntegration.csproj`, `tests/UnitTests/UnitTests.csproj`, `tests/WebIntegration/WebIntegration.csproj` |
| 2026-10-23 | `dccad53` | Arthur801 | chore(deps): pgvector image 固定為 0.8.7-pg17 | `tests/DatabaseIntegration/PostgresFixture.cs`, `tests/WebIntegration/WebFixture.cs` |
| 2026-10-23 | `2a74705` | Arthur801 | feat(hosting): configurable forwarded-header networks and data protection key path (#92) | `tests/UnitTests/HostingSetupTests.cs` |

## #109 M1 書庫後端（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 提交 | Subject | 影響 |
|---|---|---|
| `831fcee` | feat(catalog): add BookBrowse use case and port for 書庫 | 新增 tests/UnitTests/BookBrowseServiceTests.cs（手寫 fake port） |
| `7c369fd` | feat(catalog): implement EF book browse list and random sample | 新增 tests/WebIntegration/BookBrowseIntegrationTests.cs（組裝守衛）；CatalogSeed 的 BookSeed 新增可選 Id |
| `b2c04ce` | test(bestseller): guard retained Bestseller backend through DI | 新增 tests/WebIntegration/BestsellerReaderIntegrationTests.cs（每案獨立 factory）；BestsellerPageTests 保留 |

## 相關依賴歷史與限制

[ci.yml](../../.github/workflows/ci.yml) 在 tests 外；`e3fa9cd` 的 checker-only compat 觸發條件與 `aef8cb0` 的 Python 3.12 host tests 會改變整體 CI 驗證，並未直接改 tests 原始碼。`f233b9d` 為本目錄 fixture 修正，與部署無關。根 solution、主專案、CI 與 deploy 的完整歷史不在上述直接歷史範圍。

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [案例](test-suite.md)

## #109 M2 書庫 Web 呈現（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 分支／提交 | Subject | 影響 |
|---|---|---|
| `a8a5077` | feat(web): show 書庫 on home and /books in place of the bestseller ranking | 新增 tests/UnitTests/BookBrowseViewModelTests.cs；TaipeiTimeZoneTests 改驗 fallback zone 轉換 |
| `2642182` | test(web): cover 書庫 paging, home sample and the /bestsellers redirect | 新增 tests/WebIntegration/BookBrowsePageTests.cs（HTTP 頁面）；刪除 BestsellerPageTests；HtmlPage 移除僅此檔使用的 RenderedRanks |
| 本 M2 docs commit | docs(web): record 書庫 Web presentation in folder docs | 新增 TEST-16 書庫與首頁 HTTP 案例；TEST-15 維持後端守衛 |
| 2026-10-25 | `2a6966b` | feat(catalog): add ISBN normalization protocol and shared fixture | `tests/Fixtures/isbn-normalization.json`（新增）、`tests/UnitTests/IsbnNormalizerTests.cs`（新增）、`tests/UnitTests/UnitTests.csproj`（複製 fixture） |
| 2026-10-25 | `2c662f5` | feat(db): add expand migration 010 for multi-source catalog | `tests/WebIntegration/{CatalogSeed,CatalogSeedTests,BookDetailPageTests,WebFixture}.cs`（SourceCode；reset 保留 source_providers）、`tests/DatabaseIntegration/{EfBookProfileStoreTests,EfCandidateSearchTests,EfEmbeddingStoreTests,StoredEnumTests,PostgresFixture}.cs` |
| 2026-10-25 | `905c6fc` | test(db): cover migration 010 triggers, physical schema and backfill | `tests/DatabaseIntegration/MultiSourceCatalogSchemaTests.cs`、`MultiSourceBackfillTests.cs`（新增）、`constraints.sql`（book_offers、provider 案例） |
| 2026-10-25 | `d9d8948` | feat(catalog): read ISBN, ISBN-13 and ISBN-10 and provider names on detail | `tests/UnitTests/BookDetailViewModelTests.cs`（新增）、`tests/WebIntegration/BookDetailPageTests.cs`（三種類型、去重、disabled provider）、`tests/WebIntegration/SearchPageTests.cs`（ISBN 類型、ABC123） |
| 2026-10-25 | `df57cbf` | test(db): assert last_seen_at-only UPDATE passes the 010 trigger | `tests/DatabaseIntegration/MultiSourceCatalogSchemaTests.cs`（last_seen_at-only UPDATE 案例） |
| 2026-10-25 | `bbe0a0a` | refactor(catalog): share ISBN-family types and display priority | `tests/DatabaseIntegration/MultiSourceCatalogSchemaTests.cs`（新增 `Physical_constraints_match_the_expand_contract`，檢查 NOT NULL、check、RESTRICT／CASCADE FK、identifier 值） |
| 2026-10-25 | `aa792bf` | fix(catalog): pin ISBN NFKC to Unicode 15.1 independent of the runtime | `tests/Fixtures/unicode-15.1/`（DerivedAge.txt、NormalizationTest.txt、NormalizationTest-NFKC.txt、NOTICE.txt）、`tests/Fixtures/isbn-normalization.json`（+2 vector）、`tests/UnitTests/NormalizationConformanceTests.cs`、`Unicode151AssignedTests.cs`（新增）、`IsbnNormalizerTests.cs`（啟動防護）、`UnitTests.csproj` |
| 2026-10-25 | `c3021e3` | fix(catalog): make the detail reader own ISBN identifier order | `tests/DatabaseIntegration/EfBookDetailReaderTests.cs`（新增） |
