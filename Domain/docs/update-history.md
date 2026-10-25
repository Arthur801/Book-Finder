# Domain Git 修改歷史

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

查核基準 `91333c3` 的 source history 如下；`Domain/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。PR2 phase A（#115）的程式變更已補入表格，見下方最後一列。

查核：2026-10-24；HEAD `91333c3`。範圍是全部可達 `Domain` 歷史，排除 `Domain/docs`，非 shallow。四筆直接 commit，按 author 日期由早至晚；日期為 `%ad --date=short`，不是部署／測試日。Author 都是 Arthur801，共同作者 trailer 不替代 author。

```bash
git log --reverse --format='%H %ad %an %s' --date=short 91333c3 -- Domain ':!Domain/docs'
git show 6b19340 -- Domain
git show be3cce9 -- Domain
git show 0c064f1 -- Domain
git show a19a7e2 -- Domain
git rev-parse --is-shallow-repository
```

| Author 日期／SHA | Subject | Domain 實際變化 |
|---|---|---|
| 2026-10-11／`6b19340b56c8a3123b56ff0060bc0ec8565b2173` | Complete PostgreSQL db creation | 新增 16 個來源：11 個資料類別、五 enum。Book nullable metadata／DateOnly／precision，Profile JSON/array；Search.UserId 當時 Guid?，書單名為 UserBook。已讀當前全部實體並查核 stat、Book 與 Result 建立 diff；不是推定 Domain 執行 DDL。 |
| 2026-10-11／`be3cce92a3a6b76e4a59803260ebda38249479ef` | Require user on recommendation searches (#1) | 已讀 Domain diff：UserId 從 Guid? 改 Guid；資料清理與 migration 是外層。 |
| 2026-10-11／`0c064f12b379352dfcb21cdf21d3f4594d99cdcc` | Add book_embeddings table with vector(1536) (#2) | 已讀新增 BookEmbedding 全文：BookId、required Vector/model/hash/time；1536 限制在 mapping，不在 class。 |
| 2026-10-11／`a19a7e297240ff8e01675d40d1f755617ed82e34` | Rename UserBook entity to LibraryEntry (#3) | 已讀 92% 相似度 rename diff，改類名符合 CONTEXT；DB 表仍 user_books。 |

## 相關依賴歷史

以下是選列的跨層歷史，不宣稱全量 Infrastructure 歷史；author 都是 Arthur801。

| Author 日期／SHA | 來源、查核範圍與影響 |
|---|---|
| 2026-10-21／`12296ef` | Implement the recommendation store in one SaveChanges；查核 EfRecommendationStore 路徑 log 與當前全文。交易由 adapter 管理；未逐檔讀整個 commit。 |
| 2026-10-22／`d5e1589aa4e38824e63317b5f5a33751dc77b87f` | Add book profile store (issue #18 M4)；讀 stat 與當前 EfBookProfileStore 全文。hash/staleness/framework/upsert 在外層，不覆寫 Book 內容。 |
| 2026-10-22／`a4c1fdc17d1b26c6c77ff9b9109ded41fabd84f7` | Keep the profile-only columns out of the embedding scan (issue #18)；已讀 BookMetadata diff。includeProfileFields 兩條 projection 防止 embedding 讀 publisher/TOC，不是刪 Book 欄位。 |
| 2026-10-25 | `2c662f5` | feat(db): add expand migration 010 for multi-source catalog | `Entities/SourceType.cs`（刪除）、`Entities/SourceCodes.cs`（新增）、`Entities/SourceProvider.cs`／`ProviderKind.cs`／`BookOffer.cs`／`OfferAvailability.cs`（新增）、`Entities/BookSource.cs`、`Entities/BookSubject.cs`（`SourceType` 改必填 `SourceCode` string）、`Entities/IdentifierType.cs`（新增 `Isbn`） |
| 2026-10-25 | `bbe0a0a` | refactor(catalog): share ISBN-family types and display priority | `Entities/IsbnIdentifierTypes.cs`（新增）|
| 2026-10-25 | `5052361` | feat(catalog): contract migration 011 and read only the ISBN type | `Entities/IdentifierType.cs`（刪除 `Isbn10`／`Isbn13`）、`Entities/IsbnIdentifierTypes.cs`（刪除）、`Persistence/Configurations/BookIdentifierConfiguration.cs`（移除 legacy partial unique）、`Persistence/Migrations/20261025120000_ContractMultiSourceCatalog.cs`（011）|
| 2026-10-25 | 本次 backlog 整理 commit | docs(backlog): tidy domain backlog after #113 PR1–PR4 | `docs/backlog.md`：DOM-B01、DOM-B05、DOM-B06 移出表格至「已處理」；補記標頭；未改程式 |

Git 不能證明已部署、migration 已套用或測試通過。實體建立後，多數行為演進在外層，Domain log 不等於全系統進度。

互參：[流程](workflow-diagram.md)、[架構](architecture.md)、[待辦](backlog.md)、[案例](test-suite.md)。
