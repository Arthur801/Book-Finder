# AGENTS.md

> Repository-wide agent guidance for 「好想找書」.
> Purpose: route agents to the minimum necessary documentation, define safe autonomy, resolve instruction precedence, and match validation effort to change risk.

This file is intentionally a **router and work contract**, not a complete copy of project documentation. Do not preload every document for every task.

---

# 1. 文件路由

## 1.1 Routing 原則

使用 progressive disclosure：先讀與目前任務直接相關的文件，只有在發現跨邊界影響時再讀下一層文件。

不要因為要修改一個局部功能，就預設讀完整 requirements、architecture、database、API、deployment 與 test plan。

Repository-level 文件結構：

```text
AGENTS.md
CONTEXT.md                     ← 領域詞彙表；命名與用語以此為準
Docs/
├── agents/                    ← agent skill 設定（issue tracker、labels、domain docs）
├── requirements/
│   └── product-requirements.md
├── architecture/
│   ├── system-architecture.md
│   └── architecture-decisions.md
├── data/
│   └── data-model.md
├── api/
│   └── api-spec.md
├── modules/
│   ├── identity-auth.md
│   ├── book-catalog.md
│   ├── bestseller.md
│   ├── recommendation.md
│   ├── user-library.md
│   └── crawler.md
├── ui/
│   └── ui-flow.md
├── testing/
│   └── test-plan.md
├── Implementation-Report/   ← agent 實作報告（實作紀錄，非規格；不得作為 authority 引用）
└── deployment/
    └── deployment.md
```

規格未涵蓋的細節依 §2.5 處理，不要自行假造缺少的規格。

## 1.2 依任務類型選讀文件


| Task                                                  | 先讀                                          | 有跨邊界影響時再讀                                        |
| ----------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------- |
| 修改產品行為 / acceptance criteria                    | `Docs/requirements/product-requirements.md`   | 對應 module、API、UI                                      |
| 系統邊界、部署單元、跨模組依賴                        | `Docs/architecture/system-architecture.md`    | `architecture-decisions.md`、deployment                   |
| 新增 / 修改 Entity、欄位、constraint、index、pgvector | `Docs/data/data-model.md`                     | 對應 module、API、migration / test                        |
| 新增 / 修改 JSON endpoint、錯誤格式、request 驗證     | `Docs/api/api-spec.md`                        | 對應 module、UI、data model                               |
| Auth / JWT / current user                             | `Docs/modules/identity-auth.md`               | API、UI、data model、test plan                            |
| 一般搜尋 / Book detail                                | `Docs/modules/book-catalog.md`                | data model、API、recommendation                           |
| Bestseller                                            | `Docs/modules/bestseller.md`                  | crawler、data model、cache rules                          |
| AI 推薦 / pgvector / Google Books / OpenAI            | `Docs/modules/recommendation.md`              | data model、API、book catalog、test plan                  |
| 個人書單 / reading status / rating                    | `Docs/modules/user-library.md`                | auth、data model、API、UI                                 |
| Python crawler                                        | `Docs/modules/crawler.md`                     | bestseller、book catalog、data model、deployment          |
| Razor View / JavaScript / 頁面路由 / 空狀態           | `Docs/ui/ui-flow.md`                          | API、對應 module                                          |
| 單元 / 整合 / 系統測試                                | `Docs/testing/test-plan.md`                   | 被測 module + API / data spec                             |
| Docker / EC2 / RDS / nginx / TLS / secrets / 排程     | `Docs/deployment/deployment.md`               | system architecture、data model                           |
| 領域名詞、命名                                        | `CONTEXT.md`                                  | —                                                         |
| 架構取捨或新增基礎服務                                | `Docs/architecture/architecture-decisions.md` | system architecture + affected specs                      |

## 1.3 Domain-specific routing rules

### AI Recommendation

涉及 AI 推薦時，至少確認下列 invariant：

- 必須登入；每位使用者每日上限 20 次，達上限時不呼叫任何外部服務。
- Local DB 為優先候選來源。
- 硬條件過濾只來自使用者明確提到的條件；不確定就不加。LLM 只輸出結構化 filter，不產生或執行 SQL。
- Candidate Set = 通過硬條件**且** similarity ≥ 門檻的書；不相關的書不得成為候選。
- Candidate Set `< 5` 才允許 Google Books fallback。
- Google Books 結果必須 normalize 並寫入系統資料模型、產生 embedding、通過同樣的過濾與門檻後才能成為 Candidate。
- AI 只能推薦 Candidate Set 中存在的 Book；每次最多 10 本，可為 0 本。
- Bestseller rank 不得直接作為 AI relevance ranking；排序不讀 Book AI Profile。
- 只保存成功的 Recommendation Search。

若修改會破壞任一 invariant，先更新 / 提出規格衝突，不要靜默改行為。

### Crawler

涉及 crawler 時，確認：

- 每日取得博客來中文書 7 日 TOP 100。
- 博客來來源 Book 以商品 URL 判斷是否已存在。
- 既有 Book 不因每日榜單刷新重新抓完整 metadata。
- 排行榜頁必須完整解析 100 筆，否則整次失敗。
- 新書詳細頁最多嘗試 3 次（含第一次）仍失敗則跳過；限制級會員頁直接跳過、不重試、不算錯誤；連續一般錯誤超過 20 本才中止；成功、重用與限制級均重設計數，非連續錯誤無累計上限。
- Bestseller 只保留最新榜單，rank 保留博客來原始排名，被跳過的排名缺號、不重新編號。
- 新榜單尚未成功驗證前，不應先破壞上一份有效榜單。
- Fetcher 預設使用 curl_cffi Chrome fingerprint（使用者於 2026-10-11 核准），循序請求且每次請求含重試的隨機等待目標為 3～30 秒（`Docs/modules/crawler.md` §15）；保留 Playwright 診斷入口。其他 browser stealth、`navigator.webdriver` 修補、CAPTCHA 代解或代理 IP 輪替仍禁止。測試不連線博客來；真實抓取驗證須有當前任務授權。

### Search

一般搜尋只查 Local Database，不使用 embedding 或 LLM。不要因為搜尋結果為空就自動呼叫 Google Books。

### Book 內容顯示

書籍簡介（description）與目錄（table of contents）不論來源都只供 AI 推薦讀取，不得顯示在任何頁面或出現在 API 回應中；書籍完整介紹以外部連結導向來源網站（BOOK-05）。AI 推薦理由不得大段引用簡介或目錄原文。

## 1.4 不要預設讀的文件

除非任務相關，不要為下列動作強迫載入整套文件：

- typo / copy edit；
- 局部 Razor 樣式調整；
- 純 refactor 且外部 contract 不變；
- 單一 pure function 的局部修正；
- 文件格式修正。

---

# 2. Agent 工作契約與自主權規範

## 2.1 工作契約

對一個明確的工程任務，Agent 應：

1. 找到最接近該任務的 authoritative spec。
2. 檢查現有實作與測試，不假設文件一定與程式完全同步。
3. 先維持既有 public contract，除非任務明確要求改 contract。
4. 完成 request 所需的最小完整變更，不只停在第一個可編譯版本。
5. 執行與風險相稱的驗證。
6. 修正由本次變更直接造成的失敗，並重新驗證受影響範圍。
7. 若發現規格、程式與測試互相矛盾，明確指出衝突，不自行挑一個版本當成事實。

## 2.2 可自主執行

在 local / disposable development environment 中，可不逐步請示地：

- 搜尋 repository。
- 編輯與新增實作檔案。
- 新增或更新測試。
- 執行 formatter / linter / build。
- 執行受影響的 unit / integration tests。
- 修正本次修改造成的 test / build failure。
- 產生 migration 檔案並檢查 SQL / schema diff。
- 使用 mock / stub / test container 驗證外部依賴。
- 更新與本次行為變更直接相關的設計文件。

完成條件不是「已修改程式」，而是「需求行為、contract、驗證與必要文件彼此一致」。

## 2.3 必須停下或要求明確授權

除非當前任務已明確授權，不要自主執行：

- 對 production RDS 套用 migration。
- DROP / TRUNCATE / 大量刪除正式資料。
- 旋轉或覆寫 production secrets。
- 建立會持續產生成本的新 AWS service。
- 修改 public API contract 但不更新規格與 caller。
- 修改 authentication / authorization policy 以「先讓功能能跑」。
- 關閉 TLS、憑證驗證、CSRF / authorization 等安全機制來繞過錯誤。
- 將真實 API key、password、JWT、AWS credential 寫入 repository。
- 未經規格支持，讓 LLM 執行任意 SQL 或推薦 Candidate Set 外的 Book。

## 2.4 架構自主權邊界

可以在既定模組內自行重構，但下列變更屬 architecture change：

- 新增微服務。
- 新增 message broker / Redis / vector database 等基礎服務。
- 改變 PostgreSQL 為非主要 source of truth。
- 將 Razor View 改成 SPA framework。
- 改變 Google Books fallback 規則。
- 改變 Auth token model。
- 將 crawler 與 Web schema 各自演化成不相容模型。

Architecture change 應先建立或更新 `Docs/architecture/architecture-decisions.md`，說明 reason、alternatives、trade-offs、migration impact。

## 2.5 對不完整規格的處理

若規格未定義細節：

- 優先沿用既有 codebase pattern。
- 能以局部、可逆、低風險預設完成者，可做最小合理決策並記錄。
- 若選擇會改變產品行為、資料契約、安全性或造成不可逆 migration，停止並指出待決策事項。
- 不把 model knowledge 或「常見做法」冒充成專案既定需求。

---

# 3. 指令優先級

## 3.1 Priority order

當指令衝突時，依序遵循：

1. **Runtime / platform / safety instructions**。
2. **當前使用者或任務的明確指示**。
3. **Repository root `AGENTS.md`**。
4. **已核准的產品與設計文件**。
5. **既有 tests 與 code conventions**。
6. **Agent 自行推論的預設**。

低優先級內容不得靜默覆蓋高優先級要求。

## 3.2 專案文件的 authority

不同文件各自對自己的領域具有主要 authority：


| 領域                                     | Authority                                     |
| ---------------------------------------- | --------------------------------------------- |
| 產品範圍、User Story、功能規則           | `Docs/requirements/product-requirements.md`   |
| 系統拓樸、container、service boundary    | `Docs/architecture/system-architecture.md`    |
| 已決定的架構取捨                         | `Docs/architecture/architecture-decisions.md` |
| Schema、relation、constraint、index      | `Docs/data/data-model.md`                     |
| JSON endpoint、錯誤格式、request 驗證    | `Docs/api/api-spec.md`                        |
| 模組內部責任與 invariants                | 對應`Docs/modules/*.md`                       |
| 頁面路由、導覽、空狀態                   | `Docs/ui/ui-flow.md`                          |
| 測試層級與 coverage expectation          | `Docs/testing/test-plan.md`                   |
| Runtime / AWS / Docker                   | `Docs/deployment/deployment.md`               |
| 領域名詞                                 | `CONTEXT.md`                                  |

## 3.3 文件衝突處理

遇到衝突時：

1. 先判斷是哪個領域的 contract。
2. 以該領域的 authoritative document 為主要依據。
3. 確認其是否違反更高層產品需求或 explicit task。
4. 若衝突無法依 authority 消解，停止擴大修改並回報 conflict。
5. 解決後同步修正過時文件，避免留下兩套 truth。

---

# 4. 與風險匹配的驗證機制

驗證範圍應由 change risk、blast radius 與不可逆性決定。

## 4.1 Risk levels


| Risk           | 常見變更                                                                                          | 最低驗證要求                                                             |
| -------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| L1 — Low      | 文件、文案、CSS、局部 View、不改 contract 的 refactor                                             | syntax / render / targeted check                                         |
| L2 — Medium   | Controller、Application Service、一般搜尋、書單 CRUD、crawler parsing                             | build + affected unit tests + targeted integration test                  |
| L3 — High     | Auth、JWT、DB schema、EF migration、pgvector query、AI Candidate rule、Google Books normalization | build + unit + integration + negative / boundary cases + contract review |
| L4 — Critical | production deployment、destructive migration、secret、network / IAM、正式資料修復                 | staging / dry run + rollback plan + explicit production authorization    |

# 5. Agent skills

## Issue tracker

Issues live in GitHub Issues on `Arthur801/Book-Finder` (via the `gh` CLI). See `Docs/agents/issue-tracker.md`.

## Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `Docs/agents/triage-labels.md`.

## Domain docs

Single-context: root `CONTEXT.md` + ADRs in `Docs/architecture/architecture-decisions.md`. See `Docs/agents/domain.md`.
