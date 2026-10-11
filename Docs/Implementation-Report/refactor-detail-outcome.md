# 重構實作報告：詳細頁與寫入步驟回傳分類結果

- 來源：2026-10-11 架構檢視的候選 4「詳細頁回傳分類好的結果」（見 `refactor-run-ledger.md` 未解決事項 2）
- Issue：無（純重構）
- Branch：`refactor-detail-outcome`（worktree `Book-Finder-wt/refactor-detail-outcome`，自 `main` `a22cb17` 建立；未 push、未 merge）
- 實作：子 agent 以 TDD 實作
- 日期：2026-10-11

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/books_crawler/run.py` | 修改 | 刪除 `DuplicateBookInRankingError` 與 `_AttemptFailed`；新增私有 dataclass `_ParsedDraft`、`_RestrictedPage`、`_WrittenSource`、`_DuplicateBook`；`_fetch_and_parse`、`_write_new_source` 改為回傳 outcome 或 `Failure`；抽出 `_log_attempt_failed`；`_resolve_row` 的重試迴圈只檢查回傳值 |
| `crawler/books_crawler/parsers.py` | 修改 | `RestrictedBookError` 改為 `Exception` 的子類別並更新 docstring；`ParseError` docstring 與模組 docstring 改為「排行榜解析錯誤使 run 失敗；詳細頁解析錯誤重試後跳過」；`parse_detail_html` 的契約不變 |
| `crawler/tests/test_parsers_real_fixtures.py` | 修改 | 新增 `test_restricted_book_error_is_not_a_parse_error_or_value_error` |
| `crawler/tests/test_first_book.py` | 修改 | 新增 `test_draft_validation_error_from_the_detail_parser_is_retried_as_parse_error`；`test_restricted_first_book_skips_once_without_error` 補上限制級 INFO log 的斷言 |
| `Docs/Implementation-Report/refactor-detail-outcome.md` | 新增 | 本報告 |

未修改：`models.py`、其他 crawler 模組、`Docs/modules/crawler.md`（§4、§6 的規則與行為已一致，不需改動）。

## 實作思路

- **兩個步驟都回傳分類結果，不再拋出例外**：
  - 詳細頁步驟 `_fetch_and_parse` 回傳 `_ParsedDraft(draft)`、`_RestrictedPage(message)`，或 `Failure`（`fetch_error` 與 `parse_error`）。
  - 寫入步驟 `_write_new_source` 回傳 `_WrittenSource(ref, match)`、`_DuplicateBook(message)`，或 `Failure`（`database_error`）。
- **重試迴圈只看回傳值**：`_resolve_row` 不再有任何 `try/except`。`_RestrictedPage` 立即跳過（不重試、`attempts` 為當次嘗試次數）；`Failure` 記一行 WARNING 後進入下一次嘗試；`_DuplicateBook` 立即跳過；成功則回傳 `ResolvedRow`。詳細頁 `Failure` 重試時會重新 request；寫入 `Failure` 重試時沿用已解析的 draft，不重新 request。
- **分類只寫在一處**：`RestrictedBookError` 已不是 `ValueError`，因此分類不再依賴 `except` 的順序。`_fetch_and_parse` 的 `except ValueError` 分支（附註解）統一把 `ParseError` 與 `BookDraft` 驗證失敗歸為可重試的 `parse_error`，這是程式中唯一寫明此規則的地方。
- **未分類例外照常傳遞**：`BrowserUnavailableError` 等不被任何 `except` 捕捉，使整次 run FAILED，行為不變。
- **行為不變的部分**：每本新來源最多 3 次（第 1、2 秒退避）；WARNING 與 INFO 的 log 格式與欄位不變；錯誤訊息仍經 `_failure` 遮罩；已知 URL 的重複（`attempts=0`）路徑未動；`run_once`、`run_first_book`、`RunDependencies`、`format_report` 與 `parse_detail_html` 的公開介面都不變。

## 執行紀錄（Log）

1. 閱讀 `run.py`、`parsers.py`、`models.py`、`Docs/modules/crawler.md` §4–§6、`CONTEXT.md` 與既有測試，並盤點五種結果的既有測試覆蓋。
2. 基線：`pytest crawler/tests` → 280 passed（約 45 秒）。
3. 紅燈（TDD）：
   - 先新增 `test_restricted_book_error_is_not_a_parse_error_or_value_error`，在修改 class 之前執行，結果為 FAILED（`issubclass(RestrictedBookError, ParseError)` 為 True）。
   - 新增 `test_draft_validation_error_from_the_detail_parser_is_retried_as_parse_error` 與限制級的 INFO log 斷言。這兩項描述的是本次不得改變的行為，目前的程式已符合，因此直接通過（特徵測試），不屬於紅燈。
4. 修改 `parsers.py`（`RestrictedBookError` 的基底與 docstring、`ParseError` 與模組 docstring）→ 新測試轉為通過。
5. 修改 `run.py`：新增四個 outcome dataclass，改寫 `_fetch_and_parse`、`_write_new_source` 與 `_resolve_row` 的迴圈，刪除兩個例外類別。
6. 全套測試：282 passed（280 + 2 個新測試）。
7. `git diff --check` 通過，提交 `32f6faf`（程式、測試與 docstring 同一個 commit）。
8. 撰寫本報告並提交。

## 驗證結果

- `~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`：

  `282 passed in 37.43s`

  沒有 skip。DB 測試使用 Testcontainers 的一次性 PostgreSQL，測試不連線博客來。

### 設計要求 1–5 的對照

| # | 設計要求 | 結果 | 依據 |
|---|---|---|---|
| 1 | 兩個步驟都回傳分類結果；刪除 `_AttemptFailed` 與 `DuplicateBookInRankingError`；迴圈不再 catch；`parse_detail_html` 仍拋出 | 達成 | `run.py` 與 `crawler/` 內已無這兩個名稱的殘留；`parse_detail_html` 函式本體未改 |
| 2 | `RestrictedBookError` 為獨立 `Exception` 子類別，更新 docstring | 達成 | 新測試 `test_restricted_book_error_is_not_a_parse_error_or_value_error`（先紅後綠） |
| 3 | `ParseError` 與 `BookDraft` 驗證的 `ValueError` 仍為可重試的 `parse_error`，規則只寫在一處 | 達成 | `_fetch_and_parse` 的 `except ValueError` 分支與註解；行為由下表 (2)、(3) 的測試驗證 |
| 4 | 私有 dataclass 表示 outcome；可重試失敗使用既有 `models.Failure`；不改 `models.py` | 達成 | 四個私有 dataclass；`models.py` 未改動 |
| 5 | 修正 `parsers.py` 模組 docstring 與 `ParseError` docstring | 達成 | 兩處都改為「排行榜解析錯誤使 run 失敗；詳細頁解析錯誤重試後跳過（crawler.md §4、§6）」 |

### 五種結果與對應測試（run 介面）

| 結果 | 必須的行為 | 對應測試 | 狀態 |
|---|---|---|---|
| (1) 限制級頁面 → 不重試 | 只請求一次；`attempts` 為 1；無退避；`error_type=restricted_book`；INFO log | `test_db_integration.py::test_each_restricted_page_is_requested_once_and_leaves_a_gap`（`run_once`）；`test_first_book.py::test_restricted_first_book_skips_once_without_error`（`run_first_book`，本次補上 INFO log 斷言）；`test_e2e_real_fixtures.py::test_real_restricted_member_gate_is_skipped_once_and_leaves_a_gap`（真實 fixture） | 既有；log 斷言為本次補上 |
| (2) 詳細頁解析錯誤 → 重試並重新 request | 第一次解析失敗後重新 fetch；三次都失敗則 `parse_error`、`attempts=3` | `test_db_integration.py::test_detail_page_fetch_is_retried_when_the_parse_fails_at_first`；`test_e2e_real_fixtures.py::test_derived_new_source_without_title_is_retried_then_skipped_without_an_empty_book`；`test_e2e_real_fixtures.py::test_derived_new_source_without_product_container_is_retried_then_skipped` | 既有 |
| (3) `BookDraft` 驗證的 `ValueError` → 重試為 `parse_error` | 與 (2) 相同；錯誤訊息保留 `title is required` | `test_first_book.py::test_draft_validation_error_from_the_detail_parser_is_retried_as_parse_error` | 既有測試未覆蓋此路徑，本次新增 |
| (4) 資料庫寫入失敗 → 只重試寫入，不重新 request | 詳細頁只 fetch 一次；`database_error`、`attempts=3`；退避 1 秒、2 秒 | `test_db_integration.py::test_book_transaction_failing_twice_then_succeeding_writes_the_book_normally`；`test_db_integration.py::test_detail_page_is_fetched_once_when_database_writes_fail_three_times`；`test_db_integration.py::test_failed_book_transaction_is_rolled_back_retried_and_skipped_while_others_are_unaffected`；`test_first_book.py::test_import_only_first_book_and_retry_database_without_refetch` | 既有 |
| (5) 重複 Book（ISBN 命中先前排名的 Book）→ 不重試 | `attempts=1`；詳細頁只 fetch 一次；無退避；`duplicate_book_in_ranking`；不寫入 | `test_db_integration.py::test_existing_url_then_new_source_with_same_isbn_skips_the_later_rank`（斷言無退避）；`test_db_integration.py::test_two_new_sources_sharing_an_isbn_skip_the_later_rank`（斷言 `attempts == 1`、只 fetch 一次）；`test_db_integration.py::test_new_source_then_existing_url_for_same_book_skips_the_later_rank` | 既有 |

另外，既有的 `test_db_integration.py::test_browser_unavailable_on_a_detail_page_fails_the_run_without_retry_or_skip` 覆蓋未分類例外仍使 run 失敗的行為。

## 未解決事項

1. **分類的位置**：設計要求寫在「分類函式」中。實作把分類放在 `_fetch_and_parse` 的 `except ValueError` 分支，沒有另外抽出函式，因為獨立函式必須重新拋出未分類的例外，會讓控制流程更複雜。若使用者要求必須是獨立函式，再調整。
2. **已知 URL 的重複（`attempts=0`）**：此路徑未修改，但 run 層級的測試只斷言 `error_type`，沒有斷言 `attempts == 0`。超出本次五種結果的範圍，未補測試。
3. **Co-Authored-By 行**：任務指定為 Haiku 4.5，但執行環境的 attribution 規定為 Haiku 5.5（即實際執行的模型）。本次 commit 採用 Haiku 5.5，請使用者確認。
4. **歷史實作報告**：`issue-6-crawler-success-path.md` 與 `issue-7-crawler-retry-skip.md` 仍提到 `DuplicateBookInRankingError` 與 `_AttemptFailed`。這些是當時的紀錄，未修改。
5. 本次處理了 `refactor-run-ledger.md` 未解決事項 2 中 `run.py` 與 `parsers.py` docstring 的部分。
6. 未 push、未 merge、未操作其他 branch 或 worktree。
