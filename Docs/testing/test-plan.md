# Test Plan

> Path: `Docs/testing/test-plan.md`
> Authority: 測試分層、工具、外部依賴處理、各風險等級的最低測試要求
> 各模組的具體驗證項目見該模組文件的 Validation 章節。

## 1. 原則

1. **測試中絕不呼叫真實外部服務**：OpenAI、Google Books、博客來一律以 fake / fixture 取代。
2. 測試絕不連線開發或 production 資料庫；整合測試使用 Testcontainers 拋棄式資料庫。
3. 測試名稱使用 `CONTEXT.md` 的詞彙；可引用需求編號（例：`REC_06_drops_books_outside_candidate_set`）。

## 2. 分層

| 層 | 工具 | 範圍 | 位置 |
|---|---|---|---|
| Unit | xUnit | 純規則：ISBN 判定與正規化、filter JSON → 查詢條件、排序結果驗證、評分 / 狀態驗證、returnUrl 檢查 | `tests/UnitTests` |
| Integration | xUnit + Testcontainers（`pgvector/pgvector:pg17`） | Schema / constraint、Repository、一般搜尋 SQL、向量檢索與門檻、Bestseller 讀取、Library CRUD、Recommendation 全流程（搭配 fake adapter） | `tests/DatabaseIntegration`（已存在）及後續整合測試 project |
| Web | xUnit + `WebApplicationFactory` + Testcontainers | 認證 cookie、antiforgery、401 / 404 / 429、ProblemDetails 格式、PRG 重導；目前已覆蓋首頁、暢銷榜頁與共用版面 | `tests/WebIntegration`（骨架已建立，其餘項目後續補上） |
| Crawler | pytest + 存下來的博客來 HTML fixtures + 拋棄式 PostgreSQL | 排行榜與詳細頁解析、重試 / 跳過 / 上限、Bestseller 替換 transaction | `crawler/tests/` |
| E2E 瀏覽器 | — | MVP 不做 | |

## 3. 外部服務替身

| 服務 | 替身 | 要求 |
|---|---|---|
| OpenAI | 實作 Application 層介面的 fake，回傳預設的解析 / 排序 / embedding / profile 結果 | 可設定回傳非候選編號、超過 10 筆、拋出錯誤、逾時；可斷言是否被呼叫 |
| Google Books | 同上 | 可設定回傳含 / 不含 ISBN 的 volume、拋出錯誤；可斷言是否被呼叫 |
| 博客來 | `crawler/tests/fixtures/*.html` | 至少包含：完整排行榜、不足 100 筆的排行榜、有 / 無目錄與頁數的詳細頁、缺 title 的詳細頁 |

Embedding fake 回傳可控向量（例：固定維度 1536、由測試指定相似度），以驗證門檻邏輯。

## 4. 依風險等級的最低要求

對應 `AGENTS.md` §4.1。

| Risk | 最低測試 |
|---|---|
| L1 | build 通過；改到的頁面可渲染 |
| L2 | build + 受影響模組 unit + 相關 integration |
| L3 | 上述 + 負面 / 邊界案例（見各模組 Validation）+ contract 對照（`data-model.md` / `api-spec.md`） |
| L4 | 上述 + staging / dry run + rollback 計畫（見 `deployment.md`） |

## 5. 必須永遠成立的測試（regression guard）

| 規則 | 測試 |
|---|---|
| SEARCH-01 | 一般搜尋查無結果時 Google Books fake 未被呼叫 |
| REC-01 | 未登入時所有外部 fake 未被呼叫 |
| REC-03 | Candidate Set ≥ 5 時 Google Books fake 未被呼叫 |
| REC-06 | 排序結果不含 Candidate Set 外的 Book，且 ≤ 10 |
| REC-11 | 達上限時所有外部 fake 未被呼叫 |
| CRAWL-05 | 連續一般錯誤 20 本仍繼續、21 本立即中止且 Bestseller／既有 last_seen_at 不變；交錯 50 本錯誤仍更新。成功、重用與限制級重設計數；每本重試只計一次最終錯誤 |
| data-model §10 | constraint 測試（`tests/DatabaseIntegration/constraints.sql`） |

## 6. 執行

```text
dotnet test                 # 需本機 Docker（Testcontainers）
cd crawler && pytest
```

MVP 無 CI；PR 前於本機執行。CI/CD 為延後項目。
