# Controllers 架構與選型對照

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
| 榜單 | [bestseller.md](../../Docs/modules/bestseller.md) | `HomeController`、`BestsellersController` |
| 書單隔離與更新語意 | [user-library.md](../../Docs/modules/user-library.md) | `LibraryController`、`LibraryApiController` |
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
| Home.Index | conventional `/`、`/Home/Index` | 否 | `BestsellerService.GetTopAsync(10)` → `BestsellerListViewModel` / View |
| Home.Error | conventional `/Home/Error` | 否 | RequestId → `ErrorViewModel` / View，NoStore |
| Bestsellers.Index | conventional `/bestsellers`、`/Bestsellers/Index` | 否 | `BestsellerService.GetAllAsync` → 榜單 View |
| Search.Index | GET `/search` | 否 | `BookSearchService`、`PageNumber` → View 或最後頁 Redirect |
| Books.Detail | GET `/books/{id}` | 否 | `IBookDetailReader`、`LibraryService` → Detail / 404 View |
| Account.Login | GET、POST `/account/login` | 否 | `AccountService`；成功由共用 SignInAndRedirect 寫 cookie、執行待辦與 Redirect |
| Account.Register | GET、POST `/account/register` | 否 | 同上；註冊成功直接登入 |
| Account.Logout | POST `/account/logout` | 是 | `AuthCookie.Delete` → Redirect `/` |
| Library.Index | GET `/library` | 是 | `LibraryService.ListAsync` → 書單 View |
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
| 讀取快取 | process-local IMemoryCache decorator，ADR-005 | Redis 可跨 instance 共用，但新增基礎服務 | 榜單 1 小時／空榜 5 分鐘；書目 10 分鐘；沒有 crawler invalidation 通道 |
| 個人化內容 | Library state 置於獨立 `ViewData[LibrarySectionKey]` | 與共用書目一起快取會混入跨使用者資料 | 共用書目可快取，Library 每次以 token 使用者重新讀取 |
| 資料存取 | Application service / read port → EF Core adapter → PostgreSQL | Controller 直接查 DbContext 會混合 HTTP 與 use case | Schema 由 EF migration 管理；本文件不授權任何 migration |
| 分頁 | 共用 PageNumber / PagerViewModel；每頁 20 筆 | 無限捲動或 cursor pagination 會改變 UI contract | 超大正整數視為超頁；完整頁重導、片段讀末頁，兩者不可混用 |
| 推薦 | Controller 驗證與映射；Application 控額度、計時、檢索、排序、保存 | Controller 內串 API 難以測試、易繞過 invariant | difficulty 快照與排隊在保存之後，失敗須降級 |
| 測試 | WebApplicationFactory + Testcontainers + fake 外部 adapter | 只 mock Controller 無法驗證 middleware / binding / HTML | 需 Docker；Web 測試不代表瀏覽器 JS 已被執行 |

## 5. 安全、內容與錯誤邊界

- 需登入的 action 使用 `[Authorize]`；user id 一律由 `CurrentUserId()` 取自 JWT `sub`，不接受 caller 指定 user id。
- 全域 `AutoValidateAntiforgeryTokenAttribute` 保護 unsafe MVC requests；API 失敗轉為 `/errors/antiforgery`。不要為了方便測試而關閉它。
- 頁面 challenge 導向登入；API challenge 為 401 `application/problem+json`。GET/HEAD 回跳保留 path/query；其他頁面方法不帶 returnUrl。
- API action 例外映射：AI unavailable 502、timeout 504、其他 500；response 不含 stack trace。RequestAborted 時 filter 不把取消轉為 500。
- Book detail 與 AI history 的非法 GUID／查無資料回 404；AI history 他人資料也回相同 404。Library DELETE 的非法 GUID 則為 204。
- Book `description`、`table of contents` 不進任何公開 ViewModel / JSON。AI profile 其他文字欄位不展示；理由不能大段引用原文。
- 普通搜尋只查 Local DB。AI 每日限制在任何外部呼叫前檢查；Candidate Set 必須同時通過硬條件與 similarity 門檻，結果最多 10 本，允許 0 本。
- 只有成功搜尋保存，包含 0 本結果；歷史列表只查本人；difficulty 即時讀取而不寫入搜尋結果快照。

## 6. 已知差距與文件時效

1. **Google Books fallback 尚未實作**：規格要求候選 `< 5` 才執行，現有 `RecommendationService` 未接 fallback，response 固定 `fallbackUsed:false`。這是既有功能缺口，不是此文件核准改掉 REC-03。
2. **登入／註冊 rate limiting 明確暫緩**：[Docs/TODO.md](../../Docs/TODO.md)、identity-auth §7 記錄 2026-10-20 決定；不可將每日推薦額度與登入 IP 頻率限制混為一談。
3. **部分規格保留階段性文字**：book-catalog §4.1 的 Library 空容器描述限定在 #11 前，現況已有完整區塊；test-plan §2 的 Web「骨架」描述落後現有測試。閱讀時結合當前程式，不據此移除既有功能。此任務不改原文件。
4. 本次僅新增文件，沒有執行 build、資料庫整合、外部服務或 production 驗證。測試庫內「已有測試」僅表示找到對應程式，不代表本次已通過。

流程細節見 [workflow-diagram.md](workflow-diagram.md)，可執行後續工作見 [backlog.md](backlog.md)，歷史證據見 [update-history.md](update-history.md)。
