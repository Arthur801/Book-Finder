# Views 架構與呈現契約

> 會員中心 C3 補記：2026-11-15 更新；程式變更以 `c3f09dc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 非同步推薦 Job M7 補記：2026-11-14 更新；程式變更以 `4db0c98`、`e00cbb5`、`5559870`、`ac88ef2` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P5 補記：2026-11-14 更新；程式變更以 `a9b7ad1`、`c2d68a1`、`d43ea57` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 分類頁 P2 補記：2026-11-15 更新；程式變更以 `86a1876`（測試）、`c6a83bb`（實作）記入 update-history。原查核基準保留，未重新審查其餘內容。

查核：2026-10-24；HEAD `91333c3`。主 authority 是 [UI Flow](../../Docs/ui/ui-flow.md)；JSON 合約見 [API](../../Docs/api/api-spec.md)，領域用語見 [CONTEXT](../../CONTEXT.md)，安全／資料規則見 [Identity](../../Docs/modules/identity-auth.md)、[Library](../../Docs/modules/user-library.md)、[Catalog](../../Docs/modules/book-catalog.md)、[Recommendation](../../Docs/modules/recommendation.md)。本文件不是第二份規格。

## 組合與依賴

完整頁以 [_ViewStart](../_ViewStart.cshtml) 選 [_Layout](../Shared/_Layout.cshtml)，[_ViewImports](../_ViewImports.cshtml) 啟用 Tag Helpers。Layout 是 zh-Hant 文件，title 為頁名＋站名，導覽依 auth state 分支，載入本機 Bootstrap、jQuery、site.js 與頁面 Scripts section。[_Layout.cshtml.css](../Shared/_Layout.cshtml.css) 是 MVC scaffold scoped CSS，與 wwwroot/css/site.css 共同影響外觀；bundle `Book_Finder.styles.css` 的實際產出未在本次驗證。

| 呈現責任 | 模型／caller | partial 與輸出契約 |
|---|---|---|
| 首頁／書庫 | HomeController、BooksController、HomeViewModel、BookBrowseViewModel、BookListItemViewModel | _SearchForm 共用 GET 搜尋；首頁 10 本隨機樣本與書庫分頁共用 _BookList（封面占位、作者、出版社、出版日期）；空庫顯示「書庫還沒有書」；/bestsellers 只 301 至 /books，無榜單頁 |
| 搜尋 | SearchController、SearchResultsViewModel、PagerViewModel | query 預填、總數／頁數、結果列由 _BookList 呈現、_Pager；搜尋完全是 local DB |
| 分類瀏覽 | CategoriesController、CategoryBrowseViewModel、BookListItemViewModel | 單欄頁面，由上而下為：[_SearchForm](../Shared/_SearchForm.cshtml)（包在 `data-tour="category-search"`，GET `/search?q=`，不帶分類或來源）→ H1 → [_CategoryGrid](../Categories/_CategoryGrid.cshtml)（`nav.category-grid-nav`，一次渲染 `Model.Categories` 全部項目，全部書籍在前；每格為連結與「N 本」，零本也顯示；選取項目帶 `is-active` 與 `aria-current="page"`；不截斷、不補空格）→ 「書籍來源」標題與來源 nav-pills（`nav[aria-label=來源篩選]`，包在 `data-tour="category-sources"`）→ 摘要、_BookList、_Pager。已沒有側欄、offcanvas、切換按鈕、`<noscript>` 清單，也不載入分類頁專用 JS。欄數由 CSS 決定：2／3／4／6 欄，斷點 0／576／768／1200px；目前規則檔的 18 類加「全部書籍」共 19 格，6 欄時排成四列。樣式在 [category-browser.css](../../wwwroot/css/category-browser.css)，經 Layout 的 `Styles` section 載入 |
| Book 詳情 | BooksController、BookDetailViewModel | 基本資料／safe 外連；LibrarySection 另外放 ViewData，避免將個人資料塞入 catalog cache |
| 會員中心 | MemberController、MemberPageViewModel、LibraryPageViewModel | [Member/Index](../Member/Index.cshtml) 三區塊；書單區塊呈現 [_LibraryContent](../Shared/_LibraryContent.cshtml)（tabs、每列 _LibraryControls、頁面 token、空狀態）；AI 區塊呈現 [_RecommendationJobList](../Shared/_RecommendationJobList.cshtml)；tab 連結由 base path `/account` 與 fragment `#library` 決定；`/library` 不再有 View |
| 帳號 | AccountController、LoginForm／RegisterForm | server field errors／summary、hidden ReturnUrl/PendingAction；post success redirect |
| AI 主頁／列表 | AiController、AiHistoryListViewModel | #ai-form／#ai-status／#ai-results；_AiHistoryList 是唯一列表 HTML，fragment 不含 layout |
| AI 詳情 | AiController、AiHistoryDetailViewModel | 本人紀錄；快照 rank/reason/relevance＋即時 Book 與 difficulty |
| MCP 操作手冊 | McpGuideController（無 model） | `McpGuide/Index.cshtml` 靜態內容：MCP 網址、ChatGPT／Claude／VS Code 連線步驟與預註冊 client_id、AI 推薦與每日額度、授權、常見問題、錯誤碼對照；不含技術 metadata。內容要與 production 設定（`deploy/release/compose.prod.yaml` 的 OAuth Client、`Recommendation:DailyLimit`、token 效期）一致，任何一邊改變都要同步。Layout 導覽列右側（登入／註冊或登出之後）固定顯示「MCP 說明」連結，不分登入狀態 |
| 404／錯誤 | Books/Ai NotFound、Home.Error／ErrorViewModel | controller 明確 404；Error 只有 request ID，無 stack trace；Development pipeline 不同 |

主要依賴可查：[Controllers](../../Controllers/BooksController.cs)、[Models](../../Models/BookDetailViewModel.cs)、[ai.js](../../wwwroot/js/ai.js)、[library.js](../../wwwroot/js/library.js)、[Program](../../Program.cs)。具體入口全表見 [流程](workflow-diagram.md)。

## 選型與維護代價

| 面向 | 現況與依據 | 替代差異／代價 |
|---|---|---|
| SSR＋少量 fetch | UI Flow §1 明訂 Razor，普通表單 GET/POST，AI/Library JSON 就地更新 | SPA 會改 architecture boundary；SSR 易保留 server validation，但 JS 掛掉時 AI/Library 不可編輯 |
| ViewModel 先整形 | BookDetailViewModel、AiHistoryDetailViewModel 將日期／安全連結／空值準備好 | View 內做資料查詢會耦合且易洩私有內容；現況 View 仍負責分支與 markup |
| 共用 partial | _BookList、_SearchForm、_Pager、_LibraryControls、_LibraryContent、_AiHistoryList、_RecommendationJobList | 複製可局部自由但易文案／ARIA／狀態漂移；partial 改動需雙 caller 驗證 |
| server 渲染 controls | #12 diff 明示將 labels/stars 移回 server；JS 只更新 attributes/state | 完全 client renderer 易產兩套 labels；現況須保持 data-* selector 與 JS 同步 |
| sessionStorage 交接 | UI Flow §3.2；ai.js try/catch 封鎖情境 | query string 易把需求放 URL/log；sessionStorage 只在同 tab，無法保證關閉儲存時交接 |
| HTML fragment refresh | UI Flow §3.4；只一份 _AiHistoryList markup | JSON list renderer 需重複 pager/time/empty 邏輯；outerHTML 只接受同源成功片段，仍須維持 SSR encoding |
| Bootstrap／本機 assets | Layout 可見選擇；未找到本次範圍內的獨立 UI framework ADR | 自製 CSS 可更精細但要更多維護；本次不主張設計系統重寫 |
| client validation partial | scaffold 檔存在但沒有引用 | 加入可改善回饋，但不取代 server；先決定是否需要，不把未引用當已確認產品缺陷 |

## 安全、個人化與內容

Razor `@` 輸出採 HTML encoding，本次 source 未發現 Html.Raw。AI 文字／LLM reason 用 textContent；history 的 HTML 插入來自同源 server partial，不能延伸為接受任意 HTML。BookDetailViewModel 只保留 absolute http(s) source/cover，外連 target=_blank、rel=noopener noreferrer。各種 cover 的正規化由對應模型／reader負責，不能僅靠 Razor encoding 阻擋危險 scheme。

Book.Description／TableOfContents 不屬任何顯示資料，不能加進 View/API；理由不能大段引用原文。既有 BookDetailPageTests、SearchPageTests 有 seeded content 排除斷言，其他頁新增欄位仍需契約查核。

[Auth 註冊](../../Infrastructure/Identity/AuthServiceCollectionExtensions.cs) 設全域 AutoValidateAntiforgeryToken。Account/logout FormTagHelper 自動產 token；AI 明確 AntiForgeryToken，Library 各頁明確產一次 controls 用 token。登入頁上的 navbar 可能另有 logout form，談「一次 token」時須限制 Library 區域，而非斷言所有 authenticated document 只有一個 input。JS 送 RequestVerificationToken 與 same-origin credentials；API 401 是 ProblemDetails，protected page 是 redirect。

View 不讀 JWT、不做權限判定；隱藏控制項不等於授權。Book catalog cache 是通用 metadata，LibrarySection 每次獨立查；不 cache 個人化完整頁。登出是 POST，成功移除 auth cookie。ReturnUrl/PendingAction 可以回填但只在 controller/service 驗證後採用；密碼不回填。日期由模型轉 Taipei，View 不自行改 timezone。

## 失敗邊界與限制

搜尋與 AI 主頁超頁 redirect 由 controller；fragment 超頁回末頁 HTML。Book/AI invalid ID 404 在 controller，View 本身無法設定此政策。Error 仍是英文 scaffold，無 exception stack，但有開發模式教學；是否調整為正式中文文案是改善提案 VIEW-B03，不當成實際安全漏洞。

ai.js 沒 browser AbortController timeout，server 60 秒限制才是契約；history refresh 失敗保留舊列表。library.js PATCH 失敗還原 server 確認值；filtered list 修改狀態後不立即重查，與 server filter 的即時一致性尚待產品決策。完整 E2E 在 [test-plan](../../Docs/testing/test-plan.md) 明確 MVP 不做；[WebFixture](../../tests/WebIntegration/WebFixture.cs) 使用 NullFileProvider、HttpClient 不執行 JS，因此 HTML tests 不能證明 assets 可用或互動成功。

互參：[流程](workflow-diagram.md)、[待辦](backlog.md)、[歷史](update-history.md)、[案例](test-suite.md)。本次未 build/test/render/browser/network。

## 推薦工作頁面（Job 計畫 M7）

- [Ai/Index.cshtml](../Ai/Index.cshtml)：`#ai-form` 輸出 `data-recommendation-jobs="true|false"`；開關開啟時在表單下方加入 [_RecommendationJobList](../Shared/_RecommendationJobList.cshtml)（標題由 `ViewData["RecommendationJobListHeading"]` 傳入，`/ai` 設為「推薦工作」；空狀態「還沒有推薦工作」、`/ai?jobsPage=N` 分頁）。原本的推薦紀錄列表不變；兩個列表的分頁連結各自只帶自己的頁碼。
- [Ai/Job.cshtml](../Ai/Job.cshtml)：根元素 `#ai-job` 帶 `data-job-status-url`（由 view model 的 `StatusUrl` 產生，與 API 的 `statusUrl` 同一個來源）、`data-job-status`；排隊或執行中顯示「已加入工作佇列，可以離開網站，稍後回來查看。」，成功顯示「查看推薦結果」連到 `/ai/history/{searchId}`，失敗顯示依 error code 而定的固定文案；只載入 `ai-job.js`。
- 需求文字全部經 Razor 編碼。

## 帳號刪除（會員中心 D1）

- `Views/AccountDeletion/Index.cshtml`：確認頁，列出會刪除的資料（帳號、個人書單、AI 推薦工作與搜尋紀錄、MCP 連線授權），說明公開書籍不受影響，並提示「刪除後無法復原」。表單含密碼欄（`type=password`，不回填值）與「我了解刪除後無法復原」勾選框（`checked` 只反映 ModelState 的回填）；錯誤顯示於 `asp-validation-for` 欄位。
- `Views/Member/Index.cshtml` 的 `#account-security` 內加入「刪除帳號」連結，供 C4 之後加入「重設密碼」使用同一區塊。
- Header（會員中心 A3，使用者 2026-11-15 確認）：「個人書單」只在登入後顯示，位於右側會員名稱左邊；未登入時右側只有「登入」「註冊」「MCP 說明」，左側不再有「個人書單」。
- `Views/Shared/_Layout.cshtml` 在 `main` 內顯示 `TempData["Notice"]`（`role="status"`），只在刪除後的首頁出現一次。這是目前唯一的一次性通知機制。
- 所有新增頁面的文字皆為繁體中文；Razor 會把非 ASCII 的動態訊息編碼成數字字元參照，測試需解碼。

## 會員中心 C3：驗證頁面與登入提示（新增）

| 檔案 | 用途 | 表單與安全 |
|---|---|---|
| [Views/AccountVerification/VerifyEmail.cshtml](../AccountVerification/VerifyEmail.cshtml) | 確認頁（GET 連結可用時） | `method=post action=/account/verify-email`，`@Html.AntiForgeryToken()`；隱藏欄位 Token、ReturnUrl、PendingAction。Token 只出現在這個表單與 URL 中。 |
| [VerificationLinkInvalid.cshtml](../AccountVerification/VerificationLinkInvalid.cshtml) | 「連結無效或已過期」 | 沒有表單；只提供重寄頁連結。 |
| [VerificationSent.cshtml](../AccountVerification/VerificationSent.cshtml) | 註冊後「請收信」頁 | 顯示收件地址；`SendFailed` 時顯示「驗證信寄送失敗，帳號已建立」。沒有表單。 |
| [Resend.cshtml](../AccountVerification/Resend.cshtml) | 重寄驗證信 | 只有 Email 欄位，`@Html.AntiForgeryToken()`；POST 後顯示統一通知（ViewData Notice）。 |
| [Views/Account/Login.cshtml](../Account/Login.cshtml) | 登入頁 | 新增：`Notice`（「Email 已驗證，請登入」）與 `ShowResendLink`（「請先完成 Email 驗證」時出現的重寄連結）。其餘不變。 |

**安全**：token 頁的標頭由 `TokenLinkPage` 控制，view 本身不設定。429 頁是 `AccountRateLimiting` 的 inline HTML，不經過 view。

**第三方資源**：檢查 [_Layout.cshtml](../Shared/_Layout.cshtml) 後，確認只載入同源資源，沒有第三方 CDN；`importmap` 為空。

**文案**：所有新文案為本次撰寫（繁中），尚未經過使用者審閱，見 backlog VIEW-B07。

## 會員中心 C4：忘記密碼與重設頁（新增）

- `Views/PasswordReset/Forgot.cshtml`：只有 Email 欄位與 antiforgery；`Notice` 區塊顯示固定通知（`alert alert-success py-2`）。
- `Views/PasswordReset/Reset.cshtml`：新密碼與確認新密碼欄位（`autocomplete="new-password"`），隱藏欄位 `Token`，驗證錯誤用 `asp-validation-for` 顯示在欄位旁。表單不回填密碼。
- `Views/PasswordReset/LinkInvalid.cshtml`：「連結無效或已過期」，連結到忘記密碼頁。沒有表單，也沒有 token。
- `Views/Account/Login.cshtml`：開關開啟時，在「重寄驗證信」連結下方顯示「忘記密碼？」。
- `Views/Member/Index.cshtml`：`#account-security` 在開關開啟時多一個「重設密碼」連結，位於「刪除帳號」之上。
