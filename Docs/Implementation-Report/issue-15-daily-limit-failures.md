# Issue #15 AI 推薦：每日上限與失敗處理：實作報告

- Issue：#15 AI 推薦：每日上限與失敗處理（REC-09、REC-11）
- 計劃：`Docs/plans/issue-15-daily-limit-failures.md`（模組拆分、預設決定 §5）
- 規格：`Docs/modules/recommendation.md` §8、§11、§13、§14、`Docs/api/api-spec.md` §2、§3、`Docs/ui/ui-flow.md` §3.5
- 日期：2026-10-22
- 分工：
  - 主 agent：規劃、派工、驗收、撰寫文件；M6 改動很小，由主 agent 直接修改。
  - Haiku subagent：以 TDD 實作 M1～M5 與 review 修正。
  - 每個模組完成後，主 agent 親自執行 build 與測試、閱讀程式碼，L3 模組另做 mutation 抽查。
- PR：每個模組一個 PR，base 都是 `main`。分支接在 #12 的最後一個分支之後，依序疊上去：#59 M1 → #60 M2 → #61 M3 → #62 M4 → #63 M5 → #64 M6 → 本報告的 PR（M7）。
- 本票所有測試與瀏覽器驗證都沒有呼叫真實的 OpenAI。

模組依賴：

```text
M1 台北日界線 + DailyLimit 設定 ┐
M2 IRecommendationUsage         ├→ M3 每日上限關卡（service + 429）
M4 OpenAI 失敗 → 502             ┤
M5 60 秒逾時 → 504               ┘  → M6 前端訊息
```

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/modules/recommendation.md` §11 | 上限設定改用 `Recommendation:DailyLimit`；補上 429 的 type 與 title |
| `Docs/modules/recommendation.md` §13 | 新增以下內容：<br>• 60 秒是固定值，不開放設定。<br>• 計時範圍：從上限檢查之後開始，到保存為止。<br>• 使用者斷線不算逾時。<br>• 502 的條件與 title。<br>• `Recommendation:DailyLimit` 設定項。 |
| `Docs/modules/recommendation.md` §14 | 新增「未成功的推薦各記一行」，涵蓋三種情況：達上限、502、504 |
| `README.md` | 設定說明補上每日上限 |

## M1 台北日界線與 DailyLimit 設定（#59）

### 變更檔案

- `Models/TaipeiTimeZone.cs` 搬到 `Application/Common/TaipeiTimeZone.cs`（單獨一個 commit，純搬移），並新增 `StartOfDayUtc`。
- `Application/Recommendation/RecommendationOptions.cs`：新增 `DailyLimit` 與 `HasValidDailyLimit`。
- `Infrastructure/OpenAi/OpenAiServiceCollectionExtensions.cs`：加上啟動驗證。
- `appsettings.json`。
- 測試：`TaipeiTimeZoneTests`、`RecommendationOptionsTests`、`OpenAiServiceCollectionExtensionsTests`。

### 實作思路

- 每日上限的檢查在 Application 層，所以時區工具也要放在 Application，避免 Application 反過來依賴 `Models`。
- `StartOfDayUtc` 的做法：先把時間換成台北的日曆日，取當天 00:00，再轉回 UTC。

### 執行紀錄（Log）

- 紅燈：缺少 `StartOfDayUtc`、`DailyLimit`、`HasValidDailyLimit`，編譯失敗。
- 搬移的 commit 單獨跑過一次 UnitTests，521 個全部通過。

### 驗證結果

- 測試涵蓋三個邊界：台北 23:59:59、00:00、00:01，另外驗證 +08:00 輸入與 UTC 輸入結果相同。
- DailyLimit 設成 0 或 -1 時，啟動會失敗。

### 未解決事項／Code Review 與修正

見修正 2（`TaipeiTimeZone` 的開頭註解）。

## M2 今日使用次數查詢（#60）

### 變更檔案

- `Application/Recommendation/IRecommendationUsage.cs`、`Infrastructure/Persistence/EfRecommendationUsage.cs`（新增）。
- `Program.cs`：註冊上述服務。
- `tests/DatabaseIntegration/EfRecommendationUsageTests.cs`（新增）。

### 實作思路

計數和保存是兩件不同的事，所以獨立成一個新的 port，不擴充 `IRecommendationStore`。查詢會用到既有的 `(user_id, created_at DESC)` index。

### 執行紀錄（Log）

- 紅燈：編譯失敗。
- 主 agent 做了兩個 mutation，都被測試抓到：
  - 把 `>=` 改成 `>`：1 個測試失敗。
  - 拿掉 `user_id` 條件：4 個測試失敗。

### 驗證結果

新增 4 個 DatabaseIntegration 測試，涵蓋：只計算本人的搜尋、邊界時間的包含與排除、沒有紀錄時回 0、0 本結果的搜尋也算一次。

## M3 每日上限關卡（#61）

### 變更檔案

- `Application/Recommendation/RecommendationAttempt.cs`（新增）。
- `RecommendationService.cs`、`RecommendationsController.cs`、`ApiProblemResults.cs`（新增 `DailyLimitExceeded`）。
- `tests/WebIntegration/WebFixture.cs`：新增可替換的 `FakeTimeProvider Time`。
- 測試：`RecommendationServiceTests`、`RecommendationApiTests`。

### 實作思路

- 服務的第一步就是計數，早於需求解析。達到上限時直接回傳 `DailyLimitReached`，下游的 parser、embedding、candidate、ranker、store 都不會被呼叫。
- 回傳型別沿用 `LoginResult` 的模式。
- 不加鎖：規格 §11 已接受同時請求時可能超過上限 1～2 次。

### 執行紀錄（Log）

- 紅燈：編譯失敗。
- Mutation 抽查，兩個都被測試抓到：
  - Haiku 把判斷改成 `if (false && …)`：2 個 Web 測試失敗。
  - 主 agent 把檢查移到解析之後：2 個 Unit 測試失敗。

### 驗證結果

- WebIntegration 新增 4 個測試：
  - 第 21 次推薦回 429，而且所有 fake 都沒有被呼叫（REC-11 regression guard）。
  - 昨天的紀錄不算進今天的次數。
  - 台北時間 00:00 換日後可以再次使用。
  - 失敗的推薦不計入次數。
- UnitTests 新增 6 個。

## M4 OpenAI 失敗 → 502（#62）

### 變更檔案

- `Application/Recommendation/AiUnavailableException.cs`（新增）；三個 port 介面加上註明。
- `Infrastructure/OpenAi/OpenAiCall.cs`（新增）；三個 adapter 都改用它。
- `ApiExceptionProblemDetailsFilter.cs`、`ApiProblemResults.cs`（新增 `AiUnavailable`）。
- 測試：三個 adapter 的測試、`OpenAiTestTransport`（新增 `TimeoutHandler`）、`EmbeddingBackfillServiceTests`、`RecommendationApiTests`。

### 實作思路

- 三個 adapter 共用 `OpenAiCall.RunAsync`：任何失敗都包成 `AiUnavailableException`，原本的錯誤保留在 inner exception。
- 只有一種情況不包裝：呼叫端自己取消時，`OperationCanceledException` 原樣拋出，因為 M5 要靠它判斷是不是逾時。
- SDK 自己逾時（呼叫端並沒有取消）視為 AI 失敗，同樣包裝。
- 例外訊息不包含 API key，也不包含需求文字。

### 執行紀錄（Log）

- 紅燈：UnitTests 11 個失敗、WebIntegration 4 個失敗（回 500，預期 502）。
- 主 agent 做 mutation：把取消條件改成 `when (true)`，SDK 逾時的測試失敗，代表這個邊界有測到。

### 驗證結果

- 測試涵蓋：
  - parser、embedding、ranker 任一個失敗 → 502，資料庫沒有新增紀錄。
  - 非 AI 的錯誤仍然回 500。
  - Embedding 背景補齊遇到這個例外時，照常計為失敗並繼續處理下一本。

## M5 60 秒逾時 → 504（#63）

### 變更檔案

- `Application/Recommendation/AiTimeoutException.cs`（新增）、`RecommendationOptions.RequestTimeout`。
- `RecommendationService.cs`、filter、`ApiProblemResults.cs`（新增 `AiTimeout`）。
- `tests/Shared/CallGate.cs`（新增）；fake parser 與 fake ranker 加上 `Gate`。

### 實作思路

- 計時器使用注入的 `TimeProvider`，並與呼叫端的 token 連結。上限檢查在計時器之外；解析到保存都在計時器之內，所以逾時時不會保存任何資料。
- `CallGate` 的作用：讓 fake 停在呼叫裡等待，並通知測試「已經進入等待」。測試收到通知後才推進假時鐘，所以不需要真的 sleep。

### 執行紀錄（Log）

- 紅燈：編譯失敗。
- 新的 Web 測試連跑 5 次，5 次都通過。
- Mutation 抽查：
  - 把逾時的 catch 改成 `when (false)`：504 測試失敗。
  - 拿掉 `&& !cancellationToken.IsCancellationRequested`：沒有測試失敗。這是等價 mutation：使用者斷線時計時器並沒有到期，原本的條件本來就不成立；只有計時器到期和斷線同時發生時，這段才有差別。

### 驗證結果

- Unit：
  - 卡在 60 秒 → 逾時；卡在 59 秒 → 還沒逾時。
  - parser 卡住也會逾時。
  - 逾時時記一行 Warning。
  - 使用者自己取消時，不算逾時。
- Web：
  - 回 504，資料庫沒有新增紀錄。
  - 下一次請求回 200，而且逾時那一次不計入次數。

## M6 前端訊息（#64）

### 變更檔案

- `wwwroot/js/ai.js`

### 實作思路

- 收到 429 時顯示「今天的 AI 推薦次數已用完，明天再來」。
- 收到 502、504 或其他錯誤時，沿用 #13 的通用訊息。
- 不論哪一種失敗，輸入框的文字都保留。

### 驗證結果

瀏覽器驗證 11/11 通過。請求透過 `page.route` 攔截，模擬回 429、502、504，所以沒有呼叫 OpenAI。

## 兩軸 Review

Standards 與 Spec 兩個 reviewer 平行審查 `issue-12-report...issue-15-report`。主 agent 逐項對照程式碼確認：

| # | 發現 | 判斷 | 處理 |
|---|---|---|---|
| 1 | 502 時沒有 log 經過時間與失敗的步驟（計劃 M7、§14） | 成立 | service 新增 `catch (AiUnavailableException)`：記一行 Error（含經過時間、步驟、原始錯誤）後原樣拋出（`8268ccb`） |
| 2 | 逾時會記兩次 log：service 記 Warning，filter 又記一次 Error | 成立 | filter 遇到 AI 相關例外時不再記 log，交給 service 記（`8268ccb`） |
| 3 | filter 裡有兩段幾乎相同的 `if` | 成立 | 合併成一個 `switch`（`8268ccb`），並新增 `ApiExceptionProblemDetailsFilterTests`（主 agent 做 mutation：讓 filter 對 AI 例外也記 log，3 個測試失敗） |
| 4 | §13 沒有 `Recommendation:DailyLimit` | 成立 | 規格已同步（`ed5301f`） |
| 5 | `TaipeiTimeZone` 開頭註解過時；`OpenAiCall` 引用的章節不精確 | 成立 | 已修正（`4ff2b16`） |
| 6 | `ApiProblemResults` 與兩個 filter 放在 `Infrastructure/Identity`，但它們已經是整個 API 的錯誤對應表，命名空間名稱與用途不符 | 成立 | 這次先不改：要搬 5 個檔案，會牽動 #11～#15 的程式。列在未解決事項 |
| 7 | `step` 用字串表示；`RecommendAsync` 變長；`RequestTimeout` 放在 options 類別 | 判斷題 | 維持：`step` 只用來寫 log；`RequestTimeout` 的位置是計劃 M5 核准的 |

## 最終驗證

- `dotnet build`：0 warning。
- `dotnet test`：UnitTests 552、DatabaseIntegration 86、WebIntegration 231，全部通過。與 #12 完成時（521／82／224）相比，新增 31／4／7 個測試。
- 瀏覽器：見 M6，11/11 通過。

## 未解決事項（整張票）

- **review 第 6 項**：把 `ApiRequest`、`ApiProblemResults`、`AntiforgeryProblemDetailsFilter`、`ApiExceptionProblemDetailsFilter` 從 `Infrastructure/Identity` 搬到一個名稱符合用途的位置（例如 `Infrastructure/Web`）。這是純搬移，建議在 MVP 的 PR 都合併之後，單獨開一個 refactor PR。
- **§14 的兩個欄位**：「是否 fallback」與「Google Books 寫入數」目前寫死為 `false` 與 `0`，要等 #14 實作 fallback 後才會有實際值。
