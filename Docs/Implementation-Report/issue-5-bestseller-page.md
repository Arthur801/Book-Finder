# Issue #5 實作報告：暢銷榜頁與 Web 測試骨架

- Issue：#5
- Branch：issue-5-bestseller-page
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11
- 修訂：第一輪實作（commit `976d9fe`）；第二輪為 code review 後的修正（見「Code Review 與修正」）

## 變更檔案

「第二輪」欄標示第二輪修正時新增、修改或刪除的檔案；未標示者為第一輪產出且第二輪未變動。

| 檔案 | 類型（新增/修改/刪除） | 說明 | 第二輪 |
|---|---|---|---|
| `Application/Bestsellers/BestsellerSnapshot.cs` | 新增 | `BestsellerSnapshot`（`CapturedAt` + `Entries`）與 `BestsellerEntry`（rank、book id、title、authors、thumbnail）record | |
| `Application/Bestsellers/IBestsellerReader.cs` | 新增 | Application 層資料存取介面，回傳整份目前榜單 | |
| `Application/Bestsellers/BestsellerService.cs` | 新增 → 修改 | 讀取 use case：`GetTopAsync(count)`（前 N 筆）、`GetAllAsync()`。第一輪直接依賴 `IMemoryCache`；第二輪移除快取依賴，快取移至 Infrastructure | 修改 |
| `Infrastructure/Caching/CachedBestsellerReader.cs` | 新增 | `IBestsellerReader` 的 decorator，以 `IMemoryCache` 快取整份榜單（非空 1 小時、空 5 分鐘） | 新增 |
| `Infrastructure/Persistence/EfBestsellerReader.cs` | 新增 | `IBestsellerReader` 的 EF Core 實作；兩次查詢（榜單 join books、再一次查所有 AUTHOR 角色貢獻者），無 N+1 | |
| `Models/BestsellerListViewModel.cs` | 新增 → 修改 | Presentation 用 view model；作者串接（`、`）與 `captured_at` 格式化。第二輪移除 `Lazy<TimeZoneInfo>`，改接受 `TimeZoneInfo` 參數 | 修改 |
| `Models/TaipeiTimeZone.cs` | 新增 | Asia/Taipei 解析：找得到系統時區就使用，找不到（`TimeZoneNotFoundException`／`InvalidTimeZoneException`）退回固定 UTC+08:00 | 新增 |
| `Controllers/BestsellersController.cs` | 新增 → 修改 | `/bestsellers`，回傳完整榜單。第二輪移除 Controller 內的標題設定 | 修改 |
| `Controllers/HomeController.cs` | 修改 | `Index` 改為取前 10 名；移除 `Privacy` action；第二輪移除 Controller 內的標題設定 | 修改 |
| `Views/Bestsellers/Index.cshtml` | 新增 → 修改 | 暢銷榜頁，使用共用 partial；第二輪由 View 設定 `ViewData["Title"]` | 修改 |
| `Views/Home/Index.cshtml` | 修改 | 一般搜尋表單（GET `/search?q=`）、AI 推薦表單（GET `/ai`）、暢銷榜前 10 名、「查看完整榜單」連結；第二輪由 View 設定標題 | 修改 |
| `Views/Shared/_BestsellerEntries.cshtml` | 新增 | 榜單列表 partial（排名、封面、書名連結 `/books/{id}`、作者、更新時間、空狀態「榜單尚未建立」），首頁與暢銷榜頁共用 | |
| `Views/Home/Privacy.cshtml` | 刪除 | 範本樣板頁（見「自行決定」第 8 點） | |
| `Views/Shared/_Layout.cshtml` | 修改 | 導覽列：logo（好想找書）→ `/`、暢銷榜、AI 推薦、個人書單，右側登入／註冊；移除 Privacy 連結與 footer 的 Privacy 連結；`lang="zh-Hant"` | |
| `Program.cs` | 修改 | 註冊 `AddMemoryCache`、`EfBestsellerReader`、`IBestsellerReader`（decorator 包住 EF reader）、`BestsellerService`；檔尾 `public partial class Program { }` 供測試使用 | 修改 |
| `Book-Finder.slnx` | 修改 | 加入 `tests/UnitTests/UnitTests.csproj` 與 `tests/WebIntegration/WebIntegration.csproj` | 修改 |
| `tests/UnitTests/UnitTests.csproj` | 新增 | xUnit 單元測試專案；引用主專案，套件版本與其他測試專案相同 | 新增 |
| `tests/UnitTests/CachedBestsellerReaderTests.cs` | 新增 | 快取 decorator 的 TTL（1 小時／5 分鐘）與「快取命中時不重讀 inner reader」；fake inner reader + 記錄 TTL 的 `IMemoryCache` 包裝 | 新增（由 WebIntegration 移入） |
| `tests/UnitTests/BestsellerServiceTests.cs` | 新增 | `GetTopAsync` 取前 N 筆並保留 `captured_at`；`GetAllAsync` 回傳全部 | 新增 |
| `tests/UnitTests/TaipeiTimeZoneTests.cs` | 新增 | 時區解析：系統時區可用、`TimeZoneNotFoundException`／`InvalidTimeZoneException` 的 fallback、fallback 下的格式化結果 | 新增 |
| `tests/WebIntegration/WebIntegration.csproj` | 新增 | xUnit 測試專案；引用 `Microsoft.AspNetCore.Mvc.Testing` 10.0.12、`Testcontainers.PostgreSql` 4.16.0 | |
| `tests/WebIntegration/WebFixture.cs` | 新增 | `WebFixture`（一個 `pgvector/pgvector:pg17` 容器、啟動時套用全部 migration、`CreateFactory()`、`ResetCatalogAsync()`）、`BookFinderFactory : WebApplicationFactory<Program>`（以 `UseSetting` 注入容器連線字串）、`WebCollection` collection fixture | |
| `tests/WebIntegration/BestsellerSeed.cs` | 新增 → 修改 | 透過 `AppDbContext` 直接寫入 Book、Book Source（博客來 URL）、Contributor（含明確 `contributor_order`）、Bestseller 的 seed helper | 修改 |
| `tests/WebIntegration/HtmlPage.cs` | 新增 | 頁面輔助：`GetPageAsync`（斷言 200、HTML decode）與 `RenderedRanks`（解析 `data-rank` 順序） | 新增（取代 `HttpAssertions.cs`） |
| `tests/WebIntegration/HttpAssertions.cs` | 刪除 | 由 `HtmlPage.cs` 取代（名稱不符實際內容） | 刪除 |
| `tests/WebIntegration/BestsellerPageTests.cs` | 新增 → 修改 | 首頁前 10、rank 11 納入、100 筆完整榜單、缺號不重編、作者／封面／書名（反向插入順序）、`/books/{id}` 連結、Asia/Taipei 更新時間、空狀態 200、HTTP 層快取 | 修改 |
| `tests/WebIntegration/LayoutAndHomeTests.cs` | 新增 → 修改 | 導覽列連結、Privacy 頁 404 與版面無連結、首頁搜尋／AI 表單與「查看完整榜單」連結 | 修改 |
| `tests/WebIntegration/BestsellerCacheTests.cs` | 新增 → 刪除 | 第一輪放在 Web 層；第二輪移至 `tests/UnitTests/CachedBestsellerReaderTests.cs` 與 `BestsellerServiceTests.cs` | 刪除 |
| `Docs/testing/test-plan.md` | 修改 | Web 列位置改為 `tests/WebIntegration`；Unit 列位置改為 `tests/UnitTests` | 修改 |
| `Docs/deployment/deployment.md` | 修改 | §3 Containers 新增：`web` image 必須含 tzdata（與 ICU，除非 invariant globalization），找不到 Asia/Taipei 時的 UTC+08:00 fallback | 修改 |
| `Docs/architecture/system-architecture.md` | 修改 | §4.2 新增唯讀顯示查詢的例外：可直接讀取 Book Catalog 擁有的 `books` 及其子表，寫入一律經由擁有模組 | 修改 |
| `AGENTS.md` | 修改 | §1.1 檔案樹加入 `Implementation-Report/`（實作紀錄，非規格，不得作為 authority 引用） | 修改 |
| `Docs/Implementation-Report/issue-5-bestseller-page.md` | 新增 → 修改 | 本報告 | 修改 |

## 實作思路

### 分層

- **Presentation**（`HomeController`、`BestsellersController`、Razor）只呼叫 `BestsellerService`，不碰 `DbContext`、不寫 SQL。
- **Application**（`Application/Bestsellers/`）：`BestsellerService` 保有 use case 規則（前 N 筆、`HomeTopCount = 10`）；`IBestsellerReader` 是資料存取的 port。Application 不依賴 `IMemoryCache`、EF Core 或 ASP.NET 快取。
- **Infrastructure**：`EfBestsellerReader` 實作 `IBestsellerReader`，依 `rank` 排序，對應 `Docs/modules/bestseller.md` §2 的 `SELECT rank, book, captured_at FROM bestsellers JOIN books ORDER BY rank`。`CachedBestsellerReader` 是包住它的 decorator，負責快取。
- **Domain**：沒有變更，直接使用既有 `Bestseller`、`Book`、`BookContributor`、`ContributorRole`。

DI 組合（`Program.cs`）：`AddMemoryCache`；`EfBestsellerReader` 為 scoped；`IBestsellerReader` 為 scoped，實際回傳 `CachedBestsellerReader(EfBestsellerReader, IMemoryCache)`；`BestsellerService` 為 scoped。

### 介面切點

- `IBestsellerReader.ReadCurrentAsync` 回傳整份榜單（最多 100 筆）與 `CapturedAt`。空榜單回傳 `CapturedAt = null` 與空清單。
- Application 的 record（`BestsellerSnapshot`、`BestsellerEntry`）不依賴 EF 或 ASP.NET；作者清單已在 Infrastructure 組好。
- Presentation view model（`BestsellerListViewModel`）負責格式化（作者串接、時區），Razor 只做輸出。

### 快取策略（ADR-005）

- 快取位於 Infrastructure 的 `CachedBestsellerReader`，快取鍵 `bestsellers:current`，值為整份 `BestsellerSnapshot`。首頁與 `/bestsellers` 讀同一份快取。
- 非空榜單：`AbsoluteExpirationRelativeToNow = 1 小時`；空榜單：`5 分鐘`。TTL 為 `CachedBestsellerReader` 的 `static readonly TimeSpan` 常數，在 `GetOrCreateAsync` 工廠中依結果設定。
- `BestsellerService.GetTopAsync` 在整份清單上取前 N 筆（`Take`），不另外查詢，因此首頁與完整榜單保持一致。
- 快取只存可由 PostgreSQL 重建的資料（ADR-005），不作為 source of truth。

### 時區

- `TaipeiTimeZone.Resolve(findById)` 以注入的查找函式取得 `Asia/Taipei`；找不到時退回固定 UTC+08:00（台灣無夏令時間，顯示結果相同）。結果在靜態欄位中一次計算，不快取例外。
- 格式化使用 `BestsellerListViewModel.FormatUpdatedAt(capturedAt, zone)`；公開的單參數版本使用 `TaipeiTimeZone.Taipei`。

### 排名與前 10 名

- 顯示 `rank` 原值，不重新編號；缺號時 36 之後直接接 38。
- 首頁的「前 10 名」是 rank 排序後的前 10 筆，因此缺號時可能包含 rank 11（見規格 §3）。

### 測試骨架設計

- **共用 fixture**：`WebFixture` 是 collection fixture，整次測試只啟動一個 `pgvector/pgvector:pg17` 容器並套用全部 migration（沿用 `tests/DatabaseIntegration/PostgresFixture.cs` 的模式）。
- **連線字串注入**：`BookFinderFactory` 使用 `WebApplicationFactory<Program>.ConfigureWebHost` 內的 `builder.UseSetting("ConnectionStrings:DefaultConnection", ...)`。已驗證 minimal hosting 會讀到這個設定，`Program.cs` 的 `InvalidOperationException` 不會觸發。
- **快取隔離**：快取存在 app instance 中，因此**每個 Web 測試建立新的 factory**（新的 host、新的 cache）。
- **資料隔離**：`ResetCatalogAsync()` 先刪 `bestsellers`（RESTRICT FK），再刪 `books`（CASCADE 到 book_sources、book_contributors）。同一個 collection 的測試依序執行。
- **只透過 HTTP 驗證**：Web 測試一律以 `HttpClient` 取頁面，斷言狀態碼與 HTML 內容；不直接呼叫 Controller。資料以 `AppDbContext` 直接 seed。
- **單元測試**：`tests/UnitTests` 不需要 Docker，包含快取 decorator（以 fake inner reader 驗證 TTL 數值與命中行為）、service 的前 N 筆規則與時區解析的 fallback。

## 執行紀錄（Log）

### 第一輪

1. `gh issue view 5`：失敗，錯誤訊息為 GraphQL 的 Projects (classic) 棄用警告。改用 `gh api repos/Arthur801/Book-Finder/issues/5 --jq '.title, .body'` 取得 issue 內容，成功。
2. `git status` / `git branch --show-current`：確認位於 `issue-5-bestseller-page`，工作樹乾淨。
3. 閱讀規格：`AGENTS.md`、`CONTEXT.md`、`Docs/modules/bestseller.md`、`Docs/ui/ui-flow.md`、`Docs/architecture/system-architecture.md` §4、`Docs/architecture/architecture-decisions.md` ADR-005、`Docs/testing/test-plan.md`、`Docs/data/data-model.md` §5.8；閱讀既有程式與 `tests/DatabaseIntegration`。
4. 基線：`dotnet tool restore && dotnet build` 通過，0 warnings / 0 errors（.NET SDK 10.0.112，runtime 10.0.12）。
5. 寫入 Application、Infrastructure、Presentation 與測試專案檔案；`git rm Views/Home/Privacy.cshtml`。
6. 更新 `Book-Finder.slnx` 加入 WebIntegration（使用 bash heredoc 寫入）。
7. `dotnet build`：0 errors、0 warnings。
8. 第一次 `dotnet test tests/WebIntegration/WebIntegration.csproj`：16 通過、2 失敗。失敗原因相同：Razor 將 CJK 字元輸出為數字實體（例如 `&#x66F4;&#x65B0;`），測試用 `Contains("2026-10-11 04:03 更新")` 與 `Contains(">三體</a>")` 找不到字串。確認為測試端問題（瀏覽器可正確顯示），應用程式不變。解法：`HttpAssertions.GetOkAsync` 回傳 `WebUtility.HtmlDecode` 後的內容。
9. 為除錯暫時建立 `tests/WebIntegration/DebugDumpTests.cs` 與 `/tmp/dump-bestsellers.html`，確認上述原因後已刪除（`rm -f`），`git status` 確認無殘留。
10. 修正後重跑 WebIntegration：18 通過。
11. `dotnet build`（整個 solution）：0 errors、0 warnings。
12. `dotnet ef migrations has-pending-model-changes`：`No changes have been made to the model since the last migration.`（未改 schema）。
13. `dotnet test`（整個 solution）：DatabaseIntegration 12 通過、WebIntegration 18 通過。
14. 更新 `Docs/testing/test-plan.md` 的 Web 列位置。
15. 撰寫本報告，commit（`976d9fe`）。

### 第二輪（code review 修正）

16. 讀取 `Docs/deployment/deployment.md` §3、`Docs/architecture/system-architecture.md` §4.2、`AGENTS.md` §1.1、`Docs/testing/test-plan.md` 的相關行。
17. 建立 `Models/TaipeiTimeZone.cs`；`BestsellerListViewModel` 移除 `Lazy<TimeZoneInfo>`，改為 `FormatUpdatedAt(capturedAt, zone)`。
18. `BestsellerService` 移除 `IMemoryCache`、`CacheKey` 與 TTL 常數；新增 `Infrastructure/Caching/CachedBestsellerReader.cs` 承接快取；`Program.cs` 改為以 decorator 包住 `EfBestsellerReader`。
19. Controller 移除 `ViewData["Title"]`，改由 Razor View 設定（`Views/Home/Index.cshtml`、`Views/Bestsellers/Index.cshtml`）。
20. 測試端：`HttpAssertions` 改名為 `HtmlPage`（`GetOkAsync` → `GetPageAsync`）；`BestsellerSeed` 的 contributor 改為明確 `ContributorSeed(order, name, role)`；Entries 測試改為反向插入；兩個 HTTP 快取測試改名；Privacy 測試改為精確斷言。
21. 建立 `tests/UnitTests`（csproj、`CachedBestsellerReaderTests`、`BestsellerServiceTests`、`TaipeiTimeZoneTests`），將 TTL 測試由 `WebIntegration/BestsellerCacheTests.cs` 移入（該檔刪除），並加入 `Book-Finder.slnx`。
22. 第一次 `dotnet build` 與 `dotnet test`（全 solution）：0 errors、0 warnings；UnitTests 9 通過、DatabaseIntegration 12 通過、WebIntegration 14 通過。
23. 突變測試（mutation check）：暫時從 `EfBestsellerReader` 移除 contributor 的 AUTHOR 角色過濾，`Entries_show_...` 失敗（`Assert.Contains() Failure`），符合預期。
24. 突變測試：暫時移除 contributor 的 `OrderBy(ContributorOrder)`，`Entries_show_...` 仍通過。原因：`book_contributors` 的主鍵為 `(book_id, contributor_order)`，查詢以 `book_id IN (...)` 走主鍵索引，結果本來就依 `contributor_order` 排列，因此此突變無法由測試觀察到。`ORDER BY` 仍保留在程式中作為明確契約。兩次突變後以 `git checkout -- <該檔>` 還原，`git diff HEAD` 確認檔案與 HEAD 相同。
25. `dotnet ef migrations has-pending-model-changes`：`No changes have been made to the model since the last migration.`
26. 最終 `dotnet build`（0 errors、0 warnings）與 `dotnet test`（全 solution，見下方 summary）。
27. 更新本報告並 commit（新 commit，不 amend）。

## 驗證結果

### Issue #5 Acceptance criteria

| 條目 | 結果 | 對應測試 |
|---|---|---|
| 測試 seed 榜單後，首頁回傳 rank 最小的 10 本，`/bestsellers` 回傳全部 | ✅ | `BestsellerPageTests.Home_shows_the_first_ten_rows_by_rank`；`BestsellerPageTests.Bestsellers_page_lists_all_100_entries_in_rank_order_without_pagination` |
| 第 37 名缺號時，畫面上 36 之後接 38 | ✅ | `BestsellerPageTests.Skipped_rank_is_not_renumbered_on_either_page` |
| 顯示 `captured_at`（Asia/Taipei）作為更新時間 | ✅ | `BestsellerPageTests.Updated_at_is_shown_in_taipei_time_on_both_pages`；格式化 fallback 路徑：`TaipeiTimeZoneTests.Captured_at_is_shown_in_taipei_time_with_the_fallback_zone` |
| 空榜單時顯示「榜單尚未建立」且狀態碼為 200 | ✅ | `BestsellerPageTests.Empty_bestsellers_show_placeholder_with_status_200_on_both_pages` |
| 每本書可連到 `/books/{id}` | ✅ | `BestsellerPageTests.Each_entry_links_to_its_book_detail_page_on_both_pages` |
| 導覽列包含暢銷榜、AI 推薦、個人書單，以及登入／註冊入口 | ✅ | `LayoutAndHomeTests.Shared_navbar_links_to_sections_and_auth_entry_points`（`/` 與 `/bestsellers` 兩個 case） |
| Web 層測試透過 HTTP 驗證以上行為，不直接呼叫 Controller | ✅ | `tests/WebIntegration` 所有測試只使用 `HttpClient`；`tests/UnitTests` 為 Application／Infrastructure 單元測試，不經 Controller |
| `dotnet build`、`dotnet test` 通過 | ✅ | 見下方 summary |

### 其他規格對照

| 規格 | 結果 | 對應測試 |
|---|---|---|
| 首頁 rank 排序後前 10 筆，可能包含 rank 11 | ✅ | `BestsellerPageTests.Home_top_ten_can_include_rank_11_when_a_rank_is_skipped` |
| 作者只取 AUTHOR 角色，依 `contributor_order` 排序（以反向插入的資料驗證） | ✅ | `BestsellerPageTests.Entries_show_cover_title_and_only_author_contributors_in_contributor_order`。突變驗證：移除角色過濾會失敗；移除 `ORDER BY` 不會失敗（見「Code Review 與修正」） |
| 封面、書名顯示 | ✅ | 同上 |
| 空榜單首頁與 `/bestsellers` 皆 200 | ✅ | `BestsellerPageTests.Empty_bestsellers_show_placeholder_with_status_200_on_both_pages` |
| 空榜單在快取期間不被新資料取代（HTTP 層） | ✅ | `BestsellerPageTests.Empty_snapshot_is_served_from_cache` |
| 非空榜單在快取期間，即使資料列被移除仍被服務（HTTP 層） | ✅ | `BestsellerPageTests.Non_empty_snapshot_is_served_from_cache` |
| 非空榜單 TTL 1 小時、空榜單 TTL 5 分鐘（數值） | ✅ | `CachedBestsellerReaderTests.Non_empty_snapshot_is_cached_for_one_hour`；`CachedBestsellerReaderTests.Empty_snapshot_is_cached_for_five_minutes` |
| 快取命中時不重讀 inner reader | ✅ | `CachedBestsellerReaderTests.Inner_reader_is_called_once_while_the_snapshot_is_cached` |
| `GetTopAsync` 取前 N 筆並保留 `captured_at`；`GetAllAsync` 回傳全部 | ✅ | `BestsellerServiceTests.Top_returns_the_first_rows_by_rank_with_the_capture_time`；`BestsellerServiceTests.All_returns_every_row_in_the_snapshot` |
| 時區解析：找不到時退回固定 UTC+08:00，不拋例外 | ✅ | `TaipeiTimeZoneTests.Resolve_falls_back_to_fixed_utc_plus_8_when_the_zone_is_missing`；`TaipeiTimeZoneTests.Resolve_falls_back_to_fixed_utc_plus_8_when_the_zone_is_invalid`；`TaipeiTimeZoneTests.Resolve_uses_the_system_zone_when_it_is_available` |
| 首頁提供一般搜尋表單與 AI 推薦表單，並有「查看完整榜單」連結（表單本身；AI 導向與預填屬 #13／#10，見下） | ⏸ | `LayoutAndHomeTests.Home_shows_search_and_ai_entry_forms_and_link_to_full_ranking` |
| Privacy 範本頁已移除，版面無連結 | ✅ | `LayoutAndHomeTests.Privacy_boilerplate_page_is_removed` |

**⏸ 說明**：ui-flow §3.2 第 2 點要求 AI 推薦框在「已登入」時導向 `/ai` 並預填需求文字，「未登入」時導向登入並帶 `returnUrl=/ai`。本票只完成表單本身（GET `/ai`，欄位 `q`），導向與預填行為需要 `/ai` 頁面（#13）與認證（#10），因此標示為未完成。同理，ui-flow §3.1 的已登入狀態列（display_name、登出）也留待 #10。

### dotnet test 結果摘要

```text
Passed!  - Failed:     0, Passed:     9, Skipped:     0, Total:     9, Duration: 31 ms - UnitTests.dll (net10.0)
Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - DatabaseIntegration.dll (net10.0)
Passed!  - Failed:     0, Passed:    14, Skipped:     0, Total:    14, Duration: 1 s - WebIntegration.dll (net10.0)
```

另有：`dotnet build`（整個 solution）為 `0 Error(s)`、`0 Warning(s)`；`dotnet ef migrations has-pending-model-changes` 為 `No changes have been made to the model since the last migration.`

## Code Review 與修正

第二輪依 Standards 與 Spec 兩個面向審查 commit `976d9fe`，審查結果與處理如下。

### Standards

| 審查發現 | 處理 |
|---|---|
| Application 層依賴 `IMemoryCache`（快取策略混在 use case） | ✅ 已修正：快取移至 Infrastructure 的 `CachedBestsellerReader`（decorator）；`BestsellerService` 不再依賴 `IMemoryCache` |
| 跨模組資料表讀取的規格歧義：`system-architecture.md` §4.2 禁止直接讀寫其他模組的表，但 `bestseller.md` §2 要求 `bestsellers JOIN books` | ✅ 已修正：在 `system-architecture.md` §4.2 加入唯讀顯示查詢的例外（可讀 Book Catalog 的 `books` 與子表；寫入一律經擁有模組） |
| `Implementation-Report` 未登錄於 `AGENTS.md` 檔案樹 | ✅ 已修正：`AGENTS.md` §1.1 加入 `Implementation-Report/`（實作紀錄，非規格，不得作為 authority 引用）；其餘內容未動 |
| 測試基礎設施重複（`WebFixture` 與 `DatabaseIntegration/PostgresFixture` 皆自行建立 Testcontainers 與 migration） | ⏸ 未修正：兩者各約 20 行，且 `DatabaseIntegration` 為既有專案。抽出共用 test-infrastructure 專案會改動既有測試，超出本票範圍，留作後續重構 |
| 頁面標題重複設定（Controller 與 View 各設一次） | ✅ 已修正：標題只在 View 設定（`ViewData["Title"]`），Controller 不再設定 |
| `HttpAssertions` 名稱與實際內容（HTML 解析與 HTTP 輔助）不符 | ✅ 已修正：改名為 `HtmlPage`，`GetOkAsync` 改名為 `GetPageAsync` |
| `CacheKey` 常數在 service 中未使用 | ✅ 已修正：移除 service 中的常數；快取鍵改為 decorator 內的私有常數（實際使用處） |
| 純單元測試放在 Web 整合測試專案 | ✅ 已修正：新增 `tests/UnitTests`，快取、service 與時區測試移入；`Docs/testing/test-plan.md` §2 的 Unit 列位置同步更新 |
| 時區 `Lazy<TimeZoneInfo>` 會永久快取 `TimeZoneNotFoundException`，tzdata 缺失時首頁與暢銷榜永久 500 | ✅ 已修正：移除 `Lazy`；`TaipeiTimeZone.Resolve` 在例外時退回固定 UTC+08:00，結果於靜態欄位一次計算；`deployment.md` §3 加入 tzdata／ICU 需求與 fallback 說明；`TaipeiTimeZoneTests` 覆蓋 fallback 路徑 |
| Privacy 測試以 `DoesNotContain("Privacy", html)` 斷言，過於脆弱（任何含該字串的文字都會失敗） | ✅ 已修正：改為斷言 `GET /Home/Privacy` 為 404，且版面 HTML 中沒有指向 privacy 的 `href`（`(?i)href="[^"]*privacy`） |

### Spec

| 審查發現 | 處理 |
|---|---|
| ui-flow §3.2 的 AI 推薦框行為（已登入導向 `/ai` 並預填；未登入導向登入 `returnUrl=/ai`）未完成，第一輪報告卻標示 ✅ | ✅ 已修正：報告中改為 ⏸，理由見「其他規格對照」；行為待 #13（AI 頁）與 #10（認證）完成 |
| 已登入導覽列（display_name、登出）未實作 | ⏸ 未修正：需要認證（#10）。報告與「未解決事項」已註明 |
| 作者排序測試未能區分排序是否被移除（插入順序與 `contributor_order` 一致） | ✅ 部分修正：測試改為反向插入，並斷言完整輸出字串 `劉慈欣、作者乙`。突變驗證結果：移除角色過濾時測試失敗；移除 `ORDER BY` 時測試仍通過，因為主鍵索引 `(book_id, contributor_order)` 已使查詢依序回傳。`ORDER BY` 保留在程式中作為明確契約；此突變在此資料庫結構下無法由測試觀察，已如實記錄 |
| 兩個 HTTP 快取測試名稱暗示 TTL 到期行為，但實際只驗證「在快取期間被服務」 | ✅ 已修正：改名為 `Empty_snapshot_is_served_from_cache` 與 `Non_empty_snapshot_is_served_from_cache`；TTL 數值由 `tests/UnitTests` 的 `CachedBestsellerReaderTests` 驗證 |

## 未解決事項與後續注意

1. **OriginalAuthor 是否計入作者**：規格與 issue 寫「`AUTHOR` 角色」，目前只取 `ContributorRole.Author`。若原作者（`OriginalAuthor`）也應顯示，需產品端確認。
2. **TTL 的時間行為未以真實時間測試**：`CachedBestsellerReaderTests` 驗證的是設定的 TTL 數值，而非等待實際過期。若要驗證實際過期，需要注入可控時鐘，目前未做。
3. **跨實例快取**：ADR-005 已說明，多 instance 時快取不一致；MVP 單一 instance 可接受。
4. **時區資料相依**：`Asia/Taipei` 優先使用系統 tzdata／ICU；找不到時退回固定 UTC+08:00（見 `deployment.md` §3）。仍建議部署映像包含 tzdata，使顯示名稱與系統時區一致。
5. **Razor 的 CJK 編碼**：Razor 預設將非 ASCII 字元輸出為數字實體。瀏覽器顯示正確，但 HTML 體積較大；本票未變更此設定，測試端以 `HtmlDecode` 處理。若之後要調整，可考慮 `HtmlEncoder.Create(UnicodeRanges.All)`，但屬全域行為變更，需另行評估。
6. **Test 隔離**：每個 Web 測試建立新 factory，`ResetCatalogAsync` 會刪除所有 `books`。這只適用於 Testcontainers 的拋棄式資料庫，不得指向開發或 production 資料庫（測試本來就只透過 fixture 連線）。
7. **後續票依賴**：`/books/{id}`、`/ai`、`/search`、`/library`、`/account/login`、`/account/register` 目前皆未實作，連結會回 404；`/ai` 的導向與預填（#13／#10）、已登入導覽列（#10）留待後續票。
8. **測試基礎設施重複**：`WebFixture` 與 `DatabaseIntegration/PostgresFixture` 有重複的容器啟動程式，留作後續重構（見 Code Review 表）。
9. **ORDER BY 無法由測試觀察**：見 Spec 審查的說明；若未來 contributor 查詢的索引或 SQL 形狀改變，應重新評估是否需要更強的測試。
10. **Web 測試骨架可延伸**：`WebFixture` 與 `BookFinderFactory` 已可供後續 Web 測試（認證、antiforgery、401/404/429、PRG）重用。
