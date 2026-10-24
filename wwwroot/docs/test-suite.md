# wwwroot 面向 AI 的文字測試案例庫

> 查核 2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。本次只讀與文件靜態檢查，沒有本次測試通過結果。

## 測資、替身與隔離

Authority：[ui-flow](../../Docs/ui/ui-flow.md)、[API](../../Docs/api/api-spec.md)、[Library](../../Docs/modules/user-library.md)、[Recommendation](../../Docs/modules/recommendation.md)。以實際 Razor DOM 作 fixture：Home／Ai form、Book section、Library controls、Ai history partial。使用固定 GUID Book、狀態 READING、rating 3／null；需求可包含 `<img onerror=...>` 與繁中 Unicode，但不含真個資／secret。

待建 browser harness 需載入原始 ai.js／library.js，以 deferred fetch 控制每個 response 的 status／redirected／json／text／network reject，記錄 URL／options；stub sessionStorage 可讀寫與 throw、location.assign、history.replaceState。每案重置 DOM、storage、script context、WeakMap 與 network stubs；不可沿用上一案 listeners。只攔截本機路徑，不連 OpenAI、Google Books、博客來或正式 DB。未找到既有 JS browser runner／package.json，因此下列互動案例是可執行設計，不是已存在測試命令。[test-plan §2](../../Docs/testing/test-plan.md) 明定「E2E 瀏覽器：MVP 不做」；網站 browser E2E 狀態為明確暫緩。可另選純 DOM＋fetch 替身 harness，不等同解除網站 E2E 暫緩；需真網站瀏覽器測試時先更新此決策。

既有 .NET WebIntegration 驗證 HTTP／Razor，不執行 JS；[AiPageTests](../../tests/WebIntegration/AiPageTests.cs) 明確記錄此限制。[WebIntegration.csproj](../../tests/WebIntegration/WebIntegration.csproj) 使用 WebApplicationFactory、xUnit、Testcontainers PostgreSQL，需 .NET／Docker 與依賴準備，會產生 build artifacts，因此本次不執行。日後在隔離環境可用真實入口：

```bash
dotnet test tests/WebIntegration/WebIntegration.csproj --filter "FullyQualifiedName~AiPageTests|FullyQualifiedName~AiHistoryListTests|FullyQualifiedName~LibraryPageTests|FullyQualifiedName~BookLibrarySectionTests|FullyQualifiedName~LibraryApiTests"
```

此命令不等同 JS browser 回歸，也不能證明 wwwroot/docs 的 publish 路由或視覺呈現。

## WT-01 — 需求 sessionStorage 交接

- 責任／規格：ui-flow §3.2；ai.js；風險 L2；狀態：待補強（browser 待建，已有 HTML 測試）。
- Given：Home home-ai-form／ai-request 輸入含前後空白文字；sessionStorage 正常與拋錯各一案；新的 Ai DOM。
- When：觸發 Home submit，再於新 DOM 執行 ai.js；另送空白 Home 與空白 AI。
- Then：Home preventDefault、trim 後存 bookFinder.aiRequirement，導向 /ai，URL 無需求；Ai 讀後清除並預填，不自動 POST；storage throw 不阻斷導航；AI 空白不 fetch 且顯示請輸入。匿名 /ai 登入 redirect 由 HTTP 測試另證。
- 來源／擴充入口：[tests/WebIntegration/AiPageTests.cs](../../tests/WebIntegration/AiPageTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-02 — 推薦 request 與成功 render

- 責任／規格：ui-flow §3.4；api-spec §3；風險 L2；狀態：待補強（JS 待建）。
- Given：Ai DOM 有 CSRF hidden token、舊結果，stub deferred fetch 200，results 含特殊字元、null difficulty、http 封面與 javascript scheme 封面。
- When：submit 非空需求，解析 200 body。
- Then：按鈕 busy、清舊結果、等待文案；POST /api/recommendations JSON requirementText、Content-Type、RequestVerificationToken 與 credentials same-origin；文本以 textContent 顯示不生成惡意節點；id 路徑 encode，relevance 四捨五入百分比、difficulty null 顯示破折號；不合法封面 placeholder；最後按鈕恢復。
- 來源／擴充入口：[wwwroot/js/ai.js](../../wwwroot/js/ai.js)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-03 — 推薦錯誤、額度與輸入恢復

- 責任／規格：ui-flow §3.5；api-spec §2／3；風險 L2；狀態：待補強（JS 待建，API 有獨立測試）。
- Given：已輸入需求，stub 401／429／400 validation／400 antiforgery／502／504／500／network reject／無效 JSON。
- When：逐案 submit 並完成 Promise chain。
- Then：401 保存原 trim 需求並 assign /account/login?returnUrl=%2Fai；429 專屬每日上限；validation 顯示 requirementText 首筆；其餘一般錯誤。文字保留、按鈕恢復；錯誤不觸發 history GET。UI 不推定 server 是否保存，要以 server tests 驗證。
- 來源／擴充入口：[wwwroot/js/ai.js](../../wwwroot/js/ai.js)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-04 — 歷史片段刷新與降級

- 責任／規格：ui-flow §3.4；b2c72a0 回歸；風險 L2；狀態：待補強（JS 待建，server partial 已測）。
- Given：網址 /ai?page=2、舊 ai-history；推薦 200 含結果或空 results；history fetch 分別為200有效 partial、302跟隨後200 redirected、非200、缺 id、network reject。
- When：完成推薦 response，再獨立完成 history promise。
- Then：推薦結果或無結果訊息已顯示；GET /ai/history-list?page=1 same-origin；只有200非redirected且現有節點／HTML id 都存在才 outerHTML 替換並 replaceState /ai；失敗保留原列表與網址，不抹成功結果；推薦按鈕不等待此 GET 才恢復。
- 來源／擴充入口：[tests/WebIntegration/AiHistoryListTests.cs](../../tests/WebIntegration/AiHistoryListTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-05 — 書單加入與移除後再加入

- 責任／規格：user-library §3／5；api-spec §4；風險 L2；狀態：待補強（JS 待建，DOM／API 已測）。
- Given：Book section 有隱藏 controls、加入按鈕、CSRF；stub PUT 200 status WANT_TO_READ rating null；另一案已存在回目前 status／rating。
- When：click add；DELETE 204 後再 add。
- Then：PUT 無 body、bookId encode、同源與 CSRF；成功 commit server 值，顯示 controls／未評分、clear disabled、隱藏 add。重複 PUT 不在 client 擅改 server 值；再 add 以新200覆寫隱藏 stale 值。非200／JSON錯誤解鎖 add 並顯示 add error。
- 來源／擴充入口：[tests/WebIntegration/BookLibrarySectionTests.cs](../../tests/WebIntegration/BookLibrarySectionTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-06 — PATCH 單欄與 confirmed rollback

- 責任／規格：user-library §3／4；api-spec §4；風險 L2；狀態：待補強（JS 待建，API 已測）。
- Given：兩組 controls，A=READING／3，B=WANT_TO_READ／null，Fake fetch pending／200。
- When：A change status、點5星、clear rating，逐次回200 server entry。
- Then：各請求只送 readingStatus 或 rating，clear 明確 null，省略欄位不送；只停用 A；server 200 後更新 WeakMap、select、aria-pressed、未評分、clear disabled；篩選頁 status 改變仍保留 row，不重新排序至 reload。
- 來源／擴充入口：[tests/WebIntegration/LibraryApiTests.cs](../../tests/WebIntegration/LibraryApiTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-07 — 書單失敗與 401 導航

- 責任／規格：ui-flow §3.5；library.js；風險 L2；狀態：待補強（JS 待建）。
- Given：A server confirmed READING／3，原生 select 已暫改；error data-failed-text 與 data-login-url 含 returnUrl；stub400／404／500／network／malformed JSON／401。
- When：觸發 PATCH 或 DELETE；另觸發 PUT 401。
- Then：400依readingStatus、rating、空body key 首筆，否則 generic；非401失敗恢復最後confirmed值、解除busy、顯示textContent錯誤。401 assign server URL；PUT URL含pendingAction，PATCH／DELETE edit URL回原頁。401直接導航，不宣稱導航前會解鎖。
- 來源／擴充入口：[wwwroot/js/library.js](../../wwwroot/js/library.js)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-08 — DELETE 列表與最後列空狀態

- 責任／規格：user-library §3／4；api-spec §4；風險 L2；狀態：待補強（JS 待建，初始 DOM 已測）。
- Given：Library 有兩列各 controls、hidden library-empty；另 Book section 情境；DELETE stub204。
- When：移除第一列再最後列；Book controls 移除。
- Then：DELETE 無body且CSRF；不顯示確認對話；204只移除對應row，最後一列才顯示empty與前往書庫連結；Book情境隱藏controls、恢復add。錯誤保留row並走rollback。
- 來源／擴充入口：[tests/WebIntegration/LibraryPageTests.cs](../../tests/WebIntegration/LibraryPageTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-09 — CSRF 與 DOM contract

- 責任／規格：api-spec §1／2；View contract；風險 L3；狀態：待補強（server已有測試，JS payload待建）。
- Given：真 View fixture；Library interaction area 共用 token，authenticated Layout 的 logout form 可另有 token；Book authenticated 有 token、匿名 Book 只有 login anchor；AI form 有 token。Library 缺 token 負例必須移除整個 document 所有 matching inputs，另備只移除 Library 區域但保留 logout token 的對照。
- When：執行各 script 並捕捉 requests；Library 對照 document 第一個 `input[name="__RequestVerificationToken"]` 的值；server 另以錯／缺 token 送非 GET。
- Then：所有非GET帶header；Library selector 找不到任何 matching input 才送空值並由 server 400 拒絕；只移除 Library 區域 token 時，若 logout token 仍在，應使用 document 第一個 matching input，不得預期空值。AI form 缺 token 是同步例外（正常View已有token），作contract負例而非假造正常頁bug；匿名Book不執行PUT。token／JWT不寫storage。server CSRF 拒絕的資料證據限 LibraryApiTests 的 Entry count／既有 rating 斷言，不泛推所有副作用。
- 來源／擴充入口：[tests/WebIntegration/LibraryApiTests.cs](../../tests/WebIntegration/LibraryApiTests.cs)；[LibraryPageTests](../../tests/WebIntegration/LibraryPageTests.cs) 的 `Page_renders_one_antiforgery_token_for_all_rows` 明確只計算 Library view 區域，排除 logout form。browser 案例未有可執行 runner 時維持待建，不宣稱通過。

## WT-10 — CSS、鍵盤與公開內容

- 責任／規格：ui-flow §3.3／3.4；BOOK-05；WB-03；風險 L1；狀態：明確暫緩（網站browser E2E於MVP不做；render案例設計保留，server內容已有測試）。
- Given：本機真Razor頁面，viewport 375／767／768／1280，長需求、rating3／null，鍵盤Tab／Enter操作；stub全部外部fetch。
- When：檢查computed字級／focus／star與歷史截斷，操作表單與controls。
- Then：768以下html14px、以上16px；focus可見，aria-pressed前3星與顏色一致，null未評分；需求兩行截斷title保全文；不顯示description或table of contents；窄螢幕無關鍵操作被遮蔽。只聲稱觀測到的瀏覽器結果。
- 來源／擴充入口：[tests/WebIntegration/BookDetailPageTests.cs](../../tests/WebIntegration/BookDetailPageTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-11 — 靜態文件發布範圍

- 責任／規格：Program MapStaticAssets；Web SDK；WB-02；風險 L2；狀態：待驗證／待決策（未build或publish）。
- Given：已決定wwwroot/docs是否允許公開；disposable本機publish目錄，無正式credentials，固定SDK。
- When：後續授權工作執行publish檢視manifest／輸出檔，再本機HTTP請求代表性docs URL。
- Then：依政策斷言檔案／路由存在或排除；記錄status與media type，不假定.md自動404或公開。若政策禁止，另案修csproj／位置後回歸；本次不得改設定或刪文件。
- 來源／擴充入口：[Program.cs](../../Program.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## WT-12 — Server HTML 與狀態初始契約

- 責任／規格：ui-flow §3.4；user-library §4；風險 L2；狀態：已有測試但本次未執行（不含JS）。
- Given：WebIntegration fixture使用隔離DB、登入使用者與自己的／別人的Entry與RecommendationSearch。
- When：以HttpClient GET /ai、/ai/history-list?page=1、/library、/books/{id}。
- Then：正確script引用、IDs、data attributes、初始hidden／stars與token；history partial等同整頁區塊、不含layout、20筆分頁與Asia/Taipei時間；只顯示本人資料。此HTTP斷言不能代替WT-01～09。
- 來源／擴充入口：[tests/WebIntegration/AiPageTests.cs](../../tests/WebIntegration/AiPageTests.cs)；browser案例未有可執行runner時維持待建，不宣稱通過。

## 狀態與限制

site.js 目前只有模板註解，沒有待實作商業功能；不把它列缺陷。網站 browser E2E 依 test-plan 明確暫緩（MVP 不做）；純 DOM harness 未實作、publish與render待驗證。WT-01～09 可先用純 DOM 替身驗證；WT-10 真網站 browser render 在解除 E2E 暫緩前只保留案例設計。第三方vendor不逐行複製測試；使用者可見Bootstrap navbar互動由未來render測試涵蓋，不能從載入script推定已工作。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)。
