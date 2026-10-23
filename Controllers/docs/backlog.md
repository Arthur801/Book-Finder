# Controllers 優化與 Debug 待辦

整理日期：2026-10-24；基準：`91333c3`。本文件僅記錄工作，不代表已修改程式或授權部署。`P1` 優先處理既有規格缺口，`P2` 補驗證與效能證據，`P3` 維護改善；此優先序不是正式 issue label。

狀態定義：**確認缺口**＝由現行程式與規格可直接對照；**明確暫緩**＝已有決定；**待驗證**＝調查題目，不宣稱已重現 bug；**改善提案**＝須以證據判斷是否值得做。所有項目目前均未在本次執行。

## 1. 功能缺口與優化

### CTL-01 — 接入 Google Books fallback

- [ ] **P1／確認缺口／L3**。影響 `RecommendationsController` 的回應行為，但主要實作應在 Application / Catalog adapters。
- 證據：`Application/Recommendation/RecommendationService.cs` 檢索後直接排序／保存；`Models/RecommendationResponse.cs` 固定 `FallbackUsed:false`，註解指出待 #14 接入。
- 規格：[recommendation.md §6](../../Docs/modules/recommendation.md)、[book-catalog.md §6](../../Docs/modules/book-catalog.md)、REC-03。
- 待辦：先完成 normalization、ISBN identity resolution 與保存，再接 Candidate `< 5` 分支；補 embedding 並重跑相同硬條件與 similarity 檢索。Controller 保持驗證／HTTP 映射責任，不能直接推薦 Google response 中的書。
- 驗收：本地候選 5 本時 Google fake 0 次；4 本時會呼叫；fallback 失敗使用既有候選；未過門檻不成候選；正確回傳與保存 fallback 狀態；仍遵守 60 秒 budget 與成功才保存。
- 測試入口：`RecommendationServiceTests`、`RecommendationApiTests`，以及未來 normalization 的 DB 整合測試；案例 `AI-F01`～`AI-F03`。

### CTL-02 — 恢復登入／註冊頻率限制

- [ ] **P2／明確暫緩／L3**，不是目前回歸 bug。
- 依據：[identity-auth.md §7](../../Docs/modules/identity-auth.md)、[Docs/TODO.md](../../Docs/TODO.md)：2026-10-20 暫緩。
- 前置決策：登入與註冊是否共用額度、成功請求是否計數，尚不能把過去建議當已核准規格。
- 待辦：決策後以 ASP.NET Core rate limiter 實作；IP 取已驗證的 Forwarded Headers；不得信任任意 caller 偽造的 forwarded IP。
- 驗收：同 IP 一分鐘第 6 次 429；不同 IP 隔離；新 window 恢復；一般表單錯誤提示與適用的 API 錯誤格式一致。完成前 `AUTH-F01` 保持暫緩。

### CTL-03 — 量測 AI history 分頁查詢成本

- [ ] **P3／改善提案／L2**。`AiController.Index` 已在 `6f716cc` 避免重導前額外讀末頁，不要重做已完成優化。
- 調查：紀錄列表大時，量測 COUNT／排序成本；完整頁應只讀所要求頁後決定重導，fragment 超頁才再讀末頁。
- 驗收：以可重現資料量記錄 query 數與延遲；若確需優化，維持每頁 20 筆、本人隔離、空紀錄不重導、片段不重導；勿直接改 cursor contract。
- 測試入口：`AiHistoryListTests`、`EfRecommendationHistoryTests`；案例 `HIST-02`～`HIST-04`。

### CTL-04 — 同步階段性文件敘述

- [ ] **P3／改善提案／L1**，須由後續允許編輯 Docs 的任務處理。
- 證據：`Docs/testing/test-plan.md` §2 仍稱 Web 測試為骨架；`book-catalog.md` §4.1 留有 #11 前 Library 空容器敘述。現況已有 Web 測試與 Library 區塊。
- 驗收：更新現況描述並保留歷史限定語意；不改 endpoint／Library contract；不要把 implementation report 升格為 authority。

## 2. Debug 調查與測試補強

### CTL-05 — 推薦 JSON model binding 邊界

- [ ] **P2／待驗證／L2**。沒有 `[ApiController]`，且 action 只以 `request?.RequirementText` 判斷輸入，不可假設所有 binding 錯誤都等價。
- 操作：登入且提供合法 CSRF，逐一測試空 body、破損 JSON、`null`、陣列、錯誤型別、JSON 後多餘 token、不同 Content-Type。
- 證據：擷取 status、Content-Type、ProblemDetails type/errors、fake 呼叫與 DB 搜尋數；既有 `RecommendationApiTests` 只作起點。
- 完成條件：分清已有 contract、框架 415 與規格未定義的 Content-Type 行為；發現差異先記錄／決定 contract，再做最小修正。不能直接沿用 Library PATCH 的「任何 Content-Type 皆解析」到推薦 API。
- 案例：`AI-02`、`DBG-01`。

### CTL-06 — API 非 action 階段錯誤格式

- [ ] **P2／待驗證／L2**。`ApiExceptionProblemDetailsFilter` 是 MVC exception filter，並非全域 middleware。
- 操作：用測試 host 檢查未知 `/api/...`、已知 API 的錯誤 HTTP method、body 超限、非 action 階段例外，必要時分別在 Development／非 Development 執行。
- 證據：記錄 404／405／413 等實際結果、response body 與 traceId；不要把未測路徑宣稱為已符合 ProblemDetails。
- 完成條件：先確認 `api-spec.md` 通則是否要求上述範圍；需要擴大一致性時再提方案與 contract 測試。維持頁面錯誤與 API 錯誤各自規則。
- 案例：`DBG-02`。

### CTL-07 — 取消請求與保存邊界

- [ ] **P2／待驗證／L3**。
- 操作：使用 fake clock / cancellable adapter 在 parse、embedding、檢索、排序、保存時取消；另在已保存後的 difficulty／排隊階段注入例外或 request cancellation。
- 現有保護：service 在每日 gate 後才啟動 60 秒 budget；保存後讀 difficulty／排隊改用 caller token；API filter 遇到已取消 request 不轉 500。
- 驗收：伺服器 budget 到期回 504 且未保存；使用者斷線不算 AI timeout；保存後一般 profile 失敗只 Warning，不把已成功搜尋改成 502／504。先證明 transaction 邊界，不根據 HTTP response 猜測 DB 狀態。
- 測試入口：`RecommendationServiceTests`、`RecommendationApiTests`、`ApiExceptionProblemDetailsFilterTests`、`BookDifficultyReaderTests`。
- 案例：`AI-10`、`AI-11`、`DBG-03`。

### CTL-08 — 個人化狀態與 cache 隔離

- [ ] **P2／待驗證／L3**。目前程式已將 Library 狀態排除於書目快取之外；此項是補強回歸證據，不宣稱存在洩漏。
- 操作：同一個 app instance、相同 bookId，先匿名暖快取，再以 A／B 兩個 cookie session 讀書籍頁；A 修改／移除後再讀。
- 驗收：共用 metadata 可命中 cache；各使用者只看到本人 Entry；匿名不查 Library store；修改後 Library 狀態立即更新，不受 10 分鐘書目 TTL 影響。
- 測試入口：`BookLibrarySectionTests`、`BookDetailPageTests`、`CachedBookDetailReaderTests`；案例 `BOOK-04`、`DBG-04`。

### CTL-09 — Conventional actions 的 method 邊界

- [ ] **P3／待驗證／L2**。Home.Index、Home.Error、Bestsellers.Index 沒有 `[HttpGet]`，現有 conventional route 不會單靠 action 命名限制方法。
- 操作：測試 GET／HEAD，以及提供合法 antiforgery 的 POST／其他方法；列出 endpoint routing 實際允許的方法與結果。
- 完成條件：由產品路由 contract 決定是否需要明確 method constraints，再更新實作與測試；不直接把所有 actions 加 attribute 當成無行為變更 refactor。
- 案例：`DBG-05`。

### CTL-10 — 部分列表並行變動的邊界

- [ ] **P3／待驗證／L2**。fragment 超頁有兩次 `history.ListAsync`；兩次讀取間資料可能改變，尚未證明會造成可見錯誤。
- 操作：以 fake history port 依序回傳不同 TotalCount／Items，測試第二次讀末頁前資料增加或清空；同時測完整頁與空紀錄。
- 完成條件：確認 ViewModel 不產生非法 pager 或重導迴圈；先以現有規則重現，再決定是否需要第二次計算，不任意改變穩定路徑。
- 案例：`DBG-06`。

## 3. Debug 執行與結案證據

1. 先對照 [architecture.md](architecture.md) 找責任層；HTML 404、API 404、authorization challenge、antiforgery 400 要分開記錄。
2. 使用 disposable Testcontainers DB、獨立 cookie session、fake 外部 adapters。不得以 production 重現，不呼叫真實 OpenAI、Google Books 或博客來。
3. 保存 request method/path、必要的去識別輸入、status、Content-Type、Location、ProblemDetails type/traceId、fake calls 與 DB 前後差異。不可記錄 cookie、JWT、密碼、secret 或原始私人需求文字。
4. 「有測試」不等於「已執行」；結案附命令、環境、實際通過／失敗／未執行結果。瀏覽器 JS 行為不能由 WebApplicationFactory 的 HTML 測試單獨證明。
5. 改 contract、schema、auth policy 或架構時先依根目錄 AGENTS 規範處理；本文件不構成對這些變更的額外授權。
