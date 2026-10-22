# Recommendation Module

> Path: `Docs/modules/recommendation.md`
> Authority: AI 推薦流程、Candidate Set、Google Books fallback、embedding 與 Book AI Profile 生成、AI 搜尋紀錄、每日上限
> Requirements: REC-01～11
> 相關 ADR：ADR-003（OpenAI 只在 C#）
> Data contract: `Docs/data/data-model.md`

## 1. Scope

- 解析自然語言需求、檢索 Candidate Set、Google Books fallback、LLM 排序、保存 Recommendation Search。
- 背景補齊 Book embedding 與 Book AI Profile。
- AI 搜尋紀錄查看、每日使用上限。

不負責：一般搜尋（book-catalog）、Google Books 書目正規化規則（book-catalog §6，本模組呼叫它）。

## 2. Invariants

1. 必須登入（REC-01）；未登入不呼叫任何外部服務。
2. 硬條件只來自使用者**明確提到**的條件；不確定就不加（REC-04）。
3. Candidate Set = 通過硬條件 **且** similarity ≥ T 的 Top-30（REC-05）。
4. 只有 Candidate Set < 5 才呼叫 Google Books（REC-03）。
5. Google Books 的書必須先寫入本地資料庫、有 embedding，並通過同樣的硬條件與門檻，才能成為候選。
6. LLM 只能從 Candidate Set 推薦；不在其中的結果一律丟棄（REC-06）。
7. 每次最多 10 本，可少於 10 本或 0 本。
8. Bestseller 排名不參與任何檢索或排序（REC-08）。
9. LLM 不產生、不執行 SQL；只輸出結構化 filter JSON，由系統翻譯成查詢。
10. 推薦排序只使用 Book 原始 metadata，不讀 Book AI Profile。

## 3. Flow

```mermaid
flowchart TD
    A[需求文字] --> L{已登入且今日 < 20 次?}
    L -->|否| R[401 / 429]
    L -->|是| P[OpenAI: 需求解析]
    P --> Q[硬條件 SQL + 向量 similarity >= T, Top-30]
    Q --> C{Candidate Set >= 5?}
    C -->|是| K[OpenAI: 排序 Candidate Set]
    C -->|否| G[Google Books 查詢]
    G --> N[book-catalog 正規化寫入 + 同步 embedding]
    N --> Q2[重跑檢索]
    Q2 --> Z{Candidate Set = 0?}
    Z -->|否| K
    Z -->|是| S
    K --> V[驗證: 丟棄非候選、去重、最多 10、重編 1..n]
    V --> S[保存 Recommendation Search + Results]
    S --> E[排入 AI Profile 佇列]
    E --> O[回應]
```

## 4. Step 1 — 需求解析

一次 OpenAI chat 呼叫，使用 structured output（JSON schema），輸出：

```json
{
  "filters": {
    "language": "string | null",
    "published_year_from": "int | null",
    "published_year_to": "int | null",
    "page_count_min": "int | null",
    "page_count_max": "int | null",
    "contributor": "string | null",
    "publisher": "string | null"
  },
  "retrieval_text": "用於 embedding 的需求描述",
  "google_queries": ["1～3 組 Google Books 關鍵字"]
}
```

### 4.1 硬條件規則

| Filter | 對應 | 比對 |
|---|---|---|
| `language` | `books.language` | 語言代碼（`data-model.md` §2.1）；`zh` 匹配所有 `zh-*`，`zh-TW` 只精確匹配 |
| `published_year_from/to` | `books.published_date` 的年份 | 範圍（含端點） |
| `page_count_min/max` | `books.page_count` | 範圍（含端點） |
| `contributor` | 任一 `book_contributors.name` | `ILIKE '%v%'` |
| `publisher` | `books.publisher` | `ILIKE '%v%'` |

- 只開放上表 5 類；分類（`book_subjects`）不作為硬條件，交給向量相似度。
- Prompt 必須要求：使用者沒有明確提到的條件一律 `null`；語意模糊時（例：「不要太厚」沒有數字）可轉為範圍，但無法判斷時寫 `null`。
- Prompt 年份規則：「X 年以後／之後／起」與「X 年以前／之前」皆含 X 年（範圍含端點）。
- 系統端再檢查一次：值不合理（年份範圍顛倒、頁數 ≤ 0）時丟棄該條件並記 log，不回錯誤。
- 套用範圍條件時，該欄位為 `NULL` 的 Book 視為不符合。

## 5. Step 2 — 檢索

```text
query_vector = embed(retrieval_text)   # retrieval_text 為空白時改 embed 原始需求文字

SELECT book_id, 1 - (embedding <=> query_vector) AS similarity
FROM book_embeddings JOIN books ...
WHERE <硬條件>
  AND 1 - (embedding <=> query_vector) >= T
ORDER BY embedding <=> query_vector
LIMIT 30
```

- `retrieval_text` 去除頭尾空白後為空時，改以使用者的原始需求文字 embed；不得以空字串呼叫 embedding。
- `T` 預設 0.45，設定 `Recommendation:SimilarityThreshold`（0–1）；依 log 中的 similarity 分布調整（2026-10-21 本機實測：短需求文字對書的前 30 名 similarity 約 0.44～0.57）。
- 沒有 embedding 的 Book 不會被檢索到。
- MVP 使用 exact search，不建 HNSW index（`data-model.md` §5.7）。

## 6. Step 3 — Google Books fallback

只在 Candidate Set < 5 時執行，`fallback_used = true`。

```text
for q in google_queries（1～3 組）:
    Google Books volumes.list(q, maxResults=20, langRestrict=zh)
→ 每筆交給 book-catalog §6 正規化寫入（ISBN 去重）
→ 對新寫入或缺 embedding 的 Book 同步產生 embedding
→ 重跑 Step 2
```

- 重跑後 1～4 本：用這些候選排序。
- 重跑後 0 本：不呼叫排序，保存 0 本結果的 Recommendation Search，回應「找不到符合的書」。
- Google Books 呼叫失敗或逾時：以現有本地候選繼續，記 log；不視為推薦失敗。
- Google Books 寫入的 Book 即使最後沒有被推薦，也保留在本地資料庫。

## 7. Step 4 — 排序

一次 OpenAI chat 呼叫，structured output。

輸入：需求文字 + 每本候選的 metadata（title、subtitle、contributors、publisher、published date、subjects、description 截斷）。description 取前 500 個 Unicode code point（`Recommendation:RankingDescriptionLength`）。候選以 1..n 的短編號提供給 LLM，系統再對應回 `book_id`。

輸出：

```json
[{ "candidate_no": 3, "relevance": 0.82, "reason": "繁體中文推薦理由" }]
```

推薦理由的 prompt 規則（REC-07、BOOK-05）：description 與 table of contents 只供 LLM 判斷，不對使用者顯示。prompt 必須要求以自己的話說明這本書為何符合使用者需求，不得大段引用簡介或目錄原文。

驗證（不重試 LLM）：

1. `candidate_no` 不在 1..n → 丟棄並記 log。
2. `reason` 去除頭尾空白後為空 → 丟棄並記 log（與非法 `candidate_no` 同樣處理，不保存空理由）。
3. 重複的 `candidate_no` → 保留第一次**有效**出現（已丟棄的項目不算）。
4. `relevance` 超出 0–1 → clamp；非數值（NaN）視為 0。
5. 取前 10 筆，依 LLM 回傳順序重新編號為 rank 1..n。
6. LLM 可以因不相關而回傳少於 10 本或 0 本。

## 8. Step 5 — 保存

同一 transaction 寫入 `recommendation_searches` 與 `recommendation_results`（`rank`、`relevance_score`、`reason`）。

- 只有走到這一步才保存；Step 1～4 任一 OpenAI 失敗或整體逾時 → 不保存，回錯誤（REC-09）。
- Google Books fallback 已寫入的 Book 不因推薦失敗而 rollback。

## 9. Book AI Profile

用途：提供推薦結果與紀錄詳情顯示的 `difficulty`（1–5）。

- 觸發：保存 Recommendation Results 後，將其中沒有 profile（或 `source_content_hash` 不符）的 `book_id` 排入 in-process queue（`Channel`）。
- BackgroundService 消化佇列，每本一次 OpenAI 呼叫，輸入只限 Book metadata（`data-model.md` §5.6）。
- `web` 重啟遺失佇列為可接受行為；該書下次出現在推薦結果時重新排入。
- 顯示時即時讀取 `book_ai_profiles.difficulty`；沒有時顯示「—」。difficulty 不寫入 Recommendation Result 快照。
- MVP 只使用 `difficulty`；其他欄位（summary、framework 等）照 schema 產生並保存，但不顯示。

## 10. Embedding 補齊

Embedding model：`text-embedding-3-small`（1536 維）。

Book embedding 輸入文字（`BookEmbeddingText.Build`，`Application/Recommendation/BookEmbeddingText.cs`）：

```text
書名：{Title}
副標題：{Subtitle}
作者：{名字1}、{名字2}
分類：{分類1}、{分類2}
簡介：{Description 前 2000 個 Unicode code point}
```

- 每個欄位一行，標籤後接全形冒號「：」，順序固定，行與行以換行連接。
- 沒有值的欄位整行省略（副標題、作者、分類、簡介皆然）；沒有簡介的 Book 仍產生 embedding。
- 每個值先去除頭尾空白；去除後為空即視為沒有值。
- 作者依 `contributor_order` 排序，只取名字，所有角色（作者、譯者、插畫等）都列入，不去重。
- 分類合併所有來源的 subject，去重後以 ordinal 排序，以「、」串接。
- 簡介以 Unicode code point 截斷，不切斷 surrogate pair；簡介內部的換行保留。
- `source_content_hash` = 上述文字的 UTF-8 bytes 的 SHA-256，64 字元小寫 hex。

| 時機 | 對象 |
|---|---|
| Fallback 流程中（同步） | Google Books 新寫入、或缺 embedding 的 Book |
| BackgroundService，每 10 分鐘 | 沒有 embedding 或 hash 不符的 Book（主要為 crawler 新書），每批上限 100 本 |

找出待補齊的 Book（每輪）：

- 每輪讀取全部 Book 的文字欄位與既有 `source_content_hash`，在 C# 計算新 hash 後比對。hash 只能在 C# 計算，MVP 規模下全量讀取可接受，增長後的做法見 `Docs/TODO.md`。
- 待補齊 = 沒有 `book_embeddings` 列，或既有 hash 與新計算的 hash 不同。
- 沒有 embedding 的排在前面，hash 不同的排在後面；各組內依 `created_at` 由新到舊，相同時以 Id 排序。
- 每輪最多 `Embedding:BatchSize`（預設 100）本。
- `model_name` 不同不觸發重建。更換 model 需新增 migration 並全部重建（`Docs/data/data-model.md` §5.7）。

執行與失敗：

- 每本 Book 呼叫一次 embedding，依序進行，不平行。
- 單本失敗（呼叫或寫入）記 Error log 並繼續下一本；該本留待下一輪重試。
- 連續 5 本失敗後本輪提前結束，之後的 Book 不呼叫 OpenAI。任一本成功即歸零計數。
- 向量維度不是 1536 時記 Warning，仍嘗試寫入；`vector(1536)` 欄位拒絕寫入時視為一次失敗。
- 保留 OpenAI SDK 預設的 retry（對暫時性錯誤退避重試）；只有重試後仍失敗的呼叫才計入連續失敗。
- 停機造成的取消不算失敗，直接結束。

排程與設定：

- 啟動後立即跑一輪，之後每 `Embedding:Interval`（預設 10 分鐘）跑一輪；同一時間最多一輪。
- 一輪中的例外只記 log，不影響網站其他功能（`Docs/architecture/system-architecture.md` §6）。
- 設定：`OPENAIAPI_KEY`（secret，放在環境變數或 user-secrets，不得寫入 repository 內的設定檔；缺少則啟動失敗）、`Embedding:Model`（預設 `text-embedding-3-small`）、`Embedding:Interval`（預設 `00:10:00`）、`Embedding:BatchSize`（預設 100）、`Embedding:BackfillEnabled`（預設 `true`，本機開發可設 `false` 關閉）。
- `Embedding:Interval` ≤ 0、`Embedding:BatchSize` ≤ 0、`Embedding:Model` 空白，都讓啟動失敗。

## 11. 每日上限

- 每位使用者每日（Asia/Taipei 00:00 起算）最多 20 次，數值放設定檔（`Recommendation:DailyLimit`，§13）。
- 計數 = 該使用者當日 `recommendation_searches` 筆數；失敗的推薦不計入。
- 在 Step 1 之前檢查；已達上限 → 429，不呼叫任何外部服務。
- 同時送出多個請求時可能超出 1～2 次，可接受，不加鎖。
- 錯誤回應：429 `/errors/daily-limit-exceeded`，title「今天的 AI 推薦次數已用完」（`api-spec.md` §2）。

## 12. AI 搜尋紀錄

| 功能 | 規則 |
|---|---|
| 列表 | 只列自己的；`created_at` 新到舊；每頁 20 筆；顯示需求文字、時間、結果數 |
| 詳情 | 當時的 rank、Book、reason、relevance（快照）；difficulty 即時讀取 |
| 他人紀錄 | 回 404（不透露存在） |
| 刪除 | MVP 不提供 |

## 13. 逾時與設定

- 整個推薦請求伺服器端逾時 60 秒；逾時視為失敗（不保存）。60 秒是固定值，不開放設定（#15 決定）。
  - 計時從每日上限檢查之後開始，涵蓋需求解析、embedding、檢索、排序與保存；逾時 → 504 `/errors/ai-timeout`，title「AI 推薦逾時」。
  - 使用者自己中斷連線不算逾時，不回應。
- 任一 OpenAI 呼叫（需求解析、需求文字的 embedding、排序）在 SDK 內建重試後仍失敗 → 502 `/errors/ai-unavailable`，title「AI 推薦暫時無法使用」；不保存（§8）。其他伺服器錯誤仍為 500。
- 設定項（`appsettings` / 環境變數）：chat model 名稱、embedding model 名稱、`T`、Top-K（30）、Candidate 下限（5）、結果上限（10）、每日上限（20）、Google Books `maxResults`（20）與 `langRestrict`（zh）。Embedding 補齊的設定見 §10。
- `Recommendation` 區段（`appsettings.json`，啟動時驗證；不合法則啟動失敗）：
  - `Recommendation:ChatModel`：`appsettings.json` 設為 `gpt-6-luna`；程式不提供預設值，未設定或空白則啟動失敗。
  - `Recommendation:SimilarityThreshold`（T）：預設 `0.45`，範圍 0–1。
  - `Recommendation:TopK`：預設 `30`，必須 > 0。
  - `Recommendation:ResultLimit`：預設 `10`，範圍 1–10（`recommendation_results.rank` 上限）。
  - `Recommendation:RankingDescriptionLength`：預設 `500`，必須 > 0；排序 prompt 中 description 的 code point 數（§7）。
  - `Recommendation:DailyLimit`：預設 `20`，必須 > 0；每位使用者每日成功推薦次數上限（§11）。
- Chat model 型號只放設定檔，不寫死在程式。

## 14. Logging

每次推薦記錄：`search_id`（若有）、套用的硬條件、Candidate Set 大小、similarity 最高 / 最低值、是否 fallback、Google Books 寫入數、被丟棄的 `candidate_no`、結果數、各外部呼叫耗時。不記錄 API key。

未成功的推薦各記一行（不記錄需求文字與 API key）：

- 達每日上限：Information，含 user id、當日已用次數、上限。
- OpenAI 失敗（502）：Error，含已花費時間、失敗的步驟名稱，以及 SDK 的原始錯誤。
- 逾時（504）：Warning，含已花費時間與當時執行的步驟名稱。

## 15. Validation

全部使用 fake OpenAI / Google Books adapter，不呼叫真實 API。

1. 未登入、已達上限 → 不呼叫任何 fake adapter。
2. Filter JSON 中 `null` 欄位不產生 SQL 條件；不合理值被丟棄。
3. 通過硬條件但 similarity < T 的 Book 不進入 Candidate Set。
4. Candidate Set ≥ 5 → Google Books fake 未被呼叫。
5. Candidate Set < 5 → 呼叫 Google Books，寫入後重跑檢索；ISBN 命中既有 Book 時不建立 duplicate。
6. Google Books 失敗 → 以本地候選繼續。
7. 排序結果含非候選編號 → 被丟棄；超過 10 筆 → 截斷；重新編號。
8. 0 本候選 → 保存 0 本結果的紀錄，不呼叫排序。
9. 排序 OpenAI 失敗 → 沒有新的 Recommendation Search。
10. 他人紀錄 → 404。
