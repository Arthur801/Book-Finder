# Views 優化與 debug 待辦

查核：2026-10-24；HEAD `91333c3`。沒有本次動態重現的 bug。P2 為後續驗證／產品決策，P3 為低優先改善；風險沿用 L1–L4。只列證據支持的工作，不把歷史已修復問題重開。測試命令與待辦不是本次執行授權。

| ID | 優先／風險／狀態 | 證據與影響 | 方向及前置決策 | 可結案驗收／案例 |
|---|---|---|---|---|
| VIEW-B01 | P2／L2／待驗證；網站 E2E 明確暫緩 | [WebFixture](../../tests/WebIntegration/WebFixture.cs) NullFileProvider，現有 tests 只驗 HTML；[test-plan](../../Docs/testing/test-plan.md) MVP 不做 E2E，無法證明 fetch／storage／DOM 復原／static assets | 先決定是否解除暫緩；若核准用 local browser、mock AI、disposable DB；不連 real API | asset 200；AI 200/401/429/network、history redirected refresh、Library add/edit/remove/rollback 正常；記錄瀏覽器／資料與證據，不把 HTML tests 當 browser 通過；VIEW-T10–T12 |
| VIEW-B02 | P2／L2／待決策 | [Library/Index](../Library/Index.cshtml) 按 status 篩選，library.js PATCH 只更新 controls，不移走非符合列、不依 UpdatedAt 重排；換頁後才重新套 server 結果 | 決定修改後留當前列或即時重新篩選／排序；規格未明訂就不能標已確認 bug | 選定行為寫入 UI/library spec，測試 filtered READING 列改 FINISHED、最後列、UpdatedAt 重排；不丟操作錯誤或 token；VIEW-T12 |
| VIEW-B03 | P3／L1／改善提案 | [Shared/Error](../Shared/Error.cshtml) 英文 scaffold 含 Development 教學，與主要中文介面不同；無 stack trace 但文案不符合正式站語氣 | 確認正式錯誤文案及 RequestId 支援方式；不變 exception handler 安全政策 | 非 Development 錯誤用核定文案、保留 trace 支援、不顯 exception/secret；VIEW-T09 |
| VIEW-B04 | P3／L1／待決策 | [_ValidationScriptsPartial](../Shared/_ValidationScriptsPartial.cshtml) 無 caller，Account forms 依 server validation；不是已承諾的 client validation 缺陷 | 決定刪未用 scaffold 或有需要才引用；先確認表單沒有改動 public rules | 若啟用，JS 與 server 同樣欄位錯誤，不回填密碼、仍驗 CSRF；若保留／刪除，文件反映現況；VIEW-T04 |
| VIEW-B05 | P2／L2／待驗證（#113 PR2） | [Books/Detail](../Books/Detail.cshtml) 只渲染 view model 給的 ISBN 列與連結，本身不判斷來源；#113 改由 `source_providers.display_name` 產生連結文字、ISBN 標籤新增「ISBN」（[book-catalog §4](../../Docs/modules/book-catalog.md)） | 預期不需改 View；PR2 確認新的連結文字（例如 disabled provider 的顯示名稱）與 ISBN 列在現有版面正常呈現 | Detail 頁 HTML 含 provider 顯示名稱的連結、主要按鈕樣式只有一個、ISBN 列不重複；BookDetailPageTests |

已修復、不列待修：history refresh 跟隨登入 redirect 不能覆蓋片段（b2c72a0）；共用 pager／controls；未評分文字；ReadingStatusCode 單一順序；Book 安全外連與缺值投影。不要在此提案直接實作 SPA、取消 server validation 或把簡介／目錄加進 UI。

互參：[流程](workflow-diagram.md)、[架構](architecture.md)、[歷史](update-history.md)、[案例](test-suite.md)。
