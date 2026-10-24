# tests 面向 AI 的文字案例庫

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 2026-10-24；HEAD `91333c3`。已有測試均為「已有測試但本次未執行」。本次只查核來源，沒有通過結果；文字案例不授權執行外部連線、部署或 migration 至正式資料庫。

## 共同準備與隔離

Authority：[test-plan](../../Docs/testing/test-plan.md)、[API](../../Docs/api/api-spec.md)、[data model](../../Docs/data/data-model.md) 與各案例模組文件。用 [CONTEXT](../../CONTEXT.md) 名詞。

- Unit 使用各測試 class 內 fixture／recording stores；[Shared](../Shared) 提供 scripted fakes，未設定 parser 會 echo 原文且無 filters，故測 filters 必須明確 Respond。
- DB 使用 [PostgresFixture](../DatabaseIntegration/PostgresFixture.cs) 新 container 與 MigrateAsync；mapping 案例用 transaction rollback，其他 store 依既有案例清理方式，勿假設統一 truncate。
- Web 使用 [WebFixture](../WebIntegration/WebFixture.cs)：序列 collection、先 ResetDatabaseAsync、seed、本案新 factory/client；factory 必須 dispose。只用 container connection string，不連開發或 production。
- 選用 [CatalogSeed](../WebIntegration/CatalogSeed.cs)、[AccountFlow](../WebIntegration/AccountFlow.cs) 準備 Books 與真實登入／antiforgery flow。測試 signing key 隨機；OpenAI placeholder 不是 secret。
- SimilarityVectors 為 1536 維，Query 配合 WithSimilarity 控制 cosine。時間案例在第一個 request 前設 factory.Time。CallGate.Close 後先 await Entered 再 Advance／Release，避免 real sleep。
- fake Calls 可以斷言未呼叫外部依賴；SDK adapter tests 使用 [OpenAiTestTransport](../UnitTests/OpenAiTestTransport.cs)。不得因測試需要改接 live API。

## 來源存在的執行入口（本次未執行）

在 repository root、符合 global.json SDK 且 dependencies 已備妥後：

```sh
dotnet test tests/UnitTests/UnitTests.csproj
dotnet test tests/DatabaseIntegration/DatabaseIntegration.csproj
dotnet test tests/WebIntegration/WebIntegration.csproj
dotnet test tests/WebIntegration/WebIntegration.csproj --filter FullyQualifiedName~RecommendationApiTests
```

後兩個 integration projects 需 Docker。solution CI 先 restore、Release build，再 `dotnet test Book-Finder.slnx --no-build -c Release --logger trx --results-directory TestResults`。命令會寫產物，故本文件任務未執行。目錄外 `cd crawler && pytest --junitxml=test-results/junit.xml`、`pytest .github/scripts/tests deploy/tests -q` 來源為 [ci.yml](../../.github/workflows/ci.yml)，各有自己的 Python／Docker／browser 前置。

## 案例

### TEST-01：分層選擇與結果範圍

- 責任／規格：runner selection；test-plan §2/6；L1；已有測試入口但本次未執行。
- Given：三個 csproj 與 solution；只需純 unit 時不要求 DB fixture。
- When：執行 UnitTests project；另以 solution 命令執行完整 .NET 範圍。
- Then：前者只執行 unit；後者發現三個 projects；不應將 crawler、deploy、CI script pytest 算成 .NET 結果。
- 位置：[solution](../../Book-Finder.slnx)、三個 csproj；TEST-B01。

### TEST-02：migration、constraint 與 offline model

- 責任／規格：DB schema contract；data-model、test-plan §5；L3；已有測試但本次未執行。
- Given：全新 disposable pgvector；無開發 DB 設定；offline model 使用 Host=unused 且不開連線。
- When：執行 SchemaTests、ModelSnapshotTests、StoredEnumTests；Schema_constraints_hold 讀 output 中 constraints.sql。
- Then：可用 migration 全部套用；UUID/date/UTC/jsonb/array/null 及 1536 vector roundtrip；constraint 違反被攔截，fixture 回復；model 與 snapshot 無 pending change。offline cases 不需啟 DB。
- 位置：[SchemaTests](../DatabaseIntegration/SchemaTests.cs)、[ModelSnapshotTests](../DatabaseIntegration/ModelSnapshotTests.cs)、[StoredEnumTests](../DatabaseIntegration/StoredEnumTests.cs)、[constraints.sql](../DatabaseIntegration/constraints.sql)。

### TEST-03：Web 資料與 cache 隔離

- 責任／規格：test-plan §1/2；L2；已有 fixture、本次未執行，跨案例自動防呆待補強。
- Given：第一個 host 已 seed 與讀取 cache；Dispose 後呼叫 ResetDatabaseAsync。
- When：建立下一個 factory，seed 不同 Catalog，再請求首頁／Book detail。
- Then：看到第二案資料與新 cache；migration history 保留；不依賴上一案 cookie 或 fake Calls。reset 只能操作 fixture container。
- 位置：[WebFixture](../WebIntegration/WebFixture.cs)、[BookBrowsePageTests](../WebIntegration/BookBrowsePageTests.cs)、[BookDetailPageTests](../WebIntegration/BookDetailPageTests.cs)。

### TEST-04：Auth、CSRF 與不洩漏錯誤

- 責任／規格：identity-auth、api-spec；L3；已有測試但本次未執行。
- Given：匿名 client、有效登入 client、缺／錯 antiforgery token；AI fakes Calls 為空。
- When：請求受保護 API、頁面與 POST；以既有 helper 建立有效對照。
- Then：API 匿名 401、頁面按 contract challenge；CSRF 無效 400 ProblemDetails；無 stack trace 或真實 signing key；推薦 API 未通過認證／CSRF gate 時 parser／embedding／ranker Calls 為零。登入 cookie 固定安全屬性；不能由 test-only HTTP status 推定任意 production service／DB／log 均無副作用。
- 位置：[AuthPipelineTests](../WebIntegration/AuthPipelineTests.cs)、[AccountPagesTests](../WebIntegration/AccountPagesTests.cs)、[AuthCookieTests](../UnitTests/AuthCookieTests.cs)、[RecommendationApiTests](../WebIntegration/RecommendationApiTests.cs) 的 `Not_signed_in_returns_401_and_calls_no_external_service` 與 `Signed_in_request_without_antiforgery_header_returns_400_and_calls_no_external_service`（明確斷言三種 AI Calls 為零）。

### TEST-05：搜尋與公開內容邊界

- 責任／規格：book-catalog、BOOK-05、api-spec；L2；已有測試但本次未執行。
- Given：CatalogSeed，含無結果文字、特殊 contributor／date 與有 description／table of contents 的 Book。
- When：GET /search 與 /books/{id}；執行 BookDetailContractTests。
- Then：一般搜尋只查 local；空結果不觸發 AI；頁面顯示 contract 欄位與來源外鏈，description／table of contents 不出現在公開內容；不存在 Book 404。
- 位置：[SearchPageTests](../WebIntegration/SearchPageTests.cs)、[BookDetailPageTests](../WebIntegration/BookDetailPageTests.cs)、[BookDetailContractTests](../UnitTests/BookDetailContractTests.cs)。未實作 Google port 前，未呼叫 Google 的證明仍有限，見 TEST-09。

### TEST-06：Candidate 門檻與排序安全

- 責任／規格：recommendation §2/5/7；L3；已有測試但本次未執行。
- Given：可控 1536 維 vectors，門檻兩側 Books、無 embedding Book、明確 filters；ranker 含候選外 number、重複與超過 10 筆結果。
- When：執行 EfCandidateSearchTests、RankingRulesTests、RecommendationApiTests 對應案例。
- Then：只保留硬條件且 similarity 達門檻者；無 embedding 不入選；排序剔除候選外、輸出最多 10、正確 renumber；空 Candidate 不叫 ranker，可保存空結果。
- 位置：[EfCandidateSearchTests](../DatabaseIntegration/EfCandidateSearchTests.cs)、[RankingRulesTests](../UnitTests/RankingRulesTests.cs)、[RecommendationApiTests](../WebIntegration/RecommendationApiTests.cs)。

### TEST-07：每日 gate、失敗與取消

- 責任／規格：recommendation §11/13；L3；已有測試但本次未執行。
- Given：同使用者今日 20 筆成功紀錄；另一案為 19 筆；FakeTimeProvider 在 Taipei 午夜前；parser/ranker Gate 可阻塞並可拋 adapter exception。
- When：第 21 次 POST /api/recommendations；跨午夜再送；另一案關 Gate、等 Entered、前進 60 秒；另測 request cancellation。
- Then：達上限 429 且所有 AI calls 零次；午夜重置；60 秒 504、adapter unavailable 502、核心階段均不保存／不計額度；保存前 service cancellation 傳遞且無保存。成功保存後的 difficulty 讀取／profile 排程使用 caller token，失敗只記錄、不回滾成功搜尋。不得以 wall-clock sleep 判定。
- 位置：[RecommendationApiTests](../WebIntegration/RecommendationApiTests.cs)、[RecommendationServiceTests](../UnitTests/RecommendationServiceTests.cs)、[CallGate](../Shared/CallGate.cs)。

### TEST-08：Library ownership 與冪等

- 責任／規格：user-library、api-spec；L3；已有測試但本次未執行。
- Given：兩位使用者、一本 Book、owner Library Entry，含 rating。
- When：同 Book 併發 add；另一使用者 update/remove；合法 PATCH 的 null／省略 rating；重複 delete。
- Then：同 user/book 僅一列；他人資料不變；null 清 rating、省略保留；added_at 不變；讀取只含自己的資料；不存在／無權按 contract 回應。
- 位置：[EfLibraryStoreTests](../DatabaseIntegration/EfLibraryStoreTests.cs)、[LibraryApiTests](../WebIntegration/LibraryApiTests.cs)、[LibraryPatchParserTests](../UnitTests/LibraryPatchParserTests.cs)。

### TEST-09：Google Books fallback 保護

- 責任／規格：recommendation §6/15、book-catalog normalization；L3；未實作／測試待建；TEST-B02。
- Given：分別有 4 與 5 local candidates；待建 Google fake 提供 ISBN duplicate、新 Book、不相關 Book 與失敗回應。
- When：完成 fallback port／normalization 後執行同一推薦流程。
- Then：4 才呼叫，5 零次；新資料 normalize 寫 DB、embedding 後重查，duplicate 不增 Book；不相關不入 Candidate；來源失敗 local 繼續；fallback 新 Book 不因排序失敗 rollback。
- 擴充入口：[RecommendationServiceTests](../UnitTests/RecommendationServiceTests.cs)、DatabaseIntegration、RecommendationApiTests；現有 fallbackUsed=false 不是此案例通過證據。

### TEST-10：目錄外 crawler 與 skip

- 責任／規格：test-plan §1/2、crawler；L2；已有測試但本次未執行；TEST-B01/B04。
- Given：crawler requirements、EF tooling、Docker、local Chromium；fixture HTML 與 local server，無真實博客來。
- When：在 crawler 執行 pytest；缺 Chromium 的對照環境讀 skip reason。
- Then：JUnit 分清 executed/failed/skipped；local browser 測試非網站 E2E；缺依賴 skip 不當成實際驗證通過。DB schema 由 EF 產生，不自行演化。
- 位置：[conftest](../../crawler/tests/conftest.py)、[browser tests](../../crawler/tests/test_playwright_fetcher.py)、[CI](../../.github/workflows/ci.yml)。完整 crawler 業務案例由 crawler 文件承擔。

### TEST-11：CI scripts、deploy families、Docker 與結果證據

- 責任／規格：test-plan §6、deployment；L2（正式部署另為 L4）；**Implemented test sources / Not executed in this audit**；TEST-B01/B04。新增 deploy family 的版本證據為 PR #100 merge target `main@ce7b4f46c0889db6b10216294cac658136796ad7`，不假設較早文件分支已含這些檔案。
- Given：disposable CI、placeholder secrets、隔離 state/history/config、fake host ports；Docker 案例另備 internal network；有／無 migration-related PR diff；將 default pytest 與 opt-in integration 分開。
- When：依 [target ci.yml](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/.github/workflows/ci.yml) 執行 `pytest .github/scripts/tests deploy/tests -q`，CI 另在 Python 3.12 跑 `python -m pytest deploy/tests -q`。其中 local integration 與 imagetools pytest wrapper 只有 `BOOKFINDER_IT=1` 才啟用；不得因 default pytest 通過就宣稱它們已執行。Docker job 另直接執行 web smoke、no-keys control 與 `bash deploy/integration/imagetools-roundtrip.sh`；符合 migration-detect 條件才跑 compat。
- Then：逐 family 保存 executed／failed／skipped 狀態與結果；release／operator／host state assertions 不冒充 production 證據；key persistence 正向與 no-keys control 相符；compat JSON 可定位 mandatory checks，未觸發標未執行；TRX/JUnit/artifact 缺檔 warn 不等於完整成功。

| Target test family | 來源與證據邊界 |
|---|---|
| CI checker／release files | [target .github/scripts/tests](https://github.com/Arthur801/Book-Finder/tree/ce7b4f46c0889db6b10216294cac658136796ad7/.github/scripts/tests)、[test_release_files.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/test_release_files.py)；release 檔案的 network／secret／publish 邊界是靜態斷言，不需要真的發布。 |
| Operator CLI／host installation | [test_operator_cli.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_operator_cli.py)、[test_install_host.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_install_host.py)；檢查拒絕條件、state/history/exit、安裝切換與注入 crash point，不是 EC2 已安裝證據。 |
| Compose probe | [test_compose_probe.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_compose_probe.py)；替身模擬 raw env_file capability、錯誤與 cleanup，不代表現場 Compose 已驗證。 |
| State／history／machine coordination | [test_state.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_state.py)、[test_history.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_history.py)、[test_machine.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_machine.py)；fakes／tmp 狀態與轉移斷言，區分實際 Docker integration。 |
| Crawler maintenance coordination | [target crawler/test_deploy.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/tests/test_deploy.py)、[test_run_crawler_contract.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_run_crawler_contract.py)；absent／paused／dirty／malformed state、shared-lock 先後與存續、timeout exits，詳見 [CR-T12](../../crawler/docs/test-suite.md)。 |
| Local Docker integration／release digest | [test_local_integration.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/integration/test_local_integration.py)、[test_imagetools_roundtrip.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/integration/test_imagetools_roundtrip.py)；`integration` marker 與 `BOOKFINDER_IT=1` gate，需 Docker 與可用 local ports；pytest default 會 skip。Imagetools 同一腳本亦由 CI Docker job 直接執行，兩條入口結果分開。 |

上述 target 檔案由 Git object 查核；本次未執行任何 pytest／Docker／host 操作。較早的 [ci.yml](../../.github/workflows/ci.yml)、[deploy/tests](../../deploy/tests)、[compat.sh](../../deploy/migration-test/compat.sh) 相對連結保留作 repository 導覽，target 新增行為以固定 SHA 來源為準。

### TEST-12：網站瀏覽器與靜態資產

- 責任／規格：test-plan E2E 暫緩；L2；明確暫緩，待核准解除；TEST-B03。
- Given：若日後核准，local browser、mock external、disposable DB、實際 static assets。
- When：瀏覽 Book／Library，執行登入 pending action、rating／status 互動。
- Then：asset 200、JavaScript 可操作、CSRF 與 ownership 保留；不可用現有 NullFileProvider HTML tests 宣稱涵蓋。
- 擴充入口：待建網站 browser suite；crawler Playwright 不可當替代。

### TEST-13：背景 embedding 與 profile 的可控執行

- 責任／規格：recommendation §9/10；L3；已有測試但本次未執行。
- Given：embedding timer 在 Web fixture 關閉，scripted generators，無 embedding 或 metadata hash 已變更的 Book；profile enabled／disabled 對照。
- When：直接呼叫 EmbeddingBackfillService.RunOnceAsync；執行 BookProfileSchedulerTests／BookProfileWorkerTests 對應案例，再讀推薦與 history。
- Then：只處理待補齊或過期資料；不呼叫真實 AI；首次 difficulty 快照為 null，後續 profile 完成才可讀；disabled 不排入 queue；生成 profile 不改 Book description／table of contents。錯誤與取消不應使測試背景 timer 失控。
- 位置：[EmbeddingBackfillTests](../WebIntegration/EmbeddingBackfillTests.cs)、[BookProfileSchedulerTests](../UnitTests/BookProfileSchedulerTests.cs)、[BookProfileWorkerTests](../UnitTests/BookProfileWorkerTests.cs)、[RecommendationApiTests](../WebIntegration/RecommendationApiTests.cs)。

### TEST-14：hosting 信任邊界

- 責任／規格：deployment、identity-auth；L3；已有測試但本次未執行。
- Given：可信 CIDR、loopback、非可信 remote address；有效／無效 DataProtection key path 設定。
- When：執行 HostingSetupTests 的真實 ForwardedHeadersMiddleware harness，及 ForwardedHeadersTests 的 HTTP host requests。
- Then：只有可信來源可影響 Scheme／client IP；非可信來源不能偽造 HTTPS；key path 設定按既有斷言解析。這不是 public nginx／Cloudflare 或跨 container key persistence 的驗證；後者見 TEST-11。
- 位置：[HostingSetupTests](../UnitTests/HostingSetupTests.cs)、[ForwardedHeadersTests](../WebIntegration/ForwardedHeadersTests.cs)。

### TEST-15：書庫列表與 Bestseller 後端的組裝守衛

- 責任／規格：Catalog browse 與 Bestseller backend 的 DI 鏈；L3；**已建立測試（#109 M1），執行結果見 #109 實作報告**。
- Given：WebFixture 的 disposable DB 與 CatalogSeed；固定 Id 的書、無日期與新舊日期、25 本、空庫、15 本與 3 本、打亂 rank 的榜單、缺號榜單與空表。
- When：每案建立獨立 factory，從 `app.Services.CreateScope()` 解析 BookBrowseService 或 BestsellerService 直接呼叫，不經 HTTP；Bestseller 每案另建 factory，避免 host cache 跨案。
- Then：書庫同日依 Id、有日期新到舊且無日期在後、分頁無重複、超頁不溢位、空庫 0 頁、樣本數與作者規則正確；Bestseller 依 rank 排序、只取 AUTHOR 並依 contributor_order、CapturedAt 等於 seed、缺號不重編且 GetTopAsync(10) 可含 rank 11、空表 CapturedAt 為 null。
- 位置：[BookBrowseIntegrationTests](../WebIntegration/BookBrowseIntegrationTests.cs)、[BestsellerReaderIntegrationTests](../WebIntegration/BestsellerReaderIntegrationTests.cs)、[CatalogSeed](../WebIntegration/CatalogSeed.cs)（`BookSeed.Id` 可選固定 Id）。
- 單元層：[BookBrowseServiceTests](../UnitTests/BookBrowseServiceTests.cs) 以手寫 fake port 驗證頁碼下限、固定 pageSize 20 與首頁樣本 10 筆。

### TEST-16：書庫與首頁的 HTTP 頁面

- 責任／規格：book-catalog §3、ui-flow；L2；**已建立測試（#109 M2），執行結果見 #109 實作報告**。
- Given：WebFixture 的 disposable DB 與 CatalogSeed；固定 Id 的書、有日期與無日期的書、25 本、空庫、15 本，以及帶 description／table of contents 哨兵文字的書。
- When：以 HttpClient 請求 `/books`（含 page 參數）、`/`、`/bestsellers`；需檢查 302 與 301 時使用 `AllowAutoRedirect=false` 的 client。
- Then：書庫同日依 Id、有日期新到舊、無日期在後；每頁 20 本、摘要與分頁正確、兩頁無重複；非正數頁為第 1 頁；超頁 302 至最後一頁；空庫顯示「書庫還沒有書」且無摘要、無分頁、page=5 為 200；列表 HTML 不含簡介與目錄；首頁最多 10 本、不重複、不顯示 rank；導覽有書庫、沒有 `/bestsellers` 連結；`/bestsellers` 301 至 `/books`。
- 位置：[BookBrowsePageTests](../WebIntegration/BookBrowsePageTests.cs)、[LayoutAndHomeTests](../WebIntegration/LayoutAndHomeTests.cs)、[HtmlPage](../WebIntegration/HtmlPage.cs)；單元層 [BookBrowseViewModelTests](../UnitTests/BookBrowseViewModelTests.cs)。

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md)

### TEST-17：Migration 010 的實體 schema、trigger 與 ISBN 正規化 fixture

- **Given**：拋棄式 pgvector container，已 migrate 到 head；ISBN 正規化使用 [tests/Fixtures/isbn-normalization.json](../Fixtures/isbn-normalization.json)。
- **When**：查 catalog；以 v0.0.4 形式與 `source_code`-only 形式寫入；寫入不一致值或 KINGSTONE；用 legacy ISBN_13 與 `ISBN` 寫入同值；回填測試從 `20261010204858_Embedding` 遷移。
- **Then**：TEST-02 的 constraint 不回歸；§7 #9、#10 通過；實體 PK 與 UNIQUE 符合 data-model §11.4；NOT NULL、legacy check、RESTRICT／CASCADE FK 與 identifier check 值符合 010；`IsbnNormalizerTests` 的 73 個 vector 全部相符。
- **來源與狀態**：[MultiSourceCatalogSchemaTests](../DatabaseIntegration/MultiSourceCatalogSchemaTests.cs)、[MultiSourceBackfillTests](../DatabaseIntegration/MultiSourceBackfillTests.cs)、[constraints.sql](../DatabaseIntegration/constraints.sql)、[IsbnNormalizerTests](../UnitTests/IsbnNormalizerTests.cs)。本次 `dotnet test` DatabaseIntegration 120 項、UnitTests 806 項通過。

### TEST-18：Detail 的 ISBN 三種類型、同值去重與 disabled provider

- **Given**：一本書的 `ISBN`、`ISBN_13`、`ISBN_10` identifier（含同值），以及 Google Books 來源；測試結束時 `source_providers` 的 `enabled` 還原。
- **When**：Detail 頁與 ISBN、關鍵字搜尋；把 GOOGLE_BOOKS 設為 `enabled=false` 後再開 Detail。
- **Then**：同值只顯示 `ISBN`；不同值全部顯示；`ABC123` 走關鍵字而不命中 ISBN 類型；disabled provider 既有的來源仍顯示，連結文字為 provider 顯示名稱。
- **來源與狀態**：[BookDetailViewModelTests](../UnitTests/BookDetailViewModelTests.cs)（單元）、[BookDetailPageTests](../WebIntegration/BookDetailPageTests.cs)、[SearchPageTests](../WebIntegration/SearchPageTests.cs)（WebIntegration）。本次 `dotnet test` 通過。

### TEST-19：NFKC 與 Unicode 15.1 一致性、detail 的 ISBN 順序

- **Given**：vendored NormalizationTest 15.1 的 c1→c4 對；fixture 的未指派 OUTLINED DIGIT 與分段 vector；一本含三種 ISBN 類型與 OTHER 的書。
- **When**：`NormalizationConformanceTests` 與 `IsbnNormalizerTests`；`EfBookDetailReaderTests` 讀 Detail。
- **Then**：NFKC 與 15.1 一致；未指派 code point 不被正規化；reader 依 ISBN、ISBN_13、ISBN_10 排序，OTHER 不出現。
- **來源與狀態**：[NormalizationConformanceTests](../UnitTests/NormalizationConformanceTests.cs)、[Unicode151AssignedTests](../UnitTests/Unicode151AssignedTests.cs)、[EfBookDetailReaderTests](../DatabaseIntegration/EfBookDetailReaderTests.cs)。本次 `dotnet test` UnitTests 826、DatabaseIntegration 123 通過。
