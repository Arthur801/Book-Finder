# scripts/categories 流程

> 建立：2026-11-14，分類計畫 P2。指令用法見 [README](../README.md)。

## 規則維護與同步

```mermaid
flowchart TD
    T[誠品分類樹存檔<br/>使用者取得] -->|eslite-import| TSV[config/eslite_level3.tsv]
    R[config/*.toml] --> V{category_config 驗證}
    TSV --> V
    V -->|錯誤| E2[exit 2，不連線]
    V -->|通過| D[category_mapper.derive_desired]
    D -->|--apply 且有 AMBIGUOUS／unruled| E2
    D --> C[(連線)]
    C --> S{schema 檢查}
    S -->|FAIL| H[印出 migration 提示，exit 2]
    S -->|PASS| P{source_code 都在 source_providers?}
    P -->|否| E2
    P -->|dry-run| PL[讀現況 → build_plan → 報告，exit 0]
    P -->|--apply| L[交易：LOCK → 讀現況 → build_plan → UPSERT]
    L -->|錯誤| RB[rollback，exit 1]
    L -->|成功| OK[commit，印出寫入列數]
```

- `verify`：與 dry-run 相同的計畫；有 insert／update／AMBIGUOUS／unruled 時 exit 1。orphan 不算 drift。
- `audit`：依各來源列出 Subject 數與已對應數（對應到 active 分類才算），書的分類覆蓋（有分類、沒有分類、兩類以上；一本書透過任一來源的 Subject 都算），可選 `--unmapped-csv` 輸出未對應清單。
- `init`：只做 schema 檢查。

## 上線順序（計畫 §7）

1. migration `AddCanonicalCategories` 經 CD 套用。
2. `init` → `sync --dry-run`（審核報告）→ `sync --apply`（使用者執行、需授權）。
3. `audit` 確認覆蓋率。
4. 之後的分類頁（P4、P5）讀這兩張表。

新出現、沒有規則的 Subject 只會出現在報告中；補規則後再跑 `sync`。誠品分類樹改變時，重新取得存檔並執行 `eslite-import`，審核 TSV 的 diff 後再 `sync`。

互參：[架構](architecture.md)、[案例](test-suite.md)。
