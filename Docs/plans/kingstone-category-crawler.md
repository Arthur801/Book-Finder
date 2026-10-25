# Kingstone Crawler — v11 實作計畫（使用者提供分類頁清單）

> Baseline：原始 v10 為 `main @ cfb606eb15f23e781d48ffe381887057cd243dfb`；2026-10-25 依 `main @ de52793` 現況核對（見文末「現況核對紀錄」），同日依 E0 證據與使用者決定改為 v11。
> 來源：使用者提供的 Final Accepted Implementation Plan v10，加上 2026-10-25 的設計變更：**比照博客來分類榜，由使用者提供要抓的金石堂分類列表頁，crawler 不再解析分類層**。取代先前的修訂版（baseline `ee29e02`，留在 git 歷史）。
> **E0 已完成來源證據；程式實作待 E0 contract review 通過；production activation 待 P1–P5。**
> 本文件是實作計畫，不代表功能已實作、測試已通過或取得 production 授權。

## 1. 目標、現況與範圍

完成「使用者提供的金石堂分類列表頁→商品詳細頁→Catalog ingestion」。行為比照博客來分類榜（`python -m books_crawler.pages`、`category-pages.txt`）：清單由使用者維護，crawler 只讀清單上每一頁列出的書，不探索分類樹、不跟分頁。來源 acquisition／parsing 集中於 `crawler/kingstone/`，共用 identity、ISBN、NULL enrichment、transaction 與 retry recovery，不複製 core。

Baseline：PR3（#119）與 PR4（#123）已合併，KINGSTONE registry row 預設 disabled。**migration 011 已在 repo，production 也已套用（v0.0.7）**，schema 上已能寫入 KINGSTONE；本次不實作 migration，金石堂 runtime 仍須做 post-011 schema read-only preflight（§8）。Python persistence 已只寫 `source_code`、ISBN 只查 `ISBN` 型別，但仍依賴 module-global `PROVIDER=BOOKS_COM_TW`（`crawler/books_crawler/db.py`、`ledger.py`），需改為明確傳入 provider。現行 authority 依 AGENTS.md §3.2 為 module-local docs（`crawler/docs/*`、`deploy/docs/*`）；root `Docs/` 是 archived reference，只作歷史背景。

In scope：provider-neutral core、金石堂頁面清單／adapter／CLI、有限 acquisition、budget 與 replay、Docker／runner、writer fencing、report／alert hook、離線與 DB 測試、文件。

Out of scope：分類樹 discovery、自動跟分頁、跨 run 進度狀態檔（state.json、repair queue）、DDL／schema、金石堂 Bestseller、Offer／價格／庫存、登入與跨 run cookies、CAPTCHA 代解／proxy rotation、browser acquisition、平行爬取、item-level detail queue、mutation receipt／audit manifest／GC、自動資料回滾、新雲端服務。首次 canary 不啟用自動排程。

## 2. E0 — Source evidence（已完成）

2026-10-25 使用者授權有限真站抓取（循序、上限約 60 次、不登入、不代解 CAPTCHA、不用 proxy），實際使用 31 次，沒有 429、challenge、Retry-After 或登入頁。凍結結果寫在 `crawler/docs/backlog.md`「CB-07 來源契約」（尚未實作，實作後依實際行為移入 architecture／workflow-diagram），重點：

- Acquisition：`HTTP_ONLY`；origin 只有 `https://www.kingstone.com.tw`；循序請求，每次請求（含重試）前隨機等待 **3～10 秒**（使用者依 E0 證據決定）。
- 列表頁：`/book/<code>/?dis=list&page=<n>[&sort=<key>]`；商品卡在 `section#allProducts` 內的 `.mod_prod_card[data-prodno]`，每頁最多 48 張；頁碼超過總頁數時是合法空頁（「此分類沒有相關商品唷！」）。卡片沒有 ISBN，New Source 一定要抓詳細頁。
- 詳細頁：`/basic/<13 位 km_code>/`；JSON-LD `Product` 提供 sku（external_id）、ISBN、出版社、出版日、圖片；語言、contributors、頁數、目錄要從 HTML 取（JSON-LD 的 `inLanguage` 與 `author` 不可靠）。
- 錯誤：分類不存在回 302 → `/book/`；商品不存在回 200 soft 404（標題只有「金石堂」、沒有 Product JSON-LD）。
- 分類樹的觀察（`nav.nav1b_classlevel`、代碼長度不代表層級、子分類切分父分類）只保留為背景：v11 不實作 discovery，使用者可以在清單放任一層的分類列表頁。

E0 exit：fixture（`crawler/tests/fixtures/kingstone/`）、source contract 與 CR-K01 contract test 已在分支 `kingstone-e0-fixtures` 完成，兩軸 review 的修正後待使用者 review／merge。

## 3. 模組與型別邊界

```text
kingstone page list / acquisition / parser / run
                  ↓ typed contracts
catalog_core identity / normalization / service / persistence
                  ↓
PostgreSQL item transaction
```

| Module | 責任 |
|---|---|
| `crawler/catalog_core/{models,identity,normalize,persistence,service}.py` | provider、Source identity matrix、ISBN、CatalogResolution、NULL-only enrichment、touch、transaction、commit-uncertain recovery |
| `crawler/books_crawler/` | 博客來 parser、RunLedger、Bestseller、來源 response classification；改用共用 core，外部行為除 touch 單調化外不變 |
| `crawler/kingstone/{__main__,models,page_list,urls,parser,acquisition,run}.py` | 清單驗證、URL canonicalization、列表／詳細頁解析與分類、逐頁執行、budget、report；不含 Catalog SQL |
| runner／deployment | shared locks、writer fencing、watchdog、mounts、alert delivery |

共用 persistence 明確接收 provider／external_id，不讀 module-global `PROVIDER`。Provider HTML 不穿過 core interface；列表頁 URL 只屬 observation／job context。

- `ProviderCode`：至少 BOOKS_COM_TW、KINGSTONE。
- `ListedItem`：provider、canonical source URL、external_id、來源列表頁 URL。
- `SourceBookDraft`：provider／URL／external_id、title、optional publisher／日期與精度／language／description／目錄／頁數／thumbnail、identifiers／contributors／subjects。

## 4. 頁面清單

- 檔案：`crawler/kingstone-pages.txt`，或 `KINGSTONE_PAGES_FILE` 指定的路徑。格式沿用博客來 `page_list`：UTF-8（允許 BOM）、每行一個 URL、`#` 開頭為註解、空行忽略、前後空白去除、重複 URL（canonical 後）只保留第一次。
- 只接受 `https://www.kingstone.com.tw/book/<code>/?dis=list&page=<n>`，可另加 `sort=<key>`：
  - `code`：ASCII 字母 2～4 個，canonical 轉小寫。
  - `n`：正整數。
  - `key`：只能是頁面上提供的 `sa_desc`、`pu_desc`、`pu_asc`、`pr_desc`、`pr_asc`。
  - 其他 path、host、query 參數一律拒絕。
- 每個 URL 只抓那一頁，不跟分頁；要更多頁就在清單列出 `page=2`、`page=3`。
- 清單無效、空清單或超過 200 筆 → exit 2，不建立 fetcher、不發任何請求（200 筆上限：每頁至少一次請求，最大等待 10 秒時約 33 分鐘，留給詳細頁的 budget 才夠；要提高須重新計算）。
- 清單順序就是執行順序。

## 5. Catalog、交易與 replay

先依既有 matrix 同查 provider＋external_id／URL：Existing→touch、不抓 detail；New→detail、normalize、所有 ISBN 查 distinct Books。

| ISBN 命中 | `normal` | `new-books-only`（僅 canary） |
|---|---|---|
| 0／無 ISBN | 建 Book＋Source | 同左 |
| 1 | 附加 Source、只補 NULL；缺 AUTHOR 才補 AUTHOR，補 identifiers／來源 subjects | `POLICY_SKIPPED_EXISTING_BOOK`；不建 Source、不 enrichment |
| ≥2 | 新建 Book＋Source，不改 ambiguous Books | 同左 |

每個 New Source 的 Book／Source／補值／identifiers／contributors／subjects 在**同一 transaction**；commit 完整落地、rollback 零半套 mutation。Existing touch 獨立，原子執行 `last_seen_at=max(current, observed_at)`，確認恰為預期 provider Source。測正向、時鐘倒退、重複 touch、uncertain ACK。現行 `db.touch_source` 是 `SET last_seen_at = now WHERE id = …`（不單調、不檢查 provider），改共用 core 後博客來的 touch 也變單調；這是 Books 唯一的行為變更，須同步更新 `crawler/docs/architecture.md`、`workflow-diagram.md` 與 Books 測試。

Commit 結果不確定時丟棄／重連 connection，**下次寫入前重新 resolve identity，不盲目重播 transaction**：

- Existing：不重播，回報 `RECOVERED_COMMIT`；不要求重建原 IMPORTED／ISBN_ATTACHED 計數。
- New：依 shared recovery／transaction identity 保護與剩餘 budget 有限重試。
- Conflict／查詢不可用：不再寫該 item，記為該頁的 item 失敗。

**Replay 取代進度狀態檔**：每次 run 都從清單第一個 URL 開始。上次已 commit 的書在這次是 Existing（只 touch、不抓詳細頁），所以被 budget 中斷、crash 或單本失敗之後，下一次 run 會自然往前推進，不需要記錄做到哪裡。不建立跨資源 receipt log，也不承諾逐欄位 forensic rollback。

已知限制：清單前段若每次都有超過一次 run budget 的新書，後段 URL 會延後處理；report 要列出本次沒有處理到的 URL 數（`pages_not_reached`），由使用者調整清單順序或長度。

## 6. Acquisition 與安全

- HTTP：最多3次、request timeout30秒、backoff最多60秒、Retry-After最多120秒、response最多5MiB。retry限 timeout／connection reset／429／500／502／503／504；所有等待受 soft budget 限制。
- Pacing：循序請求，每次請求（含重試）前隨機等待 3～10 秒（E0 凍結）。
- Retry-After 超出可等待範圍時不得提早重送，該頁或該本記為本次失敗。以 fake clock 驗證 delay 與 budget。
- 每次請求前檢查 HTTPS、origin、無 userinfo／IP literal、核准 path grammar（§4 的列表頁、`/basic/<km_code>/` 詳細頁）。不跟隨 redirect：列表頁 302（分類不存在）是頁面失敗；沒有任意 HTML URL acquisition。
- 只用 HTTP，不新增 Playwright production dependency；遇到 challenge／CAPTCHA／限制級頁時以 parse error fail closed，收錄 fixture 後再定分類。不新增 cookie subsystem。
- 不輸出 DB URL／cookies／secret；只用必要 Catalog DB 權限，無 DDL。診斷有限額。

## 7. 執行流程、設定、budget 與 terminal status

逐頁流程（比照博客來 pages）：

1. 依清單順序 fetch 列表頁（最多 3 次）；失敗、302 或 parse error → 跳過該頁，記錄原因。
2. 解析 `#allProducts` 的商品卡（0～48 張）；合法空頁是成功的零列頁，不是跳過的頁。
3. 每張卡依 §5 處理；詳細頁 fetch／parse／write 共用最多 3 次嘗試；soft 404 直接跳過、不重試、不寫入。
4. 單本失敗不中止該頁或整次 run；不設連續錯誤上限（同博客來 pages）。

`crawler.conf`為金石堂設定來源；只在kingstone mode驗證，不讓Books新增必填金石堂設定。

| Key | Default |
|---|---|
| `KINGSTONE_PAGES_FILE` | `crawler/kingstone-pages.txt` |
| `KINGSTONE_WRITE_POLICY` | `new-books-only` |
| `KINGSTONE_SOFT_RUN_BUDGET_SECONDS` | 3300 |
| `CRAWLER_RUN_HARD_LIMIT_SECONDS` | 3600 |
| `KINGSTONE_HTTP_TIMEOUT_SECONDS` / `KINGSTONE_HTTP_MAX_ATTEMPTS` | 30 / 3 |
| `KINGSTONE_MAX_RESPONSE_BYTES` | 5MiB |
| `KINGSTONE_DIAGNOSTIC_MAX_BYTES` | 2MiB |
| `CRAWLER_ALERT_COMMAND` | dev可unset；host設定 |

外部工作前驗證：soft<hard、durations/counts>0、bytes finite。每次請求前檢查 soft budget：不足時不發請求，乾淨停止，剩下的頁與書留給下次 run replay。正在進行的單本 transaction 一律完成或 rollback，不在交易中途停止。

一個集中函式決定terminal：

| Status | 條件 | Exit |
|---|---|---|
| FAILED | fatal config／registry／schema／security contract、watchdog／orphan；或所有頁都被跳過（零 useful progress） | 1；config／provider-disabled維持2 |
| PARTIAL_SUCCESS | 無 fatal、有 useful progress，但有跳過的頁、失敗的書，或因 budget 有頁沒處理到 | 0 |
| SUCCESS | 所有頁都處理完，沒有跳過的頁或失敗的書；或 new-books-only 合法全 policy-skip、無 acquisition error | 0 |

`new-books-only`可零mutation但不可作為promotion到normal的證據；report須區分policy skip與真正零進度。

**Useful progress**：至少一頁成功解析，而且該頁的每張卡都已處理完（Existing touch、policy skip、新寫入、單本失敗都算處理完）。v11 穩定後常見整次 run 都是 Existing、只做 touch，這是正常的 SUCCESS，不是零進度。`zero_progress_reason` 只在所有頁都被跳過時填寫。

## 8. Runner、writer fencing 與報告

Invocation order：config→run.lock→maintenance shared lock／既有deployment gate→orphan check→DB secret→provider enabled→post-011 schema read-only preflight→讀取並驗證清單→逐頁處理→terminal report→alert delivery／container終止確認→放鎖。

provider／schema／清單驗證前無 Catalog mutation、無 HTTP；schema preflight失敗為`SCHEMA_PREREQUISITE_MISSING`、config failure、零HTTP／mutation。provider預設disabled。

待決（Phase 6）：runner 現有 `CRAWLER_ENABLED` 是整台 host 的開關，production 目前為 `false`（博客來封鎖 EC2，`crawler/docs/backlog.md` CB-03）；金石堂經 runner 也會被它擋下。Phase 6 須決定金石堂是否使用獨立的 host 開關，並同步 `crawler.conf.example`、deployment。

- runner新增`kingstone`；Books沿用`CRAWLER_IMAGE`，金石堂用`KINGSTONE_CRAWLER_IMAGE`（HTTP-only）。清單檔跟 `category-pages.txt` 一樣隨 image 發布，或由 host 以唯讀 mount 提供（Phase 6 決定）。
- 所有provider共享run.lock與maintenance shared lock；container固定name=`book-finder-crawler-active`、label=`com.bookfinder.role=catalog-crawler`、cidfile與mode/provider labels。
- running／restarting／paused writer阻擋start；exited／dead deterministic container安全清理後再啟動。
- migration取maintenance exclusive lock，檢查deterministic writer及legacy candidates；shared/exclusive lock避免inspect/start race。
- hard limit：stop實際container→bounded grace→必要時kill→inspect確認不再running→放鎖。無法證明writer終止→`ORPHAN_WRITER`，未來crawler／migration皆fail closed；不只kill docker client。

每run一份sanitized terminal JSON，輸出到 stdout，並原子寫入 artifacts mount 的 `kingstone/last-run.json`：run/provider/status/exit；pages listed／processed／skipped（含原因）／not reached；items listed／details fetched；existing／new Source、policy-skip、mutation／recovered commit；HTTP attempts／failures；zero_progress_reason、alert_reasons。

Host alert command為absolute root-owned executable，只收sanitized event JSON path，不收secret。FAILED、orphan、schema 問題、challenge 出現、成功解析的頁全部是 0 張卡（可能是網站結構改變）、`pages_not_reached` 連續多次大於 0 均須觸發；全部 Existing 的正常 run 不觸發。production須注入測試事件並由named owner確認收到；僅log不足，delivery失敗阻擋PRODUCTION_READY。

## 9. 實作順序與驗證

| Phase | 工作與完成條件 |
|---|---|
| 0 Evidence | fixtures、source contract、CR-K01 已完成；使用者 review 通過（E0 PASS）才開程式實作 |
| 1 Core | provider-neutral types／identity／normalize／persistence、monotonic touch、改Books caller；除 touch 單調化外 Books 行為不變；全Books regression PASS |
| 2 Adapter | 清單驗證與 URL canonicalization、列表頁／詳細頁 parser；fixture/unit/contract全離線 |
| 3 Acquisition | HTTP bounds／pacing／URL security；failure suite PASS |
| 4 Run | 逐頁流程、跳頁、budget 停止、replay、terminal status、report；run suite PASS |
| 5 Ingestion | composition、雙policy、commit recovery；post-011真DB integration／atomicity／replay／Bestseller protection PASS |
| 6 Operations | runner mode／清單檔來源／container identity／watchdog／legacy orphan guard／report／alerts；deploy tests PASS |
| 7 Acceptance | 全金石堂、必要DB零skip、Books、Docker smoke與docs；標記IMPLEMENTATION_VERIFIED |

自動測試不連真站；HTTP／clock／sleep可fake，DB用EF schema的disposable PostgreSQL。

| Acceptance／failure | 必測行為 |
|---|---|
| 清單→列表→detail→DB | 真fixture＋真parser＋真DB全流程；清單格式／去重／拒絕規則／200 筆上限、空頁、302、soft 404、encoding、URL↔sku 一致 |
| HTTP | retry／Retry-After／budget／oversize／off-origin／不跟 redirect／challenge fail closed |
| shared core／DB | 兩provider共用E/U完整matrix、0／1／≥2 ISBN、無ISBN、NULL／AUTHOR／identifiers／subjects／monotonic touch |
| Atomicity | Book／Source／fill／identifier／contributor／subject後與commit前注入失敗，零半套mutation |
| Uncertain commit／replay | 真commit＋ACK lost不二次mutation；真rollback可bounded retry；re-resolve unavailable不blind write；第二run Source不增加、既有detail=0；budget 中斷後第二 run 從清單開頭 replay 並推進 |
| Run／status | 全頁跳過→FAILED；部分跳過→PARTIAL_SUCCESS；budget 中斷與 `pages_not_reached`；全 policy-skip→SUCCESS；全部 Existing→SUCCESS 且不 alert；成功頁全為 0 張卡→alert |
| Host stop | watchdog stop/kill、精確container inspect、orphan blocking、migration fence |
| Books／Bestseller | daily/pages/first_book原contract與report/retry不變；Kingstone三種status前後Bestseller邏輯一致 |
| Docs | 五份crawler/docs與deploy/docs的module／CLI／config／status／path一致 |

## 10. Production gates 與 rollback

Production保持disabled，全部通過才activation：

- **P1**：011已部署（v0.0.7，2026-10-25 已完成）；剩金石堂 runtime 的 schema preflight 在 production 通過。
- **P2**：crawler只有必要Catalog read/write、無DDL權限。
- **P3**：production-like host驗證UID／mounts／Docker limits／watchdog／fencing。
- **P4**：注入critical event，named owner實際收到alert。
- **P5**：當次授權後controlled enable KINGSTONE，以new-books-only手動canary；需實際new Source、無duplicate／Bestseller／deploy異常。再controlled normal，使用合適資料驗證exact-one ISBN attach／NULL enrichment；全部skip不算promotion證據。手動 canary 最長佔用 run.lock 3600 秒，須避開博客來 cron（daily 20:00 UTC、pages 21:00 UTC）；金石堂若同樣封鎖 EC2，依 rollback 停用、不採規避技術。

首canary無自動schedule；normal驗證後才另處理排程啟用（可比照博客來 pages 的 72 小時排程）。

Rollback：disable KINGSTONE→確認writer停止→必要時回復runner/image tuple；Books維持既有enabled狀態。本次不做schema rollback；保留已commit Catalog，不自動反轉NULL enrichment。資料修復另行調查、比對backup與當前資料，禁止blind rollback。

**設計原則：沒有進度狀態檔；每次 run 從清單開頭 replay，靠 Source identity idempotency 讓已完成的書變成 Existing，不重抓詳細頁。不新增 receipt／audit subsystem。**

## 現況核對紀錄（2026-10-25，`main @ de52793`）

| # | 核對結果 | 處理 |
|---|---|---|
| D1 | 011 已合併並部署到 production（v0.0.7），原 baseline「011 是寫入前置」過時 | 修正 §1、§10 P1 |
| D2 | `db.py`、`ledger.py` 仍用 module-global `PROVIDER` | 計畫正確，Phase 1 照做 |
| D3 | `touch_source` 不單調、不檢查 provider | §5 註明 Books 行為變更與文件同步 |
| D4 | v10 沒定義金石堂請求間隔 | E0 凍結為 3～10 秒（§2、§6） |
| D5 | 新舊兩份計畫並存 | 本文件取代舊版，刪除根目錄副本 |
| D6 | runner 尚無 container name／label／cidfile／hard limit | 與計畫一致，屬 Phase 6 新增 |
| D7 | 共用 run.lock 符合 data-model §7.5；長 run 會讓博客來 cron 排隊 | §10 P5 註明避開時段 |
| D8 | archived `Docs/data/data-model.md` §7.2 的 ISBN 查詢已註明 011 後只查 `ISBN`，與程式一致 | 無需處理 |
| D9 | host `CRAWLER_ENABLED` 為全域開關，production 為 `false` | §8 列為 Phase 6 待決 |
| D10 | AGENTS.md 已改為 module-local docs 為 authority（PR #126），v10 原本要求更新 root `Docs/` 規格 | 全文改寫為 `crawler/docs/`、`deploy/docs/` |

## 設計變更紀錄（v10 → v11，2026-10-25）

| 項目 | v10 | v11（使用者決定） | 原因 |
|---|---|---|---|
| 抓取範圍 | 分類 discovery，sweep 全部 target | 使用者提供的分類列表頁清單，比照博客來分類榜 | E0 顯示全站書量是數十萬筆、完整 discovery 約 270 次請求，超過單次 run budget；改由使用者控制範圍 |
| 分頁 | 依 bounds 走分頁 | 每個 URL 只抓那一頁 | 行為可預測，工作量由清單決定 |
| 跨 run 狀態 | state.json v1、repair queue、`next_primary_index` | 拿掉，靠 replay＋identity | 清單固定、已完成的書變 Existing，下次 run 自然推進 |
| Pacing | 未定義 | 3～10 秒 | E0 31 次請求沒有任何節流訊號 |
| Browser | E0 決定 | 不用（`HTTP_ONLY`） | 頁面都是 server-rendered HTML |
| 非書分類排除 | E0 中曾決定以排除清單處理 | 不需要 | 範圍改由使用者的清單決定 |
