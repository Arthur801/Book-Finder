# Issue #6 實作報告：Crawler 完整爬取成功的流程

- Issue：#6
- Branch：issue-6-crawler-success-path
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 範圍與進度

- **Part 1（核心）**：排行榜與詳細頁以外的所有流程（URL 正規化、ISBN、語言、角色、日期、排行榜驗證、DB 交易、榜單原子替換、run 流程與 log）。
- **Part 2（解析器與真實 fixture）**：使用者以瀏覽器另存 1 個排行榜頁與 4 個商品頁（2026-10-11）。本輪實作 `parse_ranking_html` 與 `parse_detail_html`，以真實頁面驗證，並補上端到端測試。
- **Part 2 追加決策（使用者）**：新商品的 ISBN 命中既有 Book 時，改為「只新增 BOOKS_COM_TW source 指向既有 Book」，不再因 ISBN 衝突而失敗（見「實作思路／ISBN 比對」）。
- 仍未完成：retry / skip / PARTIAL_SUCCESS（#7）；正式抓取博客來的方式（issue #21）。

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/crawler_books.py` | 刪除（Part 1） | 空白佔位檔，由套件取代 |
| `crawler/requirements.txt` | 新增（Part 1） | 釘選依賴：psycopg 3.3.6、requests 2.34.2、beautifulsoup4 4.15.0、pytest 9.1.1（Python 3.14.4 驗證可安裝） |
| `crawler/pytest.ini` | 新增（Part 1） | `testpaths = tests`、`pythonpath = .` |
| `crawler/.gitignore` | 新增（Part 1） | 忽略 `__pycache__/`、`.pytest_cache/` |
| `crawler/books_crawler/__init__.py` | 新增（Part 1） | 套件說明與執行指令 |
| `crawler/books_crawler/__main__.py` | 新增（Part 1） | `python -m books_crawler` 進入點 |
| `crawler/books_crawler/cli.py` | 新增（Part 1）／修改（Part 2） | 讀取 `DATABASE_URL`、組裝依賴、回傳 exit code；stdout logging。Part 2：移除 `propagate=False`，讓測試可用 `caplog` 驗證 log |
| `crawler/books_crawler/models.py` | 新增（Part 1） | `RankingRow`、`Identifier`、`Contributor`、`BookDraft`、`SourceRef`、`SnapshotRow` 與常數 |
| `crawler/books_crawler/urls.py` | 新增（Part 1） | 商品 URL 正規化（canonical identity） |
| `crawler/books_crawler/normalize.py` | 新增（Part 1） | ISBN 正規化與 checksum、語言對照、貢獻者角色對照、出版日期精度、`clean_text` |
| `crawler/books_crawler/ranking.py` | 新增（Part 1） | 排行榜驗證（100 筆、rank 1..100、URL 唯一）、快照驗證 |
| `crawler/books_crawler/fetcher.py` | 新增（Part 1） | `Fetcher` Protocol（`get(url) -> str`）、`HttpFetcher`（browser UA、timeout、禮貌延遲） |
| `crawler/books_crawler/parsers.py` | 新增（Part 1 為 stub）／**實作（Part 2）** | `parse_ranking_html`（`ul.clearfix > li.item`，rank 取自 `strong.no`）與 `parse_detail_html`（標題、出版社、日期＋精度、語言、描述、目錄、頁數、封面、ISBN、貢獻者與角色、本書分類）。`RANKING_PAGE_URL` 移除 UNVERIFIED 標記 |
| `crawler/books_crawler/db.py` | 新增（Part 1）／**修改（Part 2）** | Part 2：`BookConflictError` 移除；新增 `persist_new_product`（ISBN-13 → ISBN-10 比對；命中則只新增 BOOKS_COM_TW source，否則建立新 Book；單一 transaction）與 `BookAlreadyRankedError`（reserved book） |
| `crawler/books_crawler/run.py` | 新增（Part 1）／**修改（Part 2）** | Part 2：追蹤本次榜單已使用的 book_id（重複 Book → run FAILED 並輸出清楚錯誤）；命中既有 Book 時 INFO log（rank、url、命中 ISBN、book_id）；RunReport 新增 `attached_source_count` |
| `crawler/tests/__init__.py` | 新增（Part 1） | 測試套件套件化 |
| `crawler/tests/conftest.py` | 新增（Part 1） | session 級 `pgvector/pgvector:pg17` 容器、EF 產生 idempotent schema 並套用、各測試 TRUNCATE |
| `crawler/tests/fakes.py` | 新增（Part 1）／**修改（Part 2）** | Part 2：真實 fixture 載入、由真實頁面衍生負面案例的輔助函式（移除列、重複 URL、移除標題等） |
| `crawler/tests/test_urls.py` | 新增（Part 1） | URL 正規化單元測試 |
| `crawler/tests/test_normalize.py` | 新增（Part 1） | ISBN、語言、角色、日期精度單元測試 |
| `crawler/tests/test_ranking.py` | 新增（Part 1） | 排行榜與快照驗證單元測試 |
| `crawler/tests/test_fetcher.py` | 新增（Part 1） | HttpFetcher 單元測試（假 session） |
| `crawler/tests/test_run_unit.py` | 新增（Part 1）／修改（Part 2） | Part 2：stub 測試改為「非排行榜頁面 → ParseError、不開啟連線」 |
| `crawler/tests/test_db_integration.py` | 新增（Part 1）／修改（Part 2） | Part 2：舊的 ISBN 衝突失敗測試改為 ISBN-13／ISBN-10 attach、ISBN-13 優先、同一 Book 兩次 → 失敗 |
| `crawler/tests/test_parsers_real_fixtures.py` | **新增（Part 2）** | 排行榜 fixture（100 筆、位置、驗證、負面案例）；4 個商品頁的具體期望值；由 0011062863 衍生的負面案例 |
| `crawler/tests/test_e2e_real_fixtures.py` | **新增（Part 2）** | 端到端：真實排行榜＋4 個真實商品頁，寫入 100 筆 bestseller 與 4 本書的欄位；由真實頁面衍生的 3 個失敗案例 |
| `crawler/tests/fixtures/ranking_books_7d_top100.html` | **新增（Part 2）** | 使用者另存的中文書 7日暢銷榜（未修改） |
| `crawler/tests/fixtures/detail_0011062863.html` | **新增（Part 2）** | 政。望：前線五十年…（未修改） |
| `crawler/tests/fixtures/detail_0010852315.html` | **新增（Part 2）** | 臺灣漫遊錄（未修改） |
| `crawler/tests/fixtures/detail_0011062550.html` | **新增（Part 2）** | 與妳相戀到生命盡頭 (首刷限定版) 9（未修改） |
| `crawler/tests/fixtures/detail_0011057581.html` | **新增（Part 2）** | 花錢的藝術…（未修改） |
| `crawler/tests/fixtures/README.md` | 新增（Part 1）／**修改（Part 2）** | 列出實際檔案、來源網址、擷取日期、覆蓋與未覆蓋的情境 |
| `Docs/modules/crawler.md` | **修改（Part 2）** | §5 Book Resolution：新增新商品的 ISBN 比對步驟、attach 行為、同一 Book 不得重複的規則 |
| `Docs/data/data-model.md` | **修改（Part 2）** | §6：新增一段說明 books.com.tw crawler 套用相同 ISBN 比對但不做 canonical merge |
| `Docs/Implementation-Report/issue-6-crawler-success-path.md` | 新增（Part 1）／修改（Part 2） | 本報告 |

未變更：任何 C# 程式、EF migration。

## 實作思路

### 模組切分

- **純函式（無 IO）**：`urls`、`normalize`、`ranking`、`models`，以及 `parsers` 中的 HTML 解析函式（輸入為字串）。
- **IO 接縫**：`fetcher.Fetcher`（Protocol）；`run.RunDependencies` 注入 fetcher、兩個解析器、`connect` 與 `clock`。測試以 fake 取代 fetcher，並可用真實解析器配合真實頁面。
- **DB 層**：`db.py` 只做查詢與寫入。
- **流程**：`run.run_once` 串接上述元件，永不拋出例外，失敗以 `RunReport` 表示；`cli.main` 將 `RunReport.exit_code` 回傳。

### Fetcher 接縫

`Fetcher` 只有 `get(url) -> str`。`HttpFetcher` 提供 browser User-Agent、`Accept-Language`、timeout（connect 5 秒、read 20 秒）、
第一次之後每次請求前延遲 1 秒（可注入 `sleep`）。非 200 或網路錯誤一律轉為 `FetchError`。未針對 Cloudflare 做任何調校。
正式抓取方式由 issue #21 處理。

### 解析器（Part 2）

**排行榜頁**（`parse_ranking_html`）

- 頁面有多個 `li.here`（頂層分頁、子分頁、分類各一）。確認條件是 `ul.sub_list li.here > a` 的文字為「7日暢銷榜」，否則 `ParseError`（run 失敗）。
- 100 筆排名為 `ul.clearfix > li.item`（直接子節點），且含 `p.no_list strong.no`（排名）。選單與分類項目沒有排名，會被忽略。
- 商品 URL 為該列第一個 `a[href*="/products/"]`（封面連結，與書名連結為同一 URL），經 `canonicalize_product_url` 正規化（去除 `?loc=` 追蹤參數）。

**商品詳細頁**（`parse_detail_html`）

- 標題：第一個 `h1`（與 `og:title` 相同）。沒有標題 → `ParseError`（run 失敗）。
- 商品資訊列為 `li`，形式為 `<標籤>：<值>`。解析時只讀取該列的**直接子節點**，因為來源 HTML 有未關閉的 `li`（見「假設修正」）。
- 出版社：列中 `puballb` 連結的文字。出版日期：`parse_published_date`（精度保留）。語言：`map_language`。規格：`(\d+)\s*頁`。ISBN：`normalize_isbn`（無效則不寫入）。
- 貢獻者：列中直接子節點的 `a[href*="adv_author"]` 為姓名，列的標籤決定角色（`map_contributor_role`），順序為頁面出現順序（1-based）。只在 `div.type02_p003` 區塊內搜尋（其他商品的清單使用相同標記）。
- 內容簡介／目錄：`h3` 所屬區塊（`div.mod_b`）中 `.bd > .content` 的文字；`<br>` 轉為換行。目錄只在區塊存在且有內容時保存。
- 本書分類：`ul.sort` 列中的直接 `a`，每一層分類存為一個 subject（見未解決事項）。
- 封面：`img.cover` 且 alt 等於書名的 `src`。
- subtitle 永遠 NULL（`BookDraft` 沒有此欄位）。

### ISBN 比對（Part 2，使用者決定 option b）

- 新商品（BOOKS_COM_TW `source_url` 尚未存在）的 ISBN 比對順序：**ISBN-13 → ISBN-10**（與 data-model §6 相同）。
- **命中既有 Book**：只新增一筆 BOOKS_COM_TW `book_sources` 指向該 Book（同一 transaction）。不建立 Book，不修改該 Book 的 metadata、identifiers、contributors、subjects（不做 canonical merge，與「既有 Book 不因每日爬取而更新 metadata」一致）。榜單中此商品的 row 使用既有 `book_id` 與新的 source id。
- **未命中或沒有 ISBN**：建立新 Book（不依書名或作者相似度合併）。
- **同一 Book 出現兩次**（例如既有商品與新商品的 ISBN 命中同一 Book）：`bestsellers.book_id` 為 UNIQUE，故本次 run FAILED，榜單不變，錯誤訊息指出衝突的排名。此為目前的處理方式，見未解決事項。
- 命中時記錄 INFO log：`attached BOOKS_COM_TW source to existing Book: rank=… url=… matched=ISBN_13:… book_id=…`。
- `RunReport.existing_book_count` 包含 attach 的商品（它們重用既有 Book）；`attached_source_count` 為其中的子集；`new_book_count` 只計建立的 Book。

### URL 正規化

- 商品網址為 `https://www.books.com.tw/products/<10 位數字>`，後面可能接 `?loc=P_0003_001`（排行榜）或 `?loc=hot_003`（熱門關鍵字區）。正規化去除 query、fragment 與結尾斜線，輸出 `https://www.books.com.tw/products/<id>`。
- 接受 `http`/`https`、`books.com.tw`、`www.books.com.tw`、相對路徑與協定相對網址；非商品網址一律拒絕。
- 排行榜 100 筆經正規化後為 100 個不重複 URL（已由真實 fixture 驗證）。

### 正規化規則（data-model §2、§2.1、§5.3–§5.5）

- **ISBN**：移除 `-`、空白與各種連字號，轉大寫；ISBN-10 需 `\d{9}[\dX]` 且加權和 mod 11 = 0；ISBN-13 需 `97[89]\d{10}` 且加權和 mod 10 = 0。無效值不寫入並記 log。決策：ISBN-13 需 978/979 前綴（格式驗證）。
- **語言**：繁體中文→zh-TW、簡體中文→zh-CN、英文→en、日文→ja、韓文→ko；其他→NULL 並記 log。
- **貢獻者角色**：作者→AUTHOR、原文作者→ORIGINAL_AUTHOR、譯者→TRANSLATOR、編者→EDITOR、繪者→ILLUSTRATOR；去除尾端「：／:」後比對；其他→OTHER。
- **出版日期精度**：`2026/10/11`→DAY、`2026/10`→MONTH、`2026`→YEAR；其餘格式或不合法日期→`(NULL, NULL)`。決策：MONTH／YEAR 的 `published_date` 以當月 1 日、當年 1 月 1 日作為儲存錨點，真實精度由 `published_date_precision` 表示。

### 交易邊界

- 連線採 `autocommit=True`，所有寫入都以顯式 `conn.transaction()` 包住（若使用非 autocommit，讀取會隱含開啟交易，巢狀 `transaction()` 只會建立 savepoint，外層不提交）。
- **每個新商品一個交易**（`persist_new_product`）：建立 Book 的路徑寫入 `books`、`book_sources`、`book_identifiers`、`book_contributors`、`book_subjects`；attach 路徑只寫 `book_sources`。
- **榜單替換一個交易**：`replace_bestsellers` 內 `DELETE FROM bestsellers` + `executemany INSERT`；任一步失敗即整體 rollback。
- 失敗前已提交的新商品保留（各自的交易已提交），不影響既有榜單；下次 run 會以 URL 重用。

### Schema 取得方式

- 整合測試於 session 開始時執行 `dotnet tool restore`、`dotnet build Book-Finder.csproj`、`dotnet ef migrations script --idempotent --no-build -o <tmp>`，並以 `utf-8-sig` 讀取（EF 產生的檔案帶 UTF-8 BOM）後套用到拋棄式容器。
- 爬蟲本身不執行 DDL（ADR-002）。資料表沒有 DB default，UUID 與時間戳皆由爬蟲產生。

### 流程（`run_once`）

1. 抓排行榜 → `parse_ranking` → `validate_ranking`（失敗即 FAILED，未開啟資料庫連線）。
2. 逐筆：`find_source`；存在則重用 Book（且不抓詳細頁）；不存在則抓詳細頁 → `parse_detail` → `persist_new_product`（建立或 attach）。
3. 若同一 Book 在本榜單出現兩次 → FAILED。任一新商品的抓取或解析失敗 → 整次 FAILED（#7 之前的行為）。`_resolve_row` 即為 #7 包 retry / skip 的單商品步驟。
4. `validate_snapshot`（100 筆、rank 唯一、book_id 唯一）→ `replace_bestsellers`（同一 captured_at）。
5. 任何例外皆被捕捉為 FAILED，記錄 `error=<type>: <message>`，exit code 1。

### 日誌

每次 run 於 stdout 輸出一行 key=value：`run_id`、`started_at`、`finished_at`、`status`、`ranking_count`、`existing_book_count`、`new_book_count`、`attached_source_count`、`skipped_count`（恆為 0）、`exit_code`，失敗時加 `error`。`DATABASE_URL` 不被記錄。

## 假設修正（看過真實 HTML 後）

Part 1 的假設與真實頁面比對結果如下。

| 項目 | Part 1 假設 | 真實頁面 | 結果 |
|---|---|---|---|
| 商品 URL | `/products/<id>`，query 可丟棄 | `https://www.books.com.tw/products/0011062550?loc=P_0003_001`；熱門區為 `?loc=hot_003` | 符合，無需修改。排行榜 100 筆 canonical 後皆唯一。 |
| 出版日期格式 | `YYYY/MM/DD`、`YYYY/MM`、`YYYY` | `出版日期：2026/09/17` | 符合。解析為 DAY。 |
| 語言標籤 | 繁體中文、簡體中文、英文、日文、韓文 | `語言：繁體中文` | 符合。4 本皆為 zh-TW。簡體、英、日、韓的標籤未在真實頁面出現。 |
| 貢獻者標籤 | 作者、原文作者、譯者、編者、繪者 | `作者：`、`譯者：` | 標籤符合。**但譯者列的 HTML 不完整**：`<li>譯者：<a>…</a><li>出版社…` 未關閉，後續列被 html.parser 巢狀包住。已改為只讀直接子節點，並避免讀取作者列中的「追蹤作者」widget（`div.trace_box`）。 |
| 貢獻者的姓名位置 | 未假設 | 姓名為 `a[href*="adv_author"]` | 新增的定位規則（以搜尋連結定位，而非純文字）。 |
| 排行榜列位置 | 未假設 | `ul.clearfix > li.item`，排名在 `p.no_list strong.no` | 新增。頁面有多個 `li.here`，7日暢銷榜以 `ul.sub_list` 內的選取項判斷。 |
| ISBN | ISBN-10 或 ISBN-13 | 4 頁皆只顯示 ISBN-13（如 `9789570881592`） | 符合。未遇到 ISBN-10 的實際列。 |
| 目錄 | 有無兩種狀態 | 0011062550 無目錄區塊；其他 3 本有 | 符合。另外發現：目錄文字中出現「譯者」字樣（0010852315），但商品列沒有譯者，因此不產生譯者 row。 |
| 本書分類 | 單一或多層 | `人文社科 > 政治 > 政治人物` | 多層。每一層存為 subject（決策，見未解決事項）。 |
| 封面圖 | `imageLinks` | `img.cover`（alt=書名），`src` 為 `im*.book.com.tw/image/getImage?i=https://www.books.com.tw/img/…jpg&…` | 存為頁面上的 `src`（代理網址，原樣保存）。 |
| 內容簡介 | 純文字 | 0010852315 的內容開頭含促銷徽章文字（「臺灣文學第一本 / 2026 / 國際布克獎得主 …」） | 來源即如此，原樣保存。記為已知現象。 |

## 執行紀錄（Log）

### Part 1

1. `gh issue view 6` 失敗：GraphQL 錯誤，原因為 GitHub 已棄用 Projects (classic) 欄位。改用 `gh api repos/Arthur801/Book-Finder/issues/6`，成功。
2. 第一次抓取嘗試：以瀏覽器 User-Agent 對 `https://www.books.com.tw/web/sys_saletopb/books/?attribute=7` 發出單次請求，HTTP 403。回應標頭含 `cf-mitigated: challenge`、`server: cloudflare`；內容為標題「歡迎光臨博客來」的驗證頁。首頁 `https://www.books.com.tw/` 的 HEAD 請求同樣回傳 challenge。依指示停止抓取，未保存任何 HTML，暫存目錄已刪除，未嘗試其他 client 或標頭繞過驗證。
3. 搜尋既有 fixture：`git ls-files` 無 HTML fixture。
4. `.venv` 安裝：`pip install psycopg[binary] requests beautifulsoup4 pytest`，於 Python 3.14.4 解析為 psycopg 3.3.6、requests 2.34.2、beautifulsoup4 4.15.0、pytest 9.1.1，安裝成功。
5. `dotnet tool restore` 成功（dotnet-ef 10.0.12）；`dotnet build` 0 errors；`dotnet ef migrations script --idempotent` 產生 434 行 SQL，含 `CREATE EXTENSION IF NOT EXISTS vector;` 與 12 張表。
6. Part 1 pytest：94 passed。整合測試以 `pgvector/pgvector:pg17` 啟動，測試後無殘留容器。
7. 入口驗證：`cd crawler && python -m books_crawler`（未設定 `DATABASE_URL`）輸出錯誤並以 exit code 2 結束。註：巢狀 shell 中以 `echo $?` 查詢退出碼得到錯誤的 0（引號展開問題），改以工具回報的 exit code 確認為 2。

### Part 2

8. `gh api repos/Arthur801/Book-Finder/issues/21` 確認存在：「決定 production crawler 存取博客來的方式（Cloudflare challenge）」，state open。
9. 使用者另存 5 個檔案至 `crawler/tests/fixtures/`（未經程式修改）。以 BeautifulSoup（venv）檢視結構：
   - 排行榜：`ul.clearfix > li.item` 共 100 筆，`p.no_list strong.no` 為排名（1..100）；`li.here` 出現 3 次（頂層、子分頁、分類），7日暢銷榜為 `ul.sub_list` 的選取項。
   - 商品頁：標題在 `h1`；資訊列為 `li`；目錄與內容簡介為 `div.mod_b` 中的 `h3` + `.bd > .content`。
10. 核對使用者的粗略 grep：0011062550 與 0011057581 的譯者列為未關閉的 `li`（結構差異）。0010852315 **沒有譯者列**，「譯者」只出現在目錄文字中，與粗略判斷不同。
11. 以腳本確認 4 個商品都在排行榜中：0011062550 排第 1、0010852315 排第 8、0011062863 排第 12、0011057581 排第 17。
12. 首次解析結果發現兩個錯誤，已修正並再次驗證：
    - 排行榜檢查使用 `li.here a`，取到的是頂層分頁「暢銷榜」而非 7日。改為 `ul.sub_list li.here > a`。
    - 內容簡介與目錄取到同一段文字（兩者都取到同一個 `.content`），因為 `find_parent("div", class_="mod")` 找到的是外層包裝而非區塊。改為 `h3` 的直接父節點區塊。
13. 解析結果（抽樣）與期望值一致（見「驗證結果」）。
14. ISBN 政策改為使用者決定的 option b（命中既有 Book 時 attach）。`db.py` 移除 `BookConflictError`，新增 `persist_new_product`；`run.py` 新增同一 Book 重複的檢查與 INFO log；`cli.py` 移除 `propagate=False`。
15. 測試：`tests/test_db_integration.py` 中舊的衝突測試改為 ISBN-13 attach、ISBN-10 attach（參數化）、ISBN-13 優先於 ISBN-10、同一 Book 兩次失敗。新增 `test_parsers_real_fixtures.py` 與 `test_e2e_real_fixtures.py`。第一次執行：127 passed。
16. `dotnet build`：0 Warning(s)、0 Error(s)。
17. 文件更新：`Docs/modules/crawler.md` §5、`Docs/data/data-model.md` §6、本報告、`crawler/tests/fixtures/README.md`。

## 驗證結果

### Issue #6 acceptance criteria

| 條件 | 結果 | 對應測試 / 說明 |
|---|---|---|
| 完整排行榜 → 100 筆 Bestseller，run = SUCCESS，exit 0 | ✅ | 真實 fixture：`test_e2e_real_fixtures.py::test_real_fixtures_run_writes_100_bestsellers_and_the_four_real_books`（100 筆、ranks 1..100、captured_at 相同、指向正確的 4 本書）；流程層級：`test_db_integration.py::test_full_ranking_success_writes_100_bestsellers` |
| 不足 100 筆或 URL 重複 → 失敗，原有 Bestseller 不變 | ✅ | 真實頁面衍生：`test_e2e_real_fixtures.py::test_derived_ranking_with_99_rows_fails_and_keeps_bestsellers`、`test_derived_duplicate_product_url_fails_and_keeps_bestsellers`；解析層：`test_parsers_real_fixtures.py::test_derived_ranking_with_99_rows_fails_validation`、`test_derived_ranking_with_duplicate_product_url_fails_validation` |
| 已存在的商品 URL 不觸發詳細頁抓取，Book metadata 不變 | ✅ | `test_db_integration.py::test_existing_urls_are_reused_without_detail_fetch_or_metadata_change`；端到端中 96 個既有商品的 detail 請求為 0（`fetcher.detail_calls()` 只含 4 個真實商品） |
| 新書欄位符合 data model；缺少的選填欄位存 NULL，不推測 | ✅ | 真實頁面：`test_e2e_real_fixtures.py::test_real_books_are_written_with_the_expected_columns`（0011062550 的 TOC 為 NULL、subtitle 皆 NULL）；衍生缺欄位：`test_parsers_real_fixtures.py::test_missing_publication_date_is_null_not_guessed`、`test_missing_language_row_is_null`、`test_missing_spec_row_means_no_page_count`、`test_missing_isbn_row_means_no_identifier`、`test_missing_toc_section_is_null`、`test_missing_cover_image_is_null` |
| 語言對照：繁→zh-TW、簡→zh-CN、英→en、日→ja、韓→ko、其他→NULL | ⚠️ 部分 | 對照函式：`test_normalize.py::test_map_language`；DB 寫入 zh-CN：`test_db_integration.py::test_new_book_columns_match_data_model_with_nulls_for_missing_fields`；真實頁面只有繁體（4 本皆 zh-TW）。簡體、英、日、韓的真實標籤未覆蓋（見未解決事項） |
| 榜單替換為 atomic transaction；中途失敗時舊榜單完整保留 | ✅ | `test_db_integration.py::test_failed_snapshot_replacement_keeps_previous_list` |
| `pytest` 通過 | ✅ | 見下方 pytest 摘要 |

### Part 2 具體驗證

| 項目 | 結果 | 測試 |
|---|---|---|
| 排行榜 fixture：100 筆、rank 1..100、100 個不重複商品 ID | ✅ | `test_ranking_fixture_yields_exactly_100_rows_ranked_1_to_100`、`test_ranking_fixture_passes_validation` |
| 排行榜固定位置（rank 1、8、12、17、100） | ✅ | `test_ranking_fixture_known_positions`（5 個參數） |
| 排行榜 URL 去除 `?loc=` 追蹤參數 | ✅ | `test_ranking_urls_drop_tracking_parameters` |
| 排行榜不是 7日分頁 → 失敗 | ✅ | `test_ranking_page_must_be_the_7_day_chart` |
| 4 個商品頁的具體期望值（標題、出版社、日期＋精度、語言、頁數、ISBN、貢獻者＋角色、目錄有無、本書分類、描述、封面） | ✅ | `test_detail_fixture_extracts_expected_values`（4 個參數） |
| 追蹤參數的商品網址可被正規化 | ✅ | `test_detail_parser_accepts_tracking_url_and_canonicalizes_it` |
| 商品頁缺標題 → 解析失敗（run 失敗） | ✅ | `test_derived_detail_without_title_is_a_parse_error`；端到端 `test_derived_new_product_without_title_fails_and_keeps_bestsellers` |
| ISBN 校驗碼錯誤 → 不寫入 | ✅ | `test_invalid_isbn_checksum_is_not_stored` |
| ISBN-13 命中既有 Book → 只新增 BOOKS_COM_TW source，既有 Book 不變，榜單指向既有 book_id 與新 source id | ✅ | `test_db_integration.py::test_new_product_with_known_isbn_attaches_source_to_existing_book[isbn13]`、`[isbn10]`（含 INFO log 斷言） |
| ISBN-13 優先於 ISBN-10 | ✅ | `test_db_integration.py::test_isbn13_match_takes_priority_over_isbn10_match` |
| 兩個排名列解析到同一 Book → 失敗，榜單不變 | ✅ | `test_db_integration.py::test_two_ranks_resolving_to_the_same_book_fail_the_run` |

### 指令與結果

- Python 測試：`~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q`
  - 摘要：`127 passed in 16.02s`
- `dotnet build`：成功（0 Warning(s)、0 Error(s)）。本次未修改任何 C# 或 migration。

### 真實 fixture 的抽樣結果（0011062863，政。望）

- title：政。望：前線五十年，從國安決策到世界現場的國家思考
- publisher：聯經出版公司；published_date：2026-09-17，precision DAY；language：zh-TW；page_count：320
- identifiers：ISBN_13 9789570881592；contributors：(1, 李翔宙, AUTHOR)；subjects：人文社科、政治、政治人物
- table_of_contents：有（以「序 五十年軍政生涯的省思」開頭）；description：有（以「五十年軍政歷練，見證國家一路走來。」開頭）；subtitle：NULL

## 執行指令

```text
# 測試（於 worktree 根目錄；需要 Docker 與 dotnet）
~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q

# 執行一次 crawler（於 crawler/ 目錄；需要真實的 DATABASE_URL）
cd crawler && DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<db> python -m books_crawler
```

退出碼：0 = SUCCESS、1 = FAILED（榜單不變）、2 = 設定錯誤（未設定 `DATABASE_URL`）。
注意：正式執行會以 `HttpFetcher` 直接請求博客來，目前會遇到 Cloudflare 驗證（見 issue #21），因此在 #21 決定方式前不應執行。

## 未解決事項與後續注意

### 給 #7 的接續點

- retry / skip / PARTIAL_SUCCESS 尚未實作。目前任一新商品的抓取或解析失敗即整次 FAILED。
- 接續點：`run._resolve_row`（單商品步驟）；`RunReport.skipped_count` 恆為 0；`format_report` 未輸出 skipped 清單。
- `persist_new_product` 每個商品一個交易，#7 包 retry 時，失敗的單商品交易已 rollback，不會留下部分寫入。

### 正式抓取博客來（issue #21）

- 博客來對 HTTP 請求回傳 Cloudflare 驗證。`HttpFetcher` 只是簡單實作，未調校。
- 正式方案（例如瀏覽器自動化）未決定，由 issue #21 處理。`Fetcher` 接縫已就緒，替換不需修改流程。

### 需要產品決策

1. **同一 Book 在一個榜單中出現兩次**（例如既有商品 A 與新商品 B 的 ISBN 都命中同一 Book）：目前 run FAILED，榜單不變，錯誤訊息指出衝突的排名。`bestsellers.book_id` 為 UNIQUE，因此無法同時放入兩列。替代方案包括：只保留排名較前者並跳過另一列（需要 #7 的 skip 機制與 PARTIAL 語意），或改變榜單 schema。待決定。
2. **本書分類的層級**：目前每一層分類都存為一個 subject（`人文社科`、`政治`、`政治人物`）。規格只說「本書分類」，未規定層級。待確認。
3. **既有商品的 `last_seen_at`**：不更新（規格未要求，且既有書不修改）。待確認。
4. **`contributor_order`**：1-based，與排行榜 rank 慣例一致。
5. **日期錨點**：MONTH／YEAR 的 `published_date` 以當月 1 日、當年 1 月 1 日儲存，精度由 `published_date_precision` 表示。
6. **內容簡介中的促銷徽章**：0010852315 的 description 開頭為徽章文字，原樣保存。是否需要清理，待決定。

### 真實 fixture 尚未覆蓋的情境

`crawler/tests/fixtures/README.md` 列出完整清單。仍未覆蓋：原文作者、編者、繪者、OTHER 角色、簡體中文與其他語言標籤、真實的缺 ISBN 商品、規格沒有頁數、年／年月精度的出版日期、無本書分類、多作者同一列。缺漏的情境以程式衍生的測試覆蓋其中部分（缺 ISBN、缺日期、缺語言、缺頁數、缺目錄、缺封面）；其餘情境待使用者另存頁面後補上。

### 其他

- `books_crawler` 的 logger 輸出至 stdout，並保留 propagate（測試使用 `caplog`）。
- 整合測試以 Docker CLI 啟動容器，未使用 Testcontainers 套件（依賴數較少）；若 CI 需要，可再評估。
- 封面 `src` 為博客來的 `getImage` 代理網址（含尺寸參數），原樣保存；若之後需要穩定的原始圖片網址，需另行決定。
