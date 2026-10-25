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

- P2；L3；狀態：E0 完成；Phase 1（共用 `catalog_core`：型別、identity、ISBN、provider 明確的 persistence、單調 touch、item 解析 service，博客來已改走 service）完成（2026-10-25，見 [實作報告](../../Docs/Implementation-Report/kingstone-phase1-core.md)）；Phase 2 完成：清單檔、URL grammar（#134）、列表頁 parser（#135）、詳細頁 parser（#136），見 [實作報告](../../Docs/Implementation-Report/kingstone-phase2-adapter.md)；Phase 3 core acquisition 完成（URL 守門、pacing、retry、budget、回應分類，見 [architecture](architecture.md)「金石堂 adapter」）；計畫 §6 的有限額診斷檔（`KINGSTONE_DIAGNOSTIC_MAX_BYTES`，預設 2 MiB）已於 Phase 6 M5 實作（列表頁與詳細頁的 parse error，見 [architecture](architecture.md)「報告、alert 與診斷」）；Phase 4 完成（run 帳本與逐頁流程；尚無 CLI／DB composition；見 [實作報告](../../Docs/Implementation-Report/kingstone-phase4-run.md)）：設定與 run 帳本（M1：`kingstone/config.py`、`kingstone/ledger.py`，含 terminal status 規則），逐頁 run（M2：`kingstone/run.py`，budget 停止、replay、fatal 範圍與 redact，見 [architecture](architecture.md)「Run（逐頁流程）」）；Phase 5 完成（寫入政策、組裝與 CLI、真 DB 整合）：寫入政策（M1：`catalog_core` 的 `WritePolicy`、`resolve_item(write_policy=)` 與 `ItemPolicySkipped`；金石堂 `KINGSTONE_WRITE_POLICY`，預設原為 `new-books-only`，Phase 7 改為 `normal`；ledger 的 `policy_skipped`，見 [architecture](architecture.md)「Run 帳本與 terminal status」）；組裝與入口（M2：`kingstone/cli.py`、`kingstone/__main__.py`，真 fetcher 與 DB store 的組裝、`budget.remaining` 接線、exit code，見 [architecture](architecture.md)「入口與組裝」）；真 DB 整合（M2：全流程、replay、政策、atomicity、uncertain commit、Bestseller protection，CR-K09、CR-K10）。Phase 6 進行中（M1：清單、上限、image；見 [architecture](architecture.md)「Image」；M2：每個 DB session 的新連線（首次與 reconnect）先取 shared migration lock，取不到不寫入（CR-T19），以及金石堂 schema preflight `SCHEMA_PREREQUISITE_MISSING`（CR-K12，入口 exit 2）；M5：terminal JSON（`last-run.json`）、bounded history、log alert、診斷檔與計數欄位（CR-K13、CR-K14、CR-K15）；M3：deploy 端以存活的 lock session 持有 exclusive lock（#146，見 deploy/docs）；M4：本地 runner，含 writer fencing、watchdog 與 runner 的 ALERT 與 record）；Phase 6 實作完成，CD 推送 `KINGSTONE_CRAWLER_IMAGE` 待後續；Phase 7 進行中（見 [實作報告](../../Docs/Implementation-Report/kingstone-phase7-acceptance.md)）：P1、P2、P5（`new-books-only` 與 `normal` 各一次 1 頁 canary）通過，P3 主要項目已在 canary 中實測（2026-10-25，見下方「Phase 7 進度」）；寫入政策預設已改為 `normal`（使用者決定，#154）；剩 P3 的斷線、signal 實測與完整清單的首次執行。
- 決定（使用者 2026-10-25）：比照博客來分類榜，由使用者在 `crawler/kingstone-pages.txt` 提供金石堂分類列表頁；每個 URL 只抓那一頁、不跟分頁；不探索分類樹；沒有跨 run 進度狀態檔，靠 replay＋Source identity 推進；`HTTP_ONLY`；請求間隔 3～10 秒。來源契約見下方「CB-07 來源契約」。
- 證據：[kingstone fixtures](../tests/fixtures/kingstone/README.md)（13 份）與 CR-K01。
- 待做：Phase 6 的 M1～M5 已完成；CD 推送 `KINGSTONE_CRAWLER_IMAGE` 待後續。Phase 7：acceptance（依 [v12 計畫](../../Docs/plans/kingstone-category-crawler.md) §9、§10）。Phase 1～5 已完成（見上）。
- 博客來入口未加 schema preflight（可選，未排程）。
- Phase 6 M5 完成（2026-10-25，計畫 v12 §8）：`kingstone/alerts.py`（alert reason 的唯一判定處）、`kingstone/artifacts.py`（`last-run.json` 原子寫入、history 上限 20 與 `pages_not_reached` streak）、`kingstone/diagnostics.py`（診斷 HTML 限額與保留 20 份）、`kingstone/cli.py` 接線（所有 terminal 結果，ALERT 行）、計數欄位（`items_listed`、`details_fetched`、`http_attempts`、`http_failures`）。「待做」中 last-run JSON、bounded history、log alert（零進度、zero-card、streak）與診斷檔已完成；零進度的 alert 另以 `failed` 表達（FAILED 狀態）。
- Phase 6 決定（使用者 2026-10-25，計畫 v12）：crawler 改在本地 host 手動執行，SSH 轉發經 EC2 直連 RDS；沿用全域 `CRAWLER_ENABLED`；清單隨 image 發布；另做 HTTP-only `KINGSTONE_CRAWLER_IMAGE`；writer fencing／watchdog 套用到所有 provider；與 migration 的互斥改為 DB advisory lock；alert 只寫 log；清單上限 400、soft／hard 7200／9000 秒；先手動、不排程。細節見 [v12 計畫](../../Docs/plans/kingstone-category-crawler.md) §8、§10。
- Phase 6 M4 完成（2026-10-25）：本地 runner `deploy/local/run-local-crawler.sh`（kingstone 與博客來四個 mode 共用 `run.lock`、EC2 deploy state 唯讀閘門、orphan check、DB secret、SSH 本地轉發與 `verify-full` 連線字串改寫、watchdog 與 writer fencing、exit code 表）；架構見 [architecture](architecture.md)「Runtime ownership」與 [流程](workflow-diagram.md)「本地 runner」；測試 CR-T20（假指令，未連外部）。使用說明與 exit code 見 [deploy README](../deploy/README.md) §9。
- Phase 7 進度：
  - **P2 通過（2026-10-25）**：檢查發現 crawler 原本使用 RDS 主帳號 `bookfinder_admin`（`rds_superuser`、CREATEROLE、CREATEDB、擁有所有表）。依使用者決定改建 `bookfinder_crawler`：`books`、`book_sources` 為 SELECT／INSERT／UPDATE，`book_identifiers`、`book_contributors` 為 SELECT／INSERT，`book_subjects` 為 INSERT，`bestsellers` 為 INSERT／DELETE，`source_providers` 為 SELECT；連線上限 5；無 DDL、不擁有物件、無所屬角色。使用者以新帳號執行 `crawler/deploy/local/sql/p2-crawler-privileges.sql` 的結果全部符合。權限依程式實際的 SQL 整理；本機另以拋棄式 PG 17 驗證新帳號可完成 schema preflight、New Source、ISBN attach、touch、榜單替換與 shared migration lock，讀 `users`、DDL、`DELETE FROM books`、`TRUNCATE` 皆被拒。
  - **權限的後續維護**：之後的 migration 若新增 crawler 需要的表或重建既有表，需要補 GRANT（`crawler/deploy/local/sql/create-crawler-role.sql` 為權限清單）；缺少時 crawler 以權限錯誤寫入失敗，不會寫到其他地方。schema preflight 只檢查表與欄位，不檢查權限。
  - **P3 第一次實測發現（2026-10-25，已修正）**：runner 原本以 `ssh <host> cat <state.json>` 讀取，但 deploy host 每次寫入都把 `state.json` 設為 root 0600，SSH 使用者讀不到而 exit 12；假指令測試沒有涵蓋檔案權限。改為 `sudo -n cat --`，EC2 的 SSH 使用者需要免密碼 sudo（README §9.1 有限定單一指令的 sudoers 寫法）。
  - **啟用 KINGSTONE（2026-10-25）**：第一次 canary 以 exit 2 停在 `source provider KINGSTONE is disabled or not registered`（migration 010 seed 為 `enabled = false`），未發出任何請求。使用者以主帳號執行 `crawler/deploy/local/sql/enable-kingstone.sql` 啟用。web 以 `enabled` 決定書籍頁是否顯示該 provider 的外部連結；回復即改回 `false`。
  - **P1 通過（2026-10-25）**：canary 經 tunnel 在 production 通過 schema preflight 並取得 shared migration lock（兩者都在第一個請求之前）。
  - **P5 第一段通過（2026-10-25，run `2d933792`）**：`kingstone:canary`（清單 1 頁 `https://www.kingstone.com.tw/book/jdd/?dis=list&page=1`）、`new-books-only`。`SUCCESS`、exit 0、無 alert；48 張卡、48 個詳細頁、`http_attempts=49`、`http_failures=0`、`parse_error_200_count=0`；`imported=39`、`policy_skipped=9`（ISBN 已對應既有書）、`failed=0`；6 分 7 秒（平均約 7.5 秒／請求）。使用者以 `crawler/deploy/local/sql/verify-canary-2026-10-25.sql`（唯讀）核對 production：KINGSTONE Source 39 筆皆在 run 時段內建立，`external_id`、URL、Book 皆 39 個不重複；無一書多個 KINGSTONE Source；39 本新書上沒有其他 provider 的 Source；新書 ISBN 不與既有書重複；ISBN、作者、分類、出版社、出版日期、簡介、封面皆 39／39；博客來 Source 在 run 時段內未被 touch 或新增，`bestsellers` 81 列、最後寫入 2026-10-11，run 時段內 0。
  - **P5 第二段通過（2026-10-25，run `cab53f56`）**：同一頁、`normal` 政策（暫時 image `kingstone:canary-normal` = `FROM kingstone:canary` + `ENV KINGSTONE_WRITE_POLICY=normal`，未改程式）。`SUCCESS`、exit 0；`existing_source=39`（只 touch，未重抓詳細頁）、`isbn_attached=9`、`details_fetched=9`、`http_attempts=10`、`imported=0`、`failed=0`；2 分鐘。使用者以 `crawler/deploy/local/sql/verify-normal-2026-10-25.sql`（唯讀）核對 production：KINGSTONE Source 48 筆（新增 9、touch 39、未 touch 0）；9 筆皆掛在 canary 前已存在、有 `BOOKS_COM_TW` Source 的書上，各 1 個 KINGSTONE Source；每本新增 3 個 KINGSTONE 分類；無重複 Source／ISBN；run 時段內無新書、博客來 Source 與 `bestsellers` 未變動。9 本的 `updated_at` 皆未變：這些書的欄位原本就齊全，沒有 NULL 可補，所以 NULL enrichment 在真實資料上**未被觸發**（其正確性由 `catalog_core` 的測試保證）。使用者確認 `normal` 的結果符合期望（同一本書同時有博客來與金石堂連結）。
  - **P3 已實測的項目**（同一次 canary）：EC2 state gate（`sudo -n cat`，#152）、SSM 讀取、URL 改寫、SSH 轉發與 `verify-full`、crawler 帳號的讀寫、UID 10001 寫入 artifacts、container 結束與移除、terminal JSON 與 ALERT（失敗的兩次 run 各產生 `ALERT reasons=failed`）。
  - **觀察：暫時性的逾時**：canary 前一次 run（`f03377c2`）列表頁 3 次皆 `TransportTimeout`（各 30 秒），結果 `FAILED`、`every listed page was skipped (1 of 1)`、exit 1、未寫入。隨後在同一主機以 curl 與 canary image 內的 curl_cffi 各發一次請求皆 200（約 1 秒），重跑即成功。判定為暫時性；之後若重複出現，需比對 container 內外是否同時不通。
  - **待做**：
    - **P3 剩餘實測（待使用者本機執行）**。三項都在 container 啟動後才觸發；每項結束後都要確認：`docker ps -a --filter label=com.bookfinder.role=catalog-crawler` 沒有 running／paused 的 container、`pgrep -af 'ssh -N .* -L 127.0.0.1:<port>:'` 沒有輸出、runner 的 stdout 只有一份 JSON、stderr 只有一行 `ALERT`。
      1. **tunnel 中途斷線**：用 `kingstone:canary`（1 頁）執行；看到第一個詳細頁的 `GET` 之後，另開終端以 `pkill -f 'ssh -N .* -L 127.0.0.1:<port>:'` 結束 tunnel。預期：crawler 的 DB 操作與重連失敗（本機埠已關閉，連線立即被拒），該卡以 `database_error` 記為失敗，run 不卡住、在有限時間內結束；exit 非 0、`ALERT reasons` 含 `failed`；`kingstone/last-run.json` 寫出。之後以唯讀 SQL 確認沒有半寫入：斷線時段內建立的 Book 都有 KINGSTONE Source、identifiers 與作者（每本書是一個 transaction）。目前 runner 不監看 tunnel，container 結束後才收尾，這點一併觀察。
      2. **SIGTERM**：同樣用 `kingstone:canary`，在詳細頁抓取中對 runner 送 `kill -TERM <runner pid>`（或 Ctrl-C）。預期：exit 21、`SIGNAL_STOP`、`artifacts/runner/kingstone-last-run.json` 寫出、container 被 `docker stop` 後已停止、tunnel 關閉。crawler 自己的 `kingstone/last-run.json` 是否寫出取決於 container 收到 SIGTERM 時的處理，目前未定義，記錄實際結果；已 commit 的書保留，被中斷的那本不應半寫入（同上 SQL）。
      3. **hard limit 與 kill 路徑（不連網、不碰 DB）**：建暫時 image `FROM kingstone:canary` 加 `ENTRYPOINT ["sh", "-c", "trap '' TERM; sleep 600"]`（忽略 SIGTERM 的假 writer），設定 `CRAWLER_RUN_HARD_LIMIT_SECONDS=60`、`CRAWLER_STOP_GRACE_SECONDS=10` 後執行 kingstone mode。預期：約 60 秒後 watchdog `docker stop`、10 秒後仍在跑而 `docker kill`，exit 20、`HARD_LIMIT`、`ALERT reasons=hard_limit`。此項同時驗證真 Docker 的 `stop`／`kill`／`ps --filter label=` 語意與 `--cidfile`。做完把兩個值與 image 改回。博客來模式的 3600 秒上限需要真站抓取博客來，不在目前授權內，另案。
    - Phase 7 實作報告。
- Phase 6 M4 之後仍待辦：
  - **EC2 crawler cron 移除（另案）**：目前以 `CRAWLER_ENABLED=false` 停用，cron 仍安裝於 EC2；移除需另行決定與執行。
  - **P3 真實驗證（待使用者本機執行）**：真實 SSH 轉發與 `ExitOnForwardFailure`、SSM 權限、Docker 的 `--cidfile`、UID 10001 對 artifacts 與 CA mount 的讀寫、`docker stop`／`kill`／`ps` 語意、tunnel 斷線、以及 deploy migration 與 crawler 的互斥（見 v12 §10 P3）。本次只有假指令測試。
  - **與 migration 的互斥由 crawler 程式與 deploy 負責，不在 runner**：container 內的 crawler 在每次 DB 連線與重連時取 shared advisory lock（`catalog_core.session`，PR #145），deploy 在 migration 期間以存活的 lock session 持有 exclusive lock（PR #146）；runner 本身不取 lock。#145、#146 已合併；deploy 端在下一次 production deploy 後才生效，在此之前本地執行仍須自行避開 CD 部署窗口（[deploy README](../deploy/README.md) §9.5）。
  - **`deploy/docs` 同步（不在本 PR 改 `deploy/`）**：`deploy/docs/architecture.md`、`workflow-diagram.md` 若仍描述 crawler 在 EC2 執行，需同步 runtime ownership；`deploy/` 的 migration 與 advisory lock 變更屬 deploy 的 M2／M3。
  - **博客來 hard limit 3600 秒未量測**：`BOOKS_RUN_HARD_LIMIT_SECONDS` 預設值取自計畫表的「原 3600」；博客來 daily 與 pages 的實際耗時未驗證，P3 時應確認不會被 watchdog 誤殺。
  - ~~runner 端 orphan alert，以及 hard limit、signal 的 `ALERT` 與 terminal record~~：已於 #148 完成（容器外 lifecycle failure；見 [deploy README](../deploy/README.md) §9.4.1）。容器內結果仍由 crawler 的 last-run JSON 與 ALERT 負責（#147）。
  - **runner 的一般 operational failure 沒有 ALERT 與 terminal record（待修正，PR #148 review）**：目前只有容器 lifecycle failure（13、14、20、21、22）會經 `record_terminal`；下列 exit 只走 `fail`（stderr 後直接 exit），沒有 `ALERT` 行、stdout terminal JSON，也沒有 `artifacts/runner/<mode>-last-run.json`，不符 v12 observability contract「每次 run 有 terminal JSON；FAILED 觸發 ALERT」。AWS profile 過期、SSH 主機暫時連不上、Docker daemon 未啟動都是本地 runner 的常見情況。
    - 對應：12 `STATE_UNREADABLE`、15 `SECRET_UNAVAILABLE`、16 `TUNNEL_UNAVAILABLE`、17 `DATABASE_URL_INVALID`、18 `DOCKER_UNAVAILABLE`；一律 `status=FAILED`、`alert_reasons=["failed"]`、`exit_code` 維持原值。
    - 做法：在 artifacts 路徑驗證之後，新增類似 `fail_recorded(code, reason, message)` 的函式（stderr 訊息 → `record_terminal` → 以原 code exit），`runner_support.RUNNER_RULES` 加入上述 reason。不需改架構。
    - 不納入：exit 6（paused／dirty，屬 skip）、exit 11（`run.lock` busy，屬並行閘門）、exit 10（設定與用法；artifacts 路徑尚未可信時維持現行）。
    - 驗收測試（`test_local_runner.py`）：state unreadable、SSM failure、tunnel failure、URL rewrite failure、Docker unavailable 各一案，皆驗證 exit code 不變、stdout 恰好一份 JSON、stderr 恰好一個 `ALERT`、terminal record 內容正確、secret 不出現在任何輸出。
  - **container 輸出未持久化**：`docker run` 輸出只顯示在終端；container 自身的 `ALERT` 行未轉寫到 runner log（計畫 §8 為可選），仍待辦。
  - **secret 檔 owner 檢查無測試**：程式有檢查，但需要另一個 owner 的檔案才能測。
- 未覆蓋：E0 沒有觀察到 challenge、CAPTCHA、限制級頁、429／5xx、無 ISBN 的書；出現時先收錄 fixture。
- Phase 1 留下的待辦：
  - `ItemResolved`／`ItemFailed.identity_warning` 目前只有 service 測試讀取；博客來沒有 `external_id`，不會產生 URL 漂移 warning。金石堂（有 km_code）的 warning 已由 Phase 4 run 記錄（`kingstone.run`，WARNING 一行並計入 `identity_warning_count`）。
  - `books_crawler/models.py` 重新匯出 `catalog_core.models` 的型別，讓既有測試的 import 不用改；同一型別因此有兩個匯入入口，之後把測試改成直接從 `catalog_core` 匯入，再移除這層相容匯出。
- Phase 2 留下的待辦：
  - `.productGrid` 內沒有 `data-prodno` 的 `.mod_prod_card` 目前被靜默略過（選擇器要求 `data-prodno`）；E0 fixture 沒有此情形，是否改為 parse error 待定。
  - Dockerfile、`.dockerignore` 納入 `kingstone/` 已於 Phase 6 M1 完成（`kingstone` target）；runner 納入留到 Phase 6 後續。
  - 只讀「作者：」「譯者：」兩種標籤；其他角色標籤（繪者等）出現時再定。
  - 角色前綴一律 `OTHER`（E0 只見「審訂/」）；出現可對應 Catalog 角色的金石堂標籤時，依 fixture 加入金石堂自己的對應。
  - 作者值含 `/` 一律視為角色前綴（`角色/姓名`）；真實作者名含 `/` 時會被拆錯。E0 沒有此情形，出現時再定規則。
  - 規格表「分級」欄（限制級辨識）尚未讀取；E0 的 7 本都是「普通級」，待有限制級 fixture 再定。
- Phase 4 留下的待辦（M1、M2）：
  - `zero_card_pages` 已計數；alert 條件已於 Phase 6 M5 實作（`zero_card_pages` reason）。
  - 診斷大小 `KINGSTONE_DIAGNOSTIC_MAX_BYTES` 已於 Phase 6 M5 加入 config；`CRAWLER_ALERT_COMMAND` 不實作（使用者決定 alert 只寫 log）。（寫入政策已於 Phase 5 M1 加入 config。）
  - 已於 Phase 5 M2 解決：`kingstone/cli.py` 把 `KINGSTONE_SOFT_RUN_BUDGET_SECONDS` 轉成 `SoftBudget`，並把同一個 budget 交給真 fetcher（`budget_remaining=budget.remaining`）。
  - 詳細頁在 budget 停止時被截斷的卡，以 `budget_exhausted` 記入 `failed_items`（統計上算失敗，下次 replay 會處理）；是否改為不計入失敗另定。
- Phase 3 留下的待辦：
  - challenge／CAPTCHA 分類待 fixture：目前 200 照常回傳，由 parser fail closed，落在 `unclassified_200` alert（保守告警，Phase 6 M5 後續）；收錄 fixture 後把可辨識的部分細分為 `challenge`，其餘維持 `unclassified_200`。
  - `budget_remaining` 由 Phase 4 run 以 `SoftBudget` 提供（caller 組裝時傳入 `budget.remaining`）；Phase 3 預設 `math.inf`（不限制）。真 fetcher 的組裝已於 Phase 5 M2 完成（`kingstone/cli.py`）；真站上的 budget 行為仍未驗證（禁止連網）。
  - libcurl 傳輸中的大小上限（`MAXFILESIZE_LARGE`）未以真實傳輸驗證：開發環境禁止連網，單元測試只驗證選項有傳入與 `FILESIZE_EXCEEDED`（63）的對應。目前保證 5 MiB 記憶體上限的是 per-call 串流計量（第二道）；第一道是額外保護。
  - TLS 握手中被 reset 若以 curl `RECV_ERROR` 回報，會歸為 `ConnectionError` 並被重試；計畫把 TLS 失敗列為不重試，此分支沒有測試，也未經真站確認。
  - 最後一次嘗試的 Retry-After 不讀，失敗記為 `HTTP_STATUS`；原因分類可能失真（伺服器的意圖是要求等待），目前保留，之後若要區分需另定錯誤類別。
- Phase 5 留下的待辦（M2）：
  - 真站（金石堂網站）的端到端未驗證：所有 HTTP 都是 fake；真站抓取需要當前任務的明確授權。
  - 必要 DB 測試的 skip 風險：既有 `conftest.py` 在缺 dotnet SDK 時 skip EF schema 測試（Books 既有行為，未改）。本次執行 Kingstone DB 測試 19 個全部執行。
  - DB 角色權限：程式只發出 SELECT、INSERT、UPDATE；實際 role 的 grant 屬部署（Phase 6），未驗證。
  - hard limit 強制執行與 runner 屬 Phase 6（見上方待做）。Dockerfile 已於 Phase 6 M1 完成；alert 與診斷檔已於 Phase 6 M5 完成。
- Phase 6 M5 留下的待辦：
  - challenge／CAPTCHA 偵測未實作：acquisition 回 200，parser fail closed，無法與其他無法解析的頁區分。**已以 `unclassified_200` 保守告警**（任何 200 之後的 parse 失敗，不論 status，含列表頁與詳細頁；soft 404 不算）；待收錄 challenge fixture 後，再把其中可辨識的部分細分為 `challenge`，其餘維持 `unclassified_200`。不做猜測性偵測，不以 HTML 猜測 challenge。
  - runner 端的 orphan alert（`ORPHAN_WRITER`）屬 Phase 6 M4；runner 也要把 artifacts 目錄掛入 container（目前程式只使用 `KINGSTONE_ARTIFACTS_DIR`）。
  - `pages_not_reached` streak：history 有壞檔時不判定 streak（少報）；壞檔會留到被 20 份上限擠掉為止，期間 streak alert 不會觸發，需要人工刪除壞檔才恢復。
  - 「provider 停用或未註冊」的 pre-run 結果以 `failed` alert 表達（status FAILED，exit 2）。這是實作決定，若只想對執行失敗告警需另定。
  - `items_listed` 是解析去重後的卡片數（同頁重複的 km_code 只計一次），與計畫 §8「items listed」的字面定義一致，但不等於頁面上可見的卡片總數。
- Phase 6 M1 留下的待辦：
  - CD 尚未推送 `KINGSTONE_CRAWLER_IMAGE` 與 release metadata：`cd.yml` 仍以 `docker build crawler/`（預設 target＝博客來）建置；待後續另案。
  - Kingstone image 在本機未 build（`pip install` 需網路）；build 與離線 smoke 以 CI docker job 為準，實際結果待確認。
  - 清單內容由使用者提供；金石堂真站對這 328 頁的可達性與 image 內的實際抓取未驗證（禁止連網）。

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
