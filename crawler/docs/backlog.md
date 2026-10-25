# Crawler 優化與 debug 待辦

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。
> backlog 整理（2026-10-25）補記：CB-01、CB-04、CB-05、CB-06 已完成，移至文末「已處理」；CB-03 補記 schema 與 production 狀態。核心來源依原始基準靜態閱讀；host 另依上述 merge-target snapshot；本次未執行 build、測試、部署、外部服務或真實抓取。

未執行重現；未宣稱已重現 bug。待辦不構成外部操作授權。

## CB-02 — 診斷產物容量與保留期限

- P2；L2；狀態：改善提案。
- 證據：[save_failure_diagnostics](../books_crawler/fetcher.py) 每次失敗新增 artifact、沒有清理；[deployment §8](../../Docs/deployment/deployment.md) 明示另管保留，logrotate 只管 host logs。
- 成本量測：每日檔案數、bytes、最舊時間與調查窗口；未證明已磁碟滿。方向：決定天數／容量／權限與保留例外，再新增 cleanup 作業。
- 前置決策：可刪時間與調查證據保留。驗收：disposable 目錄清理舊檔、保留近期／例外，失敗可觀測，無 cookie／secret 輸出。
- 入口：[test_fetcher.py](../tests/test_fetcher.py)、[test_playwright_fetcher.py](../tests/test_playwright_fetcher.py)；CR-T11，cleanup 測試待建。

## CB-03 — 排程啟用前正式環境驗證

- P1；L4；狀態：待驗證（2026-10-25 整理時 production 仍為 `CRAWLER_ENABLED=false`，博客來封鎖 EC2 IP，見 DEP-B01）。
- 證據：[deployment §8](../../Docs/deployment/deployment.md) 要求 EC2 手動抓取驗證後才啟用；[test_deploy.py](../tests/test_deploy.py) 是替身測試，不能代表 SSM／IAM／EC2／來源成功。
- 前置：當前任務 production／真實抓取授權，EF schema（011 已於 v0.0.7 套用）、image 預載（--pull=never）、專用 SSM secret、host 時區與權限。
- 方向與驗收：依 [部署操作](../deploy/README.md) 留存去識別 status／exit／可解析證據，確認 UTC cron、72 小時狀態與失敗不前移、舊榜保護。另依 [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) 與 [target deployment §8](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/deployment/deployment.md) 查核 host 與 crawler 使用相同 maintenance lock 路徑：先取 shared lock 再讀 state、容器期間持鎖、paused／dirty exit6、wait timeout exit3、無法解析 state exit2、absent state 保留相容行為。CR-T12-B 的現有替身案例只是 source 證據，不能替代此 L4 環境驗證。challenge 阻擋則不啟用；rollback 為停用該 cron 並保留現有榜單，不採規避技術。
- 入口：[wrapper](../deploy/run-crawler.sh)；CR-T12、CR-T13。

## CB-07 — 金石堂分類頁 crawler（v11）

- P2；L3；狀態：E0 完成；Phase 1（共用 `catalog_core`：型別、identity、ISBN、provider 明確的 persistence、單調 touch、item 解析 service，博客來已改走 service）完成（2026-10-25，見 [實作報告](../../Docs/Implementation-Report/kingstone-phase1-core.md)）；Phase 2 完成：清單檔、URL grammar（#134）、列表頁 parser（#135）、詳細頁 parser（#136），見 [實作報告](../../Docs/Implementation-Report/kingstone-phase2-adapter.md)；Phase 3 core acquisition 完成（URL 守門、pacing、retry、budget、回應分類，見 [architecture](architecture.md)「金石堂 adapter」）；計畫 §6 的有限額診斷檔（`KINGSTONE_DIAGNOSTIC_MAX_BYTES`，預設 2 MiB）尚未實作，留待 runner／production 整合（Phase 6）；Phase 4 完成（run 帳本與逐頁流程；尚無 CLI／DB composition）：設定與 run 帳本（M1：`kingstone/config.py`、`kingstone/ledger.py`，含 terminal status 規則），逐頁 run（M2：`kingstone/run.py`，budget 停止、replay、fatal 範圍與 redact，見 [architecture](architecture.md)「Run（逐頁流程）」）；Phase 5 完成（寫入政策、組裝與 CLI、真 DB 整合）：寫入政策（M1：`catalog_core` 的 `WritePolicy`、`resolve_item(write_policy=)` 與 `ItemPolicySkipped`；金石堂 `KINGSTONE_WRITE_POLICY`，預設 `new-books-only`；ledger 的 `policy_skipped`，見 [architecture](architecture.md)「Run 帳本與 terminal status」）；組裝與入口（M2：`kingstone/cli.py`、`kingstone/__main__.py`，真 fetcher 與 DB store 的組裝、`budget.remaining` 接線、exit code，見 [architecture](architecture.md)「入口與組裝」）；真 DB 整合（M2：全流程、replay、政策、atomicity、uncertain commit、Bestseller protection，CR-K09、CR-K10）。Phase 6 起未實作。
- 決定（使用者 2026-10-25）：比照博客來分類榜，由使用者在 `crawler/kingstone-pages.txt` 提供金石堂分類列表頁；每個 URL 只抓那一頁、不跟分頁；不探索分類樹；沒有跨 run 進度狀態檔，靠 replay＋Source identity 推進；`HTTP_ONLY`；請求間隔 3～10 秒。來源契約見下方「CB-07 來源契約」。
- 證據：[kingstone fixtures](../tests/fixtures/kingstone/README.md)（13 份）與 CR-K01。
- 待做（Phase 6，依 [v12 計畫](../../Docs/plans/kingstone-category-crawler.md) §8、§9）：本地 runner（kingstone mode、SSH tunnel、DB secret、EC2 deploy 狀態唯讀閘門、watchdog 強制 `CRAWLER_RUN_HARD_LIMIT_SECONDS`、所有 provider 的 fencing）、HTTP-only `KINGSTONE_CRAWLER_IMAGE`（Dockerfile 與 `.dockerignore` 納入 `kingstone/`）、DB advisory lock（crawler 端與 deploy migration 端）、schema preflight、last-run JSON 與 bounded history、log alert（零進度、zero-card、`pages_not_reached` 連續 3 次）、診斷檔（`KINGSTONE_DIAGNOSTIC_MAX_BYTES`）、清單上限 400。Phase 7：acceptance。Phase 1～5 已完成（見上）。
- Phase 6 決定（使用者 2026-10-25，計畫 v12）：crawler 改在本地 host 手動執行，SSH 轉發經 EC2 直連 RDS；沿用全域 `CRAWLER_ENABLED`；清單隨 image 發布；另做 HTTP-only `KINGSTONE_CRAWLER_IMAGE`；writer fencing／watchdog 套用到所有 provider；與 migration 的互斥改為 DB advisory lock；alert 只寫 log；清單上限 400、soft／hard 7200／9000 秒；先手動、不排程。細節見 [v12 計畫](../../Docs/plans/kingstone-category-crawler.md) §8、§10。尚未實作。
- 未覆蓋：E0 沒有觀察到 challenge、CAPTCHA、限制級頁、429／5xx、無 ISBN 的書；出現時先收錄 fixture。
- Phase 1 留下的待辦：
  - `ItemResolved`／`ItemFailed.identity_warning` 目前只有 service 測試讀取；博客來沒有 `external_id`，不會產生 URL 漂移 warning。金石堂（有 km_code）的 warning 已由 Phase 4 run 記錄（`kingstone.run`，WARNING 一行並計入 `identity_warning_count`）。
  - `books_crawler/models.py` 重新匯出 `catalog_core.models` 的型別，讓既有測試的 import 不用改；同一型別因此有兩個匯入入口，之後把測試改成直接從 `catalog_core` 匯入，再移除這層相容匯出。
- Phase 2 留下的待辦：
  - `.productGrid` 內沒有 `data-prodno` 的 `.mod_prod_card` 目前被靜默略過（選擇器要求 `data-prodno`）；E0 fixture 沒有此情形，是否改為 parse error 待定。
  - Dockerfile、`.dockerignore` 與 runner 納入 `kingstone/` 留到 Phase 6。
  - 只讀「作者：」「譯者：」兩種標籤；其他角色標籤（繪者等）出現時再定。
  - 角色前綴一律 `OTHER`（E0 只見「審訂/」）；出現可對應 Catalog 角色的金石堂標籤時，依 fixture 加入金石堂自己的對應。
  - 作者值含 `/` 一律視為角色前綴（`角色/姓名`）；真實作者名含 `/` 時會被拆錯。E0 沒有此情形，出現時再定規則。
  - 規格表「分級」欄（限制級辨識）尚未讀取；E0 的 7 本都是「普通級」，待有限制級 fixture 再定。
- Phase 4 留下的待辦（M1、M2）：
  - `zero_card_pages` 已計數，但 alert 條件與送出位置屬於 Phase 6。
  - 診斷大小 `KINGSTONE_DIAGNOSTIC_MAX_BYTES` 與 `CRAWLER_ALERT_COMMAND` 不在 M1 config 內，留給 Phase 6。（寫入政策已於 Phase 5 M1 加入 config。）
  - 已於 Phase 5 M2 解決：`kingstone/cli.py` 把 `KINGSTONE_SOFT_RUN_BUDGET_SECONDS` 轉成 `SoftBudget`，並把同一個 budget 交給真 fetcher（`budget_remaining=budget.remaining`）。
  - 詳細頁在 budget 停止時被截斷的卡，以 `budget_exhausted` 記入 `failed_items`（統計上算失敗，下次 replay 會處理）；是否改為不計入失敗另定。
- Phase 3 留下的待辦：
  - 診斷檔（限額）未實作，所以 Phase 3 只算 core acquisition 完成：金石堂 acquisition 不寫 failure diagnostics；計畫 §6 要求「診斷有限額」，§7 設定表有 `KINGSTONE_DIAGNOSTIC_MAX_BYTES`（2 MiB）。留待 runner／production 整合（Phase 6）時一併定內容、數量、保留期限（參考 CB-02）並實作。
  - challenge／CAPTCHA 分類待 fixture：目前 200 照常回傳，由 parser fail closed；收錄 fixture 後再定分類。
  - `budget_remaining` 由 Phase 4 run 以 `SoftBudget` 提供（caller 組裝時傳入 `budget.remaining`）；Phase 3 預設 `math.inf`（不限制）。真 fetcher 的組裝已於 Phase 5 M2 完成（`kingstone/cli.py`）；真站上的 budget 行為仍未驗證（禁止連網）。
  - libcurl 傳輸中的大小上限（`MAXFILESIZE_LARGE`）未以真實傳輸驗證：開發環境禁止連網，單元測試只驗證選項有傳入與 `FILESIZE_EXCEEDED`（63）的對應。目前保證 5 MiB 記憶體上限的是 per-call 串流計量（第二道）；第一道是額外保護。
  - TLS 握手中被 reset 若以 curl `RECV_ERROR` 回報，會歸為 `ConnectionError` 並被重試；計畫把 TLS 失敗列為不重試，此分支沒有測試，也未經真站確認。
  - 最後一次嘗試的 Retry-After 不讀，失敗記為 `HTTP_STATUS`；原因分類可能失真（伺服器的意圖是要求等待），目前保留，之後若要區分需另定錯誤類別。
- Phase 5 留下的待辦（M2）：
  - 真站（金石堂網站）的端到端未驗證：所有 HTTP 都是 fake；真站抓取需要當前任務的明確授權。
  - 必要 DB 測試的 skip 風險：既有 `conftest.py` 在缺 dotnet SDK 時 skip EF schema 測試（Books 既有行為，未改）。本次執行 Kingstone DB 測試 19 個全部執行。
  - DB 角色權限：程式只發出 SELECT、INSERT、UPDATE；實際 role 的 grant 屬部署（Phase 6），未驗證。
  - hard limit 強制執行、runner、Dockerfile、alert 與診斷檔都屬 Phase 6（見上方待做）。

### CB-07 來源契約（E0 凍結）

> 2026-10-25 E0 凍結的來源契約。已實作的部分（清單檔、URL grammar、列表頁與詳細頁 parser、acquisition）以 [architecture](architecture.md)「金石堂 adapter」為現行 authority，本節對應段落只留指標；尚未實作的 run、ingestion、runner 仍依本節契約。實作計畫見 [kingstone-category-crawler.md](../../Docs/plans/kingstone-category-crawler.md)（v11）；之後每實作一部分，就依實際行為移入 architecture／workflow-diagram。
> 證據：使用者授權的有限真站抓取，2026-10-25 03:39–03:55 UTC，31 次循序請求（curl_cffi Chrome、不跟隨 redirect、3～30 秒隨機等待），沒有 429、challenge、Retry-After 或登入頁。原始回應在 `crawler/artifacts/kingstone-e0/`（不 commit）；fixture 見 [kingstone fixtures](../tests/fixtures/kingstone/README.md)。

**範圍**（使用者 2026-10-25 決定）：比照博客來分類榜。使用者在清單提供金石堂分類列表頁，crawler 只抓清單上每一頁列出的書；不探索分類樹、不跟分頁、沒有跨 run 進度狀態檔。

**Acquisition**：已實作，現行契約見 [architecture](architecture.md)「金石堂 adapter」的 Acquisition 段落。來源端的前提（仍有效）：`HTTP_ONLY`，不需要 browser，不新增 Playwright production dependency；只允許 origin `https://www.kingstone.com.tw`；robots.txt 禁止的 `/api/`、`/bms/`、`/dks/`、`/cart/`、`/Refund/`、`/einvoice/`、`/wp-admin/` 都不使用；循序請求，每次請求（含重試）前隨機等待 **3～10 秒**（使用者 2026-10-25 依 E0 證據決定）；不跟隨 redirect。

**URL grammar**（其他 URL 一律拒絕）：

| 用途 | Canonical URL | 規則 |
|---|---|---|
| 列表頁（清單項目） | `/book/<code>/?dis=list&page=<n>[&sort=<key>]` | `code` 為 ASCII 字母 2～4 個，canonical 轉小寫（伺服器也接受大寫，`<link rel="canonical">` 指向小寫；`/normal/book/<code>` 是同內容別名，不接受）。`n` 為正整數。`key` 只能是頁面提供的 `sa_desc`（預設，依銷售）、`pu_desc`、`pu_asc`、`pr_desc`、`pr_asc`。`sa_desc` 是預設，canonical 時移除，與省略相同（`&sort=sa_desc` 與不帶 sort 的同一頁） |
| 詳細頁 | `/basic/<km_code>/` | `km_code` 為 13 位數字；列表連結的 `?lid=`、`&actid=` 追蹤參數不進 canonical source URL |

**列表頁解析**：

已實作，現行契約見 [architecture](architecture.md)「金石堂 adapter」的列表頁段落。

**詳細頁解析**：已實作，現行契約見 [architecture](architecture.md)「金石堂 adapter」的詳細頁段落。

**錯誤分類**（不跟隨 redirect）：

| 觀察到的回應 | 分類 | 處理 |
|---|---|---|
| 列表頁的分類不存在：302，`Location: /book/` | page failure | 跳過該頁、不重試 |
| 商品不存在：200 soft 404，`<title>` 只有「金石堂」、沒有 Product JSON-LD | product not found | 跳過、不重試、不寫入 |
| 200 但缺少預期結構 | parse error | 不猜測、不寫入 |
| challenge、CAPTCHA、限制級頁 | E0 未觀察到 | 出現時以 parse error fail closed，收錄新的 fixture 再定分類 |

**背景（不實作）**：E0 也觀察了分類樹：`/book/` 下有 21 個第一層分類，分類頁的 `nav.nav1b_classlevel` 列出直接子分類，代碼長度不代表層級（`nkl` 是 `ssss` 的第二層），子分類的筆數剛好切分父分類。v11 改由使用者提供清單，這些觀察只供使用者挑選網址時參考，不是 crawler 的行為。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。

## 已處理

- **CB-01**（#113 PR3，PR #119）：pages 新來源寫入 `first_seen_at = last_seen_at = now`；Existing Source 看到即 touch `last_seen_at`。證據：`861c334`（phase B）、`0149b69`、`448571e`（phase A）；實作位於 `db._insert_source` 與 `run.py`。
- **CB-04**（#113 PR3，PR #119）：只用 `source_code`；ISBN 依 §7.1 正規化並以共用 fixture 驗證；以 distinct Book 0／1／≥2 判斷；disabled provider 以 exit 2 拒絕。證據：`861c334`。
- **CB-05**（#113 PR3，PR #119）：`CatalogResolution` 與 `RankingDecision` 分層；既有 Source 獨立 transaction touch；重試與 first_book 行為。證據：phase A `0149b69`、`448571e`、`ad82318`、`fb707de`；phase B `861c334`。
- **CB-06**（#113 PR4，PR #123）：`IdentifierType` 只剩 `ISBN`，`find_books_by_isbn` 只查 `ISBN`。證據：`f92a63d`（M2），依賴 migration 011 `5052361`。
