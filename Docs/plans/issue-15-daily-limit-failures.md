# #15 AI 推薦：每日上限與失敗處理：實作計劃

> 規格：`Docs/modules/recommendation.md` §8、§11、§13、§14、`Docs/api/api-spec.md` §2、§3、`Docs/ui/ui-flow.md` §3.5、`Docs/data/data-model.md` §5.11。
> 前置：#13 的 `RecommendationService`（各步驟透過 port 呼叫）。
> 風險：L3（AI 推薦 invariant：達上限時不得呼叫任何外部服務）。

## 1. 要做什麼

- 每人每天（Asia/Taipei 00:00 起算）最多 20 次成功的推薦；第 21 次回 429，**不呼叫任何外部服務**。
- OpenAI 任一呼叫失敗 → 502 `/errors/ai-unavailable`；整個推薦超過 60 秒 → 504 `/errors/ai-timeout`。兩者都不保存、不計次。
- 前端依狀態碼顯示對應訊息，失敗時保留輸入文字。
- 確認 log 包含 §14 列出的所有項目。

目前狀態（#13 Q1）：OpenAI 失敗一律走 `ApiExceptionProblemDetailsFilter` 回 500。

## 2. 模組總覽

```text
RecommendationsController
   │  呼叫
   ▼
RecommendationService.RecommendAsync
   │
   ├─ ① M3 每日上限關卡 ──▶ M1 TaipeiDay（純函式：今天從何時開始）
   │        │                M2 IRecommendationUsage.CountSinceAsync（數今天幾筆）
   │        └─ 已達上限 → 回傳 DailyLimitReached（不往下走）
   │
   ├─ ② M5 60 秒計時器包住「解析 → embedding → 檢索 → 排序 → 保存」
   │        └─ 計時器到期 → 拋 AiTimeoutException
   │
   └─ ③ OpenAI adapters（M4）失敗時一律拋 AiUnavailableException

例外 ──▶ M4/M5 ApiExceptionProblemDetailsFilter：AiUnavailable→502、AiTimeout→504、其他→500
回應 ──▶ M6 ai.js 依狀態碼顯示訊息
```

## 3. 各模組

### M1 台北日界線（Application，純函式）

**職責**：給一個 UTC 時間，算出那一天在台北的 00:00 是 UTC 的幾點。

**檔案**：把 `Models/TaipeiTimeZone.cs` 移到 `Application/Common/TaipeiTimeZone.cs`（Application 不應依賴 `Models`），新增 `StartOfDayUtc`。

**接口**：

```csharp
static class TaipeiTimeZone
    TimeZoneInfo Taipei { get; }                       // 既有
    DateTime StartOfDayUtc(DateTimeOffset nowUtc)     // 新增；例：2026-10-22T15:59Z → 2026-10-21T16:00Z
```

**設定**：`Recommendation:DailyLimit`（預設 20，必須 > 0，啟動時驗證），加在既有 `RecommendationOptions`。

**測試**：UnitTests——台北 23:59 / 00:00 / 00:01 三個邊界、設定驗證。

### M2 今日使用次數查詢（Application port + Infrastructure）

**職責**：數某位使用者從某個時間點起有幾筆 Recommendation Search。

**檔案**：`Application/Recommendation/IRecommendationUsage.cs`、`Infrastructure/Persistence/EfRecommendationUsage.cs`

**接口**：

```csharp
interface IRecommendationUsage
    Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken ct)
```

獨立成新介面而不是擴充 `IRecommendationStore`：保存與計數是兩件事，測試替身也比較小。查詢走既有的 `(user_id, created_at DESC)` index。

**測試**：DatabaseIntegration——只數自己的、只數 `created_at >= sinceUtc` 的。

### M3 每日上限關卡（Application + Web）

**職責**：在 Step 1（需求解析）**之前**擋下已達上限的請求。

**檔案**：`RecommendationService`、`RecommendationOutcome`、`RecommendationsController`

**接口變更**：

```csharp
// 服務的回傳改為兩種結果之一（沿用 LoginResult 的寫法）
abstract record RecommendationAttempt
    record Succeeded(RecommendationOutcome Outcome)
    record DailyLimitReached
```

**規則**：

- 服務第一件事：`usage.CountSinceAsync(userId, TaipeiTimeZone.StartOfDayUtc(time.GetUtcNow()))`；`>= DailyLimit` → `DailyLimitReached`，並記一行 Information log。
- 失敗的推薦本來就不會被保存，所以自然不計次；不需要額外邏輯。
- 不加鎖；同時送出多筆而超出 1～2 次可接受（規格 §11）。
- Controller：`DailyLimitReached` → 429 ProblemDetails，`type=/errors/daily-limit-exceeded`、`title=今天的 AI 推薦次數已用完`。

**測試**：

- UnitTests：達上限時 parser / embedding / candidate / ranker / store 的 fake 都沒被呼叫。
- WebIntegration：先寫入 20 筆當日紀錄，第 21 次 429 且 fake 未被呼叫（REC-11 regression guard）；用 `FakeTimeProvider` 推進到台北隔天 00:00 後可再使用；昨天的紀錄不算；`Content-Type` 為 `application/problem+json`。

### M4 OpenAI 失敗 → 502（Infrastructure + Web）

**職責**：讓「OpenAI 失敗」成為一種可辨識的錯誤，並對應到 502。

**檔案**：`Application/Recommendation/AiUnavailableException.cs`、`Infrastructure/OpenAi/*`（parser、ranker、embedding generator）、`ApiExceptionProblemDetailsFilter`

**規則**：

- 例外型別定義在 Application（服務與 filter 都看得到），由 `Infrastructure/OpenAi/` 的 adapter 拋出：SDK 錯誤（`ClientResultException`、網路錯誤）、拒答、格式不正確都包成 `AiUnavailableException`，原本的例外放在 `InnerException` 供 log 使用。
- 取消（`OperationCanceledException`）**不**包裝，留給 M5 判斷。
- 資料庫錯誤等其他例外維持 500。
- Embedding 補齊的背景工作本來就捕捉所有例外，行為不變。
- Filter：`AiUnavailableException` → 502 `/errors/ai-unavailable`，`title=AI 推薦暫時無法使用`。

**測試**：UnitTests（各 adapter 用 `OpenAiTestTransport` 模擬 500、拒答、壞 JSON → 拋 `AiUnavailableException`）；WebIntegration（排序 fake 拋錯 → 502、沒有新的 Recommendation Search、不計次）。

### M5 整體 60 秒逾時 → 504（Application + Web）

**職責**：推薦從開始到保存超過 60 秒就放棄，並且不保存。

**檔案**：`RecommendationService`、`Application/Recommendation/AiTimeoutException.cs`、`ApiExceptionProblemDetailsFilter`

**規則**：

- 服務建立 `CancellationTokenSource(TimeSpan.FromSeconds(60), time)`（用注入的 `TimeProvider`，測試可推進假時間），與 request 的取消 token 連結後傳給每一步。
- 計時器取消 → 拋 `AiTimeoutException`；使用者自己斷線 → 維持原本「不回應」的行為。
- 每日上限檢查在計時器之外，保存在計時器之內（逾時不保存）。
- 60 秒是規格固定值，寫成 `RecommendationOptions` 的常數，不開放設定（§13 的設定清單沒有它）。
- Filter：`AiTimeoutException` → 504 `/errors/ai-timeout`，`title=AI 推薦逾時`。

**測試**：UnitTests（fake ranker 等待取消、推進假時間 60 秒 → `AiTimeoutException`、store 未被呼叫；59 秒內完成則成功）；WebIntegration（504 + problem+json + 無新紀錄）。

### M6 前端訊息（JS）

**檔案**：`wwwroot/js/ai.js`

- 429 → 「今天的 AI 推薦次數已用完，明天再來」。
- 502 / 504 / 其他非 2xx → 「AI 推薦暫時無法使用，請稍後再試」，保留輸入文字（#13 已有，確認不退步）。

**測試**：瀏覽器手動驗證（用 fake 或在測試環境觸發 429）。

### M7 Logging 檢查、文件與報告

- 對照 §14 檢查：硬條件、Candidate Set 大小、similarity 最高／最低、fallback、結果數、丟棄編號、各呼叫耗時（#13 已有）。本票補上：達上限、502、504 各記一行（含已花費時間與失敗的步驟名稱），**不記需求文字與 API key**。
- `ApiExceptionProblemDetailsFilter` 開頭「502 and 504 … are mapped in #15」註解改寫。
- 規格同步、兩軸 review、`Docs/Implementation-Report/issue-15-daily-limit-failures.md`。

## 4. 模組之間的關係

- M1、M2 各自獨立、可單獨測試；M3 是唯一把它們組起來的地方。
- M4 讓 Infrastructure 對外只露出一種「AI 失敗」語意，服務與 controller 不需要認識 OpenAI SDK 的例外。
- M5 只在服務裡加一層計時，不改任何 port 介面。
- Filter 是錯誤 → HTTP 的唯一對應表；controller 只處理「達上限」這個正常結果。

## 5. 預設決定（局部、可逆；如不同意請指出）

1. 502 / 504 的 `title`：「AI 推薦暫時無法使用」／「AI 推薦逾時」（`api-spec.md` §2 只定義 `type`）。
2. 60 秒不開放設定。
3. Google Books（#14）的失敗不屬於本票的 502；#14 規定它失敗時以本地候選繼續。

## 6. 實作步驟

依 [README §3](README.md#3-共通的實作步驟每個模組都一樣)：

1. M1 `issue-15-m1-taipei-day` — UnitTests。
2. M2 `issue-15-m2-usage-count` — DatabaseIntegration。
3. M3 `issue-15-m3-daily-limit-gate` — UnitTests + WebIntegration；mutation 抽查（把檢查移到解析之後，「fake 未被呼叫」測試必須失敗）。
4. M4 `issue-15-m4-ai-unavailable` — UnitTests + WebIntegration。
5. M5 `issue-15-m5-timeout` — UnitTests + WebIntegration。
6. M6 `issue-15-m6-frontend-messages` — 瀏覽器手動驗證。
7. M7 `issue-15-report` — log 檢查、完整 `dotnet build` + `dotnet test`、瀏覽器手動驗證、review、文件、報告；關閉 #15。
