# Issue #5 實作報告：暢銷榜頁與 Web 測試骨架

- Issue：#5
- Branch：issue-5-bestseller-page
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 變更檔案

| 檔案 | 類型（新增/修改/刪除） | 說明 |
|---|---|---|
| `Application/Bestsellers/BestsellerSnapshot.cs` | 新增 | `BestsellerSnapshot`（`CapturedAt` + `Entries`）與 `BestsellerEntry`（rank、book id、title、authors、thumbnail）record |
| `Application/Bestsellers/IBestsellerReader.cs` | 新增 | Application 層資料存取介面，回傳整份目前榜單 |
| `Application/Bestsellers/BestsellerService.cs` | 新增 | 讀取 use case：`GetTopAsync(count)`、`GetAllAsync()`；整份榜單以 `IMemoryCache` 快取，非空 1 小時、空 5 分鐘 |
| `Infrastructure/Persistence/EfBestsellerReader.cs` | 新增 | `IBestsellerReader` 的 EF Core 實作；兩次查詢（榜單 join books、再一次查所有 AUTHOR 角色貢獻者），無 N+1 |
| `Models/BestsellerListViewModel.cs` | 新增 | Presentation 用 view model；負責作者串接（`、`）與 `captured_at` → Asia/Taipei 格式化（`yyyy-MM-dd HH:mm 更新`） |
| `Controllers/BestsellersController.cs` | 新增 | `/bestsellers`，回傳完整榜單 |
| `Views/Bestsellers/Index.cshtml` | 新增 | 暢銷榜頁，使用共用 partial |
| `Views/Shared/_BestsellerEntries.cshtml` | 新增 | 榜單列表 partial（排名、封面、書名連結 `/books/{id}`、作者、更新時間、空狀態「榜單尚未建立」），首頁與暢銷榜頁共用 |
| `Controllers/HomeController.cs` | 修改 | `Index` 改為取前 10 名；移除 `Privacy` action |
| `Views/Home/Index.cshtml` | 修改 | 一般搜尋表單（GET `/search?q=`）、AI 推薦表單（GET `/ai`）、暢銷榜前 10 名、「查看完整榜單」連結 |
| `Views/Home/Privacy.cshtml` | 刪除 | 範本樣板頁，已無規格依據 |
| `Views/Shared/_Layout.cshtml` | 修改 | 導覽列：logo（好想找書）→ `/`、暢銷榜、AI 推薦、個人書單，右側登入／註冊；移除 Privacy 連結與 footer 的 Privacy 連結；`lang="zh-Hant"` |
| `Program.cs` | 修改 | 註冊 `AddMemoryCache`、`IBestsellerReader → EfBestsellerReader`、`BestsellerService`；檔尾 `public partial class Program { }` 供測試使用 |
| `Book-Finder.slnx` | 修改 | 加入 `tests/WebIntegration/WebIntegration.csproj` |
| `tests/WebIntegration/WebIntegration.csproj` | 新增 | xUnit 測試專案；引用 `Microsoft.AspNetCore.Mvc.Testing` 10.0.12、`Testcontainers.PostgreSql` 4.16.0 |
| `tests/WebIntegration/WebFixture.cs` | 新增 | `WebFixture`（一個 `pgvector/pgvector:pg17` 容器、啟動時套用全部 migration、`CreateFactory()`、`ResetCatalogAsync()`）、`BookFinderFactory : WebApplicationFactory<Program>`（以 `UseSetting` 注入容器連線字串）、`WebCollection` collection fixture |
| `tests/WebIntegration/BestsellerSeed.cs` | 新增 | 透過 `AppDbContext` 直接寫入 Book、Book Source（博客來 URL）、Contributor、Bestseller 的 seed helper |
| `tests/WebIntegration/HttpAssertions.cs` | 新增 | 以 HTTP 取頁面（斷言 200、HTML decode）並解析 `data-rank` 順序 |
| `tests/WebIntegration/BestsellerPageTests.cs` | 新增 | 首頁前 10、rank 11 納入、100 筆完整榜單、缺號不重編、作者／封面／書名、`/books/{id}` 連結、Asia/Taipei 更新時間、空狀態 200、快取行為（HTTP 層） |
| `tests/WebIntegration/LayoutAndHomeTests.cs` | 新增 | 導覽列連結、Privacy 頁移除、首頁搜尋／AI 表單與「查看完整榜單」連結 |
| `tests/WebIntegration/BestsellerCacheTests.cs` | 新增 | Application 層快取 TTL（1 小時／5 分鐘）、快取命中時不重讀 reader、`GetTopAsync` 行為；使用 fake reader 與記錄 TTL 的 `IMemoryCache` 包裝 |
| `Docs/testing/test-plan.md` | 修改 | Web 測試列的位置改為 `tests/WebIntegration`，並註明目前覆蓋範圍 |
| `Docs/Implementation-Report/issue-5-bestseller-page.md` | 新增 | 本報告 |

## 實作思路

### 分層

- **Presentation**（`HomeController`、`BestsellersController`、Razor）只呼叫 `BestsellerService`，不碰 `DbContext`、不寫 SQL。
- **Application**（`Application/Bestsellers/`）：`BestsellerService` 是讀取 use case，擁有快取策略；`IBestsellerReader` 是唯一的資料存取切點。
- **Infrastructure**（`EfBestsellerReader`）實作 `IBestsellerReader`，依 `rank` 排序，對應 `Docs/modules/bestseller.md` §2 的 `SELECT rank, book, captured_at FROM bestsellers JOIN books ORDER BY rank`。
- **Domain**：沒有變更，直接使用既有 `Bestseller`、`Book`、`BookContributor`、`ContributorRole`。

### 介面切點

- `IBestsellerReader.ReadCurrentAsync` 回傳整份榜單（最多 100 筆）與 `CapturedAt`。空榜單回傳 `CapturedAt = null` 與空清單。
- Application 的 record（`BestsellerSnapshot`、`BestsellerEntry`）不依賴 EF 或 ASP.NET；作者清單已在 Infrastructure 組好。
- Presentation view model（`BestsellerListViewModel`）負責格式化（作者串接、時區），Razor 只做輸出。

### 快取策略（ADR-005）

- 快取鍵 `bestsellers:current`，值為整份 `BestsellerSnapshot`。首頁與 `/bestsellers` 讀同一份快取。
- 非空榜單：`AbsoluteExpirationRelativeToNow = 1 小時`；空榜單：`5 分鐘`。TTL 以 `static readonly TimeSpan` 常數定義在 `BestsellerService`，`GetOrCreateAsync` 工廠依結果設定。
- `GetTopAsync` 在快取的整份清單上取前 N 筆（`Take`），不另外查詢，因此首頁與完整榜單保持一致。
- 快取只存可由 PostgreSQL 重建的資料（ADR-005），不作為 source of truth。

### 排名與前 10 名

- 顯示 `rank` 原值，不重新編號；缺號時 36 之後直接接 38。
- 首頁的「前 10 名」是 rank 排序後的前 10 筆，因此缺號時可能包含 rank 11（見規格 §3）。

### 測試骨架設計

- **共用 fixture**：`WebFixture` 是 collection fixture，整次測試只啟動一個 `pgvector/pgvector:pg17` 容器並套用全部 migration（沿用 `tests/DatabaseIntegration/PostgresFixture.cs` 的模式）。
- **連線字串注入**：`BookFinderFactory` 使用 `WebApplicationFactory<Program>.ConfigureWebHost` 內的 `builder.UseSetting("ConnectionStrings:DefaultConnection", ...)`。已驗證 minimal hosting 會讀到這個設定，`Program.cs` 的 `InvalidOperationException` 不會觸發。
- **快取隔離**：`IMemoryCache` 存在 app instance 中，因此**每個測試建立新的 factory**（新的 host、新的 cache）。
- **資料隔離**：`ResetCatalogAsync()` 先刪 `bestsellers`（RESTRICT FK），再刪 `books`（CASCADE 到 book_sources、book_contributors）。同一個 collection 的測試依序執行，不會互相干擾。
- **只透過 HTTP 驗證**：頁面測試一律以 `HttpClient` 取頁面，斷言狀態碼與 HTML 內容；測試不直接呼叫 Controller。資料以 `AppDbContext` 直接 seed。
- **TTL 驗證**：HTTP 層測試驗證「空榜單在 TTL 內不會被新資料取代」與「非空榜單在 TTL 內即使資料庫被清空仍被服務」。TTL 數值本身在 `BestsellerCacheTests` 以 `RecordingMemoryCache` 驗證：它是包裝真實 `MemoryCache` 的 `IMemoryCache`，記錄每個建立的 `ICacheEntry`，讀回 `AbsoluteExpirationRelativeToNow`。

### 自行決定、規格未定義或與規格不同之處

1. **作者角色**：依 issue 與規格字面，只取 `ContributorRole.Author`；`OriginalAuthor` 未納入。這是待確認事項（見下節）。
2. **作者分隔符**：多位作者以「、」串接；規格未定義格式。
3. **無封面**：`ThumbnailUrl` 為 null 時顯示「無封面」文字佔位；規格未定義。
4. **搜尋表單參數**：一般搜尋輸入欄位 `name="q"`（`/search?q=` 來自 ui-flow §2/§3.2）。AI 推薦表單以 GET 送到 `/ai`，欄位同樣命名為 `q`；ui-flow §3.2 說明「導向 `/ai` 並預填」，但 `/ai` 頁面與預填機制由後續票實作，因此目前只是純 GET 表單（規格未定義參數名稱）。
5. **Asia/Taipei 格式**：`TimeZoneInfo.FindSystemTimeZoneById("Asia/Taipei")` 依系統 tzdata／ICU；`captured_at` 若 Kind 為 Unspecified 視為 UTC。
6. **導覽列細節**：logo 文字為「好想找書」；footer 文字改為「© 2026 - 好想找書」，移除 Privacy 連結。`/ai`、`/library`、`/account/login`、`/account/register` 目前尚未實作，連結會回 404，屬於後續票範圍。
7. **首頁標題**：首頁加入「找書」「暢銷榜前 10 名」標題文字，規格未指定文案。
8. **Privacy**：刪除範本 Privacy action 與 view，依 issue「若只是範本樣板則移除」的指示。
9. **未實作**：ui-flow §3.1 要求已登入時顯示 display_name 與「登出」；本票無認證，因此未實作，右側一律顯示登入／註冊。
10. **快取工廠捕捉 CancellationToken**：`GetOrCreateAsync` 的工廠使用請求的 `CancellationToken`。若該請求中途取消，讀取會拋出例外，不會寫入快取，因此不影響正確性。

## 執行紀錄（Log）

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
15. 撰寫本報告，commit。

## 驗證結果

### Issue #5 Acceptance criteria

| 條目 | 結果 | 對應測試 |
|---|---|---|
| 測試 seed 榜單後，首頁回傳 rank 最小的 10 本，`/bestsellers` 回傳全部 | ✅ | `BestsellerPageTests.Home_shows_the_first_ten_rows_by_rank`；`BestsellerPageTests.Bestsellers_page_lists_all_100_entries_in_rank_order_without_pagination` |
| 第 37 名缺號時，畫面上 36 之後接 38 | ✅ | `BestsellerPageTests.Skipped_rank_is_not_renumbered_on_either_page` |
| 顯示 `captured_at`（Asia/Taipei）作為更新時間 | ✅ | `BestsellerPageTests.Updated_at_is_shown_in_taipei_time_on_both_pages` |
| 空榜單時顯示「榜單尚未建立」且狀態碼為 200 | ✅ | `BestsellerPageTests.Empty_bestsellers_show_placeholder_with_status_200_on_both_pages` |
| 每本書可連到 `/books/{id}` | ✅ | `BestsellerPageTests.Each_entry_links_to_its_book_detail_page_on_both_pages` |
| 導覽列包含暢銷榜、AI 推薦、個人書單，以及登入／註冊入口 | ✅ | `LayoutAndHomeTests.Shared_navbar_links_to_sections_and_auth_entry_points`（`/` 與 `/bestsellers` 兩個 case） |
| Web 層測試透過 HTTP 驗證以上行為，不直接呼叫 Controller | ✅ | 所有 `BestsellerPageTests`、`LayoutAndHomeTests` 只使用 `HttpClient`；`BestsellerCacheTests` 為 Application 層，不經 Controller |
| `dotnet build`、`dotnet test` 通過 | ✅ | 見下方 summary |

### 其他規格對照

| 規格 | 結果 | 對應測試 |
|---|---|---|
| 首頁 rank 排序後前 10 筆，可能包含 rank 11 | ✅ | `BestsellerPageTests.Home_top_ten_can_include_rank_11_when_a_rank_is_skipped` |
| 作者只取 AUTHOR 角色，依 `contributor_order` | ✅ | `BestsellerPageTests.Entries_show_cover_title_and_author_contributors_in_order` |
| 封面、書名顯示 | ✅ | 同上 |
| 空榜單首頁與 `/bestsellers` 皆 200 | ✅ | `Empty_bestsellers_show_placeholder_with_status_200_on_both_pages` |
| 空榜單 5 分鐘 TTL（HTTP 層） | ✅ | `BestsellerPageTests.Empty_snapshot_stays_cached_until_its_five_minute_ttl_expires` |
| 非空榜單快取（HTTP 層） | ✅ | `BestsellerPageTests.Non_empty_snapshot_is_served_from_cache_for_one_hour` |
| 非空榜單 TTL 1 小時、空榜單 TTL 5 分鐘（數值） | ✅ | `BestsellerCacheTests.Non_empty_snapshot_is_cached_for_one_hour`；`BestsellerCacheTests.Empty_snapshot_is_cached_for_five_minutes` |
| 快取命中時不重讀 reader | ✅ | `BestsellerCacheTests.Reader_is_called_once_while_the_snapshot_is_cached` |
| `GetTopAsync` 取前 N 筆並保留 `captured_at` | ✅ | `BestsellerCacheTests.Top_returns_the_first_rows_by_rank_with_the_capture_time` |
| 首頁提供一般搜尋表單與 AI 推薦表單，並有「查看完整榜單」連結 | ✅ | `LayoutAndHomeTests.Home_shows_search_and_ai_entry_forms_and_link_to_full_ranking` |
| Privacy 範本頁已移除 | ✅ | `LayoutAndHomeTests.Privacy_boilerplate_page_is_removed` |

### dotnet test 結果摘要

```text
Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - DatabaseIntegration.dll (net10.0)
Passed!  - Failed:     0, Passed:    18, Skipped:     0, Total:    18, Duration: 6 s - WebIntegration.dll (net10.0)
```

另有：`dotnet build` 為 `0 Error(s)`、`0 Warning(s)`；`dotnet ef migrations has-pending-model-changes` 為 `No changes have been made to the model since the last migration.`

## 未解決事項與後續注意

1. **OriginalAuthor 是否計入作者**：規格與 issue 寫「`AUTHOR` 角色」，目前只取 `ContributorRole.Author`。若原作者（`OriginalAuthor`）也應顯示，需產品端確認。
2. **TTL 的時間行為未以真實時間測試**：`BestsellerCacheTests` 驗證的是設定的 TTL 數值，而非等待實際過期。若要驗證實際過期，需要注入可控時鐘（`MemoryCacheOptions` 的 clock 或 `TimeProvider`），目前未做。
3. **跨實例快取**：ADR-005 已說明，多 instance 時快取不一致；MVP 單一 instance 可接受。
4. **時區資料相依**：`Asia/Taipei` 需要系統 tzdata／ICU。本機 WSL 與測試皆通過；部署用的容器映像需確認含 tzdata（否則 `FindSystemTimeZoneById` 會拋例外，首頁與暢銷榜會 500）。
5. **Razor 的 CJK 編碼**：Razor 預設將非 ASCII 字元輸出為數字實體。瀏覽器顯示正確，但 HTML 體積較大；本票未變更此設定，測試端以 `HtmlDecode` 處理。若之後要調整，可考慮 `HtmlEncoder.Create(UnicodeRanges.All)`，但屬全域行為變更，需另行評估。
6. **Test 隔離**：每個測試建立新 factory，`ResetCatalogAsync` 會刪除所有 `books`。這只適用於 Testcontainers 的拋棄式資料庫，不得指向開發或 production 資料庫（測試本來就只透過 fixture 連線）。
7. **後續票依賴**：`/books/{id}`、`/ai`、`/search`、`/library`、`/account/login`、`/account/register` 目前皆未實作，連結會回 404；這些是後續票的範圍。ui-flow §3.1 的已登入狀態列也留待 auth 票。
8. **Web 測試骨架可延伸**：`WebFixture` 與 `BookFinderFactory` 已可供後續 Web 測試（認證、antiforgery、401/404/429、PRG）重用。
