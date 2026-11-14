# scripts/categories 待辦

> 建立：2026-11-14，分類計畫 P2。

| ID | 優先／風險 | 內容 | 驗收 |
|---|---|---|---|
| SC-B01 | P3／L3 | 規則移除後的 orphan Mapping／Category 只回報、不刪除；是否需要 `--prune`（含確認與 dry-run） | 決定後再實作；若實作，需 rollback 與冪等測試 |
| SC-B02 | P2／L3 | P3：production `sync --dry-run` 報告由使用者審核，再於 migration 經 CD 套用後執行 `--apply`（需授權） | dry-run 報告與 `audit` 結果記入實作報告；金石堂缺頂層的書預期為 0 |
| SC-B03 | P3／L2 | 誠品分類樹改變（新增第 2 層、改名）時會出現 unruled，需人工補規則；目前沒有排程提醒 | 視分類樹更新頻率決定是否需要定期檢查 |

已決定、不列為待辦：誠品兩個同名第 3 層歸簡體書（決定 #7）。

互參：[架構](architecture.md)、[歷史](update-history.md)。
