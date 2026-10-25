# 實作報告：金石堂 crawler Phase 1 — 共用 Catalog core

> 實作紀錄，不是規格。規格以 `crawler/docs/*`（現行 authority）與 [v11 計畫](../plans/kingstone-category-crawler.md) §3、§5、§9 為準；待辦見 `crawler/docs/backlog.md` CB-07。

## 變更檔案

| 模組 | 分支／commit | 檔案 | 內容 |
|---|---|---|---|
| M1 core 型別 | `kingstone-p1-m1-core-models` `90b6096` | 新增 `crawler/catalog_core/{__init__,models,normalize}.py`；`git mv` `identity.py`、`unicode_15_1.py`；`books_crawler/{models,normalize,cli,db,run,parsers}.py`；`crawler/Dockerfile`、`.dockerignore`；`.github/scripts/unicode_tables.py`；測試 import | 共用型別（`ProviderCode` 加 `KINGSTONE`、`BookDraft`、`SourceRef`、`CatalogResolution` 等）、Source identity 矩陣、ISBN 正規化與 Unicode 15.1 表移到 `catalog_core`；`books_crawler.models` 重新匯出；image 納入 `catalog_core` |
| M2 persistence | `kingstone-p1-m2-persistence` `0274629` | 新增 `catalog_core/persistence.py`、`tests/test_persistence_integration.py`；`books_crawler/{db,run,cli}.py`；`catalog_core/models.py`；DB／run 測試 | 所有查詢與寫入明確傳入 provider；`BookDraft.external_id` 寫入 `book_sources`；touch 改為 `GREATEST(last_seen_at, observed_at)` 並限定 `source_code`，0 列丟出 `SourceTouchConflict`；`db.py` 只剩 Bestseller 替換 |
| M3 service | `kingstone-p1-m3-service` `173eaf9` | 新增 `catalog_core/service.py`、`tests/test_catalog_service.py` | `resolve_item`：identity → touch 或抓詳細頁 → ISBN → persist；共用嘗試次數、寫入結果不確定時先重新查 identity；以 `CatalogStore` port 與 `fetch_draft` callback 隔離 DB 與 HTML |
| M3b 接線 | `kingstone-p1-m3b-wire-books` `c9c7d4d`（含 merge M2 `8ddd09f`） | `git mv` `session.py` 到 `catalog_core`；新增 `catalog_core/store.py`；`books_crawler/run.py`；`catalog_core/service.py` | 博客來 `_resolve_row` 改為 service 的 adapter；`SessionCatalogStore` 把 `SourceTouchConflict` 轉成 `False`；`ItemFailed` 帶 identity warning |
| M4 review 與報告 | `kingstone-p1-m4-report` `13559d2`、本報告 commit | `catalog_core/{session,persistence}.py`、`books_crawler/run.py`、兩個新測試、`crawler/docs/*`、本報告 | 兩軸 review 修正、CB-07 狀態與後續待辦 |
| 文件 | 各模組 | `crawler/docs/{architecture,workflow-diagram,test-suite,backlog,update-history}.md` | 架構表新增 `catalog_core` 各模組；共用單列管線改指向 service；CR-T16（單調 touch 與 provider 隔離）、CR-T17（共用 item 解析 service） |

## 實作思路

- **先抽 core，再接 provider**：金石堂要重用的是 identity、ISBN、persistence 與單本解析流程。把它們抽成 `catalog_core` 並讓博客來先改走同一條路，金石堂之後只需要寫 adapter（清單、parser、acquisition），不必複製 core。
- **M2 與 M3 並行**：使用者要求能並行就並行。M2 與 M3 都依賴 M1，而且原本都要改 `run.py`。做法是讓 M3 只新增 `service.py`，依賴一個 `CatalogStore` Protocol（`touch_source` 回傳 `bool`），用 fake 做單元測試；兩邊完成後再由 M3b 接線，把 `SourceTouchConflict` 轉成 `False`。兩個分支不共用新檔案，merge 沒有衝突。
- **博客來行為只變 touch**：touch 改為單調並確認 provider，是計畫 §5 的要求。其餘流程（嘗試次數、哪種錯誤會重新查 identity、restricted、conflict、log 文字）都逐項對照舊 resolver 保持一致。
- **identity warning 在查詢當下記錄**：舊程式在 touch 之前記 URL 漂移 warning；若改成依回傳值事後記錄，會排到 touch 的失敗行之後。所以博客來用 `_BooksCatalogStore` 在 identity 查詢時記錄。博客來沒有 `external_id`，實際上不會產生這個 warning；`identity_warning` 欄位留給金石堂。
- **失敗原因用 `str`**：service 只擁有 `database_error`、`source_identity_conflict` 兩個原因；抓取與解析的失敗詞彙屬於各 provider（博客來的 `SkipReason`），由呼叫端轉回自己的 enum。這是刻意的邊界，review 標為 Primitive Obsession 的判斷題，保留。

## 執行紀錄（Log）

- 程式由 Haiku subagent 依 TDD 撰寫，每個模組完成後由主 agent 讀程式、重跑完整測試。
- M1 subagent 順手把 `deploy/migration-test/prev_crawler_driver.py` 改成 `from catalog_core.identity`。這支 driver 在 v0.0.6 的舊 crawler image 內以 `PYTHONPATH=/app/crawler` 執行，舊版沒有 `catalog_core`，會讓 gate 9 在 import 時失敗。主 agent 還原該行並 amend 進 M1。
- M1 另外修了 `.dockerignore`（不加 `!catalog_core/` 時 build context 不含新套件）與 `cli.configure_logging`（同時設定 `catalog_core` logger，維持 identity 的 INFO 輸出）。
- M2、M3 並行；M3b 從 M3 分支開出並 merge M2；M4 接在 M3b 之後。
- 期間使用者回報博客來 crawler 寫入本機 DB 失敗。查證後是本機 Docker PostgreSQL 停在 009，不是 crawler 問題；依使用者決定以 `dotnet ef database update` 升級到 011（ISBN_13 3,046 筆轉為 `ISBN`、Source 3,270 筆不變）。未改程式。

## 驗證結果

- 每個模組完成後主 agent 重跑 crawler 完整 pytest（含 DB integration，0 skip）：M1 19,717；M2 19,727；M3 19,742；M3b 19,753；M4 19,755 passed。
- `ruff check`、`ruff format --check`、`.github/scripts/unicode_tables.py --check`（3 個檔案）每次都通過。
- 新測試：
  - CR-T16：較晚時間前進、較早時間不倒退、重複 touch 冪等、provider 不符與 Source 不存在丟出衝突且不改資料、KINGSTONE 的 `external_id` 寫入、同 URL 的 provider 隔離、博客來 run 層級時鐘倒退、touch commit 後確認遺失的重試冪等、touch 衝突以 `source_identity_conflict` 跳過且不重試。
  - CR-T17：service 單元測試 26 個，涵蓋每個分支。
- 未執行：`dotnet build`／`dotnet test`（本次未改 .NET 或 schema）、Docker image build、真站抓取、部署。

## 未解決事項

- 見 CB-07「Phase 1 留下的待辦」：`identity_warning` 由金石堂使用；移除 `books_crawler.models` 的相容匯出；Phase 5 加入 `new-books-only` 政策。
- 博客來第二個可見變化：Source 在 touch 時已不存在（0 列）時，以前會回報 EXISTING，之後在榜單替換的 source ownership 驗證讓整次 run 失敗；現在當場以 `source_identity_conflict` 跳過該列。符合計畫 §5「確認恰為預期 provider Source」，已寫入 architecture 與 workflow-diagram。

## Code Review 與修正

兩軸 review（Standards、Spec）對 `origin/main...HEAD` 執行，主 agent 逐項查證後在 `13559d2` 修正：

| 軸 | 發現 | 處理 |
|---|---|---|
| Standards | `catalog_core/session.py` 的 logger 名仍是 `books_crawler.session` | 改為 `catalog_core.session`（`cli` 已設定 `catalog_core` logger） |
| Standards | `persistence.py` docstring 說決策在 `run` | 改為 `catalog_core.service` 與 `identity` |
| Standards | test-suite 中 CR-T17 排在 CR-T16 之前 | 調整順序 |
| Standards | `_BooksCatalogStore` docstring 寫歷史；ISBN 字串重複 join | docstring 只描述現況；恢復單一 `isbn_text` |
| Standards | `identity_warning` 沒有 production 讀者；`books_crawler.models` 重新匯出 | 記入 CB-07 待辦 |
| Standards | `reason` 用 `str`；SQL f-string | 保留：前者是 provider 詞彙邊界，後者是原樣搬移、只插入固定欄位名 |
| Spec | touch 缺少「commit 後確認遺失」測試（計畫 §5） | 新增 `test_a_touch_commit_whose_acknowledgement_is_lost_is_idempotent_on_retry` |
| Spec | 博客來 run 層級缺少時鐘倒退測試 | 新增 `test_a_clock_moved_back_keeps_a_later_last_seen_and_the_source_is_still_existing` |
| Spec | `catalog_core/session.py`、`store.py` 不在 §3 列表 | 接受：是 port 的 adapter，不含 provider HTML，已寫入 architecture |
