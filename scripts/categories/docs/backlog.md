# scripts/categories 待辦

> 建立：2026-11-14，分類計畫 P2。

| ID | 優先／風險 | 內容 | 驗收 |
|---|---|---|---|
| SC-B01 | P3／L3 | 規則移除後的 orphan Mapping／Category 只回報、不刪除；是否需要 `--prune`（含確認與 dry-run） | 決定後再實作；若實作，需 rollback 與冪等測試 |
| SC-B03 | P3／L2 | 誠品分類樹改變（新增第 2 層、改名）時會出現 unruled，需人工補規則；目前沒有排程提醒 | 視分類樹更新頻率決定是否需要定期檢查 |

已決定、不列為待辦：誠品兩個同名第 3 層歸簡體書（決定 #7）；誠品宗教命理名稱歸 religion（決定 #8）。

## 已處理

- **SC-B02**（2026-11-14）：production 已執行 `init`、`sync --dry-run`（審核後新增決定 #8）、`sync --apply`、`audit`。23,491 本中 23,486 本有分類，5 本沒有。見[實作報告](../../../Docs/Implementation-Report/canonical-category-p0-p3.md)。

互參：[架構](architecture.md)、[歷史](update-history.md)。
