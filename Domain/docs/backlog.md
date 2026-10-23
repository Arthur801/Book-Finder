# Domain 優化與 debug 待辦

查核：2026-10-24；HEAD `91333c3`。沒有本次動態重現的 bug。P1 優先於 P2；L1–L4 沿用 AGENTS。這是驗收清單，不是 schema、部署或外部服務操作授權。

| ID | 優先／風險／狀態 | 證據、影響與來源 | 調查／前置決策 | 驗收／測試入口 |
|---|---|---|---|---|
| DOM-B01 | P2／L1／確認文件衝突 | [data-model ERD](../../Docs/data/data-model.md) User optional 與 §5.11 及 [Guid UserId](../Entities/RecommendationSearch.cs) 矛盾，可能誤導匿名紀錄設計 | 依同文件表格及產品登入規則修 ERD，不改 DB | 每筆 Search 必有 User；保持 NOT NULL；DOM-T08／SchemaTests |
| DOM-B02 | P1／L3／確認缺口，外層未實作 | [EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs) 固定 false，註解指 #14；[推薦 §6](../../Docs/modules/recommendation.md) 要求候選不足五本 fallback | 跟進 Application/Infrastructure normalization 與 identity resolution，不能在 entity setter 加 I/O | >=5 不呼叫、<5 才補充；ISBN 命中不重建 Book；同門檻再檢索；保存真實 flag；核心推薦在保存前失敗不存 Search；DOM-T10／RecommendationServiceTests 擴充 |
| DOM-B03 | P2／L3／待決策、待補強 | [Book](../Entities/Book.cs) date/precision 各自 nullable；[mapping](../../Infrastructure/Persistence/Configurations/BookConfiguration.cs) 無成對 CHECK，可能誤顯示日期 | 盤點 ingestion/顯示；決定有日期無 precision 是否合法，不自行做 migration | 有明確允許矩陣；year/month 不顯示為來源確定日；必要時新 migration、舊資料盤點與 SQL review；DOM-T09／PublishedDateTextTests 擴充 |
| DOM-B04 | P2／L2／改善提案 | 公開 entity 含私有內容；[BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs) 只守 BookDetail 類型 | 先盤點其他輸出邊界；保持 contract，不全面重寫 Domain | 新輸出 DTO 守門能偵測 description/TOC/hash 外流；記錄 projection 邊界；DOM-T01、DOM-T07／contract tests |

已完成、不再列待修：UserId 非 nullable、1536 維 Embedding、LibraryEntry 改名、embedding scan 不讀 Profile 專用欄位。未有量測支持現在新增 ANN。參閱 [歷史](update-history.md)、[案例](test-suite.md)、[架構](architecture.md)、[流程](workflow-diagram.md)。
