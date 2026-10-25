# Application 待辦

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 查核日期：2026-10-24；Git 基準 `91333c3`。目標 `Application/`；本次僅靜態查核，未執行 build、測試、資料庫或外部服務。規格、實作與測試證據分開記錄。

優先序：P1核心規格缺口；P2邊界補證據。風險L1～L4依[AGENTS](../../AGENTS.md)§4。本次未重現runtime bug，待辦與命令不是執行授權。

## APP-B01 — 接入 Google Books fallback

- **P1 / L3 / 確認缺口，未實作**。
- 證據：[RecommendationService](../Recommendation/RecommendationService.cs) FindAsync後直接ranking；[ParsedRequirement](../Recommendation/ParsedRequirement.cs)的GoogleQueries未用；[EF store](../../Infrastructure/Persistence/EfRecommendationStore.cs)註解說明#14尚待接入，FallbackUsed=false。影響：本地候選0～4本不會補充。
- Authority：[recommendation §6](../../Docs/modules/recommendation.md)、[產品 REC-03](../../Docs/requirements/product-requirements.md)、[book-catalog §6](../../Docs/modules/book-catalog.md)。
- 方向與 ownership：Recommendation 新增對 Catalog-owned Google Books ingestion / normalization capability 的 orchestration port 與 fake，決定僅 Candidate Set < 5 時觸發。Google Books normalization、cross-source identity resolution 與 Book persistence 規則仍由 Book Catalog 擁有，不把 Google DTO parsing、ISBN merge 或 Book 寫入規則放進 Application/Recommendation。Recommendation 等待 Catalog 完成後補 embedding，以相同 filters/threshold 重新 retrieval，再進 ranking，保存真實 fallback flag 與 telemetry。Google 失敗降級本地候選；Catalog 已寫 Book 不隨後續推薦失敗回滾。
- 前置：依既有規格對照ISBN reuse、無ISBN與Book Source identity/data-model，不另改fallback門檻；不得把raw Google volume直接交ranker。
- 驗收：5本零Google呼叫；4本觸發；新增候選均已正規化寫DB且有embedding並通過門檻；遠端失敗仍可本地成功；quota拒絕不碰外部；log與保存欄位符合實際。
- 測試入口：[RecommendationServiceTests](../../tests/UnitTests/RecommendationServiceTests.cs)、[RecommendationApiTests](../../tests/WebIntegration/RecommendationApiTests.cs)、[EfCandidateSearchTests](../../tests/DatabaseIntegration/EfCandidateSearchTests.cs)。Recommendation 的 Catalog capability fake／編排測試，以及 Catalog-owned normalizer／identity／persistence 測試待建（Missing / Blocked by APP-B01）；不是本次已驗證結果。案例 **APP-T15、APP-T16**，回歸APP-T07～T10。

## APP-B02 — 補證保存交界與取消

- **P2 / L3 / 待驗證（Needs stronger evidence；案例 Pending）**；非已重現bug。
- 證據：service在SaveAsync內傳timer token；EF單次SaveChanges。既有unit檢查ranker/parser等待到60秒，但不證明commit與取消競態。保存後difficulty/scheduler使用caller token且允許caller取消傳遞，search已存在。
- 重現/觀測：disposable PostgreSQL、可控store/EF interceptor；在提交前、提交中、提交後設call gate，推進fake time或取消caller，記錄去識別searchId、commit觀測點、outcome與rows。不得連正式DB或以sleep猜測commit。
- 判定：提交前失敗不留半成品；提交後enrichment取消不被描述為「未保存」。若觀測到已commit但timeout，先釐清[recommendation §8/§13](../../Docs/modules/recommendation.md)可保證語意，不自行刪除已提交資料。
- 前置：實作測試前明確選擇交易觀測位置；產品語意衝突先回報。
- 驗收：交界案例穩定、無search/results半成品；保存後取消有獨立斷言；文件/contract與實際保證一致。
- 入口：[EfRecommendationStoreTests](../../tests/DatabaseIntegration/EfRecommendationStoreTests.cs)、RecommendationServiceTests。案例 **APP-T17**。

## APP-B03 — Bestseller 後端待 Web 呼叫者移除決策

- **P2 / L1 / 待決策，未實作**。
- 證據：#109 M2 後 Web 無 Bestseller 呼叫者（M1 只新增後端，Home／Bestsellers 仍呼叫）；[BestsellerService](../Bestsellers/BestsellerService.cs) 的 `HomeTopCount`、`GetTopAsync` 與 [EfBestsellerReader](../../Infrastructure/Persistence/EfBestsellerReader.cs) 仍保留，由 [BestsellerReaderIntegrationTests](../../tests/WebIntegration/BestsellerReaderIntegrationTests.cs) 守住 DI 鏈。
- 方向：Bestseller 是否長期保留、移除或改由其他功能使用，需另案決定；未決前不得刪除，也不得讓 Bestseller rank 進入推薦排序（本模組 [architecture.md](architecture.md)「核心不變條件」）。
- 驗收：決定後同步更新 [bestseller](../../Docs/modules/bestseller.md) 與本文件。

## APP-B04 — Catalog 讀取 contract 改用 provider code（#113 PR2）

- **P1 / L3 / 已處理（#115 PR2 phase A `2c662f5` 與 phase B `d9d8948`）**。
- 目標：[book-catalog §4](../../Docs/modules/book-catalog.md)：`BookDetailSource` 改為 `{Id, SourceCode, ProviderDisplayName, Url, FirstSeenAt}`；identifier 只為 `ISBN`（011 後，`5052361`）；ISBN 搜尋判定（長度 10／13）不變，與寫入端正規化分開。
- 目前差距（PR2 phase A，#115 `2c662f5` 已處理）：[BookDetail](../Catalog/BookDetail.cs) 的 `BookDetailSource` 已改為 `(Guid Id, string SourceCode, …)`，不再依賴 `SourceType`。phase B 已完成：`ProviderDisplayName`（JOIN `source_providers`，不以 `enabled` 過濾）、ISBN 讀取三種類型、Detail 去重（去重與標籤在 [BookDetailViewModel](../../Models/BookDetailViewModel.cs)）。
- 驗收：Application 不再引用 `SourceType`（已達成）；`BookDetailContractTests` 仍守住不含 description／TOC；BookSearchServiceTests 確認 `ABC123` 不走 ISBN 模式。
- phase A 新增：[IsbnNormalizer](../Catalog/IsbnNormalizer.cs) 實作寫入端 NFKC＋明確 White_Space 正規化，與一般搜尋的 `SearchQuery` 判定刻意分開；C# 與 crawler 共用 `tests/Fixtures/isbn-normalization.json`。crawler 端尚未接上（PR3）。

## APP-B05 — Google Books ingestion 改用新 identity resolution 與補 NULL（#14 前置）

- **P2 / L3 / 規格更新，與 APP-B01 一起實作**。
- 目標：[book-catalog §6](../../Docs/modules/book-catalog.md)：identity resolution 改為同來源 → distinct ISBN 數量；附加時只補 NULL（取代舊的「博客來 > Google」merge 優先順序）；source identity 衝突與 URL 漂移規則；開始寫入前先有 INF-B08 的 advisory lock。
- 驗收：同 APP-B01，另加 ISBN 恰好 1 本只補 NULL、≥ 2 本建立新 Book、Volume ID 與 URL 衝突時不寫入。

## 已修與明確暫緩

`13abf86`已共享dummy hash、`cd17224`已修difficulty讀失敗降級、`0fb9274`已修disabled仍排profile。它們是APP-T03/T12回歸項目，不列未完成。Auth MVP延後與browser E2E依架構文件的authority維持暫緩。效能未量測，不捏造向量/快取瓶頸或平行化收益。

## 導覽

[流程](workflow-diagram.md)・[架構](architecture.md)・[待辦](backlog.md)・[歷史](update-history.md)・[案例](test-suite.md)
