# scripts/categories 測試案例

> 建立：2026-11-14，分類計畫 P2。執行：在 repo 根目錄 `.venv/bin/python -m pytest scripts/categories/tests -q`；lint 用 `ruff check`／`ruff format --check --config crawler/ruff.toml scripts/categories`。CI job：`categories-tool`。

## Fixture 與隔離

- Unit 測試不連 DB、不連網；誠品分類樹用 [tree_fixtures.py](../tests/tree_fixtures.py) 的合成樹。
- Integration 測試沿用 crawler 的方式（[conftest.py](../tests/conftest.py)）：`dotnet ef migrations script --idempotent` 產生 EF schema，testcontainers 啟動 pgvector PostgreSQL，每個測試一個全新資料庫。沒有 dotnet 或 Docker 時 skip。

## 案例

| ID | 範圍 | 驗證內容 | 位置 |
|---|---|---|---|
| SC-T01 | 規則檔驗證 | 不合法的類別定義（如重複 slug）、頂層規則（未知 slug、空白或過長的鍵、值不是字串、誠品 id 不是正整數、不合法 TOML）與 MANUAL 規則 → `ConfigError`，訊息帶檔名；缺檔也是 `ConfigError`；`note` 可省略 | [test_category_config.py](../tests/test_category_config.py) |
| SC-T02 | 誠品清單 | 依樹的順序產生第 3 層，略過預設排除的第 2 層；缺 top category、名稱只剩空白時拒絕；TSV 往返；寫入是原子的（失敗時保留原檔）；格式錯誤或缺少的 TSV 被拒 | [test_eslite_tree.py](../tests/test_eslite_tree.py) |
| SC-T03 | 對應規則 | 不同來源同名各自對應；多個頂層對到同一類；誠品同名同 slug 只一筆、不同 slug 為 AMBIGUOUS；MANUAL 覆蓋並解決 AMBIGUOUS；unruled 第 2 層；diff 的 insert／update／unchanged／orphan；套用後再 diff 全為 unchanged | [test_category_mapper.py](../tests/test_category_mapper.py) |
| SC-T04 | 出貨設定 | 18 類；頂層 21／22／21；TSV 254 列且 0 unruled；不含 MANUAL 時 AMBIGUOUS 恰為兩個名稱，含 MANUAL 時為 0、可 apply，Mapping 283 筆；誠品「宗教」「命理占星／風水」推導為 humanities／lifestyle，MANUAL 後為 religion | [test_shipped_config.py](../tests/test_shipped_config.py) |
| SC-T05 | CLI | 用法錯誤與缺 `DATABASE_URL` 為 exit 2；有 AMBIGUOUS 時 `--apply` 不連線就拒絕；連線失敗 exit 1 且不印密碼；`redact()` | [test_cli.py](../tests/test_cli.py) |
| SC-T06 | DB 整合 | `init` 在已 migrate 的 DB 通過，刪表或缺 index 時 exit 2；dry-run 不寫入；apply 寫入 18 類與 Mapping；第二次 apply 寫入 0 列且時間戳不變；改顯示名稱恰好 1 筆 update；手動加入的 orphan 被回報並保留；AMBIGUOUS 拒絕且 0 列；中途失敗整批 rollback；`verify` 結束碼；audit 統計（跨來源同一本書只算一次、兩類以上）；`book_subjects` 不被修改 | [test_category_integration.py](../tests/test_category_integration.py) |

## 執行紀錄

- 2026-11-14（`deb899f`，主 agent 重跑）：103 passed、0 skipped；ruff check／format 通過。
- 注意：本機 `.venv` 的 ruff 是 0.17.2，CI 釘 0.17.4（`crawler/requirements.txt`）；第一次 CI 因 EXE001 失敗。本機請用 `uvx ruff@0.17.4` 檢查，與 CI 一致。
- Mutation 抽查（2026-11-14）：拿掉 Mapping UPSERT 的 `IS DISTINCT FROM` 條件 → SC-T06 的兩個冪等測試失敗；把 AMBIGUOUS 判斷改成永不成立 → SC-T03～SC-T06 共 4 個測試失敗。兩者都已還原。

## 已知缺口

- 沒有對 production 規模資料跑過 `sync`／`audit`；P3 由使用者以 dry-run 報告確認。
- CI 的 `categories-tool` job 尚未在 GitHub Actions 上跑過（PR 開出後的第一次 CI 為準）。

互參：[架構](architecture.md)、[流程](workflow-diagram.md)。
