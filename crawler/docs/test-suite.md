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
- 現有測試或擴充入口：[test_page_list.py](../tests/test_page_list.py)、[test_cli.py](../tests/test_cli.py)。

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

### 連線中斷與重連（crawler.md §13.1、§6.1，#119）

- **Given**：DB integration 的 PostgreSQL；fetcher 與 parser 是 fake，不連線博客來。會話斷線以 `pg_terminate_backend(<crawler backend pid>)` 從另一個 admin 連線執行，在操作前的 hook 中觸發。
- **When**：touch 前斷線；寫入前斷線；commit 成功後 client 沒有看到結果（commit-then-drop）；三次嘗試都遇到斷線；另有 first_book 的三次斷線，以及讀取既有 Source 時斷線。
- **Then**：touch 重連後成功、`last_seen_at` 前進、第 2 次嘗試成功；寫入重連後 Source 只插入一次；commit-then-drop 不重複插入，回報 EXISTING，只有一筆 source；三次斷線後該列為 FAILED `database_error`（attempts 3），daily 為 ERROR_SKIP、first_book 為 FAILED exit 1；讀取既有 Source 斷線則 run FAILED。另有 `DatabaseSession` 的單元測試（替換 closed／broken 連線、關閉錯誤被忽略、重連失敗可再試）。
- **來源與狀態**：[test_reconnect_integration.py](../tests/test_reconnect_integration.py)、[test_session.py](../tests/test_session.py)、[test_first_book.py](../tests/test_first_book.py)（重試不重抓 detail，lookup 在寫入重試前重新解析）。
