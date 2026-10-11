# 實作報告：分類榜補書模式（Pages mode）

- 來源：使用者決策（2026-10-11 起的產品決定）：分類 7 日榜只用來補充 Catalog 的新書，不是 Bestseller
- Issue：無
- Branch：`crawler-pages-config`（worktree，由 `main` 分出）
- Commits：`c15756c`（使用者先前提交，引入 pages mode）、`1f44c93`（分類頁清單檔）、`10da061`（PagesLedger 與設定檔清單）
- 實作：Claude Haiku（subagent）
- 日期：2026-10-12

## 變更檔案

| 檔案 | 變更 |
|---|---|
| `crawler/books_crawler/ledger.py` | 新增 `PagesLedger`；`RunReport` 新增選填的 `pages_total`、`rows_seen`、`skipped_pages`；兩個 ledger 共用 `_status()`、`_book_counts()` |
| `crawler/books_crawler/run.py` | `run_pages(deps, page_urls)` 改用 `PagesLedger`；分類頁失敗改為跳過；`format_report` 依模式輸出欄位；移除 `ImportReport` 與 `urls.PAGE_URLS` 的使用 |
| `crawler/books_crawler/models.py` | 新增 `SkippedPage`；移除 `ImportReport` |
| `crawler/books_crawler/page_list.py` | 新增：解析 `category-pages.txt`（或 `CRAWLER_PAGES_FILE`），去除註解、空行與重複 URL，驗證格式 |
| `crawler/books_crawler/urls.py` | 移除寫死的 `PAGE_URLS`；新增 `is_category_ranking_url` 驗證分類榜 URL 形式 |
| `crawler/books_crawler/cli.py` | 以 `CrawlerMode` StrEnum 取代兩個 bool 參數；pages 模式在建立 fetcher 前驗證清單（不合法 → exit 2） |
| `crawler/books_crawler/pages.py` | 入口改為 `main(mode=CrawlerMode.PAGES)` |
| `crawler/books_crawler/first_book.py` | 配合 `CrawlerMode` 的呼叫方式調整 |
| `crawler/category-pages.txt` | 新增：預設分類頁清單（21 個分類頁） |
| `crawler/tests/test_pages_ledger.py`、`test_page_list.py`、`test_urls.py`、`test_run_pages.py`、`test_first_book.py` | 新增與改寫測試 |
| `Docs/modules/crawler.md` | 新增 §16；§1、§2、§4、§6、§11、§12、§15.1 加入指向 §16 的說明 |
| `crawler/README.md`、`Docs/deployment/deployment.md`、`Docs/requirements/product-requirements.md`、`CONTEXT.md` | 文件同步（指令、環境變數、需求延後項目、術語） |

## 實作思路

- **不是 Bestseller**：分類榜不替換 `bestsellers`，也不更新 `last_seen_at`，因此不沿用 `RunLedger`。`RunLedger` 的排名順序、snapshot、榜內重複 Book 與連續錯誤中止規則都不適用於分類榜，硬用會讓兩種規則互相干擾。
- **`PagesLedger` 與 `RunLedger` 分開**：兩者只共用 `_status()`（任何錯誤 → FAILED，有跳過 → PARTIAL_SUCCESS）與 `_book_counts()`。
- **分類頁失敗跳過**：抓取重試 3 次仍失敗（`fetch_error`）或解析失敗（`parse_error`，不重試，attempts = 1）時跳過該頁，繼續下一頁。
- **列規則沿用每日 run**：每列套用 §5 Book resolution、§6 的 3 次嘗試與限制級跳過，但不套用榜內重複規則與連續錯誤中止。
- **FAILED 的界線**：列處理中有例外逸出（例如既有 URL 查詢的資料庫錯誤）、browser 無法啟動，或所有分類頁都被跳過。寫入新書時的資料庫錯誤仍依 §6 重試後跳過該列。
- **清單驗證**：在任何請求前完成；不合法 → exit 2。URL 須為 `https://www.books.com.tw/web/sys_saletopb/books/NN/`，`attribute=7`，query 只允許 `attribute` 與 `loc`。
- **CLI 模式**：`CrawlerMode`（`daily`、`first-book`、`pages`）取代兩個 bool 參數，避免非法組合。

## 執行紀錄（Log）

以下為 log 格式範例（欄位順序與 `format_report` 相同），數值為示意，**不是一次實際執行**。本次工作只以測試驗證，未對博客來發出真實請求。

```text
INFO  importing page: https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002
WARNING category page skipped after 3 attempt(s) (fetch_error): <url>: ...
WARNING page rank 4 (<product url>) skipped after 3 attempt(s) (parse_error): ...
INFO  mode=pages run_id=<uuid> started_at=... finished_at=... status=PARTIAL_SUCCESS pages_total=21 pages_skipped=1 rows_seen=... existing_book_count=... new_book_count=... attached_source_count=... skipped_count=... restricted_book_count=... error_count=... exit_code=0 skipped=[...] skipped_pages=[{"url": "...", "error_type": "fetch_error", "error_message": "...", "attempts": 3}]
```

- 失敗時另有一行 ERROR：`pages import failed: <error>`，並在 `mode=pages` 行加上 `error=`。
- 設定錯誤（exit 2）時只記一行 ERROR，說明檔案與行號，不發出請求。
- 不記錄 `ranking_count`、`consecutive_error_count`、`aborted_at_rank`。

## 驗證結果

- `crawler` 目錄執行 `pytest`（於 WSL 的 `.venv`）：**362 passed**（2026-10-12 重新執行；實作前為 318 passed）。
- 測試不連線博客來，使用 fake fetcher 與 HTML fixtures。
- 測試流程注意：`PagesLedger` 的 10 項測試與 `run_pages` 測試改寫是批次撰寫，未逐項紅綠循環（與 TDD 流程的偏差）。
- 文件：`crawler.md` §16 的 §號引用已全數檢查，既有章節未重新編號。

## 未解決事項

1. **Crawler Dockerfile 缺失**：repo 目前沒有 crawler Dockerfile，因此 `crawler/category-pages.txt` 是否會隨 image 一併打包，尚未驗證（見 `deployment.md` §8）。
2. **分類榜補書的排程未定義**：crontab 目前只含每日完整 run。
3. **真實網站驗證未做**：分類頁的實際解析與 Cloudflare 行為需在 EC2 上另行授權後驗證。
4. **Commit `10da061` 未再拆分**：其中各部分互相依賴（ledger、run、cli 與測試需同時變更），拆分會造成中間 commit 無法通過測試。
