# 實作報告：誠品 crawler Phase 6 — production canary（G1～G4）

> 實作紀錄，不是規格。規格以 `crawler/docs/*` 與 [誠品計畫](../plans/eslite-category-crawler.md) §11 為準；待辦見 `crawler/docs/backlog.md` CB-08。

## 變更檔案

Phase 6 沒有新增功能程式。誠品 crawler 由下列 PR 組成（時間為 `mergedAt`，UTC），各 PR 的內容與驗證見 PR 說明與 `crawler/docs/update-history.md`：

| Phase | PR | merge | 內容 |
|---|---|---|---|
| 計畫 v1 | #167 | `0cbded4`（2026-11-10T22:38:28Z） | `Docs/plans/eslite-category-crawler.md`、backlog CB-08 |
| E0（Phase 0） | #168 | `3c833c4`（2026-11-10T23:03:34Z） | 11 份 JSON fixture、來源契約、CR-E01、計畫 v2（改用 JSON API） |
| Phase 1 core | #169 | `bdd3a37`（2026-11-11T04:16:01Z） | `ProviderCode.ESLITE`、provider-aware preflight、`ListedItem`／`ListPage` 移入 `catalog_core` |
| Phase 2 adapter | #171 | `5f406cc`（2026-11-11T04:16:17Z） | `eslite/{urls,page_list,models,parse_list,parse_detail}`（CR-E02） |
| Phase 3 M1 | #170 | `ddd5f69`（2026-11-11T05:16:14Z） | `catalog_core/http_acquisition`（CR-T21） |
| Phase 3 M2 | #172 | `6ae4429`（2026-11-11T05:43:07Z） | `catalog_core/category_run`、`category_ledger`；golden test（CR-T22） |
| Phase 3 M3 | #173 | `ab829e0`（2026-11-11T06:01:17Z） | `catalog_core/run_{artifacts,alerts,diagnostics,config}`（CR-T23） |
| Phase 4 | #174 | `84d3140`（2026-11-11T06:28:05Z） | `python -m eslite`（CR-E03） |
| Phase 5 | #175 | `4e68098`（2026-11-11T07:08:41Z） | Docker `eslite` target、runner `eslite` mode、`enable-eslite.sql`、README §9.5.1（CR-E04） |
| Phase 6 工具 | #176 | `048ce83`（2026-11-11T10:32:17Z） | `crawler/deploy/local/sql/verify-eslite-canary.sql` |
| 本報告 | `eslite-p6-report` | 本次 commit | A 本報告；M `crawler/docs/{backlog,update-history}.md`、`Docs/plans/eslite-category-crawler.md`（§11 G1～G4、狀態） |

## 實作思路（驗收做法與判斷）

- **性質**：production 驗收，不是新功能。每個 gate 以計畫 §11 的條目判定，證據來自使用者在本機的實際執行：runner 的 log、`artifacts/eslite/last-run.json`，以及以主帳號執行的唯讀 SQL `verify-eslite-canary.sql`。
- **分工**：使用者負責 build canary image、以主帳號啟用 ESLITE、執行 runner 與唯讀核對。主 agent 負責 SQL 檔與 runner、輔助腳本（scratchpad 的 `run-sql.sh`：密碼只經 SSM → stdin → libpq 環境變數），以及結果判讀與文件。
- **判定標準**：只有 §11 明列的條目算通過。G4 的通過條件：exit 0、0 個失敗、至少 1 筆新 ESLITE Source、沒有重複 Source、ISBN attach 的書其他 provider 的 Source 未變、Bestseller 未變動。

| Gate | 計畫要求（§11） | 結果 | 狀態 |
|---|---|---|---|
| G0 | E0 | 已於 #168 完成（25 次請求；改用 JSON API） | 通過 |
| G1 | 經 tunnel 跑 `python -m eslite`，schema preflight 通過 | run 進入逐頁處理，表示 preflight 與 shared migration lock 在第一個請求前已通過 | 通過 |
| G2 | 沿用 `bookfinder_crawler`；canary 前以唯讀 SQL 再確認一次 | crawler 帳號完成 40 筆 Source、29 本新書與 NULL 補值的寫入，證明權限足夠。**canary 前沒有重跑 `p2-crawler-privileges.sql`** | 通過（附註） |
| G3 | 使用者以主帳號執行 `enable-eslite.sql` | 已執行；ESLITE 為 enabled | 通過 |
| G4 | 1 頁 `normal` canary 與唯讀核對 | 全部條件符合（見「驗證結果」） | 通過 |

## 執行紀錄（Log）

1. **build**：使用者在主 checkout 把 `crawler/eslite-pages.txt` 改成一行 `https://www.eslite.com/category/3/101`（字典，`total` 188），build `eslite:canary`（2026-11-11T07:10:58Z），並在 `crawler-local.conf` 設定 `ESLITE_CRAWLER_IMAGE=eslite:canary`。`ESLITE_RUN_HARD_LIMIT_SECONDS` 未設定，使用預設 9000。主 agent 以唯讀方式確認 image 內清單為 1 頁。主 checkout 的清單修改沒有 commit，repo 上仍是只有註解的佔位檔。
2. **啟用**：使用者以主帳號（SSM 參數的舊版本）經 `run-sql.sh write` 執行 `enable-eslite.sql`。
3. **canary run** `5a1deb91-012d-46f8-86c1-272cef1e85b0`：2026-11-11T10:56:38Z～11:01:35Z（約 5 分鐘），`container=end exit_code=0`。共 41 次請求（1 次列表 API、40 次詳細 API），全部 `status=200`、`attempt=1`。使用者貼回的最後 17 次詳細請求，log 時間戳記的相鄰間隔為 3.7～10.2 秒（含回應時間），符合 3～10 秒的 pacing。
4. **核對**：使用者以主帳號經 `run-sql.sh read` 執行 `verify-eslite-canary.sql`，時段為該次 run 前後各留約 10 秒。

## 驗證結果

`last-run.json`：`status` SUCCESS、`exit_code` 0、`alert_reasons` []、`pages_completed` 1、`items_listed` 40、`details_fetched` 40、`http_attempts` 41、`http_failures` 0、`existing_source` 0、`imported` 29、`isbn_attached` 11、`ambiguous_created` 0、`failed` 0、`parse_error_200_count` 0、`skipped_pages` []、`failed_items` []。

`verify-eslite-canary.sql`：

| 段 | 結果 | 預期 |
|---|---|---|
| 1 Source | total 40、created_in_run 40、touched_in_run 0、distinct_books 40、no_external_id 0 | 40 = 29＋11＋0 ✅ |
| 2 格式 | bad_guid 0、bad_source_url 0 | 0、0 ✅ |
| 3 分布 | 新建書 29（其他 provider 0）；既有書 11（11 本都有其他 provider） | 29／11 ✅ |
| 4 掛到既有書 | 11 本的其他 provider 都是 KINGSTONE，每本 ESLITE Source 1 個；1 本（國際華語學習辭典）`enriched_in_run` true | ESLITE Source = 1 ✅；**NULL 補值第一次在真實資料上觸發**（金石堂 canary 時 9 本欄位原本齊全，未觸發） |
| 5 新書欄位 | 29 本：ISBN 26、AUTHOR 27、ESLITE subject 29、出版社 29、出版日 29、語言 28、頁數 29、簡介 29、封面 29 | 見「未解決事項」1～3 |
| 6 半寫入 | 0 | 0 ✅ |
| 7 重複 | 0 列、0 列 | 0 ✅ |
| 8 ISBN 共用 | 0 | 0 ✅ |
| 9 其他 provider | BOOKS_COM_TW 建立／touch 0、KINGSTONE 建立／touch 0、Bestseller 0 | 全 0 ✅ |
| 10 抽樣 | 5 本，網址為 `https://www.eslite.com/product/<guid>` | ✅ |

## 未解決事項

1. **沒有 ISBN 的 3 本建了新 Book**：都是字典類（例如「新編實用一字多音字典」，E0 時已觀察到 `isbn13` 為空、`ean` 是 471 開頭的商品條碼）。依規則，沒有 ISBN 就新建，所以金石堂若也有同一本，兩邊會是不同的 Book。這是「無 ISBN → 新建」規則的已知限制，不在本次修正範圍。
2. **2 本沒有 AUTHOR**：作者欄是「吳美玉/ 編」這類，依 Phase 2 規則記為 EDITOR。屬於預期行為。
3. **1 本沒有語言**：規格的語言不是「中文/繁體」或「中文/簡體」，依規則記為 None。屬於預期行為。
4. **G2 沒有在 canary 前重跑權限 SQL**：以實際寫入結果作為證據；之後若有 migration 新增 crawler 需要的表，再重跑 `p2-crawler-privileges.sql`。
5. **production 狀態**：ESLITE 維持 enabled（使用者未執行 disable），網站會顯示這 40 本的誠品連結。
6. **完整清單與 budget**：使用者尚未提供完整 `eslite-pages.txt`；soft budget 7200／hard limit 9000 秒仍是暫定（計畫 §12）。CD 推送 `ESLITE_CRAWLER_IMAGE` 與金石堂相同，尚未做（CB-07）。
7. **canary 清單**：主 checkout 的 `crawler/eslite-pages.txt` 仍有使用者未 commit 的 1 行 canary 修改，由使用者決定如何處理；`eslite:canary` image 仍在本機。

## Code Review 與修正

Phase 6 沒有程式變更，未做 code review。各 Phase 的程式由 Haiku subagent 撰寫，主 agent 逐 PR 核對 diff 並親自重跑完整 crawler 測試（Phase 5 時為 21300 passed、0 skip），詳見各 PR 說明。
