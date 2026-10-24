# Controllers 詳細流程

本文件依 2026-10-24 工作樹（基準 commit `91333c3`）整理現有流程。實線表示目前實作；明確標示的缺口不是已完成功能。Controller 只負責 HTTP 與 Application 結果映射，圖中的 SQL、外部呼叫與 transaction 均由下層負責。

規格入口：[UI 路由](../../Docs/ui/ui-flow.md)、[API contract](../../Docs/api/api-spec.md)、[系統分層](../../Docs/architecture/system-architecture.md)。架構對照見 [architecture.md](architecture.md)，案例編號見 [test-suite.md](test-suite.md)。

## 1. 共用請求管線與失敗出口

來源：`Program.cs`、`Infrastructure/Identity/AuthServiceCollectionExtensions.cs`、`AntiforgeryProblemDetailsFilter.cs`、`ApiExceptionProblemDetailsFilter.cs`。

```mermaid
flowchart TD
    R[HTTP request] --> F[UseForwardedHeaders]
    F --> E{Development 環境？}
    E -->|否| EH[註冊 ExceptionHandler 與 HSTS]
    E -->|是| H[UseHttpsRedirection]
    EH --> H
    H -->|HTTP| HTTPS[重導 HTTPS]
    H -->|HTTPS| ROUTE[UseRouting]
    ROUTE --> AUTH[UseAuthentication：只讀 JWT cookie]
    AUTH --> AZ{端點需 Authorize 且未登入？}
    AZ -->|是| KIND{路徑為 /api segment？}
    KIND -->|是| UNAUTH[401 problem+json：unauthenticated]
    KIND -->|否| METHOD{GET 或 HEAD？}
    METHOD -->|是| LOGIN[302 登入頁；returnUrl 含原 path 與 query]
    METHOD -->|否| LOGIN2[302 登入頁；不帶 returnUrl]
    AZ -->|否| CSRF{MVC unsafe method 的 antiforgery 有效？}
    CSRF -->|否，API| A400[400 problem+json：antiforgery]
    CSRF -->|否，頁面| P400[框架 400]
    CSRF -->|是，或 GET/HEAD 等安全方法| BIND[Model binding / action]
    BIND --> OK[View / PartialView / Redirect / JSON / 204]
    BIND -->|未處理的 action 例外| EX{API request？}
    EX -->|否，非 Development| PAGEERR[ExceptionHandler 重執行 /Home/Error]
    EX -->|否，Development| DEVERR[開發環境錯誤處理]
    EX -->|是| CANCEL{RequestAborted 已取消？}
    CANCEL -->|是| PROP[不由 API filter 轉成錯誤回應]
    CANCEL -->|否| TYPE{例外種類}
    TYPE -->|AiUnavailableException| E502[502 problem+json：ai-unavailable]
    TYPE -->|AiTimeoutException| E504[504 problem+json：ai-timeout]
    TYPE -->|其他| E500[記 Error；500 problem+json：internal]
```

驗證順序不能混淆：未登入的受保護 API 先在 authorization 被擋下；已登入但沒有 CSRF token 才測 antiforgery 400。登入／註冊表單可用 hidden antiforgery 欄位；JSON 呼叫帶 `RequestVerificationToken` header。API exception filter 並不保證涵蓋 middleware、路由未命中或 View 渲染階段的所有錯誤。

## 2. HomeController、書庫與 BestsellersController

來源：[HomeController.cs](../HomeController.cs)、[BooksController.cs](../BooksController.cs)、[BestsellersController.cs](../BestsellersController.cs)；規格：[book-catalog.md §3](../../Docs/modules/book-catalog.md)、[ui-flow.md](../../Docs/ui/ui-flow.md)、[bestseller.md](../../Docs/modules/bestseller.md)（榜單 Web 已不顯示）。

```mermaid
flowchart TD
    HOME[首頁 Index] --> SAMPLE[BookBrowseService.SampleHomeAsync：隨機 10 本]
    SAMPLE --> HVM[HomeViewModel.From]
    HVM --> HEMPTY{Catalog 為空？}
    HEMPTY -->|是| HEM[200 View：書庫還沒有書]
    HEMPTY -->|否| HROW[200 View：_BookList，不顯示 rank]
    BOOKS[GET /books：page] --> BP[PageNumber.Parse]
    BP --> LIST[BookBrowseService.ListAsync：每頁 20 本，依有日期新到舊、無日期在後、Id]
    LIST --> OVER{TotalCount 大於 0 且 Page 超過 TotalPages？}
    OVER -->|是| BREDIR[302 /books?page=最後一頁]
    OVER -->|否| BVM[BookBrowseViewModel.From → 200 View]
    BEST[GET /bestsellers] --> R301[301 永久重導 /books]
    ERR[Home.Error] --> ID[Activity.Id 或 TraceIdentifier]
    ID --> EV[ErrorViewModel；禁止 response cache]
    EV --> ER[共用 Error View]
```

`/` 對應 Home.Index，`/books` 對應 Books.Index（GET），`/bestsellers` 對應 Bestsellers.Index 並只回 301。Bestseller 後端（BestsellerService、快取與 reader）保留但沒有 Web 呼叫端。書庫與首頁樣本只查 Local DB，不依 rank 排序，也不讀 AI profile。Error action 本身回 View，非 Development exception handler 處理原始例外時通常保留 500；直接請求 `/Home/Error` 不應當作發生原始 500 的證據。

## 3. SearchController

來源：[SearchController.cs](../SearchController.cs)；規格：[book-catalog.md §3](../../Docs/modules/book-catalog.md)。

```mermaid
flowchart TD
    R[GET /search：q、page] --> P[PageNumber.Parse]
    P --> PN[非整數或小於 1 為 1；超大正整數為 int.MaxValue]
    PN --> S[BookSearchService.SearchAsync]
    S --> Q{trim q 後空白？}
    Q -->|是| ZERO[空結果；不列出全部書]
    Q -->|否| ISBN{NFKC 等正規化後符合 ISBN 格式？}
    ISBN -->|是| EXACT[ISBN / ISBN_10 / ISBN_13 精確匹配（IsbnIdentifierTypes）]
    ISBN -->|否| KEY[原 q 比對 title / contributor name；escape LIKE 字元]
    EXACT --> ORDER[精確書名優先；出版日期 DESC NULL 最後；id 穩定排序]
    KEY --> ORDER
    ORDER --> PAGE[COUNT + 每頁 20 筆；只查 Local DB]
    PAGE --> RESULT[搜尋結果]
    ZERO --> RESULT
    RESULT --> OVER{TotalCount 大於 0 且 Page 超過 TotalPages？}
    OVER -->|是| REDIR[302 最後一頁；保留並編碼 q]
    OVER -->|否| VIEW[SearchResultsViewModel.From → 200 View]
```

任何分支均不呼叫 Google Books、embedding 或 LLM；查無結果也不啟動 fallback。

## 4. BooksController

來源：[BooksController.cs](../BooksController.cs)；規格：[book-catalog.md §4–5](../../Docs/modules/book-catalog.md)、[user-library.md §5](../../Docs/modules/user-library.md)。

```mermaid
flowchart TD
    R[GET /books/id] --> G{Guid.TryParse 成功？}
    G -->|否| NF[設 status 404；NotFound View]
    G -->|是| READ[IBookDetailReader.ReadAsync]
    READ --> CACHE[CachedBookDetailReader：書目快取 10 分鐘]
    CACHE --> FOUND{找到 Book？}
    FOUND -->|否| NF
    FOUND -->|是| LINK[建立含當前 path/query 的 editLoginUrl]
    LINK --> AUTH{已登入？}
    AUTH -->|否| ANON[未登入 LibrarySection；不讀 Library store]
    AUTH -->|是| LIB[LibraryService.FindAsync：CurrentUserId + bookId]
    LIB --> SECTION[依本人 Entry 建立 LibrarySection]
    ANON --> VD[ViewData 的 LibrarySectionKey]
    SECTION --> VD
    VD --> VM[BookDetailViewModel.From 書目資料]
    VM --> V[200 Detail View：基本資料、合格外部連結、Library 控制項]
```

Library 狀態逐次讀取且不進入書目快取；description、table of contents 不進入公開 ViewModel。匿名加入書單的登入連結帶 `pendingAction=add-to-library`，與編輯控制項的過期登入連結用途不同。

## 5. AccountController

來源：[AccountController.cs](../AccountController.cs)、`Application/Identity/AccountService.cs`、`Application/Library/LibraryService.cs`；規格：[identity-auth.md](../../Docs/modules/identity-auth.md)。

```mermaid
flowchart TD
    R[GET 或 POST login / register] --> AUTH{已登入？}
    AUTH -->|是| HOME[302 /]
    AUTH -->|否| METHOD{GET？}
    METHOD -->|是| FORM[View：保留 returnUrl 與 pendingAction]
    METHOD -->|否，通過 antiforgery| SERVICE[AccountService.LoginAsync 或 RegisterAsync]
    SERVICE --> RESULT{Application outcome}
    RESULT -->|InvalidInput| FIELD[欄位錯誤加入 ModelState；重新顯示表單]
    RESULT -->|登入 InvalidCredentials| MSG[表單級：帳號或密碼錯誤]
    RESULT -->|Succeeded| COOKIE[AuthTokenIssuer.Issue → AuthCookie.Append]
    COOKIE --> PENDING[LibraryService.AddPendingAsync]
    PENDING --> VALID{action 與 returnUrl 符合精確待辦格式？}
    VALID -->|否| SAFE[SafeReturnUrl.Resolve]
    VALID -->|是| ADD[AddAsync：本人 + 解析出的 bookId]
    ADD -->|成功或已存在| SAFE
    ADD -->|Book 不存在或一般例外| WARN[Warning；登入仍成功]
    WARN --> SAFE
    ADD -->|請求取消| CANCEL[向上傳遞取消]
    SAFE --> LOCAL{Url.IsLocalUrl？}
    LOCAL -->|是| RETURN[302 本站 returnUrl]
    LOCAL -->|否| HOME
    LOGOUT[POST /account/logout：Authorize + antiforgery] --> DEL[AuthCookie.Delete]
    DEL --> HOME
```

待辦只接受大小寫相符的 `add-to-library` 與精確 `/books/{D 格式 GUID}`，不含 query、fragment、尾斜線。SafeReturnUrl 的本站路徑規則較廣，不能拿來代替待辦格式驗證。註冊成功直接登入；登出刪 cookie，不撤銷已簽發 JWT。Rate limiting 目前暫緩。

## 6. LibraryController、LibraryApiController

來源：[LibraryController.cs](../LibraryController.cs)、[LibraryApiController.cs](../LibraryApiController.cs)；規格：[user-library.md](../../Docs/modules/user-library.md)、[api-spec.md §4](../../Docs/api/api-spec.md)。以下入口皆先經 Authorize。

```mermaid
flowchart TD
    PAGE[GET /library：status] --> FILTER[ReadingStatusCode.TryParse；不合法視為全部]
    FILTER --> LIST[LibraryService.ListAsync：CurrentUserId + filter]
    LIST --> VM[LibraryPageViewModel；updated_at 新到舊、不分頁]
    VM --> VIEW[200 Index View；含保留篩選 query 的登入連結]
    PUT[PUT /api/library/bookId] --> PG{bookId 可解析 GUID？}
    PG -->|否| NF[404 problem+json：not-found]
    PG -->|是| ADD[AddAsync：CurrentUserId；RequestAborted]
    ADD --> OUT{Book 存在？}
    OUT -->|否| NF
    OUT -->|是| OK[200 LibraryEntryResponse；既有 Entry 不變]
    PATCH[PATCH /api/library/bookId] --> UG{bookId 可解析 GUID？}
    UG -->|否| NF
    UG -->|是| JSON[不論 Content-Type 以 JsonDocument 讀 body]
    JSON --> PARSE[空白或 JsonException 轉 null；交 LibraryPatchParser]
    PARSE --> VALID{物件與欄位有效？}
    VALID -->|否| BAD[400 ValidationProblemDetails：欄位或整體 body 錯誤]
    VALID -->|是| UPDATE[UpdateAsync：CurrentUserId + bookId + change]
    UPDATE --> EXIST{本人 Entry 存在？}
    EXIST -->|否| NF
    EXIST -->|是| UOK[200 LibraryEntryResponse]
    DELETE[DELETE /api/library/bookId] --> DG{bookId 可解析 GUID？}
    DG -->|否| NC[204；不存取 store]
    DG -->|是| REMOVE[RemoveAsync：只刪本人 Entry]
    REMOVE --> NC
```

PATCH 的 `{}` 是 no-op，保留 `updatedAt`；省略 rating 保留原值，`rating:null` 清除，`readingStatus:null` 回 400。指定相同有效值仍更新 `updatedAt`。DELETE 對未知／他人／非法 GUID 均為 204；PUT、PATCH 對非法 GUID 為 404。這些差異是 contract，不能統一成同一錯誤策略。

## 7. RecommendationsController 與 Application 協作

來源：[RecommendationsController.cs](../RecommendationsController.cs)、`Application/Recommendation/RecommendationService.cs`；規格：[recommendation.md §3–13](../../Docs/modules/recommendation.md)。

```mermaid
flowchart TD
    R[POST /api/recommendations：Authorize + antiforgery] --> BIND[FromBody RecommendationRequest]
    BIND --> INPUT[RecommendationInputRules：trim 後 1 到 500 code points]
    INPUT --> VALID{有效？}
    VALID -->|否| BAD[400 validation；errors.requirementText]
    VALID -->|是| CALL[RecommendAsync：CurrentUserId + text + RequestAborted]
    CALL --> DAILY[計算 Asia/Taipei 今日已保存的搜尋次數]
    DAILY --> LIMIT{已達 DailyLimit，預設 20？}
    LIMIT -->|是| TOO[DailyLimitReached → 429；不呼叫外部服務]
    LIMIT -->|否| TIME[啟動 60 秒 linked cancellation budget]
    TIME --> PARSE[需求解析 → sanitize 結構化 filters]
    PARSE --> EMB[embed retrievalText；空白則用原需求]
    EMB --> CAND[Local DB：硬條件且 similarity 達門檻；TopK]
    CAND --> COUNT{候選為 0？}
    COUNT -->|是| ZERO[不呼叫 ranker；結果為 0]
    COUNT -->|否| RANK[LLM 排序 → RankingRules 驗證候選、理由、數量]
    RANK --> SAVE[transaction 保存搜尋與結果]
    ZERO --> SAVE
    SAVE --> HASRESULT{結果非空？}
    HASRESULT -->|否| DONE
    HASRESULT -->|是| DIFF[保存後讀 difficulty 快照；不在 60 秒 budget 內]
    DIFF --> QUEUE[再排入 profile queue；一般失敗只記 Warning]
    QUEUE --> DONE[Succeeded → RecommendationResponse → 200 JSON]
    TIME -. 保存前核心步驟 .-> FAIL[AI unavailable 為 502；server budget 到期為 504；其他例外為 500]
    FAIL --> NO[核心流程保存前失敗：不保存搜尋、不計當日次數]
    DIFF -. caller 取消 .-> CANCEL[取消可傳遞；已保存 Search 與 Results 保留]
    QUEUE -. caller 取消 .-> CANCEL
```

**保存邊界**：quota、parse、embed、retrieve、rank 在保存前失敗不進入保存；store 交易失敗不留下 Search／Results 半成品。Search 保存後的 difficulty snapshot／profile scheduling 是 post-save enrichment，改用 caller token；一般失敗 Warning 降級，caller cancellation 可傳遞但不回滾已保存資料。不能由失敗／取消 response 推定 DB 沒有 Search；commit × cancellation 競態仍待 CTL-07 補證。

**現況缺口**：目前候選檢索後直接進入排序／保存，尚無 Google Books adapter 與 fallback 分支，`RecommendationResponse.FallbackUsed` 固定 `false`。規格要求候選 `< 5` 才允許 fallback，且必須 normalize、寫入、補 embedding、重跑相同檢索後才成為候選；此處不將目標流程畫成已實作。見 [backlog.md 的 CTL-01](backlog.md)。

## 8. AiController 的完整頁、片段與詳情

來源：[AiController.cs](../AiController.cs)；規格：[ui-flow.md §3.4](../../Docs/ui/ui-flow.md)、[recommendation.md §12](../../Docs/modules/recommendation.md)。三個入口皆需登入。

```mermaid
flowchart TD
    PAGE[GET /ai：page] --> P[PageNumber.Parse]
    FRAG[GET /ai/history-list：page] --> P
    P --> L[history.ListAsync：CurrentUserId、page、PageSize 20]
    L --> T[由這次 TotalCount 計算 totalPages]
    T --> OVER{有紀錄且要求頁超過末頁？}
    OVER -->|否| KIND{完整頁或片段？}
    KIND -->|完整頁| VIEW[200 Index View]
    KIND -->|片段| PART[200 _AiHistoryList；不含 layout]
    OVER -->|是| LAST{完整頁或片段？}
    LAST -->|完整頁| REDIR[302 /ai 或 /ai?page=末頁；不先重查末頁]
    LAST -->|片段| AGAIN[再查末頁一次]
    AGAIN --> PART
    DETAIL[GET /ai/history/id] --> G{Guid.TryParse 成功？}
    G -->|否| NF[相同的 404 NotFound View]
    G -->|是| GET[history.GetAsync：CurrentUserId + searchId]
    GET --> OWN{找到本人的搜尋？}
    OWN -->|否| NF
    OWN -->|是| D[BookDifficultyReader 批次讀當前 difficulty]
    D -->|成功或一般讀取失敗後空字典| MODEL[AiHistoryDetailViewModel.From]
    D -->|請求取消| CANCEL[向上傳遞取消]
    MODEL --> HV[200 History View；無 difficulty 顯示破折號]
```

紀錄的 rank、reason、relevance 使用已保存快照；書名、作者、封面讀目前 Book 資料，difficulty 即時讀取。首頁需求文字的 `sessionStorage` 傳遞、成功後刷新片段、loading 與 401 導向屬 `wwwroot/js/ai.js` 的瀏覽器流程，非 Controller 讀取 query 中的需求文字。
