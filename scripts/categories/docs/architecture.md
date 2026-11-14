# scripts/categories 架構

> 建立：2026-11-14，分類計畫 P2（`782d9e8`～`deb899f`）。計畫與決定：[canonical-category-browse.md](../../../Docs/plans/canonical-category-browse.md)。

## 責任與邊界

`scripts/categories` 是維護 Canonical Category 與 Provider Category Mapping 的**操作工具**（名詞見 [CONTEXT](../../../CONTEXT.md)），不在 web 或 crawler 的 runtime 中執行。

| 擁有 | 不擁有 |
|---|---|
| 版本化規則檔 `config/*.toml` 與誠品第 3 層清單 `config/eslite_level3.tsv` | Schema：由 EF Core migration `AddCanonicalCategories` 負責（[Infrastructure](../../../Infrastructure/docs/architecture.md)）；本工具從不執行 DDL |
| `canonical_categories`、`provider_category_mappings` 的列（UPSERT） | `book_subjects`：由 crawler 寫入，本工具只讀、不改 |
| 覆蓋率盤點（`audit`、`sql/audit-subjects.sql`） | 誠品分類樹的抓取：存檔由使用者取得；本工具不連網 |
| | 分類頁的查詢（計畫 P4，Infrastructure／Application） |

## 模組

| 檔案 | 責任 | 依賴 |
|---|---|---|
| [manage_categories.py](../manage_categories.py) | CLI 入口：`audit`、`init`、`sync`、`verify`、`eslite-import`；結束碼、DSN 遮蔽、連線模式 | 下列全部 |
| [category_config.py](../category_config.py) | 讀取並驗證三個 TOML（slug 格式與唯一、sort_order 唯一、root 指向存在的 slug、誠品 root 為正整數 id、MANUAL 不重複、長度上限）；錯誤丟 `ConfigError`（exit 2） | `tomllib` |
| [eslite_tree.py](../eslite_tree.py) | 分類樹存檔 → 第 3 層清單；TSV 原子寫入與驗證讀取 | 重用 [`crawler/deploy/local/eslite_category_pages.py`](../../../crawler/deploy/local/eslite_category_pages.py) 的 `select()`、預設 top id 與排除清單，不另寫一套走訪規則 |
| [category_mapper.py](../category_mapper.py) | **純函式**：規則 → 期望 Mapping；與 DB 現況比對出 insert／update／unchanged／orphan、AMBIGUOUS、unruled | 無 I/O |
| [category_repository.py](../category_repository.py) | 全部 SQL：schema 檢查、讀取、交易內 UPSERT、audit 統計 | psycopg |

## 對應規則（決定 #1、#6、#7）

- 博客來、金石堂：只對應頂層 Subject，`provider_root_subject` 為頂層本身；書本身帶有頂層名稱，所以足以分類（P0 盤點：博客來 0 本缺頂層）。
- 誠品：`provider_roots.toml` 以第 2 層 id 對應 slug；`eslite_level3.tsv` 展開成第 3 層名稱，`provider_root_subject` 為 `eslite-l2:<id>`。同名第 3 層在不同第 2 層、slug 一致時只寫一筆，不一致時為 AMBIGUOUS。
- `subject_mappings.toml` 的 MANUAL 規則覆蓋推導結果，也能解決 AMBIGUOUS。現有四筆：誠品「繪本／插畫／漫畫」「語言考用」→ `simplified-chinese`（決定 #7）；誠品「宗教」（人文史哲下）、「命理占星／風水」（生活風格下）→ `religion`，與博客來、金石堂的「宗教命理」一致（決定 #8）。
- Mapping 依規則寫入，不論該 Subject 目前是否已出現在 `book_subjects`，所以之後的新書能立即分類。

出貨規則的結果：18 類，Mapping 共 283 筆（博客來 21、金石堂 22、誠品 240；其中 4 筆是 MANUAL：2 筆解決 AMBIGUOUS，2 筆覆蓋推導結果），沒有 AMBIGUOUS 與 unruled。

## 選型與取捨

| 面向 | 選擇 | 理由與代價 |
|---|---|---|
| 規則檔格式 | TOML（`tomllib`） | 不新增 PyYAML 依賴；表達力足以寫 key → slug |
| Schema 管理 | 只驗證（`init`） | 只有一條套用 schema 的途徑（EF migration／CD）；代價是開發者要另外跑 `dotnet ef database update` |
| 誠品走訪 | import crawler 的 `select()` | 與分類頁清單用同一套規則（top id 3、排除 44444、1582）；代價是工具環境需要 crawler 的 runtime 依賴（`curl_cffi` 只被 import，不會被呼叫） |
| 刪除 | 不刪；orphan 只回報 | 避免規則檔誤刪造成分類消失；代價是移除規則後要人工清理（backlog SC-B01） |
| 併發 | `--apply` 在交易內先 `LOCK TABLE ... SHARE ROW EXCLUSIVE`，再讀現況與計算計畫 | 計畫與寫入看到同一份資料；兩個 `--apply` 會序列化 |

## 安全與失敗

- DSN 只從環境變數 `DATABASE_URL` 讀取；不讀 `.env`；輸出前以 `redact()` 移除 DSN、URL 密碼與 `password=` 形式。
- `audit`、`init`、`verify`、`sync --dry-run` 使用 `default_transaction_read_only=on` 的連線。
- 結束碼：0 成功；1 執行失敗或 `verify` 發現 drift；2 用法、設定或 schema 問題（含 `--apply` 遇到 AMBIGUOUS／unruled）。
- `--apply` 任一錯誤整批 rollback；重跑不改變任何列，`updated_at` 也不變（`ON CONFLICT ... DO UPDATE ... WHERE ... IS DISTINCT FROM`）。
- production 的 `sync --apply` 需要使用者明確授權，並且要在 migration 由 CD 套用之後（AGENTS.md §2.3）。

互參：[流程](workflow-diagram.md)、[案例](test-suite.md)、[待辦](backlog.md)、[歷史](update-history.md)。
