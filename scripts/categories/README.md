# scripts/categories — Canonical Category 維護工具

計畫：[Docs/plans/canonical-category-browse.md](../../Docs/plans/canonical-category-browse.md)。

目前只有 P0 的唯讀盤點 SQL。Python 工具（`audit`／`init`／`sync`／`verify`）與本模組的 `docs/` 五份文件會在 P2 加入。

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
