# Views 優化與 debug 待辦

> Header P1 補記：2026-11-15 更新；程式變更以 `e355171`、`f4ccdc4` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 會員中心 C3 補記：2026-11-15 更新；程式變更以 `c3f09dc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> Canonical Category P5 補記：2026-11-14 更新；程式變更以 `a9b7ad1`、`c2d68a1`、`d43ea57` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 分類頁 P2 補記：2026-11-15 更新；程式變更以 `86a1876`（測試）、`c6a83bb`（實作）記入 update-history。原查核基準保留，未重新審查其餘內容。

> backlog 整理（2026-10-25）補記：VIEW-B05 已驗證完成，移至文末「已處理」；其餘狀態未變。

查核：2026-10-24；HEAD `91333c3`。沒有本次動態重現的 bug。P2 為後續驗證／產品決策，P3 為低優先改善；風險沿用 L1–L4。只列證據支持的工作，不把歷史已修復問題重開。測試命令與待辦不是本次執行授權。

| ID | 優先／風險／狀態 | 證據與影響 | 方向及前置決策 | 可結案驗收／案例 |
|---|---|---|---|---|
| VIEW-B01 | P2／L2／待驗證；網站 E2E 明確暫緩 | [WebFixture](../../tests/WebIntegration/WebFixture.cs) NullFileProvider，現有 tests 只驗 HTML；[test-plan](../../Docs/testing/test-plan.md) MVP 不做 E2E，無法證明 fetch／storage／DOM 復原／static assets | 先決定是否解除暫緩；若核准用 local browser、mock AI、disposable DB；不連 real API | asset 200；AI 200/401/429/network、history redirected refresh、Library add/edit/remove/rollback 正常；記錄瀏覽器／資料與證據，不把 HTML tests 當 browser 通過；VIEW-T10–T12 |
| VIEW-B02 | P2／L2／待決策 | [Member/Index](../Member/Index.cshtml) 的書單區塊按 status 篩選，library.js PATCH 只更新 controls，不移走非符合列、不依 UpdatedAt 重排；換頁後才重新套 server 結果 | 決定修改後留當前列或即時重新篩選／排序；規格未明訂就不能標已確認 bug | 選定行為寫入 UI/library spec，測試 filtered READING 列改 FINISHED、最後列、UpdatedAt 重排；不丟操作錯誤或 token；VIEW-T12 |
| VIEW-B03 | P3／L1／改善提案 | [Shared/Error](../Shared/Error.cshtml) 英文 scaffold 含 Development 教學，與主要中文介面不同；無 stack trace 但文案不符合正式站語氣 | 確認正式錯誤文案及 RequestId 支援方式；不變 exception handler 安全政策 | 非 Development 錯誤用核定文案、保留 trace 支援、不顯 exception/secret；VIEW-T09 |
| VIEW-B04 | P3／L1／待決策 | [_ValidationScriptsPartial](../Shared/_ValidationScriptsPartial.cshtml) 無 caller，Account forms 依 server validation；不是已承諾的 client validation 缺陷 | 決定刪未用 scaffold 或有需要才引用；先確認表單沒有改動 public rules | 若啟用，JS 與 server 同樣欄位錯誤，不回填密碼、仍驗 CSRF；若保留／刪除，文件反映現況；VIEW-T04 |

已修復、不列待修：history refresh 跟隨登入 redirect 不能覆蓋片段（b2c72a0）；共用 pager／controls；未評分文字；ReadingStatusCode 單一順序；Book 安全外連與缺值投影。不要在此提案直接實作 SPA、取消 server validation 或把簡介／目錄加進 UI。

## VIEW-B06 — 分類頁收合狀態的閃現

- **已結案（P2，`c6a83bb`）**：分類頁側欄、收合按鈕與 `category-sidebar.js` 已移除，頁面不再有收合偏好，這裡描述的閃現不會再發生。以下為舊描述，保留作為歷史。

- **P3 / L1 / 已觀察（2026-11-14 瀏覽器檢查）**：桌面版收合偏好由 [category-sidebar.js](../../wwwroot/js/category-sidebar.js) 在 DOMContentLoaded 後套用，已收合的使用者重新整理時，側邊欄可能先出現再隱藏。
- 方向：在 `<head>` 以極小的 inline script 先讀 localStorage、在 `<html>` 加 class；需確認 CSP 與 asset 規範是否允許 inline script。
- 驗收：已收合狀態重新整理無閃現；localStorage 失敗時仍正常顯示。

## 會員中心 C4 新增待辦

（無。C4 的新頁面沿用 C3 的 `alert` 與表單樣式，沒有新的版面或互動缺口。）

## 已處理

- **VIEW-B05**（#113 PR2，`d9d8948`，PR #117）：Detail 頁連結文字由 `source_providers.display_name` 產生、ISBN 標籤為「ISBN」；`Detail.cshtml` 未改。`BookDetailPageTests` 驗證 provider 名稱連結、單一主要按鈕與 ISBN 列不重複。

互參：[流程](workflow-diagram.md)、[架構](architecture.md)、[歷史](update-history.md)、[案例](test-suite.md)。

## 會員中心 C3 新增待辦

### VIEW-B07 — C3 新增文案需使用者審閱

- [ ] **P3／待決定／L1**。「請收信」、「重寄驗證信」、「連結無效或已過期」、「請先完成 Email 驗證」、「Email 已驗證，請登入」與 429 頁的文字為本次撰寫，不是規格。
- 待辦：使用者確認文案後再調整；變更文字時同步更新 `EmailVerificationFlowTests` 中的比對字串。

## P1 Header 新增待辦

### VIEW-B08 — 更多選單與功能導覽的待驗證項目

- [x] **已驗證（2026-11-15 一次性本機 Playwright（Chromium；拋棄式 pgvector 0.8.7-pg17、`manage_categories.py sync --apply` 寫入 18 類與 283 筆 Mapping、85 本假書其中一類 0 本；網站以 Development + HTTPS 啟動，OpenAI 以 proxy 擋下；腳本未 commit）80／80 通過，見 [test-suite](test-suite.md) VIEW-T30）**。原始紀錄：WebIntegration 只驗 HTML；「更多」的 Bootstrap 開關、Escape、點擊外部關閉、鍵盤 Enter／Space、手機 navbar 展開後的可點擊與不溢位，尚未以瀏覽器執行。方向：一次性本機瀏覽器驗收並把證據寫入 update-history；是否把 Browser E2E 納入 CI 仍待決定（計畫 D8）。
- [x] **P2／L1／已由 P4 結案**。「功能導覽」連到 `/categories#guide`，`onboarding.js` 已在 `/categories` 啟動導覽（見 [architecture](architecture.md) 首次造訪導覽）。WebIntegration 只驗連結與 hash 的 HTML 契約；實際啟動行為待 VIEW-B09 的瀏覽器驗收。

## P4 首次造訪導覽新待辦

### VIEW-B09 — 首次導覽的瀏覽器驗收

- [x] **已驗證（2026-11-15 一次性本機 Playwright（Chromium；拋棄式 pgvector 0.8.7-pg17、`manage_categories.py sync --apply` 寫入 18 類與 283 筆 Mapping、85 本假書其中一類 0 本；網站以 Development + HTTPS 啟動，OpenAI 以 proxy 擋下；腳本未 commit）80／80 通過，見 [test-suite](test-suite.md) VIEW-T30）**。原始紀錄：`onboarding.js` 的 spotlight 定位、窄螢幕 Collapse 展開與還原、焦點陷阱、Escape、localStorage 失敗、`/categories#guide` 的 hash 清理、以及「更多」步驟不展開選單，都還沒有在瀏覽器執行。對應 plan §8 ONB-01～ONB-09、ONB-11 的瀏覽器部分。方向：與 VIEW-B01、VIEW-B08 相同，一次性本機瀏覽器驗收並記錄證據；未核准前不加入 CI。

### VIEW-B10 — 分類頁 noscript 斷言與共用 Header 衝突

- [x] **已解決（2026-11-15，P2 `4e21229`）**：CAT-08 改為只檢查 `<main>` 之後的頁面內容，P1 header 的 noscript 不再影響。以下為原始紀錄。
- [ ] ~~**P2／L1／待決策**~~。`CategoryPageTests.Page_has_no_sidebar_drawer_toggle_or_noscript_list_and_no_sidebar_script` 在 `/categories` 斷言沒有 `<noscript`，但 P1 `f4ccdc4` 已把 navbar 的 `<noscript>` 放進共用 Layout，所以該案例失敗（P4 未改動它）。方向：決定是只檢查分類清單的 noscript，或改為斷言共用 navbar 的 noscript 與 P1 契約一致；需由 P1／P2 的負責人確認，不在 P4 內擅改。

### VIEW-B11 — OAuth consent 頁的 autostart 驗證

- [ ] **P3／L1／待確認**。OAuth consent 頁的 autostart false 只由 Layout 規則推導，尚無 WebIntegration 案例（需要 OAuth 流程）。方向：補一個已登入 OAuth consent 的 HTML 斷言。
