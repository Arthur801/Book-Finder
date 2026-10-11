# 重構實作報告：Crawler Run ledger

- 來源：2026-10-11 架構檢視（improve-codebase-architecture）的候選 1「把 run 的結算集中成一個 Run ledger module」
- Issue：無（純重構，使用者決定不開 issue）
- Branch：直接在 `main`（使用者決定）
- 實作：主 session 以 TDD 直接實作
- 日期：2026-10-11

## 背景

連續錯誤計數、中止判斷、run 狀態與各項計數原本分散在 `run.py` 的四個地方：

- `_resolve_row` 一邊回傳結果，一邊修改 `report` 的計數。
- `run_once` 的迴圈裡 inline 寫 streak 與中止，並以 `ConsecutiveErrorLimitError` 例外跳出。
- `run_first_book` 複製 `run_once` 的骨架，再用 `FirstBookImportError` 讓結果變成 FAILED。
- `RunReport` 同時放計數、streak、狀態與錯誤訊息。

CRAWL-05 的規則這一輪改過，每次都要同時改這四處；規則本身也只能透過真實 PostgreSQL 的整合測試驗證。

## 設計決定（使用者逐題確認）

| # | 決定 |
|---|---|
| Q1 | 只做 Run ledger；候選 4（詳細頁回傳分類好的結果）另開一輪 |
| Q2 | 新檔 `crawler/books_crawler/ledger.py`，類別 `RunLedger`，不 import `db`／`fetcher`／`parsers`；屬實作概念，不寫入 `CONTEXT.md` |
| Q3 | ledger 負責計數、streak、中止、狀態，以及「已上榜 Book → rank」對照表與 snapshot rows；對外提供唯讀的 `ranked` |
| Q4 | first-book 只用上限參數表達：每日 run 20、first-book 0；刪除 `FirstBookImportError` |
| Q5 | 中止用 `aborted` 屬性通知；刪除 `ConsecutiveErrorLimitError` |
| Q6 | 保留 `RunReport` 作為結果紀錄；`format_report` 欄位、log 格式、`exit_code`、`aborted_at_rank` 不變 |
| Q7 | outcome 為 `ResolvedRow(rank, source_ref, resolution)`（`EXISTING_SOURCE`／`ISBN_ATTACHED`／`NEW_BOOK`）或 `SkippedRow` |
| Q8 | ledger 寫跳過列的 log；ISBN 附加的 log 留在 `_resolve_row`（中止的 log 見 D2） |
| Q9 | 每次 run 一開始就建立 ledger；status 只在 `ledger.report(...)` 決定 |
| Q10 | `ResolvedRow` 帶 rank，ledger 只有 `record(outcome)` 一個方法 |
| Q11 | 重複 Book 由 resolver 依 `ranked` 判斷並回傳 `SkippedRow`；ledger 收到已上榜的 Book 時拋出程式錯誤 |
| Q12 | 測試 replace, don't layer：新增 ledger 測試，DB 測試只留需要真實資料庫的部分 |
| Q13 | 更新 `test-plan.md` 的 CRAWL-05 與 `crawler.md` §6／§11 |
| Q14 | 主 session 以 TDD 實作 |
| Q15 | 驗證後直接 commit 在 `main`；報告為本檔 |
| D1 | first-book 一般失敗時記 `aborted_at_rank=1`、`consecutive_error_count=1`；`crawler.md` §12 的定義改為「超過上限而中止時為該排名」 |
| D2 | 每次 FAILED（含中止）只記一行 ERROR：每日 run 為 `run failed: <error>`，first-book 為 `first-book import failed: <error>`；ledger 不另外寫中止的 log |
| D3 | 補回一個精簡的 DB 測試：多本限制級頁面每本只請求一次 |

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/books_crawler/ledger.py` | 新增 | `RunLedger`、`RunReport`（自 `run.py` 搬入，欄位不變）、`MAX_CONSECUTIVE_ERRORS`、`EXIT_SUCCESS`／`EXIT_FAILED` |
| `crawler/books_crawler/models.py` | 修改 | 新增 `Resolution`（一般 `Enum`，只在程式內使用）與 `ResolvedRow` |
| `crawler/books_crawler/run.py` | 修改 | `_resolve_row` 改為回傳 `ResolvedRow`／`SkippedRow`，不再接收 `report`；`run_once`、`run_first_book` 改為「建立 ledger → 記錄每一列 → 結算」；刪除 `ConsecutiveErrorLimitError`、`FirstBookImportError`、`RunReport`、`MAX_CONSECUTIVE_ERRORS`、exit code 常數；失敗時統一記一行 ERROR |
| `crawler/tests/test_ledger.py` | 新增 | 24 個不需資料庫的測試 |
| `crawler/tests/test_db_integration.py` | 修改 | 刪除只驗計數規則的 9 個案例；中止案例補上 ERROR log 斷言；新增多本限制級只請求一次的測試 |
| `crawler/tests/test_first_book.py` | 修改 | 錯誤訊息改為統一格式；補上 `aborted_at_rank`／ERROR log 斷言 |
| `crawler/tests/test_run_unit.py` | 修改 | `RunReport` 改從 `books_crawler.ledger` import |
| `Docs/modules/crawler.md` | 修改 | §6、§11 註明實作位置、中止訊息格式與 ERROR log 規則；§12 `aborted_at_rank` 定義改為依上限 |
| `Docs/testing/test-plan.md` | 修改 | CRAWL-05 改寫為「規則由 ledger 測試涵蓋、資料保護由 DB 測試涵蓋」 |

## 實作思路

- **interface**：`RunLedger(max_consecutive_errors=20)`、唯讀的 `ranked`、`aborted`、`snapshot`、`restricted_ranks`、`record(outcome)`、`report(run_id, started_at, finished_at, ranking_count, error)`。計數、streak、中止、snapshot、狀態都在 implementation 裡。
- **first-book**：上限 0 時，唯一一列一般失敗就超過上限 → FAILED；限制級重設計數、完成後有跳過 → PARTIAL_SUCCESS；成功 → SUCCESS。和舊行為的狀態與 exit code 一致，不需要另外的模式。
- **status 只在一處決定**：`report()` 收到外部錯誤（排行榜、DB 交易、瀏覽器）或已中止 → FAILED；有跳過 → PARTIAL_SUCCESS；其餘 SUCCESS。
- **防呆**：rank 未遞增、中止後再記錄、收到已上榜的 Book，ledger 都拋出 `ValueError`（程式錯誤，由 run 的通用例外處理記為 FAILED）。
- **遮罩**：ledger 直接記錄 outcome 裡的錯誤訊息，前提是 caller 已遮罩（`run._failure` 會做），docstring 已寫明。
- **對外差異**（使用者已核准）：中止與 first-book 失敗的 `error=` 改為 `run aborted at rank <rank> after <n> consecutive error(s) (limit <limit>): <error_type>: <error_message>`；first-book 一般失敗的 `aborted_at_rank`／`consecutive_error_count` 由 `none`／`0` 變為 `1`／`1`；每日 run 中止時的 ERROR 行仍以 `run failed:` 開頭。

## 執行紀錄（Log）

1. 架構檢視：依 git 熱點派 Explore sub-agent 走 crawler 與 Web 的 Bestseller，產出 5 個候選（HTML 報告在 OS 暫存目錄，未進 repo）。使用者選擇候選 1。
2. 兩輪 grilling（Q1～Q15），使用者全部採用建議。
3. 先寫 `test_ledger.py`（紅：`ModuleNotFoundError`），再實作 `ledger.py` 與 `models.py` 的新型別 → 25 passed。
4. `run.py` 改用 ledger；`test_first_book.py` 兩個錯誤訊息斷言依約定更新 → 全套 288 passed。
5. 依 Q12 刪除 9 個只驗計數規則的 DB 案例 → 279 passed。
6. 更新 `test-plan.md`、`crawler.md`。
7. 雙軸 code review（見下節），使用者決定 D1～D3；修正後重跑。

## 驗證結果

- `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`：**279 passed**，沒有 skip（DB 測試使用 Testcontainers 的 disposable PostgreSQL，不連線博客來）。
- `test_ledger.py` 24 個測試約 0.1 秒完成。
- `git diff --check` 通過；import 順序與引號檢查只剩 HEAD 原有的兩處（`fakes.py` 一處單引號、`test_playwright_fetcher.py:588` 函式內 import）。

| 設計要求 | 結果 | 對應測試 |
|---|---|---|
| 20 本繼續、第 21 本中止；第 21 本在 rank 100 | ✅ | `test_consecutive_error_limit` |
| 成功、既有來源、ISBN 附加、限制級都重設計數 | ✅ | `test_any_non_error_row_resets_the_streak` |
| 各種一般錯誤都計入 | ✅ | `test_every_general_error_type_counts_toward_the_streak` |
| 累計錯誤無上限、保留缺號 | ✅ | `test_cumulative_errors_have_no_limit` |
| 限制級不算錯誤 | ✅ | `test_restricted_rows_are_skipped_but_are_not_errors` |
| 上限 0（first-book）的三種結果 | ✅ | `test_limit_zero_is_the_single_book_policy`；`test_first_book.py` |
| 外部錯誤 → FAILED | ✅ | `test_external_error_fails_the_run_even_without_rows`、`test_external_error_after_rows_keeps_the_counters` |
| `ranked` 唯讀；重複 Book、亂序、中止後記錄都拋錯 | ✅ | `test_ranked_maps_each_book_to_its_rank_and_is_read_only` 等 3 個 |
| 跳過列的 log 等級；ledger 不寫 ERROR | ✅ | `test_skips_are_logged_and_the_abort_is_left_to_the_caller` |
| 中止時舊 Bestseller／`last_seen_at` 不變、之後不再請求、已 commit 新書保留、單一 `run failed:` ERROR | ✅ | `test_abort_keeps_previous_data_and_scattered_errors_still_replace`（rank 21、rank 100） |
| 交錯 50 本錯誤仍替換 | ✅ | 同上（交錯參數組） |
| 重試後成功只計一次結果 | ✅ | `test_eventual_success_after_retries_resets_twenty_errors` |
| 多本限制級每本只請求一次、`attempts=1` | ✅ | `test_each_restricted_page_is_requested_once_and_leaves_a_gap` |
| 真實限制級 fixture 的完整 run | ✅ | `test_real_restricted_member_gate_is_skipped_once_and_leaves_a_gap` |
| run log 欄位與格式不變 | ✅ | `test_run_unit.py` 的 `test_format_report_*`、`test_run_log_has_the_required_fields_and_no_database_url` |

## Code Review 與修正

雙軸審查（Standards、Spec）平行執行；主 session 逐條核對後處理。

| 軸 | 發現 | 處理 |
|---|---|---|
| Standards | `Resolution` 用 `StrEnum`，違反 `models.py` docstring「enum 值是儲存詞彙」 | 改為一般 `Enum`，docstring 註明只在程式內使用 |
| Standards | ledger 借用 `books_crawler.run` 的 logger 名稱 | 改為 `books_crawler.ledger` |
| Standards | `RunReport`／exit code 放進「純資料型別」的 `models.py` | 移到 `ledger.py`；`test_run_unit.py` 改從 ledger import，不再依賴 `run.py` 的隱性 re-export |
| Standards | `run.py` 從 `ledger.skipped` 推算限制級排名（Feature Envy） | 新增 `ledger.restricted_ranks`，移除 `skipped` 屬性 |
| Standards | ledger 依賴「訊息已遮罩」但未寫明 | `RunLedger` docstring 註明 |
| Standards | 測試 helper `play` 名稱不清、只測常數的測試、過長的行 | 改名 `record_until_abort`、刪除常數測試、拆行 |
| Spec | `crawler.md` §6 未加註 | 補上實作位置 |
| Spec | 刪掉的測試含「多本限制級只請求一次」的 resolver 行為 | D3：補回精簡 DB 測試 |
| Spec | first-book 一般失敗的 `aborted_at_rank`／`consecutive_error_count` 改變 | D1：接受，`crawler.md` §12 定義同步修改 |
| Spec | first-book 失敗不再有 `first-book import failed:`；每日 run 中止不再有 `run failed:` 前綴 | D2：每次 FAILED 由 orchestration 記一行 ERROR，ledger 不另外寫中止 log |
| Spec | rank 亂序／中止後記錄會拋錯（規格未要求） | 保留：低風險防呆 |

修正後重跑：**279 passed**；`git diff --check` 通過。

## 未解決事項

1. **候選 2（在同一 transaction 裡驗證並發布 Bestseller）**：`run_once` 仍需先查 `booksdotcom_source_books`、再把 `ledger.restricted_ranks` 傳給 `validate_snapshot`。候選 2 完成後，`restricted_ranks` 可能不再需要對外公開。
2. **候選 4（詳細頁回傳分類好的結果）**：`_fetch_and_parse` 仍靠 `except RestrictedBookError` 排在 `except ValueError` 前面來分辨限制級；`parsers.py` 的 docstring 仍寫「A parse error fails the run」，與 §6 不符。
3. **`RunLedger.report` 的參數**：`run_id`、`started_at`、`finished_at`、`ranking_count` 只是原樣放進 `RunReport`（Standards 判斷題，Data Clumps）。目前只有兩個 caller，暫不收成 dataclass。
