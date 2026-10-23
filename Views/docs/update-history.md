# Views Git 修改歷史

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
| 2026-10-22／`66ecf5558eed4cdbe2b87cdfbbc0aa5c338cc54a` | Add shared library controls to the Book page and /library (#12 M4) | 新增 _LibraryControls 共用 status/stars/clear/remove/error；Book 預先 render add/controls 以 hidden 切換；Library 改可編輯，單次 token、空態預先存在與 library.js。已讀三檔重要 diff。 |
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
