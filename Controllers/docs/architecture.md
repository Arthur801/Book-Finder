# Controllers 架構與選型對照

> 會員中心 C3 補記：2026-11-15 更新；程式變更以 `c3f09dc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 非同步推薦 Job M7 補記：2026-11-14 更新；程式變更以 `4db0c98`、`e00cbb5`、`5559870`、`ac88ef2` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P5 補記：2026-11-14 更新；程式變更以 `a9b7ad1`、`c2d68a1`、`d43ea57` 記入 update-history。原查核基準保留，未重新審查其餘內容。

整理日期：2026-10-24；程式基準：`91333c3`。本文件是目前 Controller 的導覽與設計說明，不替代 Docs 規格，也不新增 API contract。

## 1. Authority 與閱讀路徑

| 要確認的問題 | 主要規格 | 實作入口 |
|---|---|---|
| 分層、模組邊界 | [system-architecture.md §4](../../Docs/architecture/system-architecture.md) | `Program.cs`、`Application/`、`Infrastructure/` |
| 技術取捨 | [architecture-decisions.md，ADR-001、004、005](../../Docs/architecture/architecture-decisions.md) | MVC、Identity 設定與 cache decorator |
| 路由、頁面、空狀態 | [ui-flow.md](../../Docs/ui/ui-flow.md) | `Controllers/`、`Views/`、`wwwroot/js/` |
| JSON 欄位與錯誤 | [api-spec.md](../../Docs/api/api-spec.md) | API Controllers、`Models/*Response.cs`、`ApiProblemResults` |
| 帳號、安全與待辦 | [identity-auth.md](../../Docs/modules/identity-auth.md) | `AccountController`、`Infrastructure/Identity/` |
| 搜尋與書籍公開內容 | [book-catalog.md](../../Docs/modules/book-catalog.md) | `SearchController`、`BooksController` |
| 書庫與首頁樣本 | [book-catalog.md](../../Docs/modules/book-catalog.md) §3；榜單 Web 已不顯示，見 [bestseller.md](../../Docs/modules/bestseller.md) | `BooksController.Index`、`HomeController`、`BestsellersController`（301 至 `/books`） |
| 分類瀏覽 | [分類計畫](../../Docs/plans/canonical-category-browse.md) §4.2、§4.3 | `CategoriesController.Index`（`GET /categories`，匿名） |
| 書單隔離與更新語意 | [user-library.md](../../Docs/modules/user-library.md) | `MemberController`（/account 的書單區塊）、`LibraryApiController` |
| 推薦、額度、歷史與 difficulty | [recommendation.md](../../Docs/modules/recommendation.md) | `RecommendationsController`、`AiController` |
| 全域不可洩漏內容 | [product-requirements.md，BOOK-05](../../Docs/requirements/product-requirements.md) | ViewModel / response 欄位白名單 |
| 測試證據與執行層級 | [test-plan.md](../../Docs/testing/test-plan.md) | `tests/UnitTests`、`tests/WebIntegration`、`tests/DatabaseIntegration` |

名詞以 [CONTEXT.md](../../CONTEXT.md) 為準：Book、Book Source、Library Entry、Recommendation Search、Candidate Set。`Docs/Implementation-Report` 是實作紀錄，不作為規格 authority。

## 2. 分層與責任

```text
Browser / fetch
  → ASP.NET Core middleware（HTTPS、JWT cookie、authorization）
  → MVC filters（antiforgery、API 錯誤格式）
  → Controller（route / input / current user / HTTP outcome）
  → Application service 或 read port（use case / 規則）
  → Infrastructure adapter（EF Core、cache、OpenAI）
  → PostgreSQL / 外部服務

Application outcome
  → Models（ViewModel / Response DTO）
  → Razor HTML / partial HTML / JSON / redirect / 204
```

Controllers 目前共 9 個，皆繼承 MVC `Controller`；API 類別也沒有 `[ApiController]`。因此不能假設 model binding 會自動回傳專案指定的 validation 400。推薦 action 主動檢查 `request?.RequirementText`，Library PATCH 則自行解析 JSON，以維持缺欄位與明確 null 的差異。

Controller 不寫 SQL、不直接呼叫 OpenAI／Google Books、不持有推薦排序規則。依賴以 constructor injection 注入；部分注入 concrete Application service，部分注入查詢介面，不是所有依賴都經同一種 service facade。

## 3. Controller、路由與依賴清單

| Controller / Action | 路由與方法 | 登入 | 直接依賴與輸出 |
|---|---|---|---|
| Home.Index | conventional `/`、`/Home/Index` | 否 | `BookBrowseService.SampleHomeAsync`（隨機 10 本，不讀榜單）→ `HomeViewModel` / View |
| Home.Error | conventional `/Home/Error` | 否 | RequestId → `ErrorViewModel` / View，NoStore |
| Bestsellers.Index | conventional `/bestsellers`、`/Bestsellers/Index` | 否 | 不讀資料；`RedirectPermanent` 301 至 `/books` |
| Search.Index | GET `/search` | 否 | `BookSearchService`、`PageNumber` → View 或最後頁 Redirect |
| Books.Index | GET `/books` | 否 | `BookBrowseService.ListAsync`、`PageNumber` → 書庫 View 或最後頁 Redirect；空庫不重導 |
| Books.Detail | GET `/books/{id}` | 否 | `IBookDetailReader`、`LibraryService` → Detail / 404 View |
| Account.Login | GET、POST `/account/login` | 否 | `AccountService`；成功由共用 SignInAndRedirect 寫 cookie、執行待辦與 Redirect |
| Account.Register | GET、POST `/account/register` | 否 | 同上；註冊成功直接登入 |
| Account.Logout | POST `/account/logout` | 是 | `AuthCookie.Delete` → Redirect `/` |
| AccountDeletion.Index | GET `/account/delete` | 是 | 不讀資料 → 確認頁 View（`AccountDeletionForm`） |
| AccountDeletion.Delete | POST `/account/delete` | 是 | 套用 `account-auth` 每 IP 限流（與登入相同，因為會檢查目前密碼）；`AccountDeletionService`；Deleted／UserNotFound → `AuthCookie.Delete`、`TempData["Notice"]`、Redirect `/`；InvalidInput → 同一頁加錯誤（密碼不回傳） |
| OAuth.Authorize | GET、POST `/oauth/authorize` | 讀 `bf_auth`；未登入導向 `/account/login?returnUrl=` | OpenIddict passthrough（MCP-201b）：GET 顯示 consent 或依 permanent authorization 直接核准；POST 為 consent 表單（antiforgery）；session 已結束的匿名 POST 由 [ConsentSessionEndedRedirect](../ConsentSessionEndedRedirectAttribute.cs) 在 antiforgery 之前導回登入頁（同一個 authorize request）；只用 OpenIddict scheme SignIn／Forbid；`Mcp:Enabled = false` 時 404 |
| OAuth.Token | POST `/oauth/token` | 否（`[IgnoreAntiforgeryToken]`，public client + PKCE） | code／refresh_token grant；確認使用者仍存在後 SignIn；其他 grant `unsupported_grant_type` |
| McpGuide.Index | GET `/mcp-guide` | 否 | 不讀資料、不依賴任何 service → 靜態 View（MCP 操作手冊）；不在 `/mcp` 底下，MCP 閘門不處理，`Mcp:Enabled` 開關不影響 |
| Member.Index | GET `/account` | 是 | `LibraryService.ListAsync`、`RecommendationQuotaReader`、`RecommendationJobListLoader`（開關開啟時）→ `MemberPageViewModel` / View；`status`、`jobsPage` 參數 |
| Member.LibraryRedirect | GET `/library` | 是 | 不讀資料；`LocalRedirect` 302 至 `/account?status={CODE}#library`（合法 status 才保留），否則 `/account#library` |
| LibraryApi.Add | PUT `/api/library/{bookId}` | 是 | `LibraryService.AddAsync`、`ProblemDetailsFactory` → 200 / 404 |
| LibraryApi.Update | PATCH `/api/library/{bookId}` | 是 | JSON reader、`LibraryPatchParser`、`LibraryService.UpdateAsync` → 200 / 400 / 404 |
| LibraryApi.Remove | DELETE `/api/library/{bookId}` | 是 | `LibraryService.RemoveAsync` → 204 |
| Recommendations.Create | POST `/api/recommendations` | 是 | `RecommendationService`、`ProblemDetailsFactory` → 200 / 400 / 429；例外交由 filter |
| Ai.Index | GET `/ai` | 是 | `IRecommendationHistory.ListAsync` → View / Redirect |
| Ai.HistoryList | GET `/ai/history-list` | 是 | 同一 read port → `_AiHistoryList` PartialView |
| Ai.History | GET `/ai/history/{id}` | 是 | `IRecommendationHistory.GetAsync`、`BookDifficultyReader` → History / 404 View |

`Program.cs` 的預設路由是 `{controller=Home}/{action=Index}/{id?}`，沒有 HTTP method attribute 的 Home / Bestsellers actions 不應被文件誤描述成已由 `[HttpGet]` 限制。其他 actions 使用明確 method + path attributes。可能的額外 method 暴露應先盤點與測試，再決定是否收斂（見 backlog）。

## 4. 架構與選型對照

「替代方案」只用於解釋差異；除明確引用 ADR 外，不表示專案曾正式評估或批准過。

| 面向 | 目前選擇與依據 | 替代方案對照 | 目前代價 / 維護要點 |
|---|---|---|---|
| 部署與分層 | Modular Monolith，ADR-001 | 微服務可獨立擴展，但增加分散式一致性與部署負擔 | 模組邊界靠 Application ports 與 code review 維持 |
| 頁面 | ASP.NET Core MVC + Razor；UI Flow §1 | SPA 需另一套前端狀態與 API 範圍 | 保持一般表單 PRG；只有推薦與 Library 用 fetch |
| Runtime | 專案 `net10.0`，套件版本見 `Book-Finder.csproj` | 另換 runtime 無本任務需求 | Controller 文件不另釘套件版本，避免形成第二份 truth |
| HTTP 入口 | MVC `Controller` 同時提供 View / JSON | Minimal APIs 可簡化純 JSON 路由，但會分散目前 filter 與錯誤處理模式 | 不為形式一致強迫 API 改成另一框架 |
| 認證 | JWT Bearer middleware 從 HttpOnly Secure Lax cookie 讀 token，ADR-004 | localStorage + Authorization header 不適合目前一般頁面導航，且增加 JS token 暴露面 | cookie 自動附帶，unsafe request 必須驗 CSRF；不接受 Bearer header |
| 密碼 | AccountService + PasswordHasher，identity-auth §3 | 完整 ASP.NET Core Identity 提供更多帳號生命週期功能 | MVP 無 refresh token、email 驗證、忘記密碼；勿在 Controller 加入未定義流程 |
| 錯誤 | API 共用 ProblemDetails helper / filters；頁面使用 View | 每個 action 自製 JSON 容易漂移 | API action 例外 filter 的涵蓋範圍不等於整個 HTTP pipeline |
| PATCH input | JsonDocument + LibraryPatchParser | 直接綁 nullable DTO 無法單靠值區分省略與 null | 要保留 `{}`、null、數值 token 與 Content-Type 的精確 contract |
| 讀取快取 | process-local IMemoryCache decorator，ADR-005 | Redis 可跨 instance 共用，但新增基礎服務 | 書目 10 分鐘；榜單 1 小時／空榜 5 分鐘保留於後端，Web 已無呼叫端；沒有 crawler invalidation 通道 |
| 個人化內容 | Library state 置於獨立 `ViewData[LibrarySectionKey]` | 與共用書目一起快取會混入跨使用者資料 | 共用書目可快取，Library 每次以 token 使用者重新讀取 |
| 資料存取 | Application service / read port → EF Core adapter → PostgreSQL | Controller 直接查 DbContext 會混合 HTTP 與 use case | Schema 由 EF migration 管理；本文件不授權任何 migration |
| 分頁 | 共用 PageNumber / PagerViewModel；`/search`、`/books`、`/ai` 每頁 20 筆 | 無限捲動或 cursor pagination 會改變 UI contract | 超大正整數視為超頁；完整頁重導、片段讀末頁，兩者不可混用 |
| 推薦 | Controller 驗證與映射；Application 控額度、計時、檢索、排序、保存 | Controller 內串 API 難以測試、易繞過 invariant | difficulty 快照與排隊在保存之後；一般失敗降級，caller 取消可傳遞且不回滾已存資料 |
| 測試 | WebApplicationFactory + Testcontainers + fake 外部 adapter | 只 mock Controller 無法驗證 middleware / binding / HTML | 需 Docker；Web 測試不代表瀏覽器 JS 已被執行 |

## 5. 安全、內容與錯誤邊界

- 需登入的 action 使用 `[Authorize]`；user id 一律由 `CurrentUserId()` 取自 JWT `sub`，不接受 caller 指定 user id。
- 全域 `AutoValidateAntiforgeryTokenAttribute` 保護 unsafe MVC requests；API 失敗轉為 `/errors/antiforgery`。不要為了方便測試而關閉它。
- **唯一核准的例外（使用者 2026-11-15 核准）**：[ConsentSessionEndedRedirect](../ConsentSessionEndedRedirectAttribute.cs) 只套用在 `POST /oauth/authorize`。當請求沒有登入身分（cookie 因帳號刪除或 `auth_version` 遞增而被拒）且 `Mcp:Enabled` 為 true 時，它在 antiforgery 之前把瀏覽器導回 `/account/login?returnUrl=<同一個 authorize request>`。這個請求只會被轉址，不讀寫資料、不建立授權。不要擴大到其他 action；若要擴大，需重新取得使用者同意（AGENTS.md §2.3）。
- 頁面 challenge 導向登入；API challenge 為 401 `application/problem+json`。GET/HEAD 回跳保留 path/query；其他頁面方法不帶 returnUrl。
- API action 例外映射：AI unavailable 502、timeout 504、其他 500；response 不含 stack trace。RequestAborted 時 filter 不把取消轉為 500。
- Book detail 與 AI history 的非法 GUID／查無資料回 404；AI history 他人資料也回相同 404。Library DELETE 的非法 GUID 則為 204。
- Book `description`、`table of contents` 不進任何公開 ViewModel / JSON。AI profile 其他文字欄位不展示；理由不能大段引用原文。
- 普通搜尋與書庫（`/books`）只查 Local DB；書庫與首頁樣本不依 Bestseller rank 排序，也不讀 AI profile。
- 普通搜尋只查 Local DB。AI 每日限制在任何外部呼叫前檢查；Candidate Set 必須同時通過硬條件與 similarity 門檻，結果最多 10 本，允許 0 本。
- 核心推薦在保存前失敗不保存；成功保存包含 0 本結果。保存後 enrichment 的 caller cancellation 可以傳遞，但 Search／Results 已存在且不回滾；不能將所有失敗概括為「不保存」。歷史列表只查本人；difficulty 即時讀取而不寫入搜尋結果快照。

## 6. 已知差距與文件時效

1. **Google Books fallback 尚未實作**：規格要求候選 `< 5` 才執行，現有 `RecommendationService` 未接 fallback，response 固定 `fallbackUsed:false`。這是既有功能缺口，不是此文件核准改掉 REC-03。
2. **登入／註冊 rate limiting 明確暫緩**：[Docs/TODO.md](../../Docs/TODO.md)、identity-auth §7 記錄 2026-10-20 決定；不可將每日推薦額度與登入 IP 頻率限制混為一談。
3. **部分規格保留階段性文字**：book-catalog §4.1 的 Library 空容器描述限定在 #11 前，現況已有完整區塊；test-plan §2 的 Web「骨架」描述落後現有測試。閱讀時結合當前程式，不據此移除既有功能。此任務不改原文件。
4. 本次僅新增文件，沒有執行 build、資料庫整合、外部服務或 production 驗證。測試庫內「已有測試」僅表示找到對應程式，不代表本次已通過。

流程細節見 [workflow-diagram.md](workflow-diagram.md)，可執行後續工作見 [backlog.md](backlog.md)，歷史證據見 [update-history.md](update-history.md)。

## 推薦工作 API 與頁面（Job 計畫 M7）

| 端點 | 行為 |
|---|---|
| `POST /api/recommendations/jobs`（[RecommendationJobsController](../RecommendationJobsController.cs)） | 以 `RecommendationInputRules` 驗證需求 → `RecommendationJobService.SubmitAsync`（`Idempotency-Key` header 選填）→ 202＋`Location`＋`{ jobId, status, statusUrl }`；key 格式錯 400（欄位 `Idempotency-Key`）、同 key 不同需求 409 `/errors/idempotency-conflict`、每日上限 429。同 key 重送回同一個 Job 的目前狀態 |
| `GET /api/recommendations/jobs?page=N` | 本人的 Job，每頁 20 筆；`{ items, page, pageSize, totalCount, totalPages }` |
| `GET /api/recommendations/jobs/{jobId}` | `{ jobId, status, createdAt, completedAt, searchId, resultUrl, errorCode }`；不是 GUID、不存在、他人的一律同一個 404 problem |
| `/ai`（[AiController](../AiController.cs)） | 開關開啟時加上「推薦工作」列表（`jobsPage` 分頁，超出時顯示最後一頁），表單輸出 `data-recommendation-jobs` |
| `/ai/jobs/{id}` | Job 狀態頁；不是 GUID、不存在、他人的、開關關閉都是既有的 NotFound 頁（404） |

- `RecommendationJobs:Enabled` 關閉時，所有 Job API 都回 404 problem，`/ai` 與現在相同；既有的 `POST /api/recommendations` 不受影響。
- 需求文字只從 body 讀取，不出現在 URL、`Location` 或 log。
- `[Authorize]` 先於開關判斷：未登入的人一律被導向登入頁，所以開關關閉時，未登入的人看到的是登入頁，不是 404。
- 規格：[Job 計畫](../../Docs/plans/async-recommendation-jobs.md) §3.7、§3.8。

## 15. AccountDeletionController（會員中心 D1）

- 路由：`GET /account/delete`（確認頁）、`POST /account/delete`（刪除）；兩者都有 `[Authorize]`，匿名請求由 B2 的 JwtBearer challenge 導向登入頁（POST 不帶 returnUrl）。Antiforgery 由全域 filter 檢查。
- 表單欄位：`Password`、`Confirmed`（checkbox，未勾選不會送出，綁定為 false）。
- 控制器只映射結果：`Deleted` 與 `UserNotFound` 都清除 `bf_auth`、設定一次性 `TempData["Notice"] = "帳號已刪除"`，並 `Redirect("/")`；`InvalidInput` 把錯誤加入 ModelState 並重新顯示表單，`Password` 清空後不回傳瀏覽器。
- 不寫 SQL、不呼叫 OAuth，所有規則在 `AccountDeletionService`（Application）與交易在 `EfAccountDeletionStore`（Infrastructure）。
- 推薦工作 API 的提交若遇到已刪除使用者，`RecommendationJobsController` 回 401 `/errors/unauthenticated`（`ApiProblemResults.Unauthenticated`）。

## 會員中心 C3：Email 驗證頁、登入閘與頻率限制（新增）

| 項目 | 現行實作 |
|---|---|
| 驗證與重寄頁 | [AccountVerificationController](../AccountVerificationController.cs)：`GET/POST /account/verify-email`、`GET/POST /account/verification/resend`。每個 action 先檢查 `EmailVerification:Enabled`，關閉時回 404（plan D-A）。 |
| 註冊與登入 | [AccountController](../AccountController.cs)：`RegisterResult.PendingVerification` 由 `EmailVerificationService.SendAsync` 寄信並回「請收信」頁，不發 Cookie；`LoginResult.EmailNotVerified` 回登入頁並附重寄連結，不發 Cookie、不自動寄信（D-B）。 |
| 登入頁提示 | `GET /account/login?verified=1` 顯示「Email 已驗證，請登入」。`verified` 只控制提示文字，不影響驗證結果；開關關閉時仍會顯示，屬無害的文字差異。 |
| D-D 延續動作 | Controller 不自行判斷 returnUrl：`EmailVerificationService.Normalize` 決定保留哪些值，`LoginUrl` 只把保留下來的值放進 query。 |
| 重寄 POST | 只做 `IAccountEmailQueue.TryEnqueue`，回傳與帳號狀態無關的同一段通知（D-B）。佇列滿時仍回同一段通知，只寫 Warning log。 |
| Token 頁標頭 | 驗證 GET／POST 與確認頁套用 [TokenLinkPageAttribute](../../Infrastructure/Identity/TokenLinkPageAttribute.cs)：`Cache-Control: no-store`、`Referrer-Policy: no-referrer`。 |
| 頻率限制 | [AccountRateLimiting](../../Infrastructure/Identity/AccountRateLimiting.cs)：`account-auth`（登入、註冊、驗證 POST）與 `account-email`（重寄）。`UseRateLimiter` 放在 `UseRouting` 之後、`UseAuthentication` 之前；分區鍵為 `UseForwardedHeaders` 之後的 `RemoteIpAddress`。 |

Controller 只做 HTTP 對應與 outcome 分支，不含業務規則。Token 的有效性、D-D 的白名單、寄信失敗與 discard 都在 Application（[EmailVerificationService](../../Application/Identity/EmailVerificationService.cs)）；驗證交易在 Infrastructure（[EfEmailVerificationStore](../../Infrastructure/Persistence/EfEmailVerificationStore.cs)）。

**設定與預設值**

- `EmailVerification:Enabled`：預設 false。開啟時 `Email:Provider` 不可為 None（啟動時驗證，見 Infrastructure 架構文件）。
- `AccountRateLimits:AccountAuth`：PermitLimit 20、Window 1 分鐘（每個 IP）。
- `AccountRateLimits:AccountEmail`：PermitLimit 5、Window 10 分鐘（每個 IP）。
- 兩者必須大於 0，啟動時驗證。預設值只在程式內，`appsettings.json` 不含這兩段。

**頁面與安全邊界**

- 開關開啟時，註冊後的 Cookie 數量為 0，直到驗證完成後登入。
- 確認頁（GET）不消耗 token；只有 POST 消耗。
- 驗證 POST 失敗（重放、過期、用途錯誤、格式錯誤）一律顯示「連結無效或已過期」，不區分原因。
- 所有 redirect 都是 `LocalRedirect` 或 `Redirect("/")`，沒有任意外部網址（CodeQL `cs/url-redirection`）。
- [_Layout.cshtml](../../Views/Shared/_Layout.cshtml) 只載入同源資源（`bootstrap`、`jquery`、`site.js`、`site.css`），沒有第三方 CDN。因此 token 頁的 `Referrer-Policy` 目前沒有外流對象；仍保留該標頭，作為之後新增第三方資源時的防線。

**已知限制**

- 頻率限制與重寄佇列都在單一 process 的記憶體內。多 instance 部署時，限制不會跨 instance 共用（見 Infrastructure backlog）。
- 佇列未持久化：程序重啟時，尚未寄出的重寄請求會遺失；使用者重新送出即可。
- 註冊頁的「此 email 已被註冊」仍會顯示帳號是否存在，這是既有行為，不在 C3 的 D-B 範圍內（見 backlog CTL-13）。

## 會員中心 C4：忘記密碼頁（新增）

`PasswordResetController`（`Controllers/PasswordResetController.cs`）負責四個頁面，業務判斷全部在 `PasswordResetService`，控制器只把結果換成回應。

| 路由 | 方法 | 行為 |
|---|---|---|
| `/account/password/forgot` | GET | 顯示 Email 欄位。匿名或已登入都可用，不因已登入導走 |
| `/account/password/forgot` | POST | `account-email` 限流；只把 `(PasswordReset, 去空白的 Email)` 放進 `IAccountEmailQueue`，回應固定為「如果這個 Email 已註冊，我們已寄出重設密碼信，請收信」。空字串也入列，由 worker 忽略 |
| `/account/password/reset?token=` | GET | `[TokenLinkPage]`。`IsUsableAsync` 為假時顯示「連結無效或已過期」；可用時顯示新密碼與確認表單，token 放在隱藏欄位。GET 不消耗 |
| `/account/password/reset` | POST | `[TokenLinkPage]` 與 `account-auth` 限流。結果見下 |

reset POST 的三種結果：
- `Reset`：刪除此瀏覽器的 Cookie，`LocalRedirect("/account/login?reset=1")`。
- `InvalidInput`：表單重新顯示，兩個密碼欄位清空、錯誤顯示在欄位旁，token 保留，可再次送出。
- `InvalidLink`：顯示無效頁。

開關（D-A）：四個 action 在 `EmailVerification:Enabled=false` 時都回 404。條件只讀設定，不讀 request 值，因此不會成為敏感動作的 request 控制條件（CodeQL `cs/user-controlled-bypass`）。

重導一律是 `LocalRedirect`（CodeQL `cs/url-redirection`）。

其他 Controller 的變更：
- `AccountController`：登入 GET 接受 `reset=1`，顯示「密碼已重設，請重新登入」。登入 GET 與 POST 都設定 `ViewData["ShowPasswordResetLink"]`，開關開啟時顯示「忘記密碼？」連結。
- `MemberController`：`MemberPageViewModel.PasswordResetEnabled` 由開關決定，`#account-security` 區塊只在開啟時顯示「重設密碼」連結（指向同一個忘記密碼頁）。沒有需要登入的修改密碼流程（U-05）。
