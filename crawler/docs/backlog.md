# Crawler 優化與 debug 待辦

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。
> backlog 整理（2026-10-25）補記：CB-01、CB-04、CB-05、CB-06 已完成，移至文末「已處理」；CB-03 補記 schema 與 production 狀態。核心來源依原始基準靜態閱讀；host 另依上述 merge-target snapshot；本次未執行 build、測試、部署、外部服務或真實抓取。

未執行重現；未宣稱已重現 bug。待辦不構成外部操作授權。

## CB-02 — 診斷產物容量與保留期限

- P2；L2；狀態：改善提案。
- 證據：[save_failure_diagnostics](../books_crawler/fetcher.py) 每次失敗新增 artifact、沒有清理；[deployment §8](../../Docs/deployment/deployment.md) 明示另管保留，logrotate 只管 host logs。
- 成本量測：每日檔案數、bytes、最舊時間與調查窗口；未證明已磁碟滿。方向：決定天數／容量／權限與保留例外，再新增 cleanup 作業。
- 前置決策：可刪時間與調查證據保留。驗收：disposable 目錄清理舊檔、保留近期／例外，失敗可觀測，無 cookie／secret 輸出。
- 入口：[test_fetcher.py](../tests/test_fetcher.py)、[test_playwright_fetcher.py](../tests/test_playwright_fetcher.py)；CR-T11，cleanup 測試待建。

## CB-03 — 排程啟用前正式環境驗證

- P1；L4；狀態：待驗證（2026-10-25 整理時 production 仍為 `CRAWLER_ENABLED=false`，博客來封鎖 EC2 IP，見 DEP-B01）。
- 證據：[deployment §8](../../Docs/deployment/deployment.md) 要求 EC2 手動抓取驗證後才啟用；[test_deploy.py](../tests/test_deploy.py) 是替身測試，不能代表 SSM／IAM／EC2／來源成功。
- 前置：當前任務 production／真實抓取授權，EF schema（011 已於 v0.0.7 套用）、image 預載（--pull=never）、專用 SSM secret、host 時區與權限。
- 方向與驗收：依 [部署操作](../deploy/README.md) 留存去識別 status／exit／可解析證據，確認 UTC cron、72 小時狀態與失敗不前移、舊榜保護。另依 [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) 與 [target deployment §8](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/deployment/deployment.md) 查核 host 與 crawler 使用相同 maintenance lock 路徑：先取 shared lock 再讀 state、容器期間持鎖、paused／dirty exit6、wait timeout exit3、無法解析 state exit2、absent state 保留相容行為。CR-T12-B 的現有替身案例只是 source 證據，不能替代此 L4 環境驗證。challenge 阻擋則不啟用；rollback 為停用該 cron 並保留現有榜單，不採規避技術。
- 入口：[wrapper](../deploy/run-crawler.sh)；CR-T12、CR-T13。

## CB-07 — 金石堂分類頁 crawler（v11）

- P2；L3；狀態：E0 完成（2026-10-25），程式未實作。
- 決定（使用者 2026-10-25）：比照博客來分類榜，由使用者在 `crawler/kingstone-pages.txt` 提供金石堂分類列表頁；每個 URL 只抓那一頁、不跟分頁；不探索分類樹；沒有跨 run 進度狀態檔，靠 replay＋Source identity 推進；`HTTP_ONLY`；請求間隔 3～10 秒。來源契約見 [architecture](architecture.md)「金石堂 source contract」。
- 證據：[kingstone fixtures](../tests/fixtures/kingstone/README.md)（13 份）與 CR-K01。
- 待做：Phase 1～7 依 [v11 計畫](../../Docs/plans/kingstone-category-crawler.md) §9：共用 core（含單調 touch，會改變博客來的 touch 行為）、清單與 parser、acquisition、逐頁 run 與 budget、ingestion、runner／fencing／alert、acceptance。
- 前置決策（Phase 6）：host `CRAWLER_ENABLED` 是全域開關，production 目前為 `false`（CB-03），金石堂是否用獨立開關；清單檔隨 image 發布或由 host mount。
- 未覆蓋：E0 沒有觀察到 challenge、CAPTCHA、限制級頁、429／5xx、無 ISBN 的書；出現時先收錄 fixture。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。

## 已處理

- **CB-01**（#113 PR3，PR #119）：pages 新來源寫入 `first_seen_at = last_seen_at = now`；Existing Source 看到即 touch `last_seen_at`。證據：`861c334`（phase B）、`0149b69`、`448571e`（phase A）；實作位於 `db._insert_source` 與 `run.py`。
- **CB-04**（#113 PR3，PR #119）：只用 `source_code`；ISBN 依 §7.1 正規化並以共用 fixture 驗證；以 distinct Book 0／1／≥2 判斷；disabled provider 以 exit 2 拒絕。證據：`861c334`。
- **CB-05**（#113 PR3，PR #119）：`CatalogResolution` 與 `RankingDecision` 分層；既有 Source 獨立 transaction touch；重試與 first_book 行為。證據：phase A `0149b69`、`448571e`、`ad82318`、`fb707de`；phase B `861c334`。
- **CB-06**（#113 PR4，PR #123）：`IdentifierType` 只剩 `ISBN`，`find_books_by_isbn` 只查 `ISBN`。證據：`f92a63d`（M2），依賴 migration 011 `5052361`。
