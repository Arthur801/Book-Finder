# #16 AI 搜尋紀錄：實作計劃

> 規格：`Docs/modules/recommendation.md` §12、`Docs/ui/ui-flow.md` §2、§3.4、§3.5、`Docs/data/data-model.md` §5.11、§5.12、`Docs/TODO.md`〈/ai 頁面的 AI 搜尋紀錄列表〉。
> 前置：#13（`recommendation_searches`、`recommendation_results` 已有資料）；#15 已改過 `ai.js`。
> 風險：L2（只讀；跨使用者隔離為重點）。

## 1. 要做什麼

- `/ai` 下方列出自己的 AI 搜尋紀錄：新到舊、每頁 20 筆；顯示需求文字、時間、結果數；沒有紀錄時顯示「還沒有 AI 搜尋紀錄」。
- 推薦成功後，這次搜尋立即出現在列表最前面。
- `/ai/history/{id}`：顯示當時保存的 rank、書、reason、relevance（快照）；書可點擊。別人的或不存在的紀錄 → 404。
- 不提供刪除。

## 2. 模組總覽

```text
                  ┌──────────────── Web 層 ─────────────────┐
  瀏覽器          │ M2 /ai?page=      M3 /ai/history/{id}    │
 ┌────────────┐   │   AiController      AiController         │
 │ M4 ai.js   │   │   + _AiHistoryList  + History.cshtml     │
 │ 成功後插入  │   └──────┬───────────────────┬──────────────┘
 │ 列表第一列  │          │ 只呼叫            │
 └────────────┘          ▼                   ▼
                  ┌──────────── Application ────────────────┐
                  │ M1 IRecommendationHistory（唯讀 port）   │
                  │    ListAsync / GetAsync                  │
                  └──────────────────┬──────────────────────┘
                                     ▼
                  ┌──────────── Infrastructure ─────────────┐
                  │ M1 EfRecommendationHistory               │
                  └─────────────────────────────────────────┘
```

讀取（紀錄）與寫入（`IRecommendationStore`）是兩個介面，彼此不依賴。

## 3. 各模組

### M1 紀錄讀取（Application port + Infrastructure）

**職責**：讀出某位使用者自己的紀錄列表與單筆詳情。

**檔案**：`Application/Recommendation/IRecommendationHistory.cs`、`HistoryModels.cs`、`Infrastructure/Persistence/EfRecommendationHistory.cs`

**接口**：

```csharp
interface IRecommendationHistory
    Task<HistoryPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken ct)
    Task<HistoryDetail?> GetAsync(Guid userId, Guid searchId, CancellationToken ct)  // 別人的或不存在 → null

record HistoryPage(IReadOnlyList<HistorySummary> Items, int TotalCount)
record HistorySummary(Guid SearchId, string RequirementText, DateTime CreatedAt, int ResultCount)
record HistoryDetail(Guid SearchId, string RequirementText, DateTime CreatedAt, IReadOnlyList<HistoryResult> Results)
record HistoryResult(short Rank, Guid BookId, string Title, IReadOnlyList<string> Authors,
                     string? ThumbnailUrl, string Reason, double? Relevance)
```

**規則**：

- 兩個方法的查詢條件都含 `user_id = userId`；`GetAsync` 用 `id AND user_id` 一起查，別人的紀錄與不存在的紀錄結果相同（`null`）。
- 列表 `created_at DESC, id DESC`（同時間時順序穩定）。
- 詳情依 `rank` 排序；rank、reason、relevance 來自 `recommendation_results`（快照）；書名、作者、封面為目前 Book 資料（`book_id` FK 為 RESTRICT，書不會消失）。
- 不回傳 description 與目錄（BOOK-05）。

**測試**：DatabaseIntegration——排序、第 21 筆在第 2 頁、`ResultCount`（含 0 本）、A 讀不到 B、改了書名後 rank/reason/relevance 不變。

### M2 `/ai` 紀錄列表（Web）

**職責**：在 `/ai` 下方顯示紀錄列表與分頁。

**檔案**：`AiController.Index(int page = 1)`、`Models/AiPageViewModel.cs`、`Views/Ai/_AiHistoryList.cshtml`、`Views/Ai/Index.cshtml`

**規則**：

- 每頁 20 筆；分頁沿用 `Models/PageWindow`（與 `/search` 相同的頁碼列）。`page` 小於 1 或超過最後一頁的處理也與 `/search` 一致。
- 每列：需求文字（過長時 CSS 截成兩行，`title` 屬性放全文）、時間（Asia/Taipei，`yyyy-MM-dd HH:mm`）、「N 本」；整列連到 `/ai/history/{id}`。
- 空狀態：「還沒有 AI 搜尋紀錄」。
- 頁面中放一個 `<template>`，內容與伺服器渲染的一列相同，給 M4 的 JS 複製使用（只維護一份 HTML 結構）。

**測試**：WebIntegration——只列本人、順序、第 2 頁、空狀態、`<template>` 存在、未登入導向登入。

### M3 `/ai/history/{id}` 詳情頁（Web）

**職責**：顯示一次搜尋的快照。

**檔案**：`AiController.History(string id)`、`Models/AiHistoryViewModel.cs`、`Views/Ai/History.cshtml`、`Views/Ai/NotFound.cshtml`（或共用既有 404 view）

**規則**：

- `[Authorize]`；`id` 不是 GUID、不存在、不屬於本人 → 同一個 404 頁。
- 顯示需求文字、時間；每本：排名、封面、書名（連到 `/books/{id}`）、作者、推薦理由、相關度、難度欄位（本票固定顯示「—」，#18 接上真實值）。
- 相關度的格式與 `ai.js` 的推薦結果一致。
- 0 本結果的紀錄：顯示「這次沒有找到符合的書」。

**測試**：WebIntegration——內容與保存的 Results 一致、A 開 B 的紀錄 404、非 GUID 404、未登入導向登入。

### M4 成功後插入列表（JS）

**職責**：推薦成功時，不重新載入頁面就把這次搜尋加到列表最前面。

**檔案**：`wwwroot/js/ai.js`

**規則**：

- 只在 200 時插入；失敗（4xx/5xx）列表不變。
- 用 M2 的 `<template>` 填入 `searchId`、`createdAt`（API 回應已有）、需求文字（使用者剛送出的文字，送出時伺服器會 trim，JS 同樣 trim）、結果數。
- 只在目前位於第 1 頁時插入；插入後若列表超過 20 列，移除最後一列；原本是空狀態則換成列表。
- 不需要新的 API 欄位。

**測試**：瀏覽器手動驗證（成功插入、失敗不插入、第 2 頁不插入）。

### M5 文件與報告

- `ui-flow.md` §2 路由表加上 `/ai?page=`，移除「（#16 實作）」字樣；§3.4 同步。
- 移除 `Docs/TODO.md`〈/ai 頁面的 AI 搜尋紀錄列表〉。
- 兩軸 review、`Docs/Implementation-Report/issue-16-ai-history.md`。

## 4. 模組之間的關係

- M1 是唯一碰資料庫的模組；M2、M3 只透過 `IRecommendationHistory` 讀資料，彼此不共用狀態。
- M4 只依賴 M2 輸出的 `<template>` 與 `POST /api/recommendations` 的既有回應，不新增後端 contract。
- #18 只需要在 M3 的 view model 加上 difficulty，不必改 M1。

## 5. 預設決定（局部、可逆；如不同意請指出）

1. 列表分頁用 `/ai?page=N`（Razor 渲染，不新增 JSON 端點，與 `api-spec.md` §3「紀錄為 Razor 頁面」一致）。
2. 使用者不在第 1 頁時，新推薦不插入目前列表（回到第 1 頁就看得到）。
3. 需求文字在列表截成兩行顯示，詳情頁顯示全文。
4. 詳情頁的書名、作者、封面讀取目前的 Book 資料；快照只保證 rank、reason、relevance（與 issue AC 一致）。

## 6. 實作步驟

依 [README §3](README.md#3-共通的實作步驟每個模組都一樣)：

1. M1 `issue-16-m1-history-reader` — DatabaseIntegration；mutation 抽查（拿掉 `user_id` 條件，隔離測試必須失敗）。
2. M2 `issue-16-m2-history-list` — WebIntegration。
3. M3 `issue-16-m3-history-detail` — WebIntegration。
4. M4 `issue-16-m4-insert-after-success` — 瀏覽器手動驗證。
5. M5 `issue-16-report` — review、文件、報告；關閉 #16。
