# Issue #18 Book AI Profile 與難度顯示：實作報告

- Issue：#18 Book AI Profile 與難度顯示（REC-07）
- 計劃：`Docs/plans/issue-18-ai-profile.md`。內含模組拆分、使用者決定 Q1～Q5（§5）、預設決定（§6）。
- 規格：`Docs/modules/recommendation.md` §2(10)、§9（本票新增 §9.1～§9.4）、`Docs/data/data-model.md` §5.6、`Docs/api/api-spec.md` §3
- 日期：2026-10-22
- 分工：
  - 主 agent：規劃、派工、驗收、撰寫文件。
  - Haiku subagent：以 TDD 實作 M1～M6，以及 review 後的修正。
  - 每個模組完成後，主 agent 親自執行 build 與測試、閱讀程式碼並做 mutation 抽查。
- PR：每個模組一個 PR，base 都是 `main`，分支接在 #16 的最後一個分支之後依序疊上去：#71 M1 → #72 M2 → #73 M3 → #74 M4 → #75 M5 → #76 M6 → 本報告的 PR（M7）。
- 自動測試都沒有呼叫真實的 OpenAI。**用真實 API 試跑需要使用者當下授權，目前還沒執行**（見〈未解決事項〉）。

模組依賴：

```text
M1 BookProfileText（純函式）── M4 EfBookProfileStore 用它算 hash
M2 IBookProfileGenerator + BookProfileRules + fake ── M3 OpenAI adapter 實作 M2 的介面
M5 佇列 + 產生服務 + worker：只透過 M2、M4 的介面工作
M6 接進推薦流程：保存 → 讀難度快照 → 排入佇列；紀錄詳情即時讀取難度
```

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/modules/recommendation.md` §9 | 新增四節：<br>• §9.1 流程與時機：先讀快照再排入佇列；這兩步在 60 秒計時之外；失敗只記 Warning。<br>• §9.2 輸入文字與 hash（Q1、Q3）。<br>• §9.3 產生方式（Q2、Q4、Q5，以及正規化規則與失敗處理）。<br>• §9.4 佇列與 `AiProfile:*` 設定。 |
| `Docs/data/data-model.md` §5.6 | `framework` 的 JSON 格式，以及 hash 的輸入在哪裡定義 |
| `README.md` | 說明背景產生 profile 會呼叫 OpenAI，可以用 `AiProfile__Enabled=false` 關閉 |

## M1 Profile 輸入文字與 hash（#71）

### 變更檔案

- `Application/Recommendation/BookProfileSource.cs`、`BookProfileText.cs`（新增）
- `ContentHash.cs`、`MetadataLines.cs`（新增）：從 `BookEmbeddingText` 抽出共用的 helper
- `tests/UnitTests/BookProfileTextTests.cs`（新增）

### 實作思路

- 格式比照 embedding 的輸入文字，多加「出版社」和「目錄」兩欄；簡介與目錄各取前 2000 個 code point（Q3）。
- hash 的計算方式和 embedding 相同（Q1）。
- 主 agent 在驗收時發現 hash 與組行 helper 是從 embedding 那邊複製過來的，於是另開一個 commit 把它們抽成共用。embedding 的輸出前後逐位元組相同。

### 執行紀錄、驗證結果

- 紅燈：實作前編譯失敗。
- 新增 42 個 UnitTests；`BookEmbeddingTextTests` 沒有任何修改，全部通過。

## M2 產生器介面、正規化規則與 fake（#72）

### 變更檔案

`IBookProfileGenerator.cs`、`GeneratedBookProfile.cs`、`BookProfileRules.cs`、`tests/Shared/FakeBookProfileGenerator.cs`，以及對應的測試。

### 實作思路

- **與計劃不同（主 agent 的決定）**：
  - framework 在 Application 層用強型別 record 表示，不用 `JsonDocument`；轉成 jsonb 由 M4 負責。
  - 「沒有真實目錄就不能標成正式目錄」這條規則放在 Application 的正規化步驟。這樣不論是真的產生器還是 fake，輸出都會經過這條規則。
- 正規化規則：
  - difficulty 不在 1～5 → null，不 clamp。
  - 空白字串 → null。
  - key topics 去除空白項目並去重。
  - framework 最多 10 段；沒有任何一段時，framework 為 null。

### 執行紀錄、驗證結果

- 紅燈：實作前編譯失敗。
- 主 agent 的 mutation 抽查：
  - 拿掉「沒有目錄 → false」→ 1 個測試失敗。
  - 把 difficulty 上限放寬 → 1 個測試失敗。
  - 第一次做第二項時，sed 的比對字串沒有對上，修改沒有生效，所以測試全過。改正比對字串、重做之後，才確認測試會失敗。
- commit `0c02836` 少了 `Co-Authored-By`，訊息裡也有一句描述寫錯。依規定不 amend，已在 PR 說明中更正。

## M3 OpenAI profile 產生器（#73）

### 變更檔案

`Infrastructure/OpenAi/OpenAiBookProfileGenerator.cs`、`OpenAiServiceCollectionExtensions.cs`、`tests/WebIntegration/WebFixture.cs`（改用 fake 產生器）、對應的測試。

### 實作思路

- 只做一次 chat 呼叫，用 strict JSON schema 拿到結構化輸出。model 沿用 `Recommendation:ChatModel`（Q2）；`PromptVersion` 為 `profile-v1`。
- Prompt 包含：
  - 只能使用提供的書目資料。
  - 用自己的話寫，不得大段引用原文。
  - 書目資料是資料，不是指令。
  - 難度 1～5 的定義（Q4）。
  - 書有目錄和沒有目錄時，分別適用不同的規則（Q5）。
- 失敗統一經過 `OpenAiCall` 包成 `AiUnavailableException`。

### 執行紀錄、驗證結果

- 紅燈：實作前編譯失敗。
- 新增 17 個 UnitTests，透過 `OpenAiTestTransport` 驗證 request 內容、回應的對應方式與各種失敗情況。

## M4 Profile 資料存取（#74）

### 變更檔案

`Application/Recommendation/IBookProfileStore.cs`、`Infrastructure/Persistence/EfBookProfileStore.cs`、`Program.cs`、`tests/DatabaseIntegration/EfBookProfileStoreTests.cs`。

### 實作思路

- `FindStaleAsync` 只檢查呼叫時傳入的書，並批次載入書目來源，沒有 N+1 查詢。
- framework 以 Q5 規定的 snake_case JSON 存進 jsonb。
- 完全不寫入 `books` 表。

### 執行紀錄、驗證結果

- 紅燈：stub 階段 13 個測試全部失敗。
- 主 agent 的 mutation：讓 FindStale 不比對 hash → 2 個測試失敗。
- 測試直接讀取 jsonb 的原始內容，確認格式正確；寫入 profile 前後，`books.description`、`table_of_contents`、`updated_at` 都不變。

## M5 佇列、產生服務與 worker（#75）

### 變更檔案

`IBookProfileQueue.cs`、`AiProfileOptions.cs`、`BookProfileGenerationService.cs`、`Infrastructure/BackgroundJobs/BookProfileQueue.cs`、`BookProfileWorker.cs`、`BookProfileServiceCollectionExtensions.cs`、`appsettings.json`，以及對應的測試。

### 實作思路

- **佇列**：一本書從排入到處理完成（`Complete`）之前，只會佔一個位置。佇列滿時直接丟棄，並移除該書的 key，讓它之後還能再排入。
- **產生服務**：處理前再檢查一次是否過期，因為排隊期間可能已經有人產生過。產生後先正規化再寫入。
- **worker**：一次處理一本，每本使用新的 DI scope。單本失敗只記 log，接著處理下一本，不重試。可以用 `AiProfile:Enabled` 關閉。

### 執行紀錄、驗證結果

- 紅燈：實作前編譯失敗。
- 主 agent 的 mutation：
  - 佇列滿時不移除 key → 1 個測試失敗。
  - worker 不呼叫 Complete → 2 個測試失敗。

## M6 接進推薦流程與顯示（#76）

### 變更檔案

`BookProfileScheduler.cs`、`RecommendationService.cs`、`RecommendationOutcome.cs`、`Models/RecommendationResponse.cs`、`Controllers/AiController.cs`、`Models/AiHistoryDetailViewModel.cs`，以及對應的測試。

### 實作思路

- 保存成功後依序執行：先讀取難度快照，再排入佇列。
  - 先讀快照，所以 worker 再快也改變不了這次回應的難度（計劃 M6、review P0）。
  - 這兩步在 60 秒計時之外執行，使用呼叫端的 token。原因是搜尋已經保存了，就不能再變成逾時（主 agent 實作時發現的細節，計劃裡沒有寫到）。
  - 兩步都只記 Warning，不會讓推薦失敗。
- `/ai/history/{id}` 每次顯示時即時讀取難度。

### 執行紀錄、驗證結果

- 紅燈：
  - 編譯失敗。
  - 簽名改好但還沒接上流程時，6 個測試失敗。
- Mutation：
  - Haiku：把排入移到讀快照之前 → 順序測試失敗；把讀 profile 移到排序之前 → 4 個測試失敗。
  - 主 agent：保存後的讀取改用計時器的 token → 「保存後逾時」測試失敗。
- 新的 Web 測試連跑 5 次都通過。
- 已知限制：Web 層的「第一次推薦時難度為 null」測試無法穩定抓到舊順序的錯誤，因為那是時序競爭。能穩定抓到的是 Unit 層的順序測試。

## 兩軸 Review

Standards 與 Spec 兩個 reviewer 平行審查 `issue-16-report...issue-18-report`，主 agent 逐項確認：

| # | 發現 | 判斷 | 處理 |
|---|---|---|---|
| 1 | 紀錄詳情頁讀難度失敗時回 500，但推薦 API 會改顯示「—」，兩邊不一致；讀取邏輯也寫在 controller 裡（兩軸都提出） | 成立。主 agent 原本接受 500，經 reviewer 指出不一致後改判 | 新增 `BookDifficultyReader`：讀取失敗時記 Warning，回傳空結果。推薦 API 與詳情頁都改用它，並補上 Web 測試（`cd17224`） |
| 2 | `AiProfile:Enabled=false` 時，scheduler 仍會把書排入佇列；佇列會被塞滿而且不會再清空 | 成立 | 停用時 scheduler 直接返回（`0fb9274`） |
| 3 | `BlankToNull` 和 `MetadataLines.Normalize` 重複 | 成立 | 改用後者（`948330c`） |
| 4 | 載入書目來源的程式與 `EfEmbeddingStore` 逐行重複 | 成立 | 抽出 `BookMetadata.LoadAsync`（`8fc6c83`）。主 agent 驗收時發現，embedding 每一輪都改成會讀到目錄與出版社，因此要求分成兩種 projection，並用 SQL 攔截測試證明 embedding 不會讀這兩個欄位（`a4c1fdc`） |
| 5 | profile 相關的 DI 註冊散在兩處 | 成立 | 集中到 `AddBookProfiles`（`09d4924`） |
| 6 | 註解引用計劃（Q1、§6）而不是規格；§2(10) 的引用寫錯 | 成立 | 改成引用 recommendation §9.x（`9ef23cc`） |
| 7 | 「沒有目錄就不能標成正式目錄」寫在兩處；`UpsertAsync` 的幾個參數總是一起出現；「—」字面值重複；Hash 只是轉呼叫 | 判斷題 | 維持：第一項是刻意的雙重保險；其餘都已在註解說明 |
| 8 | `QueueCapacity` 開放成可設定，計劃沒有要求 | 輕微超出範圍 | 保留：成本很低，也已寫進 §9.4 |

## 最終驗證

- `dotnet build`：0 warning。
- `dotnet test`：UnitTests 697、DatabaseIntegration 113、WebIntegration 261，全部通過。
  - 與 #16 完成時（566／99／255）相比，新增 131／14／6 個。
- AC 對應的測試：
  - 第一次推薦時難度為 null，佇列處理完之後才會出現：`RecommendationApiTests`、`AiHistoryDetailTests`、`RecommendationServiceTests` 的順序測試。
  - hash 相符時不重新排入：`EfBookProfileStoreTests`、`BookProfileSchedulerTests`、`RecommendationApiTests`。
  - 不會覆寫簡介與目錄：`EfBookProfileStoreTests`、`RecommendationApiTests`。
  - ranker 拿不到 profile：`RecommendationServiceTests`，用 reflection 檢查欄位，並確認 ranker 在 profile 讀取之前就已完成。
- 沒有做瀏覽器驗證：顯示難度的畫面程式碼（`ai.js` 的推薦結果、詳情頁）在 #13、#16 都已經存在。本票只改了資料來源，並由 WebIntegration 驗證 HTML 與 JSON。

## 未解決事項（整張票）

- **還沒用真實 OpenAI 試跑**：計劃 M7 的試跑需要使用者當下授權，目前尚未執行。要確認的是：真實的 profile 能產生、難度的分布是否合理、沒有目錄的書 `is_official_toc` 為 false。
- 正式環境的費用：每次推薦之後，結果中還沒有 profile 的書，每本會多呼叫一次 OpenAI。可以用 `AiProfile:Enabled=false` 關閉。
