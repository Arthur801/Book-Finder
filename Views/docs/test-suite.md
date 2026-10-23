# Views 文字測試案例庫

查核：2026-10-24；HEAD `91333c3`。本次未執行 build、test、browser 或 network。以下已有測試代表 source 有斷言，不代表本次通過。

## Fixture 與隔離

[WebFixture](../../tests/WebIntegration/WebFixture.cs) 每次 run 建 disposable `pgvector/pgvector:0.8.7-pg17` container、套 migration；每案新 host 清 cache，序列 collection 用 ResetDatabaseAsync 清 application tables。只能對該 disposable database 執行 reset。測試 factory 提供假 signing key、fake AI parser/ranker/embedding/profile，不呼叫 OpenAI；可注入 FakeTimeProvider 與失敗 Library/Profile store。使用 [CatalogSeedTests](../../tests/WebIntegration/CatalogSeedTests.cs) 及各測試 seed，時間採固定 UTC、顯示採 Taipei；example.test URL、測試 email，不使用真實個資。

[AccountFlow](../../tests/WebIntegration/AccountFlow.cs) 先 GET token 再 POST，同 client 保留 antiforgery/auth cookies；client 不自動 follow redirects 時查 Location/status。HttpClient/HtmlPage 只查 response HTML，**不執行 JavaScript**；NullFileProvider 也不能證明 assets 或 version hash。瀏覽器案使用 mock fetch/local server，需日後先解除 test-plan MVP E2E 暫緩。

後續命令入口（會建產物／需要 Docker，故本次不執行）：

```bash
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~LayoutAndHomeTests|FullyQualifiedName~NavbarTests|FullyQualifiedName~BestsellerPageTests|FullyQualifiedName~SearchPageTests|FullyQualifiedName~BookDetailPageTests'
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~AccountPagesTests|FullyQualifiedName~AuthPipelineTests|FullyQualifiedName~BookLibrarySectionTests|FullyQualifiedName~LibraryPageTests'
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~AiPageTests|FullyQualifiedName~AiHistoryListTests|FullyQualifiedName~AiHistoryDetailTests'
```

### VIEW-T01 — Layout、導覽與榜單

風險 L1；已有測試，本次未執行。規格：[UI §3.1–3.2](../../Docs/ui/ui-flow.md)、[Bestseller](../../Docs/modules/bestseller.md)。Given 空榜、100 筆榜與缺號榜，各以匿名／已登入 user；When GET `/`、`/bestsellers`；Then title/zh-Hant/layout/nav 正確，首頁前十筆可包括 rank 11，完整頁不分頁，不重編 rank，顯示 Taipei 更新時間、作者與占位封面；空榜 200「榜單尚未建立」。匿名有 login/register，已登入有編碼 display name、POST logout token。來源：[LayoutAndHomeTests](../../tests/WebIntegration/LayoutAndHomeTests.cs)、[NavbarTests](../../tests/WebIntegration/NavbarTests.cs)、[BestsellerPageTests](../../tests/WebIntegration/BestsellerPageTests.cs)。

### VIEW-T02 — 搜尋、空值與共用 pager

風險 L2；已有測試，本次未執行。規格：[Catalog §3](../../Docs/modules/book-catalog.md)。Given 21 個匹配 Book、缺作者／publisher／日期／封面，query 含 `<`、`&`、percent；When GET `/search?q=...&page=`，測空 query、非法 page、末頁、大數頁；Then query 預填但編碼、不把空 query 當查全部，零結果無 pager；頁二一筆，超頁 302 最後頁，當前 aria-current、邊界 disabled、長頁省略號無 href、query URL 正確編碼。簡介／目錄不可出現在 HTML，出版社／簡介不被一般搜尋。來源：[SearchPageTests](../../tests/WebIntegration/SearchPageTests.cs)、[PagerViewModel](../../Models/PagerViewModel.cs)、[_Pager](../Shared/_Pager.cshtml)。

### VIEW-T03 — Book 詳情、外連與 404

風險 L2；已有測試，本次未執行。規格：[Catalog §4](../../Docs/modules/book-catalog.md)、BOOK-05。Given 完整 Book、僅 title Book、Google-only source、unsafe URL／thumbnail、原始 description/TOC；When GET `/books/{id}`，另測無效 UUID／unknown；Then 缺值不顯空標籤、year/month 不冒充確定日、ISBN13 優先、contributor 按角色，僅 safe 外連且博客來 primary、Google fallback、noopener noreferrer；原文不出 HTML。缺 Book 回 404 View，非 200 假錯誤頁。來源：[BookDetailPageTests](../../tests/WebIntegration/BookDetailPageTests.cs)、[BookDetailViewModel](../../Models/BookDetailViewModel.cs)。

### VIEW-T04 — 帳號表單、PRG 與 antiforgery

風險 L3；已有測試，本次未執行；client validation 決策 VIEW-B04。規格：[Identity §3–6/8](../../Docs/modules/identity-auth.md)。Given 新 client、token cookie、invalid credentials、7/8 字密碼、ReturnUrl/PendingAction；When GET/POST login/register、POST logout；Then 無 token 400，錯誤重顯 field/summary、email/hidden 值保留而 password 空，wrong password/unknown email 同訊息；成功 cookie 及 safe local redirect，已登入 GET login/register 回首頁；logout 移除 cookie 後 protected 頁 challenge。跨帳號表單連結保留參數，不允許外站 open redirect。來源：[AccountPagesTests](../../tests/WebIntegration/AccountPagesTests.cs)、[NavbarTests](../../tests/WebIntegration/NavbarTests.cs)、[AuthPipelineTests](../../tests/WebIntegration/AuthPipelineTests.cs)、[PendingLibraryActionTests](../../tests/WebIntegration/PendingLibraryActionTests.cs)。

### VIEW-T05 — Book LibrarySection 三種初始狀態

風險 L2；已有測試，本次未執行。規格：[Library §5](../../Docs/modules/user-library.md)。Given 匿名、已登入無 entry、已登入 Reading/rating4；When GET Book；Then 匿名僅 login link 帶 pending add 無 controls；無 entry 可見 add、hidden controls 為 WantToRead/null；有 entry hide add、selected status、四個 aria-pressed、未評分與 clear disabled 正確。狀態 labels 來自 server order；另一使用者 entry 不影響本人。來源：[BookLibrarySectionTests](../../tests/WebIntegration/BookLibrarySectionTests.cs)、[_LibrarySection](../Books/_LibrarySection.cshtml)、[_LibraryControls](../Shared/_LibraryControls.cshtml)。

### VIEW-T06 — Library 頁篩選與空狀態

風險 L2；已有測試，本次未執行。規格：[Library §4](../../Docs/modules/user-library.md)。Given A/B users、多狀態／ratings／UpdatedAt entries；When GET `/library`、`?status=READING`、unknown filter、empty filter；Then 匿名 redirect，僅本人且最新先，active tab 正確、未知視全部，逐列控制項資料不串，空態含榜單連結；有列時空態 hidden；controls edit-login-url 保留 query；Library 區域 token 共用而非每列一份。來源：[LibraryPageTests](../../tests/WebIntegration/LibraryPageTests.cs)。改狀態後即時 filter 語意另見 VIEW-T12。

### VIEW-T07 — AI SSR 與歷史分頁

風險 L2；已有測試，本次未執行。規格：[UI §3.4](../../Docs/ui/ui-flow.md)。Given 本人21筆與他人搜尋、固定 UTC；When GET `/ai?page=`、`/ai/history-list?page=`；Then 匿名 redirect，form 有 token/status/results，textarea 無 name、不渲染 URL 需求；本人新到舊每頁20、Taipei 時間與 N 本、全文 title attribute、零筆訊息無 pager。完整頁超頁302；fragment 超頁回末頁200，片段無 layout且與完整頁 section 一致。來源：[AiPageTests](../../tests/WebIntegration/AiPageTests.cs)、[AiHistoryListTests](../../tests/WebIntegration/AiHistoryListTests.cs)。

### VIEW-T08 — AI 歷史詳情與隔離

風險 L3；已有測試，本次未執行。規格：[Recommendation §12](../../Docs/modules/recommendation.md)。Given 本人 saved search（含零結果）、另一人 search、無 Profile 或 profile read 失敗；When GET `/ai/history/{id}`，另傳 malformed/unknown；Then 本人需求全文、時間、rank/reason/relevance 快照，Book link與目前 metadata，difficulty 即時或「—」、cover placeholder；零結果「這次沒有找到符合的書」。他人／不存在／無效 id 同404，不洩存在性。來源：[AiHistoryDetailTests](../../tests/WebIntegration/AiHistoryDetailTests.cs)、[AiHistoryDetailViewModel](../../Models/AiHistoryDetailViewModel.cs)。

### VIEW-T09 — 共用錯誤頁

風險 L1；待補強，本次未執行；關聯 VIEW-B03。規格：[UI §3.5](../../Docs/ui/ui-flow.md)。Given 非 Development pipeline、受控 request ID 與拋例外 adapter；When 請求觸發 exception handler（後續測試須建立專用 host，不能用 production）；Then 回共用錯誤、不含 stack/secret，可查 request ID、no-store；文案按未來核定版本。現有位置 [HomeController.Error](../../Controllers/HomeController.cs)、[Shared/Error](../Shared/Error.cshtml)；本次未找到專門覆蓋非 Development handler 的 View integration assertion，不以單看模板聲稱通過。

### VIEW-T10 — AI 瀏覽器交接與失敗

風險 L2；網站 E2E 明確暫緩、案例待建，關聯 VIEW-B01。規格：[UI §3.2/3.4/3.5](../../Docs/ui/ui-flow.md)。Given local browser、可控 sessionStorage/mock fetch、匿名/已登入；When 首頁輸入轉 ai，再 submit 空字／有效字，回應200零本/非零、400、401、429、502、504、network reject；Then URL 無需求，storage 只讀一次並清除，封鎖 storage 可重新輸入；busy disabled、結果 textContent 無 script 執行、難度 null 為「—」、429 特定文案，401 保存文字後 login，其餘保留 textarea，最終復原 button。來源：[ai.js](../../wwwroot/js/ai.js)；AiPageTests 只驗 SSR，不能替代執行此案。

### VIEW-T11 — history refresh 降級

風險 L2；網站 E2E 明確暫緩、待建；關聯 VIEW-B01。規格：[UI §3.4](../../Docs/ui/ui-flow.md)。Given `/ai?page=2` 舊 history，推薦200，mock fragment fetch；When 回200正確 section／redirected login 200／500／missing section／reject；Then 只有正確未 redirect 片段替換並 replaceState `/ai`，失敗保留舊列表、新推薦結果不消失，不把登入完整頁插入 history。來源 ai.js.refreshHistory，既有 b2c72a0 修復；本次只讀 diff 未動態重現。

### VIEW-T12 — Library 瀏覽器狀態復原與篩選決策

風險 L2；網站 E2E 明確暫緩、待建；filter 即時行為待決策，關聯 VIEW-B01/B02。規格：[API §4](../../Docs/api/api-spec.md)、[Library](../../Docs/modules/user-library.md)。Given Book 與 filtered `/library`、每列 server initial controls/mock fetch；When add PUT200、PATCH status/rating/null200、400/404/network、401、DELETE204 直到最後列；Then 送同源 cookies/token、server200 才確認值、失敗恢復 WeakMap 值與清除按鈕狀態、錯誤以 textContent 顯示；401 edit 保留 query，add 帶 pending；delete Book 重顯 add、Library 刪最後列顯空態。現況 PATCH 留在原列且不重排；決策後補明確 filter/sort 驗收。來源：[library.js](../../wwwroot/js/library.js)、[_LibraryControls](../Shared/_LibraryControls.cshtml)，API tests 不等於 DOM case 通過。

互參：[流程](workflow-diagram.md)、[架構](architecture.md)、[待辦](backlog.md)、[歷史](update-history.md)。所有 runtime、browser 與 production 證據均未由本文件任務產生。
