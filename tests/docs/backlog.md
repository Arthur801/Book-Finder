# tests 優化與 debug 待辦

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M3（#120）補記：2026-10-25 更新；程式變更以 `d249c07`、`6e70e93`、`b99b368` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> backlog 整理（2026-10-25）補記：TEST-B05 已完成，移至文末「已處理」；TEST-B01～B04 狀態未變。

> 2026-10-24；HEAD `91333c3`。未執行測試，沒有本次已重現 runtime bug。命令與驗收不是執行授權。

優先序：P1 高、P2 一般、P3 低。風險沿用 AGENTS L1–L4。

| ID | 優先／風險／狀態 | 證據與影響 | 方向、前置決策與驗收 | 測試入口／案例 |
|---|---|---|---|---|
| TEST-B01 | P2 / L1 / 確認缺口：僅 Web coverage 描述 | [target test-plan](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/testing/test-plan.md) §2 在 merge target `main@ce7b4f46c0889db6b10216294cac658136796ad7` 仍稱 WebIntegration 骨架，落後既有 Auth、Library、Recommendation API／AI history coverage | 只同步 test-plan §2 的既有 WebIntegration 現況，不改產品。驗收：依現存測試列出 auth／CSRF、Library CRUD、推薦 API／quota／failure 與 AI history HTML coverage，區分 HTTP／SSR 與 browser；保持網站 browser E2E MVP 暫緩 | TEST-04～08；AuthPipelineTests、LibraryApiTests、RecommendationApiTests、AiPageTests、AiHistoryDetailTests |
| TEST-B02 | P1 / L3 / 確認缺口：fallback 未實作 | [recommendation §6/15](../../Docs/modules/recommendation.md)、[RecommendationService](../../Application/Recommendation/RecommendationService.cs) 與 [service tests](../UnitTests/RecommendationServiceTests.cs) 尚無 Google Books adapter 編排／fake 呼叫斷言 | 先依 catalog normalization 完成 fallback 功能，不能將空候選視為完整 MVP。驗收：4 候選觸發、5 不觸發；normalize 寫 DB、embedding 再篩選；外部失敗仍用 local；候選外書不進結果 | 待建 fake／DB／API cases；TEST-09 |
| TEST-B03 | P3 / L2 / 改善提案；網站 E2E 明確暫緩 | [WebFixture](../WebIntegration/WebFixture.cs) 使用 NullFileProvider，HTML tests 無法證明 JS 與 asset 操作 | 先決定是否解除 test-plan 的 MVP 暫緩；不直接加 CI。若核准，local browser + mock external + disposable DB 驗證 asset 200、Library pending／rating 互動 | 待建；TEST-12 |
| TEST-B04 | P2 / L2 / 待驗證 | CI artifact 缺檔為 warn；[crawler browser](../../crawler/tests/test_playwright_fetcher.py) 可 skip；job 綠燈不能證明每層都執行 | 先讀實際 TRX／JUnit／compat JSON，本次未讀。驗收：逐層列 executed/failed/skipped，記錄 compat 條件未觸發；必要層 skip 再提出 gate policy 決策 | CI artifacts；TEST-10、11 |

已完成的 authority 同步：[target test-plan](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/testing/test-plan.md) §6 已於 merge target `main@ce7b4f46c0889db6b10216294cac658136796ad7` 列出 CI/CD、Python 3.14／3.12 deploy/checker pytest、Docker smoke／no-keys control、imagetools roundtrip 與 migration compat，不再屬 TEST-B01 待辦。這只代表文件已同步，不代表本次或 production 執行通過；實際 CI artifacts 仍由 TEST-B04 追蹤。

watcher 耗盡（f233b9d）與 image pin（dccad53）是已修歷史，不列未完成。未來調查 fixture 啟動失敗時，應保存去識別的 Docker／migration exception、project/filter、SDK 與 image 名稱，再區分環境或程式回歸；禁止改接開發／production DB。

## 已處理

- **TEST-B05**（#113 PR2、PR3、PR4，PR #117、#119、#123）：test-plan §7 的 C# 與 crawler 端項目完成：010 schema、trigger、backfill（`MultiSourceCatalog010SchemaTests`、`MultiSourceBackfillTests`）；011 physical schema、preflight、verify（`ContractMigration011Tests`、`ContractMigration011PreflightTests`、`ContractMigration011VerifyTests`）；ISBN fixture（`IsbnNormalizerTests`）；BookDetail／Search 頁面；crawler 端由 CB-04～CB-06 覆蓋。證據：`2c662f5`、`905c6fc`、`df57cbf`、`d9d8948`、`5052361`、`d864acc`、`6e70e93`、`b99b368`、`861c334`、`f92a63d`。recovery compat（test-plan §7 #13、#14）尚未納入 CI，見 deploy DEP-B18。

[流程](workflow-diagram.md) · [架構](architecture.md) · [歷史](update-history.md) · [案例](test-suite.md)
