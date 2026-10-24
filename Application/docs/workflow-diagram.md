# Application 流程與責任

> 查核日期：2026-10-24；Git 基準 `91333c3`。目標 `Application/`；本次僅靜態查核，未執行 build、測試、資料庫或外部服務。規格、實作與測試證據分開記錄。

## 入口及規格

| 入口 | 原始碼與輸出 | Authority |
|---|---|---|
| 書庫（#109） | [BookBrowseService](../Catalog/BookBrowseService.cs) ListAsync/SampleHomeAsync → BookBrowsePage / 隨機樣本 | [book-catalog](../../Docs/modules/book-catalog.md) §3.6 書庫瀏覽 |
| 暢銷榜（後端保留） | [BestsellerService](../Bestsellers/BestsellerService.cs) GetTopAsync/GetAllAsync → snapshot；#109 後 Web 無呼叫者 | [bestseller](../../Docs/modules/bestseller.md) §2～6 |
| 搜尋/詳細資料 | [BookSearchService](../Catalog/BookSearchService.cs)、[IBookDetailReader](../Catalog/IBookDetailReader.cs) → page/nullable detail | [book-catalog](../../Docs/modules/book-catalog.md) §3～4 |
| 註冊/登入 | [AccountService](../Identity/AccountService.cs) → typed outcome | [identity-auth](../../Docs/modules/identity-auth.md) §3～6 |
| Library/登入後待辦 | [LibraryService](../Library/LibraryService.cs) CRUD、AddPendingAsync | [user-library](../../Docs/modules/user-library.md) §3～5 |
| 推薦 | [RecommendationService](../Recommendation/RecommendationService.cs) → Succeeded/DailyLimitReached | [recommendation](../../Docs/modules/recommendation.md) §3～14 |
| 推薦紀錄 | [IRecommendationHistory](../Recommendation/IRecommendationHistory.cs) ListAsync/GetAsync | recommendation §12 |
| 背景補齊 | [EmbeddingBackfillService](../Recommendation/EmbeddingBackfillService.cs)、[BookProfileGenerationService](../Recommendation/BookProfileGenerationService.cs) | recommendation §9～10 |

```mermaid
flowchart TD
  C[Controllers 或 Infrastructure worker] --> A[Application use case orchestration 與 policy]
  A --> R[純規則與 TimeProvider]
  A --> P[Application ports 與 atomic persistence contract]
  P --> EF[Infrastructure EF adapter 或 cache decorator]
  EF --> DB[(PostgreSQL 與 pgvector)]
  P --> AI[Infrastructure OpenAI adapter]
  A --> OUT[Typed outcome 或 exception 回 caller]
```

HTTP auth、antiforgery、binding、狀態碼與畫面在 Web 邊界。Application 接收 caller 的 userId，定義 use case 的 atomic / transaction boundary；SQL、DbContext、transaction mechanics、cache implementation 與 queue worker 屬於 Infrastructure。Application 不直接操作 EF transaction。

## Catalog 與 Bestseller

```mermaid
flowchart TD
  S[SearchAsync input page token] --> N[page最小1；pageSize20；trim input]
  N --> Q{空輸入}
  Q -->|是| EMPTY[空hits total0；不呼叫DB]
  Q -->|否| ISBN{NFKC後符合ISBN字元長度}
  ISBN -->|是| I[Isbn normalized value與原trim文字]
  ISBN -->|否或無效Unicode| K[Keyword保留內部空白連字號]
  I --> PORT[IBookSearch 只查Local DB]
  K --> PORT
  PORT --> PAGE[BookSearchPage；超出頁數可回空hits]
  B[GetAllAsync 或 GetTopAsync] --> BR[IBestsellerReader讀整份snapshot]
  BR --> TOP{GetTop}
  TOP -->|是| TAKE[Take count；rank保留缺號]
  TOP -->|否| ALL[完整snapshot]
  L[BookBrowseService ListAsync page] --> LP[page最小1；pageSize20]
  LP --> BPORT[IBookBrowse.ListAsync 只查Local DB]
  BPORT --> BPAGE[BookBrowsePage；超出頁數回空items與原TotalCount]
  H[SampleHomeAsync] --> HS[IBookBrowse.SampleAsync count10；隨機，不讀Bestseller]
  D[IBookDetailReader.ReadAsync] --> EXISTS{找到Book}
  EXISTS -->|否| NULL[null；caller決定404]
  EXISTS -->|是| SAFE[BookDetail無簡介或目錄]
```

ISBN 判定只驗長度與字元，不是 checksum 檢驗。讀取例外/取消直接傳遞；沒有外部 fallback 或重試。空榜 CapturedAt=null。cache decorator 位於 Infrastructure；PublishedDateText 只依已知 precision 格式化，不自行猜測。

## Identity

```mermaid
flowchart TD
  REG[RegisterAsync] --> RULE[AccountInputRules 驗證與trim]
  RULE --> VALID{有效}
  VALID -->|否| ERROR[InvalidInput；不寫入]
  VALID -->|是| HASH[Hash密碼；v7 ID；UTC時間]
  HASH --> ADD[IUserStore.AddAsync]
  ADD --> DUP{DuplicateEmail}
  DUP -->|是| EMAIL[email欄位錯誤]
  DUP -->|否| OK[Succeeded User]
  LOGIN[LoginAsync] --> LV[必填驗證；不trim密碼]
  LV -->|無效| ERROR
  LV -->|有效| FIND[FindByEmailAsync]
  FIND --> FOUND{找到user}
  FOUND -->|否| DUMMY[Verify process共用dummy hash]
  DUMMY --> BAD[統一InvalidCredentials]
  FOUND -->|是| VERIFY[Verify password]
  VERIFY -->|失敗| BAD
  VERIFY -->|成功需rehash| UPDATE[UpdatePasswordHashAsync與UTC時間]
  VERIFY -->|成功| OK
  UPDATE --> OK
```

cookie/JWT 簽發、returnUrl 安全判定在 caller/Infrastructure。唯一 email 判定由 DB 的 lower(email) unique index 支援，服務接 DuplicateEmail outcome。dummy hash 用靜態 LazyInitializer 共用；不宣稱已做 constant-time 實測。

## Library CRUD 與待辦

```mermaid
flowchart TD
  ADD[AddAsync userId bookId] --> NEW[WantToRead rating null UTC時間]
  NEW --> STORE[AddIfMissingAsync]
  STORE --> FOUND{結果}
  FOUND -->|null| MISSING[BookNotFound]
  FOUND -->|新增或既存| ADDED[Added；既存Entry不改狀態評分]
  UPDATE[UpdateAsync] --> EMPTY{LibraryChange.IsEmpty}
  EMPTY -->|是| READ[FindAsync；時間不變；不存在null]
  EMPTY -->|否| WRITE[UpdateAsync port帶目前UTC；不存在null]
  LIST[ListAsync 或 FindAsync] --> SCOPE[port必帶userId與filter或bookId]
  REMOVE[RemoveAsync] --> DELETE[user-scoped port；不存在仍成功]
  P[登入成功後AddPendingAsync] --> VALID{精確action與canonical books路徑}
  VALID -->|否| IGNORE[忽略]
  VALID -->|是| ADD
  STORE -->|待辦一般例外| WARN[warning；登入繼續]
  STORE -->|待辦caller取消| CANCEL[傳遞取消]
```

[PendingLibraryAction](../Library/PendingLibraryAction.cs) 僅接受 add-to-library 與 `/books/{D格式GUID}`，不接受 query、fragment、尾斜線、額外 segment 或外部 URL。[LibraryChange](../Library/LibraryChange.cs) 區分 rating Unchanged/Clear/Set；JSON 型別與評分驗證在 Web parser。LibraryService 不重複檢查 HTTP JSON 規則。

## 推薦主流程：現況

```mermaid
flowchart TD
  IN[已驗證trim需求與登入userId] --> DAY[台北日界線UTC；usage.CountSinceAsync]
  DAY --> LIMIT{used至少DailyLimit預設20}
  LIMIT -->|是| STOP[DailyLimitReached；無外部call與保存]
  LIMIT -->|否| TIMER[60秒linked token；parsing到saving]
  TIMER --> PARSE[parser.ParseAsync]
  PARSE --> SAN[Sanitize filters；不合理條件丟棄warning]
  SAN --> TEXT[retrievalText空白改原需求]
  TEXT --> EMB[embedding.GenerateAsync]
  EMB --> FIND[candidates.FindAsync；filters AND similarity門檻；TopK]
  FIND --> HAS{候選非空}
  HAS -->|否| EMPTY[空results；不呼叫ranker]
  HAS -->|是| NUM[候選編號1到n；截短description]
  NUM --> RANK[ranker用原需求；不讀AI profile]
  RANK --> VALIDATE[候選編號與非空理由驗證；去重；最多10]
  VALIDATE --> SAVE[Application store port；Search 與全部 Results 原子保存]
  EMPTY --> SAVE
  SAVE --> DB[(EF單次SaveChanges；search與results一起提交)]
  DB --> LOG[成功log；目前fallback false written0]
  LOG --> ANY{結果非空}
  ANY -->|否| DONE[Succeeded]
  ANY -->|是| DIFF[先讀difficulty快照；caller token]
  DIFF --> QUEUE[再schedule stale profiles；caller token]
  QUEUE --> DONE
  TIMER -. timer取消且caller未取消 .-> TIMEOUT[AiTimeoutException；caller映射504]
  PARSE -. AI unavailable .-> ERROR[一次Error log；原例外傳遞映射502]
  EMB -. AI unavailable .-> ERROR
  RANK -. AI unavailable .-> ERROR
```

parser/embedding/search/ranker 失敗不進保存。Application 透過 [IRecommendationStore.SaveAsync](../Recommendation/IRecommendationStore.cs) 定義 Search 與全部 Results 必須一起保存的 atomic boundary，零結果也保存 Search；[EfRecommendationStore](../../Infrastructure/Persistence/EfRecommendationStore.cs) 用單次 EF SaveChanges／DB transaction 實現此 contract，保存失敗不留半成品。Application 不直接操作 DbContext 或 EF transaction mechanics。所有 ports 須配合 cancellation，傳 token 不等於強制中斷。timer 的60秒不包含 quota query，也不包含保存後 enrichment。

**保存後與保存前必須分開**：difficulty一般讀取失敗回空字典，scheduler一般失敗只記 warning；兩者使用 caller token，若 caller 在此取消，OperationCanceledException 仍可傳遞，但 search 已保存。不得概括為「所有失敗不保存」。保存後 timer 觸發不將已保存搜尋改為 timeout。見 APP-T10、T11、T17。

歷史 ListAsync 按使用者與分頁讀；GetAsync 在不存在/屬於別人均回 null。rank/reason/relevance 是保存 snapshot，title/authors/thumbnail 讀現有 Book；difficulty 另由 BookDifficultyReader 即時讀。

### 尚未實作的規格目標

```mermaid
flowchart TD
  LOCAL[本地Candidate Set] --> FEW{少於5本}
  FEW -->|否| HAS{Candidate Set 大於0本}
  FEW -->|是| GOOGLE[Recommendation 呼叫 Catalog ingestion port：未接入]
  GOOGLE -->|成功| NORMALIZE[Catalog 正規化與跨來源 identity 寫入 Book：未接入]
  NORMALIZE --> EMB[Recommendation 補 embedding 後相同 filter 與門檻重查]
  EMB --> HAS
  GOOGLE -->|失敗或逾時| ORIGINAL[使用原 Local Candidate Set 繼續]
  ORIGINAL --> HAS
  HAS -->|是| RANK[Ranking 與結果驗證]
  HAS -->|否| EMPTY[不呼叫 ranker；results 為空]
  RANK --> SAVE[保存成功 Recommendation Search 與全部 results]
  EMPTY --> SAVE
```

[recommendation §6](../../Docs/modules/recommendation.md) 是 authority；ParsedRequirement.GoogleQueries 未被 orchestration 使用，無 Google adapter port，log 固定 false/0。這是 APP-B01 未實作規格差距，不是已核准取消 fallback。Google 失敗／逾時保留原 Local Candidate Set；成功重查後亦須判斷候選數，零候選不呼叫 ranker，直接保存零結果 Search（APP-T16）。Recommendation 擁有觸發條件與 orchestration；Google Books normalization、cross-source identity resolution、Book persistence 規則由 [Book Catalog §6](../../Docs/modules/book-catalog.md) 擁有，Catalog 完成後由 Recommendation 補 embedding、重新 retrieval，再進 ranking。Catalog ingestion 與 Search／Results 保存是不同 atomic boundary；已寫入 Book 不隨後續推薦失敗回滾。

## 背景補齊與 profile

```mermaid
flowchart TD
  ROUND[Embedding RunOnceAsync] --> PENDING[FindPendingAsync BatchSize]
  PENDING --> NEXT{下一本}
  NEXT -->|無| COUNTS[回傳Succeeded Failed StoppedEarly]
  NEXT -->|有| GEN[逐本generator.GenerateAsync]
  GEN --> DIM{1536維}
  DIM -->|否| WARN[warning仍交store]
  DIM -->|是| SAVE[SaveAsync向量hash model]
  WARN --> SAVE
  SAVE --> RESET[成功加1；連續失敗歸零]
  RESET --> NEXT
  GEN -->|一般失敗| FAIL[失敗與連續失敗加1]
  SAVE -->|一般失敗| FAIL
  FAIL --> FIVE{連續失敗至少5}
  FIVE -->|否| NEXT
  FIVE -->|是| EARLY[StoppedEarly true]
  EARLY --> COUNTS
  GEN -->|caller取消| CANCEL[傳遞；不列失敗]
  SCHED[Profile ScheduleAsync] --> ENABLED{Enabled}
  ENABLED -->|否| END[不查DB不入列]
  ENABLED -->|是| STALE[FindStaleAsync；TryEnqueue]
  STALE --> WORKER[Infrastructure bounded queue與worker]
  WORKER --> LOAD[GenerationService.LoadSourceAsync]
  LOAD --> EXISTS{存在且仍stale}
  EXISTS -->|否| END
  EXISTS -->|是| TEXT[Build文字SHA256；確認真實目錄]
  TEXT --> PROFILE[generator.GenerateAsync]
  PROFILE --> NORMAL[Normalize；difficulty1到5；最多10章]
  NORMAL --> UPSERT[Upsert profile hash model prompt]
```

generation例外向 worker 傳遞，由 worker 記錄並處理下一本；Application無 retry。queue容量/去重/滿載丟棄屬 Infrastructure。profile 無真目錄不可聲稱 official。embedding/profile 的簡介各截2000 code points；profile目錄另截2000。deterministic text/hash 供 stale 判定。

## 導覽

[流程](workflow-diagram.md)・[架構](architecture.md)・[待辦](backlog.md)・[歷史](update-history.md)・[案例](test-suite.md)
