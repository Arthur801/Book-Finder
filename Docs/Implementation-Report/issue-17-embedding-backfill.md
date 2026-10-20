# Issue #17 Embedding 背景補齊：實作報告

- Issue：#17 Embedding 背景補齊（GitHub 依賴已改為 #17 block #13）
- Branch：`issue-17-embedding-backfill`（from `main` `ba08f4f`）；每個 small module 各開一個疊加式 PR（#28～#33，E7 為最後一個）。
- 規格：`Docs/modules/recommendation.md` §10、`Docs/architecture/system-architecture.md` §5.3 / §6、`Docs/data/data-model.md` §5.7、ADR-003、`Docs/testing/test-plan.md`
- 使用者決定（2026-10-20，已寫入 `c73988f`、`4d04d3c` 的規格更新）：
  - Q1 使用官方 `OpenAI` NuGet 套件（2.14.0）。
  - Q2 缺 key 時啟動失敗；設定鍵名為 `OPENAIAPI_KEY`。
  - Q3 其他設定放 `Embedding:`（Model、Interval、BatchSize、BackfillEnabled）。
  - Q4 輸入文字格式：每欄一行加標籤、空欄位省略、作者依 `contributor_order`、分類去重 ordinal 排序、簡介前 2000 code point。
  - Q5 沒有簡介也產生 embedding。
  - Q6 每輪全量讀取並在 C# 比對 hash；效能疑慮記錄於 `Docs/TODO.md`。
  - Q7 先「沒有 embedding」再「hash 不符」，各組 `created_at` 新到舊，每輪最多 100 本。
  - Q8 只看 hash，`model_name` 不同不重建。
  - Q9 每本書一次 API 呼叫，依序執行，單本失敗繼續。
  - Q10 連續失敗 5 本提早結束該輪。
  - Q11 不檢查維度直接寫入，但記 log。
  - Q12 啟動後立即一輪，之後每 10 分鐘，同時間只有一輪。
  - Q13 AC「可被推薦檢索到」改為「可用 pgvector `<=>` 查詢到」。
- 日期：2026-10-20～2026-10-21
- 分工：主 agent 規劃、派工、驗收、撰寫本報告；E1～E7（文件同步）由 Haiku subagent 以 TDD 實作。每個模組完成後，主 agent 親自執行 build 與測試並閱讀程式碼，通過後開 PR，由使用者 review 與合併。

模組依賴：E1 輸入文字與 hash → E3 資料庫讀寫；E2 產生器介面 → E4 一輪補齊 ← E3；E2 → E5 OpenAI 實作；E4 + E5 → E6 計時器與接線 → E7 文件。

```text
EmbeddingBackfillWorker（E6，計時器）
  └─ EmbeddingBackfillService.RunOnceAsync（E4，領班）
       ├─ IEmbeddingStore.FindPendingAsync / SaveAsync（E3，EF Core + pgvector）
       │    └─ BookEmbeddingText.Build / Hash（E1，純函式）
       └─ IEmbeddingGenerator.GenerateAsync（E2 介面；E5 OpenAI 實作；測試用 fake）
```

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/modules/recommendation.md` | §10：輸入文字格式、hash 規則、待補齊判定與排序、執行與失敗、排程與設定、啟動時驗證。§13：embedding 設定改參照 §10。key 來源改為「環境變數或 user-secrets，不得寫入 repository 內的設定檔」。 |
| `Docs/architecture/system-architecture.md` | §5.3：改為「啟動時與之後每 10 分鐘，為缺少 embedding 或 hash 不符的 Book 產生 embedding」。 |
| `Docs/TODO.md` | 新增「Embedding 補齊：每輪全量讀取」（Q6）。 |
| `Docs/deployment/deployment.md` | §1、§5：SSM `openai-api-key` 注入為 `OPENAIAPI_KEY`；`Embedding__*` 非機密設定與預設值。 |
| `Docs/testing/test-plan.md` | §3：WebIntegration 關閉背景補齊、換成 `FakeEmbeddingGenerator`、直接觸發一輪。 |
| `README.md` | 本機 `.env` 需要 `OPENAIAPI_KEY`；背景補齊會產生費用，可用 `Embedding__BackfillEnabled=false` 關閉。 |
| GitHub #13、#17 | 依賴改為 #17 block #13；#17 改為建立 Embedding 產生器介面；#17 的 AC 依 Q13 調整。 |

## E1 輸入文字與 hash（PR #28）

### 變更檔案
- `Application/Recommendation/BookEmbeddingSource.cs`
- `Application/Recommendation/BookEmbeddingText.cs`
- `tests/UnitTests/BookEmbeddingTextTests.cs`（26 個測試）

### 實作思路
hash 決定書是否需要重做，所以把格式集中在一個純函式。簡介截斷以 `Rune` 計數，避免切斷 surrogate pair。hash 為 UTF-8 bytes 的 SHA-256 小寫 hex，對應 `char(64)`。

### 執行紀錄（Log）
- 紅：測試編譯失敗（CS0246，`BookEmbeddingSource` 不存在）。
- 綠：UnitTests 187 全過。

### 驗證結果
主 agent 閱讀程式碼並對照 Q4；build 0 warning；UnitTests 187 / 187。

### 未解決事項
無。

### Code Review 與修正
無對應發現。

## E2 產生器介面與 fake（PR #29）

### 變更檔案
- `Application/Recommendation/IEmbeddingGenerator.cs`
- `tests/Shared/FakeEmbeddingGenerator.cs`（以 `<Compile Include … Link>` 同時編進 UnitTests 與 WebIntegration）
- `tests/UnitTests/FakeEmbeddingGeneratorTests.cs`（9 個測試）

### 實作思路
介面只有 `ModelName` 與 `GenerateAsync`，#13 會沿用。fake 可指定回傳向量或例外、記錄每次呼叫；未指定的文字回傳 1536 維、第 0 維為 1 的預設向量。

### 執行紀錄（Log）
- 紅：CS2001（共用檔不存在）；之後一次 CS4007（`ReadOnlySpan` 跨 await），修正測試寫法。
- 綠：UnitTests 196 全過。

### 驗證結果
UnitTests 196 / 196；root 與 WebIntegration build 0 warning。

### 未解決事項
無。

### Code Review 與修正
- `Dimensions` 寫死 1536 → 改為引用 `EmbeddingBackfillService.ExpectedDimensions`（`2b7a13e`）。

## E3 資料庫讀寫（PR #30）

### 變更檔案
- `Application/Recommendation/IEmbeddingStore.cs`、`PendingEmbedding.cs`
- `Infrastructure/Persistence/EfEmbeddingStore.cs`
- `tests/DatabaseIntegration/EfEmbeddingStoreTests.cs`（11 個測試，獨立的 `EmbeddingStoreCollection` container）

### 實作思路
- `FindPendingAsync`：四個 `AsNoTracking` 查詢（books、contributors、subjects、既有 hash，不讀向量），在記憶體分組後用 E1 計算 hash 並比對。
- `SaveAsync`：一條 `INSERT … ON CONFLICT (book_id) DO UPDATE`，不經 change tracker。若用 tracked entity，某本書因維度不符寫入失敗後，entity 會留在 tracker 裡，導致下一本也跟著失敗。

### 執行紀錄（Log）
- subagent 先寫實作再寫測試，沒有紅燈紀錄（偏離 TDD）。
- 主 agent 以兩個 mutation 補驗：讓「hash 不同」分支永不成立 → 2 個測試失敗；upsert 改成 `DO NOTHING` → 1 個測試失敗。

### 驗證結果
DatabaseIntegration 30 / 30（新增 11）；UnitTests 196 / 196；build 0 warning。

### 未解決事項
每輪全量讀取，見 `Docs/TODO.md`。

### Code Review 與修正
- 過時註解「TODO.md added by a later module」→ 刪除（`2b7a13e`）。
- `SaveAsync(bookId, vector, modelName, hash)` 屬於 Data Clumps → 改為 `SaveAsync(PendingEmbedding, vector, modelName)`（`2b7a13e`）。
- private `NewestFirst` 移到 public 方法之後（`2b7a13e`）。

## E4 一輪補齊（PR #31）

### 變更檔案
- `Application/Recommendation/EmbeddingOptions.cs`、`EmbeddingBackfillResult.cs`、`EmbeddingBackfillService.cs`
- `tests/UnitTests/EmbeddingBackfillServiceTests.cs`（10 個測試）

### 實作思路
只依賴兩個介面。依序處理；維度不符記 Warning 仍寫入（Q11）；非取消例外記 Error 並計入連續失敗，成功時歸零；連續 5 本失敗就提早結束（Q10）；取消往外拋；結束時記一筆摘要 log。

### 執行紀錄（Log）
- 骨架 stub 紅：Failed 9 / Passed 1（空清單測試因 stub 而通過）。
- 綠：UnitTests 206 全過。

### 驗證結果
UnitTests 206 / 206；build 0 warning；主 agent 對照 Q9～Q11 閱讀程式碼。

### 未解決事項
無。

### Code Review 與修正
- `EmbeddingOptions` 中「later step」的過時註解 → 改為描述目前的讀取者（`2b7a13e`）。

## E5 OpenAI 實作與設定（PR #32）

### 變更檔案
- `Book-Finder.csproj`：新增 `OpenAI` 2.14.0（diff 只有這一行）
- `Infrastructure/OpenAi/OpenAiOptions.cs`、`OpenAiEmbeddingGenerator.cs`、`OpenAiServiceCollectionExtensions.cs`
- `tests/UnitTests/OpenAiEmbeddingGeneratorTests.cs`（5 個）、`OpenAiServiceCollectionExtensionsTests.cs`（3 個）

### 實作思路
`EmbeddingClient.GenerateEmbeddingAsync` → `ToFloats()`，不送 dimensions，不捕捉例外。key 從設定鍵 `OPENAIAPI_KEY` 讀取並以 `ValidateOnStart` 驗證。測試全部使用假的 HTTP transport，並關閉 retry。

### 執行紀錄（Log）
- 骨架 stub 紅：Failed 7 / Passed 1。
- 綠：UnitTests 214 全過。
- `dotnet add package` 會把 csproj 中多行的 `Content Update` 合併成一行，subagent 已手動還原。

### 驗證結果
UnitTests 214 / 214；root、UnitTests、WebIntegration、DatabaseIntegration build 皆 0 warning；沒有任何測試呼叫真實 API。

### 未解決事項
- **重試**：production 保留 SDK 預設 retry policy（只對暫時性錯誤以 backoff 重試），重試後仍失敗才計入 E4 的連續失敗。這是主 agent 依 AGENTS §2.5 做的低風險預設，已寫入 §10。commit `137e5fe` 的訊息「Retries are left to the caller」描述不正確；依慣例不 amend，以本報告與 PR #32 為準。

### Code Review 與修正
- 缺 key 的錯誤訊息寫死 key 名稱 → 改由 `OpenAiOptions.ApiKeyName` 組成（`2b7a13e`）。
- `TimeProvider` 只在 auth 註冊，形成隱性依賴 → `AddBookFinderOpenAi` 也加上 `TryAddSingleton(TimeProvider.System)`（`2b7a13e`）。
- `OpenAiEmbeddingGenerator` 為 `public`：UnitTests 直接使用，且 repo 內 public / internal 本來就混用，**不修改**。

## E6 計時器與接線（PR #33）

### 變更檔案
- `Infrastructure/BackgroundJobs/EmbeddingBackfillWorker.cs`
- `Program.cs`、`appsettings.json`（`Embedding` 區段，不含 key）
- `Application/Recommendation/EmbeddingOptions.cs`、`Infrastructure/OpenAi/OpenAiServiceCollectionExtensions.cs`：Interval / BatchSize / Model 啟動時驗證（`a6f4a07`）
- `tests/WebIntegration/WebFixture.cs`：placeholder key、`Embedding:BackfillEnabled=false`、公開 `Embeddings` fake
- `tests/UnitTests/UnitTests.csproj`：新增 `Microsoft.Extensions.TimeProvider.Testing`（只加在測試專案）
- `tests/UnitTests/EmbeddingBackfillWorkerTests.cs`（5 個）、`tests/WebIntegration/EmbeddingBackfillTests.cs`

### 實作思路
`PeriodicTimer(Interval, TimeProvider)`：啟動時先跑一輪，之後每個 tick 跑一輪，同時間只有一輪。每輪使用新的 DI scope。每輪的例外只記 log，避免 .NET 預設的「背景服務例外會停止整個 host」。

### 執行紀錄（Log）
- Worker 骨架紅：4 個 `Timed out waiting for the backfill round`。實作後仍有 4 個失敗，原因是測試容器沒有註冊 `ILogger<EmbeddingBackfillService>`，修正測試後全過。
- Web 紅：`No service for type 'EmbeddingBackfillService'`；缺 key 測試出現 `No exception was thrown`。接線後全過。
- subagent 指出 `Interval ≤ 0` 會讓 `PeriodicTimer` 在 round handler 外丟出例外 → 主 agent 要求加上啟動時驗證：紅 3 個 → 綠。

### 驗證結果
UnitTests 223、DatabaseIntegration 30、WebIntegration 129，全過；build 0 warning。

### 未解決事項
- 合併後本機與 production 都需要 `OPENAIAPI_KEY`，沒有就無法啟動（Q2）。這與 system-architecture §6「OpenAI 不可用不影響其他功能」在精神上不一致，但屬於使用者核准的決定。

### Code Review 與修正
- Spec：Interval / BatchSize / Model 啟動驗證不在原規格內（scope creep）→ 屬低風險預設，已寫入文件，保留。

## E7 文件與報告（本 PR）

### 變更檔案
見「規格文件更新」與本報告；review 修正的 commit 為 `2b7a13e`（程式）、`5cd00d8`（測試）、`4d04d3c`（文件）。

### 實作思路
規格依實際行為同步，並把 Q4～Q13 的決定寫回 authoritative 文件（recommendation §10）。

### 執行紀錄（Log）
`c73988f` 文件同步 → 兩軸 code review → 三個修正 commit → 本機真實環境驗證 → 本報告。

### 驗證結果
見下方「最終驗證」。

### 未解決事項
無。

### Code Review 與修正
- Spec：AC「metadata 改變後下一輪重新產生」缺少端對端測試 → 新增 `A_changed_title_is_embedded_again_on_the_next_round_and_the_row_is_overwritten`。它第一次執行就通過（行為原本就正確），subagent 以 mutation（停用 hash 不符分支）確認測試會失敗（`5cd00d8`）。
- Spec：端對端只種一本書 → 改為 3 本（`5cd00d8`）。
- Spec：§10「key 只來自環境變數」與程式不符 → 改為「環境變數或 user-secrets」；system-architecture §5.3 補上 hash 不符（`4d04d3c`）。

## 最終驗證

### 自動化測試（`4d04d3c`）
| 項目 | 結果 |
|---|---|
| `dotnet build` | 0 warning、0 error |
| UnitTests | 223 / 223 |
| DatabaseIntegration | 30 / 30 |
| WebIntegration | 130 / 130 |

### 本機真實環境（使用者授權，2026-10-21）
- 環境：本機 Docker `book-finder-db-1`（pgvector 0.8.7，migration 已套用至 `20261010204858_Embedding`），1943 本書，原有 embedding 0 筆。
- 從 worktree 執行一次網站（`Embedding__BackfillEnabled=true`），第一輪結束後立即停止：
  - log：`Embedding backfill round finished: 100 succeeded, 0 failed, stopped early: False`，耗時約 32 秒；沒有單本失敗，也沒有維度警告。
- PostgreSQL 唯讀查詢：
  - `book_embeddings` 共 100 列，對應 100 本不同的書；`vector_dims` 全部為 1536；`model_name` = `text-embedding-3-small`；hash 皆為 64 字元小寫 hex。
  - 向量 norm 為 0.9995～1.0004（OpenAI 回傳的是正規化向量）。
  - `<=>` 最近鄰：查詢《肌力與體能訓練(增修版)》，最近的是《NSCA私人教練》（similarity 0.6975），結果合理。
  - 剩餘待補齊 1843 本，會由之後每輪補上。
- 過程中遇到的環境問題（與程式無關）：
  1. WSL 系統的 PostgreSQL 18（`postgresql@18-main`，10/16 起開機自動啟動）占用了 5432 → 由使用者暫時停止。
  2. 第一次啟動容器因端口衝突失敗，容器因此脫離 `book-finder_default` network（沒有 IP，port 也沒有 publish）→ 以 `docker network connect --alias db book-finder_default book-finder-db-1` 加上 restart 修復，沒有重建容器，volume 資料不受影響。
  3. 本機 `.env` 沒有 `Jwt__SigningKey` → 這次只在該 process 的環境變數中使用臨時隨機 key，沒有寫入任何檔案。
- 測試結束後已停止 `book-finder-db-1`。

### 尚待使用者處理
- 系統 PostgreSQL 18 若要恢復：`sudo systemctl start postgresql`。但它會再次占用 5432，與專案的 Docker DB 衝突，需要決定其中一方改用其他端口，或停用開機自動啟動。
- 本機 `.env` 需要補上 `Jwt__SigningKey`（見 README）。
