# tests 優化與 debug 待辦

> 2026-10-24；HEAD `91333c3`。未執行測試，沒有本次已重現 runtime bug。命令與驗收不是執行授權。

優先序：P1 高、P2 一般、P3 低。風險沿用 AGENTS L1–L4。

| ID | 優先／風險／狀態 | 證據與影響 | 方向、前置決策與驗收 | 測試入口／案例 |
|---|---|---|---|---|
| TEST-B01 | P2 / L1 / 確認缺口 | [test-plan](../../Docs/testing/test-plan.md) Web 仍稱骨架；[ci.yml](../../.github/workflows/ci.yml) 已有更多 Docker／deploy／checker checks | 另案同步 authority 的現況描述，不改產品。驗收：三個 .NET projects、目錄外 pytest/browser/scripts/Docker/compat 正確定位，MVP 網站 E2E 暫緩不變 | 靜態對照；TEST-01、10、11 |
| TEST-B02 | P1 / L3 / 確認缺口：fallback 未實作 | [recommendation §6/15](../../Docs/modules/recommendation.md)、[RecommendationService](../../Application/Recommendation/RecommendationService.cs) 與 [service tests](../UnitTests/RecommendationServiceTests.cs) 尚無 Google Books adapter 編排／fake 呼叫斷言 | 先依 catalog normalization 完成 fallback 功能，不能將空候選視為完整 MVP。驗收：4 候選觸發、5 不觸發；normalize 寫 DB、embedding 再篩選；外部失敗仍用 local；候選外書不進結果 | 待建 fake／DB／API cases；TEST-09 |
| TEST-B03 | P3 / L2 / 改善提案；網站 E2E 明確暫緩 | [WebFixture](../WebIntegration/WebFixture.cs) 使用 NullFileProvider，HTML tests 無法證明 JS 與 asset 操作 | 先決定是否解除 test-plan 的 MVP 暫緩；不直接加 CI。若核准，local browser + mock external + disposable DB 驗證 asset 200、Library pending／rating 互動 | 待建；TEST-12 |
| TEST-B04 | P2 / L2 / 待驗證 | CI artifact 缺檔為 warn；[crawler browser](../../crawler/tests/test_playwright_fetcher.py) 可 skip；job 綠燈不能證明每層都執行 | 先讀實際 TRX／JUnit／compat JSON，本次未讀。驗收：逐層列 executed/failed/skipped，記錄 compat 條件未觸發；必要層 skip 再提出 gate policy 決策 | CI artifacts；TEST-10、11 |

watcher 耗盡（f233b9d）與 image pin（dccad53）是已修歷史，不列未完成。未來調查 fixture 啟動失敗時，應保存去識別的 Docker／migration exception、project/filter、SDK 與 image 名稱，再區分環境或程式回歸；禁止改接開發／production DB。

[流程](workflow-diagram.md) · [架構](architecture.md) · [歷史](update-history.md) · [案例](test-suite.md)
