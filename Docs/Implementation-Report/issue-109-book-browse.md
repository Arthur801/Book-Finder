# Issue #109：書庫瀏覽取代暢銷榜 Web 頁面

## 背景

- 博客來 production 爬取因 EC2 IP 被阻擋而停用（`CRAWLER_ENABLED=false`），暢銷榜資料不再更新，Web 上的暢銷榜頁面失去實用性。
- 2026-10-24 使用者決定：暫停暢銷榜 Web 呈現，改以「書庫」（Catalog 的全量瀏覽列表）取代首頁與導覽列的暢銷榜；`/bestsellers` 永久導向 `/books`。
- Bestseller 後端（service、reader、cache、資料表、crawler）保留不動；只移除 Web 頁面與首頁暢銷榜區塊。
- 本次沒有 schema 變更、沒有 JSON API 變更。
- 規格依據：`Docs/requirements/product-requirements.md` §3.8（BROWSE-01～04）與 §4 BROWSE 驗收條件；`Docs/modules/book-catalog.md` §3.6；`Docs/modules/bestseller.md`（Web Suspended）。

## 變更檔案

以下 commit hash 取自 `git log --oneline origin/main..HEAD`。

### M1：書庫後端（Application、Infrastructure、後端測試）

- `831fcee` feat(catalog): add BookBrowse use case and port for 書庫
  - `Application/Catalog/IBookBrowse.cs`、`BookBrowseService.cs`、`BookBrowsePage.cs`（新增）。
- `7c369fd` feat(catalog): implement EF book browse list and random sample
  - `Infrastructure/Persistence/EfBookBrowse.cs`（新增）；`Program.cs` 註冊 `IBookBrowse` 與 `BookBrowseService`（scoped）；`tests/WebIntegration/CatalogSeed.cs` 的 `BookSeed` 新增可選 `Id`。
- `b2c04ce` test(bestseller): guard retained Bestseller backend through DI
  - `tests/WebIntegration/BestsellerReaderIntegrationTests.cs`（新增）。
- `65a6c01` docs(catalog): record 書庫 browse backend in folder docs
  - `Application`、`Infrastructure`、`tests` 的資料夾文件。

### M2：Web 呈現與測試

- `59f5a31` docs(catalog): Bestseller loses its Web caller in M2, not M1
  - 更正 `Application/docs/backlog.md` 中「Bestseller 失去 Web 呼叫端」的時點（屬於 M2，不是 M1）。
- `a8a5077` feat(web): show 書庫 on home and /books in place of the bestseller ranking
  - `Controllers/BooksController.cs`（`/books`）、`BestsellersController.cs`（301）、`HomeController.cs`；`Models/BookBrowseViewModel.cs`、`BookListItemViewModel.cs`、`HomeViewModel.cs`（改）、`SearchResultsViewModel.cs`（與搜尋共用的列表項目）、`BestsellerListViewModel.cs`（刪除）；`Views/Books/Index.cshtml`、`Views/Shared/_BookList.cshtml`（新增）；`Views/Home/Index.cshtml`、`Views/Search/Index.cshtml`、`Views/Library/Index.cshtml`、`Views/Shared/_Layout.cshtml`（改）；`Views/Bestsellers/Index.cshtml`、`Views/Shared/_BestsellerEntries.cshtml`（刪除）；`Models/PageNumber.cs`（分頁參數解析共用）。
- `2642182` test(web): cover 書庫 paging, home sample and the /bestsellers redirect
  - 新增 `tests/WebIntegration/BookBrowsePageTests.cs`、`BookBrowseIntegrationTests.cs`、`tests/UnitTests/BookBrowseServiceTests.cs`、`BookBrowseViewModelTests.cs`；刪除 `BestsellerPageTests.cs`；`LayoutAndHomeTests.cs`、`LibraryPageTests.cs` 更新。
- `9c7dbf6` docs(web): record 書庫 Web presentation in folder docs
  - `Controllers`、`Models`、`Views`、`wwwroot`、`tests` 的資料夾文件。

### M3：規格同步、查詢計畫基準與報告

- `7c14b09` docs(browse): sync specs to 書庫 and suspended Bestseller Web
  - `Docs/requirements/product-requirements.md`（§2、§3.2 標記 Web Suspended、§3.8 BROWSE、§4 BROWSE 與 BEST 標記）、`Docs/modules/book-catalog.md`（§3.6 書庫瀏覽）、`Docs/modules/bestseller.md`（改寫為「後端保留、Web 暫停」）、`Docs/ui/ui-flow.md`、`Docs/modules/user-library.md`、`Docs/architecture/system-architecture.md`、`Docs/testing/test-plan.md`（§2.1）、`CONTEXT.md`、`Docs/deployment/deployment.md`、`deploy/README.md`。
- 本 commit（baseline 與報告）
  - `Docs/Implementation-Report/issue-109-book-browse.md`（新增）；`Infrastructure/docs/backlog.md`（INF-B06）、`Controllers/docs/backlog.md`（CTL-11）更新為量測結果；`Infrastructure/docs/update-history.md`、`Controllers/docs/update-history.md` 各追加一列。
- 未修改 `Docs/Implementation-Report/*`（本報告除外）與 `Docs/plans/*`。

## 實作思路

1. **書庫排序**：`published_date IS NOT NULL DESC, published_date DESC, id`。PostgreSQL 的 `DESC` 預設 NULL 排最前，因此先以「是否有值」排序，讓無日期的書排最後；`id` 作為穩定的 tie-breaker。
2. **分頁**：先 `COUNT`，再以 `Skip/Take` 取頁。頁碼以 `long` 計算 offset，極大整數不溢位；offset 已超出總筆數時不執行頁查詢。頁碼規則與一般搜尋相同（不合法或小於 1 視為第 1 頁，超過最後一頁 302 重導，空庫不重導），沿用 `PageNumber.Parse`。
3. **作者**：與一般搜尋共用 `BookAuthors.ByBookAsync`（只取 `AUTHOR`、依 `contributor_order`），一次查詢取得整頁作者，不逐本查詢。
4. **首頁樣本**：`ORDER BY random() LIMIT 10`，不快取，每次載入重抽。這是整表排序，成本見下方查詢計畫基準。
5. **`/bestsellers` 301**：使用 `RedirectPermanent("/books")`，保留舊連結。
6. **Bestseller 後端保留**：`BestsellerService`、`CachedBestsellerReader`、`EfBestsellerReader`、資料表與 crawler 不改。Web 端已無呼叫者，因此以 `BestsellerReaderIntegrationTests` 經 DI scope 驗證接線與讀取 contract。
7. **BOOK-05**：書庫列表的 view model 與 EF 投影都不包含 description 與 table of contents；`BookBrowsePageTests` 驗證 HTML 不含這兩者。
8. **不呼叫外部服務**：書庫與首頁樣本只查 Local DB；沒有 embedding、LLM 或 Google Books。

## 執行紀錄（Log）

1. 讀取 `AGENTS.md`、#109 規格與 M1/M2 的 commit diff（`git log -p origin/main..HEAD -- '*.cs' '*.cshtml'`）。
2. M3 Part A：修改 10 份規格文件（見 `7c14b09`），以 `grep -rn "暢銷榜\|/bestsellers\|榜單尚未建立" Docs CONTEXT.md deploy/README.md | grep -v -e Implementation-Report -e Docs/plans` 檢查，剩餘命中皆為 Bestseller 資料／crawler 描述或 Web Suspended 標記。
3. M3 Part B：以一支暫時性的 xUnit 測試（`tests/WebIntegration/TempBrowseSqlBaselineTests.cs`，未 commit，已刪除）啟用 EF Core 命令記錄（`EnableSensitiveDataLogging` + `LogTo`），取得 EF 實際產生的 SQL 與參數。該測試以 `fixture` 的容器字串連線（不輸出連線字串），以 `EfBookBrowse.cs` 與 `BookAuthors.cs` 相同的 LINQ 執行 COUNT、分頁、作者與隨機樣本，並將 SQL 寫到 scratchpad。
4. 以 `docker exec book-finder-db-1 psql -U book_finder_dev -d book_finder` 對開發資料庫執行 `EXPLAIN (ANALYZE, BUFFERS)`，每個查詢 3 次；只執行 SELECT，未執行任何寫入或 DDL。
5. 未停止或啟動任何 container，未觸碰 7083／5199／5223 埠；未讀取 `.env`。
6. 刪除暫時性測試後 `git status` 只剩未追蹤的 `.venv`（worktree 既有的符號連結，非本次產生）。

## 驗證結果

| 指令 | 結果 |
|---|---|
| `dotnet build Book-Finder.slnx` | 成功，0 warning、0 error |
| `dotnet format Book-Finder.slnx --verify-no-changes` | 通過（exit 0） |
| `dotnet test tests/UnitTests` | 728 passed，0 failed |
| `dotnet test tests/WebIntegration` | 277 passed，0 failed |
| `dotnet test tests/DatabaseIntegration` | 113 passed，0 failed |

測試以 Testcontainers 啟動 `pgvector/pgvector:0.8.7-pg17`，不連線開發或 production 資料庫。

## Query plan baseline

- 資料量：開發資料庫 `books` 2884 筆（有出版日期 2879、無出版日期 5）；`book_contributors` 6167 筆；`books` 表大小約 12 MB。
- SQL 來源：EF Core 實際產生的 SQL（由暫時性測試的命令記錄取得，非手寫等價 SQL）。參數以開發資料庫的實際值代入：page 1 為 `OFFSET 0`，最後一頁（第 145 頁）為 `OFFSET 2880`（`ceil(2884/20)=145`），樣本 `LIMIT 10`；作者查詢使用各頁實際的 book id。

### EF Core 產生的 SQL（參數已代入）

```sql
-- count
SELECT count(*)::int FROM books AS b;
-- page（LIMIT/OFFSET 依頁代入）
SELECT b.id, b.title, b.publisher, b.published_date, b.published_date_precision, b.thumbnail_url
FROM books AS b
ORDER BY b.published_date IS NOT NULL DESC, b.published_date DESC, b.id
LIMIT 20 OFFSET 0;   -- 最後一頁：OFFSET 2880
-- author（ids 為該頁的 book id）
SELECT b.book_id, b.name FROM book_contributors AS b
WHERE b.book_id = ANY (@ids) AND b.role = 'AUTHOR'
ORDER BY b.contributor_order;
-- sample
SELECT b.id, b.title, b.publisher, b.published_date, b.published_date_precision, b.thumbnail_url
FROM books AS b ORDER BY random() LIMIT 10;
```

### 計畫與執行時間（ms，3 次；括號內為 Planning Time 範圍）

| 查詢 | 計畫節點 | Execution Time（run 1 / 2 / 3） | 備註 |
|---|---|---|---|
| count | Index Only Scan on `IX_books_publisher` → Aggregate | 0.364 / 0.465 / 0.365 | planner 選用 publisher 索引做 index-only scan |
| page 1（OFFSET 0） | Seq Scan on books → Sort（top-N heapsort，約 37 kB）→ Limit | 1.684 / 1.733 / 1.786 | 整表 2884 列都要讀與比較 |
| 最後一頁（OFFSET 2880） | Seq Scan on books → Sort（quicksort，約 1119 kB）→ Limit | 3.503 / 3.719 / 3.352 | offset 大時 top-N 範圍接近全表，改為完整排序，回傳 4 列 |
| 作者（page 1 的 20 本） | Bitmap Index Scan on `PK_book_contributors` → Bitmap Heap Scan → Sort | 1.155 / 0.145 / 0.149 | 第 1 次較慢（快取暖機），之後穩定；回傳 33 列 |
| 作者（最後一頁的 4 本） | Bitmap Index Scan on `PK_book_contributors` → Sort | 0.201 / 0.055 / 0.061 | 這 4 本在開發資料中沒有 `AUTHOR` 角色，回傳 0 列 |
| 樣本（LIMIT 10） | Seq Scan on books → Sort（top-N heapsort，約 25–30 kB）→ Limit | 1.606 / 1.679 / 1.878 | 每列計算 random() 後取前 10 |

Planning Time 各查詢約 0.3–0.9 ms。所有 buffer 皆為 shared hit（資料已在快取中）。

### 觀察

- **多欄位 ORDER BY 不使用 `published_date` 單欄索引**：排序的第一個鍵是 `(published_date IS NOT NULL) DESC` 運算式，索引無法提供這個順序，計畫為 Seq Scan + Sort。`IX_books_published_date` 不在計畫中。
- 在目前的資料量（2884 筆）下，整頁查詢約 1.7–3.7 ms，遠低於一般網頁的回應預算；但成本隨筆數線性增加（每次都讀整表與排序）。
- 首頁樣本 `ORDER BY random()` 的成本與整表大小同階（約 1.7 ms），每次首頁載入都會執行一次。
- 作者查詢以 PK 前綴（`book_id`）定位，成本隨頁大小（20 本）而非總資料量增加。
- 無 SLO：`system-architecture.md` §168 未定義效能目標，本報告只記錄觀察，不設定門檻。

### 觸發條件

若資料量增長後整頁或樣本查詢成為瓶頸，另開效能最佳化 issue（例如為排序鍵建立表達式索引、或改寫隨機取樣）。本報告不預先決定方案。

## 上線關卡：本機併發壓測（2026-10-24）

使用者在 #111 review 指出：這組變更上線前的關卡是 DB 成本，合併時不檢查這一項。使用者選擇用本機併發壓測驗證，不對 production RDS 執行查詢。

- **環境**：
  - 程式：worktree `issue-109-m3-specs-report` 的 Release build（`bin/Release/net10.0/Book-Finder.dll`），在 `https://localhost:7183` 啟動。
  - 資料庫：本機開發庫 `book-finder-db-1`，2884 本書。這份資料就是匯入 RDS 的書籍目錄，資料量和分布都相同；不同的是機型和記憶體。
  - 關掉的背景工作：`Embedding__BackfillEnabled=false`、`AiProfile__Enabled=false`，不呼叫 OpenAI。
  - 機器：24 個 logical CPU。
  - TLS：以匯出的 dev 憑證公開部分驗證，沒有關閉驗證；用完後已刪除匯出檔。
- **工具**：scratchpad 裡的 Python stdlib 腳本，每個 thread 用一條 keep-alive 的 HTTPS 連線打固定次數的 GET，統計 200 回應的延遲。每個 request 的 DB CPU，是讀 DB container cgroup 的 `cpu.stat` `usage_usec` 在壓測前後的差值，除以 request 數。
- **事前檢查**：
  - `/` 有 10 本書，重新整理後換了一組。這只是觀察，不算 pass/fail。
  - `/books` 有 20 本，摘要是「共 2884 本，第 1／145 頁」。
  - `/books?page=145` 有 4 本。
  - `/books?page=999` 回 302，導向 `?page=145`。
  - `/bestsellers` 回 301，導向 `/books`。
  - app log 沒有 error 或 exception。

| 路徑 | 併發 | 請求數 | 錯誤 | p50 / p95 / p99（ms） | 吞吐（req/s） | DB CPU／請求 |
|---|---|---|---|---|---|---|
| `/`（首頁隨機 10 本） | 1 | 500 | 0 | 2.9 / 3.4 / 4.1 | 343 | 1.08 ms |
| `/` | 16 | 3000 | 0 | 7.4 / 12.0 / 14.7 | 2052 | 1.03 ms |
| `/books`（第 1 頁） | 1 | 500 | 0 | 3.8 / 4.6 / 5.3 | 258 | 1.40 ms |
| `/books` | 16 | 3000 | 0 | 10.0 / 15.0 / 18.1 | 1545 | 1.50 ms |
| `/books?page=145`（最後一頁，整表 quicksort） | 1 | 500 | 0 | 5.2 / 6.4 / 6.9 | 190 | 2.78 ms |
| `/books?page=145` | 16 | 3000 | 0 | 8.1 / 11.9 / 14.6 | 1864 | 4.10 ms |
| 對照：`/search?q=小說`（既有功能） | 1 | 500 | 0 | 9.5 / 10.8 / 11.8 | 104 | 6.71 ms |
| 對照：`/search?q=小說` | 16 | 3000 | 0 | 14.1 / 18.0 / 24.1 | 1099 | 9.99 ms |

**結論**

使用者提出四個要確認的問題，結論如下：
1. **`ORDER BY random()`**：首頁每個請求約用 1 ms 的 DB CPU，併發從 1 升到 16 幾乎不變，也沒有 temp file（見 Query plan baseline）。
2. **`/books` 的排序要不要加 index**：第 1 頁約 1.4–1.5 ms。最後一頁整表排序最貴，約 2.8–4.1 ms，但仍低於既有的一般搜尋（約 6.7–10 ms）。目前不加 index。
3. **COUNT**：每次翻頁都會執行，約 0.4 ms（EXPLAIN），不是主要成本。
4. **併發升高時 RDS CPU 是否線性增加**：每個請求的 DB CPU 和併發數無關，所以總 DB CPU 會隨請求量線性增加。這和既有頁面的特性相同，而新頁面每個請求的成本比一般搜尋低。

以這份資料量來看，不需要改用其他 sampling strategy。

**限制與觸發條件**

- 這次是本機機型，沒有量 RDS 的實際時間，也沒有反映 burstable instance 的 CPU credit。
- 上線後如果 RDS 的 CPU 或 credit 出現異常，或者 Catalog 大幅成長，就重跑這份壓測和 EXPLAIN，再另外開一張最佳化 issue。最佳化方向例如：首頁樣本改用 TABLESAMPLE 或隨機主鍵區段；書庫排序加複合 index。

## 未解決事項

1. **Bestseller 後端保留但無 Web 呼叫者**：`BestsellerService.HomeTopCount`、`GetTopAsync` 目前沒有呼叫端，依規格保留（後端能力保留，Web 暫停），由 `BestsellerReaderIntegrationTests` 維持接線。若長期不再需要，應另開 issue 決定移除。
2. **`ORDER BY random()` 成本**：首頁每次載入都做整表排序；目前無 SLO，見上方觸發條件。`INF-B06` 記錄此項。
3. **offset 分頁的位移**：排序只在資料集不變時決定性；兩次請求之間若有書籍新增，後續頁可能出現重複或略過。是否改為 keyset 分頁，需要另行決策（會改變分頁的 UI 與 URL 契約）。
4. **資料夾文件與 `/Docs` 並存**：本次兩邊同步更新。使用者 2026-10-24 決定，文件重心逐步移到各程式資料夾的 `docs/`，`/Docs` 改為參考文件，之後封存；`AGENTS.md` 的 authority 表尚未依此修改。
5. **Crawler 停用**：production 的 Bestseller 不再更新，書庫的資料來源仍是既有 Book 資料；Crawler 恢復的條件不在本 issue 範圍。
6. **作者為空的書**：開發資料中部分書沒有 `AUTHOR` 角色的貢獻者，書庫與首頁該欄位會是空白，與一般搜尋行為一致，本次未改。
7. **`BookSearchPage.TotalPages` 的極值 overflow**：`BookBrowsePage` 已改用 long 計算（`2a646b7`），一般搜尋的 `BookSearchPage` 也是相同寫法，不在本票範圍內，沒有修改。
8. **RDS 實測**：上線關卡用本機壓測驗證，見上方〈上線關卡〉的限制。

## Code Review 與修正

兩軸 review 的範圍是 `origin/main...HEAD`（`4ec8492` 之後的 11 個 commit），由 Standards 和 Spec 兩個 reviewer 並行審查。每項發現都由主 agent 對照檔案核實過。

### Standards

| # | 發現 | 核實 | 處理 |
|---|---|---|---|
| S1 | 四處 folder docs 仍寫「書庫規則待 #109 後續模組同步」，但 M3（`7c14b09`）已補上 `book-catalog.md` §3.6，兩邊說法不一致（AGENTS.md §3.3 第 5 步） | 屬實：`Application/docs/architecture.md:19`、`workflow-diagram.md:9`、`test-suite.md:184`、`Infrastructure/docs/test-suite.md:139` | 已修正，改成指向 §3.6 和實際的 caller |
| S2 | `Views/docs/architecture.md:11` 的表格列缺少結尾的 `\|` | 屬實 | 已修正 |
| S3 | `EfBookBrowse` 的 list 和 sample 重複寫了同一段 `BookRow` 投影（Duplicated Code，屬於判斷題） | 屬實，各 7 行 | 不修。M1 已經在 #110 上，重構收益小；兩個查詢的投影欄位相同，日後若要調整欄位，兩處需同時修改 |
| S4 | `BookListItemViewModel.From` 的兩個 overload 內容相同（Duplicated Code / Data Clumps） | 屬實 | 不修。Browse 和 Search 的 Application contract 刻意分開（使用者決定），所以重複只出現在 Presentation 的這一層，屬於可以接受的代價 |
| S5 | `_BookList` 的 `search-results` / `search-result` class 名稱只描述搜尋，但現在書庫和首頁也用這個 partial（Mysterious Name） | 屬實 | 不修。改名會連動 `SearchPageTests` 等的 selector 和 `HtmlPage` helper。這次刻意保持搜尋頁的 HTML 不變；改名可以另外開一張小 refactor |
| S6 | `BestsellersController` 寫死 `"/books"`，沒有用 `BookBrowseViewModel.UrlFor` | 屬實，影響很小 | 不修。301 的目標是固定的書庫入口，不帶頁碼 |
| S7 | `BestsellerService.HomeTopCount` / `GetTopAsync` 目前沒有 caller（Speculative Generality） | 屬實 | 刻意保留，依計畫「後端保留」；已記錄在 APP-B03 |

### Spec

| # | 發現 | 核實 | 處理 |
|---|---|---|---|
| P1 | `deploy/docs/workflow-diagram.md:56` 的上線人工驗證仍寫「暢銷榜」；runbook 本文已經改過了 | 屬實，這是部署後的驗證步驟，不是在描述 Bestseller 資料 | 已修正為「書庫」 |
| P2 | `Controllers/docs/test-suite.md` 的測試案例編號用 BROWSE-01～07，和需求編號 BROWSE-01～04 撞號，而且同一個編號代表的意思不同 | 屬實（例：測試 BROWSE-04 是 redirect，需求 BROWSE-04 是空狀態） | 已修正，測試案例改成 `BOOKS-01～07`，和同一份文件的 `HOME-`、`PIPE-` 命名方式一致 |

Spec 軸沒有發現 scope creep，也沒有發現實作錯誤。排序、long offset、空書庫時摘要為 null、302 / 301、description 和目錄都不輸出、固定 Id 的 tie-breaker 測試、每個情境各自建立 factory 的 Bestseller 守衛，以上都逐項核對過，符合規格。

### 使用者 review（#110 / #111）

| # | 發現 | 核實 | 處理 |
|---|---|---|---|
| U1 | 首頁的 `ORDER BY random()` 和 `/books` 的 COUNT／排序在 production 上的 DB 成本，應該當作上線的關卡，合併時不用擋 | 屬實；baseline 只有單次查詢，沒有量併發 | 以本機併發壓測補上，見〈上線關卡：本機併發壓測〉 |
| U2 | `BookBrowsePage.TotalPages` 的 `TotalCount + PageSize - 1` 在接近 `int.MaxValue` 時會 overflow | 屬實；修正前的紅燈值是 -107374181 | `2a646b7` 改用 long 計算，加上 `BookBrowsePageTotalPagesTests`，再 merge 到 M2、M3 |
