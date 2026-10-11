# Issue #9 Book 詳細頁：實作報告

- Issue：#9 Book 詳細頁（BOOK-01～05）
- Branch：`issue-9-book-detail`（from `main`）
- 規格：`Docs/modules/book-catalog.md` §4、§4.1、§5（catalog-display-rules 分支的更新版，含使用者 2026-10-11 決定）；`Docs/requirements/product-requirements.md` BOOK-01～05；`AGENTS.md` §1.3「Book 內容顯示」
- 排序與快取規則的來源：使用者 2026-10-11 的決定記錄於 `catalog-display-rules` 分支的 `Docs/modules/book-catalog.md` §4.1 與 §5。該分支尚未進入 main；主 session 會把它合併到 main，並在 M5 前將本分支 rebase 到 main，屆時本分支的文件與程式一致。在此之前，本分支的 `Docs/modules/book-catalog.md` 仍是舊版，本報告的規則以上述更新版為準。
- 日期：2026-10-11

本檔為 issue #9 的實作紀錄，各模組依序以「## Mx ...」新增章節。本節為 M4。

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
