# Issue #6 實作報告：Crawler 完整爬取成功的流程

- Issue：#6
- Branch：issue-6-crawler-success-path
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 範圍說明（第一階段）

本次 commit 為「核心（part 1）」：除 HTML 解析器外，其餘皆已實作並測試。
排行榜頁與商品詳細頁的 HTML 解析器尚未實作，因博客來回傳 Cloudflare 驗證頁，尚無真實 fixture
（見下方「執行紀錄」與「未解決事項」）。解析器以 `NotImplementedError` 的 stub 存在，不猜測 selector。

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/crawler_books.py` | 刪除 | 空白佔位檔，由套件取代 |
| `crawler/requirements.txt` | 新增 | 釘選依賴：psycopg 3.3.6、requests 2.34.2、beautifulsoup4 4.15.0、pytest 9.1.1（Python 3.14.4 驗證可安裝） |
| `crawler/pytest.ini` | 新增 | `testpaths = tests`、`pythonpath = .` |
| `crawler/books_crawler/__init__.py` | 新增 | 套件說明與執行指令 |
| `crawler/books_crawler/__main__.py` | 新增 | `python -m books_crawler` 進入點 |
| `crawler/books_crawler/cli.py` | 新增 | 讀取 `DATABASE_URL`、組裝依賴、回傳 exit code；stdout logging |
| `crawler/books_crawler/models.py` | 新增 | `RankingRow`、`Identifier`、`Contributor`、`BookDraft`、`SourceRef`、`SnapshotRow` 與常數（stored 詞彙） |
| `crawler/books_crawler/urls.py` | 新增 | 商品 URL 正規化（canonical identity） |
| `crawler/books_crawler/normalize.py` | 新增 | ISBN 正規化與 checksum、語言對照、貢獻者角色對照、出版日期精度 |
| `crawler/books_crawler/ranking.py` | 新增 | 排行榜驗證（100 筆、rank 1..100、URL 唯一）、快照驗證 |
| `crawler/books_crawler/fetcher.py` | 新增 | `Fetcher` Protocol（`get(url) -> str`）、`HttpFetcher`（browser UA、timeout、禮貌延遲） |
| `crawler/books_crawler/parsers.py` | 新增 | 排行榜與詳細頁解析器的 stub（`NotImplementedError`，標示 TODO 待 fixture） |
| `crawler/books_crawler/db.py` | 新增 | psycopg 3 存取：來源查詢、單書交易寫入、榜單原子替換 |
| `crawler/books_crawler/run.py` | 新增 | 單次 run 流程、`RunDependencies`（可注入 fetcher / parser / connect / clock）、`RunReport`、log 格式 |
| `crawler/tests/__init__.py` | 新增 | 測試套件套件化（供 `tests.fakes` 匯入） |
| `crawler/tests/conftest.py` | 新增 | session 級 `pgvector/pgvector:pg17` 容器、EF 產生 idempotent schema 並套用、各測試 TRUNCATE |
| `crawler/tests/fakes.py` | 新增 | fixture 式 fake fetcher（記錄所有請求）、回傳預備物件的 fake parser |
| `crawler/tests/test_urls.py` | 新增 | URL 正規化單元測試 |
| `crawler/tests/test_normalize.py` | 新增 | ISBN、語言、角色、日期精度單元測試 |
| `crawler/tests/test_ranking.py` | 新增 | 排行榜與快照驗證單元測試 |
| `crawler/tests/test_fetcher.py` | 新增 | HttpFetcher 單元測試（假 session） |
| `crawler/tests/test_run_unit.py` | 新增 | 不需資料庫的流程測試（排行榜失敗時不開啟連線）、log 格式、CLI 設定錯誤 |
| `crawler/tests/test_db_integration.py` | 新增 | 整合測試（真 EF schema、拋棄式 PostgreSQL） |
| `crawler/tests/fixtures/README.md` | 新增 | 使用者需保存的頁面清單、另存方式、回報欄位 |
| `Docs/Implementation-Report/issue-6-crawler-success-path.md` | 新增 | 本報告 |

未變更：任何 C# 程式、EF migration、`Docs/` 中既有規格。

## 實作思路

### 模組切分

- **純函式（無 IO）**：`urls`、`normalize`、`ranking`、`models`。全部可單元測試。
- **IO 接縫**：`fetcher.Fetcher`（Protocol）與 `parsers` 的 callable 簽名。`run.RunDependencies` 將兩者與 `connect`、`clock` 一併注入，測試以 fake 取代，生產程式以 `HttpFetcher` 與（待實作的）真解析器組裝於 `cli.py`。
- **DB 層**：`db.py` 只做查詢與寫入，不含業務判斷。
- **流程**：`run.run_once` 串接上述元件，永不拋出例外，失敗以 `RunReport` 表示；`cli.main` 將 `RunReport.exit_code` 回傳。

### Fetcher 接縫

`Fetcher` 只有 `get(url) -> str`。`HttpFetcher` 提供 browser User-Agent、`Accept-Language`、timeout（connect 5 秒、read 20 秒）、
第一次之後每次請求前延遲 1 秒（可注入 `sleep`）。非 200 或網路錯誤一律轉為 `FetchError`。未針對 Cloudflare 做任何調校。
正式抓取方式（例如瀏覽器自動化）尚未決定，由另一張 issue 處理。

### Parser 接縫

- 排行榜：`RankingParser = Callable[[str], list[RankingRow]]`。
- 詳細頁：`DetailParser = Callable[[str, str], BookDraft]`，回傳已正規化的 `BookDraft`（title 必填；subtitle 不存在於模型中，寫入時固定 NULL）。
- `BookDraft.__post_init__` 強制：title 非空、`published_date` 與精度成對出現、精度為 YEAR/MONTH/DAY、`page_count > 0`。
- 目前 `parse_ranking_html` / `parse_detail_html` 皆為 stub，明確標示 TODO 並指向 `crawler/tests/fixtures/README.md`。

### URL 正規化（決策，需以真實 fixture 再確認）

- 假設：商品頁為 `https://www.books.com.tw/products/<id>`，`<id>` 為英數字串。
- 規則：接受 `http`/`https`、`books.com.tw` 與 `www.books.com.tw`、相對路徑與協定相對網址；去除 query（如 `loc=` 追蹤參數）、fragment 與結尾斜線；
  輸出 `https://www.books.com.tw/products/<id>`。非商品網址（例如榜單頁本身）一律拒絕。
- 身分判斷為 `BOOKS_COM_TW + canonical URL`。排行榜驗證在 canonical 之後才檢查重複。

### 正規化規則（data-model §2、§2.1、§5.3–§5.5）

- **ISBN**：移除 `-`、空白與各種連字號，轉大寫；ISBN-10 需 `\d{9}[\dX]` 且加權和 mod 11 = 0；ISBN-13 需 `97[89]\d{10}` 且加權和 mod 10 = 0。無效值回傳 `None` 並記 log，不寫入。
  - 決策：ISBN-13 加上 978/979 前綴檢查（屬格式驗證）。
- **語言**：對照表 繁體中文→zh-TW、簡體中文→zh-CN、英文→en、日文→ja、韓文→ko；其他→`NULL` 並記 log。
- **貢獻者角色**：作者→AUTHOR、原文作者→ORIGINAL_AUTHOR、譯者→TRANSLATOR、編者→EDITOR、繪者→ILLUSTRATOR；去除尾端「：/:」後比對；其他→OTHER。
- **出版日期精度**：`2026/10/11`→DAY、`2026/10`→MONTH、`2026`→YEAR；其餘格式或不合法日期→`(NULL, NULL)`，不猜測。
  - 決策：MONTH / YEAR 時 `published_date` 以當月 1 日、當年 1 月 1 日作為儲存錨點，真實精度由 `published_date_precision` 表示（與 data-model §5.1「補值日期須搭配精度」一致）。

### 交易邊界

- 連線採 `autocommit=True`，所有寫入都以顯式 `conn.transaction()` 包住。
  理由：若使用非 autocommit，讀取會隱含開啟交易，巢狀 `transaction()` 只會建立 savepoint，外層不提交，會導致寫入遺失。
- **每本新書一個交易**：`insert_new_book` 在同一交易內寫入 `books`、`book_sources`、`book_identifiers`、`book_contributors`、`book_subjects`。
  寫入前先檢查 ISBN 是否已屬於其他 Book，若是則拋出 `BookConflictError`（見未解決事項）。
- **榜單替換一個交易**：`replace_bestsellers` 內 `DELETE FROM bestsellers` + `executemany INSERT`；任一步失敗即整體 rollback。
- 失敗前已成功寫入的新書保留（各自已提交），不影響既有榜單；下次 run 會以 URL 重用。

### Schema 取得方式

- 整合測試於 session 開始時執行 `dotnet tool restore`、`dotnet build Book-Finder.csproj`、`dotnet ef migrations script --idempotent --no-build -o <tmp>`，
  並以 `utf-8-sig` 讀取（EF 產生的檔案帶 UTF-8 BOM）後套用到拋棄式容器。
- 爬蟲本身不執行 DDL。schema 來源只有 EF migration（ADR-002）。
- 資料表沒有 DB default，因此 UUID（`books.id`、`book_sources.id`）與所有時間戳（`created_at`、`updated_at`、`first_seen_at`、`last_seen_at`、`captured_at`）皆由爬蟲產生。

### 流程（`run_once`）

1. 抓排行榜 → `parse_ranking` → `validate_ranking`（失敗即 FAILED，未開啟資料庫連線）。
2. 逐筆：`find_source`；存在則重用 Book 且不抓詳細頁；不存在則抓詳細頁 → `parse_detail` → `insert_new_book`。
3. 任何一本新書的抓取或解析失敗，整次 run FAILED（#7 之前的行為）。`_resolve_row` 即為 #7 包 retry / skip 的單書步驟。
4. `validate_snapshot`（100 筆、rank 唯一、book_id 唯一）→ `replace_bestsellers`（同一 captured_at）。
5. 任何例外皆被捕捉為 FAILED，記錄 `error=<type>: <message>`，exit code 1。

### 日誌

每次 run 於 stdout 輸出一行 key=value：`run_id`、`started_at`、`finished_at`、`status`、`ranking_count`、`existing_book_count`、`new_book_count`、`skipped_count`（恆為 0）、`exit_code`，失敗時加 `error`。
`DATABASE_URL` 不被記錄。

## 執行紀錄（Log）

1. `gh issue view 6` 失敗：GraphQL 錯誤，原因為 GitHub 已棄用 Projects (classic) 欄位。改用 `gh api repos/Arthur801/Book-Finder/issues/6` 取得 issue 內容，成功。
2. 第一次抓取嘗試（第一階段）：以瀏覽器 User-Agent 對 `https://www.books.com.tw/web/sys_saletopb/books/?attribute=7` 發出單次請求，HTTP 403。
   回應標頭含 `cf-mitigated: challenge`、`server: cloudflare`；內容為標題「歡迎光臨博客來」的驗證頁。首頁 `https://www.books.com.tw/` 的 HEAD 請求同樣回傳 challenge。
   依指示停止抓取，未保存任何 HTML，暫存目錄已刪除。未嘗試其他 client 或標頭繞過驗證。
3. 搜尋既有 fixture：`git ls-files` 無 HTML fixture；`grep` 僅在 `Docs/data/data-model.md` 找到商品網址範例。
4. 依 2026-10-11 的指示進入第二階段（核心，不含解析器）。未再次請求博客來。
5. `.venv` 安裝：`pip install psycopg[binary] requests beautifulsoup4 pytest`，於 Python 3.14.4 解析為 psycopg 3.3.6、requests 2.34.2、beautifulsoup4 4.15.0、pytest 9.1.1，安裝成功。
6. `dotnet tool restore` 成功（dotnet-ef 10.0.12）；`dotnet build` 0 errors；`dotnet ef migrations script --idempotent -o /tmp/...` 產生 434 行 SQL，含 `CREATE EXTENSION IF NOT EXISTS vector;` 與 12 張表。
7. `git rm crawler/crawler_books.py`。
8. 首次完整 pytest：94 passed，整合測試確實執行（setup 約 5.3 秒為 Docker 啟動與 EF 腳本產生），測試後無殘留容器（`docker ps -a` 無 `bf6-` 容器）。
9. 模組入口驗證：`cd crawler && python -m books_crawler`（未設定 `DATABASE_URL`）輸出錯誤並以 exit code 2 結束，未連線、未抓取。
   註：在巢狀 shell 中以 `echo $?` 查詢退出碼得到錯誤的 0（引號展開問題），改以工具回報的 exit code 確認為 2。
10. 未執行任何對 `books.com.tw` 的實際請求；執行入口驗證時刻意不設定 `DATABASE_URL`，以免真實抓取。

## 驗證結果

### Issue #6 acceptance criteria

| 條件 | 結果 | 對應測試 / 說明 |
|---|---|---|
| 完整排行榜 → 100 筆 Bestseller，run = SUCCESS，exit 0 | ✅（流程與資料庫部分）／⏸（真實 HTML 解析） | `test_db_integration.py::test_full_ranking_success_writes_100_bestsellers`（以預備的 100 筆排行模擬）；真實排行榜解析待 fixture |
| 不足 100 筆或 URL 重複 → 失敗，原有 Bestseller 不變 | ✅ | `test_db_integration.py::test_ranking_with_99_rows_fails_and_keeps_previous_bestsellers`、`test_duplicate_product_url_fails_and_keeps_previous_bestsellers`；`test_ranking.py` 多項；`test_run_unit.py::test_incomplete_ranking_fails_before_database_and_detail_fetches` |
| 已存在的商品 URL 不觸發詳細頁抓取，Book metadata 不變 | ✅ | `test_db_integration.py::test_existing_urls_are_reused_without_detail_fetch_or_metadata_change`（fake fetcher 斷言只抓 50 個新 URL；舊書的 id、title、publisher、created_at、updated_at 不變） |
| 新書欄位符合 data model；缺少的選填欄位存 NULL，不推測 | ✅（寫入）／⏸（解析） | `test_db_integration.py::test_new_book_columns_match_data_model_with_nulls_for_missing_fields`；`test_normalize.py::test_parse_published_date_never_guesses` |
| 語言對照：繁→zh-TW、簡→zh-CN、英→en、日→ja、韓→ko、其他→NULL | ✅（對照函式與寫入）／⏸（從頁面取得語言字串） | `test_normalize.py::test_map_language`；`test_db_integration.py::test_new_book_columns_match_data_model_with_nulls_for_missing_fields`（zh-CN 寫入） |
| 榜單替換為 atomic transaction；中途失敗時舊榜單完整保留 | ✅ | `test_db_integration.py::test_failed_snapshot_replacement_keeps_previous_list`（第 50 筆 FK 違反，前 49 筆已插入，斷言舊 100 筆完全不變） |
| `pytest` 通過 | ✅ | 見下方 pytest 摘要 |

### 其他驗證（與本次範圍相關）

| 項目 | 結果 | 測試 |
|---|---|---|
| 商品 URL 正規化與拒絕非商品網址 | ✅ | `test_urls.py` |
| ISBN 正規化與 checksum（ISBN-10/13、X、前綴、無效值） | ✅ | `test_normalize.py::test_normalize_isbn_*` |
| 貢獻者角色對照 | ✅ | `test_normalize.py::test_map_contributor_role` |
| 出版日期精度（DAY/MONTH/YEAR、不猜測） | ✅ | `test_normalize.py::test_parse_published_date_*` |
| 排行榜驗證（100 筆、1..100、唯一、非空） | ✅ | `test_ranking.py` |
| 快照驗證 | ✅ | `test_ranking.py::test_snapshot_*` |
| Fetcher：UA、timeout、非 200、網路錯誤、禮貌延遲 | ✅ | `test_fetcher.py` |
| 排行榜失敗時不開啟資料庫、不抓詳細頁 | ✅ | `test_run_unit.py` |
| 新書 ISBN 已屬於其他 Book 時整次失敗 | ✅ | `test_db_integration.py::test_isbn_already_owned_by_another_book_fails_the_run` |
| 新書詳細頁抓取失敗時整次失敗且榜單不變 | ✅ | `test_db_integration.py::test_new_book_detail_failure_fails_run_and_keeps_previous_bestsellers` |
| 無 `DATABASE_URL` 時 exit code 2 | ✅ | `test_run_unit.py::test_cli_without_database_url_returns_config_error` |
| 真實排行榜 / 詳細頁 HTML 解析 | ⏸ | 待使用者保存 fixture（見 `crawler/tests/fixtures/README.md`） |
| 解析器 fixture 負面案例（少於 100 筆、缺標題） | ⏸ | 待 fixture 後由程式衍生 |

### 指令與結果

- Python 測試：`~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q`
  - 摘要：`94 passed in 9.84s`
- `dotnet build`：成功（0 errors）；本次未修改任何 C# 或 migration。

## 執行指令

```text
# 測試（於 worktree 根目錄；需要 Docker 與 dotnet）
~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q

# 執行一次 crawler（於 crawler/ 目錄；目前解析器為 stub，會以 exit code 1 結束）
cd crawler && DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<db> python -m books_crawler
```

退出碼：0 = SUCCESS、1 = FAILED（榜單不變）、2 = 設定錯誤（未設定 `DATABASE_URL`）。

## 未解決事項與後續注意

### 解析器（待 fixture，阻塞）

- `parse_ranking_html` 與 `parse_detail_html` 尚未實作。博客來回傳 Cloudflare 驗證頁，無法取得真實 HTML。
- 使用者需依 `crawler/tests/fixtures/README.md` 以瀏覽器另存：排行榜一頁、2–4 個詳細頁（含目錄與頁數、無目錄、譯作）。
- 取得 fixture 後需確認：排行榜 URL（`RANKING_PAGE_URL` 仍為未驗證值）、商品網址格式（`urls.py` 假設）、各欄位 selector、日期字串格式（`normalize.py` 假設 `YYYY/MM/DD`、`YYYY/MM`、`YYYY`）、語言與角色標籤實際文字。
- 解析器完成後需補 fixture 測試，並由程式衍生負面案例（少於 100 筆、重複 URL、缺標題）。

### 正式抓取方式（未決，另開 issue）

- 博客來對 HTTP 請求回傳 Cloudflare 驗證。`HttpFetcher` 只是簡單實作，未調校。
- 正式方案（例如瀏覽器自動化）未決定，屬於另一張 issue。接縫（`Fetcher` Protocol）已就緒，替換不需修改流程。

### 給 #7 的接續點

- retry / skip / PARTIAL_SUCCESS 尚未實作。目前任一新書失敗即整次 FAILED。
- 接續點：`run._resolve_row`（單書步驟）；`RunReport.skipped_count` 目前恆為 0；`format_report` 未輸出 skipped 清單。
- 需注意：`insert_new_book` 每本一個交易，#7 包 retry 時失敗的單書交易已 rollback，不會留下部分寫入。

### 本次做出的決策（需確認）

1. **ISBN 衝突**：新書的 ISBN 已屬於其他 Book 時，`insert_new_book` 拋出 `BookConflictError`，整次 run FAILED。
   規格（data-model §6、§10.4）只規定 Google Books 的 ISBN 合併，未規定博客來的衝突處理。替代方案是「重用既有 Book 並新增 source」，但會改變 Book 身分，故本次採用失敗（大聲失敗）。待確認。
2. **既有來源的 `last_seen_at`**：規格未要求，本次重用既有書時不更新 `book_sources.last_seen_at`，以符合「既有書不修改」的規則。待確認。
3. **`contributor_order`**：採 1-based，與排行榜 rank 慣例一致。規格未明定。
4. **日期錨點**：MONTH / YEAR 的 `published_date` 以當月 1 日、當年 1 月 1 日儲存，精度由 `published_date_precision` 表示。
5. **URL 正規化**：去除 query 與 fragment。若真實商品網址中的 query 參數具有識別意義（例如多版本），此規則需修正。需以真實 fixture 驗證。
6. **ISBN-13 前綴**：限定 978 / 979（格式驗證）。
7. **語言與角色的未知值**：語言未知 → NULL 並記 log；角色未知 → OTHER。
8. **部分寫入語意**：失敗前已提交的新書保留；它們在下次 run 會以 URL 重用，不影響榜單。

### 其他

- 排行榜 URL `https://www.books.com.tw/web/sys_saletopb/books/?attribute=7` 未經內容驗證，仍標示為 UNVERIFIED（`parsers.py`）。
- `books_crawler` 的 logger 在 CLI 中設定為 `propagate=False` 並輸出至 stdout；若未來需要整合其他 logging 設定，需調整。
- 整合測試以 Docker CLI 啟動容器，未使用 Testcontainers 套件（依賴數較少）；若 CI 需要，可再評估。
