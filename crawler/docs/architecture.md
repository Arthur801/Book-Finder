# Crawler 架構與選型

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。核心來源依原始基準靜態閱讀；host 另依上述 merge-target snapshot；本次未執行 build、測試、部署、外部服務或真實抓取。

[Crawler authority](../../Docs/modules/crawler.md)、[資料契約](../../Docs/data/data-model.md)、[部署](../../Docs/deployment/deployment.md)、[測試策略](../../Docs/testing/test-plan.md)、[名詞](../../CONTEXT.md)；ADR-002 見 [ADR](../../Docs/architecture/architecture-decisions.md)。分類榜補 Catalog，不是 Bestseller。

| 責任／來源 | caller、callee 與 contract |
|---|---|
| [cli](../books_crawler/cli.py) | env → 驗證 → RunDependencies → runner；exit 0 成功／部分成功、1 FAILED、2 設定錯誤；finally close |
| [run](../books_crawler/run.py) | orchestration；注入 fetcher、parser、connect、clock、sleep；outcome 送 ledger；`_resolve_row` 是 Books adapter：提供 `fetch_draft`（detail 抓取與 parse，限制級為不重試的 skip）、`on_attempt_failed`（既有 attempt 行）與 URL drift 的 WARNING，其餘交給 `catalog_core/service`；不再持有 identity、touch、寫入或重試規則 |
| [fetcher](../books_crawler/fetcher.py)、[browser](../books_crawler/browser.py) | get(url)→HTML、close；FetchError 與 BrowserUnavailableError 分類 |
| [parsers](../books_crawler/parsers.py)、[normalize](../books_crawler/normalize.py)、[urls](../books_crawler/urls.py) | HTML→RankingRow／BookDraft；URL canonicalization、語言、日期精度；博客來角色標籤表 `ROLE_MAP` 與 `map_contributor_role` 屬於本 adapter（ISBN 與共用 `clean_text`／`normalize_role_label` 見 catalog_core） |
| [catalog_core](../catalog_core/) | provider-neutral 型別（models）、Source identity 矩陣（identity）、ISBN 正規化與 provider-neutral 文字 helper（normalize：`clean_text`、`normalize_role_label`，不含任何 provider 的角色詞彙）、Unicode 15.1 表（unicode_15_1）；books_crawler 使用，之後 Kingstone 共用 |
| [catalog_core/page_list](../catalog_core/page_list.py) | 共用的 page list 檔案規則（`load_url_list`）：UTF-8 BOM、註解、空行、trim、依 provider canonical 值去重並保留首見順序、可選上限；非法行只報檔名與行號、不回顯內容；由各 provider 提供 canonicalize 與錯誤用語 |
| [identity](../catalog_core/identity.py) | Source identity 矩陣（data-model §7.3）；純函式，DB 查詢由 `catalog_core/persistence` 提供 |
| [ledger](../books_crawler/ledger.py) | CatalogResolution→Catalog counts；RunLedger 再決定 RankingDecision、streak、snapshot、status；PagesLedger 只用 CatalogResolution；無 DB |
| [catalog_core/persistence](../catalog_core/persistence.py) | provider-neutral 持久化，每個函式明確接收 `provider`（無模組層級 PROVIDER）：`connect`、`provider_enabled`、`resolve_source_identity`（依 provider 查 external_id 與 URL）、`touch_source`（`GREATEST(last_seen_at, now)`，限定該 provider 的 Source；不符合或不存在時拋 `SourceTouchConflict` 且不改任何列）、`find_books_by_isbn`、`persist_new_source`（寫入 `external_id`）；autocommit + 顯式交易，不做 DDL |
| [db](../books_crawler/db.py) | Books.com.tw 專屬：`replace_bestsellers`（榜單替換與 BOOKS_COM_TW ownership 驗證）與 `SnapshotValidationError`；不 re-export catalog_core 函式 |
| [catalog_core/session](../catalog_core/session.py) | `DatabaseSession`（自 `books_crawler/session.py` 移入，provider-neutral）：連線 closed／broken 時以注入的 connect 重連（§13.1）；每次 run 一個，無模組層級狀態 |
| [catalog_core/service](../catalog_core/service.py) | provider-neutral item 解析 `resolve_item`：identity → EXISTING 時 touch（不抓 detail）或 NEW 時 fetch／parse → ISBN 比對 → 寫入；CONFLICT 不抓不寫；共用 attempts、clock 與 retry 語意；寫入失敗後下一次先重新解析 identity（commit 不確定）：EXISTING 回報已 commit、NEW 繼續有限重試、CONFLICT 以 `source_identity_conflict` 結束，不再查 ISBN 或寫入（v11 計畫 §5；博客來沒有 `external_id`，不會走到 CONFLICT）。依賴 `CatalogStore` port（Protocol）與呼叫端注入的 `fetch_draft` callback；不含 HTML、ranking、psycopg 連線，也不記 log（由呼叫端依回傳值與 `on_attempt_failed` 記錄）。`ItemFailed.identity_warning` 攜帶 identity 的 warning，touch 失敗時仍可回報 |
| [catalog_core/store](../catalog_core/store.py) | `SessionCatalogStore`：以 `DatabaseSession` 與 `catalog_core/persistence` 實作 `CatalogStore`；每個方法在呼叫時取 `session.conn`（重連後仍有效）；`touch_source` 遇 `SourceTouchConflict` 回傳 `False`，其餘例外（含 `psycopg.Error`）原樣上拋給 service |
| [page_list](../books_crawler/page_list.py) | books.com.tw 專屬：環境變數與預設檔路徑、books.com.tw 分類榜 URL 規則；檔案規則委派給 `catalog_core/page_list`（行為與訊息不變）；非法／空清單在請求前失敗 |
| [kingstone/urls](../kingstone/urls.py) | 金石堂 URL grammar（CB-07）：`canonical_list_url`（`/book/<2–4 字母>/?dis=list&page=<n>[&sort=<key>]`，代碼轉小寫；`sort=sa_desc`（預設）canonical 時移除，與省略 sort 相同，其他 key 保留）、`detail_url`、`km_code_from_href`、`km_code_from_detail_url`（只接受與 `detail_url` 完全相等的 canonical 詳細頁 URL）；相對與絕對 href 共用同一組 query 字元集；純函式，不連線 |
| [kingstone/page_list](../kingstone/page_list.py) | 金石堂分類列表頁檔（`crawler/kingstone-pages.txt`，最多 200 個 URL）；檔案規則委派給 `catalog_core/page_list`；重複行 INFO 記在 `kingstone.page_list` logger；尚未接到任何入口 |
| [kingstone/models](../kingstone/models.py) | 金石堂 adapter 的資料型別：`ListedItem`、`ListPage`，以及 `KingstoneParseError`、`ProductNotFound` |
| [kingstone/parse_list](../kingstone/parse_list.py) | 金石堂分類列表頁 HTML → `ListPage`（純函式）；契約見下方「金石堂 adapter」 |
| [kingstone/parse_detail](../kingstone/parse_detail.py) | 金石堂詳細頁 HTML → `BookDraft`（純函式）；soft 404 → `ProductNotFound`；契約見下方「金石堂 adapter」 |
| [kingstone/acquisition](../kingstone/acquisition.py) | 金石堂 HTTP acquisition（Phase 3）：`Transport` port、`CurlTransport`（curl_cffi Chrome、不跟隨 redirect、libcurl `MAXFILESIZE_LARGE` 與串流計量兩道上限）、`KingstoneFetcher`（URL 守門、pacing、重試、budget、回應分類；timeout、max attempts、size 上限可設定）；契約見下方「金石堂 adapter」 |
| [kingstone/config](../kingstone/config.py) | 金石堂 run 設定（Phase 4 M1）：`load_config(env) -> KingstoneConfig`，純函式、不讀檔不連網；讀取並驗證 `KINGSTONE_PAGES_FILE`、預算、HTTP 與回應大小設定；非法值 → `KingstoneConfigError`（`ValueError`，caller 對應 exit 2）；契約見下方「金石堂 adapter」 |
| [kingstone/ledger](../kingstone/ledger.py) | 金石堂 run 帳本（Phase 4 M1）：`KingstoneLedger`（逐頁 started／completed／skipped、卡片結果計數、budget 停止）、`KingstoneReport`、集中的 terminal status 函式 `decide_status`、`format_report`；純記帳、不做 I/O（只記 WARNING log）；契約見下方「金石堂 adapter」 |
| [kingstone/run](../kingstone/run.py) | 金石堂逐頁 run（Phase 4 M2）：`run_pages(deps, page_urls, run_id)` 永不 raise；`SoftBudget`、`KingstoneFetcherPort`、`KingstoneRunDependencies`；列表頁 → 卡片 → `catalog_core.service.resolve_item` → `KingstoneLedger`；詳細頁 fetch／parse 是 `fetch_draft` callback；契約見下方「Run（逐頁流程）」；目前沒有 caller（組裝是 Phase 5／6） |
| [catalog_core/html_text](../catalog_core/html_text.py) | 共用 HTML 區段文字抽取 `text_with_line_breaks`（自 `books_crawler/parsers.py` 原樣搬出）：只有 `<br>` 與區塊元素邊界換行、inline 元素不切行、連續空行收為一行；博客來詳細頁與金石堂詳細頁共用；會就地修改傳入的 node |
| [catalog_core/redact](../catalog_core/redact.py) | 共用 secret redaction（DSN、`password=`）：`books_crawler/redact.py` 只重新匯出它；金石堂 run 的錯誤訊息、skipped 頁與失敗書訊息、金石堂清單讀檔錯誤都經此處理 |
| [Dockerfile](../Dockerfile) | Python 3.14、UID 10001、runtime 依賴與清單 |
| [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) | host scheduling、SSM secret retrieval、daily/pages serialization、DB maintenance coordination、deployment state gate、Docker execution 與 pages schedule state |

## 金石堂 adapter（kingstone/）— 已實作的解析契約

現況：清單檔讀取、URL grammar、列表頁與詳細頁 parser 是純函式，不連網、不寫 DB；acquisition 經 transport 連網但不寫 DB；run 已把它們串成逐頁流程，經注入的 store 寫入 DB，但沒有任何入口（caller 待 Phase 5／6）。資料流：

```text
金石堂列表頁 URL ──► kingstone.acquisition.KingstoneFetcher.fetch_list_page ──► HTML
    ──► kingstone.parse_list.parse_list_html ──► ListPage(items: ListedItem…)
                                                  └─► kingstone.run（逐頁）：每張卡 → catalog_core.service.resolve_item（Existing 只 touch；New 才抓詳細頁）
金石堂詳細頁 URL ──► kingstone.acquisition.KingstoneFetcher.fetch_detail_page ──► HTML
    ──► kingstone.parse_detail.parse_detail_html ──► BookDraft（external_id = km_code）
                                                  └─► kingstone.run 的 fetch_draft callback（只在 New 時）→ catalog_core.service 寫入
```

設定（`kingstone/config.py`）與 run 帳本（`kingstone/ledger.py`）為純函式；逐頁 run（`kingstone/run.py`）已把兩者與 acquisition、catalog_core 接起來，但尚無任何入口（見下方「Run（逐頁流程）」）。

尚未實作：ingestion composition（真 fetcher 與 DB store 的組裝、`SoftBudget` 與 `budget_remaining` 的接線）、CLI／runner，以及 Dockerfile 納入 `kingstone/`（見 [backlog](backlog.md) CB-07）。URL grammar 與錯誤分類仍以 backlog CB-07 為來源契約。

**列表頁**（`parse_list_html(html, url) -> ListPage`）

- `url` 必須是 canonical 列表頁 URL，否則 `ValueError`（caller 錯誤，不是 parse error）。
- 必要結構：`section#allProducts` 與其內的 `#displayCSS`；缺少即 `KingstoneParseError`。
- 商品卡只取 `section#allProducts #displayCSS > .productGrid > .mod_prod_card[data-prodno]`；`#allProducts` 外的輪播卡、空頁巢狀 `section.prodSlider` 內的推薦卡不計。
- 空頁：沒有 `.productGrid`，且 `#displayCSS > .emptyCategory` 清理空白後為「此分類沒有相關商品唷！」→ 成功的零列頁（`empty=True`）。沒有 grid 也沒有此提示 → parse error。
- 每張卡：`data-prodno` 必須是 13 位數；`.coverbox a` 的 href 必須符合詳細頁 grammar（相對 `/basic/<km_code>/[?query]`，或同 origin 的絕對 URL）；連結的 km_code 必須等於 `data-prodno`。任一不符即 parse error。
- 刻意採用的 fail-closed／實作決定（非 CB-07 逐字要求，變更時同步此處與測試）：每頁超過 48 張 → parse error；有 `.productGrid` 但 0 張卡 → parse error；同頁重複的 km_code 只保留首見（重複卡仍逐一驗證）。
- 產出 `ListedItem`：`external_id` = km_code、`source_url` = `/basic/<km_code>/`（追蹤參數不進 URL）、`list_url` = 列表頁 URL。卡片的書名、作者、出版社、日期不讀；列表頁沒有 ISBN，所以 New Source 一律要抓詳細頁。
- `input#totalPages` 與「共計<span>n</span>筆」是 best-effort 的 report metadata，只寫入 `ListPage.total_pages`、`total_count`，不影響 `items`，也不跟分頁：缺少 → None；合法 → int；存在但格式無法解析（totalPages 非正整數、共計非純數字）→ None，並在 `kingstone.parse_list` logger 記一筆 WARNING（不回顯 HTML），商品卡照常處理。

**詳細頁**（`parse_detail_html(html, url) -> BookDraft`）

- `url` 必須是 canonical 詳細頁 URL（`kingstone.urls.km_code_from_detail_url`：`https://www.kingstone.com.tw/basic/<13 位數>/`），否則 `ValueError`。
- 身分來自第一個含 `Product` 字樣的 `application/ld+json` script（物件、`@graph` 或陣列皆可，取 `@type` 含 `Product` 者）。該 script 不是合法 JSON 即 parse error，因此損壞的商品區塊不會被誤判為 soft 404。
- 沒有 Product JSON-LD 時：`<title>` 清理後等於「金石堂」→ `ProductNotFound`（soft 404，不重試、不寫入）；其他情況 → `KingstoneParseError`。
- `sku` 必須等於 URL 的 km_code；`name` 必填（缺少、空白或非字串皆為 parse error）。`external_id` = km_code，`source_url` = 傳入的 URL。title 與 publisher 經 `clean_text`（收斂內部空白）。
- `publisher` ← `publisher.name`（選填）；`published_date` ← `datePublished`，僅接受有效的 `YYYY-MM-DD`，精度 `DAY`；格式不合或日期無效時記 WARNING 並為 None；`thumbnail_url` ← `image`（陣列取第一個，字串直接用；字串形式同樣接受）。
- ISBN：`isbn` 非空即採用，否則採 `gtin13`；經共用 `normalize_isbn` 正規化，有值才寫入 `identifiers=(ISBN,)`。不驗證前綴或 checksum。
- 語言來自規格表「語言」列：中文繁體 → `zh-TW`、中文簡體 → `zh-CN`；其他非空值 → None 並記 WARNING；列不存在 → None。**不使用** JSON-LD `inLanguage`。
- 頁數來自規格表「頁數」列：純數字且大於 0 才有值，否則 None。
- 作者（`li.basicunit` 中標籤為「作者：」）：取列內連結文字，排除「追蹤」、「?」與整段被括號包住的連結（原文姓名，例如「(Gao Junqing)」或「（某某）」；括號須成對且內部不含括號，否則照一般作者名處理）；文字以「、」拆分。值含 `/` 時，前段為角色標籤、後段為姓名，角色一律為 `OTHER`；無 `/` 者為 `AUTHOR`。金石堂不借用博客來的 `ROLE_MAP`：E0 只見「審訂/」，沒有可對應到 Catalog 角色的標籤，出現時再依 fixture 加入金石堂自己的對應。
- 譯者（標籤為「譯者：」）：取該列去掉標籤後的文字節點，排除文字為「追蹤」「?」的節點（與作者欄一致），以「、」拆分，角色為 `TRANSLATOR`。其他標籤（如繪者）的列不讀。`Contributor.order` 依文件順序從 1 編號。
- subjects：`.basic-category-breadcrumb a` 的文字依序去重，並去掉根節點「中文書」。
- description 取 `.pdintro .panelCon`，table_of_contents 取 `.catalog .panelCon`，兩者都經 `catalog_core.html_text.text_with_line_breaks`：只有 `<br>` 與區塊元素邊界產生換行，inline 元素不切行，行內空白收斂為一個空白，連續空行收為一行，頭尾空行去除。目錄保留出版社原文內容（含開頭的作者簡介／內容簡介／目錄字樣），只做與簡介相同的換行與空白正規化。區塊不存在 → None。description、table_of_contents 只供 AI，不公開。
- 目前刻意採用的 fail-closed／實作決定（非 CB-07 逐字要求，變更時需同步此處與測試）：JSON-LD `image` 為字串也接受；譯者列與作者欄同樣排除「追蹤」「?」；原文名括號須成對且內部不含括號。
- 只讀上述區塊；活動、相關主題、作者介紹與贈品區塊不讀。

**Acquisition**（`kingstone/acquisition.py`，Phase 3）

- 兩層：`Transport` port（`get(url, *, timeout, max_bytes) -> RawResponse`，另有 `close`）與策略層 `KingstoneFetcher`。`CurlTransport` 是唯一接觸 curl_cffi 的地方：`Session(impersonate="chrome", curl_options={CurlOpt.MAXFILESIZE_LARGE: max_response_bytes})`（`max_response_bytes` 預設 `MAX_RESPONSE_BYTES`）；每次 `get` 帶 `allow_redirects=False`、`stream=True`、`Accept-Language: zh-TW,zh;q=0.9`；TLS 驗證維持 curl_cffi 預設（開啟）。
- `KingstoneFetcher` 的依賴全部可注入：`transport`、`sleep`、`clock`（monotonic）、`wall_clock`、`sample_delay`（預設 uniform 3～10 秒）、`budget_remaining`（預設 `math.inf`，Phase 4 run 提供剩餘秒數）。公開方法：`fetch_list_page(url) -> str`、`fetch_detail_page(url) -> str`、`close()`。
- URL 守門（每次請求前；不通過即 `ValueError`，transport 未被呼叫）：列表頁必須 `canonical_list_url(url) == url`（`&sort=sa_desc` 不合格，因為 canonical 形式省略它）；詳細頁必須 `km_code_from_detail_url(url)` 非 None（帶 query 不合格）。兩者另明確要求 `https`、host 與 `kingstone.urls.SITE_HOST`（`www.kingstone.com.tw`）完全相等、無 userinfo、無 port；非字串一律拒絕。IP literal 不需另外判斷，因為它不可能等於 `SITE_HOST`。
- 等待：每次請求（含重試）前的等待 = `max(sample_delay() − 距上一次請求結束的秒數, retry floor)`，兩者取較大者，不相加。第一個請求沒有上一次請求，pacing 項為完整的 sample delay；retry floor 只在重試時非 0。
  - pacing 從上一次請求結束起算（parse 與 DB 時間計入）。
  - retry floor（backoff，或 429／503 的 Retry-After）從收到失敗回應（或例外）的當下起算，之後不因經過的時間而縮減。
- Retry：最多 3 次（含第一次）。重試範圍：curl 的 `Timeout` 類（含 `ConnectTimeout`）；`ConnectionError` 類（含 `DNSError`、無法連線 `COULDNT_CONNECT`、連線被 reset `RECV_ERROR`、沒收到回應 `GOT_NOTHING`）；HTTP 429、500、502、503、504。不重試：`SSLError`（含 `CertificateVerifyError`，以及 curl `SSL_CONNECT_ERROR`，即 TLS 握手失敗）；其他 transport 例外（例如 `IncompleteRead`／partial file、`HTTPError`／HTTP/2 stream 錯誤、`ProxyError`）。歸類依 curl_cffi `requests/exceptions.py` 的 `CODE2ERROR` 表確認。已知限制：TLS 握手中被 reset 若以 `RECV_ERROR` 回報，會歸為 `ConnectionError` 而被重試；本層沒有針對此分支的測試（E0 與測試皆不連網）。TLS 錯誤不重試的理由：憑證問題不會因重送而消失（計畫未明列，此為實作決定）。
- Backoff：retry N 的 floor 為 `backoff_seconds(N)`（第 2 次 5 秒、第 3 次 10 秒，`min(60, 5 * 2 ** (N - 2))`）。
- Retry-After（只在 429、503 且仍會重送時讀取）：秒數（`[0-9]+`，任何長度）與 HTTP-date 都支援；HTTP-date 以注入的 wall clock 換算，已過去的日期視為 0；無法解析的值忽略，只用 backoff。值大於 120 秒（含極長的數字）→ `RETRY_AFTER_TOO_LONG`，不提早重送。最後一次嘗試的 Retry-After 不讀取（沒有可延後的重送），該次直接以 `HTTP_STATUS`（attempts=3）失敗；此時原因分類可能失真（伺服器其實要求等待後重試，但最終只表達為 HTTP 狀態）。
- Budget：每次請求前檢查（包括不需等待的請求）：`budget_remaining() <= 0`，或等待 > `budget_remaining()` → `BUDGET_EXHAUSTED`，不睡、不送；`attempts` 為已送出的請求數。預設 `math.inf`（不限制）。
- 回應分類：200 → 嚴格 UTF-8 解碼，失敗為不重試的 `DECODE_ERROR`；3xx → `REDIRECT`（不跟隨、不重試；訊息只含 Location 的 path，列表頁 302 到 `/book/` 即分類不存在）；其他 4xx（含 403、404）與其他非 200 狀態 → `HTTP_STATUS`，不重試；可重試狀態用盡 → `HTTP_STATUS`（attempts=3）；body 超過 `max_response_bytes`（預設 5 MiB）→ `OVERSIZE`；可重試 transport 例外用盡 → `TRANSPORT`；其他 transport 例外 → `TRANSPORT`（不重試）。
- 大小上限三道：(1) `Content-Length` 超過上限 → `ResponseTooLarge`，不讀 body；(2) libcurl `MAXFILESIZE_LARGE` 超過時 libcurl 以 `FILESIZE_EXCEEDED`（63）中止，`CurlTransport` 對應為 `ResponseTooLarge`；(3) 串流計量超過 per-call `max_bytes` 即中止。第 (2) 道的選項有傳入、錯誤對應有測試；libcurl 在傳輸中是否確實依此中止（例如無 Content-Length 時）未以真實傳輸驗證（禁止連網），因此第 (3) 道是保證 5 MiB 記憶體上限的依據，第 (2) 道是額外保護。
- Cookie：curl session 在單次執行內以記憶體保存 `Set-Cookie`，並在後續請求送出（與博客來 fetcher 相同）；不寫檔、不跨 run；沒有 cookie 子系統（沒有持久化、管理或設定介面）。
- 失敗一律 raise `AcquisitionError(kind, message, attempts, status)`，`kind` 為 `AcquisitionFailure`（`REDIRECT`、`HTTP_STATUS`、`OVERSIZE`、`TRANSPORT`、`DECODE_ERROR`、`RETRY_AFTER_TOO_LONG`、`BUDGET_EXHAUSTED`）。`attempts` 是實際送出的請求數，budget 在第一次請求前失敗時為 0。錯誤訊息只含 URL、HTTP 狀態與 Location 的 path，不含 body、cookie 或其他 header 值；transport 例外只記錄型別名稱，不回顯其訊息。
- 常數（預設值）：`MAX_ATTEMPTS=3`、`REQUEST_TIMEOUT_SECONDS=30`、`BACKOFF_BASE_SECONDS=5`、`MAX_BACKOFF_SECONDS=60`、`MAX_RETRY_AFTER_SECONDS=120`、`MAX_RESPONSE_BYTES=5 MiB`、`MIN_PAGE_DELAY_SECONDS=3`、`MAX_PAGE_DELAY_SECONDS=10`、`RETRYABLE_STATUSES={429, 500, 502, 503, 504}`、`RETRY_AFTER_STATUSES={429, 503}`。
- 可設定的三個參數（Phase 4 M1，`KingstoneFetcher` 的可選建構參數，預設為上述常數，預設值下行為不變）：`timeout`（每次請求的 timeout 秒數，傳給 transport）、`max_attempts`（總請求數上限，含第一次；必須 ≥ 1，否則 `ValueError`；`1` 表示不重試）、`max_response_bytes`（body 上限：傳給 transport 的 `max_bytes`；每個回應的 body 都以它比對；也是 `CurlTransport` 建立 session 時的 libcurl `MAXFILESIZE_LARGE`）。由 `KingstoneFetcher` 建立的 `CurlTransport` 會收到 `max_response_bytes`；注入的 transport 與注入的 session 不受影響。
- 刻意的實作決定（計畫未逐字要求，變更時需同步此處與測試）：
  - 嚴格 UTF-8：200 body 不以替代字元解碼，失敗即 `DECODE_ERROR`。
  - `Accept-Language: zh-TW,zh;q=0.9`。
  - Content-Length 預檢（先於讀 body），並與 libcurl 上限、串流計量並列為三道大小上限。
  - TLS 錯誤不重試（見 Retry）。
  - 最後一次嘗試的 Retry-After 不讀，記為 `HTTP_STATUS`（分類可能失真，見 Retry-After）。
  - pacing 與 backoff、Retry-After 取較大者，不相加。
- log：logger `kingstone.acquisition`；每次送出請求一行 INFO `GET <url> status=<n> bytes=<n> attempt=<n>`（連線層或其他 transport 例外為 `error=<例外型別>`）；每次重試一行 WARNING。
- 不在本層：challenge、CAPTCHA、限制級頁的判斷（200 照常回傳，交給 parser fail closed）、cookie 持久化、Playwright、診斷檔（計畫 §6 要求限額、§7 有 `KINGSTONE_DIAGNOSTIC_MAX_BYTES`；尚未實作，留待 runner／production 整合，見 [backlog](backlog.md) CB-07）。


**設定**（`kingstone/config.py`，Phase 4 M1）

- `load_config(env: Mapping[str, str]) -> KingstoneConfig` 是純函式：只讀傳入的 mapping，不讀 `.env`、不讀檔、不連網。`KingstoneConfig`（frozen）欄位：`pages_file`、`soft_budget_seconds`、`hard_limit_seconds`、`http_timeout_seconds`、`http_max_attempts`、`max_response_bytes`。
- 鍵與預設：`KINGSTONE_PAGES_FILE`（經 `kingstone.page_list.resolve_pages_file`，預設 `crawler/kingstone-pages.txt`）；`KINGSTONE_SOFT_RUN_BUDGET_SECONDS`=3300；`CRAWLER_RUN_HARD_LIMIT_SECONDS`=3600；`KINGSTONE_HTTP_TIMEOUT_SECONDS`=`REQUEST_TIMEOUT_SECONDS`；`KINGSTONE_HTTP_MAX_ATTEMPTS`=`MAX_ATTEMPTS`；`KINGSTONE_MAX_RESPONSE_BYTES`=`MAX_RESPONSE_BYTES`。
- 驗證：秒數必須是有限的數字且 > 0；次數與位元組數必須是十進位整數且 ≥ 1（不接受小數、科學記號或正負號）；空白或只含空白的值視為未設定；`soft < hard`。非法值 raise `KingstoneConfigError`（`ValueError` 子類，caller 對應 exit 2），訊息點名 key。只有被範圍規則拒絕的有限數字會在訊息中回顯；非數字的值一律不回顯。
- 不在本模組：寫入政策 `KINGSTONE_WRITE_POLICY`（Phase 5）、診斷大小 `KINGSTONE_DIAGNOSTIC_MAX_BYTES`（Phase 6）、`CRAWLER_ALERT_COMMAND`（Phase 6）。

**Run 帳本與 terminal status**（`kingstone/ledger.py`，Phase 4 M1）

- `KingstoneLedger(page_urls)` 依清單順序記帳，一次只允許一頁開啟。呼叫順序：`page_started(url)`（頁已取得並解析）→ 每張卡一次 `record_item(url, result, source_url=, external_id=)`（`result` 為 `ItemResolved` 或 `ItemFailed`）→ `page_completed(url)`；頁無法取得或解析時改為 `record_page_skipped(SkippedPage)`；`stop_for_budget()` 之後不再開始或跳過任何頁。違反順序（未列出的 URL、重複處理、在開啟的頁之外記卡片、budget 之後開始頁）raise `ValueError`。
- 頁的狀態：completed（每張卡都已有結果）、skipped（`SkippedPage`：url、reason、message、attempts；reason 由 run 提供，帳本不解讀）、interrupted（已開始、未完成；`stop_for_budget` 或致命錯誤時仍開啟的頁）、not reached（清單中既未開始也未跳過的頁，`pages_not_reached = 清單數 − completed − interrupted − skipped`）。
- 卡片計數：`ItemResolved` 依 `CatalogResolution` 計入 `existing_source`、`imported`、`isbn_attached`、`ambiguous_created`；`ItemFailed` 計入 `failed` 並保存 `FailedItem`（list_url、source_url、external_id、reason、message、attempts）。`recovered_commit_count` 計 `recovered_commit=True`；`identity_warning_count` 計任何帶 `identity_warning` 的結果。`items_seen` 為 `record_item` 次數。
- `zero_card_pages`：完成、但 0 張卡的頁數（合法空頁，是成功頁）。
- **Useful progress**：至少一頁 completed。`decide_status(...)` 是唯一寫下 terminal 規則的地方，`KingstoneLedger.report` 只傳入計數：

| 條件 | status | `zero_progress_reason` |
|---|---|---|
| `error` 非 None（致命錯誤） | FAILED | None |
| 沒有 completed 頁，且清單為空 | FAILED | 清單沒有頁 |
| 沒有 completed 頁，且所有頁都被跳過 | FAILED | 所有清單頁都被跳過 |
| 沒有 completed 頁，且 budget 已停止 | FAILED | budget 在任何一頁完成前用盡 |
| 沒有 completed 頁，其他 | FAILED | 沒有清單頁完成 |
| 有 completed 頁，且有跳過頁、失敗書、interrupted 頁或 not reached 頁 | PARTIAL_SUCCESS | None |
| 其他（包含全部 Existing、成功頁全為 0 張卡） | SUCCESS | None |

- `RunStatus`（`SUCCESS`、`PARTIAL_SUCCESS`、`FAILED`）是 kingstone 自己的 StrEnum，不 import `books_crawler`。`KingstoneReport.exit_code`：FAILED → `EXIT_FAILED`（1），其餘 → `EXIT_SUCCESS`（0）；`EXIT_CONFIG_ERROR`（2）由 caller 的設定失敗使用。
- `format_report(report)`：一行 `key=value`，欄位順序固定（見 `format_report` docstring）；計數為整數，`budget_exhausted` 為 `true`／`false`；`zero_progress_reason`、`error` 為 JSON 字串或 `null`；`skipped_pages`、`failed_items` 為 `ensure_ascii=False` 的 JSON 陣列。訊息不在此層 redact：run 必須在傳入前處理（與 Books 的 `_failure` 相同責任）。
- 帳本只在記錄跳過頁與失敗書時寫 WARNING 到 `kingstone.ledger`；不寫其他 log，也不做 I/O。

**Run（逐頁流程）**（`kingstone/run.py`，Phase 4 M2）

- 入口：`run_pages(deps: KingstoneRunDependencies, page_urls, run_id=None) -> KingstoneReport`，永不 raise；fatal 錯誤進 `report.error`。`page_urls` 先依首見順序去重（清單檔已去重，這裡保持帳本的唯一性規則）。
- 依賴：`fetcher`（`KingstoneFetcherPort`：`fetch_list_page(url) -> str`、`fetch_detail_page(url) -> str`）、`store`（`CatalogStore`）、`budget`（`SoftBudget(seconds, monotonic)`：建立時記起點，`remaining()`、`exhausted()`（remaining ≤ 0））、`clock`（UTC，observed_at 與報告時間）、`sleep`（DB 重試退避）、`max_item_attempts`（預設 3）。
- **caller 必須把同一個 `budget` 交給真 fetcher**（`budget_remaining=budget.remaining`）。run 在每個清單頁與每張卡之前檢查 `budget.exhausted()`；fetcher 另在每次請求前檢查「等待時間是否超過剩餘預算」。兩道守門讀同一個時鐘，超出時都乾淨停止。真 fetcher 與 DB store 的組裝不在本模組（Phase 5／6）。
- 流程（清單順序）：每頁先 `fetch_list_page`；`AcquisitionError` 的 `BUDGET_EXHAUSTED` → `stop_for_budget()`，該頁為 not reached；其他 kind → `record_page_skipped`，reason 為 kind 的小寫（`redirect`、`http_status`、`transport`、`oversize`、`decode_error`、`retry_after_too_long`），attempts 為 fetcher 報告的值。`parse_list_html` 的 `KingstoneParseError` → skipped，reason `parse_error`，attempts 1。解析成功 → `page_started`；每張卡：先檢查 budget，再 `resolve_item`，結果交 `record_item`；頁內全部完成 → `page_completed`。
- budget 停止點（停止後不再發出任何請求）：(a) 清單頁之前：該頁與之後的頁 not reached；(b) 頁中、卡片之前：該頁 interrupted；(c) 詳細頁的 `BUDGET_EXHAUSTED`：該卡以 reason `budget_exhausted` 記為失敗（`failed_items`），然後該頁 interrupted；(d) 清單頁的 `BUDGET_EXHAUSTED`：同 (a)。正在進行的卡不會被中斷：檢查只在卡與卡之間與頁與頁之間。被停下的卡與頁沒有寫入，下一次 run 會再處理。
- 詳細頁不在 service 層重試（決定）：acquisition 已在 HTTP 層重試（最多 3 次，`MAX_ATTEMPTS`），若 service 再重試抓取，同一本書最多會發出 9 次請求。因此非 budget 的 `AcquisitionError` 轉為 `DraftFailure(kind 小寫, retryable=False)`，立即記為該卡失敗。service 的 attempts（`max_item_attempts`，預設 3）只用於資料庫失敗，且解析出的 draft 保留，不會為了資料庫重試而重抓詳細頁。退避為 1 秒、2 秒（`BACKOFF_BASE_SECONDS * 2**(n-2)`，n = 2、3）。
- 詳細頁的 `DraftFailure` reason：`product_not_found`（soft 404，`ProductNotFound`）、`parse_error`（`KingstoneParseError`，或下方防禦分支）、`budget_exhausted`、acquisition 的 kind 小寫。
- `external_id` 防禦：解析出的 `BookDraft.external_id` 必須等於卡片的 km_code。不符 → `parse_error`（單本失敗，不中止 run）。理由：parser 已用 URL 驗證 sku，而 URL 由卡片的 km_code 建立，不符只可能來自程式錯誤；把它當作單本失敗比中止整個 run 局部，並在 `failed_items` 留下證據。
- replay：沒有跨 run 的進度檔。重跑從清單開頭；Existing 只 touch（不抓詳細頁），未完成的 New 才抓。
- fatal 範圍：`store.resolve_source_identity` 拋出的 `psycopg.Error`（identity 查詢不重試）、其他未預期例外，以及 `ValueError`（URL 不合 grammar 等程式錯誤）。發生時 run 停止，`report.error` 為 `"<例外型別>: <訊息>"`，status FAILED；已 commit 的卡保留（每本書一筆交易）。卡片的 DB 失敗（寫入、ISBN 查詢、touch）不是 fatal，只使該卡失敗。
- redact：fatal 訊息、skipped 頁訊息、失敗書訊息與 log 中的 attempt 訊息，在進入帳本或 log 前經 `catalog_core.redact.redact`；帳本本身不 redact。
- identity warning（URL 漂移）：在該卡 resolve 完成後記一行 WARNING（`kingstone.run`），並由帳本計入 `identity_warning_count`。金石堂的 warning 在查詢時尚未有 attempt 行可排序，因此不像 Books 那樣在查詢時記錄。
- log：logger `kingstone.run`。DB 重試失敗一行 WARNING；FAILED 一行 ERROR；結束時一行 INFO `mode=kingstone <format_report>`。

## 選型、替代與代價

| 面向 | 現行依據 | 替代差異（本次分析，非 ADR 決策） | 代價／維護 |
|---|---|---|---|
| one-shot batch | ADR-002 | queue／常駐 worker 需新服務與重送協定 | host 排程與觀測；無失敗佇列 |
| curl 預設、browser 診斷 | crawler §12 核准決策 | browser 資源較高；禁止自動切換規避 | preset 與 HTML fixtures 回歸 |
| 循序節流與三次 retry | §13／12 | 並行增加來源負載並改 contract | 執行可能久，避免 backoff 重複等待 |
| URL identity、ISBN 正規化與 distinct 比對 | §6、data-model §7 | 模糊書名合併有 edition 誤判風險，未授權 | 只依 ISBN 值比對；命中 1 本才附加，附加只補 NULL；≥2 本建立新 Book |
| 連線斷開時重連、寫入前重新解析 | §13.1、§6.1 | 讀取（既有 Source 的 SELECT）不重連，維持 run FAILED；重連後若前次寫入已 commit，回報 EXISTING，原 resolution 無法還原；touch 匹配不到本 provider 的 Source（`SourceTouchConflict`）不屬資料庫錯誤，不重試，直接以 `source_identity_conflict` 跳過 | 連線以 psycopg 的 closed／broken 判斷；寫入重試前先 resolve_source_identity，避免重複插入 |
| ISBN NFKC 固定 Unicode 15.1 | data-model §7.1 | 使用 runtime 的 Unicode 資料會讓 16.0 新增的分解改變 key | 未指派 code point 分段保留；`catalog_core/unicode_15_1.py` 由 `.github/scripts/unicode_tables.py` 產生（CI `--check`）；啟動時檢查 NFKC(U+1E030)，低於 15.0 即 exit 2 |
| 每書與榜單分開交易 | §9／14.4 | 全 run 長交易會擴大鎖與失敗損失 | FAILED 仍可累積 Catalog |
| EF 唯一 schema owner | data-model §9 | Python 自管 DDL 造成雙 truth | DB integration 須使用真 EF schema |
| 兩種 ledger | 程式可見選擇；歷史 refactor 可查 | 混合 I/O 會使政策更難隔離 | 不可把 daily 限制套到 pages |
| Docker＋host cron | [target deployment §8](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/deployment/deployment.md) | systemd timer／scheduler 需另案 | 依賴 image 預載、狀態檔、時區與權限 |
| Deployment/crawler coordination | crawler run.lock → maintenance shared lock → state gate；deploy migration 用同一 lock 的 exclusive mode | 先讀 state 再鎖會讓 pause／migration 與啟動交錯 | shared lock 持有至 Docker 完成；timeout exit 3、paused／dirty exit 6、state 無法解析 exit 2；state 缺少保留 pre-CD gate 行為 |

## 核心不變條件

以下條件原列於 root `AGENTS.md` §1.3（`f6ac094` 以前），AGENTS.md 改為 router 後改由本模組持有；修改任一條件須先提出規格變更，不可靜默改行為。

- 每日取得博客來中文書 7 日 TOP 100；排行榜頁必須完整解析 100 筆，否則整次失敗。
- 博客來 Book Source 以商品 URL 判斷是否已存在；新來源依正規化 ISBN 對到的 distinct Book 數量決定附加或建立新 Book。既有 Book 不因每日榜單刷新重新抓完整 metadata。
- New Source 詳細頁最多嘗試 3 次（含第一次），仍失敗則跳過；限制級會員頁直接跳過、不重試、不算錯誤。連續一般錯誤超過 20 本才中止；進入榜單（含重用）與限制級均重設計數，榜內重複算一般錯誤，非連續錯誤無累計上限。
- Bestseller 只保留最新榜單；rank 保留博客來原始排名，被跳過的排名缺號、不重新編號。新榜單尚未成功驗證前，不破壞上一份有效榜單。
- Fetcher 預設 curl_cffi Chrome fingerprint（使用者 2026-10-11 核准），循序請求，每次請求（含重試）隨機等待目標 3～30 秒；保留 Playwright 診斷入口。
- 抓取政策（#108，使用者決定）：browser stealth、`navigator.webdriver` 修補、CAPTCHA 代解或代理 IP 輪替可以使用；目前實作沒有這些功能，是否採用見 deploy DEP-B01。
- 測試不連線博客來；真實抓取驗證須有當前任務授權。

## 邊界與差距

只寫 books、book_sources、book_identifiers、book_contributors、book_subjects、bestsellers。SQL 參數化；不寫 users、AI／推薦資料、不做 DDL。簡介／目錄可存但只能供 AI，Web 必須排除公開回應；crawler 不提供 HTTP。subtitle NULL，optional 不推測，ISBN 命中 1 本時只附加 Source 並依 §7.4 補 NULL（不做 canonical merge）；命中 2 本以上則建立新 Book。

榜單交易先驗證 source ownership 再 DELETE／INSERT（`last_seen_at` 已於逐項處理時獨立 touch）；schema 與 ledger 保證 rank／Book uniqueness。空 snapshot 合法。不含 cache；Web cache 行為不是此模組已驗證責任。時間採注入 UTC clock，排程採 epoch 與 UTC cron。沒有取消 token；EXIT trap 不能推論 SIGKILL 也會清理。

本里程碑（Kingstone P1 M2）對 Books 的唯一行為變更：existing Source 的 touch 改為 `last_seen_at = GREATEST(last_seen_at, now)`，時鐘倒退時不再把 `last_seen_at` 往回拉；touch 限定 BOOKS_COM_TW，Source 已不存在時視為 `source_identity_conflict` 跳過（不重試、不抓詳細頁）。其餘 Books 寫入內容不變（`external_id` 對 Books 草稿仍為 NULL）。

Host coordination 以 target wrapper 為準：先取 shared maintenance lock 才讀 state，與 deploy 的 exclusive migration lock 形成 concurrency boundary。`crawler.paused != null` 或 `schema.dirty is True` 在 SSM／Docker 前跳過；state 缺少只省略 state gate，maintenance lock 仍生效。Deployment state.json 與 pages-last-success 是不同 contract：前者保護部署／schema，後者只決定 pages 是否到期。鎖順序、exit 語意與既有測試見 [流程](workflow-diagram.md) 及 CR-T12-B。

Target 的 image 由 CD 依 release.json 管理 GHCR digest，[crawler.conf.example](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/crawler.conf.example) 中 `<digest>` 必須替換為實際值；不要把舊 Docker Hub 手動推送流程視為現行發布政策。

SSM 僅取 DB URL，log／JSON 遮罩；HTML 是原始頁面，PNG 可能含畫面資料，不能稱為全面去識別。目前沒有 stealth、CAPTCHA 代解與 proxy 輪替；政策上允許使用，見「核心不變條件」。

確認字面差距（#113 前的規格）：舊 §16.9 說 pages 不寫任何來源 last_seen_at，但 `_insert_source` 對新建／附加來源 INSERT 初始化 now；既有來源確實不刷新。見 CB-01，未確認功能 bug。artifact 無清理政策實作，deployment 已明示另管，屬 CB-02 改善提案。EC2、SSM／IAM、GHCR／CD、cron 安裝、來源可抓性本次未驗證（CB-03），不能由設定存在推定已部署。

金石堂（KINGSTONE）目前有清單檔、URL grammar、列表頁與詳細頁 parser、HTTP acquisition、設定、run 帳本與逐頁 run（見「金石堂 adapter」）；ingestion composition 與 runner 尚未實作，來源契約與計畫見 [backlog](backlog.md) CB-07。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
