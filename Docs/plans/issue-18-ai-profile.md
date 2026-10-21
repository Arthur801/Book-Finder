# #18 Book AI Profile 與難度顯示：實作計劃

> 規格：`Docs/modules/recommendation.md` §2(10)、§3、§9、`Docs/data/data-model.md` §5.6、`Docs/api/api-spec.md` §3、`Docs/requirements/product-requirements.md` REC-07。
> 前置：#13（推薦流程）、#16（紀錄詳情頁）；#15 的 `AiUnavailableException`。
> 風險：L3（新的 OpenAI 呼叫、背景工作、推薦 invariant「排序不讀 profile」）。

## 1. 要做什麼

- 推薦結果保存後，把「還沒有 profile」或「profile 已過期（hash 不符）」的書排進記憶體佇列。
- 背景服務一本一本呼叫 OpenAI 產生 profile（summary、framework、key_topics、target_audience、difficulty），存進 `book_ai_profiles`。
- `POST /api/recommendations` 的 `difficulty` 與 `/ai/history/{id}` 即時讀取 profile 的 difficulty；沒有就顯示「—」。
- 排序完全不讀 profile；profile 不覆寫 `books.description`、`books.table_of_contents`。

## 2. 模組總覽

```text
 RecommendationService（保存後，依序）
        │ M6 ①：ReadDifficultiesAsync(結果的 bookIds) → 本次回應用的 difficulty 快照
        │ M6 ②：ScheduleAsync(結果的 bookIds)          → 排入佇列
        ▼
 BookProfileScheduler ──查──▶ M4 IBookProfileStore.FindStaleAsync ──▶ M1 BookProfileText（算 hash）
        │ 只把需要的 bookId 放進
        ▼
 M5 BookProfileQueue（Channel，去重）
        │
        ▼
 M5 BookProfileWorker（BackgroundService，一次一本）
        ├─ M4 IBookProfileStore.LoadInputAsync(bookId) ─▶ M1 BookProfileText
        ├─ M2 IBookProfileGenerator.GenerateAsync(input)  ◀── M3 OpenAiBookProfileGenerator（真實）
        │                                                  ◀── FakeBookProfileGenerator（測試）
        └─ M4 IBookProfileStore.UpsertAsync(...)

 顯示：
   推薦回應      ── 使用 ① 在排入佇列「之前」讀到的快照（RecommendationOutcome 帶出，controller 不再查 DB）
   #16 詳情頁   ── 每次即時呼叫 M4 IBookProfileStore.ReadDifficultiesAsync(bookIds)
```

寫入路徑（佇列 → 產生 → 保存）與讀取路徑（讀 difficulty）只共用資料表，不共用程式狀態。

## 3. 各模組

### M1 Profile 輸入文字與 hash（Application，純函式）

**職責**：把一本書的 metadata 組成固定格式的文字，並算出 `source_content_hash`。仿照既有 `BookEmbeddingText`。

**檔案**：`Application/Recommendation/BookProfileText.cs`

**接口**：

```csharp
record BookProfileSource(string Title, string? Subtitle, IReadOnlyList<string> Contributors,
                         string? Publisher, IReadOnlyList<string> Subjects,
                         string? Description, string? TableOfContents)

static class BookProfileText
    string Build(BookProfileSource source)   // 固定欄位順序、空值整行省略、長文字以 code point 截斷
    string Hash(string text)                 // UTF-8 SHA-256，64 字元小寫 hex
```

輸入只能是上述 metadata（`data-model.md` §5.6）。欄位格式與截斷長度見 §5 Q1、Q3。

**測試**：UnitTests——欄位順序、空值省略、截斷不切斷 surrogate pair、hash 穩定、目錄有無會改變 hash。

### M2 Profile 產生器介面與 fake（Application + tests/Shared）

**職責**：定義「給 metadata，拿回 profile」的介面與輸出規則。

**檔案**：`Application/Recommendation/IBookProfileGenerator.cs`、`GeneratedBookProfile.cs`、`tests/Shared/FakeBookProfileGenerator.cs`

**接口**：

```csharp
interface IBookProfileGenerator
    string ModelName { get; }
    string PromptVersion { get; }
    Task<GeneratedBookProfile> GenerateAsync(string profileText, bool hasTableOfContents, CancellationToken ct)

record GeneratedBookProfile(string? Summary, JsonDocument? Framework, IReadOnlyList<string>? KeyTopics,
                            string? TargetAudience, short? Difficulty)
```

**規則**（`GeneratedBookProfile` 的正規化，放在 Application，不信任 LLM 輸出）：

- `difficulty` 不在 1～5 → 存 `null`（不 clamp，避免猜測）並記 Warning。
- 空白字串 → `null`。

**測試**：UnitTests（正規化規則、fake 的行為）。

### M3 OpenAI profile 產生器（Infrastructure/OpenAi）

**職責**：一次 chat 呼叫（structured output）產生 profile。

**檔案**：`Infrastructure/OpenAi/OpenAiBookProfileGenerator.cs`

**規則**：

- Prompt 只放 M1 的文字；要求繁體中文、以自己的話撰寫。
- 沒有目錄時（`hasTableOfContents = false`），prompt 明確要求 framework 是「推論的內容概覽」，JSON 中 `is_official_toc` 必須為 `false`；系統端再強制設成 `false`，不信任 LLM（`data-model.md` §5.6）。
- 失敗包成 `AiUnavailableException`（沿用 #15）。
- `PromptVersion` 為程式內常數（例如 `"profile-v1"`），prompt 改動時遞增。

**測試**：UnitTests 用 `OpenAiTestTransport`——request 內容（schema、無目錄時的指示）、回應解析、拒答/壞 JSON 拋例外、無目錄時 `is_official_toc` 被強制為 false。

### M4 Profile 資料存取（Application port + Infrastructure）

**職責**：讀寫 `book_ai_profiles`，以及讀出產生 profile 所需的 metadata。

**檔案**：`Application/Recommendation/IBookProfileStore.cs`、`Infrastructure/Persistence/EfBookProfileStore.cs`

**接口**：

```csharp
interface IBookProfileStore
    // 回傳這些書中「沒有 profile 或 hash 不符」的 bookId
    Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken ct)
    Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken ct)
    Task UpsertAsync(Guid bookId, GeneratedBookProfile profile, string sourceHash,
                     string modelName, string promptVersion, CancellationToken ct)
    Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken ct)
```

**規則**：

- 只寫 `book_ai_profiles`，**絕不**更新 `books` 的任何欄位。
- `FindStaleAsync` 讀 metadata、用 M1 算 hash 後比對（只看傳入的最多 10 本，不做全表掃描）。
- `ReadDifficultiesAsync` 只回傳 difficulty 不為 null 的書。

**測試**：DatabaseIntegration——沒有 profile／hash 相符／hash 不符三種、upsert 覆蓋舊 profile、`books.description` 與 `table_of_contents` 不變、difficulty 讀取。

### M5 佇列與背景服務（Infrastructure/BackgroundJobs）

**職責**：在記憶體中排隊、在背景一本一本產生 profile。

**檔案**：`Application/Recommendation/IBookProfileQueue.cs`、`Infrastructure/BackgroundJobs/BookProfileQueue.cs`、`BookProfileWorker.cs`

**接口**：

```csharp
interface IBookProfileQueue
    bool TryEnqueue(Guid bookId)          // 已在佇列中或正在處理 → 不重複加入；佇列滿 → 丟棄並回 false
    void Complete(Guid bookId)            // worker 處理完一本（成功或失敗）後呼叫，解除去重
// Worker 內部：ReadAllAsync → LoadSource → Build/Hash → Generate → Upsert → finally Complete
```

**規則**：

- `Channel` 有上限（預設 1000）。
- 去重：同一本書從排入到**處理完成**之間只會有一筆（用 `ConcurrentDictionary` 記錄）。
  - key 在 `TryEnqueue` 時加入，worker 處理完後在 `finally` 呼叫 `Complete` 才移除；**不是**取出時就移除。否則書正在呼叫 OpenAI 時又可以被排入一次，浪費佇列空間。
  - 佇列滿而寫入失敗時，立即移除剛加入的 key，下次出現時才能重新排入。
- Worker 一次處理一本，不平行；每本開新的 DI scope（DbContext 不跨書共用）。
- 單本失敗：記 Error log、跳過；不重試（下次出現在推薦結果時會重新排入，規格 §9）。
- 處理前再確認一次 hash（排隊期間可能已有 profile）。
- 停機取消不算失敗；重啟遺失佇列可接受。
- 設定 `AiProfile:Enabled`（預設 `true`，本機可關閉），仿照 `Embedding:BackfillEnabled`。

**測試**：UnitTests——去重、**處理中（產生器尚未返回）再次 `TryEnqueue` 回 false、處理完成後可再排入**、產生器失敗時 key 也會解除、滿了丟棄且 key 被移除、失敗後繼續下一本、取消時乾淨結束、hash 已相符時不呼叫產生器。

### M6 接進推薦流程與顯示（Application + Web）

**職責**：保存後排入佇列；回應與紀錄詳情顯示 difficulty。

**檔案**：`Application/Recommendation/BookProfileScheduler.cs`、`RecommendationService`、`RecommendationOutcome`、`RecommendationResponse`、`AiController.History`（#16）

**為什麼要固定順序**：如果先排入佇列、之後才由 controller 讀 difficulty，worker 可能在這兩步之間就產生好 profile，第一次推薦的回應會有時是 `null`、有時有值。這違反 issue AC「第一次推薦時 `difficulty` 為 null」，也會讓整合測試時好時壞。

**規則**：

- `RecommendationService` 保存成功之後，**依序**做兩件事：
  1. `ReadDifficultiesAsync(結果 bookIds)`：讀出目前已存在的 difficulty，作為**本次回應的快照**，放進 `RecommendationOutcome`（例如 `IReadOnlyDictionary<Guid, short> Difficulties`）。
  2. `BookProfileScheduler.ScheduleAsync(bookIds)`：`FindStaleAsync` → `TryEnqueue`。
- 因為快照在排入佇列**之前**就讀完，worker 再快也不會影響本次回應。
- 這兩步的任何例外都只記 log，**不讓推薦失敗**（推薦已經保存成功）：讀取失敗時快照為空（全部 `null`），排入失敗時不排入。
- 排序呼叫前後都不讀 profile；difficulty 只在保存之後讀取，只用於顯示（規格 §2(10)）。
- 推薦回應：`RecommendationResponse` 直接用 outcome 的快照填 `difficulty`，沒有就是 `null`；controller 不再查詢資料庫。
- `/ai/history/{id}`：每次即時呼叫 `ReadDifficultiesAsync`，沒有顯示「—」。difficulty 不寫入 `recommendation_results`。

**測試**：

- UnitTests：
  - 呼叫順序為 save → read difficulties → schedule（用 fake 記錄呼叫順序）。
  - 讀取或排入失敗不影響結果。
  - ranker fake 收到的輸入不含 profile 欄位。
- WebIntegration（不依賴時間）：
  - 讓 fake 產生器**同步、立即**完成，確認第一次推薦的 `difficulty` 仍為 null。這個情境在舊的順序下會失敗，是本項的 regression guard。
  - 等 worker 處理完後，再次推薦與紀錄詳情都會顯示難度。
  - hash 相符的書不再排入。

### M7 文件與報告

- `recommendation.md` §9 補上 Q1～Q5 的決定與 `AiProfile:*` 設定；`README.md` 設定說明。
- `RecommendationResponse.cs` 中「Difficulty … always null」註解改掉。
- 兩軸 review、`Docs/Implementation-Report/issue-18-ai-profile.md`。
- 真實 OpenAI 試跑**需使用者當下授權**。

## 4. 模組之間的關係

- M1、M2 是純定義，不依賴任何其他模組。
- M3 只實作 M2；M4 只用 M1 算 hash。
- M5 只透過 M2、M4 的介面工作，可用 fake 完整測試。
- M6 是唯一碰推薦流程的模組；它只多做「保存後讀 difficulty 快照、再通知排入佇列」，推薦既有的 port 介面不需要改，只在 `RecommendationOutcome` 多帶一份快照。

## 5. 使用者決定（2026-10-22，Q1～Q5 皆採建議）

規格原本沒有定義以下事項，由使用者決定。M7 會把這些決定寫回 `recommendation.md` §9。

- **Q1 `source_content_hash` 的輸入**：對 M1 `BookProfileText.Build` 的輸出計算。
  - 輸出包含書名、副標題、作者、出版社、分類、簡介、目錄，格式仿照 `BookEmbeddingText`。
  - metadata 有任何變動就會重新產生；model 或 prompt 版本改變不會觸發（與 embedding 的規則一致）。
- **Q2 chat model**：沿用 `Recommendation:ChatModel`（目前為 `gpt-6-luna`），不新增設定。
- **Q3 長度上限**：簡介取前 2000 個 code point（與 embedding 相同），目錄也取前 2000 個 code point。
- **Q4 difficulty 1～5 的定義**（寫進 prompt）：
  - 1 = 沒有背景知識也能輕鬆讀
  - 2 = 一般大眾讀物
  - 3 = 需要專注，或需要少量背景知識
  - 4 = 需要該領域的基礎
  - 5 = 專業或學術程度
- **Q5 `framework` 的 JSON 格式**：`{ "is_official_toc": bool, "sections": [{ "title": "…", "summary": "…" }] }`，最多 10 個 section。
  - `is_official_toc` 只有在書有真實目錄時可以為 `true`。

## 6. 預設決定（局部、可逆；如不同意請指出）

1. 佇列上限 1000，滿了丟棄（下次出現時會重新排入）。
2. 單本產生失敗不重試。
3. difficulty 超出 1～5 時存 `null`，不 clamp。
4. 新增 `AiProfile:Enabled` 開關（預設開啟）。

## 7. 實作步驟

依 [README §3](README.md#3-共通的實作步驟每個模組都一樣)：

1. M1 `issue-18-m1-profile-text` — UnitTests。
2. M2 `issue-18-m2-generator-port` — UnitTests。
3. M3 `issue-18-m3-openai-profile` — UnitTests（不呼叫真實 API）。
4. M4 `issue-18-m4-profile-store` — DatabaseIntegration。
5. M5 `issue-18-m5-queue-worker` — UnitTests。
6. M6 `issue-18-m6-wire-and-display` — UnitTests + WebIntegration；mutation 抽查（讓 ranker 輸入帶 profile、把 schedule 移到 read difficulties 之前，對應測試都必須失敗）。
7. M7 `issue-18-report` — 完整 `dotnet build` + `dotnet test`、瀏覽器手動驗證、review、文件、報告；（經授權）真實試跑；關閉 #18。
