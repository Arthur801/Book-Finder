# wwwroot 優化與 debug 待辦

> 查核：2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。當前工作樹靜態證據；本次未執行 build、測試、瀏覽器、網路或發布。只新增本目錄五份文件。

沒有本次已重現的 browser bug；歷史 redirect 修復不再列未完成。以下均不授權增加工具、發布或外部呼叫。

## WB-01 — 建立自有 JS 互動回歸證據

- P1；L2；狀態：確認驗證缺口；網站 browser E2E 明確暫緩（MVP 不做）。
- 證據：[AiPageTests](../../tests/WebIntegration/AiPageTests.cs) 註解明言不執行 JS；現有 tests 為 .NET HTML／API，未找到 package.json／JS browser runner。ai.js 的 storage／history promise、library.js 的 WeakMap rollback 無此層執行證據。
- 影響：HTML／API 綠燈不能證明推薦與書單在瀏覽器完成互動。不是已重現錯誤。
- 方向：先選可重用 browser／DOM harness，使用真 View fixture 與 stub fetch／storage／location，禁止真 OpenAI／Google Books／正式 DB；測量 CI 成本與不穩定性。
- 前置決策：[test-plan §2](../../Docs/testing/test-plan.md) 明定「E2E 瀏覽器：MVP 不做」。可先選純 DOM／fetch 替身 harness（不等同網站 E2E）；若選真網站 browser E2E，必須先明確決定解除暫緩並更新 authority。runner 依賴與 CI 策略也需決策；不是這次文件工作實作授權。
- 驗收：WT-01～WT-09 的 payload、CSRF、401、429、解析錯誤、零結果、redirect history、rollback、最後列移除都有可重跑斷言；沒有外部服務；測試不僅匹配 source 字串。
- 入口：[AiPageTests](../../tests/WebIntegration/AiPageTests.cs)、[LibraryPageTests](../../tests/WebIntegration/LibraryPageTests.cs)、[LibraryApiTests](../../tests/WebIntegration/LibraryApiTests.cs)；browser cases 待建。

## WB-02 — 確認 wwwroot/docs 發布政策

- P1；L2；狀態：待驗證／待決策，非確認洩漏。
- 證據：[Program](../../Program.cs) MapStaticAssets，Web SDK project 未排除 wwwroot/docs；本文件放置位置本身可能進入靜態資產範圍。
- 影響：技術流程／測試案例可能成為公開下載資產；本文件沒有 secret，但不能將工作區位置當作存取控制。
- 方向：先決定是否允許公開；後續在 disposable publish 輸出檢查 manifest／檔案，必要時本機 HTTP 驗證 MIME／status，不靠推論。若要排除或移動需另行核准範圍，本次不改 csproj。
- 驗收：WT-11 有明確允許／禁止政策與對應 artifact／HTTP 證據；政策與文件位置一致。
- 入口：[Book-Finder.csproj](../../Book-Finder.csproj)、[Program](../../Program.cs)；publish／HTTP 測試待建。

## WB-03 — 驗證視覺與鍵盤互動

- P2；L1；狀態：待驗證。
- 證據：[site.css](../css/site.css) 768px 字級、focus outline、星色與兩行 clamp；[Controls](../../Views/Shared/_LibraryControls.cshtml) aria-pressed／button；現有 HTML 測試無渲染證據。
- 方向／量測：本機固定 viewport／瀏覽器確認溢位、兩行截斷、focus 可見與失敗後可操作；確認歷史全文可存取。
- 前置：可用 browser，無需真外部 API。驗收：WT-10 鍵盤與桌機／窄螢幕觀測可追溯，無未記錄外部呼叫；不擅改其他 UI 軸。
- 入口：[site.css](../css/site.css)、[LibraryPageTests](../../tests/WebIntegration/LibraryPageTests.cs)；視覺測試待建。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
