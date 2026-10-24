# Crawler 優化與 debug 待辦

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。核心來源依原始基準靜態閱讀；host 另依上述 merge-target snapshot；本次未執行 build、測試、部署、外部服務或真實抓取。

未執行重現；未宣稱已重現 bug。待辦不構成外部操作授權。

## CB-01 — pages 新來源時間語意

- P1；L3（若改資料契約）；狀態：規格已決策（#113），待 PR3 實作。#113 的 [crawler §6.1、§15.1](../../Docs/modules/crawler.md) 改為：分類榜的 Existing Source 看到即 touch `last_seen_at`，新來源寫 `first_seen_at = last_seen_at = now`。以下證據描述 #113 前的字面差距。
- 證據：#113 前的 crawler §16.9 宣告包含附加來源也不寫 last_seen_at；[db._insert_source](../books_crawler/db.py) 明確 INSERT first_seen_at、last_seen_at=now，[run_pages](../books_crawler/run.py) 共用此路徑。
- 影響：可能誤刪建檔必要欄位，或把初始化誤認為每日刷新。方向：先確認 authority 是否意指「不更新既有來源」。不得直接改 nullability。
- 前置決策：資料契約與產品同意初始化／刷新語意。驗收：authority 清楚區分，三種新建／附加／重用的 DB 斷言一致；若改行為同步 schema 與 caller。
- 測試入口：[test_run_pages.py](../tests/test_run_pages.py)、[test_db_integration.py](../tests/test_db_integration.py)；CR-T08。

## CB-02 — 診斷產物容量與保留期限

- P2；L2；狀態：改善提案。
- 證據：[save_failure_diagnostics](../books_crawler/fetcher.py) 每次失敗新增 artifact、沒有清理；[deployment §8](../../Docs/deployment/deployment.md) 明示另管保留，logrotate 只管 host logs。
- 成本量測：每日檔案數、bytes、最舊時間與調查窗口；未證明已磁碟滿。方向：決定天數／容量／權限與保留例外，再新增 cleanup 作業。
- 前置決策：可刪時間與調查證據保留。驗收：disposable 目錄清理舊檔、保留近期／例外，失敗可觀測，無 cookie／secret 輸出。
- 入口：[test_fetcher.py](../tests/test_fetcher.py)、[test_playwright_fetcher.py](../tests/test_playwright_fetcher.py)；CR-T11，cleanup 測試待建。

## CB-03 — 排程啟用前正式環境驗證

- P1；L4；狀態：待驗證。
- 證據：[deployment §8](../../Docs/deployment/deployment.md) 要求 EC2 手動抓取驗證後才啟用；[test_deploy.py](../tests/test_deploy.py) 是替身測試，不能代表 SSM／IAM／EC2／來源成功。
- 前置：當前任務 production／真實抓取授權，EF schema、image 預載（--pull=never）、專用 SSM secret、host 時區與權限。
- 方向與驗收：依 [部署操作](../deploy/README.md) 留存去識別 status／exit／可解析證據，確認 UTC cron、72 小時狀態與失敗不前移、舊榜保護。另依 [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) 與 [target deployment §8](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/deployment/deployment.md) 查核 host 與 crawler 使用相同 maintenance lock 路徑：先取 shared lock 再讀 state、容器期間持鎖、paused／dirty exit6、wait timeout exit3、無法解析 state exit2、absent state 保留相容行為。CR-T12-B 的現有替身案例只是 source 證據，不能替代此 L4 環境驗證。challenge 阻擋則不啟用；rollback 為停用該 cron 並保留現有榜單，不採規避技術。
- 入口：[wrapper](../deploy/run-crawler.sh)；CR-T12、CR-T13。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。

## CB-04 — Multi-source Catalog：provider code 與 ISBN 比對（#113 PR3）

- P1；L3；狀態：確認缺口（目標規格已定，未實作）。
- 目標：[crawler §6.3、§7.2](../../Docs/modules/crawler.md) 與 [data-model §7.1～§7.4](../../Docs/data/data-model.md)：只用 `source_code`（不讀寫 010 的 `source_type`）；ISBN 依 Unicode 15.1 NFKC → 刪 U+002D 與 Unicode 15.1 White_Space → ASCII 大寫正規化，存成 `ISBN`，不驗證 checksum；以 draft 所有 ISBN 查 distinct Book（三種類型），0 建立、1 附加並補 NULL、≥ 2 ambiguous 建立；source identity 衝突與 URL 漂移；disabled provider exit 2。
- 目前差距：[models](../books_crawler/models.py) 有 `SourceType`；[normalize](../books_crawler/normalize.py) 驗證格式與 checksum 並分成 ISBN_10／13；[db.find_book_by_isbn](../books_crawler/db.py) 以 `fetchone()` 依 ISBN_13 → ISBN_10 取第一筆；附加時不補 NULL。
- 前置：PR2 的 migration 010 已部署（同一 release tag）；共用 fixture `tests/Fixtures/isbn-normalization.json` 由 PR2 建立。
- 驗收：[test-plan §7](../../Docs/testing/test-plan.md) #1～#4、#15、#18、#19 通過；pytest 讀共用 fixture 與 C# 逐 byte 一致。
- 測試入口：[test_normalize.py](../tests/test_normalize.py)、[test_db_integration.py](../tests/test_db_integration.py)；新案例待建。

## CB-05 — 兩層 outcome、計數與 last_seen_at touch（#113 PR3）

- P1；L3；狀態：確認缺口（目標規格已定，未實作）。
- 目標：[crawler §3.5、§6.1、§10.2、§14.2～§14.4、§19.2](../../Docs/modules/crawler.md)：`CatalogResolution` 與 `RankingDecision` 分層；連續錯誤只由 `RankingDecision` 決定；榜內重複時 Catalog 照常 commit；Existing Source 在 discovery 時以獨立 transaction touch，touch 失敗依各模式 policy；`replace_bestsellers` 不再更新 `last_seen_at`；log 新增 `provider_code`、`job_name`、`items_seen`、`existing_source_count`、`new_source_count`、`ambiguous_isbn_count`、`offer_updated_count`。
- 目前差距：[run.py](../books_crawler/run.py) 的 `_DuplicateBook` 在寫入前就跳過重複；[ledger](../books_crawler/ledger.py) 只有單層 `Resolution`，`Existing` 一律重設計數；[db.replace_bestsellers](../books_crawler/db.py) 在 snapshot transaction 內更新 `last_seen_at`；pages 與 first_book 不更新既有來源；程式 docstring 的 `crawler.md §…` 仍是舊編號。
- 驗收：[test-plan §7](../../Docs/testing/test-plan.md) #5～#7、#11、#17 通過；CRAWL-05 的 ledger 測試改依 RankingDecision；`crawler/docs/*` 與 `crawler/README.md` 同步（plan §2 docs-sync 規則）。
- 測試入口：[test_ledger.py](../tests/test_ledger.py)、[test_pages_ledger.py](../tests/test_pages_ledger.py)、[test_run_unit.py](../tests/test_run_unit.py)、[test_run_pages.py](../tests/test_run_pages.py)、[test_first_book_integration.py](../tests/test_first_book_integration.py)。

## CB-06 — 只查 `ISBN` 類型（#113 PR4）

- P2；L3；狀態：確認缺口（依賴 migration 011）。
- 目標：011 之後 crawler 刪除 `ISBN_10`／`ISBN_13`，distinct 查詢只用 `identifier_type = 'ISBN'`（[data-model §7.2](../../Docs/data/data-model.md)）。
- 前置：011 gate 全部通過（[data-model §11.3](../../Docs/data/data-model.md)），包括 PR3 crawler 在 011 上的相容性測試。
- 驗收：PR4 的 crawler 測試只建立與查詢 `ISBN`；PR3 crawler 在 011 schema 上的 smoke（Existing Source touch、ISBN 查詢、新 Source、Bestseller 替換）通過。

