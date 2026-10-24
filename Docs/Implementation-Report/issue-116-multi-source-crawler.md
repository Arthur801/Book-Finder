# 實作報告：#116 multi-source crawler（phase A、phase B 與 review 修正）

- 來源：#113 multi-source 規格的 crawler 部分（`Docs/modules/crawler.md`、`Docs/data/data-model.md` §7）；計畫 `cheerful-finding-shell`（R1～R6、§4 驗證 #1～#19 中的 crawler 端）
- Issue：#116（crawler）；與 #115（Domain／Infrastructure／Web，migration 010）及 #117（PR2）同批發布
- Branch：`issue-116-multi-source-crawler`（worktree `Book-Finder-wt/issue-116-multi-source-crawler`），自 `main` `ee29e02` 開始，已合併 #115 phase A 與 review 後的 `7b7bfc0`
- 實作：主 session 以 TDD 實作（red 先寫）；雙軸 code review 由協調者完成，本報告只記錄處理方式
- 日期：2026-10-25

## 背景

#113 規格把 crawler 從「只認博客來、ISBN-13→10 逐一比對、榜內重複不寫入、`last_seen_at` 只在榜單替換時更新」改為：provider registry（`source_code`）、ISBN 正規化（§7.1）與 distinct Book 比對（§7.2）、附加來源時補 NULL（§7.4）、Source identity 矩陣（§7.3）、兩層 outcome（`CatalogResolution`／`RankingDecision`，§3.5）、`last_seen_at` 逐項 touch（§6.1）、disabled provider 拒絕執行（§3.1）。本 issue 只做 crawler 端；資料表結構由 #115 的 migration 010 提供。

## 設計決定

| 項目 | 決定 | 依據 |
|---|---|---|
| 讀取 `source_providers` 失敗 | 以 FAILED 結束（exit 1），記一行 ERROR，不建立 fetcher | 規格只把 disabled 與未登錄列為設定錯誤（exit 2） |
| 未登錄（查無 row） | exit 2，與 disabled 相同 | §3.1 |
| 補 NULL 的 subtitle | 永不補 | §7.4，博客來沒有可靠的副標題 |
| 補 AUTHOR | 只在 Book 沒有任何 AUTHOR 時補，順序接在現有最大值之後 | §7.4 |
| `updated_at` | 只在真的補了 books 欄位時更新 | §7.4 |
| 衝突（`source_identity_conflict`） | FAILED，`attempts = 0`，不重試、不 touch、不寫入 | §7.3，且沒有抓 detail |
| `items_seen` | 送進 resolution 的 item 數，包含之後被跳過的（含榜內重複、限制級、失敗） | §19.2 |
| job name | `daily-bestseller`、`first-book`、`category-pages` | §19.2、§15.8 |
| shell 模式名稱 | `run-crawler.sh first_book`（底線）；log 的 job_name 仍為 `first-book` | 與既有 `daily`、`pages` 的命名一致，但 job name 依規格保留連字號 |
| 常數 | `ProviderCode.BOOKS_COM_TW`、`PROVIDER` 只定義一次（`models.py`），其他模組匯入 | review |

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/books_crawler/normalize.py` | 修改 | §7.1 正規化（NFKC、明確的 White_Space code point 集合、ASCII 大寫）；移除 checksum 與長度驗證 |
| `crawler/books_crawler/identity.py` | 新增 | §7.3 矩陣（純函式）；衝突、URL 漂移（WARNING）、NULL external_id 不 backfill（INFO） |
| `crawler/books_crawler/db.py` | 修改 | 只讀寫 `source_code`；`find_books_by_isbn`（distinct Book，三種類型）；`touch_source`；`persist_new_source` 含 §7.4 補 NULL；`provider_enabled`；`replace_bestsellers` 不再更新 `last_seen_at` |
| `crawler/books_crawler/run.py` | 修改 | 身分解析 → touch（重試同 DB 寫入、不重抓 detail）→ 新來源寫入；0／1／≥2 本分別為 IMPORTED、ISBN_ATTACHED、AMBIGUOUS_CREATED |
| `crawler/books_crawler/cli.py` | 修改 | 建立 fetcher 前讀 `source_providers.enabled`；停用或未登錄 exit 2；讀取錯誤 exit 1 |
| `crawler/books_crawler/models.py` | 修改 | `IdentifierType.ISBN`、`ProviderCode`、`PROVIDER`、`SourceRecord`、`SkipReason.SOURCE_IDENTITY_CONFLICT`；移除 `IsbnMatch` |
| `crawler/books_crawler/ledger.py` | 修改 | 匯入 `PROVIDER` |
| `crawler/tests/test_isbn_fixture.py` | 新增 | 共用 fixture 逐 byte 比對（73 組）；每個 White_Space code point 都有 vector |
| `crawler/tests/test_identity.py` | 新增 | §7.3 矩陣每一列；NULL external_id 的 INFO log |
| `crawler/tests/test_normalize.py`、`test_parsers_real_fixtures.py`、`test_e2e_real_fixtures.py` | 修改 | ISBN 期望改為 §7.1 規則（型別 `ISBN`、不驗 checksum） |
| `crawler/tests/test_db_integration.py` | 修改 | 新增 legacy ISBN_13 比對、NULL 補值、ambiguous、touch、URL 漂移、衝突、trigger、`provider_enabled` 的 DB 測試；既有測試改依新規則 |
| `crawler/tests/test_cli.py`、`test_run_pages.py`、`test_first_book.py` | 修改 | 新增 provider 停用與讀取失敗；touch 失敗的 policy 與 store 無成功 touch |
| `tests/DatabaseIntegration/EfStaleDetectionTests.cs` | 新增 | plan §4 #15：9 種 §7.4 補值，依 embedding／profile hash 的欄位判定 pending 與 stale |
| `Docs/data/data-model.md` §14、`Docs/modules/crawler.md` §2、§3.1 | 修改 | 現行實作狀態；舊 baseline 標示為已由 #116 取代；provider 讀取錯誤的 exit code |
| `crawler/docs/*`、`crawler/README.md` | 修改 | 架構、流程、測試覆蓋、backlog（CB-04、CB-05 關閉，CB-06 保留）、更新歷史 |

## 實作思路

- **正規化是唯一的比對 key**：寫入與比對都使用 §7.1 的結果；不驗證長度與 checksum，因此錯誤的 ISBN 也會以 `ISBN` 儲存。搜尋端的 ISBN 判斷（10 或 13 位）與寫入端分開（data-model §7.1）。
- **比對看 distinct Book**：一次 SQL 查出 `ISBN`、`ISBN_10`、`ISBN_13` 三種類型的 distinct Book。一本 Book 有多個命中值只算一本，因此不會誤判 ambiguous。
- **附加與補 NULL 在同一 transaction**：補值前用 `FOR UPDATE` 讀取 books；只補 NULL 欄位，日期與精度成對；identifiers 與 subjects 使用 `ON CONFLICT DO NOTHING`。
- **touch 獨立 transaction**：每個既有 Source 在解析當下立即 touch，不依附於榜單替換。失敗依 DB 寫入的重試規則（最多 3 次，不重抓 detail）；最後失敗時 `existing_source_count` 不加一，依模式處理。
- **身分矩陣是單一函式**：`decide_source_identity` 只接收兩個查詢結果，因此可以完整單元測試；Books.com.tw 不提供 external_id，只走 URL 路徑。
- **trigger 負責相容**：SQL 只寫讀 `source_code`；v0.0.4 形式的寫入由 migration 010 的 trigger 補上 `source_code`。

## 執行紀錄（Log）

1. 階段 A（`0149b69`、`448571e`、`ad82318`、`fb707de`）：兩層 outcome、summary 欄位、`run-crawler.sh first_book`、docstring 重新編號、docs 同步。
2. 合併 #115 phase A（`b79d278`），DB 測試改由 EF 建立含 migration 010 的 schema。
3. 階段 B（`861c334`）：ISBN 正規化、身分矩陣、比對與補 NULL、touch、provider 閘門；部分既有測試因舊規則失敗（checksum、`ISBN_13` 期望、`find_source` 等），依新規則更新。
4. 階段 B docs（`75b8aab`）。
5. review 修正（`1051d6e`、`0fa845d`、`0d3e28f`），見下節。
6. 本報告與更新歷史。

## 驗證結果

| 驗證 | 指令 | 結果 |
|---|---|---|
| crawler 單元與 DB 整合 | `cd crawler && ../.venv/bin/python -m pytest -q` | 528 passed，0 failed（DB 整合使用含 migration 010 的 EF schema） |
| CI lint | `ruff check .`、`ruff format --check .`（pinned 0.17.2） | 通過 |
| deploy 測試 | `python -m pytest deploy/tests -q`（pytest 9.1.1） | 632 passed，7 skipped |
| deploy lint | `ruff check --config deploy/ruff.toml deploy` | 通過 |
| CI 腳本測試 | `pytest .github/scripts/tests` | 69 passed |
| C# 建置 | `dotnet build Book-Finder.csproj` | 0 error |
| C# DatabaseIntegration | `dotnet test tests/DatabaseIntegration` | 131 passed（含 9 個新 stale detection 案例） |
| shellcheck | `run-crawler.sh` | 只有 SC1090（第 20 行，既有）；CI 不檢查此檔 |

## Code Review 與修正

協調者完成雙軸審查（Standards、Spec），逐條核對後以新增 commit 修正（未 amend、未 rebase）。

| 軸 | 發現 | 處理 |
|---|---|---|
| Spec | `run.py` 模組 docstring 仍寫「ISBN-13 → ISBN-10，不補 NULL」 | 改寫為 §7.2 distinct Book 比對與 §7.4 補 NULL（`1051d6e`） |
| Spec | `run_pages` docstring 仍寫「不更新 `last_seen_at`」 | 改為依 §15 touch 既有 Source（`1051d6e`） |
| Spec | data-model §14 三條舊 baseline 與現行行為並列，容易誤讀 | 標示為 #116 已取代的歷史對照（`0fa845d`） |
| Spec | `crawler.md` §2 是否有同樣問題 | 已核對，無舊 ISBN 陳述；§2 的「已實作」列已在 `75b8aab` 更新 |
| Spec | architecture L37「ISBN 命中不 canonical merge」 | 改為附加並依 §7.4 補 NULL（`0fa845d`） |
| Spec | test-suite「ISBN format／checksum 正確」 | 改為 §7.1 正規化、以 `ISBN` 保存、不驗 checksum（`0fa845d`） |
| Spec | 身分矩陣的「NULL external_id 不 backfill」只有行為、沒有 INFO log | 在 identity 模組輸出 INFO，並加單元測試（`1051d6e`） |
| Spec | 讀取 `source_providers` 失敗的 exit code 未寫入規格 | `crawler.md` §3.1 與 README 明確寫出 exit 1，disabled 與未登錄為 exit 2（`0fa845d`） |
| Spec | touch 失敗測試未確認 `existing_source_count` 與 `last_seen_at` | DB 測試已有兩者斷言；pages 與 first_book 補上「沒有成功 touch」的斷言（`1051d6e`） |
| Spec | plan §4 #15 缺少 C# 測試 | 新增 field-sensitive theory，使用既有 embedding 與 profile store 的 pending／stale API（`0d3e28f`） |
| Standards | `PROVIDER` 在 cli、db 各定義一次 | 只在 `models.py` 定義，其他模組匯入（`1051d6e`） |
| Standards | ISBN 日誌字串重複三次 | 抽成單一變數 `isbn_text`（`1051d6e`） |
| Standards | `_write_identifiers` 為何固定寫 `ISBN` 型別不明 | 加一行註解說明 §7.1 與 §7.2（`1051d6e`） |
| 處理 | 更新歷史仍有「本 commit」placeholder、範圍標題只寫 phase B | 換成實際 SHA，標題改為涵蓋 phase B 與 review 修正（本報告 commit） |

## 未解決事項

1. **Unicode 版本**：spec 固定 NFKC 與 White_Space 於 Unicode 15.1；venv 的 Python 3.14 使用 Unicode 16.0。共用 fixture 全部通過，但 15.1 至 16.0 之間新增、且有相容分解的字元仍可能有差異。需要固定的 Unicode 表格，或在執行期比對版本。
2. **PR4（migration 011）**：移除 `ISBN_10`、`ISBN_13` 型別與其比對 SQL；需要 gate 全部通過並經使用者授權。CB-06 保留。
3. **`book_offers`**：只建表，沒有 writer；`offer_updated_count` 固定 0。
4. **發布順序**：與 #117（PR2）及 #115 同一個 release tag 發布。發布前 production 不得手動執行 `first_book`；它現在可經 `run-crawler.sh first_book` 取得 run.lock，但新 identity 規則尚未在 production 驗證。
5. **已知限制**：Books.com.tw 的 adapter 不提供 external_id，因此身分衝突與 URL 漂移的路徑目前只由單元測試與 DB 測試覆蓋，不會由真實博客來資料觸發。
