# 重構實作報告：在替換榜單的 transaction 內驗證 Bestseller snapshot

- 來源：2026-10-11 架構檢視的候選 2「在同一個 transaction 裡驗證並發布 Bestseller snapshot」
- Issue：無（純重構，使用者決定不開 issue）
- Branch：直接在 `main`（使用者決定）
- 實作：主 session 以 TDD 直接實作
- 日期：2026-10-11

## 背景

`ranking.validate_snapshot` 是為了好測而抽出的 pure function，但 caller（`run_once`）必須先用 `db.booksdotcom_source_books` 查資料庫、再從 ledger 取出限制級排名傳進去。這個查詢在 autocommit 下執行，不在寫入的 transaction 裡。它檢查的五條規則中：

| 規則 | 實際由誰保證 |
|---|---|
| R1 筆數 ≤ 100 − 限制級數 | `RunLedger`：rank 嚴格遞增，限制級排名不進 snapshot |
| R2 限制級排名在範圍內、不重複、不在 snapshot | `RunLedger`（同上） |
| R3 rank 在 1～100 且不重複 | 排行榜驗證（§4）；schema 的 `ck_bestsellers_rank` 與 rank 主鍵 |
| R4 `book_id` 不重複 | `RunLedger` 的 invariant；schema 的 unique index |
| R5 `source_id` 必須是同一本 Book 的博客來來源 | **只有 `validate_snapshot`** |

## 設計決定（使用者逐題確認）

| # | 決定 |
|---|---|
| Q1 | R1～R4 不再重複檢查，交給 `RunLedger` 與 schema；違反 schema 時 transaction rollback，舊榜單保留，run 為 FAILED |
| Q2 | R5 在 `replace_bestsellers` 自己的 transaction 內、DELETE 之前查詢並檢查；錯誤訊息指出 rank。不用 `INSERT … SELECT` 比對筆數，也不改 schema |
| Q3 | 沿用 `db.replace_bestsellers(conn, rows, captured_at)` 這個名稱 |
| Q4 | 主 session TDD、雙軸 review、commit 在 `main`；報告為本檔 |
| Q5 | 刪除 `ranking.validate_snapshot` 與其 helper、`db.booksdotcom_source_books`、`RunLedger.restricted_ranks`；`SnapshotValidationError` 搬到 `db.py`，名稱與訊息格式不變；`run_once` 發布縮成一行 |
| Q6 | 刪除 `test_ranking.py` 的 snapshot 測試；新增三個直接呼叫 `replace_bestsellers` 的 DB 測試；保留「INSERT 中途失敗會 rollback」的測試；`test_ledger.py` 改看 `report.skipped` |
| Q7 | `crawler.md` §10 改為單一 transaction 的流程，並說明其他條件由誰保證 |

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/books_crawler/db.py` | 修改 | 新增 `SnapshotValidationError`；`replace_bestsellers` 在 transaction 內先檢查 R5 再替換；刪除 `booksdotcom_source_books`；模組 docstring 說明這條例外 |
| `crawler/books_crawler/ranking.py` | 修改 | 只保留排行榜驗證：刪除 `validate_snapshot`、`SnapshotValidationError`、`_has_unique_ranks_in_range` |
| `crawler/books_crawler/run.py` | 修改 | 發布改為 `db.replace_bestsellers(conn, ledger.snapshot, captured_at=deps.clock())` |
| `crawler/books_crawler/ledger.py` | 修改 | 刪除 `restricted_ranks` |
| `crawler/tests/test_db_integration.py` | 修改 | 新增 R5 的三種拒絕情況與空 snapshot 測試；「INSERT 中途失敗」改用重複 `book_id` 觸發 |
| `crawler/tests/test_ranking.py` | 修改 | 刪除 snapshot 測試（18 個案例，含參數化展開） |
| `crawler/tests/test_ledger.py` | 修改 | 限制級排名改從 `report.skipped` 取得 |
| `Docs/modules/crawler.md` | 修改 | §10 改寫；§3 流程圖的驗證節點改為在替換 transaction 內 |
| `Docs/data/data-model.md` | 修改 | bestsellers 一節的替換說明改為「在 replace 的同一 transaction 內驗證」 |

## 實作思路

- **一個 operation**：`replace_bestsellers` 先 `SELECT id, book_id FROM book_sources WHERE source_type = 'BOOKS_COM_TW' AND id = ANY(...)`，逐列比對；任何一列不符就在 DELETE 之前拋出 `SnapshotValidationError`。因為在同一個 `conn.transaction()` 裡，拋出會 rollback，舊榜單與 `last_seen_at` 都不變。
- **不重複的規則**：R1～R4 已由 `RunLedger` 與 schema 保證，不在 replace 時再檢查。
- **對外不變**：錯誤類別名稱與訊息格式與原本相同，run log 的 `error=` 看起來一樣。唯一差異：重複 `book_id` 的錯誤從 `SnapshotValidationError: snapshot book_id must be unique` 變成 schema 的 `UniqueViolation`，run 一樣是 FAILED、榜單不變；而且 `RunLedger` 讓這種情況在正常流程中不會發生（Q1 已接受）。

## 執行紀錄（Log）

1. 讀 `crawler.md` §10、`validate_snapshot` 與其測試、`replace_bestsellers`、bestsellers 與 book_sources 的 schema；整理出 R1～R5 的保證來源。
2. 兩輪 grilling（Q1～Q7），使用者全部採用建議。
3. 先寫三個 R5 的 DB 測試（紅：`SnapshotValidationError` 不在 `db`），再實作 `replace_bestsellers` 的檢查。
4. 刪除 `validate_snapshot`、`booksdotcom_source_books`、`restricted_ranks` 與 snapshot 測試，`run_once` 改用新的發布方式。
5. 原本以「不存在的 Book」觸發 INSERT 失敗的測試，現在會先被 R5 擋下；改用重複 `book_id`，讓它通過來源檢查後在第 50 列違反 schema。
6. 改寫 `crawler.md` §10；雙軸 code review 後修正（見下節）。

## 驗證結果

- `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`：**265 passed**，沒有 skip（Testcontainers 的 disposable PostgreSQL，不連線博客來）。
- 測試數量：原 279 − snapshot 測試 18 + R5 測試 3 + 空 snapshot 測試 1 = 265。
- `git diff --check` 通過；import 檢查只剩 HEAD 原有的 `test_playwright_fetcher.py:588`。

| 設計要求 | 結果 | 對應測試 |
|---|---|---|
| source 屬於另一本 Book → 拒絕，舊榜單與 `last_seen_at` 不變 | ✅ | `test_replacement_rejects_a_source_that_is_not_the_books_own_books_com_tw_source[another_books_source]` |
| source 是同一本書的 Google Books 來源 → 拒絕（驗到來源類型） | ✅ | 同上 `[google_books_source]` |
| source id 不存在 → 拒絕 | ✅ | 同上 `[missing_source]` |
| INSERT 中途失敗（schema 的 `book_id` unique）→ rollback | ✅ | `test_failed_snapshot_replacement_keeps_previous_list_and_last_seen` |
| 沒有最低筆數：空 snapshot 也替換 | ✅ | `test_an_empty_snapshot_still_replaces_the_list` |
| 完整 run 的發布、中止不發布、限制級缺號 | ✅ | 既有的 DB 與真實 fixture 整合測試全部通過 |

## Code Review 與修正

雙軸審查（Standards、Spec）平行執行，兩軸都沒有違規或實作錯誤；主 session 核對後處理以下項目：

| 軸 | 發現 | 處理 |
|---|---|---|
| Spec | 刪掉 size=0 的 snapshot 測試後，沒有 DB 層測試證明「沒有最低筆數」 | 新增空 snapshot 測試 |
| Spec | §10 只寫 rank 範圍由 schema 保證，漏了排行榜驗證 | 補上 §4；`book_id` 也寫明 `RunLedger` 與 schema 兩層 |
| Standards | §10 的「不設最低筆數」沒寫由誰負責；和 `last_seen_at` 清單黏在一起 | 寫明「`RunLedger` 與 replace 都不設下限」；`last_seen_at` 清單加上標題 |
| Standards | `db.py` docstring 寫「schema cannot express」太強 | 改為「the schema does not enforce」，並寫出是哪條規則 |
| Standards | `[row.source_id for row in rows]` 算兩次 | 抽成 `source_ids` |
| Standards | §3 流程圖的「Snapshot valid?」畫在替換之前 | 改為在替換 transaction 內驗證 |
| Standards | `data-model.md` 仍寫「通過驗證後才能 transaction replace」 | 改為在 replace 的同一 transaction 內驗證 |
| Standards | 測試同時 import `db` 與 `db.SnapshotValidationError` | 改用 `db.SnapshotValidationError` |
| Standards | `SnapshotValidationError` 名稱比語意寬；db 開始承擔一條業務規則 | 保留：名稱不變可讓 run log 維持一致；docstring 已寫明這是唯一例外 |
| Standards | 參數化測試內用 `if case == …` 分支 | 保留：三個情況只差在準備資料，拆開會重複大部分斷言 |

修正後重跑：**265 passed**；`git diff --check` 通過。

## 未解決事項

1. **R5 仍是應用層檢查**：若日後有其他程式寫入 `bestsellers`，需要經過 `replace_bestsellers` 才會受到保護。要讓資料庫本身強制，需要 composite FK 加來源類型的設計與 EF migration（Q2 選擇不做）。
2. **重複 `book_id` 的錯誤文字**：會顯示 schema 的 `UniqueViolation`，而不是原本的 `SnapshotValidationError` 訊息。正常流程中 `RunLedger` 會先擋下，不會發生。
