# Views 頁面與互動流程

查核：2026-10-24；HEAD `91333c3`。範圍是 Views 原始 Razor／scoped CSS；Controller、Models、JavaScript 是定位呼叫及呈現責任的依賴來源。Authority：[UI Flow](../../Docs/ui/ui-flow.md)、[API](../../Docs/api/api-spec.md)、[Catalog](../../Docs/modules/book-catalog.md)、[Library](../../Docs/modules/user-library.md)、[Identity](../../Docs/modules/identity-auth.md)、[Recommendation](../../Docs/modules/recommendation.md)。沒有本次執行或瀏覽器證據。

## 入口與呈現單元

| HTTP 入口 | View／主要 partial | 資料來源與邊界 |
|---|---|---|
| GET `/` | [Home/Index](../Home/Index.cshtml)、_SearchForm、_BestsellerEntries | HomeController；榜單前十筆，保留原 rank |
| GET `/bestsellers` | [Bestsellers/Index](../Bestsellers/Index.cshtml)、_BestsellerEntries | BestsellerService 完整目前榜單，不分頁 |
| GET `/search?q=&page=` | [Search/Index](../Search/Index.cshtml)、_SearchForm、_Pager | SearchController／SearchResultsViewModel；只有 local DB |
| GET `/books/{id}` | [Books/Detail](../Books/Detail.cshtml)、_LibrarySection、_LibraryControls | catalog read model + 每次獨立 user Library 查詢 |
| GET/POST `/account/login`、`/account/register` | [Login](../Account/Login.cshtml)、[Register](../Account/Register.cshtml) | AccountController；POST token、成功 cookie/redirect、失敗表單 |
| POST `/account/logout` | _Layout 內 form | 登入限制＋全域 antiforgery；成功回首頁 |
| GET `/library?status=` | [Library/Index](../Library/Index.cshtml)、_LibraryControls | 需登入；未知 status 視為全部 |
| GET `/ai?page=` | [Ai/Index](../Ai/Index.cshtml)、_AiHistoryList、_Pager | 需登入；每頁二十筆本人紀錄 |
| GET `/ai/history-list?page=` | [Ai/_AiHistoryList](../Ai/_AiHistoryList.cshtml) | 需登入；只回片段，無 layout |
| GET `/ai/history/{id}` | [Ai/History](../Ai/History.cshtml) 或 [Ai/NotFound](../Ai/NotFound.cshtml) | 需登入；不存在／非本人／無效 UUID 同 404 |
| `/Home/Error` | [Shared/Error](../Shared/Error.cshtml) | 非 Development exception handler；RequestId，不輸出 stack trace |

## 共用 layout、認證與一般表單

```mermaid
flowchart TD
    A[頁面請求] --> B{Controller 授權需求}
    B -->|需登入且匿名| C[302 login；GET 帶原路徑 returnUrl]
    B -->|允許| D[Controller 取得資料並建立 ViewModel]
    D --> E[ViewStart 指定 Layout；ViewImports 啟用 Tag Helpers]
    E --> F[Layout navbar 與 RenderBody]
    F -->|匿名| G[登入與註冊連結]
    F -->|已登入| H[編碼 display name；POST logout form 含 token]
    F --> I[頁面專屬 Scripts section]
    J[Login 或 Register POST] --> K{全域 antiforgery}
    K -->|無或錯 token| L[400；不執行帳號動作]
    K -->|有效| M{AccountService 結果}
    M -->|無效輸入或憑證| N[重顯欄位或 summary 錯誤；不回填密碼]
    M -->|成功| O[設定 cookie；處理 pending add；safe local redirect]
```

_ViewImports/_ViewStart 是完整 View 的框架組合，不是 HTTP endpoints。PartialView 的 history fragment 不跑完整 layout；_ValidationScriptsPartial 存在但目前沒有 caller，不能宣稱登入表單已載入 jQuery client validation。Razor 編碼與 token 生成不等於 server 授權或商業規則。

## Catalog 頁面、空狀態與 404

```mermaid
flowchart TD
    A[首頁或完整榜單] --> B{榜單是否空}
    B -->|是| C[榜單尚未建立；200]
    B -->|否| D[更新時間 Taipei；rank 封面或占位 作者 書名]
    E[Search GET] --> F{query 與 page 經 service/controller 處理}
    F -->|空 query 或零筆| G[找不到符合的書；無 pager；200]
    F -->|頁數超過末頁且有結果| H[302 最後一頁；保留 query]
    F -->|有效頁| I[結果 count 與日期精度；_Pager]
    D --> J[Book 詳細頁]
    I --> J
    J --> K{UUID 與 Book 是否存在}
    K -->|否| L[Books/NotFound；404]
    K -->|是| M[安全 metadata；缺值不輸出空標籤]
    M --> N[安全 http 或 https source 外連；noopener noreferrer]
    M --> O[Library 個人化區塊]
```

Pager 只在 TotalCount>0 顯示；上一頁／下一頁不存在時為 disabled span，當前頁為 aria-current，省略號不是連結。封面 null 顯示「無封面」。簡介與目錄不得進 HTML；Book 完整介紹導向來源網站。Book 模型先過濾安全 URL，Views 不自行 normalize；其他列表也依各自模型／reader 決定 cover 值。

## AI 輸入、結果與歷史 refresh

```mermaid
flowchart TD
    A[首頁 AI form submit] --> B[ai.js trim；文字非空才存 sessionStorage]
    B --> C[導向 ai；匿名由 server challenge 到 login]
    C --> D[登入後 ai 取出文字預填並刪 storage key]
    D --> E{AI submit 文字是否空}
    E -->|是| F[請輸入閱讀需求；不送 API]
    E -->|否| G[停用按鈕；清舊結果；顯示等待訊息]
    G --> H[POST recommendations；JSON 加 antiforgery header]
    H -->|401| I[保留文字到 storage；導向 login returnUrl ai]
    H -->|400| J[顯示 server validation 或通用錯誤]
    H -->|429| K[每日上限訊息]
    H -->|502 504 網路或其他錯誤| L[暫時無法使用；保留輸入]
    H -->|200| M{results 是否空}
    M -->|是| N[找不到符合的書，試著換個描述]
    M -->|否| O[textContent 建立結果；相關度百分比；難度或破折號]
    N --> P[啟動獨立 GET history-list page 1]
    O --> P
    P -->|200 未 redirect 且含 history section| Q[替換片段；網址有 query 才改回 ai]
    P -->|失敗或登入 redirect| R[保留舊 history；新推薦結果仍顯示]
    J --> S
    K --> S
    L --> S
    P --> S[主推薦 promise 結束即重新啟用按鈕]
    Q --> T[history 更新完成]
    R --> T
```

刷新 history 是額外非同步 fetch，推薦主流程按鈕復原不等待它完成。sessionStorage 被瀏覽器封鎖時不拋出未處理錯誤，但文字無法交接；需求不放 URL。AI form 沒 action/method，textarea 沒 name，依 JS 送 JSON；無 JS 不會完成推薦。前端沒有自訂 AbortController／60 秒 timer，60 秒由 server contract 保護，不宣稱瀏覽器有逾時取消。

歷史完整頁 `/ai` 超頁 redirect；fragment 超頁重新讀末頁後回片段，非 redirect。詳情 rank/reason/relevance 是保存快照，書名／封面／作者是目前資料，difficulty 即時讀取失敗降級「—」。空列表「還沒有 AI 搜尋紀錄」；零結果詳情「這次沒有找到符合的書」。

## Library 互動

```mermaid
flowchart TD
    A[Book 的 LibrarySection] --> B{Controls 是否存在}
    B -->|否；匿名| C[加入書單 login link；pendingAction]
    B -->|是；已登入| D[渲染 add 與 controls；以 hidden 切換]
    E[Library 頁面] --> F[篩選 tabs；每列 controls；空狀態預先渲染]
    D --> G[Library interaction area 共用 request token；controls 不逐列產 token]
    F --> G
    G --> H{使用者動作}
    H -->|add| I[PUT；200 顯示 server entry]
    H -->|status 或 stars 或 clear| J[PATCH；busy 停用控制項]
    H -->|remove| K[DELETE；204 才移除]
    J -->|200| L[確認 server 值；星星 aria-pressed；未評分與 clear 狀態]
    I -->|401| M[server data-login-url；add 帶 pendingAction]
    J -->|401| N[server edit-login-url；保留目前 query，不帶 pendingAction]
    K -->|401| N
    J -->|400 或其他失敗| O[還原確認值；顯示 server 或通用錯誤]
    K -->|失敗| O
    I -->|其他失敗| P[顯示加入失敗；重啟按鈕]
    K -->|204 Book 頁| Q[隱藏 controls；重顯 add]
    K -->|204 Library 頁| R[移除列；最後一列後顯示空狀態]
```

Library interaction area 共用可用 request token；完整 authenticated document 的 Layout logout form 也會產 token，不能斷言整頁只有一個 input。library.js 從 document 中第一個 matching antiforgery input 取值，不限 Library 區域。狀態與星星 labels 在 server partial，JS 只送請求與切狀態。PATCH rating 省略保留、null 清空由 API/parser 保證；錯誤回復使用 WeakMap 保存最近確認值。Library filter 不會因 PATCH 自動重排／移走列，不能從 server filter 推論 client 即時重查（見待辦）。跨頁、取消及 DB rollback 均屬 controller/service/store。

互參：[架構](architecture.md)、[待辦](backlog.md)、[歷史](update-history.md)、[案例](test-suite.md)。本次 Mermaid 僅結構檢查、未渲染。
