# 誠品（Eslite）分類頁 crawler — v1 實作計畫

> Baseline：`origin/main @ 99f65d4`（2026-11-11）。來源：使用者提供的初步規劃，經 repo 現況核對與使用者決定（下表）整理成本版。
> **尚未實作任何部分**；本文件是實作計畫，不代表功能已實作、測試已通過或取得 production 授權。追蹤條目：`crawler/docs/backlog.md` CB-08。

## Context

金石堂 crawler（CB-07，plan v12）已完成 Phase 1–7，並在 production 啟用。下一個 provider 是誠品：比照金石堂，由使用者提供分類列表頁清單，crawler 逐頁讀取商品卡、抓新書的詳細頁，再經 `catalog_core` 寫入 Catalog，同一本書透過 ISBN 附加到既有的 Book（`normal`）。

使用者的初步計劃已核對 `origin/main @ 99f65d4`，以下前提都成立：

- `Domain/Entities/SourceCodes.cs` 有 `Eslite = "ESLITE"`；migration `20261024160045_MultiSourceCatalog` 已 seed `ESLITE`（`RETAILER`，`enabled=false`）；011 已在 production（v0.0.7）。**不需要 DDL 或 migration。**
- Python `catalog_core.models.ProviderCode` 只有 `BOOKS_COM_TW`、`KINGSTONE`，需要新增 `ESLITE`。
- `catalog_core/persistence.py:90` 的 `missing_schema_prerequisites()` 寫死檢查 `KINGSTONE` 列，需改成接收 provider。
- 金石堂寫死 provider 的地方：`kingstone/run.py:262`（`CatalogItem(ProviderCode.KINGSTONE…)`）、`ledger.py:131`、`artifacts.py:39,44`（目錄名與 `PROVIDER`）、`cli.py:73`、`config.py`（`KINGSTONE_*` env）、`acquisition.py`（`KingstoneFetcher` 綁定 `kingstone.urls`）。
- crawler DB 帳號 `bookfinder_crawler` 的權限以資料表為單位（`create-crawler-role.sql`），不分 provider，**不需要新增 GRANT**。

各 Phase 依慣例開 worktree 與 PR；計畫的變更記在文末「設計變更紀錄」。

## 使用者決定（2026-11-11）

| # | 決定 |
|---|---|
| 1 | E0 真站抓取授權比照金石堂：循序請求、上限約 60 次、不登入、不代解 CAPTCHA、不用 proxy；遇到 429、challenge 或登入頁立即停止。原始回應不 commit，只放整理過的 fixture。 |
| 2 | 只規劃 HTTP-only。若 E0 證實 HTTP-only 拿不到書目資料，停在 E0 gate，帶著證據回報，由使用者在「頁面自己呼叫的公開 JSON API」和「Playwright browser」之間選擇，再修改計畫。 |
| 3 | 分類頁清單由使用者提供（`crawler/eslite-pages.txt`），只抓清單列出的頁，不探索分類樹、不跟分頁；上限 400 筆。budget 與 hard limit 在清單長度確定後再訂（§7 待決定）。 |
| 4 | 首次 production canary 直接用 `normal`（1 頁）；程式預設值也是 `normal`。 |

## 1. 範圍

**In scope**：`ProviderCode.ESLITE`、provider-aware schema preflight；`crawler/eslite/` adapter（清單、URL grammar、列表頁／詳細頁 parser、acquisition policy、config、cli）；把金石堂的逐頁 run、ledger、acquisition 引擎、artifacts／alerts／diagnostics 抽成 provider-neutral 的共用元件（金石堂行為不變）；HTTP-only Docker target `eslite`；本地 runner 的 `eslite` mode；離線測試、disposable DB integration；文件；1 頁 production canary。

**Out of scope**：分類樹 discovery、自動跟分頁、進度狀態檔、DDL／migration、誠品 Bestseller、`book_offers`（價格、庫存）、登入與 cookies、CAPTCHA 代解、proxy、平行爬取、Playwright（除非 E0 gate 改決定）、排程、CD 推送 image（沿用 CB-07 backlog）、ASP.NET API／Razor 變更。

## 2. Phase 0 — E0 來源證據（真站，已授權）

在授權範圍內蒐集：

- 分類列表頁：2 個不同分類的第 1 頁、一個 `?page=3`、一個超過總頁數的頁、一個不存在的分類。
- 詳細頁：5～7 本（含多作者、有譯者、無 ISBN 或非書商品各一本，如果找得到）、一個不存在的商品 ID。
- `robots.txt` 當下版本（記錄 `/category`、`/product` 未被禁止）。

每個 fixture 都要回答以下問題，並寫進 `crawler/docs/backlog.md` CB-08「來源契約（E0 凍結）」：

1. **取得方式**：curl_cffi（Chrome impersonate、不跟隨 redirect）拿到的 HTML 是否包含商品卡與書目欄位（SSR／`__NUXT__` 等內嵌 state／JSON-LD），還是只有前端空殼。**若是空殼 → 停在 E0 gate（決定 #2）。**
2. **列表頁**：商品卡容器的 selector、每頁卡數、卡上是否有 ISBN；`page` 參數的語意、合法空頁長什麼樣子、排序參數有哪些、預設排序是否穩定。
3. **商品 identity**：URL 裡的 16 位數 ID 與頁面上「誠品貨碼」是否相同；`external_id` 採用哪一個（預設候選為 URL ID，因為卡片上就拿得到）；canonical 詳細頁 URL 的形式。
4. **詳細頁欄位**：`BookDraft` 每個欄位的來源（HTML 或 JSON-LD 哪個可靠）、作者／譯者標籤、出版日期精度、語言、頁數、目錄、封面、分類麵包屑；推薦商品、相關書籍區塊如何排除。
5. **錯誤形態**：分類不存在、商品不存在（HTTP status 或 soft 404）、redirect 目標；有無 Retry-After、challenge。
6. **Pacing**：觀察到的回應時間，提出 pacing 區間（預設沿用金石堂的 3～10 秒），交使用者確認。

產出：`crawler/tests/fixtures/eslite/`（含 README 說明來源與時間）、CB-08 來源契約、`test_eslite_fixture_contract.py`（只讀 fixture，鎖定上面的觀察）。**E0 gate**：使用者 review 來源契約後才開始 Phase 1 以後的程式。

## 3. 模組邊界

```text
eslite/{urls,page_list,parse_list,parse_detail,acquisition,config,cli}   kingstone/（同樣的檔案，改為呼叫共用元件）
                         ↓ CategoryAdapter（provider 專屬的 parse／URL／錯誤分類）
catalog_core/category_run   逐頁 orchestration、SoftBudget、ledger、terminal status
catalog_core/http_acquisition   Transport、CurlTransport、重試、Retry-After、pacing、budget、size 上限
catalog_core/run_artifacts      last-run JSON、history、alerts、diagnostics（以 provider 目錄區分）
                         ↓
catalog_core/service.resolve_item → SessionCatalogStore → PostgreSQL（不變）
```

| 元件 | 動作 |
|---|---|
| `catalog_core/{service,identity,session,store,normalize,page_list,html_text,redact,migration_lock}` | 直接重用，不改 |
| `catalog_core/models.py` | 加 `ProviderCode.ESLITE`；`ListedItem`、`ListPage` 從 `kingstone/models.py` 移到這裡（kingstone 重新匯出，import 路徑不變） |
| `catalog_core/persistence.py` | `missing_schema_prerequisites(conn, provider)`，檢查該 provider 的 `source_providers` 列；caller（`kingstone/cli.py`）傳 `KINGSTONE` |
| `catalog_core/category_run.py`（新） | 從 `kingstone/run.py` 抽出：`SoftBudget`、`run_pages(deps, adapter, page_urls, run_id)`；`CategoryAdapter` protocol 提供 `provider`、`parse_list`、`parse_detail`、`ParseError`／`NotFound` 型別、`list_page_label(url)`（診斷檔命名）、logger 名稱前綴 |
| `catalog_core/category_ledger.py`（新） | 從 `kingstone/ledger.py` 抽出：`CategoryLedger`、`CategoryReport`、`RunStatus`、`decide_status`、`format_report`；`provider_code` 必填 |
| `catalog_core/http_acquisition.py`（新） | 從 `kingstone/acquisition.py` 抽出：`Transport`、`CurlTransport`、`AcquisitionError`／`AcquisitionFailure`、重試與 Retry-After、pacing、budget 引擎；provider 傳入 `FetchPolicy`（允許的 host、列表頁與詳細頁 URL 守門、回應分類、pacing 區間） |
| `catalog_core/run_artifacts.py` 等（新） | 從 `kingstone/{artifacts,alerts,diagnostics}.py` 抽出，以 provider 目錄名（`kingstone`／`eslite`）參數化；alert 規則（含 `pages_not_reached` 3 次 streak）不變 |
| `catalog_core/run_config.py`（新） | 共用的 budget／HTTP／size／write policy 驗證，以 env 前綴（`KINGSTONE_`／`ESLITE_`）參數化；soft < hard 檢查保留 |
| `kingstone/*` | 改成薄的接線層：保留所有現有模組、類別名（`KingstoneLedger`、`KingstoneFetcher`、`KingstoneReport` 為別名或子類）、logger 名稱、env key、CLI、exit code、last-run JSON 欄位與 log 行 |
| `eslite/*`（新） | `urls`、`page_list`、`models`（`EsliteParseError`、`ProductNotFound`）、`parse_list`、`parse_detail`、`acquisition`（只有 `FetchPolicy`）、`config`、`cli`、`__main__` |

**抽離原則**：先抽離、再接誠品。抽離 PR 不改任何金石堂行為，驗收方式是「金石堂測試一行不改就全部通過」，再加上一個 golden test：同一組 fake 輸入下，抽離前後的 terminal record JSON 與 `format_report` 輸出完全相同。

## 4. 頁面清單與 URL（E0 後凍結細節）

- `crawler/eslite-pages.txt` 或 `ESLITE_PAGES_FILE`；檔案規則委派 `catalog_core/page_list.load_url_list`（BOM、註解、空行、trim、canonical 後去重、保留順序）；上限 400 筆；無效、空清單或超過上限 → exit 2，不發任何請求。
- 暫定列表頁 grammar：`https://www.eslite.com/category/<level>/<id>[?page=<n>]`，`level`、`id` 是十進位整數，`page` 為正整數，`page=1` 的 canonical 形式在 E0 後決定；其他 host、path、query 一律拒絕。允許的排序參數依 E0。
- 暫定詳細頁：`https://www.eslite.com/product/<16 位數 ID>`；只接受從卡片 href 建出的 canonical URL。
- 清單順序就是執行順序；每個 URL 只抓那一頁。

## 5. Catalog 與交易（沿用，不改）

完全沿用 `catalog_core.service.resolve_item` 與 plan v12 §5：Existing（provider＋external_id／URL 命中）→ 單調 touch `last_seen_at`、不抓詳細頁；New → 抓詳細頁、ISBN 比對：0 本或無 ISBN → 建 Book＋Source；1 本 → `normal` 附加 Source 並只補 NULL 欄位；≥2 本 → 新建 Book。每本 New Source 一個 transaction；commit 不確定時先重新 resolve identity，不盲目重送。Replay 取代進度狀態檔。

## 6. Acquisition 與安全

沿用金石堂的界線（由共用引擎提供）：最多 3 次、timeout 30 秒、backoff 最多 60 秒、Retry-After 最多 120 秒、回應最多 5 MiB；只重試 timeout／connection reset／429／500／502／503／504；所有等待受 soft budget 限制；每次請求前驗證 HTTPS、host 只有 `www.eslite.com`、沒有 userinfo、只允許 §4 的 path grammar；不跟隨 redirect；challenge／無法解析的 200 以 parse error fail closed，記為 `unclassified_200` alert。pacing 區間依 E0 決定。被封鎖（403／429 持續出現）→ 停用 ESLITE，不採規避技術。

## 7. 設定、執行與 terminal status

| Key | Default |
|---|---|
| `ESLITE_PAGES_FILE` | `crawler/eslite-pages.txt` |
| `ESLITE_WRITE_POLICY` | `normal` |
| `ESLITE_SOFT_RUN_BUDGET_SECONDS` | **待決定**（依清單長度與 pacing 計算） |
| `CRAWLER_RUN_HARD_LIMIT_SECONDS`（container 內） | runner 以 `ESLITE_RUN_HARD_LIMIT_SECONDS` 傳入；**待決定**，必須大於 soft budget |
| `ESLITE_HTTP_TIMEOUT_SECONDS` / `ESLITE_HTTP_MAX_ATTEMPTS` | 30 / 3 |
| `ESLITE_MAX_RESPONSE_BYTES` / `ESLITE_DIAGNOSTIC_MAX_BYTES` | 5 MiB / 2 MiB |
| `ESLITE_ARTIFACTS_DIR` | `crawler/artifacts`（產物在 `eslite/` 子目錄） |

`python -m eslite` 的順序與金石堂相同：Unicode／DB URL → config → 清單 → `source_providers.ESLITE` enabled（disabled → exit 2、零 HTTP）→ 第一個 DB 連線取 shared migration lock → `missing_schema_prerequisites(conn, ESLITE)` → 逐頁 run → terminal record（stdout 一份 JSON、`artifacts/eslite/last-run.json`、history 20 份）→ `alert_reasons` 非空時一行 `ALERT`。Terminal status（SUCCESS／PARTIAL_SUCCESS／FAILED）與 exit code（0／1／2）沿用共用 `decide_status`。

## 8. Docker 與本地 runner

- `crawler/Dockerfile`：新增 `eslite` target，和 `kingstone` 一樣是 HTTP-only，不含 Playwright；`ENTRYPOINT ["python", "-m", "eslite"]`。兩個 target 共用一個 base stage；博客來預設 target 不變。`.dockerignore` 白名單加入 `eslite/`、`eslite-pages.txt`；`test_kingstone_image.py` 的檢查比照新增 eslite 版本。
- `crawler/deploy/local/run-local-crawler.sh`：新增 `eslite` mode（provider `ESLITE`、`ESLITE_CRAWLER_IMAGE`、`ESLITE_RUN_HARD_LIMIT_SECONDS`）；tunnel、DB secret、EC2 state 閘門、`run.lock`、writer 名稱與 label、watchdog、orphan guard、`runner/eslite-last-run.json` 全部沿用。conf 範例、`crawler/deploy/README.md` §9 補上 eslite。
- **已知限制**：所有 provider 共用同一個 `run.lock` 與 writer 名稱，所以誠品和金石堂不能同時跑；金石堂完整清單最多跑 22 小時。本版不改。
- runner 一般失敗（exit 12、15–18）沒有 ALERT／record 的缺口（CB-07 backlog）同樣影響 eslite mode，不在本計畫修，修好後自動適用。

## 9. 實作順序（一個 Phase 一個或數個 PR；慣例：worktree、TDD、Haiku 寫程式、兩軸 review、使用者合併）

| Phase | 工作 | 完成條件 |
|---|---|---|
| 0 E0 | §2 的真站證據、fixtures、來源契約、contract test | 使用者 review 通過（E0 gate）；HTTP-only 可行 |
| 1 Core | `ProviderCode.ESLITE`；`missing_schema_prerequisites(conn, provider)`；`ListedItem`／`ListPage` 移入 `catalog_core` | 金石堂與博客來全部測試通過；新增 ESLITE preflight 的 DB 測試 |
| 2 Adapter | `eslite/urls.py`、`page_list.py`、`models.py`、`parse_list.py`、`parse_detail.py`（純函式、全離線） | fixture／unit／contract 測試通過 |
| 3 共用元件抽離（可與 Phase 2 並行） | M1 `http_acquisition`；M2 `category_ledger` + `category_run`；M3 `run_artifacts`／alerts／diagnostics／`run_config` | 每個 M：金石堂測試不修改即通過 + golden record／report 測試 |
| 4 Eslite run | `eslite/acquisition.py`（`FetchPolicy`）、`config.py`、`cli.py`、`__main__.py`；fake transport 的 run 測試；disposable DB integration | §10 的 run／DB 案例通過 |
| 5 Operations | Docker `eslite` target、runner `eslite` mode、conf 範例、README §9 | image smoke、`test_local_runner.py` eslite 案例通過 |
| 6 Acceptance | 完整 gate；使用者在 production 啟用 ESLITE；本地 runner 1 頁 `normal` canary；唯讀 SQL 核對；實作報告 | §11 gates 通過 |

每個 PR 同步更新 `crawler/docs/` 五份文件（architecture、workflow-diagram、test-suite、backlog、update-history）；Phase 5 另更新 `crawler/deploy/README.md`。

## 10. 驗收案例（自動測試不連真站；HTTP／clock／sleep 用 fake；DB 用 EF schema 的 disposable PostgreSQL）

| 情境 | 預期 |
|---|---|
| 多個合法分類 URL | 依清單順序處理；重複 URL canonical 後只處理一次 |
| 非法網址、其他網域、非法 query | 發出請求前拒絕；清單層級 → exit 2 |
| 同頁或跨頁重複商品 | 同一 external_id 只建立一個 Source |
| 已有 ESLITE Source | 只單調 touch `last_seen_at`，不抓詳細頁 |
| ISBN 命中恰 1 本既有 Book（博客來或金石堂） | `normal` 附加 ESLITE Source，只補 NULL；既有 Source 不變 |
| ISBN 0 本／無 ISBN／≥2 本 | 建 Book＋Source；≥2 本時不改動既有 Books |
| 詳細頁解析失敗、soft 404 | 該書失敗或略過，零半套寫入；存診斷 HTML |
| transaction 中途注入失敗、commit ACK lost | rollback 零 mutation；重新 resolve，不重複寫入 |
| 所有分類頁都失敗 | FAILED、exit 1、ALERT `failed` |
| 部分頁失敗或有書失敗 | PARTIAL_SUCCESS、exit 0 |
| soft budget 用盡 | 不再發請求、`pages_not_reached` 正確；下次 run 從頭 replay 並推進 |
| ESLITE disabled、schema 缺 ESLITE 列 | exit 2／`SCHEMA_PREREQUISITE_MISSING`，零 HTTP、零 mutation |
| migration lock 被占用 | 不寫入，run FAILED |
| 429／Retry-After／oversize／redirect | 依 §6 重試或失敗；不跟 redirect |
| 金石堂 regression | 全部既有測試不修改即通過；golden record 相同 |
| 博客來 regression | daily／pages／first_book 與 Bestseller 不受影響 |
| runner `eslite` mode | hard limit stop／kill、SIGTERM、orphan、record 路徑 `runner/eslite-last-run.json` |

## 11. Production gates 與 rollback

- **G1 schema**：本地 runner 經 tunnel 跑 `python -m eslite`，preflight 通過（ESLITE 列存在、post-011 欄位齊全）。
- **G2 權限**：沿用 `bookfinder_crawler`，已具備所需權限（不需新增 GRANT）；在 canary 前用唯讀 SQL 再確認一次。
- **G3 啟用**：提供 `crawler/deploy/local/sql/enable-eslite.sql`（比照 `enable-kingstone.sql`），由使用者以主帳號執行（production 寫入，需使用者執行與授權）。
- **G4 canary**：清單只放 1 頁，`normal`。通過條件：exit 0、0 個失敗、至少 1 筆新 ESLITE Source；唯讀 SQL `verify-eslite-canary-<日期>.sql` 確認沒有重複 Source、ISBN attach 的書其他 provider 的 Source 未變、博客來 Bestseller 未變動。
- 完整清單 run 在 canary 通過後，由使用者手動執行；不加排程。
- **Rollback**：`source_providers.ESLITE` 設回 disabled → 確認 writer 停止、tunnel 關閉；已 commit 的資料保留，資料修復需另外調查，不做盲目回滾。

## 12. 待決定（E0 後回報，附建議）

1. pacing 區間（預設建議 3～10 秒）。
2. `external_id`：URL 的 16 位數 ID 或「誠品貨碼」。
3. 列表頁 canonical 規則：`page=1` 是否省略、允許哪些排序參數。
4. 清單長度確定後的 soft budget 與 hard limit。
5. 非書商品（文具、CD 等）出現在分類頁時的處理：建議 parser 以「沒有 ISBN 且不是書籍規格」略過並計數，E0 確認後定。

## 驗證

各 Phase 的程式驗證：在 `crawler/` 執行 `../.venv/bin/python -m pytest -q`（含 DB integration）、`.venv/bin/ruff check crawler`、`ruff format --check crawler`；Phase 5 再跑 `docker build --target eslite` 與 runner 測試；Phase 6 由使用者在本機執行 canary 並回貼結果。

## 設計變更紀錄

- v1（2026-11-11）：初版。
