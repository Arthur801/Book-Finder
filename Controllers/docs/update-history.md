# Controllers 修改歷史

查核基準 `91333c3` 的 source history 如下；`Controllers/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

整理日期：2026-10-24；Git 查核基準：`91333c3`。下表列出此基準可達歷史中，**直接修改 `Controllers/*.cs`** 的全部 27 筆 commit，依 `git log --reverse` 順序呈現，不將整個 commit 的所有變更都歸入 Controller。

日期取自 Git author date（`--date=short`），不是部署日期；commit 存在不代表已部署，也不代表本次重新執行過該版本測試。歷史來源為實際 Git log / diff，不以 Implementation-Report 推定。

## 1. 查核方法

```bash
git rev-parse --short 91333c3
git log --reverse --date=short --format='%h %ad %s' 91333c3 -- 'Controllers/*.cs'
git log --reverse --name-only --format='%h %ad %s' --date=short 91333c3 -- 'Controllers/*.cs'
git show <commit> -- Controllers
```

限定 `.cs` 可避免日後本資料夾的文件 commit 被誤算為 Controller 行為變更。需追蹤被改名或刪除的單檔時，可再用 `git log --follow -- Controllers/<file>.cs`。

## 2. 逐筆歷史

| 日期 | Commit / 原始 subject | 直接影響的 Controller | Controller 層改變 |
|---|---|---|---|
| 2026-10-11 | `eb93cd5` — Initialize dotnet mvc project | Home | 建立 MVC 範本 Index、Privacy、Error；Error 帶 RequestId 並禁止 response cache。 |
| 2026-10-11 | `976d9fe` — Add bestseller pages and web integration test harness (#5) | Home、Bestsellers | Home.Index 改為非同步讀榜單前 10 筆；移除 Privacy action；新增完整榜單 Index，透過 BestsellerService 讀取並轉 ViewModel。 |
| 2026-10-11 | `dc4a570` — Address code review findings (#5) | Home、Bestsellers | 移除 Controller 指定的 ViewData Title，由 View 管理頁面標題；保留榜單讀取流程。 |
| 2026-10-11 | `b4d2aaf` — Add Book detail page at /books/{id} | Books | 新增 Detail action、GUID 解析、IBookDetailReader 查詢、查無資料的 404 View。 |
| 2026-10-11 | `668d0fb` — Address M5 code review: safe links, blank subjects, titles, test helpers | Books | Controller diff 移除 Detail／NotFound 的 ViewData Title；安全連結等其餘改變屬該 commit 的其他檔案。 |
| 2026-10-11 | `0efed0b` — Add the general search results page at /search | Search | 新增 q／page 輸入、BookSearchService 查詢與 SearchResultsViewModel 顯示。 |
| 2026-10-11 | `53c0391` — Redirect search pages past the last page to the last page | Search | 有結果而頁碼超過末頁時重導末頁，保留 q；空結果仍顯示空狀態。 |
| 2026-10-20 | `6faf1e2` — Add login, registration and logout pages | Account | 新增登入／註冊 GET、POST 與登出；AccountService outcome 對應表單錯誤、JWT cookie 及安全本站重導。 |
| 2026-10-21 | `22542ca` — Add the POST /api/recommendations endpoint | Recommendations | 新增受保護推薦 JSON action，驗證需求文字、呼叫 RecommendationService、回傳結果或 validation problem。 |
| 2026-10-21 | `4081d41` — Add the /ai page and its WebIntegration tests | Ai | 新增需登入的 `/ai` 頁面；不從 URL 讀取需求文字。 |
| 2026-10-22 | `f258880` — Add PUT /api/library/{bookId} add-to-library endpoint (#11 M3) | LibraryApi、Recommendations | 新增書單 PUT action，映射 Added／BookNotFound；從推薦 Controller 抽出 CurrentUserId helper，兩者共用 JWT sub 解析。 |
| 2026-10-22 | `becc5e2` — Add Library section to the Book detail page (#11 M4) | Books | 注入 LibraryService，逐次讀本人 Entry；LibrarySection 透過 ViewData 與可快取書目模型分離；匿名不讀 Library。 |
| 2026-10-22 | `0c11ea2` — Run pending add-to-library after login and registration (#11 M5) | Account | 登入／註冊成功後處理 pendingAction，加入書單後回原 Book；待辦失敗仍維持登入成功。 |
| 2026-10-22 | `7f61fcc` — Add /library page with filter tabs and read-only rows (#11 M6) | Library | 新增需登入書單頁，以 ReadingStatus filter 查本人資料；未知 status 視為全部。 |
| 2026-10-22 | `e1809a4` — Move pending add-to-library rule from AccountController into LibraryService | Account | 待辦加入與失敗處理移到 LibraryService；Controller 保留 cookie、service 呼叫與 redirect 映射。 |
| 2026-10-22 | `c12f2ba` — Share the problem+json result helper across API controllers and filters (#12 M3) | LibraryApi、Recommendations | 將重複的 ProblemDetails ObjectResult 組裝改用 ApiProblemResults 共用 helper。 |
| 2026-10-22 | `7a310f7` — Add PATCH and DELETE for library entries (#12 M3) | LibraryApi | 新增 PATCH 的 JSON／欄位驗證、本人 Entry 更新及 DELETE；保留 rating 省略／null 與刪除冪等語意。 |
| 2026-10-22 | `66ecf55` — Add shared library controls to the Book page and /library (#12 M4) | Books、Library | 書籍頁與書單頁傳入 editLoginUrl，讓控制項在 token 過期時回到原 path/query。 |
| 2026-10-22 | `0a70d42` — Parse the PATCH library body as JSON whatever its Content-Type | LibraryApi | 移除 Content-Type 前置限制；body 一律嘗試 JsonDocument 解析，格式錯誤交 parser 轉整體 body 驗證錯誤。 |
| 2026-10-22 | `d32d41c` — Add the daily Recommendation limit gate (#15 M3) | Recommendations | 改為映射 RecommendationAttempt：Succeeded 回 200，DailyLimitReached 回 429；額度判斷留在 service。 |
| 2026-10-22 | `b6bf8ea` — Move the page number parsing into PageNumber (#16) | Search | 使用共用 PageNumber.Parse，移出 Controller 內頁碼正規化。 |
| 2026-10-22 | `852591c` — Show the AI search history list on /ai (#16 M2) | Ai | 注入 IRecommendationHistory；新增本人歷史列表、分頁與 `/ai/history-list` HTML partial endpoint。 |
| 2026-10-22 | `ddb4f9a` — Show a saved AI search on /ai/history/{id} (#16 M3) | Ai | 新增本人搜尋詳情；非法 GUID、未知與他人搜尋均回同一 404 View。 |
| 2026-10-22 | `894883b` — Share one pager between /search and the AI history list (#16 review) | Ai | AI 列表改由共用 Pager 表示 totalPages；此 commit 沒有直接修改 SearchController。 |
| 2026-10-22 | `6f716cc` — Decide the /ai redirect from the first page's count (#16 review) | Ai | 完整 `/ai` 依首次查詢的 TotalCount 判斷重導，避免先讀末頁；fragment 超頁仍另讀末頁並回 partial。 |
| 2026-10-22 | `cda623f` — Wire the Book AI profile into recommendations and history (issue #18 M6) | Ai | 詳情注入 profile store，即時批次讀 difficulty，與已保存的 rank／reason／relevance 快照分離。 |
| 2026-10-22 | `cd17224` — Show a dash instead of an error when the difficulty read fails (issue #18) | Ai | 改依賴 BookDifficultyReader；一般讀取失敗降級為無 difficulty，頁面顯示「—」。 |

## 3. 歷史如何影響維護

- **HTTP 與商業規則分離**：`e1809a4` 是待辦規則下移的具體例子；後續功能應維持 service outcome → Controller response 的方向。
- **共用結果與輸入規則**：`c12f2ba`、`b6bf8ea`、`894883b` 分別集中 API errors、頁碼解析、pager。不要在新 action 另寫不一致版本。
- **完整頁與片段不同**：`6f716cc` 說明兩者不能以「去重」為由合併成同一個先載末頁流程。
- **難度可用性降級**：`cd17224` 修正 profile 讀取失敗影響整頁；不能因 future refactor 又直接查 store 而失去此保護。
- **歷史範圍限制**：`Program.cs`、Identity filters、Application services、Models 或 Views 的單獨變更，可能影響 Controller 行為但不會出現在上表。調查特定回歸時須擴大到實際依賴路徑，不能只查 Controllers。

現況與待辦請見 [architecture.md](architecture.md)、[backlog.md](backlog.md)。

## #109 M2 書庫 Web 呈現（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 分支／提交 | Subject | 影響 |
|---|---|---|
| `a8a5077` | feat(web): show 書庫 on home and /books in place of the bestseller ranking | 新增 BooksController.Index（GET `/books`）；HomeController 改注入 BookBrowseService；BestsellersController 改為 301 至 `/books`，不再注入 BestsellerService |
| `2642182` | test(web): cover 書庫 paging, home sample and the /bestsellers redirect | 無產品行為變更；Web 測試改驗書庫與首頁，刪除 BestsellerPageTests |
| 本 M2 docs commit | docs(web): record 書庫 Web presentation in folder docs | 更新 Controllers、Models、Views、tests、wwwroot 文件；歷史列只追加 |

## #109 M3 書庫查詢計畫基準（新增紀錄）

本段是 #109 實作的紀錄，不改寫上方查核表。

| 分支／提交 | Subject | 影響 |
|---|---|---|
| `7c14b09` | docs(browse): sync specs to 書庫 and suspended Bestseller Web | 規格同步；Controllers 程式無變更 |
| 本 M3 baseline commit | docs(browse): record 書庫 query plan baseline and implementation report | CTL-11 補上量測結果（見實作報告）；待辦狀態不變（仍待 Catalog 增長後觀察） |
