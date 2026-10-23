# Models Git 修改歷史

> 查核日期：2026-10-24；基準：`91333c3`；目標：`Models/`。本次只做靜態閱讀，未執行 build、測試、Mermaid renderer、資料庫或外部服務。開始時來源無未提交修改；其他代理既有的 `Controllers/docs/` 不屬本文件範圍。

## 範圍與重跑方式

來源為 `Models` 全部已追蹤歷史（包含之後搬走或刪除的 helper），排除 `Models/docs`。倉庫不是 shallow；採 `git log --reverse` 的反向提交遍歷順序，不宣稱按 author timestamp 排序。日期欄使用 author date（建立提交時設定的時間），附 committer date（本地 Git 接受該提交時間）以免混為部署日期；作者不等於部署者。查核HEAD `91333c3`，未提交文件尚無Git歷史。

```bash
git log --reverse --date=iso-strict --format='%h|%H|%ad|%cd|%an|%s' 91333c3 -- Models ':(exclude)Models/docs'
git log --reverse -p 91333c3 -- Models ':(exclude)Models/docs'
git show 668d0fb -- Models
git show 66ecf55 -- Models
git show 894883b -- Models
git show cda623f -- Models
```

以下全量列出36筆來源提交；重要轉折已讀diff，註解提交與實作提交分開描述，不以整個commit subject推定模型責任。

| Author日期／Committer日期 | SHA／作者 | Subject | 目標內diff與檔案 |
|---|---|---|---|
| 2026-10-11T00:24:40+08:00 / 2026-10-11T00:24:40+08:00 | `eb93cd5`／Arthur801 | Initialize dotnet mvc project | 建立 ErrorViewModel 的 RequestId／ShowRequestId。 `Models/ErrorViewModel.cs` |
| 2026-10-11T05:12:08+08:00 / 2026-10-11T05:12:08+08:00 | `976d9fe`／Arthur801 | Add bestseller pages and web integration test harness (#5) | 新增 BestsellerListViewModel／Entry：保留 rank、作者串接、台北更新文字。 `Models/BestsellerListViewModel.cs` |
| 2026-10-11T05:23:00+08:00 / 2026-10-11T05:23:00+08:00 | `dc4a570`／Arthur801 | Address code review findings (#5) | 新增 TaipeiTimeZone fallback；Bestseller formatter 開放注入 zone。 `Models/BestsellerListViewModel.cs`、`Models/TaipeiTimeZone.cs` |
| 2026-10-11T13:06:57+08:00 / 2026-10-11T13:06:57+08:00 | `b5f9a34`／Arthur801 | Add catalog display rules for publish dates and contributors | 新增出版日期精度 formatter 與 Contributor 分組顯示。 `Models/ContributorDisplay.cs`、`Models/PublishedDateText.cs` |
| 2026-10-11T13:10:21+08:00 / 2026-10-11T13:10:21+08:00 | `cf26eb6`／Arthur801 | Address code review of catalog display rules | ContributorGroup Label 改從 Role 推導；日期 formatter 區域變數更名。 `Models/ContributorDisplay.cs`、`Models/PublishedDateText.cs` |
| 2026-10-11T13:22:34+08:00 / 2026-10-11T13:22:34+08:00 | `b4d2aaf`／Arthur801 | Add Book detail page at /books/{id} | 新增 BookDetailViewModel、InfoRows、BookLink，排除簡介與目錄。 `Models/BookDetailViewModel.cs` |
| 2026-10-11T13:29:52+08:00 / 2026-10-11T13:29:52+08:00 | `668d0fb`／Arthur801 | Address M5 code review: safe links, blank subjects, titles, test helpers | 封面／來源限安全http(s)、空白分類過濾，OTHER identifier 違反前置條件時拋錯。 `Models/BookDetailViewModel.cs` |
| 2026-10-11T13:29:04+08:00 / 2026-10-11T13:37:06+08:00 | `8684513`／Arthur801 | Add pagination window for catalog search results | 新增 PageWindow，首尾頁與中央視窗、省略號。 `Models/PageWindow.cs` |
| 2026-10-11T13:29:04+08:00 / 2026-10-11T13:37:06+08:00 | `0efed0b`／Arthur801 | Add the general search results page at /search | 新增 SearchResultsViewModel、搜尋query編碼與分頁顯示。 `Models/SearchResultsViewModel.cs` |
| 2026-10-11T13:44:09+08:00 / 2026-10-11T13:44:09+08:00 | `53c0391`／Arthur801 | Redirect search pages past the last page to the last page | 調整搜尋分頁上一／下一鏈結，避免超過最後頁；重導在Controller。 `Models/SearchResultsViewModel.cs` |
| 2026-10-20T21:35:11+08:00 / 2026-10-20T21:35:11+08:00 | `6faf1e2`／Arthur801 | Add login, registration and logout pages | 新增 LoginForm／RegisterForm nullable欄位及returnUrl／pendingAction。 `Models/LoginForm.cs`、`Models/RegisterForm.cs` |
| 2026-10-20T21:43:46+08:00 / 2026-10-20T21:43:46+08:00 | `a57d58d`／Arthur801 | Share the account form helpers between web tests | 只更新form驗證責任註解：AccountService套用AccountInputRules。 `Models/LoginForm.cs`、`Models/RegisterForm.cs` |
| 2026-10-21T13:57:30+08:00 / 2026-10-21T13:57:30+08:00 | `337fb21`／Arthur801 | Move PublishedDateText into the catalog application layer | 刪除Models/PublishedDateText，搬至Application/Catalog；呼叫端namespace同步。 `Models/PublishedDateText.cs` |
| 2026-10-21T14:03:01+08:00 / 2026-10-21T14:03:01+08:00 | `22542ca`／Arthur801 | Add the POST /api/recommendations endpoint | 新增RecommendationRequest／Response及子DTO；當時fallback固定false、difficulty=null。 `Models/RecommendationRequest.cs`、`Models/RecommendationResponse.cs` |
| 2026-10-22T07:54:52+08:00 / 2026-10-22T07:54:52+08:00 | `f258880`／Arthur801 | Add PUT /api/library/{bookId} add-to-library endpoint (#11 M3) | 新增LibraryEntryResponse，ReadingStatus轉code與台北時間。 `Models/LibraryEntryResponse.cs` |
| 2026-10-22T07:59:37+08:00 / 2026-10-22T07:59:37+08:00 | `becc5e2`／Arthur801 | Add Library section to the Book detail page (#11 M4) | 新增Book detail的LibrarySectionViewModel與匿名登入連結。 `Models/LibrarySectionViewModel.cs` |
| 2026-10-22T09:41:48+08:00 / 2026-10-22T09:41:48+08:00 | `0c11ea2`／Arthur801 | Run pending add-to-library after login and registration (#11 M5) | LoginForm註解改為成功登入會執行pending action；執行本身在外部Controller／Application。 `Models/LoginForm.cs` |
| 2026-10-22T09:45:52+08:00 / 2026-10-22T09:45:52+08:00 | `7f61fcc`／Arthur801 | Add /library page with filter tabs and read-only rows (#11 M6) | 新增LibraryPageViewModel、篩選tabs、rows及RatingText。 `Models/LibraryPageViewModel.cs`、`Models/RatingText.cs` |
| 2026-10-22T09:55:48+08:00 / 2026-10-22T09:55:48+08:00 | `c961620`／Arthur801 | Build the Library login URL once and reuse it in library.js | LibrarySection登入連結改共用PendingLibraryAction常數。 `Models/LibrarySectionViewModel.cs` |
| 2026-10-22T09:56:24+08:00 / 2026-10-22T09:56:24+08:00 | `5a827b1`／Arthur801 | Share the UTC to Taipei conversion between library and recommendation responses | Library與Recommendation response共用TaipeiTimeZone.FromUtc。 `Models/LibraryEntryResponse.cs`、`Models/RecommendationResponse.cs`、`Models/TaipeiTimeZone.cs` |
| 2026-10-22T09:56:29+08:00 / 2026-10-22T09:56:29+08:00 | `0d180a4`／Arthur801 | Cite the Library plan for the rating display format | RatingText僅調整規格來源註解，無行為變更。 `Models/RatingText.cs` |
| 2026-10-22T10:01:59+08:00 / 2026-10-22T10:01:59+08:00 | `e5c57c8`／Arthur801 | Add PATCH body parser and library change model (#12 M1) | 新增LibraryPatchParser、Valid／Invalid，明確分省略／null／設定。 `Models/LibraryPatchParser.cs` |
| 2026-10-22T10:20:14+08:00 / 2026-10-22T10:20:14+08:00 | `66ecf55`／Arthur801 | Add shared library controls to the Book page and /library (#12 M4) | 新增共享LibraryControlsViewModel，Library rows／section攜帶controls，刪RatingText。 `Models/LibraryControlsViewModel.cs`、`Models/LibraryPageViewModel.cs`、`Models/LibrarySectionViewModel.cs`、`Models/RatingText.cs` |
| 2026-10-22T10:27:09+08:00 / 2026-10-22T10:27:09+08:00 | `217e035`／Arthur801 | Point the Library comments at the spec sections that hold the rules | Library註解改指向現行UI／模組規格，無行為變更。 `Models/LibraryControlsViewModel.cs` |
| 2026-10-22T10:27:53+08:00 / 2026-10-22T10:27:53+08:00 | `4217ddc`／Arthur801 | Keep one list of reading statuses in ReadingStatusCode.All | 移除controls狀態清單，tabs改用Application ReadingStatusCode.All。 `Models/LibraryControlsViewModel.cs`、`Models/LibraryPageViewModel.cs` |
| 2026-10-22T10:28:40+08:00 / 2026-10-22T10:28:40+08:00 | `704c9e8`／Arthur801 | Build the login link in one helper for the Library pages | 新增LoginLink，兩種Library登入連結改共用建構。 `Models/LibraryControlsViewModel.cs`、`Models/LibrarySectionViewModel.cs`、`Models/LoginLink.cs` |
| 2026-10-22T10:29:18+08:00 / 2026-10-22T10:29:18+08:00 | `0948897`／Arthur801 | Derive the Library section state from its controls | LibrarySection移除重複登入／收藏布林，InLibrary由Controls.Hidden推導。 `Models/LibrarySectionViewModel.cs` |
| 2026-10-22T10:34:51+08:00 / 2026-10-22T10:34:51+08:00 | `9b0a8a1`／Arthur801 | Move TaipeiTimeZone to Application/Common | TaipeiTimeZone搬至Application/Common，Models呼叫端增加using。 `Models/BestsellerListViewModel.cs`、`Models/LibraryEntryResponse.cs`、`Models/RecommendationResponse.cs`、`Models/TaipeiTimeZone.cs` |
| 2026-10-22T11:10:20+08:00 / 2026-10-22T11:10:20+08:00 | `b6bf8ea`／Arthur801 | Move the page number parsing into PageNumber (#16) | 新增PageNumber，從Controller抽出BigInteger解析及上限。 `Models/PageNumber.cs` |
| 2026-10-22T11:14:53+08:00 / 2026-10-22T11:14:53+08:00 | `852591c`／Arthur801 | Show the AI search history list on /ai (#16 M2) | 新增AI history列表VM、頁數／時間映射及URL。 `Models/AiHistoryListViewModel.cs` |
| 2026-10-22T11:19:23+08:00 / 2026-10-22T11:19:23+08:00 | `ddb4f9a`／Arthur801 | Show a saved AI search on /ai/history/{id} (#16 M3) | 新增AI history詳情VM；相關度格式、封面前綴與難度placeholder。 `Models/AiHistoryDetailViewModel.cs`、`Models/AiHistoryListViewModel.cs` |
| 2026-10-22T11:25:01+08:00 / 2026-10-22T11:25:01+08:00 | `a0cd6ae`／Arthur801 | Name the history read models after the glossary (#16 review) | 與Application歷史read model詞彙更名同步，採Recommendation Search用語。 `Models/AiHistoryDetailViewModel.cs`、`Models/AiHistoryListViewModel.cs` |
| 2026-10-22T11:26:53+08:00 / 2026-10-22T11:26:53+08:00 | `894883b`／Arthur801 | Share one pager between /search and the AI history list (#16 review) | 新增PagerViewModel，Search與AI history列表改內含同一Pager。 `Models/AiHistoryListViewModel.cs`、`Models/PagerViewModel.cs`、`Models/SearchResultsViewModel.cs` |
| 2026-10-22T11:27:29+08:00 / 2026-10-22T11:27:29+08:00 | `982ad1c`／Arthur801 | Format the history minute in TaipeiTimeZone, not in the list model (#16 review) | AI history時間格式改用TaipeiTimeZone.FormatMinute，刪重複formatter。 `Models/AiHistoryDetailViewModel.cs`、`Models/AiHistoryListViewModel.cs` |
| 2026-10-22T11:28:25+08:00 / 2026-10-22T11:28:25+08:00 | `f7ed758`／Arthur801 | Cite the right specs in the history reader and the page number (#16 review) | PageNumber註解來源改為UI §3.4，無行為變更。 `Models/PageNumber.cs` |
| 2026-10-22T12:09:17+08:00 / 2026-10-22T12:09:17+08:00 | `cda623f`／Arthur801 | Wire the Book AI profile into recommendations and history (issue #18 M6) | Recommendation回應以結果字典快照映射difficulty；歷史頁即時字典映射缺值為破折號。 `Models/AiHistoryDetailViewModel.cs`、`Models/RecommendationResponse.cs` |

## 維護轉折與相關依賴

- 原本在 Models 的 PublishedDateText、TaipeiTimeZone 已分別經337fb21、9b0a8a1移到 Application，現行程式不應再依賴舊namespace；RatingText由66ecf55刪除，改用server-rendered共享controls。
- 704c9e8、0948897、894883b 分別收斂登入連結、Library三態與分頁；不把這些已修重複列為待辦。
- cda623f 的跨層行為需要 Application difficulty reader／worker及Controller先準備字典，Models只投影。原始RecommendationResponse的difficulty=null是歷史狀態，現行不可再描述為一律null。
- 外部依賴：Book detail reader先過濾OTHER identifier、各service先驗證候選與使用者隔離、SafeReturnUrl先約束重導；這些不是Models自己的新增實作。本次未另外對外層全部Git歷史作全量稽核；現行caller定位見架構／流程。

## 限制

未逐檔執行 `git log --follow`，搬移透過上述commit diff交叉確認；本表是指定路徑歷史，不等於整個產品或舊路徑完整歷史。未讀CI artifact、未執行測試或部署，任何日期與subject均不構成runtime驗證。輸出文件未混入實作歷史。

相關文件：[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [測試案例](test-suite.md)。
