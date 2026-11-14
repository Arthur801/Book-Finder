# scripts/categories — Canonical Category 維護工具

計畫：[Docs/plans/canonical-category-browse.md](../../Docs/plans/canonical-category-browse.md)。

維護 Canonical Category 與 Provider Category Mapping 的操作工具。設計與取捨見 [docs/architecture.md](docs/architecture.md)，流程見 [docs/workflow-diagram.md](docs/workflow-diagram.md)。

## manage_categories.py

在 repo 根目錄執行；資料庫指令需要環境變數 `DATABASE_URL`（不會被印出）。所有指令都接受 `--config-dir`（預設 `scripts/categories/config`）。

```bash
python scripts/categories/manage_categories.py init              # 只檢查 schema；不執行 DDL
python scripts/categories/manage_categories.py sync               # 預設 dry-run：列出新增、更新、orphan、AMBIGUOUS
python scripts/categories/manage_categories.py sync --apply       # 單一交易寫入；重跑寫入 0 列
python scripts/categories/manage_categories.py verify             # DB 與規則不一致時 exit 1
python scripts/categories/manage_categories.py audit [--unmapped-csv out.csv]
python scripts/categories/manage_categories.py eslite-import --tree ~/eslite-category-tree.json   # 不連 DB、不連網
```

- 結束碼：0 成功；1 執行失敗或 drift；2 用法、設定或 schema 問題。
- `init`／`audit`／`verify`／`sync --dry-run` 用 read-only 連線。
- schema 缺漏時：開發環境跑 `dotnet ef database update`；production 一律經 CD 套用 migration。
- production 的 `sync --apply` 要在 migration 套用之後，並經使用者授權。

## 規則檔（config/）

| 檔案 | 內容 |
|---|---|
| `canonical_categories.toml` | 18 類：`slug`、`display_name`、`sort_order`、`is_active`（預設 true） |
| `provider_roots.toml` | 各來源頂層 → slug。博客來、金石堂的鍵是頂層 Subject；誠品的鍵是第 2 層 id |
| `subject_mappings.toml` | MANUAL 例外，覆蓋推導結果、解決 AMBIGUOUS；每筆需經使用者審核 |
| `eslite_level3.tsv` | 由 `eslite-import` 從誠品分類樹存檔產生，commit 進 repo；分類樹改變時重新產生並審核 diff |

修改規則後：跑 `pytest scripts/categories/tests`（出貨設定測試會檢查數量與 0 個 AMBIGUOUS／unruled），再 `sync --dry-run` 審核報告。

## sql/audit-subjects.sql（P0，唯讀）

列出各來源的 Subject 與書數，並推測每個 Subject 的上層候選，作為擬定 Canonical 分類集合的依據。

```bash
psql -X -v csv=category-audit-subjects.csv -f scripts/categories/sql/audit-subjects.sql
```

- 整份 SQL 在 `BEGIN READ ONLY` 中執行，最後 `ROLLBACK`，不建立任何物件，所以也可以在 `default_transaction_read_only=on` 的連線上跑。
- 畫面會輸出第 1～4 段：各來源概況、全書庫概況、異常、頂層候選。
- 第 5 段的完整清單寫入 `csv` 變數指定的檔案（省略時是目前目錄的 `category-audit-subjects.csv`）。欄位：`source_code, subject, books, parent_candidate, parent_books`。
- 「上層候選」是用共同出現推測的：如果另一個 Subject 出現在這個 Subject 的每一本書上，而且書數更多，就當作上層候選。兩個 Subject 書數相同時無法分出上下，兩者都會列為頂層候選。誠品每本書只存第 3 層名稱，所以誠品的 Subject 全部會列為頂層候選；誠品的層級改從分類樹取得。

驗證：2026-11-14 在 EF Schema 的 disposable PostgreSQL 上，用 read-only 連線跑過；當時用的是暫時測試，驗證完已刪除。資料包含博客來三層、金石堂兩層、誠品單層，以及一筆沒有 Source 的 Subject。
