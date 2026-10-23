# Crawler 優化與 debug 待辦

> 查核 2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。依當前工作樹靜態閱讀；本次未執行 build、測試、部署、外部服務或真實抓取。

未執行重現；未宣稱已重現 bug。待辦不構成外部操作授權。

## CB-01 — pages 新來源時間語意

- P1；L3（若改資料契約）；狀態：確認缺口（字面規格差距）。
- 證據：[crawler §16.9](../../Docs/modules/crawler.md) 宣告包含附加來源也不寫 last_seen_at；[db._insert_source](../books_crawler/db.py) 明確 INSERT first_seen_at、last_seen_at=now，[run_pages](../books_crawler/run.py) 共用此路徑。
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
- 方向與驗收：依 [部署操作](../deploy/README.md) 留存去識別 status／exit／可解析證據，確認 UTC cron、72 小時狀態與失敗不前移、舊榜保護。challenge 阻擋則不啟用；rollback 為停用該 cron 並保留現有榜單，不採規避技術。
- 入口：[wrapper](../deploy/run-crawler.sh)；CR-T12、CR-T13。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
