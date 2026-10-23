# Application 架構選型

> 查核日期：2026-10-24；Git 基準 `91333c3`。目標 `Application/`；本次僅靜態查核，未執行 build、測試、資料庫或外部服務。規格、實作與測試證據分開記錄。

## Authority 與責任

名詞依 [CONTEXT](../../CONTEXT.md)；拓樸依 [system architecture](../../Docs/architecture/system-architecture.md)、既定取捨依 [ADRs](../../Docs/architecture/architecture-decisions.md)。[API](../../Docs/api/api-spec.md) 管輸入/錯誤，[data-model](../../Docs/data/data-model.md) 管 schema；模組規則見流程入口表。本文件不取代 authority。

Application 負責 use case orchestration、application-level policy / validation、ports，並定義 use case 的 atomic / transaction boundary；Infrastructure 負責 EF、SQL 與 transaction mechanics。Domain 負責核心 entity 與 domain invariants；具體規則的現行落點仍須依實作查核。Application 依賴 Domain enum/entity 與 logging/options/time abstractions，不直接操作 HttpContext、DbContext、SQL 或外部 API client。部分 read port 由 controller 直接呼叫，沒有無規則的 service wrapper。

Application-level policy 包含 [LibraryService.AddPendingAsync](../Library/LibraryService.cs) 的 best-effort 行為（一般失敗只記 Warning、登入流程繼續，caller 取消仍傳遞）、[EmbeddingBackfillService](../Recommendation/EmbeddingBackfillService.cs) 的連續失敗五次停止，以及推薦的 quota ordering、timeout boundary 與錯誤政策，並非只有純規則。

依 [system architecture §4](../../Docs/architecture/system-architecture.md) 的分層責任，[IRecommendationStore.SaveAsync](../Recommendation/IRecommendationStore.cs) 在 Application 層定義「成功 Search 與全部 Results 一起保存，零結果仍保存 Search」的 atomic persistence contract；[EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs) 以單次 SaveChanges 與 DB transaction 落實。這個 use case 邊界不涵蓋先前的 Catalog ingestion 或保存後的 profile enrichment。

| 責任 | 主要介面/輸出 | Caller與callee |
|---|---|---|
| Bestseller | [BestsellerService](../Bestsellers/BestsellerService.cs)、IBestsellerReader → snapshot | Home/Bestsellers controllers → cached EF reader |
| Catalog | [BookSearchService](../Catalog/BookSearchService.cs)、IBookSearch、IBookDetailReader → page/detail | Search/Books controllers → EF/cache |
| Identity | [AccountService](../Identity/AccountService.cs)、IUserStore、IPasswordHashing → typed result | Account controller → EF/hashing |
| Library | [LibraryService](../Library/LibraryService.cs)、ILibraryStore、LibraryChange → Entry/null | Library/Books/Account controllers → EF |
| 推薦 | [RecommendationService](../Recommendation/RecommendationService.cs) → RecommendationAttempt | Recommendation controller → parser/embedding/candidate/ranker/store/usage ports |
| 歷史 | [IRecommendationHistory](../Recommendation/IRecommendationHistory.cs) → page/detail/null | Ai controller → user-scoped EF reader |
| 背景工作 | [EmbeddingBackfillService](../Recommendation/EmbeddingBackfillService.cs)、[BookProfileGenerationService](../Recommendation/BookProfileGenerationService.cs) | Infrastructure workers → store/generator ports |
| Profile顯示/排程 | [BookDifficultyReader](../Recommendation/BookDifficultyReader.cs)、[BookProfileScheduler](../Recommendation/BookProfileScheduler.cs) | 推薦/歷史 caller → profile store與queue |

[Program](../../Program.cs) 註冊 scoped use cases/EF ports；[auth registration](../../Infrastructure/Identity/AuthServiceCollectionExtensions.cs)、[OpenAI registration](../../Infrastructure/OpenAi/OpenAiServiceCollectionExtensions.cs)、[profile registration](../../Infrastructure/BackgroundJobs/BookProfileServiceCollectionExtensions.cs) 提供 adapters。TimeProvider、generators、queue 為 singleton；DbContext/store/service 維持 scoped，worker需每工作建立 scope。

## 選型與代價

以下替代方案為本次分析，非新 ADR；缺少設計紀錄時只陳述程式可見選擇，不推測原作者意圖。

| 面向 | 現況與依據 | 替代差異與代價 | 維護重點 |
|---|---|---|---|
| 邊界 | ports由Application定義、adapter位於Infrastructure | controller直接用EF會混合規則與transport | ports、fake與adapter需同步 |
| Outcome | record分支區分InvalidInput/Limit/Success | 業務分支用exception增加錯誤耦合 | caller完整pattern match |
| 搜尋 | SearchQuery union；空白不查DB；20筆/page | 空白列全部或遠端fallback違反SEARCH-01 | ISBN只判字元/長度，SQL escaping在adapter |
| Candidate | 結構化filters與向量交ICandidateSearch | LLM產SQL違反invariant | sanitizer不能證明條件真為使用者明示；parser也須受測 |
| 時間 | TimeProvider與[台北時間helper](../Common/TaipeiTimeZone.cs) | DateTime.Now難以測試日界線 | UTC保存；date precision缺失不猜 |
| 配額 | count後save無鎖，規格§11接受少量並行超額 | 嚴格reservation需改規則與交易 | 不當作已確認race bug |
| 交易邊界與機制 | Application 的 IRecommendationStore 定義 Search 與全部 Results 原子保存；Infrastructure 用單次 EF SaveChanges／DB transaction 實現 | 將 Search／Results 分開保存會違反 port contract，留下半成品 | Application 定義 policy/boundary，不直接操作 EF transaction；零結果仍保存，保存後 enrichment 不回滾 |
| Timeout | 固定60秒linked token，保存後profile在預算外 | 每步獨立timeout不能保證總預算 | adapters須合作取消；commit邊界待補證據 |
| Cache | reader decorator在Infrastructure，依ADR-005 | use case內cache增加耦合 | Bestseller正常1小時、空榜5分鐘；Book cache不含個人Library |
| Profile | 保存後先讀difficulty再入process queue | 同步生成增加延遲，broker屬新架構 | process重啟可丟工作；下次出現可重排 |
| Embedding | 循序、連續失敗5次停本輪、預期1536維 | 平行提高吞吐也提高外部壓力 | 維度異常仍save，由DB最後拒絕 |
| Stale | deterministic metadata text與SHA256 | 每次重新生成浪費成本 | profile model/prompt改變不觸發stale，依§9.2 |
| 密碼 | hashing port與process共用dummy hash | 完整Identity擴大責任 | dummy hash縮小時間差，不宣稱已實測constant-time |

## 安全、公開內容與一致性

身份與CSRF由Web驗證；Library/history每次帶userId，但service不驗JWT，不能獨立視為authorization boundary。AccountService回User entity，caller不可直接序列化，以免PasswordHash外洩。

BookDetail/BookSearchHit沒有description/table_of_contents。CandidateBook、RankingCandidate、embedding/profile source是內部AI資料，不可直接當public response。理由不得大段引用原始簡介或目錄，仍需prompt與response contract檢查。

成功log不含完整requirementText，包含filters、候選與時間等metrics；exception log的實際去識別需另查adapter，不能從service無key欄位就宣稱所有provider例外安全。

History的reason/rank/relevance是snapshot，Book標題等為目前資料；difficulty即時讀且不寫Recommendation Result。空results是成功搜尋，會保存並計入配額。保存前失敗不進save；保存後caller取消仍可能丟例外，不能據此判定未保存。

## 差距、暫緩與未驗證

**APP-B01確認缺口**：REC-03/推薦§6要求Google fallback；service未使用GoogleQueries，無Google port，metrics固定false/0。[EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs) 註解指向#14尚待接入。不是已核准取消該規則。

**明確暫緩**：[identity-auth §1](../../Docs/modules/identity-auth.md) 的Google登入、email驗證、忘記密碼、修改個資、refresh token，以及[test-plan §2](../../Docs/testing/test-plan.md)的browser E2E。不可混為已確認缺陷。

**待驗證**：APP-B02取消與DB commit交界、保存後取消的狀態證據。此次沒有runtime效能、真實provider、production DB、cache更新或部署驗證。

## 導覽

[流程](workflow-diagram.md)・[架構](architecture.md)・[待辦](backlog.md)・[歷史](update-history.md)・[案例](test-suite.md)
