# 實作報告：Issue #8 一般搜尋

- Issue：#8 一般搜尋（GitHub `Arthur801/Book-Finder`）
- Branch：`issue-8-search`（從 `main` 切出，之後 rebase 到新的 `main`）
- 規格：`Docs/modules/book-catalog.md` §2、§3、§7（以 `catalog-display-rules` 的更新版為準，含 2026-10-11 使用者決定；§3.1 的全形輸入決定見規格 commit `290d76e`）；`SEARCH-01～04`
- 本檔為 issue #8 的實作報告，各模組依序在頂層新增一節：M2 搜尋查詢（本節）、M3 搜尋頁與 HTTP 測試（後續追加）。

## M2 搜尋查詢

### 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Catalog/SearchQuery.cs` | 新增 | 搜尋輸入的解析結果（`Empty`／`Isbn(Value, Text)`／`Keyword(Text)`）與 `SearchQuery.Parse` |
| `Application/Catalog/IBookSearch.cs` | 新增 | 資料存取 port `IBookSearch.SearchAsync(query, page, pageSize, ct)` |
| `Application/Catalog/BookSearchPage.cs` | 新增 | `BookSearchPage`（含 `TotalPages` 計算屬性）與 `BookSearchHit` DTO |
| `Application/Catalog/BookSearchService.cs` | 新增 | 搜尋 use case：`PageSize = 20`、頁碼下限 1、空輸入短路 |
| `Infrastructure/Persistence/EfBookSearch.cs` | 新增 | `internal sealed` EF Core 實作：單一 switch 決定比對條件與排序文字、ISBN 與關鍵字比對、排序、分頁 |
| `Infrastructure/Persistence/LikePattern.cs` | 新增 | 單一 helper：`Contains`（子字串）與 `Exact`（完整字串），皆 escape `\`、`%`、`_` |
| `Infrastructure/Persistence/BookAuthors.cs` | 新增 | 共用的 Author 名稱查詢（`ByBookAsync`），供 Bestseller 與一般搜尋共用 |
| `Infrastructure/Persistence/EfBestsellerReader.cs` | 修改 | 作者查詢改用 `BookAuthors.ByBookAsync`，行為不變；移除不再使用的 `Domain.Entities` using |
| `Program.cs` | 修改 | 新增 `using Book_Finder.Application.Catalog;`；在 Bestseller 註冊之後註冊 `IBookSearch`（`EfBookSearch`）與 `BookSearchService` |
| `tests/UnitTests/SearchQueryTests.cs` | 新增 | `SearchQuery.Parse` 的 ISBN 判定邊界、全形輸入與關鍵字規則（25 個案例） |
| `tests/UnitTests/BookSearchServiceTests.cs` | 新增 | 以 fake `IBookSearch` 驗證空輸入、頁碼、PageSize、查詢傳遞，以及 `TotalPages` 六個案例（15 個案例） |
| `Docs/Implementation-Report/issue-8-search.md` | 新增 | 本報告 |

未修改 controller、view、其他模組檔案與規格文件。

### 實作思路

- **輸入判定（`SearchQuery.Parse`）**
  - `q = trim(input)`；為空（含 `null`、空白）→ `Empty`。
  - ISBN 判定前先做 Unicode NFKC（`string.Normalize(NormalizationForm.FormKC)`），把全形數字、全形 `X`／`ｘ`、全形連字號轉成半形（規格 §3.1，使用者 2026-10-11 決定）。NFKC 結果再去除 `-` 與所有空白（`char.IsWhiteSpace`）後轉大寫。
  - 結果為 13 個 ASCII 數字 → `Isbn`；為 9 個 ASCII 數字 + 數字或 `X` → `Isbn`；其餘 → `Keyword`。
  - `Isbn` 同時保存 `Value`（normalized ISBN，用於比對）與 `Text`（trim 後的 q，用於排序的完全相符比較）。
  - `Keyword` 保留 trim 後的原始文字（含全形字、內部空白與連字號），不做 NFKC。NFKC 只用於 ISBN 判定。
  - NFKC 對含未配對代理字元（lone surrogate）的字串會拋出 `ArgumentException`；此時回傳 `null`，視為非 ISBN，輸入成為 `Keyword`。
- **ISBN 模式**：`book_identifiers` 中 `ISBN_13`／`ISBN_10` 且 `identifier_value = Value` 的 Book；不做 10↔13 互轉；`OTHER` 不參與。以 `Any` 子查詢取代 join，避免同一本書重複列出。
- **關鍵字模式**：整段 `q` 為一個字串；`books.title ILIKE '%q%'` OR 任一 `book_contributors.name ILIKE '%q%'`（所有角色）。不比對 description、publisher、subjects。LIKE 特殊字元以 `LikePattern.Contains` escape，並明確指定 escape 字元為 `\`。
- **單一切換點**：`EfBookSearch.Plan(query)` 是唯一對 `SearchQuery` 種類做 switch 的地方，同時回傳比對條件與「完全相符」的文字（ISBN 為 `Text`，關鍵字為 `Text`）。新增查詢種類時只需改這裡。
- **排序**：
  1. `EF.Functions.ILike(book.Title, LikePattern.Exact(text), "\\")`：完全相符（忽略大小寫）者優先。比較完全在 SQL 內進行，與關鍵字比對使用相同的大小寫規則（避免 C# `ToLowerInvariant` 與 SQL `lower()` 不一致，例如 `İ`）。
  2. `PublishedDate.HasValue`（DESC）：Postgres 在 DESC 時預設 NULL 排最前，因此用 `HasValue` 先排，讓 NULL 日期排在有日期的書之後。
  3. `PublishedDate`（DESC）。
  4. `Id`（穩定排序）。
- **分頁與查詢次數**：`BookSearchService` 將頁碼下限設為 1、空輸入直接回傳空頁（不呼叫 port）。`EfBookSearch` 先做 COUNT；offset 以 `long` 計算（避免大頁碼溢位），超出總筆數時直接回傳空頁、不再查詢；否則做一次分頁查詢與一次 Author 查詢（`BookAuthors.ByBookAsync`），共最多 3 次查詢。
- **Author 查詢共用**：`BookAuthors.ByBookAsync` 只列 `Author` 角色、依 `contributor_order`；Bestseller 與一般搜尋同一份實作（行為與修改前相同，既有 Bestseller WebIntegration 測試仍通過）。
- **結果項目**：`BookSearchHit` 只含 book id、書名、作者、出版社、出版日期與精度、封面 URL；不含 description 與 table of contents（AGENTS.md §1.3）。
- **TotalPages**：`TotalCount == 0 ? 0 : ceil(TotalCount / PageSize)`，以整數運算實作。
- **分層**：port 與 DTO 在 Application，EF 實作在 Infrastructure（`internal`），與 Bestseller 切片相同。

### Code Review 與修正

Code review 結果：無阻斷性問題。審查者以一次性 Postgres 驗證了 escape、NULL 日期排序與超出範圍頁。以下為審查後的修正（新增 commit，未改寫歷史）。

| # | 審查意見 | 處理 |
|---|---|---|
| 1 | 全形輸入：ISBN 判定應先做 NFKC | 採用。`Parse` 先 NFKC 再去除連字號與空白，只用於 ISBN 判定；關鍵字保留原文。新增全形 ISBN-13、全形 ISBN-10（末位全形 `ｘ`）、混合全形與半形、全形關鍵字原文保留的單元測試（先紅後綠） |
| 2 | ISBN 模式的完全相符比較應使用 trim 後的 q | 採用。`Isbn` 增加 `Text` 欄位（trim 後的 q），排序使用 `Text`；`Isbn(Value, Text)` 為 contract 變更，所有呼叫端（`BookSearchServiceTests`、`SearchQueryTests`）同步更新 |
| 3 | `EfBookSearch` 有兩個 `SearchQuery` switch（`Matches`、`ExactTitle`），新增種類需改兩處 | 合併為單一 `Plan` switch，回傳比對條件與完全相符文字；移除 `ExactTitle` 名稱 |
| 4 | 完全相符比較在 C# 做 `ToLowerInvariant()`，SQL 端用 `lower()`，大小寫規則可能不一致（例如 `İPQ`） | 採用。改為 `EF.Functions.ILike(book.Title, LikePattern.Exact(text), "\\")` 作為第一個排序鍵，比較完全在 SQL 內進行；新增 `LikePattern.Exact` |
| 5 | Author 名稱查詢在 `EfBookSearch` 與 `EfBestsellerReader` 重複 | 抽出 `internal static class BookAuthors`（`Infrastructure/Persistence/BookAuthors.cs`）的 `ByBookAsync`，兩個 reader 共用；Bestseller 行為不變 |
| 6 | 註解使用中文「一般搜尋」，且 `AUTHOR` 大小寫不一致 | 程式註解改為英文（例如 `General search (book-catalog.md §3)`），Author 統一使用 `Author` 寫法；本報告保留中文 |

審查中另外發現（本次修正之外）：`string.Normalize` 對含未配對代理字元的輸入會拋出 `ArgumentException`，會使 `Parse` 拋例外。已修正：`NormalizeForIsbn` 捕捉此例外並視為非 ISBN（新增單元測試）。

### 執行紀錄（Log）

1. 讀取共同指示與 `book-catalog.md` 更新版（`catalog-display-rules` worktree）§3、§7；參照 `Application/Bestsellers/*`、`EfBestsellerReader.cs`、`Program.cs` 與既有 `tests/UnitTests` 的風格。
2. 第一輪（M2 初版，commit `ad345c0`）：TDD 紅燈（`dotnet test tests/UnitTests` 因型別不存在而編譯失敗），綠燈後實作 `Application/Catalog/*`、`EfBookSearch.cs`、`LikePattern.cs`，並在 `Program.cs` 註冊。
3. 第一輪的暫時性 DatabaseIntegration smoke test（使用既有 `PostgresFixture` 的 pgvector 測試容器，不連線開發或正式資料庫）：第一次執行失敗（4 ≠ 3），原因是測試資料的期望值錯誤（「ZZSMOKE 10」的書名本身包含關鍵字，正確結果為 4 筆）；修正後通過；已刪除，未進 commit。
4. 第二輪（審查修正）：
   - TDD 紅燈：先更新 `SearchQueryTests.cs`（`Isbn(Value, Text)`、全形案例、代理字元案例）與 `BookSearchServiceTests.cs`，`dotnet test tests/UnitTests` 因 `Isbn` 無兩參數建構子而編譯失敗（CS1729）。
   - 代理字元案例先以未修正的程式碼執行：拋出 `System.ArgumentException: String contains invalid Unicode code points`，確認問題後修正 `NormalizeForIsbn`。
   - 實作 NFKC、`Isbn.Text`、`LikePattern.Exact`、`Plan` switch、SQL 端完全相符排序、`BookAuthors`，並改寫註解。
   - 第二輪的暫時性 DB smoke test：重新建立、執行通過（`Passed: 1`），涵蓋原有 smoke 項目與全形 ISBN-13、全形 ISBN-10；另發現：若未配對代理字元進入 Npgsql 參數，會拋出 `EncoderFallbackException`。ASP.NET Core 以 UTF-8 替換字元解碼查詢字串，因此透過 HTTP 不應產生未配對代理字元；此路徑未以 HTTP 驗證。smoke test 已刪除，未進 commit。
5. 以 `git diff --check` 檢查後 commit。

### 驗證結果

逐條對照需求（issue #8 AC 與 `book-catalog.md` §3、§7）：

| 需求 | 結果 | 驗證方式 |
|---|---|---|
| 只查 Local DB；不使用 embedding、LLM、Google Books | ✅ | `EfBookSearch` 只使用 `AppDbContext`；無外部相依 |
| 空白輸入 → 空結果，不列出全部書籍，且不呼叫 port | ✅ | `Empty_input_never_calls_the_port_and_returns_an_empty_page`（null、空字串、空白）、`Blank_input_parses_to_empty` |
| `q = trim(input)`，內部空白保留 | ✅ | `Keyword_is_trimmed_and_keeps_inner_spaces_and_hyphens` |
| ISBN-13：含連字號、空白、13 位數字 | ✅ | `Thirteen_digit_isbn_with_hyphens_and_spaces_is_an_isbn`、`Thirteen_digit_isbn_without_separators_is_an_isbn` |
| ISBN-10：9 位數字 + 數字或 X，含小寫 x，值為大寫 | ✅ | `Ten_character_isbn_ending_in_x_is_an_isbn_with_an_uppercase_x`、`Ten_digit_isbn_ending_in_a_digit_is_an_isbn` |
| 全形 ISBN（NFKC）：全形數字、全形連字號、全形 `ｘ`、混合全半形 | ✅ | `Full_width_isbn_13_with_full_width_hyphens_is_an_isbn`、`Full_width_isbn_10_ending_in_full_width_x_is_an_isbn`、`Mixed_full_width_and_half_width_isbn_is_an_isbn`；整合 smoke 以全形 ISBN-13、ISBN-10 命中正確書籍 |
| 全形但非 ISBN 的輸入保留原文 | ✅ | `Full_width_digits_that_are_not_an_isbn_stay_a_keyword_with_the_original_text`、`Full_width_keyword_keeps_its_original_text` |
| ISBN `Text` 為 trim 後的 q | ✅ | `Isbn_text_is_the_trimmed_input`、`Parsed_isbn_query_reaches_the_port` |
| 12 位、11 位數字 → 關鍵字 | ✅ | `Non_isbn_digit_patterns_are_keywords`（`978986123456`、`97898612345`） |
| 混入字母、X 不在末位、14 字元 → 關鍵字 | ✅ | `Non_isbn_digit_patterns_are_keywords`（`978986123456A`、`12345X7890`、`9789861234567X`、`X`、`0306406152X1`） |
| 未配對代理字元不會使解析拋出例外 | ✅ | `Input_with_a_lone_surrogate_is_a_keyword_and_does_not_throw` |
| ISBN 模式：只比對 ISBN_13／ISBN_10 且值完全相等，不做 10↔13 互轉，OTHER 不參與 | ✅ | 整合 smoke：`978-986-1234-56-7` 只命中 A；`0-306-40615-x` 只命中 B；OTHER 的 `1234567890123` 命中 0 筆 |
| 關鍵字模式：書名或任一貢獻者姓名 ILIKE，整段 q 為一個字串 | ✅ | 整合 smoke：`ZZSMOKE` 命中書名與貢獻者（F 以作者姓名命中） |
| 不比對簡介、出版社、分類 | ✅ | 整合 smoke：description 含關鍵字的 G 未出現在結果中 |
| LIKE 特殊字元 escape（`%`、`_`、`\`） | ✅ | 整合 smoke：`ZZ_SMOKE`、`ZZ%`、`ZZ\SMOKE` 皆 0 筆 |
| 排序：書名與 q 完全相符（忽略大小寫）優先，比較在 SQL 內進行 | ✅ | 整合 smoke：`zzsmoke` 與 `ZZSMOKE` 排在前兩名（兩者皆由 SQL `ILIKE` 判定） |
| 排序：published_date DESC，NULL 最後 | ✅ | 整合 smoke：有日期者 2015、2008 在前，NULL 日期的 F 與 b 在最後 |
| 排序：books.id 穩定排序 | ✅ | `ThenBy(book => book.Id)`（程式碼審查） |
| 每頁 20 筆，page 從 1 起，下限 1 | ✅ | `Page_below_one_is_treated_as_page_one`、`Port_receives_the_page_size_of_twenty` |
| 超出範圍頁回傳空頁、不報錯，總筆數仍正確 | ✅ | 整合 smoke：第 3 頁（每頁 2 筆，共 4 筆）與 `int.MaxValue` 頁皆回傳空 `Hits`、`TotalCount` 為 4 |
| 總筆數以 COUNT 查詢取得 | ✅ | `EfBookSearch` 的 `matches.CountAsync` |
| 結果項目含 book id、書名、Author（僅 `Author` 角色、依 contributor_order）、出版社、出版日期與精度、封面 | ✅ | 整合 smoke：作者 `["劉慈欣"]`（譯者不列出）、出版社、精度 `Year`、封面 URL |
| Bestseller 作者查詢改用 `BookAuthors` 後行為不變 | ✅ | 既有 `tests/WebIntegration` 的 Bestseller 測試通過 |
| 不輸出 description 與 table of contents | ✅ | `BookSearchHit` 無這兩個欄位；`EfBookSearch` 投影不含這兩個欄位 |
| `TotalPages`：0、1、20、21、40、41 筆 → 0、1、1、2、2、3 | ✅ | `Total_pages_is_the_ceiling_of_total_count_over_page_size`（6 個 InlineData） |
| `Program.cs` 註冊 `IBookSearch` 與 `BookSearchService`，無 controller／view | ✅ | 程式碼審查；`git status` 只顯示 `Program.cs` 修改 |

建置與測試（Windows 端經 WSL 執行，rebase 到新 `main` 之後）：

- `dotnet build`：`0 Warning(s)`、`0 Error(s)`
- `dotnet test tests/UnitTests`：`Passed!  - Failed:     0, Passed:    71, Skipped:     0, Total:    71, Duration: 51 ms - UnitTests.dll (net10.0)`（其中 M2 為 `SearchQueryTests` 25 個與 `BookSearchServiceTests` 15 個；其餘來自 `main` 的既有與 catalog display rules 測試）
- `dotnet test tests/DatabaseIntegration`：`Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - DatabaseIntegration.dll (net10.0)`
- `dotnet test tests/WebIntegration`：`Passed!  - Failed:     0, Passed:    20, Skipped:     0, Total:    20, Duration: 2 s - WebIntegration.dll (net10.0)`
- 暫時性 smoke test（已刪除、未 commit）：`Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1`

### 未解決事項

1. **HTTP 層測試交由 M3**：issue #8 的 AC 要求 HTTP 層測試。M3 的測試需涵蓋：
   - `%`、`_`、`\` 的字面比對（不被當成萬用字元）；
   - 出版日期 NULL 排最後；
   - 只列 `Author` 角色的作者（譯者、編者等不列出）；
   - 第 2 頁的第 21 筆結果（每頁 20 筆的分頁邊界）；
   - 書名完全相符（忽略大小寫）排在最前；
   - 全形 ISBN 命中正確書籍。
2. **「查無結果時不呼叫 Google Books」（`book-catalog.md` §7）目前無法測試**：專案尚無 Google Books adapter，此驗證需等 AI 推薦相關 ticket 建立 adapter 後，以 fake adapter 驗證沒有呼叫。M2／M3 不處理。
3. **未配對代理字元**：若此類字元進入 Npgsql 參數，會拋出 `EncoderFallbackException`。依 ASP.NET Core 的查詢字串解碼行為，HTTP 輸入不應產生此類字元，但此假設未以 HTTP 測試驗證；如 M3 的測試發現問題，再處理。
4. **`/search` 頁面、controller、view、分頁 UI**：屬 M3，本模組未處理。

## M3 搜尋頁

### 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `Controllers/SearchController.cs` | 新增 | `[HttpGet("/search")]`，參數 `q`、`page`；`page` 非整數或小於 1 → 第 1 頁；只呼叫 `BookSearchService.SearchAsync` |
| `Models/PageWindow.cs` | 新增 | 純函式 `PageWindow.For(currentPage, totalPages)`：≤ 10 頁全列；否則第 1 頁、最後一頁與目前頁前後各 2 頁，不相鄰處放 `null`（「…」） |
| `Models/SearchResultsViewModel.cs` | 新增 | `SearchResultsViewModel.From(query, page)`、`SearchResultItemViewModel`、`PageLinkViewModel`；作者以「、」連接、出版日期經 `PublishedDateText.Format`、分頁 URL `/search?q={escaped}&page={n}` |
| `Views/Search/Index.cshtml` | 新增 | 搜尋框、「共 N 筆，第 p／P 頁」、結果列表（封面或「無封面」、書名連結、作者、出版社、出版日期）、上一頁／頁碼／下一頁；無結果時「找不到符合的書」 |
| `Views/Shared/_SearchForm.cshtml` | 新增 | 首頁與搜尋頁共用的搜尋表單（label 與 input 完全相同，預填目前 `q`） |
| `Views/Home/Index.cshtml` | 修改 | 搜尋表單改用 `_SearchForm`；label 由「搜尋書名、作者或出版社」改為「搜尋書名、作者或 ISBN」（對齊 book-catalog.md §3.2，出版社不被搜尋） |
| `tests/UnitTests/PageWindowTests.cs` | 新增 | 分頁視窗 11 個案例（0、1、10、11 頁；25 頁的首、中、末頁；超出範圍與小於 1 的頁碼） |
| `tests/WebIntegration/SearchPageTests.cs` | 新增 | `/search` HTTP 層測試 33 個案例（含 Theory 展開） |
| `Docs/Implementation-Report/issue-8-search.md` | 修改 | 追加本節 |

未修改 `Application/Catalog/*`、`EfBookSearch.cs`、`Program.cs`、既有測試與規格文件。`Views/Shared/_Layout.cshtml` 未改；既有 `LayoutAndHomeTests` 只檢查 `action="/search"` 與 `name="q"`，不依賴舊 label，因此未修改任何既有測試。

### 實作思路

- **Controller 只做一件事**：解析 `page`（`long.TryParse`，失敗 → 1；成功 → 夾到 `1..int.MaxValue`，超大頁碼仍落在範圍外而得到空結果頁）後呼叫 `BookSearchService`，不接觸 Google Books、embedding 或 LLM。頁碼下限 1 由 `BookSearchService` 保證。
- **分頁視窗（`PageWindow`）**：先把目前頁夾到 `1..P`，再取前後各 2 頁，並加入第 1 頁與最後一頁放入有序集合；相鄰數字之間不連續即插入 `null`。純函式，無 I/O。
- **ViewModel 的 prev／next**：上一頁為 `min(p − 1, P)`（從超出範圍的頁回到最後一個真實頁）；下一頁只在 `p < P` 時存在；目前頁在頁碼列中不產生連結。
- **結果項目**：作者只來自 `BookSearchHit.Authors`（已是 AUTHOR 角色），無作者時整行不顯示；出版社、出版日期、封面同樣缺值即省略。`ViewModel` 不含 description 與 table of contents 欄位（AGENTS.md §1.3）。
- **共用表單**：`_SearchForm` 以 `@model string` 接收目前 `q`，首頁傳 `string.Empty`，搜尋頁傳 `Model.Query`，label 與 input 不會因兩頁而分歧。

### 執行紀錄（Log）

1. 讀取共同指示、M2 程式與報告、`book-catalog.md` §2–§4.1、`ui-flow.md` §3.2／§3.5／§3.6、`product-requirements.md` SEARCH-01～04、issue #8 內文、既有 Bestseller 與 WebIntegration 測試。
2. TDD 紅燈：
   - 先寫 `tests/UnitTests/PageWindowTests.cs`；`dotnet test tests/UnitTests` 因 `PageWindow` 不存在而編譯失敗（CS0103）。
   - 先寫 `tests/WebIntegration/SearchPageTests.cs`（不含 controller、view）；`dotnet test tests/WebIntegration --filter SearchPageTests` 結果 `Failed!  - Failed: 32, Passed: 0, Skipped: 0, Total: 32`。
3. 綠燈：實作 `PageWindow.cs`，`PageWindowTests` 全部通過；再實作 `SearchController.cs`、`SearchResultsViewModel.cs`、`Views/Search/Index.cshtml`、`_SearchForm.cshtml`，並把首頁表單改為 partial；搜尋頁測試全部通過。
4. 補充 M2 留下的未解決事項 3（未配對代理字元）：新增 `Lone_surrogate_in_the_query_does_not_fail_the_request`（`q=%ED%A0%80`），回應 200，M2 的代理字元擔憂經 HTTP 驗證無問題。
5. 最終建置與全部測試（見驗證結果）。

### 驗證結果

逐條對照 issue #8 AC 與需求。

**Issue #8 Acceptance criteria**

| AC | 結果 | 測試 |
|---|---|---|
| `978-986-xxx` 含連字號、空白、小寫 x 可判定為 ISBN，只回傳完全相符的書 | ✅ | `Isbn_with_hyphens_spaces_or_lowercase_x_finds_only_that_book`（4 案例：`978-986-1234-56-7`、`978 986 1234 567`、`1-55860-832-x`、`1 55860 832 x`）；判定邊界的純函式測試為 M2 的 `SearchQueryTests`（25 案例） |
| 12 位數字不被當成 ISBN | ✅ | `Twelve_digits_are_not_an_isbn_so_a_thirteen_digit_isbn_with_that_prefix_is_not_returned`（輸入 `978986123456`，前綴相同的 ISBN-13 書不回傳） |
| 書名片段與作者片段都能找到書；不比對簡介 | ✅ | `Title_fragment_and_author_fragment_both_find_the_book`（`學習入`、`王小明`、`小明`）；`Description_and_publisher_are_not_searched_and_the_description_never_renders` |
| 輸入 `%` 不會匹配所有書 | ✅ | `Percent_underscore_and_backslash_are_matched_literally`（`%`） |
| 排序符合規則；第 21 筆在第 2 頁 | ✅ | `Exact_title_ignoring_case_comes_first_then_newest_date_with_null_dates_last`；`Twenty_first_match_is_on_page_two_with_the_count_line` |
| 空白輸入回傳空結果，不列出全部書籍 | ✅ | `Blank_input_shows_no_results_and_does_not_list_every_book`（`q=`、`q=%20%20`）；`Search_without_a_query_string_shows_no_results` |
| ISBN 判定以純函式 unit test 涵蓋邊界 | ✅（M2） | `SearchQueryTests`（M2 已完成）；M3 另有 `PageWindowTests` 11 案例 |
| `dotnet test` 通過 | ✅ | 見下方執行結果 |

**book-catalog.md 與 ui-flow.md 規則**

| 規則 | 結果 | 測試 |
|---|---|---|
| §3.1 全形 ISBN（NFKC）找到書 | ✅ | `Full_width_isbn_input_finds_the_book`（`９７８－…` 與 `１５５８６０８３２ｘ`） |
| §3.2 `OTHER` 類型不參與 ISBN 比對 | ✅ | `Other_identifier_with_the_same_value_is_not_matched_in_isbn_mode` |
| §3.2 `%`、`_`、`\` 字面比對 | ✅ | `Percent_underscore_and_backslash_are_matched_literally`（三個 Theory 案例） |
| §3.2 不比對出版社、簡介 | ✅ | `Description_and_publisher_are_not_searched_and_the_description_never_renders` |
| §3.3 無效頁碼（`abc`、`0`、`-1`）視為第 1 頁 | ✅ | `Page_that_is_not_a_positive_integer_shows_the_first_page` |
| §3.3 超出範圍頁回傳空結果、不報錯，提供回上一頁連結 | ✅ | `Page_past_the_end_shows_no_results_but_links_back_to_the_last_page` |
| §3.3 「共 N 筆，第 p／P 頁」 | ✅ | `Twenty_first_match_is_on_page_two_with_the_count_line` |
| §3.3 頁碼：≤ 10 頁全列；超過時首、末、前後各 2 頁，其餘「…」 | ✅ | `PageWindowTests` 全部；`Pager_shows_ellipses_and_the_current_window_when_there_are_more_than_ten_pages`（201 筆、11 頁、第 5 頁） |
| §3.4 作者只列 AUTHOR，以「、」連接 | ✅ | `Result_items_show_authors_only_publisher_year_precision_date_and_placeholder_cover` |
| §3.4 出版日期依精度（YEAR → `2011`） | ✅ | 同上（`published-date` 為 `2011`，且不含 `2011-03`） |
| §3.4 封面或「無封面」佔位 | ✅ | `Cover_is_shown_when_present_and_placeholder_when_not`；同上 |
| §3.4 缺值整列省略 | ✅ | `Missing_author_publisher_and_date_are_left_out_of_the_item` |
| §3.4 連結 `/books/{id}` | ✅ | `Result_items_...`（`href="/books/{id}"`）；所有 `ResultBookIds` 斷言 |
| §3.5 搜尋框預填目前 q | ✅ | `Search_box_is_prefilled_with_the_query` |
| §3.5 空白或查無結果顯示「找不到符合的書」 | ✅ | `Blank_input_...`、`Twelve_digits_...`、`Other_identifier_...`、`Description_and_publisher_...` |
| §3.2 首頁與搜尋頁 label 為「搜尋書名、作者或 ISBN」 | ✅ | `Home_and_search_page_label_the_search_box_with_title_author_or_isbn`（`/` 與 `/search`） |
| ui-flow §3.2 首頁搜尋框送出至 `/search?q=` | ✅ | 既有 `LayoutAndHomeTests.Home_shows_search_and_ai_entry_forms_and_link_to_full_ranking` 仍通過 |
| AGENTS.md §1.3 / "Book 內容顯示"：不輸出簡介與目錄 | ✅ | `Seeded_description_never_appears_in_the_results_html`（description 與 table of contents 都帶標記） |
| §3.4 結果的書名、作者、出版社等只用 Local DB | ✅ | `SearchController` 只依賴 `BookSearchService`（程式碼審查） |
| §7 查無結果時不呼叫 Google Books | ⏸ 未測 | 尚無 Google Books adapter，見未解決事項 |

**Controller 與 M2 handover 項目**

| 項目 | 結果 | 測試 |
|---|---|---|
| M2 #1：`%`、`_`、`\` 字面比對 | ✅ | `Percent_underscore_and_backslash_are_matched_literally` |
| M2 #2：出版日期 NULL 排最後 | ✅ | `Exact_title_ignoring_case_comes_first_then_newest_date_with_null_dates_last` |
| M2 #3：只列 Author 角色（譯者不列出） | ✅ | `Result_items_show_authors_only_...`（譯者甲不出現） |
| M2 #4：第 2 頁第 21 筆 | ✅ | `Twenty_first_match_is_on_page_two_with_the_count_line` |
| M2 #5：完全相符（忽略大小寫）優先 | ✅ | `Exact_title_ignoring_case_comes_first_...`（`python`、`PYTHON` 排在前） |
| M2 #6：全形 ISBN 命中正確書 | ✅ | `Full_width_isbn_input_finds_the_book` |
| M2 #3（未解決）：未配對代理字元 | ✅ | `Lone_surrogate_in_the_query_does_not_fail_the_request`（200） |

**建置與測試（Windows 端經 WSL 執行，commit 前）**

- `dotnet build --no-incremental`：`0 Warning(s)`、`0 Error(s)`
- `dotnet test tests/UnitTests`：`Passed!  - Failed:     0, Passed:    82, Skipped:     0, Total:    82, Duration: 51 ms - UnitTests.dll (net10.0)`（M2 的 71 + M3 的 `PageWindowTests` 11）
- `dotnet test tests/DatabaseIntegration`：`Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - DatabaseIntegration.dll (net10.0)`
- `dotnet test tests/WebIntegration`：`Passed!  - Failed:     0, Passed:    53, Skipped:     0, Total:    53, Duration: 4 s - WebIntegration.dll (net10.0)`（既有 20 + M3 的 `SearchPageTests` 33）

### 未解決事項

1. **§7「查無結果時不呼叫 Google Books」未測試**：專案尚無 Google Books adapter，需等 AI 推薦相關 ticket 建立 adapter 後，以 fake adapter 驗證沒有呼叫。
2. **呈現上的本地決定（可逆，請審閱）**：
   - 超出範圍頁（例 `page=30`、共 25 頁）：頁碼列以第 25 頁為中心（1、…、23、24、25）；上一頁指向第 25 頁；只顯示「共 N 筆」，不顯示「第 p／P 頁」。規格只說「回傳空結果頁」，未規定頁碼列與計數文字，因此採此最小處理。
   - `page` 為超過 `int` 範圍的整數：夾到 `int.MaxValue`，得到超出範圍的空結果頁（而非視為第 1 頁）。規格「非整數 → 第 1 頁」不涵蓋此情況，屬整數但極大，故採此處理。
   - 搜尋框預填的是使用者輸入的原始 `q`（未 trim）。
3. **頁面未以瀏覽器實際檢視**：版面（手機寬度、封面尺寸、分頁換行）只經 HTML 測試驗證，未做視覺檢查。
4. 未建立 `/search` 的 JSON 端點（ui-flow 與規格皆無此需求）。
