# Issue #7 實作報告：Crawler 重試、跳過與失敗門檻

- Issue：#7
- Branch：issue-7-crawler-retry-skip
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 變更檔案

| 檔案 | 類型（新增/修改/刪除） | 說明 |
|---|---|---|
| `crawler/books_crawler/run.py` | 修改 | 重試與跳過（`_attempt_new_source`、`_resolve_row`）、排行榜頁重試（`_fetch_ranking_page`）、同一 Book 重複時跳過較後排名、跳過上限與 `PARTIAL_SUCCESS`、log 格式與 DSN 遮罩；`RunDependencies` 新增可注入的 `sleep` |
| `crawler/books_crawler/models.py` | 修改 | `RunStatus` 新增 `PARTIAL_SUCCESS`；新增 `SkippedRow` dataclass |
| `crawler/books_crawler/ranking.py` | 修改 | `validate_snapshot` 改為 90～100 筆、rank 在 1..100 內且唯一（允許缺號）、book_id 唯一、source_id 必須是同一 Book 的 BOOKS_COM_TW 來源；新增 `MAX_SKIPPED_ROWS = 10`；`validate_ranking` 不變 |
| `crawler/books_crawler/db.py` | 修改 | 新增 `booksdotcom_source_books`（替換前查 source_id → book_id） |
| `crawler/books_crawler/cli.py` | 修改 | 只更新 docstring 的 exit code 說明（PARTIAL_SUCCESS 為 0）；`HttpFetcher` 建構行未動 |
| `crawler/tests/fakes.py` | 修改 | `FakeFetcher` 新增 `transient_failures`（前 N 次失敗）；新增 `FakeSleep`（記錄 backoff，不實際等待） |
| `crawler/tests/test_run_unit.py` | 修改 | 排行榜頁重試、parse 失敗不重試、門檻、backoff、log 欄位與遮罩測試；全部 RunDependencies 注入 `FakeSleep` |
| `crawler/tests/test_ranking.py` | 修改 | `validate_snapshot` 新規則（90..100、缺號允許、source 所屬 Book 檢查） |
| `crawler/tests/test_db_integration.py` | 修改 | 舊的「新書失敗即整次失敗」「同一 Book 即整次失敗」測試改寫為新規則；新增重試成功、transaction 重試、10/11 門檻、log 測試 |
| `crawler/tests/test_e2e_real_fixtures.py` | 修改 | 缺 title / 缺 product container 的派生頁改為重試後跳過（PARTIAL_SUCCESS，99 筆、缺號） |
| `Docs/modules/crawler.md` | 修改 | §3 流程圖、§4 排行榜頁重試、§5 移除「暫定」並寫入最終規則、§6 重試與跳過的具體規則、§10 snapshot 驗證、§12 log 格式與遮罩 |
| `Docs/data/data-model.md` | 修改 | §6 移除「暫定」，寫入最終規則（跳過較後排名） |
| `Docs/Implementation-Report/issue-7-crawler-retry-skip.md` | 新增 | 本報告 |

## 實作思路

### 重試範圍與 backoff

- 「一次嘗試」（attempt）= 詳細頁 request + parse + ISBN 比對 + 該書的 Book transaction。每次嘗試失敗都從頭重來，所以 transaction 失敗時也會重新抓一次詳細頁（實作上最簡單；代價是 DB 失敗時多一次 request，見未解決事項）。
- 可重試的失敗與 `error_type`：
  - `FetchError` → `fetch_error`
  - `ParseError`（它是 `ValueError` 子類，含 title / product container 缺失、非法商品 URL）以及 `BookDraft` 驗證失敗（`ValueError`）→ `parse_error`
  - `psycopg.Error`（ISBN 查詢或 Book transaction）→ `database_error`；transaction 已由 `conn.transaction()` rollback
- 最多 3 次嘗試（含第一次）。第 2 次前等 **1s**，第 3 次前等 **2s**（`BACKOFF_BASE_SECONDS * 2 ** (attempt - 2)`）。`sleep` 由 `RunDependencies.sleep` 注入，預設 `time.sleep`，測試全部注入 `FakeSleep`。
- 其他未列出的例外不會被當作單列跳過，而是讓整次 run 失敗（避免程式錯誤被悄悄吞成跳過）。

### 跳過的資料語意

- 跳過的排名不寫任何資料列（沒有 `books` / `book_sources` / 其他關聯列），榜單 snapshot 只包含未跳過的排名。
- 每個被跳過的排名記錄 `rank`、`url`、`error_type`、`error_message`、`attempts`。
- 每個商品仍各自一個 transaction（§9），跳過某本不影響其他書的寫入。
- 替換榜單時 rank 保留博客來原始排名，缺號不重新編號（bestsellers 與 BEST-03 一致）。

### 同一 Book 兩個排名（使用者決定：跳過較後面的排名）

- 排名依 rank 由小到大處理，「較前面」即 rank 較小者。
- 三種情況一律處理：既有 URL 與新商品 ISBN 命中同一 Book（兩種順序）、兩個新商品共用 ISBN。
- 較後面的排名被跳過，`error_type = duplicate_book_in_ranking`，`attempts = 1`，不重試；不抓、不寫該商品的 `book_sources`。
- 既有 URL 的重複排名不需抓詳細頁，直接跳過。
- 較前面的排名保留該 Book（若是 ISBN 附加的新來源，其 `book_sources` 列保留，因為它在榜單上）。

### 門檻與狀態

- `status_for_skipped_count`：0 → `SUCCESS`；1～10 → `PARTIAL_SUCCESS`（替換榜單，exit 0）；>10 → `FAILED`（不替換，exit 1）。
- 跳過數一超過 10，run 立即中止（`SkipLimitExceededError`），不再處理之後的排名。理由：改版時否則每一列都要白白重試 3 次。
- 排行榜頁不跳過：筆數、rank、URL 驗證失敗仍整次 FAILED。

### 排行榜頁重試（規格未定義，本實作決定）

- 排行榜頁 `FetchError` 套用與詳細頁相同的政策（3 次，1s、2s），3 次仍失敗才 FAILED。
- 排行榜頁 `ParseError`、筆數或 URL 驗證失敗是確定性的，不重試。

### Snapshot 驗證

- `validate_snapshot(rows, source_books)`：90 ≤ 筆數 ≤ 100；rank 在 1..100 內且唯一；book_id 唯一；每列 source_id 必須出現在 `source_books`（由 `db.booksdotcom_source_books` 查得的 BOOKS_COM_TW 來源 → book_id 對應）且 book_id 相同。
- 驗證在 `replace_bestsellers` 之前，驗證失敗即 FAILED，榜單與 `last_seen_at` 不變。
- `_has_exact_ranks` 仍用於排行榜頁；snapshot 使用新的 `_has_unique_ranks_in_range`，避免重複邏輯。

### Log 結構

- 每次 run 一行 INFO：`run_id`、`started_at`、`finished_at`、`status`、`ranking_count`、`existing_book_count`、`new_book_count`、`attached_source_count`、`skipped_count`、`exit_code`，以及 `skipped=` JSON 陣列（無跳過時 `[]`）。
- 每次嘗試失敗一筆 WARNING；每本被跳過的書一筆 WARNING；run 失敗一筆 ERROR。
- 遮罩：所有輸出經 `_redact`，`postgres(ql)://...` 字串一律改為 `postgresql://<redacted>`。`DATABASE_URL` 本身不會進入 log。

## 執行紀錄（Log）

以真實的 `format_report` 產生的一行（資料為示意，URL 編號為虛構）：

```text
run_id=7f3c2a10-0000-4000-8000-000000000007 started_at=2026-10-11T04:00:05+00:00 finished_at=2026-10-11T04:00:05+00:00 status=PARTIAL_SUCCESS ranking_count=100 existing_book_count=40 new_book_count=57 attached_source_count=3 skipped_count=2 exit_code=0 skipped=[{"rank": 12, "url": "https://www.books.com.tw/products/0011234567", "error_type": "fetch_error", "error_message": "GET https://www.books.com.tw/products/0011234567 returned HTTP 503", "attempts": 3}, {"rank": 88, "url": "https://www.books.com.tw/products/0011234599", "error_type": "parse_error", "error_message": "title (h1) not found in the product container of https://www.books.com.tw/products/0011234599", "attempts": 3}]
```

## 驗證結果

pytest 摘要（`~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`）：

```text
164 passed in 25.04s
```

（改動前基線為 147 passed。）測試容器由 testcontainers 管理，結束後無殘留（`docker ps -a` 中沒有測試容器）。`dotnet build` 在 `conftest.py` 的 session fixture 中執行（`dotnet build Book-Finder.csproj` + `dotnet ef migrations script`），每次測試都通過；本次沒有 C# 變更。

### Issue #7 acceptance criteria

| 條目 | 結果 | 對應測試 |
|---|---|---|
| 詳細頁前兩次失敗、第三次成功 → 該書正常寫入 | ✅ | `test_detail_failing_twice_then_succeeding_writes_the_book_normally`（sleep = [1.0, 2.0]）；另 `test_book_transaction_failing_twice_then_succeeding_writes_the_book_normally` |
| 3 本新書持續失敗 → 97 筆、原始排名保留、`PARTIAL_SUCCESS`、exit 0 | ✅ | `test_three_persistently_failing_new_books_are_skipped_and_ranks_keep_their_numbers` |
| 跳過 10 本 → `PARTIAL_SUCCESS` | ✅ | `test_exactly_ten_skipped_rows_is_partial_success_and_replaces_bestsellers` |
| 跳過 11 本 → `FAILED`，原有 Bestseller 與 `last_seen_at` 完全不變，exit 非 0 | ✅ | `test_eleven_skipped_rows_fail_the_run_and_keep_bestsellers_and_last_seen_completely`（CRAWL-05 regression guard） |
| 缺 title 的詳細頁 fixture 視為失敗、重試後跳過，不寫入空 Book | ✅ | `test_derived_new_source_without_title_is_retried_then_skipped_without_an_empty_book`（派生自真實 fixture）；另 `test_derived_new_source_without_product_container_is_retried_then_skipped` |
| log 含規定欄位，且不含 secret | ✅ | `test_run_log_has_the_required_fields_and_no_database_url`；`test_format_report_lists_skipped_rows_and_redacts_database_urls` |
| 同一 Book 的兩個排名：跳過較後面、計入 skipped、PARTIAL_SUCCESS | ✅ | `test_existing_url_then_new_source_with_same_isbn_skips_the_later_rank`；`test_new_source_then_existing_url_for_same_book_skips_the_later_rank`；`test_two_new_sources_sharing_an_isbn_skip_the_later_rank` |
| 暫定標示移除（`crawler.md` §5、`data-model.md` §6） | ✅ | 文件 diff；`grep 暫定` 無結果 |
| `pytest` 通過 | ✅ | 164 passed |

其他要求：

| 條目 | 結果 | 對應測試 |
|---|---|---|
| book transaction 失敗 → rollback、重試、跳過，其他書不受影響 | ✅ | `test_failed_book_transaction_is_rolled_back_retried_and_skipped_while_others_are_unaffected` |
| 排行榜不足 100 筆 → FAILED（無跳過路徑） | ✅ | `test_ranking_with_99_rows_fails_and_keeps_previous_bestsellers`；`test_derived_ranking_with_99_rows_fails_and_keeps_bestsellers`；`test_incomplete_ranking_fails_before_database_and_detail_fetches` |
| 排行榜頁 fetch 重試；parse 失敗不重試 | ✅ | `test_ranking_fetch_error_is_retried_three_times_then_fails_run`；`test_ranking_fetch_that_recovers_is_validated_as_usual`；`test_real_parsers_reject_a_page_that_is_not_the_ranking_and_fail_the_run` |
| snapshot 驗證（90..100、缺號允許、source 屬於同一 Book） | ✅ | `crawler/tests/test_ranking.py` 中的 `test_snapshot_*`、`test_source_must_be_a_booksdotcom_source_of_the_same_book`、`test_source_missing_from_the_database_is_rejected` |
| 替換失敗時榜單與 `last_seen_at` 不變（既有測試仍通過） | ✅ | `test_failed_snapshot_replacement_keeps_previous_list_and_last_seen`；`test_failed_run_leaves_last_seen_unchanged` |
| 不得記錄 DATABASE_URL | ✅ | `format_report` 遮罩測試；DB log 測試斷言 `db_url` 與 `crawler_test:crawler_test@` 不出現在 log 中 |
| backoff 與 exit code（SUCCESS / PARTIAL 為 0、FAILED 非 0） | ✅ | `test_status_thresholds`；`test_backoff_schedule`；各 DB 測試的 `report.exit_code` 斷言 |

## 未解決事項與後續注意

1. **規格未定義、本實作的決定**（請 reviewer 確認）：
   - 排行榜頁的 fetch 重試（3 次，1s、2s）。
   - 一次「嘗試」包含 detail request、parse、ISBN 比對與 Book transaction；transaction 失敗時會重新抓詳細頁。
   - backoff 值 1s、2s（規格例子為 1s、2s、4s；3 次嘗試只需兩段等待）。
   - `error_type` 採用 snake_case 類別名：`fetch_error`、`parse_error`、`database_error`、`duplicate_book_in_ranking`。
   - 重複排名的 `attempts` 為 1；既有 URL 的重複排名不抓詳細頁。
   - 跳過數超過 10 時立即中止，之後的排名不處理。
   - `ValueError`（含 `ParseError` 與 `BookDraft` 驗證）歸類為 `parse_error`；其他非預期例外不跳過，整次 run 失敗。
   - log 遮罩 `postgres(ql)://` 字串，作為額外保護。
2. **FAILED run 留下已 commit 的新 Book**：依 §9，每本書各自一個 transaction，因此跳過數超過 10 而中止時，之前寫入的新 Book 會保留。它們不在任何榜單上，`last_seen_at` 也沒有被更新，但會留在 `books` / `book_sources`，下次 run 會被視為既有來源。這是符合現行 §9 的行為，但值得注意。
3. **DB 失敗時重抓詳細頁**：transaction 失敗的重試會重新 request 詳細頁，是為了實作簡單；若博客來流量成為問題，可改為只重試寫入（需要保留 draft）。
4. **snapshot 尚未驗證「rank 集合 = 排行榜 − 跳過排名」**：規格沒有要求，目前只驗證 §10 列出的條件。若要加強，可在 `run_once` 中比對。
5. **Playwright fetcher（issue-24）的契約**：重試只針對 `FetchError`。新的 fetcher 必須把 challenge 頁、非 200、逾時都包成 `FetchError`，否則會變成整次 run 失敗而不是跳過。本次沒有修改 `fetcher.py`，也沒有修改 `cli.py` 的 fetcher 建構。
6. **backoff 的實際耗時**：每本被跳過的書約額外耗時 3 秒（1s + 2s），加上 3 次 request；跳過上限 10 本時，額外等待約 30 秒，可接受。
