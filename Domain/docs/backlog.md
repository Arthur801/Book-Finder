# Domain 優化與 debug 待辦

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

查核：2026-10-24；HEAD `91333c3`。沒有本次動態重現的 bug。P1 優先於 P2；L1–L4 沿用 AGENTS。這是驗收清單，不是 schema、部署或外部服務操作授權。

| ID | 優先／風險／狀態 | 證據、影響與來源 | 調查／前置決策 | 驗收／測試入口 |
|---|---|---|---|---|
| DOM-B01 | P2／L1／已處理（#113 PR1 文件） | [data-model ERD](../../Docs/data/data-model.md) 原本把 User 畫成 optional，與 §6.13 及 [Guid UserId](../Entities/RecommendationSearch.cs) 矛盾；#113 改寫 data-model 時 ERD 已改為 `USERS \|\|--o{ RECOMMENDATION_SEARCHES` | 不改 DB | 每筆 Search 必有 User；保持 NOT NULL；DOM-T08／SchemaTests |
| DOM-B02 | 跨層依賴追蹤／L3；上游 APP-B01 為 P1，非 Domain 實作缺陷 | [EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs) 固定 false，註解指 #14；[推薦 §6](../../Docs/modules/recommendation.md) 要求候選不足五本 fallback | Recommendation 決定 fallback 並編排；Catalog 擁有 normalization／cross-source identity／Book persistence 規則；Infrastructure 實現 Google／EF mechanics。Domain 僅追蹤契約影響，不在 entity setter 加 I/O | >=5 不呼叫、<5 才補充；ISBN 命中不重建 Book；同門檻再檢索；保存真實 flag；核心推薦在保存前失敗不存 Search；DOM-T10／RecommendationServiceTests 擴充 |
| DOM-B03 | P2／L3／待決策、待補強 | [Book](../Entities/Book.cs) date/precision 各自 nullable；[mapping](../../Infrastructure/Persistence/Configurations/BookConfiguration.cs) 無成對 CHECK，可能誤顯示日期 | 盤點 ingestion/顯示；決定有日期無 precision 是否合法，不自行做 migration | 有明確允許矩陣；year/month 不顯示為來源確定日；必要時新 migration、舊資料盤點與 SQL review；DOM-T09／PublishedDateTextTests 擴充 |
| DOM-B05 | P1／L3／已處理（#115 PR2 phase A，`2c662f5`） | 已刪除 closed enum `SourceType`；[BookSource](../Entities/BookSource.cs)、[BookSubject](../Entities/BookSubject.cs) 改為必填 string `SourceCode`（常數見 [SourceCodes](../Entities/SourceCodes.cs)）；新增 [SourceProvider](../Entities/SourceProvider.cs)、[BookOffer](../Entities/BookOffer.cs)、[IdentifierType.Isbn](../Entities/IdentifierType.cs)。目標見 [data-model §6.1、§6.3～§6.5、§6.7](../../Docs/data/data-model.md)。剩餘：Domain 不再有待辦 | PR2：`BookSource`／`BookSubject` 只保留必填 string `SourceCode`，刪除 `SourceType` enum；新增 `SourceProvider`、`BookOffer`；`IdentifierType` 新增 `Isbn`，`Isbn10`／`Isbn13` 暫留。EF 不 mapping 010 的 `source_type`（data-model §11.4） | entity 不再引用 `SourceType`；`StoredEnumTests` 涵蓋 `ISBN`；DB integration 依 [test-plan §7](../../Docs/testing/test-plan.md) #9、#10 驗證實體 schema |
| DOM-B06 | P2／L3／已處理（#120 PR4 M1，`5052361`） | `IdentifierType.Isbn10`／`Isbn13` 已刪除；`IsbnIdentifierTypes` 也刪除，搜尋與 Detail 直接比對 `IdentifierType.Isbn` | 無 | `IdentifierType` 只剩 `Isbn`、`Other`；ModelSnapshot 與 StoredEnum 測試同步 |
| DOM-B04 | P2／L2／改善提案 | 公開 entity 含私有內容；[BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs) 只守 BookDetail 類型 | 先盤點其他輸出邊界；保持 contract，不全面重寫 Domain | 新輸出 DTO 守門能偵測 description/TOC/hash 外流；記錄 projection 邊界；DOM-T01、DOM-T07／contract tests |

已完成、不再列待修：UserId 非 nullable、1536 維 Embedding、LibraryEntry 改名、embedding scan 不讀 Profile 專用欄位。未有量測支持現在新增 ANN。參閱 [歷史](update-history.md)、[案例](test-suite.md)、[架構](architecture.md)、[流程](workflow-diagram.md)。
