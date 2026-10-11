# Issue #9 Book 詳細頁：實作報告

- Issue：#9 Book 詳細頁（BOOK-01～05）
- Branch：`issue-9-book-detail`（from `main`）
- 規格：`Docs/modules/book-catalog.md` §4、§4.1、§5（catalog-display-rules 分支的更新版，含使用者 2026-10-11 決定）；`Docs/requirements/product-requirements.md` BOOK-01～05；`AGENTS.md` §1.3「Book 內容顯示」
- 排序與快取規則的來源：使用者 2026-10-11 的決定，已記錄於本分支的 `Docs/modules/book-catalog.md` §4.1 與 §5。本分支已 rebase 到 main，文件與程式一致；M4 撰寫時曾是舊版，現已更新。
- 日期：2026-10-11

本檔為 issue #9 的實作紀錄，各模組依序以「## Mx ...」新增章節。M4 與 M5 各為一個章節。

## M4 Book 詳細資料查詢

### 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Catalog/IBookDetailReader.cs` | 新增 | 讀取單一 Book 詳細資料的 port；找不到時回傳 `null` |
| `Application/Catalog/BookDetail.cs` | 新增 | `BookDetail`、`BookDetailContributor`、`BookDetailIdentifier`、`BookDetailSource` 四個 record；不含 description 與 table of contents |
| `Infrastructure/Persistence/EfBookDetailReader.cs` | 新增 | EF Core 實作，以投影只取需要的欄位，`AsNoTracking`，依各規則排序 |
| `Infrastructure/Caching/CachedBookDetailReader.cs` | 新增 | `IMemoryCache` 裝飾器，TTL 10 分鐘，以 Book id 為 key；找不到的 Book 不快取 |
| `Program.cs` | 修改 | 註冊 `EfBookDetailReader` 與以 `CachedBookDetailReader` 包裝的 `IBookDetailReader`（與 Bestseller 相同寫法） |
| `tests/UnitTests/CachedBookDetailReaderTests.cs` | 新增 | 4 個快取行為測試（TTL、重複讀取只呼叫一次、不同 Book 分開快取、找不到不快取） |
| `tests/UnitTests/RecordingMemoryCache.cs` | 新增 | 測試共用的 `RecordingMemoryCache`（原本只在 `CachedBestsellerReaderTests` 內，抽出後兩個測試類別共用） |
| `tests/UnitTests/CachedBestsellerReaderTests.cs` | 修改 | 移除重複的 `RecordingMemoryCache`，改用共用 helper；測試行為不變 |
| `tests/UnitTests/BookDetailContractTests.cs` | 新增 | 反射守門測試：`BookDetail*` 型別不得有名稱含 Description／TableOfContents 的屬性（BOOK-05） |
| `Docs/Implementation-Report/issue-9-book-detail.md` | 新增 | 本報告 |

未修改：view、controller、其他模組的檔案、規格文件。

### 實作思路

- **Contract 與 BOOK-05**：`BookDetail` 的建構參數沒有 description 與 table of contents。`EfBookDetailReader` 以 `Select` 投影 Book 的其餘欄位，不載入整個 entity，因此這兩欄也不會從資料庫讀出。
- **查詢次數**：書本一筆、貢獻者、ISBN、分類、來源各一次，皆以 `book_id` 過濾，`AsNoTracking`。
- **排序**
  - 貢獻者：`contributor_order`。
  - ISBN：只取 `ISBN_13`、`ISBN_10`；ISBN_13 排在前，其次依值（ordinal）排序。`OTHER` 不進入結果。
  - 分類：`Distinct` 後以 `StringComparer.Ordinal` 在記憶體排序，不依賴資料庫 collation。
  - 來源：`first_seen_at`，同時間再依 `id`。
- **快取**：`CachedBookDetailReader` 不使用 `GetOrCreateAsync`，改為 `TryGetValue` 後才呼叫內層並以 `Set` 寫入，因此 `null`（Book 不存在）不會被寫入快取；crawler 之後新增的 Book 可以立即被讀到。Library 狀態不屬於 `BookDetail`，快取內沒有使用者相關資料。
- **DI**：與 `EfBestsellerReader` ／ `CachedBestsellerReader` 相同的註冊方式。`AddMemoryCache()` 已由 Bestseller 區塊呼叫，這裡不重複。

### 執行紀錄（Log）

1. 先寫測試（TDD red）：`dotnet test tests/UnitTests` 因 `Application/Catalog` 型別不存在而編譯失敗：

   ```text
   CachedBookDetailReaderTests.cs(73,20): error CS0246: The type or namespace name 'BookDetail' could not be found
   BookDetailContractTests.cs(1,31): error CS0234: The type or namespace name 'Catalog' does not exist in the namespace 'Book_Finder.Application'
   ```

2. 實作 Application port 與 record、Infrastructure 的 EF reader 與快取、Program.cs 註冊。
3. 執行 `dotnet build` 與 `dotnet test tests/UnitTests`（綠燈）。
4. 單獨執行新測試，5 個皆通過：

   ```text
   Passed UnitTests.BookDetailContractTests.Book_detail_types_have_no_description_or_table_of_contents_property [10 ms]
   Passed UnitTests.CachedBookDetailReaderTests.Missing_book_is_not_cached_so_a_later_read_reaches_the_inner_reader_again [10 ms]
   Passed UnitTests.CachedBookDetailReaderTests.Different_book_ids_are_cached_separately [1 ms]
   Passed UnitTests.CachedBookDetailReaderTests.Inner_reader_is_called_once_while_the_book_is_cached [2 ms]
   Passed UnitTests.CachedBookDetailReaderTests.Existing_book_is_cached_for_ten_minutes [4 ms]
   ```

5. `git diff --check` 無輸出（通過）。
6. Code review 修正後（見「Code Review 與修正」）重新執行建置與單元測試：

   ```text
       0 Error(s)
       0 Warning(s)
   Passed!  - Failed:     0, Passed:    14, Skipped:     0, Total:    14, Duration: 35 ms - UnitTests.dll (net10.0)
   ```

### 驗證結果（逐條對照需求）

| 需求 | 驗證方式 | 結果 |
|---|---|---|
| `BookDetail` 不含 description／table of contents（BOOK-05、§4） | `BookDetailContractTests`（反射，涵蓋 namespace 內所有 `BookDetail*` 型別）；`EfBookDetailReader` 投影不含這兩欄 | 通過 |
| 找不到 Book 回傳 `null` | 程式碼（`FirstOrDefaultAsync` 為 `null` 時回傳 `null`）；快取測試中以 `null` inner 驗證 | 通過（快取層）；EF 層待 M5 HTTP 驗證 |
| 快取 TTL 10 分鐘（§5） | `Existing_book_is_cached_for_ten_minutes` | 通過 |
| 快取以 Book id 分開 | `Different_book_ids_are_cached_separately` | 通過 |
| 快取命中時不再呼叫 inner | `Inner_reader_is_called_once_while_the_book_is_cached` | 通過 |
| `null` 不快取（crawler 之後新增的 Book 可立即讀到） | `Missing_book_is_not_cached_so_a_later_read_reaches_the_inner_reader_again` | 通過 |
| 貢獻者依 `contributor_order` | 程式碼排序；EF 查詢未在此模組執行 | 待 M5 驗證 |
| ISBN 只含 ISBN_13／ISBN_10，ISBN_13 優先 | 程式碼過濾與排序；EF 查詢未在此模組執行 | 待 M5 驗證 |
| 分類 distinct、ordinal 排序 | 程式碼；EF 查詢未在此模組執行 | 待 M5 驗證 |
| 來源依 `first_seen_at`、再依 `id` | 程式碼；EF 查詢未在此模組執行 | 待 M5 驗證 |
| 建置 0 warnings／0 errors | `dotnet build` | 通過（見下方） |
| Unit tests 全數通過 | `dotnet test tests/UnitTests` | 通過（見下方） |

建置與測試結果（code review 修正後的最終執行，WSL，`dotnet build` 於 solution 根目錄；測試總數 14，其中本模組新增 5 個）：

```text
    0 Error(s)
    0 Warning(s)
Passed!  - Failed:     0, Passed:    14, Skipped:     0, Total:    14, Duration: 35 ms - UnitTests.dll (net10.0)
```

### Code Review 與修正

Coordinator 的 code review 沒有阻擋性問題；EF 查詢已由 reviewer 對暫時的 PostgreSQL 驗證。依建議做以下修正（另起一個 commit，未 amend）：

1. `EfBookDetailReader` 註解：原本寫「排序在此完成、非資料庫」不正確。實際上貢獻者與來源在 SQL 排序；ISBN 與分類在記憶體排序（ISBN-13 優先；分類需要不受 DB collation 影響的 ordinal 排序）。
2. `CachedBookDetailReader`：改用泛型 `cache.TryGetValue<BookDetail>`，key 前綴改為 `private const string KeyPrefix`。仍採 `TryGetValue`＋`Set`，不使用 `GetOrCreateAsync`（後者會快取 `null`）。
3. `BookDetail` 的註解改用領域用語，不再使用 `contributor_order`、`first_seen_at` 等欄位名；語意不變。
4. `BookDetailContractTests`：`Assert.Equal(4, ...)` 加註解，說明這是刻意的 tripwire，新增 `BookDetail*` 型別時必須有意識地更新守門測試。
5. `RecordingMemoryCache` 抽成共用測試 helper `tests/UnitTests/RecordingMemoryCache.cs`，`CachedBookDetailReaderTests` 與 `CachedBestsellerReaderTests` 共用；行為不變。
6. 本報告補充排序與快取規則的來源（見「規格」），並新增本節與測試數字的更新。

**M5 必須明確斷言**（目前 repo 內的單元測試未涵蓋 EF 排序）：

- ISBN 順序：ISBN-13 在 ISBN-10 之前，`OTHER` 類型的 identifier 不顯示。
- 來源順序：依 `first_seen_at`，同時間再依 `id`。

### 未解決事項

- **EF 查詢的 repo 內測試**：本模組依指示未新增 DB 測試。`EfBookDetailReader` 的 SQL 翻譯與排序雖已由 reviewer 以暫時 PostgreSQL 驗證，repo 內仍無對應的自動化測試；M5 的 WebIntegration 透過 `/books/{id}` 驗證時，須依上節明確斷言 ISBN 與來源順序。
- **Program.cs 的 DI 解析**：單元測試未涵蓋；M5 的 WebApplicationFactory 測試會實際解析 `IBookDetailReader`。
- **§8 分類層級順序**：屬進階目標，MVP 依分類文字排序，未實作。
- **快取為 process-local**：多實例部署時各自快取，與 Bestseller 相同限制；TTL 10 分鐘內 Book 更新可能延遲可見。

## M5 Book 詳細頁

### 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `Controllers/BooksController.cs` | 新增 | `[HttpGet("/books/{id}")]`；非 GUID 或查無 Book 時回 404 與「找不到這本書」頁 |
| `Models/BookDetailViewModel.cs` | 新增 | `BookDetailViewModel.From(BookDetail)`，產出可直接顯示的標題、副標、封面、貢獻者行、資訊列與連結；不含 description／table of contents；另含 `BookInfoRow`、`BookLink` 兩個 record |
| `Views/Books/Detail.cshtml` | 新增 | 封面（或「無封面」）、書名 `<h1>`、副標、貢獻者行、資訊列（`<dl>`）、外部連結按鈕、空的 `<section id="library">` |
| `Views/Books/NotFound.cshtml` | 新增 | 404 頁：「找不到這本書」與回首頁連結 |
| `tests/WebIntegration/BookDetailPageTests.cs` | 新增 | 32 個 HTTP 層測試（含 Theory 案例） |
| `tests/WebIntegration/HtmlPage.cs` | 修改 | 新增 `GetRawAsync`、`PageTitle`、`BookArticle`、`InfoRows`／`InfoValue`、`ExternalLinks`（以 `RenderedLink` record 解析連結）等 helper，皆以 `[GeneratedRegex]` 實作 |
| `tests/WebIntegration/CatalogSeed.cs` | 修改 | `SourceSeed` 新增選用參數 `DateTime? FirstSeenAt = null`；`AddBooksAsync` 以 `source.FirstSeenAt ?? now` 寫入 `first_seen_at`（預設行為不變） |
| `Docs/Implementation-Report/issue-9-book-detail.md` | 修改 | 本節 |

未修改 `Program.cs`：M4 已註冊 `IBookDetailReader`（以 `CachedBookDetailReader` 包裝），控制器直接依賴該介面。

### 實作思路

- **路由與 404**：`/books/{id}` 以 attribute route 掛在 `BooksController`，`id` 以字串接收，先以 `Guid.TryParse` 判斷；非 GUID 與查無資料都走同一個 404 路徑（`Response.StatusCode = 404` 再回傳 `NotFound` view），不呼叫 DB 的非法值不會造成 500。
- **Contract（BOOK-05）**：`BookDetailViewModel` 只有書名、副標、封面、貢獻者行、資訊列、連結六類屬性，沒有 description／table of contents。控制器只把 `BookDetail` 轉成 view model，不把 `BookDetail` 直接交給 view。
- **貢獻者**：`ContributorDisplay.GroupByRole` 把 `BookDetailContributor` 映射為 `ContributorName` 後分組，顯示 `ContributorGroup.Text`（例「作者：甲、丙」）。
- **出版日期**：`PublishedDateText.Format`，精度由資料決定，不補日期。
- **ISBN**：每個 `BookDetailIdentifier` 一列，標籤依型別為 `ISBN-13`／`ISBN-10`；`OTHER` 不產生列。順序由 M4 reader 保證（ISBN-13 在前）。
- **分類**：reader 已 distinct＋ordinal 排序，view model 以「、」連接。
- **缺值**：`Optional()` 把空白字串視為缺值；資訊列只在有值時加入，因此沒有空標籤、也沒有「—」。分類先濾掉空白字串，若沒有剩下任何分類則整列不顯示。
- **封面**：`ThumbnailUrl` 不是絕對 `http`／`https` URL 時視為缺值，顯示「無封面」，不輸出 `<img>`。
- **連結**（book-catalog.md §4.1）：
  - 只有絕對 `http`／`https` 的 Book Source 會產生連結；其他網址（例如 `javascript:`、相對路徑）整個略過。
  - 有博客來來源：第一個合格的博客來來源（reader 順序，即 `first_seen_at` 再 `id`）為主要按鈕「在博客來查看完整介紹」；其餘博客來為次要「在博客來查看」；Google Books 一律次要「在 Google Books 查看」。
  - 只有 Google Books（或博客來來源都不合格）：第一個合格的 Google Books 為主要按鈕，其餘次要。
  - 沒有來源：沒有連結。
  - 所有外部連結 `target="_blank" rel="noopener noreferrer"`。
- **頁面標題**：`ViewData["Title"]` 在 view 內設定（`Detail.cshtml` 為書名，`NotFound.cshtml` 為「找不到這本書」），與既有 `Bestsellers/Index.cshtml` 一致；控制器不再設定。
- **Library 區塊**：`<section id="library"></section>`，無內容。
- **快取**：詳細頁讀取走 `CachedBookDetailReader`（M4）。本模組的 HTTP 測試只證明「同一 app instance 內第二次請求由快取提供」；10 分鐘 TTL 本身由 M4 的 `CachedBookDetailReaderTests` 斷言。

### 執行紀錄（Log）

1. 先寫測試（TDD red）：`BookDetailPageTests` 20 個與既有 `CatalogSeedTests` 6 個一起執行，先因 `DbSet<Book>.SingleAsync` 缺 `using Microsoft.EntityFrameworkCore` 編譯失敗，補 using 後：

   ```text
   Failed!  - Failed:    20, Passed:     6, Skipped:     0, Total:    26, Duration: 1 s - WebIntegration.dll (net10.0)
   ```

   失敗的 20 個皆為 `BookDetailPageTests`（路由不存在，頁面回 404）；`CatalogSeedTests` 6 個通過，代表 `FirstSeenAt` 選用參數不破壞既有行為。
2. 實作 `BooksController`、`BookDetailViewModel`、`Detail.cshtml`、`NotFound.cshtml`，並在 `CatalogSeed` 加入 `FirstSeenAt`。
3. 綠燈：同一組測試 `Passed!  - Failed:     0, Passed:    26, Skipped:     0, Total:    26`。
4. 全部執行（見下方「驗證結果」）；`git diff --check` 無輸出。
5. 程式碼 commit `b4d2aaf`（Add Book detail page at /books/{id}）。
6. Code review 修正（見下節）。先寫測試（TDD red）：新增與調整 `BookDetailPageTests` 後，`WebIntegration` 執行 `Failed!  - Failed:    10, Passed:    28, Skipped:     0, Total:    38`；失敗者為不安全網址（`javascript:`、相對路徑、`ftp:`、`//`）的來源與封面、空白分類，以及「第一個來源不安全時應改用下一個合格來源」的案例。
7. 實作：`BookDetailViewModel` 只保留 http／https 的來源與封面、濾掉空白分類、以 switch 對應 ISBN 型別；`ViewData["Title"]` 移到 view；`HtmlPage` 新增解析 helper。綠燈後 `WebIntegration` 為 `Passed!  - Failed:     0, Passed:    52, Skipped:     0, Total:    52`。
8. 程式碼 commit `668d0fb`（Address M5 code review: safe links, blank subjects, titles, test helpers）。

### 驗證結果（逐條對照需求）

Issue #9 驗收條件：

| 需求 | 測試 | 結果 |
|---|---|---|
| 基本書目欄位正確顯示（書名、副標、作者、出版社、日期、頁數、封面） | `Basic_fields_are_rendered` | 通過 |
| 有簡介與目錄的書，HTML 不出現其文字（以特徵字串斷言） | `Description_and_table_of_contents_are_never_rendered` | 通過 |
| 有博客來來源 → 「在博客來查看完整介紹」主要按鈕，連到 `source_url` | `Books_com_tw_source_is_a_primary_button_to_its_source_url` | 通過 |
| 博客來＋Google Books → 兩個連結（博客來為主要） | `Books_com_tw_and_google_books_sources_show_two_links_with_books_com_tw_primary` | 通過 |
| 只有 Google Books → Google Books 連結為主要按鈕 | `Google_books_only_book_has_its_google_books_link_as_the_primary_button` | 通過 |
| 只有年份的出版日期只顯示年份 | `Published_date_is_shown_at_its_stored_precision`（Year 案例，`2011`） | 通過 |
| 不存在的 id 回傳 404 | `Unknown_book_id_returns_404_with_not_found_message` | 通過 |
| 以 HTTP 層測試；`dotnet test` 通過 | 本模組全部測試（WebIntegration） | 通過 |

明確規則（任務指定）：

| 規則 | 測試 | 結果 |
|---|---|---|
| 年月精度顯示 `2011-03`、日精度 `2011-03-15` | `Published_date_is_shown_at_its_stored_precision`（Month、Day 案例） | 通過 |
| 貢獻者依角色分組，角色依首次出現的 `contributor_order`；組內依順序、「、」連接 | `Contributors_are_grouped_by_role_in_first_appearance_order` | 通過 |
| ISBN-13 在 ISBN-10 之前；`OTHER` 值不顯示（M4 未解決事項） | `Isbn_13_is_shown_before_isbn_10_and_other_identifiers_are_not_shown` | 通過 |
| 分類依 ordinal 排序、distinct、「、」連接（M4 未解決事項） | `Subjects_are_distinct_in_ordinal_order_and_joined_with_a_dunhao` | 通過 |
| 缺值欄位整列不顯示（無 `<dt>`、`<dd>`、副標 class），顯示「無封面」 | `Book_with_only_a_title_renders_no_optional_rows_and_shows_the_cover_placeholder` | 通過 |
| 兩個博客來來源：`first_seen_at` 較早者為主要按鈕，較晚者為次要「在博客來查看」（測試刻意把較晚來源先插入） | `Earlier_seen_books_com_tw_source_is_primary_and_later_one_is_secondary` | 通過 |
| 非 GUID id（`/books/abc`、`/books/123`）回傳 404 | `Id_that_is_not_a_guid_returns_404`（2 案例） | 通過 |
| `<section id="library">` 存在 | `Page_has_an_empty_library_placeholder_section` | 通過 |
| 快取：同一 app instance 內第二次請求由快取提供（首次請求後改書名，頁面不變）。10 分鐘 TTL 本身由 M4 的 `CachedBookDetailReaderTests` 斷言 | `Second_request_within_one_app_instance_is_served_from_the_cache` | 通過 |
| 外部連結皆 `target="_blank" rel="noopener noreferrer"` | `Every_external_link_opens_in_a_new_tab_with_noopener` | 通過 |
| 沒有來源的書沒有連結 | `Book_without_sources_has_no_external_links` | 通過 |
| `CatalogSeedTests` 維持綠燈（`FirstSeenAt` 不破壞既有行為） | `tests/WebIntegration` 的 `CatalogSeedTests`（6 個） | 通過 |

Code review 修正新增的需求對照：

| 需求 | 測試 | 結果 |
|---|---|---|
| 只接受絕對 http／https 的來源網址；`javascript:`、相對路徑、`ftp:` 不產生連結（spec §4.1） | `Books_com_tw_source_with_an_unsafe_url_gets_no_link`（3 案例） | 通過 |
| 最早的博客來來源不安全時略過，主要按鈕改為下一個合格來源，且 `javascript:` 不出現在 HTML | `Unsafe_earliest_books_com_tw_source_is_skipped_and_the_next_safe_one_is_primary` | 通過 |
| 博客來來源都不合格時，合格的 Google Books 來源為主要按鈕 | `Unsafe_books_com_tw_source_falls_back_to_a_safe_google_books_primary` | 通過 |
| 封面不是絕對 http／https 網址時視為缺值，顯示「無封面」、不輸出 `<img>` | `Thumbnail_that_is_not_an_absolute_http_url_is_treated_as_missing`（3 案例） | 通過 |
| 只有空白分類時不顯示分類列 | `Blank_subject_is_ignored_and_the_subjects_row_is_omitted_when_none_remain`（2 案例） | 通過 |
| 詳細頁 `<title>` 為「書名 - 好想找書」 | `Detail_page_title_is_the_book_title` | 通過 |
| 404 頁 `<title>` 為「找不到這本書 - 好想找書」 | `Not_found_page_title_is_the_not_found_message` | 通過 |
| 博客來＋Google Books 恰好兩個外部連結，順序為博客來主要、Google Books 次要 | `Books_com_tw_and_google_books_sources_render_exactly_two_links_with_books_com_tw_primary` | 通過 |
| 只有 Google Books 的書，同時斷言簡介／目錄標記不出現（PRD BOOK-05） | `Google_books_only_book_has_its_google_books_link_as_the_primary_button_and_hides_description_and_toc` | 通過 |

M4 Code Review 指定的「必須明確斷言」（ISBN 順序、OTHER 不顯示、來源順序依 `first_seen_at`）已分別由上表的 ISBN、兩個博客來來源測試覆蓋，EF 查詢現在由 HTTP 測試在 repo 內實際執行（M4 時僅有 reviewer 的暫時 PostgreSQL 驗證）。

建置與測試（WSL，`dotnet build` 於根目錄，`dotnet test` 逐一執行三個專案）：

```text
    0 Warning(s)
    0 Error(s)
Passed!  - Failed:     0, Passed:    36, Skipped:     0, Total:    36, Duration: 42 ms - UnitTests.dll (net10.0)
Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - DatabaseIntegration.dll (net10.0)
Passed!  - Failed:     0, Passed:    52, Skipped:     0, Total:    52, Duration: 4 s - WebIntegration.dll (net10.0)
```

`dotnet build tests/WebIntegration --no-incremental` 與 `dotnet build tests/UnitTests --no-incremental` 亦為 0 warnings、0 errors。WebIntegration 的 52 個測試為：既有 14 個、`CatalogSeedTests` 6 個、本模組 `BookDetailPageTests` 32 個。

### Code Review 與修正

Coordinator 的 code review 沒有阻擋性問題，所有 issue #9 驗收條件皆有測試覆蓋。依 review 意見做以下修正（新增 commit，未 amend）：

1. **安全性（spec §4.1）**：外部連結只接受絕對 `http`／`https` URL。不合格的來源整個略過，主要按鈕改由下一個合格的博客來來源擔任；沒有合格的博客來來源時，由合格的 Google Books 來源擔任。`javascript:` 不會出現在 HTML 中。
2. **封面**：`ThumbnailUrl` 不是絕對 `http`／`https` URL 時視為缺值，顯示「無封面」。
3. **分類**：空白字串不納入分類；若沒有剩下任何分類，分類列不顯示。
4. **頁面標題**：`ViewData["Title"]` 改在 view 設定（`Detail.cshtml` 為書名、`NotFound.cshtml` 為「找不到這本書」），與既有頁面一致；控制器移除該設定。新增測試斷言 `<title>`。
5. **ISBN 對應**：`IdentifierType` 以 exhaustive switch 對應 `ISBN-13`／`ISBN-10`，其他型別丟出 `InvalidOperationException`（reader 已過濾 OTHER，因此不應發生）。
6. **測試 helper**：`GetRawAsync`、`PageTitle`、`BookArticle`、`InfoRows`／`InfoValue`、`ExternalLinks` 移入 `tests/WebIntegration/HtmlPage.cs`，皆以 `[GeneratedRegex]` 實作。連結斷言改為比對解析後的 `RenderedLink`（href、class、文字、target、rel），不再比對整段 `<a ...>` 字串。「不顯示空列」的斷言範圍限定在詳細頁的 `<article>`，不再掃描整頁（版面可能含有 `<dt` 或「—」）。
7. **測試補強**：
   - 詳細頁與 404 頁的 `<title>`；
   - 博客來＋Google Books 恰好兩個外部連結（完整列表比對）；
   - 只有 Google Books 的書同時斷言簡介與目錄標記不出現（PRD BOOK 驗收情境）；
   - 不安全網址、不安全封面、空白分類的案例。
8. **快取敘述更正**：HTTP 測試只證明「同一 app instance 內第二次請求由快取提供」；10 分鐘 TTL 本身由 M4 的 `CachedBookDetailReaderTests` 斷言。測試名稱改為 `Second_request_within_one_app_instance_is_served_from_the_cache`。
9. **M4 標頭註記**：已更新為本分支已 rebase 到 main、spec 為更新版。

### 未解決事項

- **瀏覽器視覺檢查未做**：驗證以 HTTP 層測試（HTML 內容與屬性）為主，未以瀏覽器實際檢視版面（封面比例、按鈕換行）。
- **多個相同類型 ISBN**：`BookDetailViewModel` 每個 identifier 各產生一列；資料模型假設同一 Book 每種 ISBN 型別通常只有一個，若未來出現多個，會全部列出，這是有意的選擇而非規格明定。
- **未知 `SourceType`**：目前 enum 只有 `BooksComTw` 與 `GoogleBooks`，連結邏輯以這兩者過濾；若日後新增來源類型，需同步更新 `BookDetailViewModel.LinksOf`，否則該來源不會產生連結（規格要求每個來源一個連結，這點需在新增來源時一併處理）。
- **§8 分類層級順序**：仍為進階目標，MVP 依分類文字排序。
- **`Docs/modules/book-catalog.md` 狀態**：已解決。本分支已 rebase 到 main，`book-catalog.md` 為更新版（含 §4.1、使用者 2026-10-11 決定，以及 `5eb6e9c` 新增的 http／https 連結規則）；本模組依此實作。
