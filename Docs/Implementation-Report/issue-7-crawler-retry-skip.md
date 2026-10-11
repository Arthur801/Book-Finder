# Issue #7 實作報告：Crawler 重試、跳過與失敗門檻

- Issue：#7
- Branch：issue-7-crawler-retry-skip（疊在 #24 的 Playwright fetcher 之上；見下方「分支關係」）
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 分支關係

本 branch 的提交順序（由舊到新）：

```text
af2ac5d  main（Merge PR #25）
9524b6e  Add Playwright browser fetcher for the crawler (#24)       ← 另一個 agent
7d2655b  Add crawler retry, skip and failure threshold (#7)         ← 本 issue 的原始提交（rebase 後）
<本次>   Address code review findings (#24, #7)                     ← 本輪審查修正
```

本 issue 最初在 main 上實作；協調者後來將 #7 rebase 到 #24 之上。因此本報告的測試數字以合併後的 branch 為準（見「驗證結果」）。

## 變更檔案

以下列出整個 branch 相對於 `af2ac5d`（main）中**與 #7 有關**的檔案。#24 的檔案（`fetcher.py` 的 Playwright 部分、`test_playwright_fetcher.py`、`crawler/README.md` 初版等）見 `issue-24-playwright-fetcher.md`。

| 檔案 | 類型（新增/修改/刪除） | 說明 |
|---|---|---|
| `crawler/books_crawler/run.py` | 修改 | 重試與跳過：`_attempts` 共用迴圈；`_fetch_and_parse`（重試會重新 request）與 `_write_new_source`（重試只重寫，沿用 draft）；`_resolve_row` 組合兩者；`_fetch_ranking_page`；同一 Book 的重複排名跳過；`SkipLimitExceededError` 與 `aborted_at_rank`；log 格式；所有錯誤文字經 `redact` |
| `crawler/books_crawler/models.py` | 修改 | `RunStatus.PARTIAL_SUCCESS`；`SkipReason`（StrEnum）；`Failure(error_type, error_message, attempts)`；`SkippedRow(rank, url, failure)` |
| `crawler/books_crawler/ranking.py` | 修改 | `validate_snapshot(rows, source_books)`：90..100 列、rank 在 1..100 內且唯一（允許缺號）、book_id 唯一、source_id 必須是同一 Book 的 BOOKS_COM_TW 來源；`MAX_SKIPPED_ROWS = 10`；`validate_ranking` 不變 |
| `crawler/books_crawler/db.py` | 修改 | `booksdotcom_source_books()`：替換榜單前查 source_id → book_id |
| `crawler/books_crawler/redact.py` | 新增 | 所有 log 與儲存的錯誤訊息的遮罩：`postgres(ql)[+driver]://…` → `postgresql://<redacted>`；`password=`/`pwd=` 的值 → `<redacted>` |
| `crawler/books_crawler/fetcher.py` | 修改（#24 + 本輪） | 本輪：`FetcherKind`（StrEnum）；`PlaywrightFetcher._fetch` 將 `new_page` 納入 try，所有 `PlaywrightError` 包成 `FetchError`；`page.close()` 與 context/browser/driver 的 close 改為 `_close_quietly`（記錄但不遮蔽原始錯誤）；`_start` 將 driver 啟動與 Chromium 啟動失敗包成 `BrowserUnavailableError`；公開 `navigation_timeout_ms` 唯讀屬性 |
| `crawler/books_crawler/cli.py` | 修改（#24 + 本輪） | 本輪：`CRAWLER_NAV_TIMEOUT_MS`（`parse_navigation_timeout`，非法值 → exit 2）；`FetcherKind` 取代字串比對；docstring 更新 exit code |
| `crawler/tests/fakes.py` | 修改 | `FakeFetcher(transient_failures=…)`；`FakeSleep`；`FakeBrowserContext` / `FakePage` / `FakeResponse`（模擬 Playwright 導覽與崩潰，不啟動瀏覽器） |
| `crawler/tests/test_run_unit.py` | 修改 | 排行榜頁重試、parse 失敗不重試、`BrowserUnavailableError` 不重試、門檻、backoff、log 欄位、遮罩、`SkipReason` 值 |
| `crawler/tests/test_ranking.py` | 修改 | `validate_snapshot` 新規則（90..100、缺號、rank 範圍與唯一、source 屬於同一 Book） |
| `crawler/tests/test_db_integration.py` | 修改 | 舊的「新書失敗即整次失敗」「同一 Book 即整次失敗」改寫為新規則；新增重試成功、只重寫 DB、解析暫時失敗重試、10/11 門檻、early abort、瀏覽器崩潰、`BrowserUnavailableError`、DSN 遮罩、log 欄位 |
| `crawler/tests/test_e2e_real_fixtures.py` | 修改 | 缺 title / 缺 product container 的派生頁改為重試後跳過（PARTIAL_SUCCESS，99 筆，缺號） |
| `crawler/tests/test_playwright_fetcher.py` | 修改（#24 + 本輪） | 本輪：Playwright 錯誤包裝、啟動失敗、close 失敗不遮蔽、瀏覽器中途消失、timeout 環境變數、`FetcherKind`；skip 訊息改為通用指令 |
| `Docs/modules/crawler.md` | 修改 | §4 排行榜頁重試；§5 移除「暫定」，寫入最終規則與 `attempts` 語意；§6 重試範圍（D4）；§10 snapshot 驗證；§12 `aborted_at_rank` 與遮罩；§15 與 D1、D2、瀏覽器錯誤契約、timeout 環境變數 |
| `Docs/data/data-model.md` | 修改 | §6 移除「暫定」，寫入最終規則（跳過較後面的排名） |
| `Docs/architecture/architecture-decisions.md` | 修改 | ADR-006 補充 User-Agent / zh-TW 的使用者決定（D1）與仍禁止的反偵測措施 |
| `AGENTS.md` | 修改 | §1.3 Crawler：「最多嘗試 3 次（含第一次）」；fetcher 的 UA 決定與禁止項（D1、B6） |
| `Docs/deployment/deployment.md` | 修改 | §5：非機密 crawler 環境變數 `CRAWLER_FETCHER`、`CRAWLER_NAV_TIMEOUT_MS`；釐清「只拿 DB 連線字串」指的是 secret（B7） |
| `crawler/README.md` | 修改 | 新增 `CRAWLER_NAV_TIMEOUT_MS`；exit code 0 包含 PARTIAL_SUCCESS |
| `Docs/Implementation-Report/issue-7-crawler-retry-skip.md` | 修改 | 本報告 |
| `Docs/Implementation-Report/issue-24-playwright-fetcher.md` | 修改 | 新增「Code Review 與修正」段落 |

## 實作思路

### 重試範圍與 backoff（D4 修正後）

- **一次嘗試（attempt）**：每個新來源最多 **3 次嘗試**（含第一次），兩種失敗共用同一個計數。
- **詳細頁 request 或 parse 失敗**（`fetch_error`、`parse_error`）：下一次嘗試**重新 request 詳細頁**。
- **資料庫寫入失敗**（`database_error`，ISBN 查詢或 Book transaction）：下一次嘗試**只重寫**，沿用已解析的 `BookDraft`，**不重新 request 詳細頁**。transaction 已由 `conn.transaction()` rollback，因此重寫不會留下半套資料。
- 間隔：第 2 次嘗試前等 **1s**，第 3 次嘗試前等 **2s**（`BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)`）。`sleep` 由 `RunDependencies.sleep` 注入，測試全部注入 `FakeSleep`。
- `_attempts(deps)` 是唯一的 backoff 迴圈，排行榜頁與每個新來源共用，不再有重複的 backoff 程式碼。

### 跳過的資料語意

- 被跳過的排名不寫任何資料列（不建立 `books`、`book_sources` 或關聯列）。榜單 snapshot 只包含未跳過的排名，rank 保留博客來原始排名，缺號不重新編號（BEST-03）。
- 每列記錄 `Failure(error_type, error_message, attempts)`，`attempts` 為**實際嘗試次數**（見下方「同一 Book 的重複排名」）。
- 每本新書各自一個 transaction（§9）；跳過某本不影響其他書。

### 同一 Book 的兩個排名（使用者決定：跳過較後面的排名）

- 排名依 rank 由小到大處理，「較前面」即 rank 較小者。
- 涵蓋：既有 URL 與新來源的 ISBN 命中同一 Book（兩種順序），以及兩個新來源共用一個 ISBN。
- 較後面的排名被跳過：`error_type = duplicate_book_in_ranking`，不重試，不寫該來源的 `book_sources`，較前面的排名保留該 Book。
- `attempts` 的意義（本輪修正，見 A4）：
  - 既有 URL 的重複：詳細頁從未被 request，`attempts = 0`。
  - ISBN 命中的重複：只能在讀取詳細頁之後才發現，因此 `attempts` 為發現時的嘗試編號（通常 `1`；若前面有暫時性失敗，則為 `2` 或 `3`）。

### 門檻、early abort 與狀態

- `status_for_skipped_count`：0 → `SUCCESS`；1～10 → `PARTIAL_SUCCESS`（替換榜單，exit 0）；超過 10 → `FAILED`（不替換，exit 1）。
- 跳過數一超過 10，run 立即中止（`SkipLimitExceededError`），並記錄 `aborted_at_rank`（本輪新增，D3）。中止後不再 request 之後的排名，避免改版時每列都白白重試 3 次。
- 中止前已各自 commit 的新 Book 保留（§9）；它們不在任何榜單上，`last_seen_at` 不變。
- 排行榜頁不跳過：筆數、rank、URL 驗證失敗仍整次 FAILED。

### 排行榜頁重試（D2 使用者決定）

- 排行榜頁 `FetchError` 套用與詳細頁相同的重試政策（最多 3 次，1s、2s）。3 次仍失敗即整次 FAILED。
- 排行榜頁 `ParseError`、筆數、rank、URL 驗證失敗是確定性的，不重試。
- 排行榜頁失敗時以 `raise FetchError(...) from last_error` 保留原因鏈（本輪 A2）。

### 瀏覽器錯誤契約（A1）

- `FetchError`：單頁抓取失敗，會被重試，可能被跳過。包含導覽逾時、任何 Playwright 錯誤（含 `TargetClosedError`，即瀏覽器或頁面在載入中崩潰）、challenge、非 200。
- `BrowserUnavailableError`（`RuntimeError`，**不是** `FetchError`）：driver 或 Chromium 無法啟動。不重試、不跳過單本書，整次 FAILED。測試：排行榜頁層級（`test_browser_unavailable_on_the_ranking_page_fails_the_run_without_retry`）與詳細頁層級（`test_browser_unavailable_on_a_detail_page_fails_the_run_without_retry_or_skip`）。
- `page.close()` 與 context / browser / driver 的 close 失敗會被記錄，但絕不取代原始錯誤。

### 錯誤類型（D5、C9）

`SkipReason`（StrEnum，值不變）：

| 值 | 來源 |
|---|---|
| `fetch_error` | `FetchError` |
| `parse_error` | `ParseError`，以及 `BookDraft` 驗證失敗（皆為 `ValueError`） |
| `database_error` | `psycopg.Error`（ISBN 查詢或 Book transaction） |
| `duplicate_book_in_ranking` | 同一 Book 出現在較前的排名 |

未列出的例外（例如程式錯誤）不會被當成單列跳過，而是讓整次 run FAILED。

### Snapshot 驗證

- `validate_snapshot(rows, source_books)`：90 ≤ 筆數 ≤ 100；rank 在 1..100 內且唯一（允許缺號）；book_id 唯一；每列的 source_id 必須出現在 `source_books`（由 `db.booksdotcom_source_books` 查得的 BOOKS_COM_TW 來源 → book_id），且 book_id 相同。
- 驗證在 `replace_bestsellers` 之前執行；失敗即 FAILED，榜單與 `last_seen_at` 不變。

### Log 結構與遮罩（A3、D5）

- 每次 run 一行 INFO：`run_id`、`started_at`、`finished_at`、`status`、`ranking_count`、`existing_book_count`、`new_book_count`、`attached_source_count`、`skipped_count`、`aborted_at_rank`（`none` 或排名）、`exit_code`，以及 `skipped=` JSON 陣列。
- 每次嘗試失敗一筆 WARNING；每本被跳過的書一筆 WARNING；run 失敗一筆 ERROR。
- **所有**輸出都經過 `redact`：每個 WARNING / ERROR 的錯誤文字、`Failure.error_message`（在建立時就遮罩，因此儲存的報告與 log 都乾淨）、排行榜頁的錯誤、fetcher 的關閉警告，以及最後的 run 行。

## 執行紀錄（Log）

以真實的 `format_report` 產生的一行（資料為示意，URL 編號為虛構；本輪新增 `aborted_at_rank`）：

```text
run_id=7f3c2a10-0000-4000-8000-000000000007 started_at=2026-10-11T04:00:05+00:00 finished_at=2026-10-11T04:00:05+00:00 status=PARTIAL_SUCCESS ranking_count=100 existing_book_count=40 new_book_count=57 attached_source_count=3 skipped_count=2 aborted_at_rank=none exit_code=0 skipped=[{"rank": 12, "url": "https://www.books.com.tw/products/0011234567", "error_type": "fetch_error", "error_message": "GET https://www.books.com.tw/products/0011234567 returned HTTP 503", "attempts": 3}, {"rank": 88, "url": "https://www.books.com.tw/products/0011234599", "error_type": "parse_error", "error_message": "title (h1) not found in the product container of https://www.books.com.tw/products/0011234599", "attempts": 3}]
```

超過上限而中止時，`aborted_at_rank=11` 會出現在同一行，且 `status=FAILED`、`exit_code=1`。

## 驗證結果

### pytest（合併後的 branch）

```text
217 passed in 36.13s
```

- 合併前（#7 + #24，本輪之前）為 189 passed。本輪新增 28 個測試，其中包括瀏覽器崩潰與 `BrowserUnavailableError` 的測試，它們使用真實 Chromium（本地頁面）執行。
- 本次執行**沒有任何 skip**，因此瀏覽器測試實際執行，包括 `test_browser_that_disappears_mid_run_raises_fetch_error_and_close_still_works`。
- `dotnet build`：0 Warning(s)、0 Error(s)。
- 測試容器：無殘留（`docker ps -a` 只有既有的開發用 `book-finder-db-1`）。

### Issue #7 acceptance criteria

| 條目 | 結果 | 對應測試 |
|---|---|---|
| 詳細頁前兩次失敗、第三次成功 → 該書正常寫入 | ✅ | `test_detail_failing_twice_then_succeeding_writes_the_book_normally`（sleep = [1.0, 2.0]） |
| 3 本新書持續失敗 → 97 筆、原始排名保留、`PARTIAL_SUCCESS`、exit 0 | ✅ | `test_three_persistently_failing_new_books_are_skipped_and_ranks_keep_their_numbers` |
| 跳過 10 本 → `PARTIAL_SUCCESS` | ✅ | `test_exactly_ten_skipped_rows_is_partial_success_and_replaces_bestsellers` |
| 跳過 11 本 → `FAILED`，原有 Bestseller 與 `last_seen_at` 完全不變，exit 非 0 | ✅ | `test_eleven_skipped_rows_fail_the_run_and_keep_bestsellers_and_last_seen_completely`（CRAWL-05） |
| 缺 title 的詳細頁 fixture 視為失敗、重試後跳過，不寫入空 Book | ✅ | `test_derived_new_source_without_title_is_retried_then_skipped_without_an_empty_book`（派生自真實 fixture） |
| log 含規定欄位，且不含 secret | ✅ | `test_run_log_has_the_required_fields_and_no_database_url`；`test_format_report_lists_skipped_rows_and_redacts_database_urls` |
| 同一 Book 的兩個排名：跳過較後面、計入 skipped、`PARTIAL_SUCCESS` | ✅ | `test_existing_url_then_new_source_with_same_isbn_skips_the_later_rank`；`test_new_source_then_existing_url_for_same_book_skips_the_later_rank`；`test_two_new_sources_sharing_an_isbn_skip_the_later_rank` |
| 暫定標示移除（`crawler.md` §5、`data-model.md` §6） | ✅ | 文件 diff；`grep 暫定` 無結果 |
| `pytest` 通過 | ✅ | 217 passed |

其他要求（本次 issue 的內文）：

| 條目 | 結果 | 對應測試 |
|---|---|---|
| book transaction 失敗 → rollback、重試（只重寫）、跳過，其他書不受影響 | ✅ | `test_failed_book_transaction_is_rolled_back_retried_and_skipped_while_others_are_unaffected` |
| 排行榜不足 100 筆 → FAILED（無跳過路徑） | ✅ | `test_ranking_with_99_rows_fails_and_keeps_previous_bestsellers`；`test_derived_ranking_with_99_rows_fails_and_keeps_bestsellers`；`test_incomplete_ranking_fails_before_database_and_detail_fetches` |
| snapshot 驗證（90..100、缺號、rank、source 屬於同一 Book） | ✅ | `crawler/tests/test_ranking.py` 的 `test_snapshot_*`、`test_source_must_be_a_booksdotcom_source_of_the_same_book`、`test_source_missing_from_the_database_is_rejected` |
| 替換失敗時榜單與 `last_seen_at` 不變 | ✅ | `test_failed_snapshot_replacement_keeps_previous_list_and_last_seen`；`test_failed_run_leaves_last_seen_unchanged` |
| exit code（SUCCESS / PARTIAL 為 0，FAILED 非 0） | ✅ | `test_status_thresholds`；各 DB 測試的 `report.exit_code` 斷言 |

### 本輪審查修正的測試（D14–D17、A1–A3）

| 項目 | 測試 |
|---|---|
| D14 early abort 真的停止：rank 1–11 失敗，之後的來源不被 request，log 含 `aborted_at_rank=11` | `test_eleven_failures_at_the_top_stop_the_run_before_any_later_source_is_fetched` |
| D15 瀏覽器崩潰（導覽時）→ `FetchError` → 重試並寫入；所有頁面都被關閉 | `test_browser_crash_during_navigation_is_retried_and_the_row_is_written`（真實 `PlaywrightFetcher` + 假 context） |
| D15 瀏覽器中途消失（真實 Chromium）→ `FetchError`；之後 `close()` 不拋例外 | `test_browser_that_disappears_mid_run_raises_fetch_error_and_close_still_works` |
| A1 `BrowserUnavailableError` 不重試、不跳過（排行榜頁與詳細頁） | `test_browser_unavailable_on_the_ranking_page_fails_the_run_without_retry`；`test_browser_unavailable_on_a_detail_page_fails_the_run_without_retry_or_skip` |
| A1 Playwright 錯誤包裝：new_page 崩潰、導覽崩潰、page.close 失敗不遮蔽、啟動失敗、launch 失敗會停止 driver、context close 失敗仍停止 driver | `test_new_page_crash_is_wrapped_into_fetch_error`；`test_navigation_crash_is_fetch_error_and_the_page_is_still_closed`；`test_failing_page_close_never_masks_the_original_fetch_error`；`test_browser_start_failure_is_browser_unavailable_and_not_a_fetch_error`；`test_chromium_launch_failure_stops_the_driver_and_is_browser_unavailable`；`test_close_stops_the_driver_even_when_closing_the_context_fails` |
| A3 psycopg 錯誤文字含 DSN 與密碼：log、`Failure.error_message`、`report.error` 都不含 | `test_database_error_text_with_a_connection_string_never_reaches_the_log_or_report`；`test_redact_removes_connection_strings_and_password_assignments`（4 組參數） |
| D16 DB 寫入第一次失敗後成功 → 詳細頁只 request 一次 | `test_book_transaction_failing_twice_then_succeeding_writes_the_book_normally`（fetch 次數 = 1） |
| D16 DB 寫入三次都失敗 → `database_error`、attempts 3、詳細頁只 request 一次 | `test_detail_page_is_fetched_once_when_database_writes_fail_three_times` |
| D17 解析暫時失敗後成功 → 重試並寫入（重新 request） | `test_detail_page_fetch_is_retried_when_the_parse_fails_at_first` |
| A5 `CRAWLER_NAV_TIMEOUT_MS`：傳入 fetcher；預設；非法值 → exit 2 | `test_cli_passes_the_navigation_timeout_to_the_browser_fetcher`；`test_cli_uses_the_default_navigation_timeout_when_unset`；`test_invalid_navigation_timeout_is_a_configuration_error`（6 組參數） |
| A2 排行榜頁重試後仍失敗的原因鏈 | `test_ranking_fetch_error_is_retried_three_times_then_fails_run` |

## 使用者決定（D1–D5）

| 編號 | 決定 | 本輪實作 |
|---|---|---|
| D1 | 瀏覽器 fetcher 保留一般桌面 Chrome UA 與 `zh-TW` 語系（2026-10-11 核准）；其他反偵測措施全部禁止 | ADR-006、`AGENTS.md` §1.3、`crawler.md` §15 已寫入此決定與禁止項 |
| D2 | 排行榜頁 fetch 重試最多 3 次；仍失敗 → FAILED；解析與驗證失敗不重試 | `crawler.md` §4 與 §15 文字一致；程式未變（已於 7d2655b 實作） |
| D3 | 跳過超過 10 本時 early abort，log 必須說明在哪裡中止 | 新增 `RunReport.aborted_at_rank`，log 欄位 `aborted_at_rank=<rank>` 或 `none` |
| D4 | DB 寫入失敗時只重寫、沿用 draft，不重新 request 詳細頁；fetch/parse 失敗仍重新 request；每個來源共 3 次 | `run.py` 的 `_fetch_and_parse` / `_write_new_source` 拆分；`crawler.md` §6 與本報告已更新 |
| D5 | 保留四個 `error_type` 值與 DSN 遮罩；遮罩必須涵蓋所有 log 輸出 | `redact.py`；所有 log 行與儲存的錯誤訊息都經過遮罩；測試見上表 |

## Code Review 與修正

本輪依協調者的雙軸審查（Standards + Spec）修正下列項目。

### A. 必須修正的錯誤

| 編號 | 問題 | 修正 |
|---|---|---|
| A1 | `PlaywrightFetcher._fetch`：`new_page()` 在 try 外；`page.close()` 失敗可能遮蔽原始錯誤；Playwright 錯誤未全部包成 `FetchError`；driver / 瀏覽器啟動失敗未包成 `BrowserUnavailableError` | `new_page` 移入 try；所有 `PlaywrightError`（含 `TargetClosedError`）→ `FetchError`；`page.close()` 與各項 close 由 `_close_quietly` 處理；`_start` 包裝 driver 與 launch 失敗；`BrowserUnavailableError` 仍不是 `FetchError`，並有 run 層級測試證明不被重試 |
| A2 | `_fetch_ranking_page` 重新拋出時未保留原因鏈 | `raise FetchError(...) from last_error` |
| A3 | 遮罩未涵蓋所有 log；`SkippedRow.error_message` 未遮罩 | 所有錯誤文字在建立 `Failure` 時遮罩（`_failure`）；每個 log 行與 run 行都經過 `redact`；新增 psycopg 風格 DSN 的測試，檢查 caplog 與報告都不含密碼 |
| A4 | 重複排名的 `attempts` 與文件不一致（文件寫 1，既有 URL 的重複實際為 0） | 採用實際嘗試次數：既有 URL 的重複為 `0`（未抓取），ISBN 重複為發現時的嘗試編號；`crawler.md` §5 已更新；測試對應更新 |
| A5 | 導覽逾時無法在執行時設定 | `CRAWLER_NAV_TIMEOUT_MS`（整數 1..300000，空值為預設，其他為 exit 2）；`crawler/README.md` 與 `deployment.md` §5 已記錄 |

### B. 文件一致性

| 編號 | 修正 |
|---|---|
| B6 | `AGENTS.md` §1.3：「重試 3 次」改為「最多嘗試 3 次（含第一次）」 |
| B7 | `deployment.md` §5：新增非機密 crawler 環境變數表（`CRAWLER_FETCHER`、`CRAWLER_NAV_TIMEOUT_MS`），並釐清「只拿 DB 連線字串」指的是 secret |
| B8 | `crawler.md` §5 段落改用 Book / BOOKS_COM_TW source 用語；「商品」只保留在指頁面 URL 的地方 |

### C. 整理

| 編號 | 修正 |
|---|---|
| C9 | `SkipReason`（StrEnum，四個值不變）與 `FetcherKind`（`browser` / `http`）取代字串比對 |
| C10 | `Failure(error_type, error_message, attempts)` 取代三個分散的欄位；`_AttemptFailed`、`SkippedRow`、`_skipped` 都使用它 |
| C11 | `_attempts(deps)` 共用迴圈取代排行榜頁與來源各自的 backoff 迴圈 |
| C12 | 移除不可達的 `if status is RunStatus.FAILED` 分支 |
| C13 | 測試的 skip 訊息不再寫死開發者的 venv 路徑，改為通用的 `python -m playwright install chromium` / `install-deps` 指令 |

### D. 測試

| 編號 | 修正 |
|---|---|
| D14 | 真正的 early abort 測試：rank 1–11 失敗，斷言之後的來源沒有被 request，log 含 `aborted_at_rank=11` |
| D15 | 瀏覽器崩潰（導覽中與中途消失）→ `FetchError` → 重試或跳過；另有 run 層級測試 |
| D16 | DB 寫入失敗的重試不重抓詳細頁（一次成功、三次失敗兩種情境） |
| D17 | 解析暫時失敗後成功 → 重試並寫入 |

### E. 報告

- 本報告已更新：測試數字（189 → 217）、分支關係、D4 的重試範圍、`attempts` 語意、以及本節。
- `issue-24-playwright-fetcher.md` 新增對應的「Code Review 與修正」段落（fetcher 相關的修正）。

## 規格未定義而自行決定之處

1. 排行榜頁的 fetch 重試（3 次，1s、2s）。
2. 一次「嘗試」的範圍：fetch + parse 為一組（失敗則重新 request）；DB 寫入為另一組（失敗則只重寫，D4）。兩組共用同一個 3 次上限。
3. backoff 值 1s、2s（規格例子為 1s、2s、4s；3 次嘗試只需兩段等待）。
4. `error_type` 採用 snake_case 類別：`fetch_error`、`parse_error`、`database_error`、`duplicate_book_in_ranking`。
5. 重複排名的 `attempts`：既有 URL 為 0，ISBN 命中為發現時的嘗試編號（A4）。
6. 跳過數超過 10 時立即中止，並記錄 `aborted_at_rank`（D3）。
7. `ValueError`（含 `ParseError` 與 `BookDraft` 驗證失敗）歸類為 `parse_error`；其他非預期例外不跳過，整次 FAILED。
8. 遮罩規則（`postgres(ql)` 連線字串與 `password=`）是額外的保護，超出規格原文。

## 未解決事項與後續注意

1. **FAILED run 留下已 commit 的新 Book**：依 §9，每本書各自一個 transaction，因此跳過數超過 10 而中止時，之前寫入的新 Book 會保留。它們不在任何榜單上，`last_seen_at` 也沒有被更新；下次 run 會把它們視為既有來源。這符合現行 §9，但值得注意。
2. **瀏覽器中途崩潰後不會自動重啟**：`PlaywrightFetcher` 在瀏覽器消失後，之後每次 `get` 都會失敗為 `FetchError`。在 early abort 之下，這會很快變成 FAILED（而不是部分成功）。這是可接受的失敗方式（大聲失敗），但若要更有韌性，可在偵測到 `TargetClosedError` 時重新啟動瀏覽器。本輪未實作，因為規格沒有要求。
3. **snapshot 尚未驗證「rank 集合 = 排行榜 − 跳過排名」**：規格沒有要求，目前只驗證 §10 列出的條件。
4. **challenge 信號尚未在真實博客來頁面上驗證**（#24 已記錄）。
5. **EC2 實測**：部署前仍需在 EC2 上確認瀏覽器 fetcher 能取得頁面（`deployment.md` §8、#21）。
6. **backoff 的實際耗時**：每本被跳過的書額外耗時 3 秒（1s + 2s），加上最多 3 次 request；跳過上限 10 本時約 30 秒額外等待，可接受。

## 後續更新（2026-10-11）：限制級跳過與連續錯誤中止

> 本節接續原報告，記錄 PR #26 合併後依使用者指示所做的變更。上文保留當時的實作紀錄，其中「跳過超過 10 本即中止」「snapshot 至少 90 筆」等規則已被本節取代。架構決策檔中與 crawler fetcher 相關的 ADR（ADR-006 及之後的 ADR-007、ADR-008）已於 2026-10-11 刪除；上文若有引用，以及上文與本節有衝突時，現行規則一律以 `Docs/modules/crawler.md` 為準。

### 行為

- 排行榜頁最多抓取三次。解析或「完整 100 筆」驗證失敗屬於確定性錯誤，不重試，也不會跳過排行榜。
- 新書每本最多嘗試三次（含第一次），retry backoff 為 1s、2s。抓取或解析失敗會重新抓頁；DB 寫入失敗則沿用已解析的 draft，只重試寫入。每次網路請求仍遵守 3～30 秒的隨機間隔，backoff 也計入等待目標。
- 明確的限制級會員登入頁直接跳過：不重試、不寫入 Catalog，`restricted_book` 不算一般錯誤。
- 已存在的來源直接重用。同一 Book 被較後面的 rank 重複使用時，確定性跳過、不重試，計為一次一般錯誤。

### 中止規則（取代原本的「跳過超過 10 本」）

- 依原始 rank 順序，每本書最終一般失敗時，`consecutive_error_count` 才加一；單本的多次重試只算一次。成功匯入、ISBN attach、重用既有 URL、限制級跳過都會把計數歸零。
- 連續 20 本仍繼續；第 21 本立即 FAILED，記錄 `aborted_at_rank`，後面的排名不再抓取。累計的 `error_count` 沒有上限：交錯出現 50 本錯誤，或多組各 20 本錯誤，都仍會完成並替換 snapshot。排行榜、環境與交易錯誤仍可能使整次失敗。
- 失敗時保留上一份 Bestseller 與既有來源的 `last_seen_at`；中止前已 commit 的新 Catalog Book 會保留。完成全榜後，沒有跳過為 SUCCESS，有跳過為 PARTIAL_SUCCESS。Exit code：0 為成功或部分成功、1 為 FAILED、2 為設定錯誤。

### 變更檔案

| 檔案 | 說明 |
|---|---|
| `crawler/books_crawler/run.py` | `MAX_CONSECUTIVE_ERRORS = 20`，每日 run 更新連續錯誤計數。`RunReport` 分別輸出 `skipped_count`、`restricted_book_count`、累計 `error_count`、目前的 `consecutive_error_count` 與 `aborted_at_rank`。所有錯誤訊息都經過 redact。移除與新政策不符的 `status_for_skipped_count()`，不保留兩套狀態判定。新增單書入口 `run_first_book` |
| `crawler/books_crawler/ranking.py` | 移除 `MAX_SKIPPED_ROWS`、`MIN_SNAPSHOT_ROWS` 與由累計錯誤推出的最低筆數。保留 rank、來源歸屬、Book 唯一與限制級排除的驗證 |
| `crawler/books_crawler/models.py` | `SkipReason` 新增 `RESTRICTED_BOOK = "restricted_book"`；`PARTIAL_SUCCESS` 的說明改為新規則 |
| `crawler/books_crawler/parsers.py` | 偵測限制級會員頁（頁面同時有「限制級商品」與「登入會員」字樣，且沒有內容容器），拋出 `RestrictedBookError` |
| `crawler/tests/test_run_unit.py`、`test_ranking.py`、`test_db_integration.py`、`test_parsers_real_fixtures.py` | 移除舊門檻的測試，改寫為新規則（見下表） |

`first_book` 沿用相同的解析與重試政策：第一名為限制級時回 PARTIAL_SUCCESS／exit 0，一般失敗時回 FAILED／exit 1，兩種情況都不替換榜單。

### 測試重整

移除舊的 `test_status_thresholds`、90 筆最低值測試、10／11 本累計中止，以及 rank 11 early abort 測試，改用以下行為測試：

| 案例 | 測試 |
|---|---|
| 連續 20、21 本；直到 rank 100 才出現第 21 本；交錯 50 本；兩組各 20 本 | `test_error_streak_boundaries_and_scattered_errors` |
| 重試後成功仍會重設計數，不按請求次數計錯 | `test_eventual_success_after_retries_resets_twenty_errors` |
| 既有來源與限制級在兩組錯誤之間重設計數 | `test_non_error_row_resets_streak_even_without_new_book_import` |
| 解析與 DB 最終失敗同樣在第 21 本中止 | `test_terminal_parse_and_database_errors_also_abort_at_twenty_one` |
| 限制級只抓一次，之後接 20／21 本錯誤的邊界 | `test_restricted_books_skip_once_before_error_streak_boundary` |
| Snapshot 不以累計錯誤限制最低筆數 | `test_snapshot_has_no_total_error_count_minimum` |

中止相關的測試另外檢查：後面的 URL 沒有被請求、每本最多三次、舊 snapshot 與 `last_seen_at` 完整保留、接近榜尾才中止時已 commit 的新書仍保留，以及 log 記錄了中止的排名。測試不連線博客來，DB 使用 disposable PostgreSQL。

### 驗證

2026-10-11 執行 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **258 passed in 38.64s**，沒有 skip。範圍涵蓋單元測試、真實 HTML fixtures、disposable PostgreSQL 整合測試與本機 Chromium 測試，測試不連線博客來；沒有對開發或正式資料庫套用 migration。`git diff --check` 通過。本次沒有重新做真實網站抓取，也沒有做 production／EC2 驗證。

### 未解決事項更新

1. 原第 1 項（FAILED 的 run 留下已 commit 的新 Book）仍然成立，觸發條件改為「連續第 21 本一般錯誤」。
2. 原第 2 項（瀏覽器中途崩潰後不會自動重啟）只影響可選的 browser fetcher；之後的連續失敗仍受第 21 本規則保護。
3. 原第 3、4、5 項維持不變。EC2 驗證改為驗證預設的 curl fetcher（`Docs/deployment/deployment.md` §8、#21）。
4. 原第 6 項（backoff 耗時以 10 本上限估算）已不適用：沒有累計上限，加上每次請求 3～30 秒的隨機間隔，整次 run 會明顯變長。
5. 新規則容許榜單筆數較少，這符合使用者本次的要求；但不保證能通過 Cloudflare。
6. 限制級頁面的偵測只用一行人工撰寫的 HTML 測過 parser，沒有真實頁面的 fixture，也沒有走過 curl fetcher 的完整路徑。如果真實的會員限制頁回傳非 200 或 redirect，會被 fetcher 當成一般錯誤（2026-10-11 code review 指出）。

### Code Review 與修正（2026-10-11）

依雙軸 code review 修正下列兩項，行為規則不變：

| 項目 | 發現 | 修正 |
|---|---|---|
| 限制級判斷重複 | `run.py` 有五處各自比對 `error_type == SkipReason.RESTRICTED_BOOK` | `SkippedRow` 新增 `is_restricted` 屬性，五處都改用它 |
| 第一名錯誤類型 | `run_first_book` 不論失敗原因（解析、DB 或抓取），都拋 `FetchError("rank 1 import failed")`，所以 `report.error` 的類型標籤會誤導 | 新增 `FirstBookImportError`，訊息附上實際的 `error_type`，例如 `FirstBookImportError: rank 1 import failed (database_error): …`；exit code 不變 |

新增測試 `test_first_book_database_failure_is_not_reported_as_a_fetch_error`，並在 `test_first_book_challenge_exhausts_retries_and_fails` 補上錯誤訊息的斷言。重跑 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **259 passed**；`git diff --check` 通過。

同一輪 review 另修正測試的寫法不一致，測試內容不變：`test_db_integration.py`、`test_first_book.py`、`test_parsers_real_fixtures.py`、`test_ranking.py` 新增的單引號字串改為雙引號；前三個檔案重複的 `from books_crawler.parsers import` 合併為一行。重跑結果同樣是 **259 passed**。

另將 `SkipLimitExceededError` 改名為 `ConsecutiveErrorLimitError`：它現在表示「連續一般錯誤超過上限」，不是舊的「跳過數超過上限」。docstring 改為引用 `MAX_CONSECUTIVE_ERRORS`，不再寫死 20。run log 的 `error=` 欄位會顯示新的類別名稱；中止條件、`aborted_at_rank` 與 exit code 都不變。重跑結果同樣是 **259 passed**。

### 限制級頁面的真實 fixture（2026-10-11，解決「未解決事項更新」第 6 項）

- 使用者以瀏覽器另存 0011063006（舞臺下的單向愛戀 Re (首刷限定版) 全）。這是**登入後的完整頁面**，只有「限制級商品」標章，沒有會員限制。已依命名慣例改名為 `crawler/tests/fixtures/detail_0011063006.html`。
- 未登入時實際收到的頁面，取自使用者授權的本機 curl 實測紀錄（`crawler/artifacts/verification/top100-random-20261011T001507Z/`，該次 run 的 rank 2，就是同一本書），原樣複製為 `crawler/tests/fixtures/restricted_gate_0011063006.html`。`requests.json` 記錄這次回應為 **HTTP 200**、1517 bytes，沒有 `cf-mitigated`；內容是 JavaScript `alert` 加上 `location.href` 導向登入頁，不是 HTTP 3xx。同一次 run 的 13 本限制級書籍都以 `restricted_book`、`attempts=1` 跳過，與這個觀察一致。
- 結論：code review 擔心的「會員限制頁若是非 200 或 redirect，會被 fetcher 當成一般錯誤」不會發生。程式不需要修改，以下測試把真實行為固定下來：

| 測試 | 驗證內容 |
|---|---|
| `test_real_restricted_member_gate_is_recognized` | 真實會員限制頁 → `RestrictedBookError` |
| `test_restricted_badge_on_a_real_product_page_is_not_a_member_gate`；`CASES["0011063006"]` | 登入後的完整頁面不會被誤判為限制級，書目欄位正確解析 |
| `test_real_restricted_member_gate_reaches_the_parser_unchanged` | `CurlCffiFetcher` 收到真實會員限制頁（HTTP 200）時原樣回傳，不保存失敗診斷，parser 判定為限制級 |
| `test_real_restricted_member_gate_is_skipped_once_and_leaves_a_gap` | 真實排行榜 + 真實詳細頁 + 真實會員限制頁的完整 run：PARTIAL_SUCCESS，rank 2 只抓一次並缺號，`restricted_book_count=1`、`error_count=0`，沒有寫入 `book_sources` |

原本用人工撰寫 HTML 的兩個限制級 parser 測試，改由上表的真實 fixture 測試取代。`crawler/tests/fixtures/README.md` 與 `Docs/modules/crawler.md` §6 補上實測結果。重跑 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **263 passed**。
