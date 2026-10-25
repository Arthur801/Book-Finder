# Kingstone Crawler — v12 實作計畫（使用者提供分類頁清單；crawler 在本地執行）

> Baseline：原始 v10 為 `main @ cfb606eb15f23e781d48ffe381887057cd243dfb`；2026-10-25 依 `main @ de52793` 現況核對（見文末「現況核對紀錄」），同日依 E0 證據與使用者決定改為 v11。
> 來源：使用者提供的 Final Accepted Implementation Plan v10，加上 2026-10-25 的設計變更：**比照博客來分類榜，由使用者提供要抓的金石堂分類列表頁，crawler 不再解析分類層**。取代先前的修訂版（baseline `ee29e02`，留在 git 歷史）。
> 2026-10-25 改為 v12：Phase 6 前使用者決定 crawler 改在本地 host 執行，經 SSH 轉發（EC2 只當跳板）直連 RDS；alert 只寫 log。變更見文末「設計變更紀錄（v11 → v12）」。
> **E0、Phase 1–5 已實作（PR #128–#142）；Phase 6–7 未實作；production activation 待 §10 gates。**
> 本文件是實作計畫，不代表功能已實作、測試已通過或取得 production 授權。

## 1. 目標、現況與範圍

完成「使用者提供的金石堂分類列表頁→商品詳細頁→Catalog ingestion」。行為比照博客來分類榜（`python -m books_crawler.pages`、`category-pages.txt`）：清單由使用者維護，crawler 只讀清單上每一頁列出的書，不探索分類樹、不跟分頁。來源 acquisition／parsing 集中於 `crawler/kingstone/`，共用 identity、ISBN、NULL enrichment、transaction 與 retry recovery，不複製 core。

Baseline：PR3（#119）與 PR4（#123）已合併，KINGSTONE registry row 預設 disabled。**migration 011 已在 repo，production 也已套用（v0.0.7）**，schema 上已能寫入 KINGSTONE；本次不實作 migration，金石堂 runtime 仍須做 post-011 schema read-only preflight（§8）。Python persistence 已只寫 `source_code`、ISBN 只查 `ISBN` 型別，但仍依賴 module-global `PROVIDER=BOOKS_COM_TW`（`crawler/books_crawler/db.py`、`ledger.py`），需改為明確傳入 provider。現行 authority 依 AGENTS.md §3.2 為 module-local docs（`crawler/docs/*`、`deploy/docs/*`）；root `Docs/` 是 archived reference，只作歷史背景。

In scope：provider-neutral core、金石堂頁面清單／adapter／CLI、有限 acquisition、budget 與 replay、Docker／本地 runner（SSH 轉發到 RDS）、writer fencing、report 與 log 型 alert、離線與 DB 測試、文件。

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
- 清單無效、空清單或超過 **400** 筆 → exit 2，不建立 fetcher、不發任何請求（v12：使用者清單有 328 頁，且本地手動執行不佔 EC2 上與博客來共用的鎖，上限由 200 調為 400、budget 一併放寬（§7）；400 頁的列表請求平均約 43 分鐘、最壞約 67 分鐘，其餘 budget 留給詳細頁）。
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
| `KINGSTONE_SOFT_RUN_BUDGET_SECONDS` | 7200（v12；原 3300） |
| `CRAWLER_RUN_HARD_LIMIT_SECONDS` | 9000（v12；原 3600；只套用 kingstone mode，博客來維持原值） |
| `KINGSTONE_HTTP_TIMEOUT_SECONDS` / `KINGSTONE_HTTP_MAX_ATTEMPTS` | 30 / 3 |
| `KINGSTONE_MAX_RESPONSE_BYTES` | 5MiB |
| `KINGSTONE_DIAGNOSTIC_MAX_BYTES` | 2MiB |

外部工作前驗證：soft<hard、durations/counts>0、bytes finite。每次請求前檢查 soft budget：不足時不發請求，乾淨停止，剩下的頁與書留給下次 run replay。正在進行的單本 transaction 一律完成或 rollback，不在交易中途停止。

一個集中函式決定terminal：

| Status | 條件 | Exit |
|---|---|---|
| FAILED | fatal config／registry／schema／security contract、watchdog／orphan；或所有頁都被跳過（零 useful progress） | 1；config／provider-disabled維持2 |
| PARTIAL_SUCCESS | 無 fatal、有 useful progress，但有跳過的頁、失敗的書，或因 budget 有頁沒處理到 | 0 |
| SUCCESS | 所有頁都處理完，沒有跳過的頁或失敗的書；或 new-books-only 合法全 policy-skip、無 acquisition error | 0 |

`new-books-only`可零mutation但不可作為promotion到normal的證據；report須區分policy skip與真正零進度。

**Useful progress**：至少一頁成功解析，而且該頁的每張卡都已處理完（Existing touch、policy skip、新寫入、單本失敗都算處理完）。v11 穩定後常見整次 run 都是 Existing、只做 touch，這是正常的 SUCCESS，不是零進度。`zero_progress_reason` 只在所有頁都被跳過時填寫。

## 8. 本地 runner、writer fencing 與報告（v12）

**執行位置**：crawler（博客來與金石堂）改在使用者的本地 host（WSL2／Linux＋Docker）手動執行，不再由 EC2 cron 啟動。資料路徑：

```text
本地 runner ──ssh -N -L 127.0.0.1:<port>:<RDS endpoint>:5432──► EC2（跳板，不存資料）──► RDS
本地 crawler container（--network host）── DATABASE_URL: host=<RDS endpoint> hostaddr=127.0.0.1 port=<port> sslmode=verify-full ──┘
```

- **連線**：沿用現有 `DATABASE_URL`、交易、commit 不確定時的 re-resolve 與 replay，程式不新增上傳／匯入流程。TLS 經轉發仍用 `verify-full`：libpq 的 `host` 填 RDS endpoint（憑證主機名比對）、`hostaddr` 填 `127.0.0.1`（實際連線），`sslrootcert` 用 RDS CA bundle。
- **Tunnel 生命週期**：runner 以 `ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=… -L 127.0.0.1:<port>:…` 開啟，確認轉發可用才啟動 container；run 結束（任何結果）關閉 tunnel。run 中途 tunnel 斷線 → DB 錯誤依現有規則處理（單本重試、identity 查詢失敗則 run FAILED），已 commit 的書保留，下次 replay 推進。SSH 金鑰與 EC2 主機設定在使用者本機，不進 repo。
- **DB secret**：本地不從 EC2 IAM role 讀 SSM。runner 以使用者本機的 AWS profile 讀同一個 SSM parameter，或讀本機 600 權限的檔案（擇一，Phase 6 實作兩者之一並寫入 `crawler/deploy/README.md`）；值不寫 log、不進 repo、只以 600 env file 傳給 container 並在用後刪除（沿用現有做法）。
- **開關**：沿用全域 `CRAWLER_ENABLED`（使用者決定），設在本地 host 的 runner 設定；EC2 上的 crawler cron 維持 `CRAWLER_ENABLED=false`，之後另案移除。
- **Image**：金石堂用 `KINGSTONE_CRAWLER_IMAGE`（HTTP-only，不含 Playwright；`crawler/Dockerfile` 新增 kingstone target），博客來沿用 `CRAWLER_IMAGE`。兩者由 CI／CD 建置並推到 registry，本地以 digest 拉取；手動驗證時可本地 build。
- **清單檔**：隨 image 發布（`crawler/kingstone-pages.txt`，使用者決定）；改清單即重新 build image。

**與 migration 的互斥（跨 host）**：原本 crawler 在 EC2 以 `db-maintenance.lock`（host flock）與 deploy 互斥，本地 runner 拿不到這把鎖，改為：

1. **DB advisory lock**（session-level advisory lock 在持有它的 DB session 結束時會被 PostgreSQL 自動釋放，所以契約是「lock holder 存活是 migration 執行的必要條件」）：
   - **deploy 端**：在 efbundle 執行前，以專用的 lock session（connection A）取 `pg_advisory_lock(<固定 key>)`（exclusive）；A 必須覆蓋 migration（efbundle 的 connection B）的全生命週期，B 結束後才釋放。
   - deploy 在 migration 期間持續確認 A 存活（例如定期 `SELECT 1`，加上 TCP keepalive）。**A 一旦中斷：立即中止 efbundle（SIGTERM→bounded grace→SIGKILL），把 deploy 標為 dirty／`FAILED_MIGRATION`，不得讓 migration 繼續**，也不自動重試；恢復走既有的人工流程。efbundle 的連線設定 `client_connection_check_interval`（PG 14+），讓 client 被中止後，server 端執行中的 statement 能盡快發現並 rollback。
   - deploy 在取 lock **之前**先把 EC2 deploy 狀態標成 migration 進行中（paused），完成後才清除；即使 lock 意外釋放，本地 runner 的啟動閘門（下方第 2 點）仍會拒絕啟動。
   - **crawler 端**：shared lock 綁在實際寫 Catalog 的 DB session 上。每次初次連線與每次 reconnect，都要先以 `pg_try_advisory_lock_shared(<同一 key>)` 取得 shared lock，才允許任何 mutation（含 touch）；取不到 → 不寫入，本次 run 停止（初次連線為 maintenance busy、run 中途為 FAILED），已 commit 的書保留、下次 replay。lock 的取得放在 `catalog_core.session` 的連線建立路徑，讓 Books 與金石堂共用。
   - 需要修改 deploy module 的 migration 步驟（`deploy/` 的 `machine.py`），屬 production deploy 行為變更，PR 須標明。
   - Phase 6 必測：crawler 持有 shared → migration 不可開始（deploy 等待或逾時失敗，不執行 efbundle）；migration 持有 exclusive → crawler 零 mutation；crawler reconnect → 重新取得 lock 才寫入、取不到即停止；deploy 的 lock holder 掉線 → efbundle 被中止、deploy 標 dirty、migration fail closed。
2. **deploy 狀態閘門**：runner 啟動前經 SSH 唯讀讀取 EC2 的 deploy `state.json`（paused／dirty／migration 進行中），與現行 `run-crawler.sh` 閘門同規則；讀不到或 paused／dirty → 不啟動。
3. **post-011 schema read-only preflight**：crawler 啟動時唯讀檢查必要欄位與 `source_providers`；失敗為 `SCHEMA_PREREQUISITE_MISSING`，零 HTTP、零 mutation。

**Invocation order（本地）**：config→本地 run.lock→EC2 deploy state 唯讀檢查→orphan check→DB secret→開 tunnel→container 內：Unicode／DB URL→config→清單→provider enabled→advisory shared lock→schema preflight→逐頁處理→terminal report→container 終止確認→關 tunnel→放鎖。provider／schema／清單驗證前無 Catalog mutation、無 HTTP；provider 預設 disabled。

**Writer fencing 與 watchdog（套用到所有 provider，使用者決定）**：

- 本地 runner 新增 `kingstone` mode；所有 provider 共用本地 run.lock。
- container 固定 name=`book-finder-crawler-active`、label=`com.bookfinder.role=catalog-crawler`、cidfile 與 mode／provider labels。running／restarting／paused writer 阻擋 start；exited／dead 的 deterministic container 安全清理後再啟動。
- hard limit：stop 實際 container→bounded grace→必要時 kill→inspect 確認不再 running→關 tunnel→放鎖。無法證明 writer 終止→`ORPHAN_WRITER`，之後的 crawler 一律 fail closed；不只 kill docker client。
- 博客來 daily／pages／first_book 的 runner 也套用相同 fencing；博客來 crawler 程式行為不變。

**報告與 alert（只寫 log，使用者決定）**：每次 run 一份 sanitized terminal JSON，輸出到 stdout，並原子寫入 artifacts mount 的 `kingstone/last-run.json`：run／provider／status／exit；pages listed／processed／skipped（含原因）／not reached；items listed／details fetched；existing／new Source、policy-skip、mutation／recovered commit；HTTP attempts／failures；zero_progress_reason、`alert_reasons`。

- 不設 `CRAWLER_ALERT_COMMAND`，不需要外部送達與 named owner 確認。`alert_reasons` 非空時，runner 另寫一行 `ALERT` 等級的 log（含 reasons 與 last-run.json 路徑）。
- 觸發：FAILED、orphan、schema 問題、出現 challenge、成功解析的頁全部是 0 張卡、`pages_not_reached` **連續 3 次** run 大於 0。全部 Existing 的正常 run 不觸發。
- **Bounded history**（只供 observability，不是進度狀態檔，不參與 replay）：

  ```text
  artifacts/kingstone/last-run.json          ← 最新一次結果（原子覆寫）
  artifacts/kingstone/history/<run-id>.json  ← 每次 run 的摘要，最多保留 20 份（超過刪最舊）
  ```

  `pages_not_reached` streak：以本次與前兩次 KINGSTONE run（依 `finished_at` 排序，取 history 最新的兩份）判定；任一次 `pages_not_reached == 0` 即重設；連續第 1、2 次 > 0 不 alert，第 3 次（含之後持續 > 0）alert。history 缺漏或讀不到的檔不算入 streak（寧可少報也不誤報），並在 log 記一行 WARNING。Phase 6 必測：第 1／2／3 次、streak 被 0 重設、history 上限與刪舊、壞檔略過。
- 診斷檔：parse error、無法分類的 200 頁、challenge 時存回應 HTML，單檔上限 `KINGSTONE_DIAGNOSTIC_MAX_BYTES`（2 MiB，超過截斷），存於 `artifacts/kingstone/diagnostics/`，只保留最近 20 份；不存 cookie 與 header 值。

## 9. 實作順序與驗證

| Phase | 工作與完成條件 |
|---|---|
| 0 Evidence | fixtures、source contract、CR-K01 已完成；使用者 review 通過（E0 PASS）才開程式實作 |
| 1 Core | provider-neutral types／identity／normalize／persistence、monotonic touch、改Books caller；除 touch 單調化外 Books 行為不變；全Books regression PASS |
| 2 Adapter | 清單驗證與 URL canonicalization、列表頁／詳細頁 parser；fixture/unit/contract全離線 |
| 3 Acquisition | HTTP bounds／pacing／URL security；failure suite PASS |
| 4 Run | 逐頁流程、跳頁、budget 停止、replay、terminal status、report；run suite PASS |
| 5 Ingestion | composition、雙policy、commit recovery；post-011真DB integration／atomicity／replay／Bestseller protection PASS |
| 6 Operations | 本地 runner（kingstone mode、SSH tunnel、DB secret、EC2 state 唯讀閘門）、HTTP-only image、DB advisory lock（crawler 每次連線／重連取 shared；deploy 以存活的 lock session 覆蓋 migration，掉線即中止並標 dirty）、schema preflight、container identity／watchdog／orphan guard（所有 provider）、last-run JSON＋bounded history、log alert（含 `pages_not_reached` 3 次 streak）、診斷檔、清單上限 400；§8 列出的 advisory lock 與 streak 必測案例、deploy／runner tests PASS |
| 7 Acceptance | 全金石堂、必要DB零skip、Books、Docker smoke與docs；本地 runner 經 tunnel 的 1 頁真站 canary（使用者已授權真站抓取）；標記IMPLEMENTATION_VERIFIED |

自動測試不連真站；HTTP／clock／sleep可fake，DB用EF schema的disposable PostgreSQL。

| Acceptance／failure | 必測行為 |
|---|---|
| 清單→列表→detail→DB | 真fixture＋真parser＋真DB全流程；清單格式／去重／拒絕規則／400 筆上限、空頁、302、soft 404、encoding、URL↔sku 一致 |
| HTTP | retry／Retry-After／budget／oversize／off-origin／不跟 redirect／challenge fail closed |
| shared core／DB | 兩provider共用E/U完整matrix、0／1／≥2 ISBN、無ISBN、NULL／AUTHOR／identifiers／subjects／monotonic touch |
| Atomicity | Book／Source／fill／identifier／contributor／subject後與commit前注入失敗，零半套mutation |
| Uncertain commit／replay | 真commit＋ACK lost不二次mutation；真rollback可bounded retry；re-resolve unavailable不blind write；第二run Source不增加、既有detail=0；budget 中斷後第二 run 從清單開頭 replay 並推進 |
| Run／status | 全頁跳過→FAILED；部分跳過→PARTIAL_SUCCESS；budget 中斷與 `pages_not_reached`；全 policy-skip→SUCCESS；全部 Existing→SUCCESS 且不 alert；成功頁全為 0 張卡→alert |
| Host stop | watchdog stop/kill、精確container inspect、orphan blocking、migration fence |
| Books／Bestseller | daily/pages/first_book原contract與report/retry不變；Kingstone三種status前後Bestseller邏輯一致 |
| Docs | 五份crawler/docs與deploy/docs的module／CLI／config／status／path一致 |

## 10. Production gates 與 rollback

Production 保持 disabled，全部通過才 activation：

- **P1**：011 已部署（v0.0.7，2026-10-25 已完成）；剩金石堂 runtime 的 schema preflight 經 tunnel 在 production 通過。**2026-10-25 通過**（canary run `2d933792`）。
- **P2**：crawler 使用的 DB 帳號只有必要 Catalog read/write、無 DDL 權限。由主 agent 提供唯讀 SQL，使用者經 tunnel 以 crawler 帳號執行並回貼結果（使用者決定）。**2026-10-25 通過**：原本 crawler 連線使用 RDS 主帳號 `bookfinder_admin`（`rds_superuser`、擁有所有表），改建專用帳號 `bookfinder_crawler`（7 張表的最小權限、連線上限 5、無 DDL、不擁有物件），SSM 參數改為此帳號；SQL 見 `crawler/deploy/local/sql/`。RDS 版本 17.11。
- **P3**：本地 host 驗證 UID／mounts／Docker limits／watchdog／fencing／tunnel 斷線行為，以及 deploy migration 與 crawler 的 advisory lock 互斥。
- ~~P4~~：v12 取消（alert 只寫 log，不需外部送達）。
- **P5**：使用者已授權真站抓取；controlled enable KINGSTONE，以 `new-books-only` 手動 canary，清單**只放 1 頁**；需實際 new Source、無 duplicate／Bestseller／deploy 異常。再 controlled `normal`，使用合適資料驗證 exact-one ISBN attach／NULL enrichment；全部 skip 不算 promotion 證據。**2026-10-25：`new-books-only` 1 頁 canary 通過**（`imported=39`、`policy_skipped=9`、0 失敗；production 核對無重複、博客來與 Bestseller 未變動；結果見 `crawler/docs/backlog.md` CB-07「Phase 7 進度」）；`normal` 尚未執行。本地執行不佔 EC2 的 run.lock，但仍不得與 deploy migration 重疊（advisory lock 保證）。金石堂若封鎖本地 IP，依 rollback 停用、不採規避技術。

不加排程（使用者決定）：canary 與之後的 run 都由使用者手動執行；排程另行討論。

Rollback：disable KINGSTONE→確認本地 writer 停止、tunnel 關閉→必要時回復 runner／image tuple；Books維持既有enabled狀態。本次不做schema rollback；保留已commit Catalog，不自動反轉NULL enrichment。資料修復另行調查、比對backup與當前資料，禁止blind rollback。

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

## 使用者決定（2026-10-25，Phase 6 前）

| # | 事項 | 決定 |
|---|---|---|
| 1 | 金石堂 host 開關 | 沿用全域 `CRAWLER_ENABLED` |
| 2 | 清單檔來源 | 隨 image 發布（`crawler/kingstone-pages.txt`）；使用者提供的 328 個 `/book/<code>/` 網址改寫為 `/book/<code>/?dis=list&page=1`，grammar 不變 |
| 3 | Image | 照計畫另做 HTTP-only `KINGSTONE_CRAWLER_IMAGE` |
| 4 | Writer fencing／watchdog | 套用到所有 provider |
| 5 | 部署與 alert | crawler 改在本地執行，SSH 轉發經 EC2 直連 RDS；alert 只寫 log |
| 6 | 診斷檔 | parse error／無法分類 200／challenge 存 HTML，2 MiB，保留最近 20 份 |
| 7 | `pages_not_reached` alert | 連續 3 次（bounded history，最多 20 份） |
| 8 | 其他 alert 條件 | 照計畫 |
| 9 | Canary 清單 | 1 頁 |
| 10 | P2／P5 | P2 由使用者執行主 agent 提供的唯讀 SQL；P5 允許真站抓取 |
| 11 | 排程 | 先手動，不加排程 |
| 12 | 清單上限 | 200 → 400，soft budget 7200 秒、hard limit 9000 秒（kingstone mode） |

## 設計變更紀錄（v11 → v12，2026-10-25）

| 項目 | v11 | v12 | 原因 |
|---|---|---|---|
| 執行位置 | EC2 cron＋`run-crawler.sh` | 本地 host 手動執行，SSH 轉發經 EC2 到 RDS | 使用者決定；EC2 IP 被博客來封鎖（CB-03），crawler 改由本地出網 |
| 與 migration 互斥 | EC2 `db-maintenance.lock`（host flock） | DB advisory lock（deploy 以存活的 lock session 覆蓋 migration、掉線即中止並標 dirty；crawler 每次連線／重連取 shared）＋SSH 唯讀讀 EC2 deploy 狀態（migration 期間為 paused） | 本地 runner 拿不到 EC2 的 host lock；session-level lock 會隨 session 結束自動釋放 |
| DB secret | EC2 IAM role 讀 SSM | 本機 AWS profile 讀 SSM 或本機 600 檔 | 本地沒有 EC2 IAM role |
| Alert | root-owned `CRAWLER_ALERT_COMMAND`、named owner 確認、P4 gate | 只寫 log（`ALERT` 行＋`alert_reasons`） | 使用者決定 |
| 清單上限／budget | 200 頁、3300／3600 秒 | 400 頁、7200／9000 秒（kingstone mode） | 使用者清單 328 頁；本地執行不佔共用鎖 |
| 排程 | normal 驗證後比照博客來 pages | 先手動，不排程 | 使用者決定 |
