# Crawler 文字測試案例庫

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。以下「已有測試」均表示程式存在但本次未執行，沒有本次通過結果。

## 隔離、資料與命令

Authority：[crawler](../../Docs/modules/crawler.md)、[data-model](../../Docs/data/data-model.md)、[test-plan](../../Docs/testing/test-plan.md)。共同 fixture：[fixtures](../tests/fixtures/README.md) 中保存的總榜、四本詳細頁與會員限制頁；[fakes](../tests/fakes.py) 的 fetch／sleep、[browser_fakes](../tests/browser_fakes.py) 模擬瀏覽器。固定 UTC clock，記錄 request 次數與 sleep；不連博客來。總榜 fixture 要求 100 unique 商品 URL、rank 1..100。錯誤衍生資料由複製 fixture 刪列／缺 title 建立，不改原始檔。

DB 案例用 [conftest](../tests/conftest.py)：由 dotnet EF 產生 idempotent schema，再啟動 disposable `pgvector/pgvector:0.8.7-pg17`，每案清空六張 crawler 表；不讀真實 DATABASE_URL。需要 .NET SDK、tool restore、Docker、Python dependencies，可能下載套件／image，故此文件任務沒有執行。browser 案例使用 fake 或本機 HTTP server／已安裝 Chromium，不連來源網站。host wrapper 測試替換 AWS／Docker／date 等命令，只操作 tmp_path。

日後在核准測試環境自 `crawler/` 執行（本次僅確認檔案存在）：

```bash
python -m pytest tests/test_ranking.py tests/test_ledger.py tests/test_pages_ledger.py tests/test_cli.py tests/test_run_unit.py tests/test_run_pages.py
python -m pytest tests/test_db_integration.py tests/test_e2e_real_fixtures.py tests/test_first_book_integration.py
python -m pytest tests/test_fetcher.py tests/test_curl_fetcher.py tests/test_playwright_fetcher.py tests/test_deploy.py
```

## 案例

### CR-T01 — 總榜完整性

- 責任／規格：§14.1；風險 L2；狀態：已有測試但本次未執行。
- Given：100 列 fixture，另製 99 列、重複 URL、缺 rank 或非 7 日頁；DB 與 detail 呼叫可計數。
- When：呼叫 run_once(deps)。
- Then：合法輸入解析為 rank 1..100；無效輸入 FAILED，DB／detail 未呼叫，舊榜不變；parse／validation 不重試。
- 現有測試或擴充入口：[test_run_unit.py](../tests/test_run_unit.py)、[test_ranking.py](../tests/test_ranking.py)、[test_e2e_real_fixtures.py](../tests/test_e2e_real_fixtures.py)。

### CR-T02 — 來源重用與 ISBN attach

- 責任／規格：§6；data-model §7；風險 L3；狀態：已有測試但本次未執行。
- Given：DB 既有 BOOKS_COM_TW URL、既有 `ISBN` Book（011 後 identifier 只有 `ISBN`），metadata 有可比對值。
- When：run_once，分別給既有 URL／新 URL 同 ISBN／無 ISBN draft。
- Then：既有 URL 無 detail／persist；只以 `ISBN` 類型做 distinct Book 比對，新 source attach 不改 Book／identifiers／contributors／subjects；未命中新增 Book。
- 現有測試或擴充入口：[test_db_integration.py](../tests/test_db_integration.py)。

### CR-T03 — 共用三次與 DB retry

- 責任／規格：§13.1；風險 L2；狀態：已有測試但本次未執行。
- Given：fetch 或 parse 前兩次失敗；另一情境 draft 成功但 persist 三次 psycopg.Error。
- When：run_once；注入 FakeSleep 記錄等待。
- Then：fetch／parse 重抓；DB 失敗只抓一次 detail、沿用 draft；最多三次共用 attempt，backoff 1／2 秒；耗盡 skip、無半本資料，其他原 rank 保留。
- 現有測試或擴充入口：[test_db_integration.py](../tests/test_db_integration.py)、[test_first_book.py](../tests/test_first_book.py)。

### CR-T04 — 限制級與嘗試次數

- 責任／規格：§13.2／14.3；風險 L2；狀態：已有測試但本次未執行。
- Given：會員限制 fixture；另一情境 fetch 先失敗再回會員頁；完整限制級內容頁作對照。
- When：run_once 或 run_first_book。
- Then：明確缺內容容器且含限制級與登入訊息才 skip；不重試、不寫資料、不算一般錯誤、streak 歸零；attempts 為 1 或 2；完整頁可正常解析。
- 現有測試或擴充入口：[test_parsers_real_fixtures.py](../tests/test_parsers_real_fixtures.py)、[test_db_integration.py](../tests/test_db_integration.py)、[test_first_book.py](../tests/test_first_book.py)。

### CR-T05 — 連續錯誤中止與重複 Book

- 責任／規格：§14.2／14.3／14.5；風險 L2；狀態：已有測試但本次未執行。
- Given：20／21 終局一般錯誤、50 本交錯錯誤；成功／重用／限制級插入 streak；兩 source 同 Book。
- When：RunLedger.record 依序或 run_once。
- Then：20 繼續、21 FAILED 且停止後續、舊榜與既有時間保留；交錯錯誤無累計上限，PARTIAL_SUCCESS 可替換；較後重複 Book 無寫入且不 retry，attempts 0 或實際次數。
- 現有測試或擴充入口：[test_ledger.py](../tests/test_ledger.py)、[test_db_integration.py](../tests/test_db_integration.py)。

### CR-T06 — 替換交易與空 snapshot

- 責任／規格：§14.4；風險 L3；狀態：已有測試但本次未執行。
- Given：舊榜與來源時間已存；給錯 ownership／非博客來 source，或 INSERT uniqueness 失敗；另測空 snapshot。
- When：db.replace_bestsellers(conn, rows, captured_at)。
- Then：錯 source 在 DELETE 前拒絕；交易中失敗 rollback 舊榜與 last_seen_at；空 snapshot 合法清空榜單；每書先前 commit 保留。
- 現有測試或擴充入口：[test_db_integration.py](../tests/test_db_integration.py)。

### CR-T07 — pages 清單與 CLI 設定

- 責任／規格：§12／15.3；風險 L2；狀態：已有測試但本次未執行。
- Given：UTF-8 BOM、註解、空行、重複合法 URL；另製非法 URL／非 UTF8／空檔，DB URL 缺失、fetcher 或 timeout 非法。
- When：cli.main(env, mode=CrawlerMode.PAGES)。
- Then：合法清單按首次順序；無效設定 exit 2、fetcher／request 不建立；錯誤含路徑行號不回顯敏感行，secret 不進 log；timeout 範圍 1..300000。
- 現有測試或擴充入口：[test_page_list.py](../tests/test_page_list.py)、[test_cli.py](../tests/test_cli.py)；共用檔案規則的核心測試在 [test_catalog_page_list.py](../tests/test_catalog_page_list.py)（2026-10-25 新增，含非法行不回顯、canonical 去重與上限）。

### CR-T08 — pages Catalog 與時間邊界

- 責任／規格：§15.5／15.9，CB-01；風險 L3；狀態：待補強（已有隔離案例；規格語意待決策）。
- Given：多頁含相同商品、既有 URL、新 ISBN attach、新 Book；舊榜與既有 source 時間已存。
- When：run_pages(deps, page_urls)。
- Then：來源 URL 重用不再 detail；不限制跨頁 Book，無分類 rank 保存，舊榜與既有時間不變；目前新 source 初始化 first_seen_at=last_seen_at=now。補上新建／附加／重用分開斷言後，依 CB-01 決策確認 authority。
- 現有測試或擴充入口：[test_run_pages.py](../tests/test_run_pages.py)、[test_db_integration.py](../tests/test_db_integration.py)。

### CR-T09 — pages skip 與 failure gate

- 責任／規格：§15.4～15.7；風險 L2；狀態：已有測試但本次未執行。
- Given：頁 fetch 三次失敗、頁 parse ValueError、正常頁任意筆數含零列、連續超過 20 列錯誤；另全頁失敗或 find_source DB 逸出。
- When：run_pages(deps, page_urls)。
- Then：單頁 fetch 三次／parse 一次後 skip 繼續；列失敗無上限；全部頁 skip 或逸出例外 FAILED；正常空頁可 SUCCESS；已 commit Catalog 保留，report 無 daily streak 欄位。
- 現有測試或擴充入口：[test_run_pages.py](../tests/test_run_pages.py)、[test_pages_ledger.py](../tests/test_pages_ledger.py)。

### CR-T10 — fetch pacing 與分類／生命週期

- 責任／規格：§12；風險 L2；狀態：已有測試但本次未執行。
- Given：fake session／monotonic clock、可控 uniform 樣本；challenge header、HTTP200 異常頁、非200／redirect；browser 啟動失敗。
- When：Fetcher.get，並經 cli.main 執行 runner。
- Then：首次與重試均節流，處理與 backoff 抵扣，不跟 redirect／停用 TLS；FetchError 保持分類，沒有自動切換；BrowserUnavailableError 整次失敗不 retry；finally close。
- 現有測試或擴充入口：[test_curl_fetcher.py](../tests/test_curl_fetcher.py)、[test_fetcher.py](../tests/test_fetcher.py)、[test_playwright_fetcher.py](../tests/test_playwright_fetcher.py)、[test_cli.py](../tests/test_cli.py)。

### CR-T11 — 診斷證據與保留

- 責任／規格：§12、deployment §8，CB-02；風險 L2；狀態：待補強（現有診斷測試；cleanup 未實作）。
- Given：tmp_path 可寫／不可寫，失敗頁 metadata header 有非允許項，兩次相同 URL 失敗。
- When：save_failure_diagnostics 或 fake browser challenge；未來在隔離目錄執行待建 cleanup。
- Then：現況每次不同檔名、HTML 原樣、JSON 僅選定 headers 不存 cookie，browser 可加 PNG；個別寫失敗不遮蓋 FetchError；cleanup 依先決保留政策測試新舊與例外，不能把原始 HTML 稱為全面去識別。
- 現有測試或擴充入口：[test_fetcher.py](../tests/test_fetcher.py)、test_playwright_fetcher.py；cleanup 測試待建。

### CR-T12 — Host wrapper contracts

本案例分兩組，均為 **Implemented / Not executed in this audit**；deployment coordination 是 target 已有測試，非待實作。來源：[target test_deploy.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/tests/test_deploy.py)；檔案在文件分支與 target 的版本不同，以下以固定 target SHA 為準。測試用 tmp config／state、BASH_ENV 的 AWS／Docker／chown 替身、獨立 maintenance lock 與 state.json 路徑，不連外部服務。

#### CR-T12-A — scheduler／secret contract

- 責任／規格：target deployment §8，CB-03；風險 L2。
- Given：daily/pages 共用 crawler run.lock、pages 上次成功 epoch；Docker 替身可回傳失敗碼，env 暫存檔在 tmp runtime。
- When：以 `execute` helper 呼叫 daily、pages --scheduled；連續兩個 process 測 72h 與 serialization。
- Then：container exit 原樣傳遞、secret 不出 stdout/stderr、env file 權限 600 且結束刪除；未滿259200秒不跑，滿期執行；pages exit0 更新啟動時間、失敗不前移；daily/pages 不重疊。
- 現有測試：`test_daily_keeps_exit_code_and_removes_secret_file`、`test_pages_schedule_survives_new_process_and_becomes_due`、`test_failed_pages_does_not_advance_schedule`、`test_daily_and_pages_share_a_lock`。這些是替身測試，不證明 IAM／EC2 已成功。

#### CR-T12-B — deployment-coordination contract

- 責任／規格：target deployment §8（N3）；風險 L3（正式部署驗證另 L4）。
- Given：`DB_MAINTENANCE_LOCK`、`BOOKFINDER_STATE_FILE` 皆指向本案 tmp 路徑；state 分別缺少、clean、paused object、dirty=true、malformed JSON；另以 holder process 取得 exclusive maintenance lock，Docker 替身可延遲。
- When：呼叫 daily／pages --scheduled；在 wrapper 等待 maintenance lock 時寫入 paused state；Docker 執行期間另用 nonblocking exclusive probe；另將 maintenance wait 設短以觸發 timeout。
- Then：absent state 仍能跑（只略過 state gate，仍取 maintenance lock）；clean 可跑；paused／dirty exit6 且 Docker calls 檔不存在；malformed JSON exit2 fail closed、Docker 不跑。等鎖後讀到新 paused state 並 exit6，證明不能先讀 state；Docker 執行期間 exclusive probe 失敗，證明 shared lock 持續存在；wait timeout exit3、Docker 不跑。OS 讀取錯誤屬程式的同一 fail-closed 分支，現有 unreadable 案例實際注入 malformed JSON，不冒稱已測所有權限錯誤。
- 現有測試：`test_absent_state_keeps_pre_cd_behaviour`、`test_clean_state_runs`、`test_paused_state_skips_before_docker`、`test_dirty_schema_skips_before_docker`、`test_unreadable_state_fails_closed`、`test_lock_is_taken_before_state_is_read`、`test_maintenance_lock_is_held_while_the_container_runs`、`test_maintenance_wait_timeout_exits_3`。
- 跨模組補證：[target test_run_crawler_contract.py](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/deploy/tests/host/test_run_crawler_contract.py) 用 host state writer 建立 paused／dirty／clean state，再呼叫真 wrapper 與替身 Docker，保護 crawler.paused／schema.dirty 欄位 contract；本次亦未執行。

以上測試需以 target／合併後版本執行，較早文件分支的 test_deploy.py 不包含 N3 案例。現有 pytest 入口不等於本次已通過；不可套用正式 state／lock／AWS 設定。

### CR-T13 — 正式啟用前證據

- 責任／規格：deployment §8，CB-03；風險 L4；狀態：待驗證（需當前 production 與真實抓取授權）。
- Given：授權後 EC2 image 已預載、EF schema、SSM DB 參數、權限／時區／disk 已確認，先保留舊榜可比對資料。
- When：依 deploy README 手動一次，再按核准步驟啟用 cron。
- Then：保存去識別 run status／exit、來源解析與榜單有效性證據；challenge 阻擋不啟用；rollback 停用該 cron 並保留既有榜單；不可用 fixture 結果代替 live 證據。
- 現有測試或擴充入口：../deploy/README.md，無自動 live 測試。

### CR-T14 — normalization 與內容界線

- 責任／規格：§7／11；data-model；風險 L3；狀態：已有測試但本次未執行。
- Given：有效／錯誤 ISBN、完整／年月日期、未知語言、缺 optional、分類多層與多貢獻者 HTML。
- When：parse_detail_html → BookDraft → persist_new_source。
- Then：ISBN 依 §7.1 正規化後以 `ISBN` 類型保存（不驗 checksum、不驗長度），日期保存實際精度、未知語言 NULL 並 log，subtitle NULL、optional 不推測，分類去重，角色正規化；不寫 embedding／AI tables。公開 API 排除簡介／目錄另由 Web 案例驗證。
- 現有測試或擴充入口：[test_normalize.py](../tests/test_normalize.py)、[test_parsers_real_fixtures.py](../tests/test_parsers_real_fixtures.py)、[test_e2e_real_fixtures.py](../tests/test_e2e_real_fixtures.py)。

### CR-T15 — first-book 不改榜與冪等

- 責任／規格：§16；風險 L2；狀態：已有測試但本次未執行。
- Given：完整總榜與 rank1 詳細 fixture，既有榜與 Catalog。
- When：run_first_book 兩次或 first-book CLI。
- Then：僅第一次匯入 rank1，新來源再跑重用；榜與既有來源時間不變；rank1 一般失敗 exit1，限制級 exit0 partial，設定錯誤 exit2；fetcher 關閉。
- 現有測試或擴充入口：[test_first_book.py](../tests/test_first_book.py)、[test_first_book_integration.py](../tests/test_first_book_integration.py)。

### CR-T16 — 單調 touch 與 provider 隔離

- 責任／規格：catalog_core persistence（Kingstone plan §3、§5，P1 M2）；風險 L3（touch 寫入與 provider 邊界）；狀態：已有測試（2026-10-25 新增並執行）。
- Given：一筆 BOOKS_COM_TW Source，`last_seen_at` 為 NOW；一筆 KINGSTONE 草稿（帶 `external_id`）；與 BOOKS_COM_TW 同 URL 的既有 Source。
- When：以較晚時間 touch；以較早時間（時鐘倒退）touch；同一時間重複 touch；以 KINGSTONE touch BOOKS_COM_TW 的 Source；touch 不存在的 Source id；以 KINGSTONE 寫入新 Source；以 KINGSTONE 與 BOOKS_COM_TW 分別做身分查詢；run 中 touch 匹配不到列。
- Then：`last_seen_at` 變成較晚時間，較早時間不改它，重複 touch 結果不變；錯誤 provider 與不存在的 Source 都拋 `SourceTouchConflict` 且列不變；KINGSTONE 寫入同時存 `source_code` 與 `external_id`；同 URL 對 KINGSTONE 為 NEW、對 BOOKS_COM_TW 為 EXISTING；external_id 查詢只看自己的 provider；run 中 touch 衝突的列記為 `source_identity_conflict`（attempts 1），不重試、不抓詳細頁、不 sleep，榜單不含該列。
- 來源與狀態：[test_persistence_integration.py](../tests/test_persistence_integration.py)、[test_db_integration.py](../tests/test_db_integration.py)（`test_a_touch_conflict_skips_the_row_as_source_identity_conflict_without_a_retry`、`test_a_clock_moved_back_keeps_a_later_last_seen_and_the_source_is_still_existing`）；[test_reconnect_integration.py](../tests/test_reconnect_integration.py)（`test_a_touch_commit_whose_acknowledgement_is_lost_is_idempotent_on_retry`，touch 已 commit 但 ACK 遺失，重試後仍 EXISTING、單列、`last_seen_at` 不變）。

### CR-T17 — 共用 item 解析 service

- 責任／規格：`catalog_core/service`（Kingstone plan §3、§5，P1 M3；M3b 讓 Books 經由同一 service）；風險 L3（identity、touch、寫入與重試語意）；狀態：已有測試（2026-10-25 新增並執行）。
- Given：`tests/test_catalog_service.py` 的 in-memory `CatalogStore` fake（可指定 identity、touch 結果、ISBN 匹配、寫入與各步驟拋出的 `psycopg.Error`）、可注入的 `fetch_draft`（draft、可重試或不可重試的 `DraftFailure`）、固定 clock 與 attempts。
- When：逐一執行 service 的每個分支：CONFLICT；EXISTING touch 成功、失敗後重試成功、耗盡；touch 回傳 False；NEW 的 fetch 失敗、不可重試失敗、parse 後 ISBN 查詢失敗、1／0／2 本匹配、寫入失敗後 commit 不確定與重新解析（EXISTING 恢復、未 commit 繼續寫入、CONFLICT 結束且不再查 ISBN 或寫入）、耗盡；寫入政策（Phase 5 M1）：`new-books-only` 下 ISBN 0／1／≥2 本、無 ISBN，`normal` 下 1 本，uncertain commit 後 re-resolve 得到政策跳過。
- Then：每個分支的 `ItemResolved`／`ItemFailed`／`ItemPolicySkipped` 欄位（`attempts`、`reason`、`identity_warning`、`recovered_commit`、`matched_book_ids`、`matched_book_id`）、`on_attempt_failed` 的呼叫次序，以及 CONFLICT 與 touch 衝突時 fetch 與寫入的次數都符合規格。政策跳過時 `persist_new_source` 與 `touch_source` 都不被呼叫；`POLICY_SKIPPED_EXISTING_BOOK` 不在 `RESOLVED_CATALOG_RESOLUTIONS` 內。Books 的既有測試不改即過。
- 來源與狀態：[test_catalog_service.py](../tests/test_catalog_service.py)（fake store，覆蓋所有分支；35 個測試，含 Phase 5 M1 的 8 個寫入政策案例）。Books 的整合測試（[test_db_integration.py](../tests/test_db_integration.py)、[test_first_book.py](../tests/test_first_book.py)、[test_reconnect_integration.py](../tests/test_reconnect_integration.py)）經由 adapter 與真實 session／store 覆蓋同一條路徑。

### CR-T18 — 共用 HTML 區段文字抽取

- 責任／規格：`catalog_core/html_text`（Kingstone Phase 2 M3 抽出，Books 規格與金石堂詳細頁共用）；風險 L2；狀態：已有測試（2026-10-25 新增並執行）。
- Given：含 `<br>`、`<p>`、`<li>`、`<strong>`／`<a>` 等 inline 與 block 元素的片段；原始碼內的 CRLF 與多餘空白；只有空白的區段。
- When：`text_with_line_breaks(node)`。
- Then：只有 `<br>` 與區塊邊界產生換行；inline 元素不切行；原始碼換行不算換行；連續空行收為一行；頭尾空行去除；全空白區段回傳 None。Books 的規格文字由既有 Books 解析測試（未改）覆蓋。
- 來源與狀態：[test_html_text.py](../tests/test_html_text.py)（15 個測試）；Books 端由 `books_crawler/parsers.py` 的既有測試覆蓋。

### CR-T19 — Catalog migration lock（crawler 端，plan v12 §8）

- **責任／規格**：[architecture](architecture.md)「catalog_core/session」與「catalog_core/migration_lock」、[workflow](workflow-diagram.md)「DB session 與 migration lock」；Kingstone plan v12 §8（第 1 點 shared lock 契約：每次初次連線與每次 reconnect 先取 shared，取不到不寫入；第 1 點的 Phase 6 必測）；風險 L3（決定 migration 與寫入是否互斥，寫入是否在 lock 之外發生）；狀態：已有測試（2026-10-25 新增並執行）。
- **Given**：真 PostgreSQL（`db_url`）；另一條 admin 連線扮演 migration，以 `pg_advisory_lock`／`pg_try_advisory_lock` 持有 exclusive 側（key `CATALOG_MIGRATION_LOCK_KEY = 2026102501`）。crawler 端使用真 `DatabaseSession`、真 `SessionCatalogStore`，只有 fetcher 與 parser 是 fake。反覆斷線以 `pg_terminate_backend` 完成，與 CR-T（連線中斷與重連）相同。
- **When／Then**：
  - crawler 連線持有 shared → 另一條連線的 `pg_try_advisory_lock` 為 False（migration 不可開始）；pg_locks 上持有 shared 的 pid 即為 crawler backend。
  - 連線關閉後 lock 釋放，另一條連線可取得 exclusive。
  - migration 持有 exclusive → crawler 首次連線拋 `MigrationLockBusy`，連線已關閉，資料表計數（books、book_sources、book_identifiers）不變。
  - migration 持有 exclusive → kingstone `run_pages` 以真 store 回報 FAILED（error 含 `migration lock busy`），計數不變；Books `run_pages`（pages）與 `run_once`（daily）同樣 FAILED、零寫入。
  - crawler reconnect（terminate 後 `broken` 再取連線）→ 新 backend 取得 shared（pg_locks 確認），之後 `persist_new_source` 成功。
  - run 中途連線斷線 → 重連後取得 shared，run 繼續到 SUCCESS，第三張卡的 backend 與斷線前不同、持有 shared。
  - run 中途斷線，且 migration 在斷線後取得 exclusive → 重連 busy，run FAILED，只保留斷線前已寫入的第一張卡，不寫入第二張卡。
  - `MigrationLockBusy` 不是 `psycopg.Error`；service 對它不重試，identity、touch、ISBN lookup、persist 四個呼叫點各只呼叫一次就拋出（[test_catalog_service.py](../tests/test_catalog_service.py)）。
  - session 單元：每個新連線（含 reconnect）都取 lock 一次，已有的健康連線不重取；busy 關閉新連線並拋 `MigrationLockBusy`；busy 的 reconnect 關閉舊與新連線；lock 查詢的 `psycopg.Error` 原樣拋出並關閉連線（[test_session.py](../tests/test_session.py)）。
  - 常數 `CATALOG_MIGRATION_LOCK_KEY == 2026102501`，`try_acquire_shared` 送出 `pg_try_advisory_lock_shared` 與該 key，回傳結果；`MigrationLockBusy` 不是 `psycopg.Error`（[test_migration_lock.py](../tests/test_migration_lock.py)，純函式）。
- **已知驗證缺口**：deploy 端的 exclusive 取得、efbundle 掉線中止與 dirty 標記屬 M3，不在本 repo 的 crawler 測試內；跨模組一致性測試（crawler 常數與 `deploy/host/bookfinder_host/` 的常數相等）也由 M3 負責。真 migration（efbundle）與 crawler 的實際並行未驗證；本測試以第二條連線代替 migration。
- **來源與狀態**：[test_migration_lock_integration.py](../tests/test_migration_lock_integration.py)（真 DB，鎖相關 6 個：crawler 持有 shared、釋放、busy 首次連線、Kingstone run 零寫入、Books pages 與 daily 零寫入；reconnect 3 個；其餘 preflight 案例屬 CR-K12）、[test_migration_lock.py](../tests/test_migration_lock.py)（純函式 3 個）、[test_session.py](../tests/test_session.py)（session 單元 11 個，其中 lock 相關 5 個）、[test_catalog_service.py](../tests/test_catalog_service.py)（busy 不重試 4 個參數化案例）。

## 狀態限制

沒有明確暫緩的 crawler 核心功能；embedding 是明確不屬此模組，不建立待實作案例。artifact cleanup 是未實作改善提案；產品時間語意需決策。沒有程序取消狀態與取消測試，不推定 finally 可處理 SIGKILL。本次僅靜態文件檢查，所有命令均是日後測試入口。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)。

## Phase A（#116）測試覆蓋

| 測試 | 覆蓋 | 規格 |
|---|---|---|
| [test_ledger.py](../tests/test_ledger.py) | RankingDecision 完整表；Existing Source 的榜內重複不 reset streak；附加後才重複的 Catalog 與 ranking 計數；10 個 ERROR_SKIP → RESTRICTED_SKIP → ERROR_SKIP 後 streak 為 1；DUPLICATE_BOOK 記錄而非 raise | §3.5、§10.2、§14.2、§14.3（plan §4 #5–#7） |
| [test_pages_ledger.py](../tests/test_pages_ledger.py) | pages 只用 CatalogResolution；Catalog 軸計數與 items_seen | §10.2、§15.5、§15.8 |
| [test_first_book.py](../tests/test_first_book.py) | first_book 的 summary 欄位與 job_name；既有來源計為 existing | §16、§19.2 |
| [test_run_unit.py](../tests/test_run_unit.py)、[test_run_pages.py](../tests/test_run_pages.py) | summary 欄位順序（daily 與 pages） | §15.8、§19.2 |
| [test_db_integration.py](../tests/test_db_integration.py) | 榜內重複時 Catalog 側已 commit（新 Source 存在），只跳過 rank；需要真實 PostgreSQL（EF schema） | §14.2 |
| [test_deploy.py](../tests/test_deploy.py) | `first_book` 模式的 module、pause／dirty gate、共用 run.lock 與 maintenance lock | deploy README §6 |

Phase B（#116）覆蓋：

| 測試 | 覆蓋 | 規格 |
|---|---|---|
| [test_isbn_fixture.py](../tests/test_isbn_fixture.py) | 共用 `tests/Fixtures/isbn-normalization.json` 逐 byte；每個 White_Space code point 都有 vector；反例保留 | data-model §7.1（plan §4 #18） |
| [test_identity.py](../tests/test_identity.py) | §7.3 矩陣每一列（純函式） | §7.3（plan §4 #19） |
| [test_db_integration.py](../tests/test_db_integration.py) | 0／1／≥2 本比對；既有 `ISBN` row 與 draft ISBN 同一本；只查 `ISBN`（`OTHER` 不比對）；011 schema 拒絕 `ISBN_10`／`ISBN_13`；補 NULL（日期成對、AUTHOR 條件、updated_at 只在補值時更新）；ambiguous 不改既有 Book；touch 每次 run、重試不重抓、最後失敗的 daily policy；`replace_bestsellers` 不更新 `last_seen_at`；URL drift、衝突、NULL external_id；011 後無 `source_type` 欄位；`provider_enabled` | plan §4 #1–#4、#11、#15 概念、#17、#19 |
| [test_first_book.py](../tests/test_first_book.py) | touch 最後仍失敗 → FAILED exit 1，不重抓 detail | plan §4 #17 |
| [test_run_pages.py](../tests/test_run_pages.py) | touch 最後仍失敗 → 只跳過該列，其餘照常 | plan §4 #17 |
| [test_cli.py](../tests/test_cli.py) | 停用 provider → exit 2 且不建立 fetcher；讀 registry 失敗 → exit 1 | crawler.md §3.1 |
| [EfStaleDetectionTests.cs](../../tests/DatabaseIntegration/EfStaleDetectionTests.cs)（C#，`dotnet test tests/DatabaseIntegration`） | 9 種 §7.4 補值：AUTHOR、subject、description 讓 embedding pending 且 profile stale；publisher、table_of_contents 只讓 profile stale；published_date、page_count、thumbnail_url、ISBN 兩者皆不變 | plan §4 #15 |

migration 011 的 schema 由 test_db_integration.py 在 011 上檢查（無 `source_type`、拒絕 legacy identifier 類型）；§11.3 gate 的實際執行證據不在此。尚未覆蓋：C# 端 fixture（#115 的測試範圍）；stale 偵測屬 Web 端（#115）。

### Unicode 15.1 NFKC 一致性（data-model §7.1）

- **Given**：vendored `tests/Fixtures/unicode-15.1/NormalizationTest-NFKC.txt`（19074 組 c1→c4）；`tests/Fixtures/isbn-normalization.json` 含未指派 OUTLINED DIGIT 與混合分段的 vector。
- **When**：對每組 c1 執行分段 NFKC；對 U+1CCF0 與混合字串執行 `normalize_isbn_value`；以 `ensure_runtime_unicode_supported` 模擬舊 runtime。
- **Then**：每組結果與 c4 逐字相同；未指派 code point 原樣保留並分段；舊 runtime 啟動時 exit 2。
- **來源與狀態**：[test_unicode_nfkc_conformance.py](../tests/test_unicode_nfkc_conformance.py)、[test_isbn_fixture.py](../tests/test_isbn_fixture.py)、[test_cli.py](../tests/test_cli.py)；CI `unicode_tables.py --check` 檢查產生檔沒有漂移。

### CR-K01 — 金石堂 fixture contract（E0）

- **責任／規格**：[backlog](backlog.md)「CB-07 來源契約」；風險 L2；狀態：已有測試（2026-10-25 新增並執行）。這組測試在 parser 存在之前寫成，直接以 BeautifulSoup 讀 fixture，固定 fixture 的解讀；parser 本身的行為由 CR-K03、CR-K04 驗證。
- **Given**：[kingstone fixtures](../tests/fixtures/kingstone/README.md) 的 5 個列表頁、7 個詳細頁、1 個 soft 404。
- **When**：以 contract 的選擇器與欄位規則讀取每份 fixture。
- **Then**：列表卡數 48／48／39／0／6，`data-prodno` 與連結 km_code 一致，卡片文字沒有 ISBN；空頁有 `.emptyCategory`、沒有 `.productGrid`，巢狀推薦卡不被選到；`sort=pu_desc` 出版日遞減；詳細頁 `sku` 等於檔名、`isbn` 等於 `gtin13`、`name` 非空、`image[0]` 是 assets 網址、「分級」為普通級；簡體書規格表是中文簡體但 JSON-LD `inLanguage` 是 `zh-TW`；作者連結含原文姓名、「、」串接與「審訂/」前綴，JSON-LD `author` 只有第一個連結；譯者是純文字；breadcrumb 原始清單重複兩次，subjects 依序去重並去掉「中文書」；soft 404 沒有 Product JSON-LD；README 與檔案一一對應。
- **來源與狀態**：[test_kingstone_fixture_contract.py](../tests/test_kingstone_fixture_contract.py)。Phase 2 的 parser 測試要沿用同一批 fixture；之後各 Phase 的必測行為見 [v11 計畫](../../Docs/plans/kingstone-category-crawler.md) §9。

### CR-K02 — 金石堂清單與 URL grammar

- **責任／規格**：[backlog](backlog.md)「CB-07 來源契約」與 Kingstone plan v11 §3–§4；風險 L2；狀態：已有測試（2026-10-25 新增並執行）。純函式與檔案讀取，不連線金石堂，也不碰資料庫。
- **Given**：[fixtures README](../tests/fixtures/kingstone/README.md) 列出的五個列表頁網址、五種排序鍵（`sa_desc` 與省略 sort 視為同一頁，canonical 移除；`pu_desc`、`pu_asc`、`pr_desc`、`pr_asc` 保留）、以及不在 grammar 內的網址（http、其他主機、無 www、userinfo、port、fragment、`/normal/book/jd`、缺尾斜線、代碼 1 或 5 字母或含數字、缺 `dis` 或 `page`、`dis=pic`、page 為 0／-1／01／abc、未知 sort、多餘或重複參數）；`list_jdc_p1.html` 的每張卡片連結；一份含 BOM、註解、空行、大小寫不同代碼的清單檔；`kingstone-pages.txt`（使用者提供的 328 筆）。
- **When**：`canonical_list_url`、`detail_url`、`km_code_from_href` 與 `kingstone.page_list.load_page_urls` 處理上述輸入。
- **Then**：合法網址得到固定順序（dis、page、sort）的 canonical 形式，代碼轉小寫，查詢參數順序不影響結果；不合法網址回 None；`detail_url` 只接受 13 位數字；每張卡片的 href 都解析為 `data-prodno`；清單檔以 canonical 值去重並保留首見順序（同一頁的 `sa_desc` 版本只保留一筆並記 INFO log），400 上限依 canonical 後的計數（400 個不同頁加上其中一頁的 `sa_desc` 版本仍接受；401 個不同頁失敗），非法行的錯誤含檔名與行號但不含網址文字，超過 400 個 URL 失敗，空清單回 `PageListError`；預設檔 `kingstone-pages.txt` 可載入、筆數在 1～`MAX_PAGES` 之間、彼此不重複、每筆都是 `?dis=list&page=1`（只固定規則，不固定筆數與內容，使用者改清單時不必改測試）；讀檔錯誤訊息經 `catalog_core.redact`（路徑中的 `password=` 會被遮蔽）。
- **來源與狀態**：[test_kingstone_urls.py](../tests/test_kingstone_urls.py)、[test_kingstone_page_list.py](../tests/test_kingstone_page_list.py)、[test_catalog_page_list.py](../tests/test_catalog_page_list.py)（核心 loader）；Books 的 [test_page_list.py](../tests/test_page_list.py) 不變。角色標籤表屬於 Books adapter，core 不再持有；[test_normalize.py](../tests/test_normalize.py) 檢查 `catalog_core.normalize` 不匯出 `ROLE_MAP`／`map_contributor_role`。

### CR-K03 — 金石堂列表頁 parser

- **責任／規格**：[architecture](architecture.md)「金石堂 adapter」的列表頁段落（來源：backlog CB-07 E0 契約）；風險 L2；狀態：已有測試（2026-10-25 新增並執行）。純函式，不連線。
- **Given**：E0 真實列表頁 fixture：`list_jdc_p1.html`（48 張）、`list_jdc_p1_pu_desc.html`（48 張）、`list_jdc_p93.html`（末頁 39 張）、`list_jdc_p94.html`（合法空頁，含 24 張推薦卡）、`list_sj_p1.html`（6 張）；合成 HTML 覆蓋 grid 外與輪播卡、重複 km_code、恰好 48 與 49 張、grid 有但 0 張卡、缺 `#allProducts`／`#displayCSS`、沒有 grid 也沒有空頁提示、空頁提示文字不符、非 13 位 `data-prodno`、缺 `.coverbox` 連結、href 不在 grammar、`data-prodno` 與連結 km_code 不符、totals 缺少／合法／格式異常。
- **When**：`parse_list_html(html, canonical_url)`；非 canonical URL 另測。
- **Then**：真實頁卡數為 48／48／39／0／6，順序與首末 km_code 正確，`source_url` 為 `/basic/<km_code>/`、`list_url` 為列表頁 URL；合法空頁為 `empty=True` 的成功結果，推薦卡不計；重複 km_code 保留首見；0 張卡或超過 48 張、缺 grid／display、非合法空頁、`data-prodno` 非 13 位或與連結 km_code 不符皆為 `KingstoneParseError`；totals 是 report-only：totalPages 或共計格式異常時該欄為 None、商品卡完整解析、`kingstone.parse_list` 記 WARNING 且不回顯 HTML，兩者同時異常時各記一筆 WARNING、三張卡全數保留；非 canonical URL 為 `ValueError`。
- **來源與狀態**：[test_kingstone_parse_list.py](../tests/test_kingstone_parse_list.py)（54 個測試）。

### CR-K04 — 金石堂詳細頁 parser

- **責任／規格**：[architecture](architecture.md)「金石堂 adapter」的詳細頁段落（來源：backlog CB-07 E0 契約）；風險 L3（直接決定寫入 Book／Source 的欄位與錯誤分類）；狀態：已有測試（2026-10-25 新增並執行）。純函式，不連線。
- **Given**：E0 的 7 份真實詳細頁 fixture（含簡體書、審訂前綴、括號原文作者、譯者行、多作者）；soft 404 fixture `detail_2099999999999.html`；合成 HTML 覆蓋 JSON-LD 為陣列或 `@graph`、JSON 損壞、sku 與 URL 不符、sku 缺少、name 缺少或空白、title 不是站名、gtin13 代替 isbn、ISBN 無值、日期格式不合或不存在、publisher 缺少、image 為陣列或字串、語言對應與缺列、頁數為 0、非數字、帶單位、非法 URL、作者括號與全形括號（成對整段才跳過，「(甲)乙(丙)」與「(X）」照一般作者名）、「、」拆分、角色前綴（含博客來角色表認得的「繪者/」）一律 OTHER、譯者純文字、譯者列的「追蹤」與「?」節點、subjects 去重與根節點、description／目錄缺少。
- **When**：`parse_detail_html(html, canonical_url)`；非 canonical URL 另測。
- **Then**：真實頁各欄位符合 fixture 的已知值；description 與目錄保留換行、無相鄰區塊文字外漏（活動、相關主題、作者介紹不被讀）；soft 404 為 `ProductNotFound` 而非 parse error；損壞 JSON 或 sku 不符、name 缺少為 `KingstoneParseError`；日期無效與語言未知為 None（後者記 WARNING）；ISBN 只來自 `isbn` 或 `gtin13` 並經共用正規化；作者與譯者的角色與順序依規則；譯者列排除「追蹤」「?」；subjects 去掉「中文書」並去重；非 canonical URL 為 `ValueError`。
- **來源與狀態**：[test_kingstone_parse_detail.py](../tests/test_kingstone_parse_detail.py)（74 個測試）。

### CR-K05 — 金石堂 HTTP acquisition

- **責任／規格**：[architecture](architecture.md)「金石堂 adapter」的 Acquisition 段落（來源：backlog CB-07「Acquisition」）與計畫 §6、§9 Phase 3；風險 L3（URL 守門、重送與 budget 決定是否對外發出請求）；狀態：已有測試（2026-10-25 新增並執行）。全部離線：fake transport、fake clock、記錄型 fake sleep 與 fake curl session，不連網。
- **Given**：合法的列表頁與詳細頁 canonical URL；不合法的 URL（非 canonical 列表頁、`sort=sa_desc`、http、其他 host、userinfo、port、IP literal、詳細頁帶 query、列表與詳細頁互換、非字串）；transport 依序回傳的 200、3xx、4xx、429／500／502／503／504、timeout、connection error、`ResponseTooLarge`、非 UTF-8 的 200，以及 Retry-After（秒數、極長的數字、HTTP-date、已過去的日期、無法解析、超過 120 秒、最後一次嘗試）；固定的 sample delay；有限的 budget（含 0 與負數，且 pacing 已過的情況）；fake curl session 的 Content-Length、串流、例外、headers 與 session 建立參數（含 `MAXFILESIZE_LARGE`）；curl 的 `RequestException`（code 63 `FILESIZE_EXCEEDED` 與其他 code）。
- **When**：`KingstoneFetcher.fetch_list_page`、`fetch_detail_page`，以及 `CurlTransport.get`。
- **Then**：不合法 URL 為 `ValueError` 且 transport 未被呼叫；第一個請求也等待 sample delay，已過時間計入，重試也受 pacing 約束，pacing 與 backoff 取最大值；timeout、connection error 與 429／500／502／503／504 重試，用盡時為 `TRANSPORT`／`HTTP_STATUS`（attempts=3）；400、403、404 與其他 transport 例外不重試；backoff 為 5、10 秒並受 60 秒上限約束；Retry-After 秒數與 HTTP-date 生效，超過 120 秒立即 `RETRY_AFTER_TOO_LONG` 且不重送；每次請求前檢查 budget：budget 為 0 或負數時即使 pacing 已過也 `BUDGET_EXHAUSTED`，不睡、不送；等待超過 budget 時同樣；極長的 Retry-After 數字為 `RETRY_AFTER_TOO_LONG`；302 為 `REDIRECT`，不跟隨、不重試；`ResponseTooLarge` 為 `OVERSIZE` 不重試，transport 收到的 max_bytes 為 5 MiB、timeout 為 30；200 非 UTF-8 為 `DECODE_ERROR`；錯誤訊息不含 body、cookie、header 或 transport 例外的訊息；`CurlTransport` 送出 `allow_redirects=False`、`stream=True`、Chrome impersonation 與 Accept-Language，Content-Length 或串流超過上限即 `ResponseTooLarge` 並關閉 response，timeout 與 connection 例外映射為可重試例外，SSL 例外不映射；session 以 `MAXFILESIZE_LARGE = 5 MiB` 建立，libcurl 的 code 63 映射為 `ResponseTooLarge`（`OVERSIZE`，不重試），其他 curl 例外原樣傳出；每次請求一行 INFO，重試一行 WARNING。Phase 4 M1 新增的可設定參數：`timeout` 傳給 transport 的 timeout；`max_attempts=1` 不重試 timeout 與可重試狀態（attempts=1）、`max_attempts=2` 在第 2 次後停止；`max_attempts` < 1 為 `ValueError`；`max_response_bytes` 傳給 transport 的 `max_bytes`，body 恰等於上限可接受、超過即 `OVERSIZE`；`CurlTransport(max_response_bytes=)` 與 `KingstoneFetcher` 建立的 session 以該值設定 `MAXFILESIZE_LARGE`；預設值與模組常數一致。
- **Phase 6 M5 新增（請求計數）**：`http_attempts` 為實際送出的請求數（含重試）；`http_failures` 為送出後沒有可用 200 body 的請求數（transport 例外、非 200 狀態含 3xx、body 超過上限、非 UTF-8）；被 budget 拒絕的請求不計入任一項；不合 URL grammar 的呼叫不計入。
- **來源與狀態**：[test_kingstone_acquisition.py](../tests/test_kingstone_acquisition.py)（113 個測試，`pytest --collect-only -q tests/test_kingstone_acquisition.py`；Phase 6 M5 新增請求計數的 6 個）。已知驗證缺口：libcurl 傳輸中的 63 實際觸發未以真站或真實傳輸驗證（禁止連網）；TLS 握手中的 reset 分類未有測試（見 [backlog](backlog.md) CB-07 Phase 3 待辦）。

### CR-K06 — 金石堂 run 設定

- **責任／規格**：[architecture](architecture.md)「金石堂 adapter」的「設定」段落與計畫 §7 設定表；風險 L2（決定 budget 與回應上限）；狀態：已有測試（2026-10-25 新增並執行）。純函式：只讀傳入的 mapping，不讀環境、不讀 `.env`、不讀檔。
- **Given**：空 mapping；`KINGSTONE_WRITE_POLICY` 的 `normal`、`new-books-only`、前後空白、空白與非法值（大小寫、底線、`all-books`、`all`、`0`）；每個鍵的合法值（含前後空白）；空字串與只含空白的值；非數字（`abc`、`3 300s`、`1,5`）；0 與負數；`nan`、`inf`、`-inf`、`Infinity`、`1e400`；次數與位元組數的小數、科學記號、正號與含空白；`soft` 等於或大於 `hard`（9000 對 9000，以及預設 hard 下的 9001）；調低 hard 後 soft 仍小於 hard。
- **When**：`kingstone.config.load_config`。
- **Then**：未設定時為 7200／9000 秒、30 秒、3 次、5 MiB、預設清單檔與寫入政策 `new-books-only`（Phase 6 M1 由 3300／3600 調整）；寫入政策只接受 `normal`／`new-books-only`，其他值 raise 且訊息點名 `KINGSTONE_WRITE_POLICY`、不回顯值；每個合法鍵都生效；空白值視為未設定；非法值 raise `KingstoneConfigError`（`ValueError` 子類），訊息點名 key，非數字的值不被回顯；`soft ≥ hard` 點名兩個 key。
- **Phase 6 M5 新增**：`KINGSTONE_ARTIFACTS_DIR` 空白視為未設定（預設 `crawler/artifacts`，以 package 為基準）、可由環境覆寫；`KINGSTONE_DIAGNOSTIC_MAX_BYTES` 預設 2 MiB，只接受正整數（0、負數、小數、非數字、科學記號皆 raise，訊息點名 key）。
- **來源與狀態**：[test_kingstone_config.py](../tests/test_kingstone_config.py)（84 個測試，含參數化案例）。預設值（7200／9000）由 `test_defaults_when_nothing_is_set` 固定；博客來不讀 `KINGSTONE_SOFT_RUN_BUDGET_SECONDS` 與 `CRAWLER_RUN_HARD_LIMIT_SECONDS`（全 crawler 原始碼搜尋只出現在 `kingstone/` 與其測試）。

### CR-K07 — 金石堂 run 帳本與 terminal status

- **責任／規格**：[architecture](architecture.md)「Run 帳本與 terminal status」與計畫 §7 terminal 表、useful progress 定義；風險 L2（決定 run 的 exit code 與報告）；狀態：已有測試（2026-10-25 新增並執行）。純記帳，不做 I/O，不需要資料庫或 fetcher。
- **Given**：清單 URL；`ItemResolved`（各 resolution、`recovered_commit`、`identity_warning`）、`ItemFailed`（含 warning）與 `ItemPolicySkipped`（Phase 5 M1）；跳過的頁；budget 在頁前、頁中、頁後停止；致命錯誤；空清單；只有空頁的清單；違反順序的呼叫（未列出的 URL、重複開始、開啟中的頁之外記卡片、budget 之後開始或跳過頁）。
- **When**：`KingstoneLedger` 的呼叫序列與 `report`；`decide_status` 的純計數表；`format_report`；`exit_code`。
- **Then**：terminal 表每一列：致命錯誤 FAILED（無 zero-progress reason）；所有頁跳過 FAILED；budget 在第一頁完成前用盡 FAILED（頁中與頁前兩種）；清單為空 FAILED；部分跳過、失敗書、interrupted 頁、not reached 頁各自為 PARTIAL_SUCCESS；全部 Existing 為 SUCCESS；成功頁全為 0 張卡為 SUCCESS，`zero_card_pages` 計數；只有空頁亦為 SUCCESS 且不填 zero-progress reason。計數：各 resolution、`recovered_commit_count`、`identity_warning_count`、`items_seen`；`pages_interrupted` 與 `pages_not_reached` 依規則計算。違反順序的呼叫 raise `ValueError`。WARNING 只在跳過頁與失敗書時記在 `kingstone.ledger`，Existing 與 Imported 不記。`format_report`：欄位順序固定（Phase 6 M5 起，`items_listed`、`details_fetched`、`http_attempts`、`http_failures` 位於 `items_seen` 之後），每行一列，`budget_exhausted` 為 `true`／`false`，文字欄位與 `error` 為 JSON 字串或 `null`，清單欄位為 `ensure_ascii=False` 的 JSON（含中文訊息）；exit code 為 FAILED → 1、其餘 → 0。寫入政策（Phase 5 M1）：政策跳過計入 `policy_skipped_count`，不計入失敗與 `failed_items`，其 identity warning 計入 `identity_warning_count`；全部政策跳過為 SUCCESS 且 `zero_progress_reason` 為 null；報告帶 `write_policy`，`format_report` 欄位含 `write_policy`（在 `provider_code` 後）與 `policy_skipped`（在 `ambiguous_created` 後）。
- **來源與狀態**：[test_kingstone_ledger.py](../tests/test_kingstone_ledger.py)（46 個測試）。已知驗證缺口：budget 停止與 replay 的行為由 CR-K08 以 fake 組裝驗證；真 DB 端到端由 CR-K09、CR-K10 驗證；真站的端到端仍未驗證（禁止連網）。訊息 redaction 由 run 負責（CR-K08），這裡只驗證輸出格式。

### CR-K08 — 金石堂逐頁 run

- **責任／規格**：[architecture](architecture.md)「Run（逐頁流程）」、[workflow-diagram](workflow-diagram.md)「金石堂逐頁 run」與計畫 §5、§7、§9 Phase 4；風險 L3（決定寫入 Catalog、budget 停止點與 replay）；狀態：已有測試（2026-10-25 新增並執行）。全部離線：fake fetcher（URL → HTML 或例外）、記憶體 store、fake clock、記錄型 sleep；HTML 用真實 detail fixture 與合成的列表頁，不連網、不碰資料庫。
- **Given**：列表頁（合成卡片或真實 fixture）、詳細頁 fixture、soft 404、302、parse error、合法空頁；store 的 identity 狀態、DB 失敗腳本、commit 後才失敗的寫入；budget 在首頁前、第二頁前、頁中用盡，或詳細頁、列表頁回 `BUDGET_EXHAUSTED`；store 拋出含假 DSN 與密碼的 `psycopg.Error`。
- **When**：`run_pages` 一次；同一 store 再跑一次（replay）；寫入政策（Phase 5 M1）的 `new-books-only` 與 `normal` 各跑一次，store 的 ISBN 命中以 fixture 的 ISBN 設定。
- **Then**：全部 New 寫入，report 計數正確，SUCCESS；replay 全部 Existing、詳細頁 0 次請求；列表頁 302 與 parse error 跳過該頁，下一頁照常；全部跳過為 FAILED 並附 zero_progress_reason；合法空頁為成功頁，`zero_card_pages` 計數；soft 404 只該書失敗（`product_not_found`）、不寫入；詳細頁 acquisition 錯誤只請求一次；DB 失敗後以同一 draft 重試（退避 1 秒），commit 不確定時 re-resolve 得到 EXISTING 並計入 `recovered_commit_count`；budget 在任何頁前用盡為 FAILED 且零請求，在第二頁前為 PARTIAL 且剩餘頁 not reached，頁中為 interrupted 且 PARTIAL，詳細頁或列表頁回 `BUDGET_EXHAUSTED` 時乾淨停止；第二次 run 從清單開頭 replay 並推進；identity 查詢拋出的 `psycopg.Error` 使 run FAILED，error 不含 DSN 與密碼；未預期的 `ValueError` 同為 FAILED；identity warning 記為 WARNING 並計數；每次 run 一行 `mode=kingstone`；`SoftBudget` 的剩餘時間與 exhausted 規則；`new-books-only` 下 ISBN 命中 1 本 → 政策跳過、不 persist、不 touch、仍抓詳細頁，全部政策跳過 run 為 SUCCESS，下一次 run 仍會再抓（Source 不存在）；`normal` 下同一命中 → 附加 Source；0 本與 2 本以上在 `new-books-only` 下照常寫入。
- **Phase 6 M5 新增**：`items_listed` 為每個已解析列表頁的卡片數（包含之後失敗的卡）；`details_fetched` 每次要求詳細頁即計（失敗也計）；`http_attempts` 與 `http_failures` 由 fake fetcher 的屬性讀取；跳過的列表頁不計卡片與詳細頁。列表頁的 `KingstoneParseError` 把該頁 HTML 交給 `DiagnosticSink`（kind `list`，code 為分類代碼 `jdc` 等）；詳細頁的 `KingstoneParseError` 交給 sink（kind `detail`，code 為 km_code）；soft 404 與 acquisition 失敗不交給 sink；sink 拋出例外時 run 仍 SUCCESS／PARTIAL，`error` 為 null。
- **來源與狀態**：[test_kingstone_run.py](../tests/test_kingstone_run.py)（41 個測試，Phase 6 M5 新增 6 個）。組裝、CLI 與真 DB 的端到端由 CR-K09、CR-K10 驗證（Phase 5 M2）；真 HTTP（真站）仍未驗證，hard limit 的強制執行屬 Phase 6。

### CR-K09 — 金石堂 CLI（`kingstone.cli`）

- **責任／規格**：[architecture](architecture.md)「入口與組裝」、Kingstone plan v11 §4（清單無效 → exit 2）、§6（不輸出 DB URL）、§7（設定與 exit code）、§9 Phase 5；風險 L3（決定是否發出請求、exit code，以及 DATABASE_URL 是否外洩）；狀態：已有測試（2026-10-25 新增並執行）。離線：fake fetcher、注入的 provider 查詢；資料庫 session 與 schema 檢查以替身取代（`stub_database`），不開連線；DATABASE_URL 是假 DSN（密碼 `hunter2`），不得被連線或輸出。
- **When**：`kingstone.cli.main` 的各種輸入。
- **Then**：provider 停用或未註冊 → 2，不建 fetcher、不發請求；provider 查詢的 `psycopg.Error` → 1，訊息經 redact；清單為空、只有註解、非法 URL、缺檔、超過 400 筆 → 2，不建 fetcher、不查 provider；DATABASE_URL 未設或空白 → 2，不 log 值；非法設定（秒數非數字、soft ≥ hard、寫入政策非法、attempts 為 0）→ 2，不建 fetcher；不支援的 Unicode runtime → 2；所有頁跳過 → 1；致命錯誤 → 1 且 fetcher 仍被 close；建立 fetcher 之後的每條路徑（全頁跳過、致命錯誤、正常 run）都會 close fetcher；預設 fetcher 以設定值與 `budget.remaining` 建立並為 `KingstoneFetcher`；stdout 含 `kingstone.run` 的 INFO 行，不含 DATABASE_URL 或密碼。正常 run 的 exit 0 與寫入由 CR-K10 以真 DB 驗證。
- **Phase 6 M5 新增（terminal artifacts）**：設定載入之後的 terminal 結果都寫 `kingstone/last-run.json`：FAILED（全頁 302，exit 1，`alert_reasons == ["failed"]`，stdout 含 `ALERT reasons=failed last_run=<路徑>`）；SUCCESS 但唯一的頁是合法空頁（exit 0，`zero_card_pages == 1`，alert `zero_card_pages`，`http_attempts == 1`、`http_failures == 0`）；schema 缺欄位（exit 2，`reason` 為 `SCHEMA_PREREQUISITE_MISSING`，`pages_not_reached` 為 null，alert `failed` 與 `schema_prerequisite_missing`）；首次連線 busy（exit 1，`reason` 為 `MAINTENANCE_BUSY`，alert `failed` 與 `maintenance_busy`）；provider 停用（exit 2，alert `failed`）；清單無效（exit 2，寫入 record）。設定無效與缺 DATABASE_URL 不寫任何檔案。產物寫入失敗（`artifacts` 為一個檔案）只記 ERROR，exit code 不變（busy 仍為 1）。
- **來源與狀態**：[test_kingstone_cli.py](../tests/test_kingstone_cli.py)（35 個測試，離線；含 Phase 6 M2 的 preflight 與 busy 兩案，以及 Phase 6 M5 的 artifacts 與 ALERT 行 10 個）。

### CR-K10 — 金石堂真 DB 整合（ingestion）

- **責任／規格**：Kingstone plan v11 §5（交易、commit 不確定、replay）、§6、§9 Phase 5 Acceptance（清單→列表→詳細頁→DB 全流程；shared core／DB；Atomicity；Uncertain commit／replay；Books／Bestseller）；風險 L3；狀態：已有測試（2026-10-25 新增並執行）。
- **Given**：真 PostgreSQL（post-011 EF schema，`db_url`，每案清空 crawler 表）。KINGSTONE 只在需要的測試中由 fixture UPDATE 為啟用，結束後還原為停用（`test_provider_enabled_reads_the_registry_row` 依賴停用狀態）。fake fetcher 以真實 detail fixture 與合成列表頁回應；真 parser、真 `SessionCatalogStore`、真 `DatabaseSession`；fake sleep；可控 clock。不連網。
- **When／Then**：
  - 全流程：8 張卡（7 本真 detail、1 個 soft 404）→ 寫入 7 本 Book 與 7 筆 `book_sources.source_code='KINGSTONE'`，`external_id` 為 km_code，`source_url` 為 canonical 詳細頁 URL；identifiers、contributors（含譯者角色與順序）、subjects 與 parser 結果相同；簡體書 `language='zh-CN'`；soft 404 不寫入；report 計數 items 8、imported 7、failed 1（`product_not_found`），PARTIAL_SUCCESS，CLI 回傳 0。
  - replay：同一 DB 第二次 run → Book 與 Source 數不變、全部 EXISTING、詳細頁請求 0；`last_seen_at` 前進到第二次的時間；時鐘倒退時不後退。（soft 404 不建立 Source，所以含 soft 404 的清單 replay 時仍會再請求它一次；本測試的清單不含 soft 404。）
  - 寫入政策（new-books-only）：ISBN 命中 1 本 → 政策跳過：不建 KINGSTONE Source、Books 書的欄位與 identifiers 不變、詳細頁仍抓一次；0 命中的 6 本照常建立；命中 2 本 → `AMBIGUOUS_CREATED`，建立新 Book，兩本舊 Books 不變。normal 下命中 1 本 → `ISBN_ATTACHED`，只補 NULL，既有值保留，ISBN 不重複寫入。
  - Atomicity：identifiers 寫入每次都失敗 → 該卡 `database_error`、attempts 3、退避 1 秒與 2 秒；五張表沒有屬於該書的孤兒列，也沒有該書標題的 Book；寫入到 subjects 後、commit 前失敗一次 → 重試成功，只寫入一本（沒有殘留的第四本）。
  - Uncertain commit：commit 成功後以 `pg_terminate_backend` 切斷並丟出 `OperationalError` → 後續 re-resolve 得 EXISTING（`recovered_commit_count == 1`），該 ISBN 只有 1 筆 Source，詳細頁只抓一次。
  - Bestseller protection：先以 Books run 寫入 100 名榜單；金石堂 SUCCESS、PARTIAL_SUCCESS、FAILED（全頁 302）三種結果後 `bestsellers` 完全不變。
  - CLI（真 DB）：registry 列停用 → 2，不建 fetcher；完整 run → 0、寫入 7 本、fetcher 被 close、輸出不含 DATABASE_URL；全頁 503 → 1 且 fetcher 被 close。
  - Phase 6 M5（真 DB）：完整 run 寫入 `last-run.json`：`imported == 7`、`failed == 1`（soft 404）、`items_listed == items_seen == details_fetched == imported + failed`、`http_attempts == 送出的請求數`、`alert_reasons == []`、history 1 份；replay 之後 `existing_source == 7`、`details_fetched == 1`（只有 soft 404 再抓一次）、`alert_reasons == []`、history 2 份，且 stdout 沒有 ALERT 行。
- **必要 DB 測試不得 skip**：Phase 6 M5 之後的 Kingstone DB 測試共 20 個（M5 新增 1 個），全部執行，`-rs` 沒有 skip。注意：既有 [conftest](../tests/conftest.py) 的 `ef_schema_sql` 在找不到 dotnet SDK 時會 `pytest.skip`（Books 既有行為，未改）；環境缺 dotnet 時這組測試會被 skip，必須在執行紀錄中註明。
- **跨 provider 隔離**：同一 Book 的 BOOKS_COM_TW 與 KINGSTONE Source 互不影響，已由 [test_persistence_integration.py](../tests/test_persistence_integration.py) 的 provider isolation 測試覆蓋（`test_provider_isolation_*`），這裡不重複。
- **來源與狀態**：[test_kingstone_db_integration.py](../tests/test_kingstone_db_integration.py)（20 個測試，其中 bestseller protection 為參數化 3 案）。

### CR-K11 — 金石堂 HTTP-only image（Phase 6 M1）

- **責任／規格**：[architecture](architecture.md)「Image」與 Kingstone plan v12 §7、§8「Image」「清單檔」；風險 L2（建置內容與 CI gate；不改 runtime 行為）；狀態：已有測試（2026-10-25 新增並執行）。靜態檢查，不執行 docker、不連網。
- **Given**：`crawler/Dockerfile`、`crawler/.dockerignore`、`crawler/requirements-runtime.txt`、`.github/workflows/ci.yml`。
- **When**：`tests/test_kingstone_image.py` 解析 Dockerfile 的 stage、`.dockerignore` 白名單與 CI docker job。
- **Then**：存在名為 `kingstone` 的 target，且最後一階（`docker build` 的預設）仍是博客來；`kingstone` target 不含 playwright、chromium，也不安裝 `requirements.txt`（開發依賴，含 playwright）；`requirements-runtime.txt` 不含 playwright；`kingstone` target 複製 `catalog_core/`、`kingstone/`、`kingstone-pages.txt`，不含 `books_crawler`；UID 10001 與 `ENTRYPOINT ["python", "-m"]`、`CMD ["kingstone"]`；博客來預設 target 的 COPY、USER、CMD 不變；`.dockerignore` 允許 `kingstone/` 與 `kingstone-pages.txt`；CI 有 `docker build --target kingstone` 與 `--network none` 離線 smoke，smoke 斷言 `import playwright` 因 `ModuleNotFoundError` 失敗。
- **來源與狀態**：[test_kingstone_image.py](../tests/test_kingstone_image.py)（7 個測試）。**已知驗證缺口**：本次未在本機 build image（`pip install` 需要網路）；build 與離線 smoke 的實際結果需由 CI docker job 驗證；CD 尚未推送此 image（backlog CB-07）。

### CR-K12 — 金石堂 schema preflight（`SCHEMA_PREREQUISITE_MISSING`，plan v12 §8 第 3 點）

- **責任／規格**：[architecture](architecture.md)「入口與組裝」步驟 (7)、(8) 與 `catalog_core/persistence` 的 `missing_schema_prerequisites`；Kingstone plan v12 §8 第 3 點（唯讀檢查必要欄位與 `source_providers`；失敗為 `SCHEMA_PREREQUISITE_MISSING`，零 HTTP、零 mutation）；風險 L3（決定是否開始寫入）；狀態：已有測試（2026-10-25 新增並執行）。
- **Given**：真 PostgreSQL（post-011 schema）；破壞 schema 的變更只在 transaction 內執行（以 `rollback` 還原），或在 CLI 測試中以 commit 完成並於 `finally` 還原。
- **When／Then**：
  - 正常 DB → 清單為空。
  - 逐項破壞：`book_sources.last_seen_at`、`external_id`、`source_code` 欄位改名；加回 `source_type`；刪除 KINGSTONE 列；`ck_book_identifiers_identifier_type` 改為允許 `ISBN_10` → 每一項都在清單中回報，rollback 後恢復為空清單。
  - CLI：schema 缺欄位 → exit 2，log `SCHEMA_PREREQUISITE_MISSING: book_sources.last_seen_at`，fetcher 未建立（`factory_calls == []`），books 計數為 0。
  - CLI：首次連線 busy → exit 1，log `maintenance busy`，fetcher 未建立，計數為 0。Phase 6 M5 起兩者都寫 `last-run.json`（`reason` 為 `SCHEMA_PREREQUISITE_MISSING`／`MAINTENANCE_BUSY`，alert 分別為 `failed` 與 `schema_prerequisite_missing`／`maintenance_busy`）。
  - 單元：CLI 的 preflight 在 fetcher 建立之前執行，缺項時 exit 2 且不建 fetcher；busy 時 exit 1 且不建 fetcher（[test_kingstone_cli.py](../tests/test_kingstone_cli.py)，session 與 schema 檢查以替身取代）。
- **已知驗證缺口**：`OTHER` 的 identifier type 仍允許（011 保留）；preflight 不檢查 DB 角色的實際 grant（屬部署範圍）。博客來入口未加 preflight（本次只為金石堂，見 [backlog](backlog.md) CB-07）。
- **來源與狀態**：[test_migration_lock_integration.py](../tests/test_migration_lock_integration.py)（真 DB：正常通過 1 個、逐項破壞 6 個參數化、CLI exit 2 與 exit 1 各 1 個，共 9 個；CLI 兩案另檢查 `last-run.json` 的 reason 與 alert，Phase 6 M5）、[test_kingstone_cli.py](../tests/test_kingstone_cli.py)（替身 session，preflight 與 busy 各 1 個單元案例）。

### CR-K13 — 金石堂 run 產物：last-run、bounded history 與 streak（Phase 6 M5）

- **責任／規格**：[architecture](architecture.md)「報告、alert 與診斷」、計畫 v12 §8（terminal JSON 欄位、bounded history、`pages_not_reached` streak 與必測項目）；風險 L2（寫入 artifacts，不改 exit code 與 Catalog）；狀態：已有測試（2026-10-25 新增並執行）。離線：臨時資料夾、固定時間、真實 ledger 產生的 report。
- **Given**：由真實 ledger 建立的 report（完成、跳過、interrupted、not reached 的頁；Existing、Imported、Failed 卡；HTTP 計數）；pre-run record；含 DSN 與密碼的訊息；history 檔（上限測試用 25 次 publish；壞檔為非 JSON、非物件、缺欄位、無時區、count 型別錯誤）；連續的 `pages_not_reached` 序列；`os.replace` 或目錄建立失敗。
- **When**：`KingstoneArtifacts.publish`、`read_history`、`atomic_write_json`，以及 `record_from_report`、`record_pre_run`。
- **Then**：last-run 含 v12 §8 的欄位（run、provider、status、exit、pages listed／completed／skipped（含原因）／interrupted／not reached、items listed、details fetched、existing、imported、isbn attached、ambiguous、policy skipped、recovered commit、failed items、HTTP attempts／failures、write policy、zero progress reason、alert reasons、started／finished ISO 8601）；所有字串經 redact，檔案中不出現密碼與 DSN；原子寫入失敗時舊檔保留、無殘留 temp 檔；寫入過程 fsync；history 最多 20 份，超過刪最舊，依 `finished_at` 排序（不依檔名）；壞檔略過並各記一行 WARNING，缺資料夾為空歷史；streak：第 1、2 次 `pages_not_reached > 0` 不 alert，第 3 次 alert，之後持續 alert；中間一次為 0 即重設；本次先於寫入計算，本次不被算兩次（history 寫入後正好多一份）；壞檔不計入 streak；pre-run（null）不計入也不重設；寫入失敗（`kingstone` 路徑是檔案）記 ERROR 一行並仍回傳 alert reasons。
- **來源與狀態**：[test_kingstone_artifacts.py](../tests/test_kingstone_artifacts.py)（17 個測試）。已知驗證缺口：真實磁碟的斷電一致性未驗證（只驗證 fsync 呼叫與失敗路徑）；壞檔在視窗中間時的誤報限制（見 [backlog](backlog.md) CB-07 Phase 6 M5 待辦）未有測試，只以文件說明。

### CR-K14 — 金石堂 alert reasons（Phase 6 M5）

- **責任／規格**：[architecture](architecture.md)「報告、alert 與診斷」與計畫 v12 §8 的觸發條件；風險 L2（決定告警）；狀態：已有測試（2026-10-25 新增並執行）。純函式，無 I/O。
- **Given**：status（SUCCESS、PARTIAL_SUCCESS、FAILED）、pre-run reason（schema、busy、其他、無）、完成頁數與 0 張卡頁數、streak 結果；歷史摘要序列（1、2、3 個項目，含 0、null、缺項）。
- **When**：`alerts.alert_reasons`、`alerts.pages_not_reached_streak`。
- **Then**：全部 Existing 的正常 run 不觸發（SUCCESS、無 reason、有完成頁且卡片數 > 0 → 空清單）；PARTIAL 本身不觸發；FAILED → `failed`；schema → `schema_prerequisite_missing`（並有 `failed`）；busy → `maintenance_busy`（並有 `failed`）；其他 reason 不觸發這兩項；zero-card 只在「完成頁數 > 0 且全部 0 張卡」時觸發（3 對 2 不觸發，0 對 0 不觸發）；streak 旗標直接映射；reasons 的順序固定；streak 需要 3 項且都 > 0，當前為 0 或 null 不成立，視窗中有 0、null 或不足 3 項不成立；持續 > 0 仍成立。**`challenge` 不在任何路徑中產生**（未實作，見 backlog）。
- **來源與狀態**：[test_kingstone_alerts.py](../tests/test_kingstone_alerts.py)（18 個測試）。已知驗證缺口：challenge 分類未實作，無 fixture；runner 端 orphan alert 屬 Phase 6 M4，未在本模組測試。

### CR-K15 — 金石堂診斷檔（Phase 6 M5）

- **責任／規格**：[architecture](architecture.md)「報告、alert 與診斷」與計畫 v12 §8（診斷檔、`KINGSTONE_DIAGNOSTIC_MAX_BYTES`）、計畫 §7 設定表；風險 L2（寫入本機檔案，不影響 run）；狀態：已有測試（2026-10-25 新增並執行）。離線：臨時資料夾、固定時間、run 以 fake fetcher 與記憶體 store 執行。
- **Given**：中文 HTML 超過上限、上限小於註記長度、21 次以上的儲存、同一微秒的連續儲存、不安全的 code（`../../x`）、寫入目標是一個檔案；列表頁與詳細頁的 `KingstoneParseError`、soft 404、acquisition 失敗；拋出 `OSError` 或 `RuntimeError` 的 sink。
- **When**：`DiagnosticWriter.save_html`；`run_pages` 搭配 sink。
- **Then**：檔名 `<UTC 微秒時間>-<kind>-<code>.html`，code 只保留英數字，空結果為 `unknown`；未超過上限的內容原樣保存；超過上限時在 UTF-8 字元邊界截斷，檔尾註記計入上限（檔案 ≤ 上限，且保留完整字元）；上限小於註記時只保留完整字元；保留最新 20 份（依檔名，即時間序）；同一微秒的儲存取下一個微秒，名稱不重複且保持時間序；寫檔失敗回傳 None、記 WARNING，不拋出；上限必須為正整數；run 只在列表頁與詳細頁的 `KingstoneParseError` 時呼叫 sink（list 的 code 為分類代碼、detail 的 code 為 km_code），soft 404 與 acquisition 失敗不呼叫；sink 拋出例外時 run 不受影響（`error` 為 null，正常卡片照常寫入）。CLI 預設的 sink 寫入 `artifacts/kingstone/diagnostics/`（CR-K09 的 artifacts 路徑由 `KINGSTONE_ARTIFACTS_DIR` 決定）。
- **來源與狀態**：[test_kingstone_diagnostics.py](../tests/test_kingstone_diagnostics.py)（10 個測試）與 [test_kingstone_run.py](../tests/test_kingstone_run.py) 的診斷案例（6 個，見 CR-K08）。已知驗證缺口：真站 HTML 的診斷檔大小只以合成內容驗證；磁碟寫滿等情況未驗證。

### 連線中斷與重連（crawler.md §13.1、§6.1，#119）

- **Given**：DB integration 的 PostgreSQL；fetcher 與 parser 是 fake，不連線博客來。會話斷線以 `pg_terminate_backend(<crawler backend pid>)` 從另一個 admin 連線執行，在操作前的 hook 中觸發。
- **When**：touch 前斷線；寫入前斷線；commit 成功後 client 沒有看到結果（commit-then-drop）；三次嘗試都遇到斷線；另有 first_book 的三次斷線，以及讀取既有 Source 時斷線。
- **Then**：touch 重連後成功、`last_seen_at` 前進、第 2 次嘗試成功；寫入重連後 Source 只插入一次；commit-then-drop 不重複插入，回報 EXISTING，只有一筆 source；三次斷線後該列為 FAILED `database_error`（attempts 3），daily 為 ERROR_SKIP、first_book 為 FAILED exit 1；讀取既有 Source 斷線則 run FAILED。另有 `DatabaseSession` 的單元測試（替換 closed／broken 連線、關閉錯誤被忽略、重連失敗可再試）。
- **來源與狀態**：[test_reconnect_integration.py](../tests/test_reconnect_integration.py)、[test_session.py](../tests/test_session.py)、[test_first_book.py](../tests/test_first_book.py)（重試不重抓 detail，lookup 在寫入重試前重新解析）。
