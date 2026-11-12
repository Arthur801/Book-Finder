# 實作報告：誠品 crawler — 第一次完整清單 run 與補跑（CB-08）

> 這是實作紀錄，不是規格。規格以 `crawler/docs/*` 與[誠品計畫](../plans/eslite-category-crawler.md)為準，待辦見 `crawler/docs/backlog.md` CB-08。前一份報告是 [Phase 6 canary](eslite-phase6-canary.md)。

## 變更檔案

| 項目 | PR | 內容 |
|---|---|---|
| 限制級略過 | #180（merge `10bab4d`） | 依 run 1 的結果與使用者決定修改程式。M `catalog_core/{models,category_run,category_ledger}.py`、`eslite/{models,parse_list,parse_detail,run,artifacts}.py`；測試 CR-E06；`crawler/docs/` 五份文件 |
| run 1 核對紀錄 | #181 | M `crawler/docs/backlog.md`（CB-08） |
| 本報告 | `eslite-full-run-report` | A 本報告；M `crawler/docs/{backlog,update-history}.md`、`Docs/plans/eslite-category-crawler.md`（狀態行） |

清單 `crawler/eslite-pages.txt`（254 頁）由 `deploy/local/eslite_category_pages.py` 產生（2026-11-11T11:45:42Z）。條件是中文書第 3 層、第 1 頁，並排除第 2 層 `44444`、`1582`。這份清單**沒有 commit**，只放在使用者主 checkout 的工作樹裡，並打包進本機 image `eslite:full`。

## 實作思路（驗收做法與判斷）

- **性質**：這是 production 上的實際執行，不是新功能。證據有三種，都由使用者貼回或在本機讀取：
  - runner 的 log；
  - `artifacts/eslite/last-run.json`。本機檔案屬於 UID 10001、權限 600，主 agent 是用 `eslite:full` image 以 UID 10001 唯讀掛載、`--network none` 讀取的；
  - 以主帳號執行的唯讀 SQL `verify-eslite-canary.sql`。時段由 `psql -v t0/t1` 指定。
- **補跑的設計**：清單從頭重播（replay）。已有 ESLITE Source 的卡片只更新 `last_seen_at`，不抓詳細頁，所以補跑的請求幾乎都花在還沒處理過的頁上。這個設計不需要進度狀態檔。
- **判定標準**：
  - 核對 SQL 的計數要和 `last-run.json` 一致；
  - 半寫入、重複、ISBN 共用都是 0；
  - 其他 provider 和 Bestseller 沒有變動；
  - 沒有 403／429。
- **run 之間的修正**：run 1 有 92 本限制級被當成 parse error。使用者決定直接略過，於是在補跑前完成 #180：列表卡片 `is_age_restricted` 為 true 時不抓詳細頁；詳細 `restricted` 為 true 時拋 `RestrictedProduct` 作為兜底。兩種都計入 `restricted_skipped`，不算失敗、不發 ALERT。金石堂的輸出不變。

## 執行紀錄（Log）

| | run 1 | 補跑（run 2） |
|---|---|---|
| run_id | `b76a23d9-0256-4350-b821-842496e54b16` | `3ac1fd22-c2fd-496f-960e-6583f37535b2` |
| 時間（UTC） | 2026-11-11T11:49:41～20:38:41（31,740 秒） | 2026-11-11T22:19:32～2026-11-12T07:13:22（32,029 秒） |
| image | `eslite:full`（#179 時的程式） | `eslite:full`（含 #180，重新 build） |
| status／exit | **FAILED／1** | **PARTIAL_SUCCESS／0** |
| fatal error | `ConnectionTimeout: connection timeout expired` | 無 |
| `budget_exhausted` | false | false |
| 頁：完成／跳過／中斷／未到 | 114／0／1／139 | 242／12／0／0 |
| `items_listed`／`items_seen` | 4529／4522 | 8408／8408 |
| `details_fetched` | 4480 | 3897 |
| `http_attempts`／`http_failures` | 4595／0 | 4151／0 |
| `existing_source` | 42 | 4511 |
| `imported`／`isbn_attached`／`ambiguous_created` | 2411／1976／0 | 2412／1485／0 |
| `restricted_skipped` | （尚無此欄位） | 508 |
| `failed`（`parse_error_200_count`） | 93（92） | 0（2） |
| `alert_reasons` | `failed`、`unclassified_200` | `unclassified_200` |

1. **run 1 停止的原因**：大約 20:38 UTC 時 DB 連線逾時。
   - 一本書（`1001144632682176048000`，分類 `/3/6554`）的 3 次 DB 嘗試都失敗，記為 `database_error`。
   - 下一本書查 identity 時又逾時。依共用 run 的規則，identity 查詢的例外是 fatal，所以整個 run 停止。
   - 原因推測是 SSH tunnel 或網路中斷，沒有確認。中斷那一頁已 commit 的書都保留了。
   - run 1 的 93 個失敗：92 本限制級（`restricted product is not supported`，分布在 16 個分類，其中 `/3/6545` 那一頁 40 本全是），加上 1 本 `database_error`。
2. **補跑**：254 頁全部都有到達。
   - 已有 Source 的卡片只更新時間：4511 次，含跨分類重複出現的卡片。
   - 新的卡片抓詳細頁並寫入：3897 本。
3. **pacing**：兩次 run 每次請求平均約 6.9～7.7 秒（含回應時間），落在 3～10 秒的 pacing 區間內。兩次都沒有 403／429，也沒有重試失敗。

## 驗證結果

**run 1**（主帳號；t0 `2026-11-11T11:48:30Z`，t1 `2026-11-11T20:40:00Z`）

| 段 | 結果 | 對照 |
|---|---|---|
| 1 Source | total 4427、created_in_run 4387、touched_in_run 40、distinct_books 4427、no_external_id 0 | 4387 = 2411＋1976 ✅；touched 的 40 本是 canary 那頁 `/3/101` |
| 2 格式 | 0、0 | ✅ |
| 3 分布 | 新建 2411（其他 provider 0）；既有 1976（1976 本都有其他 provider） | ✅ |
| 4 抽樣 20 本 | ESLITE Source 都是 1；其他 provider 有 KINGSTONE、BOOKS_COM_TW 或兩者 | ✅ |
| 5 新書欄位 | 2411 本：ISBN 2027、AUTHOR 2360、ESLITE subject 2411、出版社 2411、出版日 2411、語言 2387、頁數 2384、簡介 2411、封面 2410 | `books` = `imported` ✅ |
| 6～8 | 0；0 列、0 列；0 | ✅ |
| 9 其他 provider | 全 0 | ✅ |

使用者第一次執行時沿用了 canary 的時段，第二次用了 crawler 帳號，第 5 段因此 `permission denied for table book_subjects`。第三次改用主帳號才完整跑完。

**補跑**（主帳號；時段涵蓋整個補跑）

| 段 | 結果 | 對照 |
|---|---|---|
| 1 Source | total 8324、created_in_run 3897、touched_in_run 4411、distinct_books 8324、no_external_id 0 | 3897 = 2412＋1485 ✅；8324 = 4427＋3897 ✅ |
| 2 格式 | 0、0 | ✅ |
| 3 分布 | 新建 2412（其他 provider 0）；既有 1485（都有其他 provider） | ✅ |
| 4 抽樣 20 本 | ESLITE Source 都是 1；6 本掛到博客來既有書時補了 NULL 欄位（`enriched_in_run` t） | ✅ |
| 5 新書欄位 | 2412 本：ISBN 2179、AUTHOR 2367、ESLITE subject 2412、出版社 2412、出版日 2406、語言 2373、頁數 2390、簡介 2396、封面 2399 | `books` = `imported` ✅ |
| 6～8 | 0；0 列、0 列；0 | ✅ |
| 9 其他 provider | 全 0 | ✅ |
| 10 抽樣 | 5 本，網址為 `https://www.eslite.com/product/<guid>`；有 ISBN-13 和 ISBN-10 都存的書 | ✅ |

**合計**：兩次 run 共新建 4823 本 Book，掛到既有 Book 3461 本。production 的 ESLITE Source 是 8324 個（含 canary 的 40 個），每本 Book 最多 1 個 ESLITE Source。

**限制級的驗證缺口已用實際資料補上**：補跑的 `details_fetched` 3897 剛好等於 `imported`＋`isbn_attached`，表示 508 本限制級**全部**在列表階段被 `is_age_restricted` 擋下，沒有一本需要靠詳細階段的兜底。

## 未解決事項

1. **12 位數 guid（使用者決定 2026-11-12：選 C，維持現狀）**：`/3/165`（第 10 張卡片 `100602589297`「孤独的泡面」）和 `/3/170`（第 7 張卡片 `100602410024`「嬉皮士救了物理学」）的 guid 只有 12 位。
   - 這兩頁其他卡片的 guid 是 16 或 23 位。
   - 列表 parser 只接受 16～23 位，所以整頁 fail closed，記為 `parse_error`。每次 run 都會跳過這兩頁，並發出 `unclassified_200` ALERT；同頁另外 17 本書也不會被處理。
   - 放寬格式要先證明詳細 API 接受 12 位 guid，這需要另外取得真站請求的授權。
2. **10 頁 `empty_category`**：`/3/50818`、`50821`、`50822`、`50823`、`57`、`60`、`50832`、`50834`、`50844`、`6562` 的 `total` 是 0，也就是目前沒有可售商品。
   - 這符合「第 1 頁 `total` 0 記為該頁失敗」的決定，不會發 ALERT，每頁只花 1 次請求。
   - 這些頁也各存了一份診斷檔（Phase 4 的實作選擇）。重新產生清單時可以再檢視。
3. **沒有 ISBN 的新書**：兩次合計 617 本（384＋233），約占新書的 13%。依「無 ISBN → 新建」規則，金石堂若也有同一本，會是不同的 Book。要不要另訂比對規則，由使用者決定。
4. **DB 逾時會讓整個 run 停止**：這是共用 run 的現行規則（identity 查詢的例外是 fatal），金石堂也一樣。補跑可以接續，但一次斷線就浪費了剩下的 budget。要不要改成重連或只略過那本書，還沒決定。
5. **只抓第 1 頁**：每個分類只抓最新的 40 本。補跑時有 16 個 run 1 建立的 Source 沒被看到，多半是新書上架後被擠出第 1 頁，這是「只抓第 1 頁」的預期結果。
6. **清單沒有 commit；CD 推送 `ESLITE_CRAWLER_IMAGE` 還沒做（CB-07）**。runner 沒有寫 `runner/eslite-last-run.json`：兩次 run 都是 container 自己正常結束，不屬於 runner 會寫 record 的情況。
7. **production 狀態**：ESLITE 維持 enabled，網站會顯示這 8324 本的誠品連結。

## Code Review 與修正

本報告沒有程式變更。run 之間的程式修正（#180）由 Haiku subagent 以 TDD 撰寫，主 agent 核對 diff 並親自重跑完整 crawler 測試：21375 passed、0 skip，ruff check／format 通過。金石堂的 golden test 和既有測試都沒有修改。
