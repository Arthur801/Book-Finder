# 實作報告：Canonical Category P0～P3（盤點、Schema、維護工具、production 匯入）

> 這是實作紀錄，不是規格。設計與決定以[分類計畫](../plans/canonical-category-browse.md)、`scripts/categories/docs/*`、`Domain/docs/*`、`Infrastructure/docs/*` 為準。分類頁（P4、P5）尚未開始。

## 變更檔案

| 階段 | PR | 內容 |
|---|---|---|
| P0 | #183、#184 | 計畫 v2.1／v2.2；唯讀盤點 SQL `scripts/categories/sql/audit-subjects.sql`；P0 結果與 18 類分類集合 |
| P1 | #185 | EF migration `20261114003848_AddCanonicalCategories`：`canonical_categories`、`provider_category_mappings`，以及 `book_subjects (source_code, subject)` index；Domain entity、configuration、DatabaseIntegration 測試；`CONTEXT.md` 新增三個術語 |
| P2 | #186 | `scripts/categories/` 維護工具（`audit`／`init`／`sync`／`verify`／`eslite-import`）、TOML 規則檔、誠品第 3 層清單、CI job `categories-tool`、模組 `docs/` |
| P3 規則 | #187 | 誠品「宗教」「命理占星／風水」改歸 `religion`（決定 #8）；deploy backlog DEP-B24 |
| 本報告 | `canonical-category-p3-report` | A 本報告；M `scripts/categories/docs/{backlog,update-history}.md`、計畫與 `Docs/plans/README.md` 的狀態行 |

## 實作思路

- **P0 先盤點、再定規則**：`book_subjects` 只存名稱，不存層級。為此用唯讀 SQL 依「共同出現」推測上層分類，再請使用者在 production 執行。結果顯示：
  - 博客來、金石堂的書本身就帶有頂層名稱，所以只要對應頂層就足以分類（決定 #1）；
  - 誠品只存第 3 層名稱，因此改用分類樹存檔的第 2 層 id 展開（決定 #6）。
- **Schema 只由 EF migration 管理**：Python 工具的 `init` 只做檢查（決定 #2）；production 經 CD（v0.0.8）套用。
- **寫入安全**：
  - `sync` 預設只做 dry-run；
  - `--apply` 在單一交易內先鎖表，再計算計畫；
  - UPSERT 只在值改變時才寫入，重跑不會改動任何列；
  - orphan 只回報，不刪除；
  - 有 AMBIGUOUS 時拒絕寫入。
- **規則審核**：分兩次由使用者決定：
  - P2 解決誠品兩個同名第 3 層（決定 #7）；
  - P3 的 dry-run 逐行審核後，調整誠品兩個宗教命理名稱（決定 #8）。
- **連線**：scratchpad 的 `run-categories.sh` 開 SSH tunnel，密碼走 SSM → stdin → libpq 環境變數，連線使用 `verify-full`。`read` 模式整條連線唯讀；`write` 只接受 `sync --apply`，並且在開 tunnel、取密碼之前就先檢查。

## 執行紀錄（Log）

全部在 2026-11-14 進行；production 操作都由使用者執行。

1. **P0 盤點**：`audit-subjects.sql` 輸出 2508 列。第二輪覆蓋率查詢顯示博客來 2879 本全部有頂層；金石堂有 183 本看似沒有頂層，原因是查詢漏列了「羅曼史」與全形斜線的「教育／親子教養」。
2. **v0.0.8 部署（P1 migration）**：
   - 第一次 CD `plan` exit 2：EC2 root 磁碟已滿（6.7 GB，100%），pull web image 時失敗。
   - 使用者刪除 state 沒有引用的舊 image，但其中包含 host `PSQL_IMAGE`（pgvector）。這個 image 是主 agent 誤列進刪除清單的：當時只檢查了 `deploy/host` 程式碼，沒有檢查 `host.conf`。
   - 第二次 plan exit 3：`schema: observation failed … No such image: pgvector/…`。使用者在 host 手動執行 plan 取得 JSON，以 digest 重新 pull 後 plan 恢復正常。
   - 另刪除 v0.0.6 的兩個 image 騰出空間。
   - dispatch v0.0.8 → `completed:success`。詳見 deploy backlog DEP-B24。
3. **init**：10 項全部 PASS。
4. **第一次 `sync --dry-run`**：categories insert 18、mappings insert 283，沒有 orphan、AMBIGUOUS、unruled。逐行審核時發現誠品「宗教」→ humanities、「命理占星／風水」→ lifestyle，結果「宗教命理」類沒有誠品的書。使用者決定改歸 religion（#187）。
5. **`sync --apply`**：使用者以 #187 的規則執行（apply 本身的輸出沒有貼回）。
7. **`verify`**（apply 之後）：`init` 10 項 PASS；`categories: insert 0, update 0, unchanged 18, orphan 0`；`mappings: insert 0, update 0, unchanged 283, orphan 0`；`verify: the database matches the rules.`。
6. **`audit`**：結果如下。

## 驗證結果

production `audit`（apply 之後，唯讀）：

| 項目 | 數值 |
|---|---:|
| 博客來 Subject：總數／已對應 | 895／21 |
| 金石堂 Subject：總數／已對應 | 1384／22 |
| 誠品 Subject：總數／已對應 | 229／229 |
| 書庫總數 | 23,491 |
| 至少有一個分類 | 23,486（99.98%） |
| 沒有分類 | 5 |
| 兩類以上 | 902 |
| 未對應的 Subject（CSV） | 2,236 列 |

- 已對應的 Subject 數等於各來源的規則數（21／22），誠品全數對應，符合 P0 的預期。
- 未對應的 2,236 個 Subject 都是博客來、金石堂的下層名稱（874 + 1362）。這些書會透過自己的頂層分類被歸類，不需要另外對應。
- 開發端驗證：
  - .NET 測試：Unit 823、DatabaseIntegration 162、WebIntegration 280；
  - `scripts/categories` 104 個；
  - crawler 21375 個；
  - 以上全部通過。CI 也通過，包括新的 `categories-tool` job。

## 未解決事項

- **5 本沒有分類的書**：推測是完全沒有 Subject 的書，例如詳細頁沒有分類資料的書，但沒有逐本核對。它們仍可在「全部書籍」中看到。如果要確認，可以用唯讀 SQL 列出書名和來源。
- **apply 的輸出沒有貼回**：`verify` 已證明 production 的 18 類與 283 筆 Mapping 和規則完全一致（unchanged 18／283），所以不影響結果。
- **DEP-B24**：host 從不刪除舊 image，root 磁碟只有 6.7 GB，下一次發布前可能又會滿。可以由 host 自動清理、擴大 EBS，或兩者都做，由使用者決定。
- **分類頁**：P4（Application／EF 查詢）與 P5（Controller／Razor UI）尚未開始；網站目前還不會讀這兩張表。
- **舊的 gate 9 腳本**：`deploy/migration-test/prev-release-on-contract.sh` 寫死只到 011，含新 migration 的 bundle 會讓它失敗（DEP-B19 補記）。

## Code Review 與修正

- 本系列沒有做兩軸 code review。依慣例，會在功能最後一個模組（P5 之後）一併執行。
- 主 agent 已親自重跑完整測試、閱讀 diff，並對 L3 程式做 mutation 抽查：拿掉 UPSERT 的 `IS DISTINCT FROM` 條件後，冪等測試失敗；讓 AMBIGUOUS 判斷失效後，4 個測試失敗。兩處都已還原。
- 執行過程中的修正：
  - CI 的 ruff 0.17.4 報 EXE001（本機 0.17.2 沒有報），移除 shebang 後通過；共用 `.venv` 改固定為 0.17.4。
  - `run-categories.sh` 原本在取得密碼之後才檢查模式，改成在開 tunnel 之前就先檢查。
