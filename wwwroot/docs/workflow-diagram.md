# wwwroot 工作流程

> 查核：2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。當前工作樹靜態證據；本次未執行 build、測試、瀏覽器、網路或發布。只新增本目錄五份文件。

[UI authority](../../Docs/ui/ui-flow.md)、[API](../../Docs/api/api-spec.md)、[Library](../../Docs/modules/user-library.md)、[Recommendation](../../Docs/modules/recommendation.md)、[Identity](../../Docs/modules/identity-auth.md)。以下為現行自有 JS 與 DOM 的流程；商業規則、身分驗證、交易與每日額度在伺服器。

## 入口與渲染邊界

| 資產 | 觸發入口／責任 |
|---|---|
| [ai.js](../js/ai.js) | [Home](../../Views/Home/Index.cshtml) 的 home-ai-form；[Ai](../../Views/Ai/Index.cshtml) 的 ai-form、ai-requirement、ai-submit、ai-status、ai-results |
| [library.js](../js/library.js) | [Book section](../../Views/Books/_LibrarySection.cshtml)、[Library 頁](../../Views/Library/Index.cshtml)、[共用 controls](../../Views/Shared/_LibraryControls.cshtml) 的 data attributes |
| [site.js](../js/site.js) | [Layout](../../Views/Shared/_Layout.cshtml) 載入；目前只有模板註解，無行為 |
| [site.css](../css/site.css) | Layout；響應字級、focus、stars、history 兩行截斷 |
| lib／favicon | Layout 使用 Bootstrap、jQuery；validation 套件由 View 引用；第三方實作不逐行展開 |
| 靜態 endpoint | [Program](../../Program.cs) MapStaticAssets／WithStaticAssets，生成與發布由 Web SDK 負責 |

## Home、sessionStorage 與推薦

```mermaid
flowchart TD
 A[首頁 submit trim 需求] --> B{非空}
 B -->|是| C[sessionStorage set bookFinder.aiRequirement]
 B -->|否| D[導向 ai]
 C -->|成功或儲存被擋| D
 D --> E[伺服器未登入則導向登入 再回 ai]
 E --> F[ai-form 初始化 get 並 remove storage 預填 不自動送出]
 F --> G[submit trim]
 G -->|空| H[顯示請輸入 不 fetch]
 G -->|非空| I[讀 CSRF token 停用按鈕 清空舊結果 顯示等待]
 I --> J[POST recommendations same-origin JSON requirementText]
 J --> K{HTTP}
 K -->|200| L[解析 JSON renderResults 並啟動 history refresh]
 K -->|401| M[保存文字 導向 login returnUrl ai]
 K -->|429| N[顯示每日上限 保留輸入]
 K -->|400| O[validation requirementText 首筆或一般錯誤]
 K -->|其他或網路或 JSON 解析失敗| P[一般錯誤 保留輸入]
 L --> Q[Promise 完成 恢復按鈕]
 M --> Q
 N --> Q
 O --> Q
 P --> Q
```

Storage 被封鎖會被 catch；無法攜帶文字時讓使用者重填。home 空白不覆寫已有 key；takeRequirement 嘗試一次讀取後刪除，讀／刪例外回 null。maxlength=500 是 HTML 限制，伺服器才是最終驗證；等待文案 10～30 秒不是 JS timeout，60 秒由 server 負責。JS 沒有 AbortController、client retry 或取消狀態。

## 結果與歷史刷新

```mermaid
flowchart TD
 A[200 JSON body.results 或空陣列] --> B{零筆}
 B -->|是| C[顯示找不到符合的書]
 B -->|否| D[DOM createElement 與 textContent 顯示 rank title authors reason relevance difficulty]
 D --> E[book href encodeURIComponent id 封面只允許 http 或 https]
 C --> F[GET history-list page 1 same-origin]
 E --> F
 F --> G{200 且非 redirected}
 G -->|否| H[保留舊列表與網址]
 G -->|是| I{現有 ai-history 且 HTML 含對應 id}
 I -->|否| H
 I -->|是| J[以 server partial outerHTML 替換整段]
 J --> K{網址有 query}
 K -->|是| L[replaceState 回 ai]
 K -->|否| M[完成]
 F -->|網路失敗| H
```

[partial](../../Views/Ai/_AiHistoryList.cshtml) 是列表／pager 唯一來源；時區、排序、20 筆分頁由 server 決定。refreshHistory 沒有 return 到推薦 promise，按鈕可在刷新完成前恢復；刷新失敗不抹掉已成功的結果。JSON 值一律 textContent；同源 server HTML 才以 outerHTML 插入，包含 id 的 guard 不是通用 HTML sanitizer。0 結果仍刷新成功搜尋紀錄。

## 書單狀態與 API

```mermaid
flowchart TD
 A[掃描 data-library-controls] --> B[WeakMap 記住 server 初始 status 與按下星數]
 B --> C{操作}
 C -->|status change| D[PATCH readingStatus]
 C -->|點星或清除| E[PATCH rating 數字或 null]
 C -->|移除| F[DELETE 不帶 body 不跳確認]
 D --> G[hide error 並停用該 block controls]
 E --> G
 F --> G
 G --> H[同源 credentials CSRF header URL 編碼 bookId]
 H --> I{回應}
 I -->|PATCH 200| J[JSON commit WeakMap 與 UI 恢復 controls]
 I -->|DELETE 204| K{Library row}
 K -->|是| L[移除 row 最後一列顯示 empty]
 K -->|否 Book page| M[隱藏 controls 恢復加入按鈕]
 I -->|401| N[導向 server data-login-url]
 I -->|400| O[readingStatus rating body 順序首筆錯誤]
 I -->|其他或網路或 JSON 錯誤| P[一般錯誤]
 O --> Q[還原 WeakMap 值 解鎖與顯示錯誤]
 P --> Q
```

```mermaid
flowchart TD
 A[Book 加入按鈕] --> B[停用按鈕 hide add error]
 B --> C[PUT library bookId 無 body 同源與 CSRF]
 C -->|200 JSON| D[commit status rating 顯示 controls 隱藏加入]
 C -->|401| E[data-login-url 含 pendingAction 導向登入]
 C -->|其他或網路或 JSON 錯誤| F[恢復加入按鈕 顯示 server data-failed-text]
 G[匿名 Book section] --> H[server 渲染登入連結 不走 JS PUT]
```

PATCH 只送變更欄位；null 清 rating 與省略不同。失敗恢復 server 最後確認值；select 原生先改值，錯誤再還原。401 分支直接導航，沒有先解鎖（假定頁面離開）。按鈕 disabled 是 UI 防連點，非 server concurrency 保證；沒有程式層 request generation guard。篩選頁改 status 不移除或重新排序 row，直到 reload；是明訂行為。CSRF 由 document.querySelector 取整個 document 第一個 matching Razor antiforgery input（可能是 Layout logout token）；只有 selector 完全找不到 input 才傳空值，並非只檢查 Library 區域。JS 不簽發 token、不讀 JWT。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
