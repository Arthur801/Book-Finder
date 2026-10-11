# 實作報告：Issue #8 一般搜尋

- Issue：#8 一般搜尋（GitHub `Arthur801/Book-Finder`）
- Branch：`issue-8-search`（從 `main` 切出）
- 規格：`Docs/modules/book-catalog.md` §2、§3、§7（以 `catalog-display-rules` 的更新版為準，含 2026-10-11 使用者決定）；`SEARCH-01～04`
- 本檔為 issue #8 的實作報告，各模組依序在頂層新增一節：M2 搜尋查詢（本節）、M3 搜尋頁與 HTTP 測試（後續追加）。

## M2 搜尋查詢

### 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Catalog/SearchQuery.cs` | 新增 | 搜尋輸入的解析結果（`Empty`／`Isbn`／`Keyword`）與 `SearchQuery.Parse` |
| `Application/Catalog/IBookSearch.cs` | 新增 | 資料存取 port `IBookSearch.SearchAsync(query, page, pageSize, ct)` |
| `Application/Catalog/BookSearchPage.cs` | 新增 | `BookSearchPage`（含 `TotalPages` 計算屬性）與 `BookSearchHit` DTO |
| `Application/Catalog/BookSearchService.cs` | 新增 | 搜尋 use case：`PageSize = 20`、頁碼下限 1、空輸入短路 |
| `Infrastructure/Persistence/EfBookSearch.cs` | 新增 | `internal sealed` EF Core 實作：ISBN 模式、關鍵字模式、排序、分頁、作者查詢 |
| `Infrastructure/Persistence/LikePattern.cs` | 新增 | 單一 helper：把使用者文字轉成字面比對的 ILIKE pattern（escape `\`、`%`、`_`） |
| `Program.cs` | 修改 | 新增 `using Book_Finder.Application.Catalog;`；在 Bestseller 註冊之後註冊 `IBookSearch`（`EfBookSearch`）與 `BookSearchService` |
| `tests/UnitTests/SearchQueryTests.cs` | 新增 | `SearchQuery.Parse` 的 ISBN 判定邊界與關鍵字規則（18 個案例） |
| `tests/UnitTests/BookSearchServiceTests.cs` | 新增 | 以 fake `IBookSearch` 驗證空輸入、頁碼、PageSize、查詢傳遞，以及 `TotalPages` 六個案例 |
| `Docs/Implementation-Report/issue-8-search.md` | 新增 | 本報告 |

未修改 controller、view、其他模組檔案與規格文件。

### 實作思路

- **輸入判定（`SearchQuery.Parse`）**
  - `q = trim(input)`；為空（含 `null`、空白）→ `Empty`。
  - `normalized` = 去除 `-` 與所有空白（`char.IsWhiteSpace`）後轉大寫。
  - `normalized` 為 13 個 ASCII 數字 → `Isbn`；為 9 個 ASCII 數字 + 數字或 `X` → `Isbn`；其餘 → `Keyword`。
  - `Keyword` 保留 trim 後的原文（內部空白與連字號保留），不做 normalize。
  - 只接受 ASCII 數字 `0-9`；全形數字不視為 ISBN 字元（見未解決事項）。
- **ISBN 模式**：`book_identifiers` 中 `ISBN_13`／`ISBN_10` 且 `identifier_value = normalized` 的 Book；不做 10↔13 互轉；`OTHER` 不參與。以 `Any` 子查詢取代 join，避免同一本書重複列出。
- **關鍵字模式**：整段 `q` 為一個字串；`books.title ILIKE '%q%'` OR 任一 `book_contributors.name ILIKE '%q%'`（所有角色）。不比對 description、publisher、subjects。LIKE 特殊字元以 `LikePattern` escape，並明確指定 escape 字元為 `\`（`EF.Functions.ILike(column, pattern, "\\")`）。
- **排序**：`OrderByDescending(title 轉小寫 == q 轉小寫)` → `ThenByDescending(PublishedDate.HasValue)` → `ThenByDescending(PublishedDate)` → `ThenBy(Id)`。Postgres 在 DESC 時預設 NULL 排最前，因此用 `HasValue` 作為先排的鍵，讓 NULL 日期排在有日期的書之後。
- **分頁與查詢次數**：`BookSearchService` 將頁碼下限設為 1、空輸入直接回傳空頁（不呼叫 port）。`EfBookSearch` 先做 COUNT；offset 以 `long` 計算（避免大頁碼溢位），超出總筆數時直接回傳空頁、不再查詢；否則做一次分頁查詢與一次作者查詢（`AUTHOR` 角色、依 `contributor_order`），共最多 3 次查詢。
- **結果項目**：`BookSearchHit` 只含 book id、書名、作者、出版社、出版日期與精度、封面 URL；不含 description 與 table of contents（AGENTS.md §1.3）。
- **TotalPages**：`TotalCount == 0 ? 0 : ceil(TotalCount / PageSize)`，以整數運算實作。
- **分層**：port 與 DTO 在 Application，EF 實作在 Infrastructure（`internal`），與 Bestseller 切片相同。

### 執行紀錄（Log）

1. 讀取共同指示與 `book-catalog.md` 更新版（`catalog-display-rules` worktree）§3、§7；參照 `Application/Bestsellers/*`、`EfBestsellerReader.cs`、`Program.cs` 與既有 `tests/UnitTests` 的風格。
2. TDD 紅燈：先寫 `SearchQueryTests.cs` 與 `BookSearchServiceTests.cs`，`dotnet test tests/UnitTests` 因型別不存在而編譯失敗（CS0234、CS0246）。
3. 綠燈：實作 `Application/Catalog/*`，`dotnet test tests/UnitTests` → 42 passed。
4. 實作 `EfBookSearch.cs`、`LikePattern.cs`，並在 `Program.cs` 註冊。`dotnet build` 0 warnings、0 errors。
5. 因 EF 查詢只有在真實 PostgreSQL 才會驗證 SQL 翻譯與排序，另建一個**暫時性**的 DatabaseIntegration smoke test（使用既有 `PostgresFixture` 的 pgvector 測試容器，不連線開發或正式資料庫）。第一次執行失敗（4 ≠ 3），原因是測試資料的期望值錯誤：「ZZSMOKE 10」的書名本身包含關鍵字，正確結果應為 4 筆。修正測試期望後通過；確認後已刪除該檔案，未進 commit。
6. 確認 smoke test 涵蓋：書名完全相符（忽略大小寫）優先、NULL 日期最後、作者只列 AUTHOR、ISBN-13／ISBN-10 比對、`OTHER` 不比對、`_`／`%`／`\` 字面比對、description 不參與比對、超出範圍頁與極大頁碼回傳空頁。
7. 以 `git diff --check` 檢查後 commit。

### 驗證結果

逐條對照需求（issue #8 AC 與 `book-catalog.md` §3、§7）：

| 需求 | 結果 | 驗證方式 |
|---|---|---|
| 只查 Local DB；不使用 embedding、LLM、Google Books | ✅ | `EfBookSearch` 只使用 `AppDbContext`；無外部相依 |
| 空白輸入 → 空結果，不列出全部書籍，且不呼叫 port | ✅ | `Empty_input_never_calls_the_port_and_returns_an_empty_page`（null、空字串、空白）、`Blank_input_parses_to_empty` |
| `q = trim(input)`，內部空白保留 | ✅ | `Keyword_is_trimmed_and_keeps_inner_spaces_and_hyphens` |
| ISBN-13：含連字號、空白、13 位數字 | ✅ | `Thirteen_digit_isbn_with_hyphens_and_spaces_is_an_isbn`、`Thirteen_digit_isbn_without_separators_is_an_isbn` |
| ISBN-10：9 位數字 + 數字或 X，含小寫 x，值為大寫 | ✅ | `Ten_character_isbn_ending_in_x_is_an_isbn_with_an_uppercase_x`、`Ten_digit_isbn_ending_in_a_digit_is_an_isbn` |
| 12 位、11 位數字 → 關鍵字 | ✅ | `Non_isbn_digit_patterns_are_keywords`（`978986123456`、`97898612345`） |
| 混入字母、X 不在末位、14 字元 → 關鍵字 | ✅ | `Non_isbn_digit_patterns_are_keywords`（`978986123456A`、`12345X7890`、`9789861234567X`、`X`、`0306406152X1`） |
| normalized 無連字號與空白、為大寫 | ✅ | ISBN 案例的斷言（`9789861234567`、`030640615X`） |
| ISBN 模式：只比對 ISBN_13／ISBN_10 且值完全相等，不做 10↔13 互轉，OTHER 不參與 | ✅ | 整合 smoke：`978-986-1234-56-7` 只命中 A；`0-306-40615-x` 只命中 B；OTHER 的 `1234567890123` 命中 0 筆 |
| 關鍵字模式：書名或任一貢獻者姓名 ILIKE，整段 q 為一個字串 | ✅ | 整合 smoke：`ZZSMOKE` 命中書名與貢獻者（F 以作者姓名命中） |
| 不比對簡介、出版社、分類 | ✅ | 整合 smoke：description 含關鍵字的 G 未出現在結果中 |
| LIKE 特殊字元 escape（`%`、`_`、`\`） | ✅ | 整合 smoke：`ZZ_SMOKE`、`ZZ%`、`ZZ\SMOKE` 皆 0 筆（未被當成萬用字元或拋錯） |
| 排序：書名與 q 完全相符（忽略大小寫）優先 | ✅ | 整合 smoke：`zzsmoke` 與 `ZZSMOKE` 排在前兩名 |
| 排序：published_date DESC，NULL 最後 | ✅ | 整合 smoke：有日期者 2015、2008 在前，NULL 日期的 F 與 b 在最後 |
| 排序：books.id 穩定排序 | ✅ | `ThenBy(book => book.Id)`（程式碼審查） |
| 每頁 20 筆，page 從 1 起，下限 1 | ✅ | `Page_below_one_is_treated_as_page_one`、`Port_receives_the_page_size_of_twenty` |
| 超出範圍頁回傳空頁、不報錯，總筆數仍正確 | ✅ | 整合 smoke：第 3 頁（每頁 2 筆，共 4 筆）與 `int.MaxValue` 頁皆回傳空 `Hits`、`TotalCount` 為 4 |
| 總筆數以 COUNT 查詢取得 | ✅ | `EfBookSearch` 的 `matches.CountAsync` |
| 結果項目含 book id、書名、作者（僅 AUTHOR、依 contributor_order）、出版社、出版日期與精度、封面 | ✅ | 整合 smoke：作者 `["劉慈欣"]`（譯者不列出）、出版社、精度 `Year`、封面 URL |
| 不輸出 description 與 table of contents | ✅ | `BookSearchHit` 無這兩個欄位；`EfBookSearch` 投影不含這兩個欄位 |
| `TotalPages`：0、1、20、21、40、41 筆 → 0、1、1、2、2、3 | ✅ | `Total_pages_is_the_ceiling_of_total_count_over_page_size`（6 個 InlineData） |
| `Program.cs` 註冊 `IBookSearch` 與 `BookSearchService`，無 controller／view | ✅ | 程式碼審查；`git status` 只顯示 `Program.cs` 修改 |

建置與測試（Windows 端經 WSL 執行）：

- `dotnet build`：`0 Warning(s)`、`0 Error(s)`
- `dotnet test tests/UnitTests`：`Passed!  - Failed:     0, Passed:    42, Skipped:     0, Total:    42, Duration: 41 ms - UnitTests.dll (net10.0)`
- `dotnet test tests/DatabaseIntegration`：`Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - DatabaseIntegration.dll (net10.0)`（既有測試，Program 與 DI 註冊變更後仍通過）
- `dotnet test tests/WebIntegration`：`Passed!  - Failed:     0, Passed:    20, Skipped:     0, Total:    20, Duration: 2 s - WebIntegration.dll (net10.0)`（既有測試，Program 變更後仍通過）
- 暫時性 smoke test（已刪除、未 commit）：`Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1`

### 未解決事項

1. **ISBN 模式的「書名完全相符」比對對象**：`SearchQuery.Isbn` 只保存 normalized 值，因此 ISBN 模式下排序的「書名相符」比較的是 normalized 值，而非 trim 後的原始輸入（例如原始輸入含連字號時）。規格將 q 定義為 trim 後的輸入。兩者只在書名剛好等於 ISBN 字串時才有差異，實務上幾乎不會發生；如需嚴格一致，需要調整 `SearchQuery.Isbn` 的 contract（保存原文）。待確認。
2. **全形數字**：ISBN 判定只接受 ASCII 數字。全形數字（例如 `９７８...`）會被視為關鍵字。這是依「13 位數字」字面解讀的決定，屬低風險預設；若要改變請告知。
3. **`---` 等只含連字號的輸入**：normalized 為空，因此成為關鍵字模式（q 不為空）。依規格字面處理，未特別處理。
4. **EF 查詢與 LIKE escape 沒有 committed 的自動化測試**：本模組只提交了 unit test；EF 查詢（ILIKE escape、排序、分頁）只以上述暫時性 smoke test 驗證過一次，該檔案未保留。issue #8 的 AC 要求 HTTP 層的整合測試，由 M3 負責，建議在 M3 的 HTTP 測試中涵蓋 `%`、`_`、`\` 的字面比對，以及 NULL 日期排序與 AUTHOR-only 作者列表。
5. **`/search` 頁面、controller、view、分頁 UI**：屬 M3，本模組未處理。
