# Issue #9 Book 詳細頁：實作報告

- Issue：#9 Book 詳細頁（BOOK-01～05）
- Branch：`issue-9-book-detail`（from `main`）
- 規格：`Docs/modules/book-catalog.md` §4、§4.1、§5（catalog-display-rules 分支的更新版，含使用者 2026-10-11 決定）；`Docs/requirements/product-requirements.md` BOOK-01～05；`AGENTS.md` §1.3「Book 內容顯示」
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

建置與測試結果（WSL，`dotnet build` 於 solution 根目錄）：

```text
    0 Error(s)
    0 Warning(s)
Passed!  - Failed:     0, Passed:    14, Skipped:     0, Total:    14, Duration: 38 ms - UnitTests.dll (net10.0)
```

### 未解決事項

- **EF 查詢未在資料庫上執行**：本模組依指示未新增 DB 測試。`EfBookDetailReader` 的 SQL 翻譯（enum 比較、`Distinct`、投影到 record 建構子）尚未實際對 PostgreSQL 執行；需由 M5 以 WebIntegration 透過 `/books/{id}` 驗證。
- **Program.cs 的 DI 解析**：單元測試未涵蓋；M5 的 WebApplicationFactory 測試會實際解析 `IBookDetailReader`。
- **§8 分類層級順序**：屬進階目標，MVP 依分類文字排序，未實作。
- **快取為 process-local**：多實例部署時各自快取，與 Bestseller 相同限制；TTL 10 分鐘內 Book 更新可能延遲可見。
