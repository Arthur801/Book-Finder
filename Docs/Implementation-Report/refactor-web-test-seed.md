# 重構實作報告：WebIntegration 的 Catalog seed

- 來源：2026-10-11 架構檢視的候選 5「共用一個 disposable PostgreSQL 測試 module」，grilling 後依使用者決定縮小範圍
- Issue：無（測試輔助程式整理，使用者決定不開 issue）
- Branch：直接在 `main`（使用者決定）
- 實作：主 session 以 TDD 直接實作
- 日期：2026-10-11

## 背景

Web 票 #8（一般搜尋）、#9（Book 詳細頁）、#10（註冊登入）都會在 `tests/WebIntegration` 寫 HTTP 層測試，但原本的 `BestsellerSeed` 只能種「書名 + 一個博客來來源 + 貢獻者 + 排名」：

- 搜尋需要 ISBN、出版社、出版日期與精度、同名的書。
- 詳細頁需要多個來源（含只有 Google Books 的書）、分類、頁數、簡介與目錄（用來斷言頁面不顯示）。
- `ResetCatalogAsync` 只刪 Bestseller 與 Book，#10 之後的 User、Library Entry 不在隔離範圍內。

架構報告原本提議抽出共用測試專案。核對後發現兩個 C# fixture 實際重複的只有約 12 行，`DatabaseIntegration` 也不需要種 Catalog 資料；deletion test 顯示共用專案只是搬移複雜度，所以範圍改為只深化 `WebIntegration` 內的 seed。

## 設計決定（使用者逐題確認）

| # | 決定 |
|---|---|
| Q1 | 不新增共用測試專案；接受兩個 fixture 約 12 行的重複，`DatabaseIntegration` 不動；只在 `WebIntegration` 深化 Catalog seed |
| Q2 | 一個 `CatalogSeed` module：`BookSeed` 描述完整 Book（全欄位有預設），「上暢銷榜」是另一個操作 |
| Q3 | `ResetCatalogAsync` 改為 `ResetDatabaseAsync`，清空所有應用程式資料表（排除 `__EFMigrationsHistory`） |
| Q4 | 主 session TDD 實作、雙軸 review、commit 在 `main`；報告為本檔 |
| Q5 | 刪除 `BestsellerSeed`，`BestsellerPageTests` 全部改用 `CatalogSeed`；「書名 N」捷徑搬進 `CatalogSeed` |
| Q6 | interface：`AddBooksAsync` → `SeededBook`（Book id 與各來源 id／URL）、`AddBestsellersAsync`（用博客來來源上榜，沒有則拋錯）、`AddRankedBooksAsync` |
| Q7 | 沒給 `Sources` 時預設一個博客來來源；空清單代表沒有來源 |
| Q8 | 新增少量 `CatalogSeedTests` |
| 實作細節 | reset 以 `information_schema` 動態列出 `public` 的資料表，一次 `TRUNCATE … CASCADE`（主 session 決定） |

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `tests/WebIntegration/CatalogSeed.cs` | 新增 | `BookSeed`、`IdentifierSeed`、`ContributorSeed`、`SubjectSeed`、`SourceSeed`、`SeededBook`、`SeededSource`；`CatalogSeed.AddBooksAsync`／`AddBestsellersAsync`／`AddRankedBooksAsync`、`CapturedAt` |
| `tests/WebIntegration/CatalogSeedTests.cs` | 新增 | seed 本身的 6 個測試 |
| `tests/WebIntegration/WebFixture.cs` | 修改 | `ResetCatalogAsync` → `ResetDatabaseAsync`；新增 `QuoteIdentifier` |
| `tests/WebIntegration/BestsellerPageTests.cs` | 修改 | 改用 `CatalogSeed` 與 `ResetDatabaseAsync`；斷言不變 |
| `tests/WebIntegration/LayoutAndHomeTests.cs` | 修改 | 改用 `ResetDatabaseAsync` |
| `tests/WebIntegration/BestsellerSeed.cs` | 刪除 | 由 `CatalogSeed` 取代 |

沒有變更產品程式碼、`DatabaseIntegration`、規格文件（`test-plan.md` 未提及 seed 或 reset）。

## 實作思路

- **interface 小、規則在內部**：測試只需要知道三個操作與 seed records。Book 的寫入、預設來源、來源 URL 的唯一性、「上榜必須有博客來來源」都在 `CatalogSeed` 內。
- **預設來源 URL**：由來源自己的 id 產生（Google Books 優先用 `ExternalId`），所以同一本書有兩個同類型來源也不會撞上 `UNIQUE(source_type, source_url)`。
- **reset**：資料表名稱無法作為 SQL 參數，因此從 `information_schema` 取得後以 `QuoteIdentifier` 轉成 identifier 再組字串；也因此沒有產生 EF1002 警告，build 維持 0 warning。
- **seed 不檢查的規則**：`PublishedDate` 與 precision 必須成對、ISBN 跨 Book 唯一，這兩條由測試作者遵守，已寫在 `BookSeed` 的註解。

## 執行紀錄（Log）

1. 讀兩個 fixture、`BestsellerSeed`、三個測試專案與 Catalog entity／EF 設定；發現重複只有約 12 行，提出縮小範圍。
2. 兩輪 grilling（Q1～Q8），使用者全部採用建議。
3. 先寫 `CatalogSeedTests`（紅：編譯錯誤，型別不存在），再實作 `CatalogSeed.cs` 與 `ResetDatabaseAsync` → WebIntegration 19 passed，但多了兩個 EF1002 警告。
4. 改為先 quote identifier 再組字串，警告消失。
5. 遷移 `BestsellerPageTests`、`LayoutAndHomeTests`，刪除 `BestsellerSeed.cs`。
6. 雙軸 code review（見下節），修正後重跑。

## 驗證結果

- `dotnet build`：0 Warning(s)、0 Error(s)。
- `dotnet test`：UnitTests 9、DatabaseIntegration 12、WebIntegration 20，全部通過（Testcontainers 的 disposable PostgreSQL，不碰開發或正式資料庫）。
- `git diff --check` 通過。

| 設計要求 | 結果 | 對應測試 |
|---|---|---|
| 完整 `BookSeed` 的所有欄位與關聯（含 identifier 類型、貢獻者順序與角色、分類來源類型、來源 id／URL）都正確寫入並回傳 | ✅ | `A_fully_specified_book_is_written_with_every_field_and_relation` |
| 沒給來源 → 一個博客來來源；空清單 → 沒有來源 | ✅ | `Without_sources_a_book_gets_one_books_com_tw_source_and_an_empty_list_means_none` |
| 同一本書的同類型來源 URL 不重複 | ✅ | `Sources_of_the_same_type_on_one_book_get_distinct_urls` |
| 沒有博客來來源的書不能上榜 | ✅ | `A_bestseller_needs_a_books_com_tw_source` |
| 「書名 N」捷徑：排名、標題、指向博客來來源、`CapturedAt` | ✅ | `Ranked_books_are_titled_by_rank_and_point_at_their_books_com_tw_source` |
| reset 清空所有應用程式資料表（含 Catalog 以外的 users），保留 migration 紀錄 | ✅ | `Reset_empties_every_application_table_but_keeps_the_migration_history` |
| Bestseller 與 layout 測試的斷言不變 | ✅ | `BestsellerPageTests`（10）、`LayoutAndHomeTests`（4） |

## Code Review 與修正

雙軸審查（Standards、Spec）平行執行；主 session 逐條核對後處理。

| 軸 | 發現 | 處理 |
|---|---|---|
| Spec | 預設 URL 由 Book id 產生，同一本書兩個同類型來源會違反 `UNIQUE(source_type, source_url)`；#9「每個 Book Source 一個連結」會用到這種資料 | 改由來源自己的 id 產生；新增測試先紅後綠 |
| Spec | reset 測試開頭沒有先 reset，依賴測試執行順序 | 測試開頭先 reset |
| Spec | reset 測試只種 Catalog 資料，證明不了 Catalog 以外的表也被清空 | reset 前另外寫入一個 User |
| Spec | 完整欄位測試沒驗 identifier 類型、貢獻者順序與角色、分類來源類型 | 補上斷言 |
| Spec | seed 不檢查日期／精度成對與 ISBN 唯一 | `BookSeed` 註解寫明由測試作者遵守 |
| Spec | 測試數量多於設計的 2～3 個 | 保留：多出的測試涵蓋 Q7 的預設來源與「書名 N」捷徑 |
| Standards | `AddBestsellersAsync` 的參數名 `ranks` 不符內容（名次 → Book） | 改名 `bookByRank` |
| Standards | `(short)rank` 是未檢查的縮窄轉型 | 改為 `checked((short)rank)` |
| Standards | `ArgumentOutOfRangeException` 的 paramName 與傳入值不一致 | 改為傳入 `source` 本身 |
| Standards | 對 `Nullable<T>` 多餘的 `!.Value` | 改以 nullable tuple 型別比對 |
| Standards | `information_schema` 查詢在 fixture 與測試各一份；`QuoteIdentifier` 為 `internal` 給測試用 | 保留：測試刻意不重用受測程式的查詢；`internal` 的範圍很小 |

修正後重跑：build 0 warning；`dotnet test` 9／12／20 全部通過。

## 未解決事項

1. **兩個 C# fixture 約 12 行重複**：依 Q1 刻意保留。等 `DatabaseIntegration` 也需要種資料時，再抽成共用專案。
2. **seed 不檢查的資料規則**：日期與精度成對、ISBN 跨 Book 唯一，需由測試作者遵守（`BookSeed` 註解已寫明）。違反時會在 `SaveChangesAsync` 或後續斷言失敗，不會悄悄通過。
3. **舊實作報告**：`Docs/Implementation-Report/issue-5-bestseller-page.md` 仍提到 `BestsellerSeed` 與 `ResetCatalogAsync`，屬歷史紀錄，未修改。
