# Issue #16 AI 搜尋紀錄：實作報告

- Issue：#16 AI 搜尋紀錄（REC-10）
- 計劃：`Docs/plans/issue-16-ai-history.md`，含模組拆分與預設決定 §5。計劃中的型別名稱已更新成實際名稱。
- 規格：`Docs/modules/recommendation.md` §12、`Docs/ui/ui-flow.md` §2、§3.4、§3.5、`Docs/data/data-model.md` §5.11、§5.12
- 日期：2026-10-22
- 分工：
  - 主 agent：規劃、派工、驗收、撰寫文件；M4 的 JS 由主 agent 直接修改。
  - Haiku subagent：以 TDD 實作 M1～M3，以及 review 後的修正。
  - 每個模組完成後，主 agent 親自執行 build 與測試，並閱讀程式碼。
- PR：每個模組一個 PR，base 都是 `main`。分支接在 #15 最後一個分支之後，依序疊上去：#66 M1 → #67 M2 → #68 M3 → #69 M4 → 本報告的 PR（M5）。
- 本票的測試與瀏覽器驗證都沒有呼叫真實的 OpenAI。

模組依賴：M1 唯讀 port ← M2 列表頁、M3 詳情頁（兩者只透過 M1 讀取資料）。M4 的 JS 只依賴 M2 的片段端點，以及 `POST /api/recommendations` 原有的回應。

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/ui/ui-flow.md` §2 | 路由表新增 `/ai?page=` 和 `/ai/history-list?page=`（列表片段），並移除「#16 實作」字樣 |
| `Docs/ui/ui-flow.md` §3.4 | 寫明以下行為：<br>• 推薦成功後重新取得第 1 頁列表，網址改回 `/ai`；推薦失敗時列表不變。<br>• 列表每列顯示的欄位、時間格式、分頁規則（同一般搜尋）。<br>• 詳情頁的內容；哪些欄位是快照、哪些即時讀取。 |
| `Docs/TODO.md` | 移除「/ai 頁面的 AI 搜尋紀錄列表」 |
| `Docs/plans/issue-16-ai-history.md` | 型別與方法名稱同步成實作的名稱 |

## M1 紀錄讀取（#66）

### 變更檔案

- `Application/Recommendation/IRecommendationHistory.cs`、`RecommendationSearchReadModels.cs`（新增；review 前的檔名是 `HistoryModels.cs`）
- `Infrastructure/Persistence/EfRecommendationHistory.cs`（新增）、`Program.cs`
- `tests/DatabaseIntegration/EfRecommendationHistoryTests.cs`（新增）

### 實作思路

- 列表的查詢條件是 `user_id = 目前使用者`，依 `created_at DESC, id DESC` 排序，加上 `id` 是為了讓同一時間的紀錄順序固定。結果數用 correlated subquery 計算，避免 N+1。
- 詳情用 `id AND user_id` 查詢，所以「別人的紀錄」和「不存在的紀錄」都回 `null`，外部看不出差別。
- rank、reason、relevance 來自保存時的快照；書名、封面、作者讀取目前的 Book 資料。
- 只讀書名和封面，不讀簡介或目錄。

### 執行紀錄（Log）

- 紅燈：先用一個會丟出 `NotImplementedException` 的 stub 跑測試，11 個全部失敗。
- Mutation：
  - Haiku 拿掉列表的 `user_id` 條件：4 個測試失敗。
  - 主 agent 拿掉詳情的 `user_id` 條件：1 個測試失敗。
- 頁碼溢位的修正寫在 M2（見下一節）。

### 驗證結果

新增 11 個 DatabaseIntegration 測試，涵蓋：
- 排序，以及同時間紀錄的排序方式
- 21 筆分成兩頁
- 結果數（含 0 本）
- 使用者之間的隔離
- 快照：書名修改後，rank、reason、relevance 不變

## M2 `/ai` 紀錄列表（#67）

### 變更檔案

- `Models/PageNumber.cs`（新增，從 `SearchController` 抽出）
- `Controllers/AiController.cs`、`Models/AiHistoryListViewModel.cs`、`Views/Ai/_AiHistoryList.cshtml`、`Views/Ai/Index.cshtml`、`wwwroot/css/site.css`
- `Infrastructure/Persistence/EfRecommendationHistory.cs`：修正 M1 的溢位
- 測試：`tests/UnitTests/PageNumberTests.cs`、`tests/WebIntegration/AiHistoryListTests.cs`（新增）、`AiPageTests.cs`

### 實作思路

- 列表的 HTML 只寫在一個 partial 裡，有兩個入口：
  - `/ai?page=N`：完整頁面。
  - `/ai/history-list?page=N`：只回傳列表片段，給 M4 使用。
- 分頁規則和 `/search` 相同：頁碼不是數字或小於 1 視為第 1 頁；超過最後一頁時，完整頁面轉址到最後一頁，片段則直接顯示最後一頁。
- **M1 的 bug**：offset 原本用 int 計算，頁碼極大時會溢位成負數，PostgreSQL 回 `2201X OFFSET must not be negative`。改成用 long 計算；offset 超過總筆數時直接回傳空結果，寫法和 `EfBookSearch` 相同。PR #66 已留言說明。

### 執行紀錄（Log）

- 紅燈：
  - 重構：編譯失敗。
  - 溢位：2 個 DB 測試失敗。
  - 新功能：21 個測試中 15 個失敗。
- `AiPageTests` 原本有一個測試斷言 `/ai` 沒有紀錄列表，和本票的功能相反，所以改寫。

### 驗證結果

新增 20 個 WebIntegration 測試，涵蓋：
- 使用者之間的隔離、排序、第 2 頁
- 台北時間、「N 本」的顯示
- 空狀態、轉址
- 片段內容與完整頁面中的列表一致
- 未登入時導向登入頁

## M3 `/ai/history/{id}` 詳情頁（#68）

### 變更檔案

- `Controllers/AiController.cs`（新增 `History`）、`Models/AiHistoryDetailViewModel.cs`、`Views/Ai/History.cshtml`、`Views/Ai/NotFound.cshtml`（新增）
- `tests/WebIntegration/AiHistoryDetailTests.cs`（新增）

### 實作思路

- 三種情況回傳同一個 404 頁：id 不是 GUID、紀錄不存在、紀錄屬於別人。
- 相關度的格式和 `/ai` 的推薦結果相同（`Math.round(relevance × 100)%`）。封面只接受 http(s) 網址，和 `ai.js` 一致。
- 難度目前固定顯示「—」，只由 `AiHistoryDetailViewModel.DifficultyPlaceholder` 一處控制，#18 會接上真正的值。

### 執行紀錄（Log）

- 紅燈：10 個測試全部回 404，因為路由還不存在。

### 驗證結果

新增 10 個 WebIntegration 測試，涵蓋：
- 頁面內容、快照、0 本結果
- 三種 404 的內文完全相同
- 未登入時導向登入頁，並帶 returnUrl
- 從列表點進來

## M4 推薦成功後更新列表（#69）

### 變更檔案

- `wwwroot/js/ai.js`

### 實作思路

- 推薦成功（200）後，抓 `/ai/history-list?page=1`，用回傳的片段整塊替換 `#ai-history`；如果網址帶有 query，就改回 `/ai`。
- JS 不組任何一列 HTML，也不計算頁數，所以原本「新增一筆後頁碼列不準」的問題在設計上就不會發生。
- 推薦失敗時不重抓列表。

### 驗證結果

見〈最終驗證〉的瀏覽器部分。

## 兩軸 Review

Standards 與 Spec 兩個 reviewer 平行審查 `issue-15-report...issue-16-report`，主 agent 逐項對照程式碼確認：

| # | 發現 | 判斷 | 處理 |
|---|---|---|---|
| 1 | **Bug**：推薦成功後重抓列表時如果 cookie 剛好失效，伺服器回 302 導向登入頁。`fetch` 會自動跟隨轉址，最後拿到 200 的登入頁，結果整個登入頁被寫進列表區塊。 | 成立 | `response.redirected` 視為失敗；回傳內容必須包含 `id="ai-history"` 才替換（`b2c72a0`）。瀏覽器驗證新增這個情境。 |
| 2 | 讀取模型取名 `History*`，不符合 CONTEXT.md 的用語（應為 Recommendation Search／Recommendation Result） | 成立 | 改名為 `RecommendationSearchPage`、`RecommendationSearchSummary`、`RecommendationSearchDetail`、`SavedRecommendationResult`（`a0cd6ae`）。port 名稱與路由依規格保留。 |
| 3 | 分頁列的 HTML 是從 `/search` 原樣複製，連 class `search-pager` 都一樣；兩個 view model 也重複同一組分頁欄位 | 成立 | 共用 `PagerViewModel` 與 `_Pager` partial，class 改成 `pager`（`894883b`） |
| 4 | 詳情頁的時間格式依賴列表的 view model | 成立 | 改用 `TaipeiTimeZone.FormatMinute`（`982ad1c`） |
| 5 | `/ai` 頁碼超出範圍時，會多查一次最後一頁；controller 的檔頭註解過時 | 成立 | `Index` 直接依總筆數轉址；更新檔頭註解（`6f716cc`） |
| 6 | `EfRecommendationHistory` 少了檔頭註解；`PageNumber` 引用了錯誤的章節 | 成立 | 已修正（`f7ed758`） |
| 7 | 封面只接受 http(s) 的規則，在 C# 與 `ai.js` 各寫了一份 | 判斷題 | 維持：兩邊各自要對同一份資料套用同一條規則，註解已寫明兩處要同步 |
| 8 | 詳情頁的難度固定為「—」 | 計劃內 | 交給 #18 處理 |

## 最終驗證

- `dotnet build`：0 warning。
- `dotnet test`：UnitTests 566、DatabaseIntegration 99、WebIntegration 255，全部通過。和 #15 完成時（552／86／231）相比，新增 14／13／24 個。
- 瀏覽器：Playwright headless Chromium，連 `https://localhost:5201`。推薦 API 用 `page.route` 模擬回應，`/ai/history-list` 打真實伺服器。11/11 通過：
  - `/ai?page=abc` 顯示空狀態。
  - 推薦回 502 時，列表不變、不重抓列表、網址不變。
  - 推薦回 200 時，顯示結果；列表被換成新的片段；只抓 `?page=1` 一次；網址改回 `/ai`。
  - cookie 失效時，有嘗試重抓列表，但登入頁沒有被寫進列表。
  - 沒有 JS 錯誤。
- **驗證的限制**：要讓推薦真的寫進 DB，就得呼叫 OpenAI 或直接寫入 DB 容器，這兩件事都沒有做。「新紀錄排在最前面」與「第 2 頁的內容」改由 M2 的 WebIntegration 測試證明：片段的內容和 `/ai?page=N` 的列表完全相同。
- 本機 DB 新增了 `m16-test-*` 測試帳號，是否刪除由使用者決定。

## 未解決事項（整張票）

- 詳情頁的難度要等 #18 才會顯示真正的值。
