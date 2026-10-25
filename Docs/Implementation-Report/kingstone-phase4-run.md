# 實作報告：金石堂 crawler Phase 4 — run 設定、帳本與逐頁 run

> 實作紀錄，不是規格。規格以 `crawler/docs/*`（現行 authority）與 [v12 計畫](../plans/kingstone-category-crawler.md) §7、§9 為準；待辦見 `crawler/docs/backlog.md` CB-07「Phase 4 留下的待辦」。

## 變更檔案

| 模組 | 分支／commit | 檔案 | 內容 |
|---|---|---|---|
| P4 M1 run 設定與帳本（PR #139） | `kingstone-p4-m1-config-ledger` `4b8f73f`；merge #139 `fe58e25`（main，2026-10-25） | A `crawler/kingstone/config.py`、`crawler/kingstone/ledger.py`、`crawler/tests/test_kingstone_config.py`、`crawler/tests/test_kingstone_ledger.py`；M `crawler/kingstone/acquisition.py`（`KingstoneFetcher` 新增 timeout、max_attempts、max_response_bytes；`CurlTransport` 新增 max_response_bytes）、`crawler/tests/test_kingstone_acquisition.py`（+10 測試，共 106）；M `crawler/docs/{architecture,backlog,test-suite,update-history}.md` | `load_config`、`KingstoneConfigError`；`KingstoneLedger`、`decide_status`、`KingstoneReport`、`format_report`、`RunStatus`；CR-K05 補充、新增 CR-K06、CR-K07 |
| P4 M2 逐頁 run（PR #140） | `kingstone-p4-m2-run` `c927277`、`17cdb26`；merge #140 `fd9a201`（main，2026-10-25） | A `crawler/kingstone/run.py`、`crawler/catalog_core/redact.py`、`crawler/tests/test_kingstone_run.py`；M `crawler/books_crawler/redact.py`（只重新匯出 `catalog_core.redact`，規則不變）、`crawler/kingstone/page_list.py`（讀檔錯誤經 redact）、`crawler/tests/test_kingstone_page_list.py`（+1 測試）；M `crawler/docs/{architecture,backlog,test-suite,update-history,workflow-diagram}.md` | `SoftBudget`、`KingstoneFetcherPort`、`KingstoneRunDependencies`、`run_pages`；共用 redact 模組；新增 CR-K08 |

## 實作思路

- **三層分工**：`config.py` 只讀傳入的 mapping，不讀環境與檔案；`ledger.py` 只記帳與計算 terminal status，不做 I/O；`run.py` 是唯一把 acquisition、`catalog_core.service.resolve_item` 與帳本接起來的地方。`run_pages` 永不 raise，fatal 錯誤進 `report.error`。
- **terminal status 單一判定處**：`decide_status(...)` 是唯一寫下 terminal 規則的函式，`KingstoneLedger.report` 只傳入計數。規則與計畫 §7 的 terminal 表一致；計畫的 FAILED 條件另拆出四種 `zero_progress_reason`（清單為空、所有頁被跳過、budget 在任何頁完成前用盡、其他）。
- **Useful progress 與 zero-card 頁**：至少一頁 completed 即為 useful progress；成功但 0 張卡的頁計為 `zero_card_pages`，不是跳過頁，status 仍為 SUCCESS，供 Phase 6 alert 使用。
- **Budget 守門**：`SoftBudget(seconds, monotonic)` 記起點，`remaining()` 與 `exhausted()`。run 在每個清單頁與每張卡之前檢查；fetcher 另在每次請求前檢查等待時間是否超過剩餘 budget。兩道守門讀同一個時鐘。被停下的頁與卡沒有寫入，下一次 run replay 時再處理。停止點與順序見 architecture「Run（逐頁流程）」。
- **詳細頁不在 service 層重試（偏離計畫 §7 第 3 點的字面描述）**：計畫寫「詳細頁 fetch／parse／write 共用最多 3 次嘗試」。實作改為：acquisition 在 HTTP 層已重試最多 3 次；service 的 attempts（預設 3）只用於資料庫失敗，且保留已解析的 draft，不為了 DB 重試而重抓詳細頁。理由（commit `c927277` 訊息）：若 service 再重試，同一本書最多會發出 9 次請求。非 budget 的 acquisition 錯誤直接記為該卡失敗（`retryable=False`）。
- **`external_id` 防禦**：解析出的 `BookDraft.external_id` 必須等於卡片的 km_code，不符記為該卡的 `parse_error`，不中止 run。計畫未明列此項，屬實作補強。
- **寫入政策不在 Phase 4**：`KingstoneRunDependencies.write_policy` 無預設值，由 caller 決定；Phase 4 的 config 沒有 `KINGSTONE_WRITE_POLICY`（PR #139 body 明列留給 Phase 5）。
- **Redact 共用**：`catalog_core/redact.py` 由 Books 的規則複製而來，Kingstone run 的 fatal、skipped、failed item 訊息經此處理後才進帳本或 log。PR #140 的第一個 commit 先複製，第二個 commit `17cdb26` 讓 `books_crawler/redact.py` 改為重新匯出，使兩邊共用同一組規則；Books 行為與測試不變。

## 執行紀錄（Log）

- `4b8f73f` 於 2026-10-25 10:41 提交（M1 本體）；M1 分支在 `d959db4` 合併了 `kingstone-p3-acquisition`。PR #139 的 body 寫明「包含 #138（尚未合併）」，並要求「請在 #138 之後合併」。
- `c927277`（10:54）與 `17cdb26`（10:56）為 M2。PR #140 的 body 寫明「包含 #139（尚未合併）；#138 已合併進 main」。
- PR #139 於 11:15:31Z 合併（`fe58e25`），PR #140 於 11:16:34Z 合併（`fd9a201`）；兩者皆為 `MERGED`。
- M1 的 acquisition 變更是為了讓 `KingstoneFetcher` 接受設定值：新參數的預設值與 Phase 3 的常數相同，既有測試未改。
- M2 的 `17cdb26` 為重構，不改變 Books 行為；commit 訊息指出它同時消除了 backlog 中「兩份 redact 規則」的待辦。
- 未讀取 `.env`，未連網（真站），未 push（本報告的 commit 也未 push）。

## 驗證結果

- PR #139 body 的 Evidence：新測試 `test_kingstone_config.py` 67、`test_kingstone_ledger.py` 40、`test_kingstone_acquisition.py` +10（共 106）；完整 pytest `20268 passed`，0 skipped；ruff check／format、`unicode_tables.py --check` 通過。
- PR #140 body 的 Evidence：`test_kingstone_run.py` 31 個（真 detail fixture、合成列表頁、fake fetcher、記憶體 store、fake clock、記錄型 sleep）；涵蓋全流程、replay（第二次 0 個詳細頁請求）、302 與 parse error 跳頁、全跳過 FAILED、DB 重試、uncertain commit → recovered_commit、budget 在首頁前／頁間／頁中／fetcher 回報四種停止點、store 例外的 redact。完整 pytest `20300 passed`，0 skipped；ruff、`unicode_tables.py --check` 通過。
- 變異檢查（PR #140 body）：拿掉卡片間的 budget 守門後，頁中停止測試失敗。
- 後續文件記錄的測試數（已被後續 phase 增加）：CR-K06 為 84、CR-K07 為 51（含 parse_error_200_count 的 5 案）、CR-K08 為 43（Phase 6 M5 新增 6 個）。
- 未執行：真站抓取、真 DB 端到端（由 Phase 5 的 CR-K09、CR-K10 補上）、部署。全部測試離線。
- 本報告 commit 為 docs-only，未執行測試。

## 未解決事項

Phase 4 留下的待辦已記入 `crawler/docs/backlog.md` CB-07「Phase 4 留下的待辦」。後續 phase 的處理狀態如下：

- 真站上的 budget 行為未驗證（禁止連網）。Phase 4 只有 fake 組裝的測試；真 fetcher 與 budget 的接線於 Phase 5 M2（`kingstone/cli.py`）完成，真站行為仍未驗證。
- `zero_card_pages` 計數已有，alert 條件於 Phase 6 M5 實作（`zero_card_pages` reason）。
- `KINGSTONE_DIAGNOSTIC_MAX_BYTES` 於 Phase 6 M5 加入 config；`CRAWLER_ALERT_COMMAND` 不實作（使用者決定 alert 只寫 log）。
- `KINGSTONE_WRITE_POLICY` 於 Phase 5 M1 加入（`bbce58d`），ledger 新增 `policy_skipped`；Phase 4 報告不含此欄位。
- 後續變更（Phase 4 的設定與計數已改動，本報告不重述細節）：
  - Phase 6 M1（`bd70100`）：`KINGSTONE_SOFT_RUN_BUDGET_SECONDS` 由 3300 改為 7200、`CRAWLER_RUN_HARD_LIMIT_SECONDS` 由 3600 改為 9000；清單上限由 200 改為 400。
  - Phase 6 M5（`54e618b`、`9e8857e`）：新增 `items_listed`、`details_fetched`、`http_attempts`、`http_failures`、`parse_error_200_count`，以及 `unclassified_200` alert 與 terminal 產物。
- `challenge` 分類未實作：目前 200 照常回傳，由 parser fail closed，落在 `unclassified_200`（待 challenge fixture）。
- 真站 end-to-end（1 頁 canary）屬 Phase 7 acceptance，尚未執行。
- 未記錄：#139、#140 的 review 過程與 TDD 紀錄（見下節）。

## Code Review 與修正

- GitHub 上 #139 與 #140 的 review comments（`pulls/{n}/comments`）與 issue comments（`issues/{n}/comments`）均為空，未記錄正式 review 意見。
- 兩個 PR body 皆有 `Merge Danger` 區段（#139：Door two-way、Blast Radius none；#140：Door two-way、Blast Radius 博客來 log redaction）。
- 實作過程的決定均記於 commit 訊息與 architecture，未見獨立的 review 修正 commit：
  - 詳細頁不在 service 層重試（見上「實作思路」，偏離計畫 §7 第 3 點的字面描述）。
  - `external_id` 防禦（計畫未列）。
  - Redact 規則由複製改為共用（`17cdb26`）。
- 兩軸 review（Standards／Spec）的結果：未記錄。
