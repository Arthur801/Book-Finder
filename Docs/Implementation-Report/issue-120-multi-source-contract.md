# 實作報告：#120 migration 011 contract 與 ISBN cutover（#113 PR4）

> 實作紀錄，不是規格。規格以 `Docs/data/data-model.md` §6.5、§7.2、§11.3～§11.5 與 `Docs/modules/book-catalog.md` §3、§4 為準。

## 變更檔案

| 模組 | 檔案 | 內容 |
|---|---|---|
| M1 migration | `Infrastructure/Persistence/Migrations/20261025120000_ContractMultiSourceCatalog.cs`（含 Designer）、`AppDbContextModelSnapshot.cs` | 手寫 011：gate 4／5 self-guard → ISBN_10／13 轉 `ISBN`（`ON CONFLICT DO NOTHING`）→ DELETE → check 收斂為 `ISBN`、`OTHER` → DROP legacy partial unique → DROP trigger 與 function → DROP `source_type` 與其 check、index → `book_subjects` PK 換成 `(book_id, subject, source_code)`。Down 還原 010 的實體 schema；已有 KINGSTONE／ESLITE 來源時拒絕 |
| M1 C# | `Domain/Entities/IdentifierType.cs`、`IsbnIdentifierTypes.cs`（刪除）、`BookIdentifierConfiguration.cs`、`EfBookSearch.cs`、`EfBookDetailReader.cs`、`Models/BookDetailViewModel.cs` | 只剩 `Isbn`、`Other`；Search 與 Detail 只讀 `ISBN`，Detail 依值排序，移除 010 期間的去重與類型優先序 |
| M1 測試 | `tests/DatabaseIntegration/ContractMigration011Tests.cs`、`MultiSourceCatalog010SchemaTests.cs`、`MigrationServer.cs`、`SqlHelpers.cs` 等 | test-plan §7 #8、#10（011 與 Down）、gate 4／5 guard、Down 拒絕 |
| M2 crawler | `crawler/books_crawler/models.py`、`db.py`、`run.py`（docstring）與測試 | distinct Book 查詢只查 `identifier_type = 'ISBN'`；DB 測試改為 011 schema |
| M3 compat | `deploy/lib/contract_allowance.sh`、`deploy/migration-test/compat.sh`、`contract/20261025120000_…/allow.tsv`、`verify.sql`、`.github/workflows/ci.yml`（summary） | 經 review 的 contract allowance：只在該 migration pending 時生效，只准刪兩個 `source_type`、改寫 `book_identifiers`，`verify.sql` 證明轉換正確 |
| M3 seed／preflight | `deploy/migration-test/seeds/20261025120000_ContractMultiSourceCatalog.sql`、010 seed 追加列、`preflight/20261025120000_…sql`、`ContractMigration011PreflightTests.cs`、`ContractMigration011VerifyTests.cs` | 011 seed；gate 7 唯讀 preflight（test-plan §7 #20） |
| M4 gate 9 | `deploy/migration-test/prev-release-on-contract.sh`、`prev_crawler_driver.py`、`deploy/tests/integration/test_prev_release_on_contract.py` | v0.0.6 的 Web 與 crawler 在 011 上的相容性（test-plan §7 #13、#14），本機執行 |
| 文件 | `Domain/`、`Infrastructure/`、`Application/`、`Models/`、`crawler/`、`deploy/`、`tests/` 的 `docs/*`；`Docs/data/data-model.md`、`book-catalog.md`、`crawler.md`、`test-plan.md`、`deployment.md`；`deploy/README.md` §4.4、§4.5 | 與程式同步 |

## 實作思路

- **Self-guard 放進 migration**：gate 4、5 不只靠操作者檢查，011 一開始就在同一個 transaction 裡重算，不通過就 RAISE，DB 留在 010。
- **Contract allowance 必須精確**：compat 原本要求所有欄位與資料不變。011 的資料變動是刻意的，因此改成「列出允許的變動 + 用 SQL 證明結果」，其他表與欄位仍是嚴格比對；allowance 只在該 migration pending 時套用，列出的欄位若仍存在也算失敗。
- **Gate 7 的真正檢查是部署後比對**：preflight 的「每個值最多一筆」「只會去重同一本 Book 的同一個值」在 DISTINCT 計算下必然成立，標為 INFO；`deploy/README.md` §4.4 要求部署後以 `count(*)` 對照預估值。
- **Gate 9 用上一個 release 的實際 image**：以 production 的 v0.0.6 web 與 crawler digest，連到 011 的拋棄式 DB。crawler 以離線 driver 呼叫 v0.0.6 自己的 API，不連博客來。PR3 的 Detail 去重在 011 上無法構造（PK 讓同一本 Book 的同一個值只能有一筆 `ISBN`），script 改為驗證 Detail 正確顯示 ISBN。

## 執行紀錄（Log）

- M1～M4 由 subagent 實作，每個模組完成後由主 agent 重跑測試與實際資料驗證。
- M3 的第一個 subagent 在前一個 session 結束時中斷（已留 5 個 commit），由新的 subagent 依規格逐項核對後補上 `f2dbd47`（schema-ahead 路徑也要 DROP `compat_before`）。
- v0.0.6 部署過程（#121）與本 PR 平行進行，main 合併 #122 後本分支以 merge commit 併入，解決 `deploy/docs` 的衝突（#121 保留 §3.20／update-history §3.12，本 PR 改為 §3.21 與 §3.13、§3.14）。

## 驗證結果

- **本機資料實測（主 agent）**：本機 DB 複本先以 v0.0.6 efbundle 到 010，再跑 011：ISBN_13 3,046 筆 → `ISBN` 3,046 筆，subjects 11,641、sources 3,270 不變；Down 回到 010 成功；idempotent script 重跑無誤。preflight 15 列全部 `ok`，預估 3,046 與 011 後的實際筆數一致。
- **本機 compat（照 CI 指令，010 → 011）**：allowance 套用、`verify.sql` 0 筆、其他資料保留、schema 與全新安裝一致、`compat checks passed (forward_ok=true)`。
- **Gate 9（主 agent 重跑）**：`RESULT PASS 15/15`。
- **Gate 2（v0.0.6 crawler digest，真實博客來，DB 複本）**：`daily` exit 0，82 筆 Existing touch、Bestseller 替換、名次缺號不重編；`pages` 15 分鐘寫入 45 本新書，全部 `ISBN` 類型、13 碼、`source_code = BOOKS_COM_TW`。
- **merge 後完整重跑**：`deploy/tests` 670 passed、8 skipped（Python 3.12 相同）；`.github/scripts` 78 passed；ruff 通過；`dotnet build` 0 warning；UnitTests 823、DatabaseIntegration 144、WebIntegration 280 全部通過；`dotnet format`、`has-pending-model-changes`、`check_migrations.py` 通過；crawler 19,625 passed；Unicode 表檢查通過。

## 未解決事項

- 011 的部署屬 L4，需要使用者逐項確認 data-model §11.3 gate：gate 1（新版 Web 穩定）、gate 6（關閉 v0.0.4 rollback window）、gate 7（production preflight 與部署後比對）、gate 8（backup 與 recovery）。
- Gate 9 只在本機執行，未加入 CI。
- Down 把 `source_type` 加回最後一欄（不是原本的位置），已轉成 `ISBN` 的資料不會轉回 ISBN_10／13（R7 的單向變更，已記錄在 migration 註解）。
- Standards review 的程式異味（gate 9 script 的固定計數、compat.sh 的 allowance 解析重複三次、`check_data_preserved` 過長）屬判斷題，未在本 PR 處理，列入 `deploy/docs/backlog.md`。

## Code Review 與修正

兩軸 review（Standards、Spec 平行）後由主 agent 逐項核對：

- **Standards**：`Models/docs/backlog.md` M-B05、`Models/docs/test-suite.md` 指向不存在的 M-T05b、`crawler/docs/backlog.md` CB-06 的未來式目標，三項屬實，已修正（`b8fafca`）。`Domain/docs/test-suite.md` 一項經核對已是最新內容，不需修改。
- **Spec**：data-model §14 的 seed 待辦、test-plan §7 開頭的狀態句已修正；test-plan #13 補充 Detail 去重在 011 上無法構造的原因與 health 的代表方式；`deploy/README.md` §4.4 補上部署後的 row 數比對（gate 7 最後一項）。010 seed 追加列與 migration 額外的未知類型檢查保留（為了讓 compat 實際驗到轉換與去重，以及在轉換前拒絕未知資料）。
