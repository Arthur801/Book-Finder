# Domain 架構與映射

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

查核：2026-10-24；HEAD `91333c3`。Authority：[資料模型](../../Docs/data/data-model.md)、[CONTEXT](../../CONTEXT.md)、[產品 BOOK-05](../../Docs/requirements/product-requirements.md)。流程細節分別由 [書單](../../Docs/modules/user-library.md)、[推薦](../../Docs/modules/recommendation.md)、[crawler](../../Docs/modules/crawler.md) 管理。實作報告不是規格。

## 責任與 contract

Domain/Entities 有 12 個資料類別、5 個 enum，全部公開可變 setter；無 navigation、行為方法、event 或專屬 csproj，由根 [專案](../../Book-Finder.csproj) 編譯。依 [system architecture §4.1](../../Docs/architecture/system-architecture.md)，Domain 在架構上擁有核心 business rules／invariants；Application 負責 use case orchestration、application-level policy／validation 與 atomic boundary，Infrastructure 負責 EF mapping、查詢投影及 transaction mechanics。目前 Domain 偏 anemic model，規則的實際 enforcement 分散於 Application helpers 與 DB constraints；這個實作現況不代表規則 ownership 移交 Application。

| 型別 | 輸入／表示 | 映射與 consumer |
|---|---|---|
| [Book](../Entities/Book.cs) | UUID identity；required Title；DateOnly?、precision?；nullable metadata、timestamps | books；catalog/crawler/recommendation |
| [BookSource](../Entities/BookSource.cs) | BookId、SourceCode（必填，FK 至 source_providers）、required URL、external ID?、first/last seen | book_sources；外部 identity 不是 Book PK；011 後 `source_type` 已移除（data-model §11.3） |
| [BookIdentifier](../Entities/BookIdentifier.cs) | BookId/type/value | 複合 PK；ISBN 不跨 Book 唯一；011 後只有 `ISBN`／`OTHER`，legacy partial unique 已移除 |
| [BookContributor](../Entities/BookContributor.cs) | BookId/order/name/role | BookId/order PK；來源名稱，無全域 Person |
| [BookSubject](../Entities/BookSubject.cs) | BookId/subject/SourceCode | EF key 三欄；011 後實體 PK 同為 `(book_id, subject, source_code)` |
| [SourceProvider](../Entities/SourceProvider.cs) | Code、DisplayName、ProviderKind、BaseUrl?、Enabled、CreatedAt | source_providers registry；`enabled` 只控制主動 acquisition，不影響讀取 |
| [BookOffer](../Entities/BookOffer.cs) | SourceId、Currency?、Price?、ListPrice?、Availability、CapturedAt | book_offers current snapshot；尚無 writer |
| [SourceCodes](../Entities/SourceCodes.cs) | BOOKS_COM_TW、GOOGLE_BOOKS、KINGSTONE、ESLITE 常數 | 與 registry seed 對應；不是 enum，新增 provider 不改 DB |
| [User](../Entities/User.cs) | email/hash/display name/time | users；認證 store |
| [LibraryEntry](../Entities/LibraryEntry.cs) | user/book/status/nullable short rating | user_books；user/book PK |
| [Bestseller](../Entities/Bestseller.cs) | short rank/book/source/captured time | rank PK、book unique；crawler 寫、Web 讀 |
| [RecommendationSearch](../Entities/RecommendationSearch.cs) | 非 nullable user UUID、requirement、fallback/time | recommendation_searches；成功含零結果 |
| [RecommendationResult](../Entities/RecommendationResult.cs) | search/book/rank/nullable decimal score/reason | search/rank PK、search/book unique；score numeric(6,5) |
| [BookAiProfile](../Entities/BookAiProfile.cs) | nullable JsonDocument/string[]/difficulty；hash/model/prompt/time | 每 Book 一列，jsonb/text[]，只供推薦內部 |
| [BookEmbedding](../Entities/BookEmbedding.cs) | Pgvector.Vector、hash/model/time | 每 Book 一列 vector(1536) |

六組 enum 為 IdentifierType（`Isbn`、`Other`；011 移除 ISBN_10／ISBN_13）、ContributorRole、PublishedDatePrecision、ReadingStatus、ProviderKind、OfferAvailability。[StoredEnum](../../Infrastructure/Persistence/StoredEnum.cs) 將 C# PascalCase 映射 UPPER_SNAKE，並產生相同詞彙 CHECK；未知 persisted value 讀取時丟 InvalidOperationException。欄名由 [AppDbContext](../../Infrastructure/Persistence/AppDbContext.cs) 統一 snake_case，型別、鍵、關聯在 [Configurations](../../Infrastructure/Persistence/Configurations/BookConfiguration.cs)。

## 選型、替代與代價

| 面向 | 現況依據 | 替代差異與維護 |
|---|---|---|
| edition 模型 | data-model §4 明訂一層 Book | Work/Edition 雙層超出 MVP，須 schema/產品決策 |
| 可變資料類別 | source 可見；未找到 setter 設計的獨立 ADR | factory/value object 可提早驗證，但需兼顧 EF/callers；不能假設現況自證有效 |
| nullable metadata | 規格允許來源缺資料 | 空字串／猜日期會失真；顯示須保留 year/month precision |
| enum 字串 | StoredEnum 明示與 Python 共用詞彙 | numeric enum 省空間但破壞跨語言 contract；新增值需 CHECK migration 與 caller 同步 |
| UUID FK、無 navigation | source 可見選擇，理由未記錄 | navigation 易用但可能意外載入；現況明確 join/projection |
| Profile JSON/array | data-model §6.8 | 強型別可減無效 shape；現況 Application rules/store 保護，DB 只保證 jsonb 類型 |
| Pgvector 在 Domain | BookEmbedding 直接依賴套件 | float[] 可減耦合但不自帶維度限制；更換 model 要 migration 與全量重建 |
| exact vector search | data-model §6.9 核准 MVP | HNSW/IVFFlat 要先量測成本與品質，不預加基礎設施 |

## 一致性、安全與失敗

`required` 不保證非空白或 runtime 合法。NOT NULL、長度、正值頁數、評分與難度範圍、rank、enum、FK、unique 由 DB mapping/migration 執行；語言正規化、ISBN checksum、canonical merge 在 ingestion。Bestseller 的 BookId/SourceId 各自 FK 不保證兩者屬於同一本 Book，crawler 驗證仍必要。

[Indexes migration](../../Infrastructure/Persistence/Migrations/20261010174745_Indexes.cs) 建 lower(email) unique 及 lower(contributor name) index；不可只看 UserConfiguration 就宣稱缺索引。模型 snapshot 測試與 constraints.sql 分別查 EF metadata 及 raw SQL 索引。

Domain 無 cache、transaction、重試或取消機制。DateOnly 是出版日；DateTime 映射 timestamptz，UTC 時鐘由 callers 提供。每日上限的 Asia/Taipei 日界屬 Application usage。推薦 store 一次 SaveChanges 保存 Search/results，任一 result FK 錯誤不留半筆；Profile store 不覆寫 Book metadata。

Book.Description、TableOfContents 與 User.PasswordHash 是公開 property，沒有 JsonIgnore；必須用 read model/projection 隔離，不能直接當 API DTO。[BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs) 是既有守門，Library store 只選頁面允許欄位，不能推論所有未來 endpoint 自動安全。

## 差距與限制

資料模型 ERD 的 User optional 與 §5.11 非匿名／Guid UserId／NOT NULL 不一致（DOM-B01）。Google Books fallback 的跨層依賴尚未接入，現況 store flag 固定 false（DOM-B02）；此項不是 Domain entity 的 P1 implementation defect。日期與 precision 成對政策未由 DB 保證，須先決策（DOM-B03）。未找到本次動態重現 bug；未驗證 live schema、部署或外部 AI。

互參：[流程](workflow-diagram.md)、[待辦](backlog.md)、[歷史](update-history.md)、[案例](test-suite.md)。
