# Views Git 修改歷史

> Header P1 補記：2026-11-15 更新；程式變更以 `e355171`、`f4ccdc4` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 會員中心 C3 補記：2026-11-15 更新；程式變更以 `c3f09dc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 非同步推薦 Job M7 補記：2026-11-14 更新；程式變更以 `4db0c98`、`e00cbb5`、`5559870`、`ac88ef2` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P5 補記：2026-11-14 更新；程式變更以 `a9b7ad1`、`c2d68a1`、`d43ea57` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 分類頁 P2 補記：2026-11-15 更新；程式變更以 `86a1876`（測試）、`c6a83bb`（實作）記入 update-history。原查核基準保留，未重新審查其餘內容。

查核基準 `91333c3` 的 source history 如下；`Views/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

查核日期：2026-10-24；HEAD `91333c3`。直接來源範圍：`Views`，排除 `Views/docs`；完整可達歷史共 22 筆，非 shallow。排序為 `git log --reverse` 的反向 log 次序；日期欄是 author date（`%ad --date=short`），不是 committer／部署／測試日期。全部 author 為 Arthur801；co-author trailers 不改 author 欄位。

```bash
git log --reverse --format='%H %ad %an %s' --date=short --stat 91333c3 -- Views ':!Views/docs'
git show dc4a570 -- Views
git show 668d0fb -- Views
git show 53c0391 -- Views
git show 66ecf55 -- Views
git show c961620 -- Views
git show 217e035 -- Views
git show 4217ddc -- Views
git show 0948897 -- Views
git show 852591c -- Views/Ai/Index.cshtml
git show 894883b -- Views
```

已查全部目標 stat 與目前全部來源；語意不明及重要重構讀上列 diffs，其他建立／樣式變更摘要由 path stat＋當前內容定位，不冒稱逐行閱讀每個 commit 的所有跨目錄檔案。

| Author 日期／SHA | Subject | 目標內變化／查核範圍 |
|---|---|---|
| 2026-10-11／`eb93cd512d5d8e31ea8aa26f29b4a700bcd116bb` | Initialize dotnet mvc project | 新增 MVC scaffold：Home Index/Privacy、Layout/scoped CSS、Error、validation partial、ViewImports/ViewStart。Privacy 後來移除；不是現況頁面。 |
| 2026-10-11／`976d9fe01d8355408f53472b8d0708d46c41f89f` | Add bestseller pages and web integration test harness (#5) | 新增 Bestsellers/Index、_BestsellerEntries；首頁換找書與榜單入口，移除 Privacy，Layout 改為站名與領域導覽。subject 的 test harness 屬 Views 外依賴。 |
| 2026-10-11／`dc4a5703f0ddc0383858dae6a513b1a0632252f8` | Address code review findings (#5) | 實際 Views diff 僅補首頁／榜單 ViewData Title，未在 Views 改 cache 或 DB 行為。已讀完整目標 diff。 |
| 2026-10-11／`b4d2aafef766832a438edfe0bf99039b3229b127` | Add Book detail page at /books/{id} | 新增 Book Detail 與 NotFound：基本書目、contributor/info rows、外部來源 link 與封面占位。 |
| 2026-10-11／`668d0fb133e0d77666e1c33cbe070db3d37a467f` | Address M5 code review: safe links, blank subjects, titles, test helpers | Views 內只新增 Detail 與 NotFound 的 Title。safe links/blank subjects 的 substantive 邏輯在 Models，不能把 subject 全當 Views diff。已讀目標 diff。 |
| 2026-10-11／`0efed0bbe93f6aad7f1ca06ed7cc3e98f789f92f` | Add the general search results page at /search | 新增 Search/Index、共用 _SearchForm，首頁改引用 partial；結果欄位、空態與最初 pager markup。 |
| 2026-10-11／`53c039188ca08b5908aafad60415ab064dc6a908` | Redirect search pages past the last page to the last page | Search 增 data-book-id，依 ViewModel null 判斷 optional rows；pager 加 rel/ARIA、class hook。302 是 Controller 變更，不是 Razor redirect。已讀目標 diff。 |
| 2026-10-20／`6faf1e21d815b332052d57fba3ee6a2b99aaea68` | Add login, registration and logout pages | 新增 Login/Register forms：server validation summary/field messages、hidden ReturnUrl/PendingAction、相互連結。 |
| 2026-10-20／`0b60633eb65bd42da365df49ed3beb0fa6ad005b` | Show the signed-in user and a logout button in the navbar | Layout 依 auth 顯示 display name＋POST logout form 或 login/register links。 |
| 2026-10-21／`4081d412fc02fc08a47d7791fac75cae84ef9ff7` | Add the /ai page and its WebIntegration tests | 新增 AI form/status/results/token/scripts；首頁 AI textarea 移除 name 並載入 ai.js，交接文字不放 URL。 |
| 2026-10-22／`becc5e208be37a96143357bae636f584cbabb138` | Add Library section to the Book detail page (#11 M4) | Book Detail 加 Library 區塊和 library.js；新增 _LibrarySection 最初登入／匿名／已有 entry 分支。 |
| 2026-10-22／`7f61fcc8010be9d020c7f5fbb84c9be5775b1264` | Add /library page with filter tabs and read-only rows (#11 M6) | 新增 Library/Index 篩選 tabs 與唯讀 rows；_LibrarySection 的登入 URL 改用模型。唯讀是歷史階段，非當前能力。 |
| 2026-10-22／`c9616207912a01b523eb1c196f2bd7acb6934a78` | Build the Library login URL once and reuse it in library.js | _LibrarySection add button 增 data-login-url，讓 JS 使用 server 建立的 pending-add URL。已讀一行 diff。 |
| 2026-10-22／`66ecf5558eed4cdbe2b87cdfbbc0aa5c338cc54a` | Add shared library controls to the Book page and /library (#12 M4) | 新增 _LibraryControls 共用 status/stars/clear/remove/error；Book 預先 render add/controls 以 hidden 切換；Library 改可編輯，Library interaction area 新增一枚共用 token，controls 不逐列產 token；空態預先存在並載入 library.js。完整 authenticated document 的 logout form 可另有 token。已讀三檔重要 diff。 |
| 2026-10-22／`ef2b9295ab61817d4c4e9f6c5d23f6a77741ff26` | Show 未評分 next to the stars for an unrated entry | _LibraryControls 加未評分 span，rating null 時可見，JS 切 hidden。 |
| 2026-10-22／`217e035dd39ce94e14b9173d2c473541ae2daff3` | Point the Library comments at the spec sections that hold the rules | _LibraryControls 僅修正註解引用到 user-library §4/5；不宣稱功能改變。已讀 diff。 |
| 2026-10-22／`4217ddca6136c488622c7668afafa741c15f2449` | Keep one list of reading statuses in ReadingStatusCode.All | controls foreach 改讀 ReadingStatusCode.All，避免狀態順序多份定義。已讀 diff。 |
| 2026-10-22／`09488970e6604d500fea7f6c41ff910d29578f16` | Derive the Library section state from its controls | _LibrarySection 直接 pattern-match Controls 而非 IsSignedIn，再用匹配變數傳 partial；減少冗餘旗標／null-forgiving，HTML 不變。已讀 diff。 |
| 2026-10-22／`e288509f5a93211b9e7f93b86fadde1887178a14` | Drop the link underline under the rating stars | 星星 button 加 text-decoration-none 移除連結底線；不影響 rating API。 |
| 2026-10-22／`852591cf90c3f4c844a0db2809d29b9740d1eb94` | Show the AI search history list on /ai (#16 M2) | AI Index 加 AiHistoryListViewModel 與 partial；新 _AiHistoryList 有全文 title、時間／數量、empty/pager。已讀 Index diff並核對當前完整 partial。 |
| 2026-10-22／`ddb4f9af68bb4058dae1cb20d698ced960da86a8` | Show a saved AI search on /ai/history/{id} (#16 M3) | 新增 Ai/History 與 NotFound：需求全文、rank／reason／relevance、Book link／cover／difficulty、零結果與404文案。 |
| 2026-10-22／`894883b9ece1033ae7a11a47d3220e64b5c8b8f0` | Share one pager between /search and the AI history list (#16 review) | Search 與 AI history 移除重複 pager markup；新增 _Pager，caller 傳 PagerLabel，class 改 pager。已讀完整目標 diff。 |

## Views 外的相關依賴歷史

只列本次追蹤的重要 JavaScript 變化，不宣稱完整 wwwroot 歷史。author 均 Arthur801，日期仍為 author date。

| 日期／SHA | 變化與證據 |
|---|---|
| 2026-10-22／`f0e1f0f` | Refresh the AI history list after a successful search (#16 M4)。已查路徑 log 與 ai.js 現況：成功推薦 fetch history-list page1、替換同一 SSR partial；未逐行讀該 commit diff。 |
| 2026-10-22／`b2c72a0da3e29fdc70ac6f65457a097049102991` | Keep the history list when the refresh is redirected to login (#16 review)。已讀 ai.js diff：response.redirected 視失敗，還要驗 id=ai-history，避免 fetch 跟隨302後把200登入完整頁寫入列表。這是已修歷史問題，不是待修 bug。 |
| 2026-10-22／`bd429ea` | Show the daily-limit message on a 429 from the AI recommendation (#15 M6)。查路徑 log＋目前 ai.js 專用429訊息，未讀完整 commit diff；View markup 本身沒有 daily-limit 判定。 |

## 維護轉折與限制

從 scaffold 轉領域 SSR 頁面，接著帳號與 AI，最後 Library 可編輯 controls 與 AI history partial/pager 共享。現在主要行為可在 JS、Models、Controllers 演進而不改 Views，因此本歷史不是完整產品能力清單。

歷史來源排除產出 docs，避免把文件 commit 混成實作；Git source 不能證明 assets 已提供、瀏覽器互動通過、DB migration 已套用或 production 部署完成。

互參：[流程](workflow-diagram.md)、[架構](architecture.md)、[待辦](backlog.md)、[案例](test-suite.md)。

## #109 M2 書庫 Web 呈現（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 分支／提交 | Subject | 影響 |
|---|---|---|
| `a8a5077` | feat(web): show 書庫 on home and /books in place of the bestseller ranking | 新增 Books/Index 與 Shared/_BookList；Home、Search 改用 _BookList；導覽與 Library 空態連結改 `/books`；刪除 Bestsellers/Index 與 _BestsellerEntries |
| `2642182` | test(web): cover 書庫 paging, home sample and the /bestsellers redirect | 無 View 行為變更；Web 測試改驗書庫與首頁 markup，刪除 BestsellerPageTests |
| 本 M2 docs commit | docs(web): record 書庫 Web presentation in folder docs | 更新 Views 文件的路由表、流程與案例 |
| 本次 backlog 整理 commit | docs(backlog): tidy views backlog after #113 PR2 | `docs/backlog.md`：VIEW-B05 移出表格至「已處理」；補記標頭；未改程式 |

## Canonical Category P5 分類頁（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-14 | `a9b7ad1` | feat(categories): add the 分類 browse page with sidebar and source filter | `Categories/Index.cshtml`、`Categories/_CategorySidebar.cshtml`、`Categories/NotFound.cshtml`（新增）；`Shared/_Layout.cshtml`（`Styles` section、導覽列「分類」）；目錄外：`wwwroot/js/category-sidebar.js`、`wwwroot/css/category-browser.css` |
| 2026-11-14 | `d43ea57` | fix(categories): show the sidebar buttons only when JavaScript runs | `Categories/Index.cshtml`（兩個按鈕加 `js-only`）；目錄外：JS 與 CSS 對應修改。瀏覽器檢查發現 |

## 非同步推薦 Job M7（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-14 | `e00cbb5` | feat(rec-jobs): show the job list on /ai and the job status page | `Ai/Index.cshtml`、`Ai/_AiJobList.cshtml`（新增）、`Ai/Job.cshtml`（新增） |
| 2026-11-14 | `48b2edd` | feat(mcp): OAuth consent page (MCP-201b) | `OAuth/Consent.cshtml`（新增）：client 名稱、scope 說明、登入 email、允許／拒絕，原 OAuth 參數以 hidden 欄位回送 |

## 2026-11-15 MCP 操作手冊頁（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | 本 PR | feat(mcp): public MCP guide page linked from the navbar | `McpGuide/Index.cshtml`（新增）；`Shared/_Layout.cshtml`：導覽列右側加「MCP 說明」連結；目錄外：`wwwroot/css/site.css` 加 `.mcp-guide` 寬度 |

## 會員中心 A1 共用 partial（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | 本分支 | refactor(views): share the library list and job list partials (member center A1) | `Shared/_LibraryContent.cshtml`（新增，由 `Library/Index.cshtml` 抽出 tabs、token、空態、rows）；`Shared/_RecommendationJobList.cshtml`（由 `Ai/_AiJobList.cshtml` 移入，標題改由 ViewData 傳入）；`Library/Index.cshtml` 改為標題加 partial；`Ai/Index.cshtml` 改呼叫新 partial 並設定標題。以既有 WebIntegration 斷言驗證；未做 HTML 逐字比對。 |

## 會員中心 A3：/account 頁面與 Header（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | 本分支 feat commit | feat(member): member center at /account, /library redirect and header (A3) | `Member/Index.cshtml`（新增：會員中心三區塊）；`Shared/_Layout.cshtml`：左側移除「個人書單」，登入後右側加「個人書單」與名稱連結；`Library/Index.cshtml` 刪除；`Shared/_LibraryContent.cshtml` 註解更新 |

## 會員中心 D1：帳號刪除頁與一次性通知（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | 本分支 feat commit | feat(member): account deletion with password and confirmation (D1) | `AccountDeletion/Index.cshtml`（新增）；`Member/Index.cshtml`（帳號安全區塊加連結）；`Shared/_Layout.cshtml`（`TempData["Notice"]`） |

使用者可見行為：會員中心可進入刪除帳號；刪除後首頁顯示一次「帳號已刪除」。

## 會員中心 C3：驗證頁面與登入提示（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | `c3f09dc` | feat(identity): email verification, resend, login gating and per-IP limits (C3) | `AccountVerification/VerifyEmail.cshtml`、`VerificationLinkInvalid.cshtml`、`VerificationSent.cshtml`、`Resend.cshtml`（新增）；`Account/Login.cshtml`（Notice 與重寄連結） |

驗證（2026-11-15）：`dotnet build --no-incremental` 0 warning、0 error；WebIntegration 494 通過（含 `EmailVerificationFlowTests` 與 `EmailVerificationSwitchOffTests`，C3 相關頁面斷言見 test-suite）。

行為變更（開關關閉）：無；登入頁只有在 `ShowResendLink` 或 `Notice` 存在時多出區塊。

## 會員中心 C4：忘記密碼與重設頁（新增紀錄）

- 2026-11-15：`feat(identity): forgot password by email with transactional reset (C4)`，commit `8934ba4`。新增 `Views/PasswordReset/` 三個頁面；`Views/Account/Login.cshtml` 增加「忘記密碼？」連結；`Views/Member/Index.cshtml` 的 `#account-security` 增加「重設密碼」連結（開關開啟時）。
- 驗證（2026-11-15，commit `8934ba4` 之後）：`dotnet build --no-incremental` 0 warning、0 error；`dotnet test tests/UnitTests` 1326 通過；`tests/DatabaseIntegration` 313 通過；`tests/WebIntegration` 522 通過。
- 行為變更（開關關閉）：無，三個頁面不可達，兩個連結不顯示。

## 2026-11-15 會員中心 review 決策（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | 本次 commit | docs(member): record the review decisions | `docs/architecture.md`：記錄使用者確認的 header 規則（「個人書單」只在登入後顯示） |


## 分類頁 P2：搜尋與分類網格（新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | `86a1876` | test(categories): assert the category grid and page order instead of the sidebar | 目錄外：`tests/WebIntegration/CategoryPageTests.cs`、`tests/UnitTests/CategoryBrowseViewModelTests.cs`。先寫測試；此 commit 單獨檢出時，側欄相關斷言為紅燈，屬 TDD 中間狀態 |
| 2026-11-15 | `c6a83bb` | feat(categories): replace sidebar with responsive inline category grid | `Categories/Index.cshtml`（單欄：搜尋、H1、網格、來源、結果）；`Categories/_CategoryGrid.cshtml`（新增）；`Categories/_CategorySidebar.cshtml`（刪除，grep 確認無其他 caller）；`Models/CategoryBrowseViewModel.cs`（只改註解）；目錄外：`wwwroot/css/category-browser.css`（重寫）、`wwwroot/js/category-sidebar.js`（刪除） |
| 2026-11-15 | 本 commit | docs(views): record the category grid and search on /categories | 本目錄五份文件 |

驗證（2026-11-15，`c6a83bb` 之後）：`dotnet build --no-incremental` 0 warning、0 error；`dotnet test tests/WebIntegration --filter "FullyQualifiedName~CategoryPageTests|FullyQualifiedName~SearchPageTests"` 57 通過、0 失敗；`dotnet test tests/UnitTests` 1330 通過、0 失敗。未執行：瀏覽器版面與 JS 停用時的點選（見 VIEW-T27）。

行為變更：`/categories` 不再有側欄、抽屜、收合按鈕與 `<noscript>` 清單；新增頁首搜尋（`GET /search?q=`）；分類連結、數量、`aria-current`、來源、分頁、404 與超頁轉址契約不變。瀏覽器 localStorage 裡的舊 key `bookfinder.categorySidebarCollapsed` 不再被讀取，留著無害。

## Header「更多」選單（P1，新增紀錄）

| Author 日期 | SHA | subject | 本目錄實際改動檔案 |
|---|---|---|---|
| 2026-11-15 | `e355171` | test(navbar): expect the More dropdown with library, MCP, guide and logout | 無 Views 檔案；`tests/WebIntegration`：`NavbarTests.cs`、`LayoutAndHomeTests.cs`、`McpGuidePageTests.cs`、`HtmlPage.cs`（新增 `Header` 與 `MoreMenu` 輔助方法） |
| 2026-11-15 | `f4ccdc4` | feat(ui): consolidate library, MCP and logout into More menu | `Shared/_Layout.cshtml`：左側移除「書庫」；右側新增「更多」dropdown（個人書單、MCP 說明、功能導覽、分隔線、登出）；新增 noscript fallback；會員名稱與登入／註冊保留 |
| 2026-11-15 | 本分支 docs commit | docs(views): record the More menu header in folder docs | 本目錄 `architecture.md`、`workflow-diagram.md`、`test-suite.md`、`backlog.md`、`update-history.md` |

使用者可見行為：左側不再有「書庫」；個人書單、MCP 說明、登出移入「更多」。`/books` 路由與書籍頁未變。wwwroot/docs 未更新，因本次未改 CSS 或 JS。

驗證（2026-11-15）：`dotnet build --no-incremental` 0 warning、0 error；`dotnet test tests/UnitTests` 1330 通過；`dotnet test tests/WebIntegration` 527 通過。

