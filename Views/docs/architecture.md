# Views 架構與呈現契約

查核：2026-10-24；HEAD `91333c3`。主 authority 是 [UI Flow](../../Docs/ui/ui-flow.md)；JSON 合約見 [API](../../Docs/api/api-spec.md)，領域用語見 [CONTEXT](../../CONTEXT.md)，安全／資料規則見 [Identity](../../Docs/modules/identity-auth.md)、[Library](../../Docs/modules/user-library.md)、[Catalog](../../Docs/modules/book-catalog.md)、[Recommendation](../../Docs/modules/recommendation.md)。本文件不是第二份規格。

## 組合與依賴

完整頁以 [_ViewStart](../_ViewStart.cshtml) 選 [_Layout](../Shared/_Layout.cshtml)，[_ViewImports](../_ViewImports.cshtml) 啟用 Tag Helpers。Layout 是 zh-Hant 文件，title 為頁名＋站名，導覽依 auth state 分支，載入本機 Bootstrap、jQuery、site.js 與頁面 Scripts section。[_Layout.cshtml.css](../Shared/_Layout.cshtml.css) 是 MVC scaffold scoped CSS，與 wwwroot/css/site.css 共同影響外觀；bundle `Book_Finder.styles.css` 的實際產出未在本次驗證。

| 呈現責任 | 模型／caller | partial 與輸出契約 |
|---|---|---|
| 首頁／書庫 | HomeController、BooksController、HomeViewModel、BookBrowseViewModel、BookListItemViewModel | _SearchForm 共用 GET 搜尋；首頁 10 本隨機樣本與書庫分頁共用 _BookList（封面占位、作者、出版社、出版日期）；空庫顯示「書庫還沒有書」；/bestsellers 只 301 至 /books，無榜單頁 |
| 搜尋 | SearchController、SearchResultsViewModel、PagerViewModel | query 預填、總數／頁數、結果列由 _BookList 呈現、_Pager；搜尋完全是 local DB |
| Book 詳情 | BooksController、BookDetailViewModel | 基本資料／safe 外連；LibrarySection 另外放 ViewData，避免將個人資料塞入 catalog cache |
| 個人書單 | LibraryController、LibraryPageViewModel | tabs、每列 _LibraryControls、頁面 token、預先存在的空狀態 |
| 帳號 | AccountController、LoginForm／RegisterForm | server field errors／summary、hidden ReturnUrl/PendingAction；post success redirect |
| AI 主頁／列表 | AiController、AiHistoryListViewModel | #ai-form／#ai-status／#ai-results；_AiHistoryList 是唯一列表 HTML，fragment 不含 layout |
| AI 詳情 | AiController、AiHistoryDetailViewModel | 本人紀錄；快照 rank/reason/relevance＋即時 Book 與 difficulty |
| 404／錯誤 | Books/Ai NotFound、Home.Error／ErrorViewModel | controller 明確 404；Error 只有 request ID，無 stack trace；Development pipeline 不同 |

主要依賴可查：[Controllers](../../Controllers/BooksController.cs)、[Models](../../Models/BookDetailViewModel.cs)、[ai.js](../../wwwroot/js/ai.js)、[library.js](../../wwwroot/js/library.js)、[Program](../../Program.cs)。具體入口全表見 [流程](workflow-diagram.md)。

## 選型與維護代價

| 面向 | 現況與依據 | 替代差異／代價 |
|---|---|---|
| SSR＋少量 fetch | UI Flow §1 明訂 Razor，普通表單 GET/POST，AI/Library JSON 就地更新 | SPA 會改 architecture boundary；SSR 易保留 server validation，但 JS 掛掉時 AI/Library 不可編輯 |
| ViewModel 先整形 | BookDetailViewModel、AiHistoryDetailViewModel 將日期／安全連結／空值準備好 | View 內做資料查詢會耦合且易洩私有內容；現況 View 仍負責分支與 markup |
| 共用 partial | _BookList、_SearchForm、_Pager、_LibraryControls、_AiHistoryList | 複製可局部自由但易文案／ARIA／狀態漂移；partial 改動需雙 caller 驗證 |
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
