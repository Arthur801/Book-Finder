# wwwroot 架構與選型

> 非同步推薦 Job M7 補記：2026-11-14 更新；程式變更以 `4db0c98`、`e00cbb5`、`5559870`、`ac88ef2` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P5 補記：2026-11-14 更新；程式變更以 `a9b7ad1`、`d43ea57` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 查核：2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。當前工作樹靜態證據；本次未執行 build、測試、瀏覽器、網路或發布。只新增本目錄五份文件。

[UI authority](../../Docs/ui/ui-flow.md)、[API](../../Docs/api/api-spec.md)、[Library](../../Docs/modules/user-library.md)、[Recommendation](../../Docs/modules/recommendation.md)、[Identity](../../Docs/modules/identity-auth.md)。名詞沿用 [CONTEXT](../../CONTEXT.md)；Bestseller、Library Entry、Recommendation Search 不在前端重定義。

## 責任連接

| 區塊 | caller／callee 與資料契約 |
|---|---|
| ai.js | Home／Ai View scripts section 載入；POST /api/recommendations；GET /ai/history-list?page=1；sessionStorage 一次交接 |
| library.js | Book／Library View 載入；PUT／PATCH／DELETE /api/library/{encodedBookId}；WeakMap 保存每組 server 確認值 |
| category-sidebar.js | [Categories/Index](../../Views/Categories/Index.cshtml) 的 Scripts section 載入；不發 request。移除 `.js-only` 顯示兩個需要 JS 的按鈕；桌面版切換 `.category-browser.is-sidebar-collapsed`、同步 `aria-expanded` 與按鈕文字；偏好存在 localStorage `bookfinder.categorySidebarCollapsed`，讀寫都包 try/catch，失敗只是不記得。手機抽屜由 Bootstrap offcanvas 負責，不經這支 JS |
| Razor DOM | ai-form 等 ID；data-library-controls、book-id、login-url、status、rating、clear-rating、unrated、remove、error、failed-text、add、add-error；[Controls](../../Views/Shared/_LibraryControls.cshtml) 與 [Book section](../../Views/Books/_LibrarySection.cshtml) 必須同步修改 |
| CSS | [site.css](../css/site.css) 基礎樣式，768px 字級 14→16；library-star 依 aria-pressed 著色；ai-history-requirement 截兩行且 title 保全文。[category-browser.css](../css/category-browser.css) 只給分類頁：`.js-only` 預設隱藏（選擇器權重高於 Bootstrap 的 display utility）；≥992px 時側邊欄 14rem、sticky，收合 class 只在這個寬度生效 |
| Layout | [Layout](../../Views/Shared/_Layout.cshtml) 使用 Bootstrap、jQuery、site.js 與版本化 site.css；`<head>` 有 `Styles` section 讓頁面載入自己的 CSS（目前只有分類頁）；頁面按責任再載 ai／library／category-sidebar |
| lib vendor | Bootstrap／jQuery／jquery-validation／unobtrusive 的 distribution、map、license；不屬自有業務程式，更新需保留授權與相依關係 |
| 靜態發布 | [Program](../../Program.cs) MapStaticAssets；[Web csproj](../../Book-Finder.csproj) 沒有 wwwroot/docs 專用排除 |

## 選擇與代價

| 面向 | 現行選擇與依據 | 替代差異（本次分析） | 維護重點 |
|---|---|---|---|
| UI 架構 | Razor + 局部 fetch，ui-flow §1 | SPA 會改架構邊界，非本任務 | DOM attributes 與 JS 是契約 |
| 業務驗證 | server authority；JS 只切換狀態 | 複製商業規則會漂移 | 額度、候選、owner 與交易都不能靠 JS |
| 自有 JS | 原生 IIFE、fetch、WeakMap；程式可見選擇，理由無獨立 ADR | module／framework 需 build 與依賴流程 | 無 export，DOM browser 測試較適合 |
| history | server partial 單一 markup，ui-flow §3.4 | JSON 重建會複製 pager 與時區規則 | 同源 HTML 信任邊界、redirect guard |
| requirement handoff | sessionStorage，ui-flow §3.2 | URL 會洩漏需求至網址；server state 需新契約 | storage 不可用降級重填、單 tab key |
| edit rollback | WeakMap 最後 server 值，程式可見選擇 | 全頁 reload 成本較高 | 每 block busy，不保證跨 tab 一致性 |
| CSS | Bootstrap utilities + 少量自有 CSS | 自建設計系統需更多維護 | focus 與 aria 狀態、clamp 實際渲染 |

## 安全、內容與錯誤

同源 fetch 搭 cookie credentials；非 GET 帶 RequestVerificationToken。Library 以 document.querySelector 取整個 document 第一個 matching antiforgery input；Library 區域與 Layout logout form 可各有 token，只有找不到任何 matching input 才送空值讓 server 拒絕，AI 假設 DOM token 存在，讀 token 在 promise 前，缺少將同步 throw；現有 Razor 已輸出，不宣稱正常頁已故障。

結果 textContent 不解讀 title／reason HTML，Book ID 編碼路徑；thumbnail 僅 http(s)。history outerHTML 僅接受同源 server partial，id 字串檢查不是 sanitizer。簡介／目錄不在 API／DOM contract，AI reason 也不能大段引用；來源正規化與是否引用由 server 負責。sessionStorage 只放需求，不放 JWT、secret。

AI 400 只讀 validation requirementText、429 有專屬文案；502／504／其他與 network 一般錯誤。Library 400 依 status→rating→body 取首訊息，404／500 一般錯誤，401 跳登入。沒有 client timeout／retry／cancel，server 60 秒與額度 20 不能當成 JS 實作。

## 已知缺口與 runtime 限制

AiPageTests 明言沒有執行 JS；現有 WebIntegration 驗證 HTML／API，不證明 fetch、storage、rollback、focus 或視覺正確，見 WB-01；[test-plan §2](../../Docs/testing/test-plan.md) 明定 MVP 不做網站 browser E2E，純 DOM harness 可獨立評估，不代表解除暫緩。MapStaticAssets 與 Web SDK 下，wwwroot/docs 應視為可能隨靜態資產發布；沒有排除規則，未 build／publish／HTTP 驗證，不能宣稱 Markdown 一定可下載或一定私有，見 WB-02。本任務依指定位置保存，不擅自移出或改設定。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。

## 推薦工作的前端（Job 計畫 M7）

- [ai.js](../js/ai.js)：`data-recommendation-jobs="true"` 時，送出改呼叫 `POST /api/recommendations/jobs`，帶 `Idempotency-Key`（每次送出以 `crypto.randomUUID()` 產生；沒有這個 API 時不送 header）。網路錯誤時保留 key，同一段文字再送出會沿用；收到任何 HTTP 回應就清除。202 導向 `/ai/jobs/{jobId}`；401 保存文字後導向登入；429 每日上限文案；400 伺服器的驗證訊息；409 與其他狀態用通用文案。`false` 時維持原本的同步流程。
- [ai-job.js](../js/ai-job.js)：狀態為 QUEUED／RUNNING 時，分頁可見就每 3 秒查詢 `data-job-status-url`；切到背景時停止，回到前景立刻查一次並恢復輪詢；狀態變成 SUCCEEDED 或 FAILED 就重新載入頁面。查詢失敗會在下一次重試。不使用 innerHTML，也不含任何訊息文案。
