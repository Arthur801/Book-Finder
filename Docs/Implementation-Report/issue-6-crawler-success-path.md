# Issue #6 實作報告：Crawler 完整爬取成功的流程

- Issue：#6
- Branch：issue-6-crawler-success-path
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 範圍與進度

- **Part 1（核心）**：排行榜與詳細頁以外的所有流程（URL 正規化、ISBN、語言、角色、日期、排行榜驗證、DB 交易、榜單原子替換、run 流程與 log）。
- **Part 2（解析器與真實 fixture）**：使用者以瀏覽器另存 1 個排行榜頁與 4 個商品頁（2026-10-11）。實作 `parse_ranking_html` 與 `parse_detail_html`，以真實頁面驗證，並補上端到端測試。
- **Part 2 追加決策（使用者）**：新商品的 ISBN 命中既有 Book 時，只新增 BOOKS_COM_TW source 指向既有 Book，不因 ISBN 衝突而失敗（見「實作思路／ISBN 比對」）。
- **Code Review 修正（第三輪）**：依 review 清單修正（見「Code Review 與修正」）。使用者核准全部修正與 Q1–Q4 四項產品決策。
- 仍未完成：retry / skip / PARTIAL_SUCCESS（#7）；正式抓取博客來的方式（issue #21）。

## 變更檔案

### Part 1 與 Part 2（歷史）

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/crawler_books.py` | 刪除（Part 1） | 空白佔位檔，由套件取代 |
| `crawler/requirements.txt` | 新增（Part 1）／修改（第三輪） | 釘選依賴；第三輪加入 `testcontainers[postgres]==4.15.0` |
| `crawler/pytest.ini` | 新增（Part 1） | `testpaths = tests`、`pythonpath = .` |
| `crawler/.gitignore` | 新增（Part 1） | 忽略 `__pycache__/`、`.pytest_cache/` |
| `crawler/books_crawler/__init__.py`、`__main__.py` | 新增（Part 1） | 套件說明；`python -m books_crawler` 進入點 |
| `crawler/books_crawler/cli.py` | 新增（Part 1）／修改（Part 2、第三輪） | Part 2：移除 `propagate=False`（測試可用 `caplog`）。第三輪：`main(argv)` 與 `del argv` 移除，改為 `main(environ=None)` |
| `crawler/books_crawler/models.py` | 新增（Part 1）／修改（第三輪） | 第三輪：改為 StrEnum（見下方「第三輪」） |
| `crawler/books_crawler/urls.py` | 新增（Part 1）／修改（第三輪） | 第三輪：移除過時的 ASSUMPTION 段落，改為已對照真實頁面驗證的敘述 |
| `crawler/books_crawler/normalize.py` | 新增（Part 1）／修改（第三輪） | 第三輪：回傳值改為 StrEnum |
| `crawler/books_crawler/ranking.py` | 新增（Part 1）／修改（第三輪） | 第三輪：rank 1..100 檢查合併為單一 helper；`validate_ranking` 不再正規化 URL |
| `crawler/books_crawler/fetcher.py` | 新增（Part 1） | `Fetcher` Protocol（`get(url) -> str`）、`HttpFetcher` |
| `crawler/books_crawler/parsers.py` | 新增（Part 1 為 stub）／實作（Part 2）／重寫（第三輪） | 見下方「第三輪」與「解析器」 |
| `crawler/books_crawler/db.py` | 新增（Part 1）／修改（Part 2、第三輪） | 第三輪：`persist_new_source`、`find_book_by_isbn`；`replace_bestsellers` 同時更新 `last_seen_at`；移除 `BookAlreadyRankedError`、`PersistedProduct` |
| `crawler/books_crawler/run.py` | 新增（Part 1）／修改（Part 2、第三輪） | 第三輪：重複 Book 的判斷集中於此；StrEnum 狀態；移除 `ranking_url` 欄位與 `EXIT_CODES` 字典 |
| `crawler/tests/__init__.py` | 新增（Part 1） | 測試套件套件化 |
| `crawler/tests/conftest.py` | 新增（Part 1）／重寫（第三輪） | 第三輪：改用 testcontainers（見「測試 DB 方案」） |
| `crawler/tests/fakes.py` | 新增（Part 1）／修改（Part 2、第三輪） | 第三輪：新增由真實頁面衍生負面案例的函式（移除商品容器、額外 h1、第二組本書分類） |
| `crawler/tests/test_urls.py` | 新增（Part 1） | URL 正規化單元測試 |
| `crawler/tests/test_normalize.py` | 新增（Part 1）／修改（第三輪） | 第三輪：未對應語言標籤寫入 log 的 caplog 測試 |
| `crawler/tests/test_ranking.py` | 新增（Part 1）／修改（第三輪） | 第三輪：canonicalization 相關測試移至 parser 測試；新增 rank 與 snapshot 驗證測試 |
| `crawler/tests/test_fetcher.py` | 新增（Part 1） | HttpFetcher 單元測試（假 session） |
| `crawler/tests/test_run_unit.py` | 新增（Part 1）／修改（Part 2、第三輪） | 第三輪：移除 `ranking_url` 參數；stub 測試改為「非排行榜頁面 → ParseError、不開啟連線」 |
| `crawler/tests/test_db_integration.py` | 新增（Part 1）／修改（Part 2、第三輪） | 第三輪：見「驗證結果」中的新測試名稱 |
| `crawler/tests/test_parsers_real_fixtures.py` | 新增（Part 2）／修改（第三輪） | 第三輪：新增容器缺失、標題範圍、本書分類群組、行內徽章斷行、空白行等測試 |
| `crawler/tests/test_e2e_real_fixtures.py` | 新增（Part 2）／修改（第三輪） | 第三輪：新增「商品容器缺失 → run 失敗、榜單不變」 |
| `crawler/tests/fixtures/*.html`（5 個） | 新增（Part 2） | 使用者另存的真實頁面，未修改 |
| `crawler/tests/fixtures/README.md` | 新增（Part 1）／修改（Part 2） | 實際檔案、來源網址、擷取日期、覆蓋與未覆蓋的情境 |
| `Docs/modules/crawler.md` | 修改（Part 2、第三輪） | 第三輪：§5 暫定規則、last_seen；§7 本書分類規則（Q1）；§10 last_seen（Q2）；§12 新欄位 |
| `Docs/data/data-model.md` | 修改（Part 2、第三輪） | §5.2 `last_seen_at` 說明（Q2）；§6 ISBN 比對與暫定規則 |
| `Docs/Implementation-Report/issue-6-crawler-success-path.md` | 新增（Part 1）／修改（Part 2、第三輪） | 本報告 |

未變更：任何 C# 程式、EF migration。

### 第三輪（Code Review 修正）

| 檔案 | 主要變更 |
|---|---|
| `crawler/books_crawler/parsers.py` | 移除所有整頁 fallback；缺少 `.main_column` → `ParseError`；標題與封面只在商品容器內尋找；`_Row` 具名結構，`_first_value` 直接使用已拆出的值；本書分類讀取所有群組（Q1）；內容段落斷行規則（Q3） |
| `crawler/books_crawler/db.py` | `find_book_by_isbn` 只回傳 `IsbnMatch`（不決定）；`persist_new_source(attach_to_book_id=…)` 依呼叫端決定；`replace_bestsellers` 同一 transaction 更新 `book_sources.last_seen_at`（Q2） |
| `crawler/books_crawler/run.py` | 重複 Book 判斷只在 `_resolve_row` 一處（`DuplicateBookInRankingError`）；`RunStatus`／`EXIT_SUCCESS`／`EXIT_FAILED` 常數；移除 `RunDependencies.ranking_url` |
| `crawler/books_crawler/models.py` | `SourceType`、`PublishedDatePrecision`、`IdentifierType`、`ContributorRole`、`RunStatus` 為 StrEnum（值與儲存字串完全相同）；`IsbnMatch`；`BookDraft.subjects` 預設 `()`（與其他 tuple 欄位一致） |
| `crawler/books_crawler/ranking.py` | `_has_exact_ranks` 單一 helper；`validate_ranking` 不再正規化 URL（由 parser 正規化一次） |
| `crawler/books_crawler/normalize.py` | 回傳 StrEnum；未對應語言標籤的 log 測試 |
| `crawler/books_crawler/urls.py` | 過時的 ASSUMPTION 段落改為已驗證事實 |
| `crawler/books_crawler/cli.py` | `main(environ=None)` |
| `crawler/tests/conftest.py` | testcontainers；EF schema 於容器啟動前產生 |
| `crawler/requirements.txt` | `testcontainers[postgres]==4.15.0` |
| `Docs/modules/crawler.md`、`Docs/data/data-model.md` | 暫定標記（item 5）、Q1、Q2 |

## 實作思路

### 模組切分

- **純函式（無 IO）**：`urls`、`normalize`、`ranking`、`models`，以及 `parsers` 中的 HTML 解析函式（輸入為字串）。
- **IO 接縫**：`fetcher.Fetcher`（Protocol）；`run.RunDependencies` 注入 fetcher、兩個解析器、`connect` 與 `clock`。測試以 fake 取代 fetcher，並以真實解析器配合真實頁面。
- **DB 層**：`db.py` 只做查詢與寫入，不做業務決策。
- **決策層**：`run._resolve_row` 決定每個排名列如何解析（既有／附加到既有 Book／新建），以及是否違反「同一 Book 只能出現一次」。
- **流程**：`run.run_once` 串接上述元件，永不拋出例外，失敗以 `RunReport` 表示；`cli.main` 將 `RunReport.exit_code` 回傳。

### Fetcher 接縫

`Fetcher` 只有 `get(url) -> str`。`HttpFetcher` 提供 browser User-Agent、`Accept-Language`、timeout（connect 5 秒、read 20 秒）、第一次之後每次請求前延遲 1 秒（可注入 `sleep`）。非 200 或網路錯誤一律轉為 `FetchError`。未針對 Cloudflare 做任何調校。正式抓取方式由 issue #21 處理。

### 解析器

**排行榜頁**（`parse_ranking_html`）

- 確認條件是 `ul.sub_list li.here > a` 的文字為「7日暢銷榜」（頁面有多個 `li.here`），否則 `ParseError`。
- 100 筆排名為 `ul.clearfix > li.item`，且含 `p.no_list strong.no`。選單與分類項目沒有排名，會被忽略。
- 商品 URL 為該列第一個 `a[href*="/products/"]`，在此處正規化一次（去除 `?loc=` 追蹤參數）；無法正規化或沒有連結 → `ParseError`。

**商品詳細頁**（`parse_detail_html`）

- **範圍**：只讀取 `.main_column` 商品容器。容器不存在 → `ParseError`（run 失敗）。沒有任何整頁 fallback：頁面其他商品的清單使用相同標記，若讀取整頁可能混入他書的 ISBN 或日期。
- 標題：容器內的 `h1`（與 `og:title` 相同）。缺少 → `ParseError`。
- 商品資訊列為 `li`，形式 `<標籤>：<值>`。只讀取該列的**直接子節點**（來源 HTML 有未關閉的 `li`，見「假設修正」）。
- 出版社：`puballb` 連結文字。出版日期：`parse_published_date`（保留精度）。語言：`map_language`。規格：`(\d+)\s*頁`。ISBN：`normalize_isbn`（無效則不寫入）。
- 貢獻者：`a[href*="adv_author"]` 為姓名，列的標籤決定角色，順序為頁面出現順序（1-based），只在 `div.type02_p003` 區塊內搜尋。找不到區塊 → 不寫入貢獻者並記 log。
- 內容簡介／目錄：`h3` 所屬區塊的 `.bd > .content`，斷行規則見「Q3」。目錄只在區塊存在且有內容時保存。
- 本書分類：容器內所有 `ul.sort` 列中的直接 `a`，每一層都保存（Q1）。
- 封面：容器內 `img.cover` 且 alt 等於書名的 `src`（代理網址，原樣保存）。
- subtitle 永遠 NULL（`BookDraft` 沒有此欄位）。

### ISBN 比對與附加來源（使用者決定 option b）

- 新商品（BOOKS_COM_TW `source_url` 尚未存在）的比對順序：**ISBN-13 → ISBN-10**（data-model §6）。`db.find_book_by_isbn` 只回傳命中結果。
- **命中既有 Book**：`run` 先檢查該 Book 是否已被本榜單其他排名使用（見下），未使用則以 `db.persist_new_source(attach_to_book_id=…)` 只新增一筆 BOOKS_COM_TW `book_sources`（同一 transaction）。不修改該 Book 的 metadata、identifiers、contributors、subjects（不做 canonical merge）。榜單中此商品的 row 使用既有 `book_id` 與新的 source id。
- **未命中或沒有 ISBN**：建立新 Book（不依書名或作者相似度合併）。
- **同一 Book 只能出現一次**：`run` 維護本榜單已使用的 `book_id` 集合。若新排名列（既有 URL 或 ISBN 命中）解析到已在集合中的 Book，raise `DuplicateBookInRankingError`，run FAILED，榜單不變。檢查在任何寫入之前進行（attach 的情況下，檢查於 `persist_new_source` 之前）。
- 命中時記錄 INFO log：`attached BOOKS_COM_TW source to existing Book: rank=… url=… matched=ISBN_13:… book_id=…`。
- `existing_book_count` 包含 attach 的商品；`attached_source_count` 為其中的子集；`new_book_count` 只計建立的 Book。

### 決策（使用者於 review 後核准）

- **Q1 本書分類**：商品頁上**每一個** `本書分類` 群組中的**每一層**分類都保存為 subject，去重後依頁面順序保存（PK 為 `(book_id, subject, source_type)`）。規格只說「本書分類」；此為使用者決定。
- **Q2 `last_seen_at`**：每次成功 run 的榜單替換 transaction 中，將榜上所有 BOOKS_COM_TW 來源（既有與新寫入者）的 `last_seen_at` 設為本次 captured_at。這是來源紀錄的 metadata；Book 不變，「既有 Book 不被更新」的不變式仍成立。失敗的 run 不更新任何 `last_seen_at`（同一 transaction）。
- **Q3 描述與目錄的斷行**：只有 `<br>` 與區塊邊界（`div`、`p`、`li`、`ul`、`h1`–`h6`、`table`、`tr` 等）產生換行；行內元素（`strong`、`a`、`span`、`em`）不會切斷文字。來源檔案中的空白（包括 CRLF）視為空白。連續空白行收斂為一個空行。例：`<strong>2026</strong><strong>國際布克獎得主</strong>` 保持為同一行「2026國際布克獎得主」。促銷徽章文字保留，因為它是來源段落的一部分。
- **Q4 同一 Book 兩次 → run 失敗**：**暫定（temporary）**。於 #7 重新檢討，較可能的方向是跳過後一個排名（與 PARTIAL_SUCCESS 一致）。

### URL 正規化

- 商品網址為 `https://www.books.com.tw/products/<10 位數字>`，後面可能接 `?loc=P_0003_001`（排行榜）或 `?loc=hot_003`（熱門關鍵字區）。正規化去除 query、fragment 與結尾斜線，輸出 `https://www.books.com.tw/products/<id>`。
- 接受 `http`/`https`、`books.com.tw`、`www.books.com.tw`、相對路徑與協定相對網址；非商品網址一律拒絕。
- 排行榜 100 筆正規化後為 100 個不重複 URL（已由真實 fixture 驗證）。

### 正規化規則（data-model §2、§2.1、§5.3–§5.5）

- **ISBN**：移除 `-`、空白與各種連字號，轉大寫；ISBN-10 需 `\d{9}[\dX]` 且加權和 mod 11 = 0；ISBN-13 需 `97[89]\d{10}` 且加權和 mod 10 = 0。無效值不寫入並記 log。決策：ISBN-13 需 978/979 前綴（格式驗證）。
- **語言**：繁體中文→zh-TW、簡體中文→zh-CN、英文→en、日文→ja、韓文→ko；其他→NULL 並記 log（已有測試）。
- **貢獻者角色**：作者→AUTHOR、原文作者→ORIGINAL_AUTHOR、譯者→TRANSLATOR、編者→EDITOR、繪者→ILLUSTRATOR；去除尾端「：／:」後比對；其他→OTHER。
- **出版日期精度**：`2026/10/11`→DAY、`2026/10`→MONTH、`2026`→YEAR；其餘格式或不合法日期→`(NULL, NULL)`。決策：MONTH／YEAR 的 `published_date` 以當月 1 日、當年 1 月 1 日作為儲存錨點，真實精度由 `published_date_precision` 表示。

### 型別與詞彙

- 儲存詞彙以 `StrEnum` 表示（`SourceType`、`PublishedDatePrecision`、`IdentifierType`、`ContributorRole`、`RunStatus`）。值與資料庫字串完全相同（`BOOKS_COM_TW`、`ISBN_13`、`AUTHOR`、`DAY`、`SUCCESS`），可直接傳給 psycopg 並與字串比較。
- 名稱採用 `CONTEXT.md` 的詞彙：Book、Book Source、Bestseller。不使用「商品」指稱 Book。`persist_new_source`、`find_book_by_isbn`、`IsbnMatch`、`DuplicateBookInRankingError`。「商品頁」（detail page）指 HTML 頁面本身，仍可使用。

### 交易邊界

- 連線採 `autocommit=True`，所有寫入都以顯式 `conn.transaction()` 包住（若使用非 autocommit，讀取會隱含開啟交易，巢狀 `transaction()` 只會建立 savepoint，外層不提交）。
- **每個新 Book Source 一個交易**（`persist_new_source`）：建立 Book 的路徑寫入 `books`、`book_sources`、`book_identifiers`、`book_contributors`、`book_subjects`；attach 路徑只寫 `book_sources`。任一步失敗 → 整個 source 的所有列 rollback（見「驗證結果」）。
- **榜單替換一個交易**（`replace_bestsellers`）：`DELETE FROM bestsellers`、`INSERT` 100 列、`UPDATE book_sources SET last_seen_at`。任一步失敗即整體 rollback，舊榜單與舊 `last_seen_at` 保留。
- 失敗前已提交的新 Book Source 保留（各自的交易已提交），不影響既有榜單；下次 run 會以 URL 重用。

### 測試 DB 方案（第三輪）

- **選擇 testcontainers-python 4.15.0**（`testcontainers[postgres]==4.15.0`，已在 Python 3.14 安裝並通過測試）。理由：test-plan 指定 Testcontainers；context manager 保證清除：`__enter__` 在 `start()` 失敗時呼叫 `__exit__`，`stop()` 在容器未建立時安全；Ryuk 在 pytest 被強制結束時清除殘留容器。
- 驗證：全部測試完成後，`docker ps -a --filter label=org.testcontainers=true` 無任何容器。
- 行為變更：Docker 不可用時，整合測試會錯誤（不再 skip），以免遺漏失敗。
- EF schema 在容器啟動前產生（`dotnet build` + `dotnet ef migrations script --idempotent --no-build`），因此 schema 產生失敗不會留下容器。

### 流程（`run_once`）

1. 抓排行榜 → `parse_ranking` → `validate_ranking`（失敗即 FAILED，未開啟資料庫連線）。
2. 逐筆 `_resolve_row`：`find_source`；存在則檢查是否重複、重用 Book（不抓詳細頁）；不存在則抓詳細頁 → `parse_detail` → `find_book_by_isbn` → 檢查重複 → `persist_new_source`（建立或 attach）。
3. 每個排名列解析後，其 `book_id` 加入本榜單集合。
4. `validate_snapshot`（100 筆、rank 1..100 唯一、book_id 唯一）→ `replace_bestsellers`（同一 captured_at；同時更新 `last_seen_at`）。
5. 任何例外皆被捕捉為 FAILED，記錄 `error=<type>: <message>`，exit code 1。
6. 任一新 Book Source 的抓取或解析失敗 → 整次 FAILED（#7 之前的行為）。`_resolve_row` 即為 #7 包 retry / skip 的單列步驟。

### 日誌

每次 run 於 stdout 輸出一行 key=value：`run_id`、`started_at`、`finished_at`、`status`、`ranking_count`、`existing_book_count`、`new_book_count`、`attached_source_count`、`skipped_count`（恆為 0）、`exit_code`，失敗時加 `error`。`DATABASE_URL` 不被記錄。

### Schema 取得方式

- 整合測試於 session 開始時執行 `dotnet tool restore`、`dotnet build Book-Finder.csproj`、`dotnet ef migrations script --idempotent --no-build -o <tmp>`，並以 `utf-8-sig` 讀取（EF 產生的檔案帶 UTF-8 BOM）後套用到拋棄式容器。
- 爬蟲本身不執行 DDL（ADR-002）。資料表沒有 DB default，UUID 與時間戳皆由爬蟲產生。

## Code Review 與修正

Review 清單以下列編號列出。來源分類（Standards／Spec）未隨任務提供，故依編號列出。Standards reviewer 指出「Implementation-Report 未在 AGENTS.md 中登錄」，rebase 後 AGENTS.md 已包含此報告，屬誤判。

| # | 發現 | 處理 |
|---|---|---|
| A1 | `parsers.py` 的 `main = soup.select_one(".main_column") or soup` 在版面改變時整頁掃描，可能讀到他書的 ISBN 或日期（靜默產生錯誤資料） | 移除所有整頁 fallback；容器缺失 → `ParseError`；標題與封面只在容器內尋找；測試：`test_missing_product_container_is_a_parse_error_not_a_whole_page_scan`、`test_title_comes_only_from_the_product_container`、端到端 `test_derived_new_source_without_product_container_fails_and_keeps_bestsellers`（run 失敗、榜單不變） |
| A2 | 測試 DB 以 Docker CLI 管理，與 test-plan 指定的 Testcontainers 不符，且失敗時可能殘留容器 | 改為 testcontainers-python 4.15.0；EF schema 於容器啟動前產生；清除保證見「測試 DB 方案」；驗證無殘留容器 |
| A3 | 「商品」為 CONTEXT.md 排除的 Book 同義詞；`persist_new_product` 等命名不符 | 改名：`persist_new_source`、`PersistedSource`→（移除）、`find_book_by_isbn`、`IsbnMatch`、測試名稱改為 source-based（如 `test_new_source_with_known_isbn_attaches_to_existing_book`） |
| A4 | `urls.py` 的 ASSUMPTION 段落已過時 | 改為已對照真實頁面驗證的敘述 |
| A5 | §5 與 data-model §6 未標示「同一 Book 兩次 → 失敗」為暫定 | 已標示暫定，將於 #7 檢討 |
| B6 | 缺少「交易中途失敗 → 該書所有列都 rollback」的測試 | 新增 `test_failed_insert_of_a_new_book_rolls_back_all_of_its_rows`：identifiers 已寫入後，contributor 名稱超過 `varchar(255)` 造成失敗；驗證 books、book_sources、identifiers 皆無殘留，run 失敗，榜單不變 |
| B7 | 未對應語言標籤的 log 無測試；en/ja/ko 未經 DB 路徑驗證 | 新增 `test_unmapped_language_label_is_logged_and_stored_as_null`（caplog）與 `test_language_code_is_written_to_books`（5 個參數，含 en/ja/ko，經 `persist_new_source` 寫入） |
| B8 | 同一 Book 兩次的反向順序與「兩個新來源共用 ISBN」未測試 | 新增 `test_new_source_then_existing_url_for_same_book_fails_the_run` 與 `test_two_new_sources_sharing_an_isbn_fail_the_run`（另有 `test_existing_url_then_new_source_with_same_isbn_fails_the_run`） |
| C9 | `db.BookAlreadyRankedError` 與 `run.DuplicateBookInRankingError` 重複 | 合併為 `run.DuplicateBookInRankingError`；重複判斷只在 `run._resolve_row` 一處；db 只回傳匹配結果 |
| C10 | rank 1..100 檢查重複於 `validate_ranking` 與 `validate_snapshot`；URL 在 parser 與 `validate_ranking` 中各正規化一次 | `_has_exact_ranks` 單一 helper；URL 只在 parser 正規化一次 |
| C11 | `_first_value` 重新拆分標籤與值 | `_Row(label, value, li)` 具名結構；`_first_value` 直接使用 `row.value` |
| C12 | 推測性程式碼：`main(argv)`＋`del argv`、`RunDependencies.ranking_url`、`EXIT_CODES` 字典 | 移除 argv；移除 `ranking_url`（測試改用 `RANKING_PAGE_URL` 常數）；改為 `EXIT_SUCCESS`／`EXIT_FAILED` 常數 |
| C13 | 狀態、角色、識別碼類型以字串常數表示 | StrEnum（值完全相同）；測試以字串比較仍成立 |
| C14 | `subjects` 預設值與其他 tuple 欄位不一致（`field(default_factory=tuple)`） | 統一為 `()` |
| D-Q1 | 本書分類只取第一組、第一層以外的層級未保存 | 所有群組、所有層級，去重；測試 `test_subjects_from_all_groups_are_kept_once_in_page_order`；`crawler.md` §7 規則 |
| D-Q2 | `last_seen_at` 未更新 | 榜單替換 transaction 內更新榜上所有來源；測試 `test_existing_source_last_seen_advances_on_success_and_book_is_untouched`、`test_failed_run_leaves_last_seen_unchanged`、`test_failed_snapshot_replacement_keeps_previous_list_and_last_seen`；`crawler.md` §5、§10；`data-model.md` §5.2 |
| D-Q3 | 描述與目錄的斷行錯誤（`get_text("\n")` 在每個文字節點間插入換行，`2026` 與「國際布克獎得主」被拆開；來源 CRLF 也被當成換行） | 只有 `<br>` 與區塊邊界產生換行；來源空白先收斂；連續空白行收斂；測試 `test_inline_award_badges_stay_on_one_line_in_description`、`test_description_and_toc_have_no_runs_of_blank_lines` |
| D-Q4 | 同一 Book 兩次 → 失敗 | 維持現況，文件標示暫定 |

### 第三輪 pytest 與驗證

- `127 passed` → 本輪新增測試後為 **147 passed**（見「驗證結果」）。
- `dotnet build`：0 Warning(s)、0 Error(s)。

## 執行紀錄（Log）

### Part 1

1. `gh issue view 6` 失敗：GraphQL 錯誤，原因為 GitHub 已棄用 Projects (classic) 欄位。改用 `gh api repos/Arthur801/Book-Finder/issues/6`，成功。
2. 第一次抓取嘗試：以瀏覽器 User-Agent 對 `https://www.books.com.tw/web/sys_saletopb/books/?attribute=7` 發出單次請求，HTTP 403。回應標頭含 `cf-mitigated: challenge`、`server: cloudflare`；內容為標題「歡迎光臨博客來」的驗證頁。首頁 `https://www.books.com.tw/` 的 HEAD 請求同樣回傳 challenge。依指示停止抓取，未保存任何 HTML，暫存目錄已刪除，未嘗試其他 client 或標頭繞過驗證。
3. 搜尋既有 fixture：`git ls-files` 無 HTML fixture。
4. `.venv` 安裝：於 Python 3.14.4 解析為 psycopg 3.3.6、requests 2.34.2、beautifulsoup4 4.15.0、pytest 9.1.1，安裝成功。
5. `dotnet tool restore` 成功（dotnet-ef 10.0.12）；`dotnet build` 0 errors；`dotnet ef migrations script --idempotent` 產生 434 行 SQL，含 `CREATE EXTENSION IF NOT EXISTS vector;` 與 12 張表。
6. Part 1 pytest：94 passed。
7. 入口驗證：`cd crawler && python -m books_crawler`（未設定 `DATABASE_URL`）以 exit code 2 結束。註：巢狀 shell 中以 `echo $?` 查詢退出碼得到錯誤的 0（引號展開問題），改以工具回報的 exit code 確認為 2。

### Part 2

8. `gh api repos/Arthur801/Book-Finder/issues/21` 確認存在：「決定 production crawler 存取博客來的方式（Cloudflare challenge）」，state open。
9. 使用者另存 5 個檔案至 `crawler/tests/fixtures/`（未經程式修改）。以 BeautifulSoup 檢視結構：排行榜 `ul.clearfix > li.item` 共 100 筆；商品頁標題在 `h1`；資訊列為 `li`；目錄與內容簡介為 `div.mod_b` 中的 `h3` + `.bd > .content`。
10. 核對使用者的粗略 grep：0011062550 與 0011057581 的譯者列為未關閉的 `li`。0010852315 **沒有譯者列**，「譯者」只出現在目錄文字中。
11. 4 個商品都在排行榜中：0011062550 排第 1、0010852315 排第 8、0011062863 排第 12、0011057581 排第 17。
12. 首次解析發現兩個錯誤，已修正：排行榜檢查取到頂層分頁（改為 `ul.sub_list li.here > a`）；內容簡介與目錄取到同一段文字（改為 `h3` 的直接父節點區塊）。
13. ISBN 政策改為使用者決定的 option b。
14. 測試：第一次執行 127 passed。`dotnet build`：0 Warning(s)、0 Error(s)。

### 第三輪（Code Review 修正）

15. 依 review 清單修正 A1–C14、D-Q1–Q4（見「Code Review 與修正」）。
16. 首次以 testcontainers 執行時，描述第一段仍被拆行：原始 HTML 的 CRLF 與元素間空白被當成換行。修正：文字節點的空白先收斂，再加上 `<br>` 與區塊邊界的換行（D-Q3）。
17. 解析器的 `_text_with_line_breaks`：修正前 `get_text("\n")` 造成的拆行（`2026` 與「國際布克獎得主」分行）已由測試捕捉。
18. 全部測試於 testcontainers 下執行，無 skip。結束後 `docker ps -a --filter label=org.testcontainers=true` 無任何容器（僅保留既有的 `book-finder-db-1` 開發資料庫，未被測試使用）。
19. 清除暫存的探索腳本（`/tmp`，不在 repo 內）。

## 驗證結果

### Issue #6 acceptance criteria

| 條件 | 結果 | 對應測試 / 說明 |
|---|---|---|
| 完整排行榜 → 100 筆 Bestseller，run = SUCCESS，exit 0 | ✅ | 真實 fixture：`test_e2e_real_fixtures.py::test_real_fixtures_run_writes_100_bestsellers_and_the_four_real_books`；流程層級：`test_db_integration.py::test_full_ranking_success_writes_100_bestsellers` |
| 不足 100 筆或 URL 重複 → 失敗，原有 Bestseller 不變 | ✅ | `test_e2e_real_fixtures.py::test_derived_ranking_with_99_rows_fails_and_keeps_bestsellers`、`test_derived_duplicate_product_url_fails_and_keeps_bestsellers`；`test_db_integration.py::test_ranking_with_99_rows_fails_and_keeps_previous_bestsellers`、`test_duplicate_product_url_fails_and_keeps_previous_bestsellers` |
| 已存在的商品 URL 不觸發詳細頁抓取，Book metadata 不變 | ✅ | `test_db_integration.py::test_existing_urls_are_reused_without_detail_fetch_or_metadata_change`；端到端中 96 個既有來源的 detail 請求為 0 |
| 新書欄位符合 data model；缺少的選填欄位存 NULL，不推測 | ✅ | `test_e2e_real_fixtures.py::test_real_books_are_written_with_the_expected_columns`；`test_db_integration.py::test_new_book_columns_match_data_model_with_nulls_for_missing_fields`；衍生缺欄位的解析測試（見下表） |
| 語言對照：繁→zh-TW、簡→zh-CN、英→en、日→ja、韓→ko、其他→NULL | ✅ | 對照函式：`test_normalize.py::test_map_language`；未對應 log：`test_unmapped_language_label_is_logged_and_stored_as_null`；DB 路徑（5 個參數，含 en/ja/ko）：`test_language_code_is_written_to_books`；真實頁面只有繁體（4 本皆 zh-TW） |
| 榜單替換為 atomic transaction；中途失敗時舊榜單完整保留 | ✅ | `test_db_integration.py::test_failed_snapshot_replacement_keeps_previous_list_and_last_seen` |
| `pytest` 通過 | ✅ | 見下方 pytest 摘要 |

### 第三輪新增與更新的測試

| 項目 | 測試 |
|---|---|
| A1：商品容器缺失 → 解析失敗（不整頁掃描） | `test_parsers_real_fixtures.py::test_missing_product_container_is_a_parse_error_not_a_whole_page_scan`；`test_e2e_real_fixtures.py::test_derived_new_source_without_product_container_fails_and_keeps_bestsellers` |
| A1：標題只來自容器 | `test_parsers_real_fixtures.py::test_title_comes_only_from_the_product_container` |
| A4／排行榜 URL 正規化只在 parser | `test_parsers_real_fixtures.py::test_ranking_duplicate_detected_after_canonicalization`、`test_ranking_item_without_product_link_is_a_parse_error` |
| B6：中途失敗 → 該書所有列 rollback，run 失敗，榜單不變 | `test_db_integration.py::test_failed_insert_of_a_new_book_rolls_back_all_of_its_rows` |
| B7：未對應語言 log | `test_normalize.py::test_unmapped_language_label_is_logged_and_stored_as_null` |
| B7：en/ja/ko/zh-TW/zh-CN 經 DB 路徑 | `test_db_integration.py::test_language_code_is_written_to_books[英文／日文／韓文／繁體中文／簡體中文]` |
| B8：ISBN 命中後，既有 URL 指向同一 Book → 失敗 | `test_db_integration.py::test_new_source_then_existing_url_for_same_book_fails_the_run` |
| B8：既有 URL 之後的新來源命中同一 Book → 失敗 | `test_db_integration.py::test_existing_url_then_new_source_with_same_isbn_fails_the_run` |
| B8：兩個新來源共用 ISBN → 失敗 | `test_db_integration.py::test_two_new_sources_sharing_an_isbn_fail_the_run` |
| ISBN-13 命中既有 Book → 只新增 source，既有 Book 不變，榜單指向既有 book_id 與新 source id | `test_db_integration.py::test_new_source_with_known_isbn_attaches_to_existing_book[isbn13]`、`[isbn10]`（含 INFO log 斷言） |
| ISBN-13 優先於 ISBN-10 | `test_db_integration.py::test_isbn13_match_takes_priority_over_isbn10_match` |
| Q1：所有群組的所有層級，去重，依頁面順序 | `test_parsers_real_fixtures.py::test_subjects_from_all_groups_are_kept_once_in_page_order` |
| Q2：成功 run 更新榜上來源的 last_seen_at；Book 不變 | `test_db_integration.py::test_existing_source_last_seen_advances_on_success_and_book_is_untouched` |
| Q2：失敗 run 不更新 last_seen_at | `test_db_integration.py::test_failed_run_leaves_last_seen_unchanged`；`test_failed_snapshot_replacement_keeps_previous_list_and_last_seen`（替換中途失敗時 last_seen 亦保留） |
| Q3：行內徽章同一行；無三連續換行 | `test_parsers_real_fixtures.py::test_inline_award_badges_stay_on_one_line_in_description`、`test_description_and_toc_have_no_runs_of_blank_lines[4 個參數]` |

### 其他驗證

| 項目 | 測試 |
|---|---|
| 排行榜 fixture：100 筆、rank 1..100、100 個不重複商品 ID | `test_ranking_fixture_yields_exactly_100_rows_ranked_1_to_100`、`test_ranking_fixture_passes_validation` |
| 排行榜固定位置（rank 1、8、12、17、100） | `test_ranking_fixture_known_positions`（5 個參數） |
| 排行榜不是 7日分頁 → 失敗 | `test_ranking_page_must_be_the_7_day_chart` |
| 4 個商品頁的具體期望值 | `test_detail_fixture_extracts_expected_values`（4 個參數） |
| 衍生缺欄位：日期、語言、規格、ISBN、目錄、封面 → NULL，不推測 | `test_missing_publication_date_is_null_not_guessed`、`test_missing_language_row_is_null`、`test_missing_spec_row_means_no_page_count`、`test_missing_isbn_row_means_no_identifier`、`test_missing_toc_section_is_null`、`test_missing_cover_image_is_null` |
| ISBN 校驗碼錯誤 → 不寫入 | `test_invalid_isbn_checksum_is_not_stored` |
| 排行榜失敗時不開啟資料庫、不抓詳細頁 | `test_run_unit.py`（`test_incomplete_ranking...`、`test_duplicate_url_ranking...`） |
| 無 `DATABASE_URL` 時 exit code 2 | `test_run_unit.py::test_cli_without_database_url_returns_config_error` |

### 指令與結果

- Python 測試：`~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`
  - 摘要：`147 passed in 21.27s`
- `dotnet build`：成功（0 Warning(s)、0 Error(s)）。本次未修改任何 C# 或 migration。
- 容器檢查：`docker ps -a --filter label=org.testcontainers=true` 無任何容器。

### 真實 fixture 的抽樣結果（0011062863，政。望）

- title：政。望：前線五十年，從國安決策到世界現場的國家思考
- publisher：聯經出版公司；published_date：2026-09-17，precision DAY；language：zh-TW；page_count：320
- identifiers：ISBN_13 9789570881592；contributors：(1, 李翔宙, AUTHOR)；subjects：人文社科、政治、政治人物
- table_of_contents：有（以「序 五十年軍政生涯的省思」開頭）；description：有（以「五十年軍政歷練，見證國家一路走來。」開頭）；subtitle：NULL

## 假設修正（看過真實 HTML 後）

| 項目 | Part 1 假設 | 真實頁面 | 結果 |
|---|---|---|---|
| 商品 URL | `/products/<id>`，query 可丟棄 | `https://www.books.com.tw/products/0011062550?loc=P_0003_001`；熱門區為 `?loc=hot_003` | 符合，無需修改 |
| 出版日期格式 | `YYYY/MM/DD`、`YYYY/MM`、`YYYY` | `出版日期：2026/09/17` | 符合 |
| 語言標籤 | 繁體中文、簡體中文、英文、日文、韓文 | `語言：繁體中文` | 符合。簡體、英、日、韓未在真實頁面出現 |
| 貢獻者標籤 | 作者、原文作者、譯者、編者、繪者 | `作者：`、`譯者：` | 標籤符合。**譯者列 HTML 不完整**（未關閉 `li`），已改為只讀直接子節點；作者列的「追蹤作者」widget（`div.trace_box`）已排除 |
| 貢獻者的姓名位置 | 未假設 | `a[href*="adv_author"]` | 新增的定位規則 |
| 排行榜列位置 | 未假設 | `ul.clearfix > li.item`，排名在 `p.no_list strong.no` | 新增 |
| ISBN | ISBN-10 或 ISBN-13 | 4 頁皆只顯示 ISBN-13 | 符合 |
| 目錄 | 有無兩種狀態 | 0011062550 無目錄；其他 3 本有 | 符合。目錄文字中的「譯者」字樣不產生譯者列 |
| 本書分類 | 單一或多層 | `人文社科 > 政治 > 政治人物` | 多層；每層保存（Q1） |
| 封面圖 | `imageLinks` | `img.cover`（alt=書名），`src` 為代理網址 | 原樣保存 |
| 內容簡介 | 純文字 | 0010852315 開頭含促銷徽章文字 | 原樣保存（Q3） |

## 未解決事項與後續注意

### 給 #7 的接續點

- retry / skip / PARTIAL_SUCCESS 尚未實作。目前任一新 Book Source 的抓取或解析失敗即整次 FAILED。
- 接續點：`run._resolve_row`（單列步驟）；`RunReport.skipped_count` 恆為 0；`format_report` 未輸出 skipped 清單。
- `db.persist_new_source` 每個 source 一個交易，#7 包 retry 時，失敗的單列交易已 rollback，不會留下部分寫入。
- **Q4（暫定）**：同一 Book 出現兩次 → run 失敗。#7 需重新檢討，較可能的方向是跳過後一個排名（與 PARTIAL_SUCCESS 一致）。`crawler.md` §5 與 `data-model.md` §6 已標示暫定。

### 正式抓取博客來（issue #21）

- 博客來對 HTTP 請求回傳 Cloudflare 驗證。`HttpFetcher` 只是簡單實作，未調校。
- 正式方案未決定，由 issue #21 處理。`Fetcher` 接縫已就緒，替換不需修改流程。在 #21 決定前，不應對正式站執行 `python -m books_crawler`。

### 真實 fixture 尚未覆蓋的情境

`crawler/tests/fixtures/README.md` 列出完整清單。仍未覆蓋：原文作者、編者、繪者、OTHER 角色、簡體中文與其他語言標籤、真實的缺 ISBN 商品、規格沒有頁數、年／年月精度的出版日期、無本書分類、多作者同一列。部分情境（缺 ISBN、缺日期、缺語言、缺頁數、缺目錄、缺封面）已由程式衍生的測試覆蓋；其餘待使用者另存頁面後補上。

### 其他

- 封面 `src` 為博客來的 `getImage` 代理網址（含尺寸參數），原樣保存；若之後需要穩定的原始圖片網址，需另行決定。
- 貢獻者 `contributor_order` 採 1-based（與排行榜 rank 慣例一致；規格未明定）。
- MONTH／YEAR 的 `published_date` 以當月 1 日、當年 1 月 1 日作為儲存錨點，精度由 `published_date_precision` 表示。
- 行為變更：Docker 不可用時，整合測試現在會錯誤而非 skip（見「測試 DB 方案」）。

## 後續更新（2026-10-11）：fetcher、限制級跳過與連續錯誤中止

> 本節接續原報告，記錄 #7 與 #24 合併（PR #26）後依使用者指示所做的變更。上文保留當時的實作紀錄。架構決策檔中與 crawler fetcher 相關的 ADR（ADR-006 及之後的 ADR-007、ADR-008）已於 2026-10-11 刪除；上文若有引用，以及上文與本節有衝突時，現行規則一律以 `Docs/modules/crawler.md` 為準。

### 變更摘要

- **Fetcher**：每日流程預設改用 curl_cffi 的 Chrome fingerprint（`CRAWLER_FETCHER=curl`）。Playwright 改為可選的診斷 fetcher。細節見 `issue-24-playwright-fetcher.md` 的後續更新。
- **錯誤政策**：新書最多嘗試三次（含第一次）。限制級會員頁直接跳過，不重試，也不算錯誤。按 rank 計算連續一般錯誤，第 21 本才中止；成功、重用與限制級跳過都會把計數歸零。累計錯誤沒有上限，snapshot 也不再要求至少 90 筆。完整處理後只要有跳過就是 PARTIAL_SUCCESS，並保留原始 rank 的缺號。細節見 `issue-7-crawler-retry-skip.md` 的後續更新。
- **重複 Book**：較後面的排名若指向同一 Book，跳過該排名並計為一次一般錯誤，保留前面排名的資料。原報告「未解決事項」中 Q4（暫定）的「整次失敗」已不適用。
- **單書入口**：新增 `python -m books_crawler.first_book`。它仍會驗證完整排名，但只解析 rank 1；只寫 Catalog，不替換 Bestseller，也不更新既有來源的 `last_seen_at`（`crawler.md` §13.1，使用者要求）。
- **Snapshot 驗證**：仍檢查 rank 範圍與唯一、Book 唯一、來源必須是同一 Book 的 BOOKS_COM_TW source，並確認限制級排名不在 snapshot 中。連續錯誤由 run 流程檢查，不從 snapshot 筆數推斷。

### 主要檔案（目前責任）

| 責任 | 檔案（`crawler/books_crawler/`） |
|---|---|
| CLI 與每日／單書入口 | `cli.py`、`__main__.py`、`first_book.py` |
| HTML 解析與正規化 | `parsers.py`、`normalize.py`、`urls.py`、`models.py` |
| 排名驗證與匯入流程 | `ranking.py`、`run.py` |
| Catalog transaction／snapshot replacement | `db.py` |

沒有 C#、public API 或 schema migration 的變更。

### 真實抓取紀錄

使用者授權的本機真實抓取結果保存在 `crawler/artifacts/verification/top100-random-20261011T001507Z/summary.json`（artifact 不進 Git）。該次完整處理 100 個排名：重用 15、新增 66、限制級 13、一般錯誤 6，寫入 81 本 Book 與 81 筆 Bestseller。這次是在改成連續錯誤政策之前執行的，不能當作新中止條件的真實網站驗證；新政策只用離線測試驗證。EC2 排程與雲端 IP 行為尚未驗證。

### 驗證

2026-10-11 執行 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **258 passed in 38.64s**，沒有 skip。範圍涵蓋單元測試、真實 HTML fixtures、disposable PostgreSQL 整合測試與本機 Chromium 測試，測試不連線博客來。整合測試使用 Testcontainers 的 pgvector PostgreSQL，schema 由 EF migrations 產生，沒有對開發或正式資料庫套用 migration。`git diff --check` 通過。

### 未解決事項更新

- 「給 #7 的接續點」已由 #7 完成，錯誤政策後來又改為本節所述的連續錯誤規則。
- 「正式抓取博客來（issue #21）」：預設 fetcher 已改為 curl_cffi，但 EC2 實測仍未完成；實測前不得啟用排程（`Docs/deployment/deployment.md` §8）。
- 「真實 fixture 尚未覆蓋的情境」與「其他」維持不變。
