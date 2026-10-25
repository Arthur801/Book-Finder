# AGENTS.md

> Repository-wide agent guidance for 「好想找書」.  
> Purpose: route agents to the minimum necessary documentation, define safe autonomy, resolve instruction precedence, and match validation effort to change risk.

This file is intentionally a **router and work contract**, not a complete copy of project documentation. Do not preload every document for every task.

---

# 1. 文件路由

## 1.1 Routing 原則

使用 progressive disclosure：

1. 先定位目前任務實際影響的 code-owning module。
2. 優先讀取該 module 的 local `docs/`。
3. 只有發現跨 module contract、dependency 或 runtime responsibility 時，才擴大到其他 module。
4. 不因局部修改預設載入整個 repository 的所有文件。

每個 module 的 active documentation 使用固定五文件模型：

```text
<module>/
└── docs/
    ├── architecture.md
    ├── workflow-diagram.md
    ├── test-suite.md
    ├── backlog.md
    └── update-history.md
```

五份文件用途如下：

| 文件 | 用途 |
|---|---|
| `architecture.md` | current architecture、module boundary、responsibility、dependency、runtime ownership、主要設計取捨 |
| `workflow-diagram.md` | current use case、control flow、data flow、integration flow、caller / callee responsibility |
| `test-suite.md` | 測試案例、validation strategy、coverage expectation、已知驗證缺口 |
| `backlog.md` | 已知缺口、planned work、deferred work、待決策事項 |
| `update-history.md` | 歷史修改、查核基準、commit / regression context |

Repository-level 文件角色：

```text
/
├── AGENTS.md
├── CONTEXT.md
├── <module>/
│   └── docs/
│       ├── architecture.md
│       ├── workflow-diagram.md
│       ├── test-suite.md
│       ├── backlog.md
│       └── update-history.md
└── Docs/
    ├── agents/
    ├── requirements/
    ├── architecture/
    ├── data/
    ├── api/
    ├── modules/
    ├── ui/
    ├── testing/
    ├── deployment/
    └── Implementation-Report/
```

角色定義：

- `AGENTS.md`
  - repository-wide routing；
  - agent work contract；
  - instruction precedence；
  - authority 規則；
  - validation / safety boundary。

- `CONTEXT.md`
  - repository-wide domain glossary；
  - domain terminology 與 naming authority。

- `<module>/docs/*`
  - **Active Technical Documentation**；
  - Agent 日常分析、規劃、實作與驗證的主要文件來源。

- `Docs/agents/*`
  - agent workflow、skill、issue tracker、triage 等設定；
  - 不構成產品或技術 contract。

- `Docs/` 中既有 requirements、architecture、data、api、modules、ui、testing、deployment 等文件
  - **Archived Reference**；
  - 保存舊規格、歷史設計背景與 traceability；
  - 不再作為 current technical authority；
  - Agent 平常不得預設讀取。

- `Docs/Implementation-Report/*`
  - implementation record；
  - 不具 authority。

只有以下情況才讀取 archived `Docs/` technical documents：

- 任務明確要求查歷史規格；
- 需要理解 legacy design rationale；
- 需要追查某項 current behavior 的歷史來源；
- module-local active docs 明確缺少必要背景。

引用 archived 文件時，必須明確把資訊標示為 historical / reference context，不得直接當作 current requirement。

規格未涵蓋的細節依 §2.5 處理，不要自行假造缺少的規格。

## 1.2 依任務類型選讀文件

| Task | 先讀 | 有跨邊界影響時再讀 |
|---|---|---|
| 理解或修改 module boundary、layer、dependency、runtime ownership | `<module>/docs/architecture.md` | 其他受影響 module 的 `architecture.md` |
| 修改 use case、功能流程、資料流、integration flow | `<module>/docs/workflow-diagram.md` | 同 module `architecture.md`、其他受影響 module 的 `workflow-diagram.md` |
| 新增或修改測試、validation strategy、coverage | `<module>/docs/test-suite.md` | `workflow-diagram.md`、`architecture.md` |
| 判斷已知缺口、未完成工作、planned change | `<module>/docs/backlog.md` | `architecture.md`、`workflow-diagram.md` |
| Regression、歷史修改、實作來源追查 | `<module>/docs/update-history.md` | Git history、current `architecture.md` / `workflow-diagram.md` |
| Cross-module contract | 所有受影響 module 的相關 active docs | implementation、tests |
| Entity / schema / persistence behavior | owning module 的 `architecture.md`、`workflow-diagram.md` | persistence consumer modules、tests |
| API / Controller / View contract | owning module 的 active docs | caller / callee module docs、tests |
| Auth / authorization | owning module 的 active docs | 所有依賴 identity contract 的 modules |
| AI / Recommendation / embedding / external provider | owning module 的 active docs | Catalog / persistence / Web 等實際受影響 modules |
| Crawler / ingestion | crawler owning module 的 active docs | Catalog / persistence / deployment owning modules |
| Deployment / runtime / infrastructure | owning module 的 active docs | 所有受部署變更影響 modules |
| 領域名詞、命名 | `CONTEXT.md` | — |
| Agent workflow / issue tracker / triage | `Docs/agents/*` | `AGENTS.md` |
| 舊規格、舊設計理由、歷史追溯 | 對應 archived `Docs/*` | current module docs，用來確認現在是否仍成立 |

選讀原則：

- `architecture.md` 與 `workflow-diagram.md` 用來理解 **current state**。
- `test-suite.md` 用來理解應如何驗證 current behavior。
- `backlog.md` 用來理解 **尚未完成或預計改變的 state**。
- `update-history.md` 用來理解 **historical state**。

不得把 `backlog.md` 中 planned behavior 誤認成已存在行為。

不得把 `update-history.md` 中過去行為誤認成目前 contract。

## 1.3 不要預設讀的文件

除非任務確實需要，不要為下列工作強迫載入整套 documentation：

- typo / copy edit；
- 局部 Razor / CSS 樣式調整；
- pure refactor 且 public contract 不變；
- 單一 pure function 的局部修正；
- 文件格式修正；
- 不影響其他 module contract 的局部 implementation detail。

即使是小修改，若調查過程發現：

- public contract 改變；
- cross-module dependency 改變；
- schema / persistence semantics 改變；
- security boundary 改變；
- runtime responsibility 改變；

則應升級文件閱讀範圍。

---

# 2. Agent 工作契約與自主權規範

## 2.1 工作契約

對一個明確的工程任務，Agent 應：

1. 找到實際 owning module。
2. 找到與任務最接近的 module-local active documentation。
3. 檢查現有 implementation 與 tests，不假設文件一定完全同步。
4. 先維持既有 public contract，除非任務明確要求修改。
5. 完成 request 所需的最小完整變更，不停在第一個可編譯版本。
6. 執行與 change risk 相稱的驗證。
7. 修正由本次變更直接造成的 failure，再重新驗證。
8. 更新因本次 change 而失真的 module-local active docs。
9. 若 active docs、implementation 與 tests 互相矛盾，明確指出 conflict，不自行挑一個版本當成事實。

完成條件不是：

> 程式已經修改。

完成條件是：

> implementation、current contract、validation evidence 與必要的 active documentation 對同一個 change 保持一致。

## 2.2 可自主執行

在 local / disposable development environment 中，可不逐步請示地：

- 搜尋 repository；
- 閱讀 source、tests、module-local docs；
- 編輯與新增 implementation；
- 新增或更新 tests；
- 執行 formatter / linter / build；
- 執行受影響的 unit tests；
- 執行 disposable integration tests；
- 修正本次修改造成的 build / test failure；
- 產生 migration 並檢查 schema diff；
- 使用 mock / stub / fake / test container 驗證外部依賴；
- 更新與本次 behavior change 直接相關的 module-local docs。

## 2.3 必須停下或要求明確授權

除非當前任務已明確授權，不要自主執行：

- 對 production database 套用 migration；
- DROP / TRUNCATE / 大量刪除正式資料；
- 旋轉或覆寫 production secrets；
- 建立會持續產生成本的新 cloud service；
- 修改 public API contract 卻不處理 caller；
- 降低 authentication / authorization policy；
- 關閉 TLS、certificate validation、CSRF、authorization 等安全機制；
- 將真實 API key、password、JWT、cloud credential 寫入 repository；
- 未經 active contract 支持，讓 LLM 執行任意 SQL；
- 對正式外部服務進行 destructive / high-volume operation；
- 將 archived `Docs/` 中的舊需求直接恢復成 current behavior。

## 2.4 架構自主權邊界

可以在既定 module boundary 內自行重構。

下列變更視為 architecture change：

- 新增 service / deployment unit；
- 新增 message broker、Redis、額外 database 等基礎服務；
- 改變主要 source of truth；
- 改變 frontend architecture；
- 改變 cross-module ownership；
- 改變 authentication model；
- 改變 external provider fallback policy；
- 改變 transaction / consistency boundary；
- 讓原本共享的資料模型分裂成互不相容模型。

Architecture change 至少應更新所有受影響 module 的：

```text
docs/architecture.md
```

若同時改變：

- use case / data flow  
  → 更新 `workflow-diagram.md`

- validation contract  
  → 更新 `test-suite.md`

- planned / deferred work  
  → 更新 `backlog.md`

- 需要保留實作歷史  
  → 更新 `update-history.md`

新的 current architecture decision 不應只寫入 archived root `Docs/` technical specs。

## 2.5 對不完整規格的處理

若 active documentation 未定義某個細節：

- 優先沿用現有 codebase pattern；
- 優先選擇局部、可逆、低風險方案；
- 記錄必要假設；
- 不把 model knowledge 或「業界通常如此」冒充成 project requirement。

若該決策會改變：

- user-visible product behavior；
- public API；
- persisted data contract；
- authentication / authorization；
- security property；
- irreversible migration；
- cross-module ownership；

則不要自行補規格。

應停止擴大 implementation，明確列出待決策事項。

Archived `Docs/` 可用來了解過去如何定義，但不能自動補成新的 current requirement。

---

# 3. 指令優先級

## 3.1 Priority order

當指令或證據互相衝突時，依序遵循：

1. **Runtime / platform / safety instructions**
2. **當前使用者或任務的明確指示**
3. **Repository root `AGENTS.md`**
4. **受影響 module 的 active documentation 與 `CONTEXT.md`**
5. **Existing implementation 與 tests 作為 implementation evidence**
6. **Archived root `Docs/` technical documents 與其他 historical material**
7. **Agent 自行推論的預設**

低優先級內容不得靜默覆蓋高優先級要求。

Implementation 與 tests 可以證明：

> 系統目前實際做了什麼。

它們本身不會自動證明：

> 系統應該這樣做。

若 implementation evidence 與 active documentation 不一致，視為 drift / conflict 進一步查明。

## 3.2 專案文件 Authority

Current technical authority 以 **code-owning module 的 local `docs/`** 為基本單位。

Root `Docs/` 中原有 technical specifications 不再作為 current technical authority。

### Authority Matrix

| 資訊類型 | Authority |
|---|---|
| Repository-wide routing、instruction precedence、agent autonomy / safety | root `AGENTS.md` |
| Domain terminology、canonical naming | `CONTEXT.md` |
| Module boundary、layer responsibility、dependency、runtime ownership、current architecture decision | `<module>/docs/architecture.md` |
| Current use case、control flow、data flow、integration flow、責任交界 | `<module>/docs/workflow-diagram.md` |
| Test scenarios、validation strategy、coverage expectation、known validation gaps | `<module>/docs/test-suite.md` |
| Known gaps、planned work、deferred work、待決策事項 | `<module>/docs/backlog.md` |
| Historical implementation、audit baseline、commit / regression context | `<module>/docs/update-history.md` |
| Agent workflow / issue tracker / triage / skill configuration | `Docs/agents/*` |
| Root `Docs/` 中 requirements / architecture / data / api / modules / ui / testing / deployment 等舊技術文件 | **Archived Reference only** |
| `Docs/Implementation-Report/*` | Implementation record only；不是 authority |

### Authority 語意

#### `architecture.md`

描述目前：

- module responsibility；
- dependency direction；
- runtime ownership；
- technical boundary；
- 主要 architecture choices。

它回答：

> 系統現在是如何切分與運作的？

#### `workflow-diagram.md`

描述目前：

- entry point；
- use case orchestration；
- control flow；
- data flow；
- caller / callee；
- failure / outcome flow；
- integration boundary。

它回答：

> 現在這個流程實際應如何運作？

#### `test-suite.md`

描述：

- 應驗證的 behavior；
- boundary / negative cases；
- verification strategy；
- known test gaps。

它不能單獨證明測試已通過。

是否實際存在 test implementation，需檢查 repository source。

是否實際通過，需依本次 test execution evidence 判定。

#### `backlog.md`

只對以下資訊具有 authority：

- known gap；
- unfinished work；
- planned change；
- deferred work；
- pending decision。

`backlog.md` 描述 future / incomplete state。

其中內容不得被當成 current implementation contract。

#### `update-history.md`

只負責：

- historical evidence；
- audit baseline；
- implementation chronology；
- regression context；
- commit / change traceability。

它不能覆蓋 current `architecture.md` 或 `workflow-diagram.md`。

### Module Ownership

`<module>` 指：

> 實際擁有受影響 code、data、runtime responsibility 或 public contract，且具有 local `docs/` 的 code-owning area。

一個 task 可以同時涉及多個 owning modules。

Cross-module change 時：

1. 找出所有 owning modules。
2. 讀取各 module 與該 change 相關的 active docs。
3. 不得讓某一 module 的文件單方面定義另一 module 的 contract。
4. 明確確認 dependency direction 與 responsibility boundary。

### Archived `Docs/` 的地位

Root `Docs/` 中既有 technical specs 現在是：

> Archived Reference.

用途包括：

- 理解舊需求；
- 理解 legacy architecture；
- 追查設計原因；
- comparison；
- migration context；
- historical traceability。

Archived 文件：

- 不應成為 Agent 平常的預設閱讀文件；
- 不得覆蓋 module-local active documentation；
- 不得因為內容較完整就自動取得較高 authority；
- 不得單獨作為新增 current behavior 的依據。

若 archived spec 與 active docs 衝突：

> Active module-local docs 優先。

### Legacy Authority Links

Module-local docs 目前可能仍存在類似：

```text
../../Docs/requirements/*
../../Docs/architecture/*
../../Docs/data/*
../../Docs/api/*
../../Docs/modules/*
../../Docs/testing/*
../../Docs/deployment/*
```

的連結，甚至將這些文件標為：

```text
Authority
spec
requirement
```

自本規則生效後，這些既有連結一律視為：

> **Legacy reference links**

它們的存在不會使 archived root `Docs/` 恢復 current authority。

若 module-local active doc 本身仍依賴其中某項規則，Agent 應：

1. 把 archived 文件當成歷史背景讀取；
2. 檢查 implementation / tests；
3. 判斷 active doc 是否需要把該規則正式吸收進 module-local documentation；
4. 不要僅因 legacy link 存在就把 archived document 當 current source of truth。

### Implementation Evidence

Existing code 與 tests 是重要證據，但屬於：

> implementation evidence

而不是獨立的 project authority。

若發現：

```text
active docs != code
```

或：

```text
active docs != tests
```

不要靜默選擇其中一個。

應先判斷：

- 文件過時；
- implementation drift；
- test drift；
- incomplete migration；
- known backlog；
- 尚未完成的 architecture change。

再決定本次 task 是否應修正。

## 3.3 文件衝突處理

遇到 conflict 時：

1. 找出實際 owning module。
2. 若跨 module，列出所有受影響 modules。
3. 判斷 conflict 屬於：
   - architecture；
   - workflow；
   - validation；
   - backlog；
   - history；
   - terminology。
4. 依 §3.2 找到對應 active authority。
5. 對照 implementation 與 tests 找出實際 drift。
6. Archived root `Docs/` 僅用來提供 historical context。
7. 確認 active documentation 是否違反：
   - explicit task；
   - root `AGENTS.md`；
   - runtime / platform / safety instruction。
8. 若 cross-module active docs 本身互相矛盾，而且沒有足夠 authority 可以消解，不要擴大 implementation。
9. 明確回報 conflict 與待決策事項。
10. conflict 解決後，同步修正受影響 module 的 active docs，避免 repository 中同時存在兩套 current truth。

Archived 文件原則上可保留不動，以維持 historical traceability。

---

# 4. 與風險匹配的驗證機制

驗證範圍應由：

- change risk；
- blast radius；
- reversibility；
- security impact；
- data impact；

共同決定。

## 4.1 Risk levels

| Risk | 常見變更 | 最低驗證要求 |
|---|---|---|
| L1 — Low | 文件、文案、CSS、局部 View、不改 contract 的 refactor | syntax / render / targeted check |
| L2 — Medium | Controller、Application Service、一般 CRUD、一般 parsing | build + affected unit tests + targeted integration test |
| L3 — High | Auth、DB schema、migration、vector query、AI candidate rule、external-provider normalization、transaction semantics | build + unit + integration + negative / boundary cases + contract review |
| L4 — Critical | production deployment、destructive migration、secret、network / IAM、正式資料修復 | staging / dry run + rollback plan + explicit production authorization |

風險層級是最低要求。

若變更跨越多個 module，validation scope 應依 blast radius 擴大。

---

# 5. Agent skills

## Issue tracker

Issues live in GitHub Issues on `Arthur801/Book-Finder`.

See:

```text
Docs/agents/issue-tracker.md
```

`Docs/agents/issue-tracker.md` 定義 Agent 如何操作 issue workflow，不定義產品或技術 contract。

## Triage labels

Default triage vocabulary：

```text
needs-triage
needs-info
ready-for-agent
ready-for-human
wontfix
```

See:

```text
Docs/agents/triage-labels.md
```

## Domain docs

技術工作使用：

```text
CONTEXT.md
+
affected <module>/docs/*
```

作為主要 domain / technical context。

`Docs/agents/domain.md` 若仍包含指向 archived `Docs/*` technical specifications 的舊 routing 或 authority 描述，視為 agent configuration 中的 legacy guidance。

其 technical authority 一律受本文件 §1 與 §3.2 約束。
