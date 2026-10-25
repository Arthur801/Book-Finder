# 實作報告：金石堂 crawler Phase 7 — production 驗收（P1、P2、P3、P5）

> 實作紀錄，不是規格。規格以 `crawler/docs/*`、`deploy/docs/*` 與 [v12 計畫](../plans/kingstone-category-crawler.md) §10 為準；待辦見 `crawler/docs/backlog.md` CB-07「Phase 7 進度」與 `deploy/docs/backlog.md`。

## 變更檔案

Phase 7 沒有新增功能程式；以下為為驗收而合併的 PR（依合併順序），檔案清單取自各 merge commit 相對第一父節點的淨變更。時間為 `mergedAt`（UTC）。

| 模組 | 分支／commit | 檔案 | 內容 |
|---|---|---|---|
| DEP-B22 跨模組 lock key（PR #149） | `deploy-lock-key-consistency` `18cc754`、`b2439e2`；merge `c02aa59`（2026-10-25T14:04:22Z） | M `deploy/tests/host/test_locks.py`（+1 測試）、`deploy/host/bookfinder_host/locks.py`（註解）、`deploy/docs/{backlog,test-suite,update-history}.md`、`crawler/docs/architecture.md` | 以 `ast` 讀取 crawler 端 `CATALOG_MIGRATION_LOCK_KEY` 與 deploy 端比對；記錄 DEP-B21 殘留風險的使用者決定（見「未解決事項」） |
| P2 專用 DB 帳號（PR #151） | `kingstone-p7-p2-db-role` `6db1e14`、`8e34cf5`；merge `56ef651`（2026-10-25T15:55:37Z） | A `crawler/deploy/local/sql/create-crawler-role.sql`（24 行）、`crawler/deploy/local/sql/p2-crawler-privileges.sql`（67 行）；M `crawler/deploy/README.md`、`crawler/docs/{backlog,update-history}.md`、`deploy/docs/{backlog,update-history}.md`、`Docs/plans/kingstone-category-crawler.md`（§10 P2） | 建立最小權限角色 `bookfinder_crawler`；唯讀權限檢查 SQL；DEP-B20 的 RDS 版本確認為 17.11 |
| P3 runner 讀 state（PR #152） | `kingstone-p7-runner-state-sudo` `f8d0778`、`b36e560`、`92b09a4`；merge `bf2b599`（2026-10-25T16:07:06Z） | M `crawler/deploy/local/run-local-crawler.sh`、`crawler/tests/test_local_runner.py`（斷言改寫）、`crawler/deploy/README.md`（§9.1）、`crawler/docs/{architecture,backlog,test-suite,update-history,workflow-diagram}.md` | 遠端讀取 EC2 `state.json` 改為 `sudo -n cat --`；§9.1 補 sudoers 寫法與「不要以 sudo 執行 runner」 |
| P1、P5 canary（PR #153） | `kingstone-p7-canary` `59e36d9`、`2b7cb9c`、`ea66a02`；merge `0bb96c9`（2026-10-25T17:06:15Z） | A `crawler/deploy/local/sql/enable-kingstone.sql`（9 行）、`verify-canary-2026-10-25.sql`（61 行）、`verify-normal-2026-10-25.sql`（50 行）；M `crawler/deploy/README.md`（§9.5）、`crawler/docs/{backlog,update-history}.md`、`Docs/plans/kingstone-category-crawler.md`（§10 P1、P5） | 兩段 canary 的結果記錄；啟用 KINGSTONE provider 的 SQL；唯讀核對 SQL；§9.5 補上「啟用 provider」與「資料核對」兩步 |
| 寫入政策預設（PR #154） | `kingstone-p7-default-normal` `17c497d`、`e7e0c6e`；merge `dff2df5`（2026-10-25T17:16:47Z） | M `crawler/kingstone/config.py`（`DEFAULT_WRITE_POLICY = NORMAL`，並修正說明註解）、`crawler/tests/test_kingstone_config.py`（4 個預設值測試）、`crawler/kingstone/cli.py` 與 `crawler/kingstone/run.py`（各 1 行註解）、`crawler/deploy/README.md`、`crawler/docs/{architecture,backlog,test-suite,update-history,workflow-diagram}.md`、`Docs/plans/kingstone-category-crawler.md`（§6 設定表、決定 #13） | 使用者決定：`KINGSTONE_WRITE_POLICY` 未設定時為 `normal`；`new-books-only` 仍可指定 |
| P3 剩餘檢查的文件（直接提交到本分支） | `339b54f`、`9a1e22b`（本分支，未合併） | M `crawler/docs/backlog.md`、`crawler/docs/update-history.md` | 把 P3 剩餘的三項實測（tunnel 斷線、SIGTERM、hard limit 與 kill）寫成步驟與預期結果；update-history 記錄 |
| 本驗收報告（本分支） | `kingstone-p7-report`，本次 commit | A `Docs/Implementation-Report/kingstone-phase7-acceptance.md`；M `crawler/docs/backlog.md`（CB-07 狀態行加實作報告連結） | 本報告 |

## 實作思路（驗收做法與判斷）

- **性質**：Phase 7 是 production 驗收，不是新功能。每個 gate 以 plan v12 §10 的條目判定，證據來自 production 上的實際執行（使用者以 crawler 帳號或主帳號連線、唯讀 SQL 核對），加上主 agent 在本機做的 P2 預先驗證。
- **分工**：使用者負責 production 連線、真站抓取、provider 啟用、唯讀核對與 SSM／角色變更；主 agent 負責 SQL 檔、runner 與文件，並在本機以拋棄式 PostgreSQL 17 驗證 P2 權限。
- **判定標準**：只有 plan §10 明列的條目算通過。全部 skip 不算 promotion 證據（§10 P5）；NULL enrichment 必須在真實資料上觸發才算驗證，否則標示為未觸發。
- **P4 不在範圍**：v12 已取消（alert 只寫 log）。

| Gate | 計畫要求（§10） | 結果 | 證據 | 狀態 |
|---|---|---|---|---|
| P1 | schema preflight 經 tunnel 在 production 通過 | 通過；preflight 與 shared migration lock 皆在第一個請求之前完成 | canary run `2d933792`（backlog CB-07） | 通過 |
| P2 | crawler 帳號只有必要 Catalog 讀寫、無 DDL | 通過；`bookfinder_crawler`（7 張表的最小權限、連線上限 5、無 DDL、不擁有物件）；RDS 17.11 | #151；使用者以新帳號執行 `p2-crawler-privileges.sql` 的結果全部符合 | 通過 |
| P3 | 本地 host 驗證 UID、mounts、Docker limits、watchdog、fencing、tunnel 斷線；以及 deploy migration 與 crawler 的 advisory lock 互斥 | 部分：canary 中已實測的項目見「驗證結果」；tunnel 斷線、SIGTERM、hard limit 與 kill、migration 互斥未在 production 實測 | backlog CB-07「P3 剩餘實測」；deploy backlog DEP-B23 | 部分 |
| P5 | 1 頁 `new-books-only` canary（真 new Source、無 duplicate、Bestseller 與 deploy 無異常）；1 頁 `normal`（exact-one ISBN attach） | 通過；`normal` 的 NULL enrichment 未在真實資料觸發（9 本欄位原本齊全） | canary run `2d933792`、`cab53f56` | 通過（附註） |

## 執行紀錄（Log）

以下依事件發生順序整理；時間只記來源有的。

1. **P2 預先驗證（主 agent 本機）**：在對 production 執行 P2 之前，P2 SQL 與角色 SQL 已在拋棄式 PostgreSQL 17（EF schema、非 superuser 的表擁有者）上驗證。以 `bookfinder_crawler` 執行 crawler 程式，schema preflight、New Source、ISBN attach、touch、榜單替換與 shared migration lock 皆完成；讀 `users`、`CREATE TABLE`、`DELETE FROM books`、`TRUNCATE` 皆被拒絕。
2. **P2 production（#151，2026-10-25）**：使用者以 `bookfinder_crawler` 執行 `p2-crawler-privileges.sql`，角色屬性全為 false、無所屬角色、擁有 0 個物件，各表權限與計畫一致。RDS 版本為 17.11。production 的角色與 SSM 參數值由使用者手動變更（SSM 保留舊版本可回復）。角色建立的執行時間與執行者未記錄。
3. **P3 第一次實測（exit 12）**：runner 以一般 `cat` 讀 EC2 的 `state.json`，deploy host 每次寫入都把它設為 root 0600，SSH 使用者讀不到。修正為 `sudo -n cat --`（#152，2026-10-25）；第一次實測時的 run 編號未記錄。
4. **canary run 1（exit 2）**：`source provider KINGSTONE is disabled or not registered`，未發出任何請求（migration 010 的 seed 為 `enabled = false`）。使用者以主帳號執行 `enable-kingstone.sql` 啟用 provider。run 1 的編號未記錄。
5. **canary run 2（`f03377c2`，FAILED）**：列表頁 3 次皆 `TransportTimeout`（各 30 秒），`every listed page was skipped (1 of 1)`，exit 1，未寫入。隨後在同一主機以 curl 與 image 內的 curl_cffi 各發一次請求，皆回 200，約 1 秒（主 agent 本機觀察為 1～1.5 秒）。判定為暫時性。
6. **P1、P5 第一段（run `2d933792`，new-books-only）**：`SUCCESS`、exit 0、無 alert；6 分 7 秒。使用者唯讀核對 production，結果見「驗證結果」。
7. **P5 第二段（run `cab53f56`，normal）**：同一頁，使用暫時 image `kingstone:canary-normal`（`FROM kingstone:canary` 加 `ENV KINGSTONE_WRITE_POLICY=normal`，未改程式）。`SUCCESS`、exit 0、2 分鐘。使用者核對 production，結果符合期望。
8. **文件與 PR 整理**：#153 於 17:06:15Z 合併；使用者決定寫入政策預設改為 `normal`（計畫決定 #13），#154 於 17:16:47Z 合併。
9. **production-like image（主 agent 本機，#154 之後）**：以 `git archive` 從 `origin/main` `dff2df5` 建置 `book-finder-kingstone:dff2df5`：328 頁、預設政策 `normal`、soft budget 7200、UID 10001、無 playwright。未推送至 registry；CD 推送 `KINGSTONE_CRAWLER_IMAGE` 仍是待辦。
10. **P3 剩餘檢查寫入 backlog（`339b54f`）**：把 tunnel 斷線、SIGTERM、hard limit 與 kill 三項寫成步驟與預期結果，待使用者本機執行。
11. **真站頁面確認（主 agent 本機）**：一次詳細頁抓取確認，書名「長曝光：在中興新村的凝視裡，時間將我們一一顯影1949—1998—」在站上確實以「—」結尾，parser 忠實保留。
12. 本報告的撰寫：只使用 `git`、`gh` 查詢（GitHub API），未執行 crawler、未連線 production、未讀取 `.env`、未存取網站。

## 驗證結果

### Production 核對（使用者執行，唯讀）

- **P2**：`bookfinder_crawler` 角色屬性全為 false、無所屬角色、無 DDL、擁有 0 個物件；7 張表的權限與計畫一致，不需要的表全為 false（#151）。
- **canary `2d933792`（new-books-only）**：`SUCCESS`、exit 0、無 alert；48 張卡、48 個詳細頁、`http_attempts=49`、`http_failures=0`、`parse_error_200_count=0`；`imported=39`、`policy_skipped=9`、`failed=0`；平均約 7.5 秒／請求。KINGSTONE Source 新增 39 筆，`external_id`、URL、Book 皆 39 個不重複；無一書多個 KINGSTONE Source；新書無其他 provider 的 Source；新書 ISBN 不與既有書重複；ISBN、作者、分類、出版社、出版日期、簡介、封面皆 39／39；博客來 Source 與 `bestsellers`（81 列）在 run 時段內 0 變動（backlog CB-07）。
- **canary `cab53f56`（normal）**：`existing_source=39`（只 touch，未重抓詳細頁）、`isbn_attached=9`、`details_fetched=9`、`http_attempts=10`、`imported=0`、`failed=0`。KINGSTONE Source 共 48 筆（新增 9、touch 39）；9 筆皆掛在 canary 前已存在、有博客來 Source 的書上，各 1 個 KINGSTONE Source；每本新增 3 個 KINGSTONE 分類；無重複；無新書；博客來 Source 與 `bestsellers` 未變動。9 本的 `updated_at` 皆未變，因為欄位原本齊全，NULL enrichment 未觸發。

### 假指令與單元測試（PR 本身的 Evidence）

- #149：`pytest deploy/tests .github/scripts/tests` 800 passed、17 skipped（`BOOKFINDER_IT=1` 整合測試）；負向驗證：crawler 端改值時測試失敗、檔案不存在時 `FileNotFoundError`。
- #151：`pytest crawler/tests/test_local_runner.py deploy/tests .github/scripts/tests` 906 passed、17 skipped。
- #152：`test_local_runner.py` 106 passed；修改前新增的斷言失敗（ruff 通過）。真 EC2 上的 sudo 行為由 canary `2d933792` 實際執行時確認（backlog CB-07「P3 已實測的項目」）。
- #154：crawler 完整 pytest 20623 passed、0 skipped；ruff check／format 通過；修改前 4 個預設值測試失敗。

### P3 已實測的項目（canary 中）

EC2 state gate（`sudo -n cat`）、SSM 讀取、URL 改寫、SSH 轉發與 `verify-full`、crawler 帳號的讀寫、UID 10001 寫入 artifacts、container 結束與移除、terminal JSON；失敗的兩次 run 各產生 `ALERT reasons=failed`。

### 未執行

- 本報告 commit 為 docs-only，未執行測試。
- 未重跑 canary、未執行 P3 剩餘三項、未推送 production image、未執行 deploy。
- `KINGSTONE_CRAWLER_IMAGE` 的 CD 推送未做。

## 未解決事項

- **P3 剩餘實測（未做）**：tunnel 中途斷線、SIGTERM（exit 21）、hard limit 與 kill 路徑，步驟見 `crawler/docs/backlog.md` CB-07「P3 剩餘實測」。另外：container 的 `kingstone/last-run.json` 在 SIGTERM 時是否寫出未定義，需記錄實際結果。
- **migration 與 crawler 的互斥（未在 production 實測）**：DEP-B23 的未驗證項（`docker rm -f` 作為 backstop、efbundle 的 SIGTERM 與 `docker kill`）仍保留；deploy 端的 exclusive lock 在下一次 production deploy 後才生效。
- **DEP-B21 殘留風險的文件同步（本分支已修正）**：決定的 commit `922af8c` 在 #149 合併（`b2439e2`）之後才 push，沒有進 main，所以 `deploy/docs/backlog.md` 仍寫「待決策」。本分支以 cherry-pick（`a202ff4`）補上：狀態改為「殘留風險已接受（2026-10-25）」，update-history §3.17 補列。
- **DEP-B20 生效值未驗證**：`client_connection_check_interval` 在 staging 的 efbundle 連線中是否為 `10s`，仍未讀到；RDS 版本已確認為 17.11。
- **runner 的一般 operational failure 沒有 ALERT 與 terminal record**：exit 12（`STATE_UNREADABLE`）、15、16、17、18 目前只 stderr 後直接 exit（#148 review 指出，CB-07 待辦）。Phase 7 第一次 P3 實測時 exit 12 曾實際發生；依 backlog，這類失敗只寫 stderr 並直接 exit。
- **暫時性逾時的觀察**：`f03377c2` 的 3 次 `TransportTimeout` 原因未查明；之後若重複，需比對 container 內外是否同時不通。
- **NULL enrichment 未在真實資料觸發**：`normal` 的 NULL 補欄位只由測試保證（`catalog_core`）。
- **challenge 分類未實作**：真站沒有 challenge fixture；目前以 `unclassified_200` 告警。
- **production image**：`book-finder-kingstone:dff2df5` 只在本機建置，未推送；CD 的 `KINGSTONE_CRAWLER_IMAGE` 推送與 release metadata 待後續。
- **臨時 image 與清單檔**：canary image 是從暫存的程式碼副本 build（清單改為 1 行），repo 的 `crawler/kingstone-pages.txt` 從未修改，不需還原（`origin/main` 為 328 個 URL）。`kingstone:canary`、`kingstone:canary-normal` 仍留在本機，P3 剩餘實測會用到，做完後刪除。
- **博客來 hard limit 3600 秒未量測**：需真站抓取博客來，不在目前授權內，另案。
- **EC2 crawler cron 移除**：另案，目前以 `CRAWLER_ENABLED=false` 停用。
- **排程**：依使用者決定，先手動，不加排程。
- **權限維護**：之後的 migration 若新增 crawler 需要的表或重建既有表，需補 GRANT（schema preflight 不檢查權限）。
- **未記錄**：P2 角色建立的執行者與時間；P3 第一次實測與 canary run 1 的 run 編號；`f03377c2` 的 timeout 詳細原因。

## Code Review 與修正

- GitHub 上 #149、#151、#152、#153、#154 的 review comments（`pulls/{n}/comments`）與 issue comments（`issues/{n}/comments`）均為空，未記錄正式 review 意見。
- 兩軸 review（Standards／Spec）的結果：未記錄。各 PR 只有 `Merge Danger` 區段。
- 實作過程中的修正：
  - #152：第一次 P3 實測發現 state 讀取權限問題，直接以 `sudo -n` 修正（同 PR）。PR 內文當時寫「真 EC2 上的 sudo 行為待確認」，之後由 canary 確認。
  - #151、#152、#154：合併 main 時有文件衝突（`crawler/docs/backlog.md`、`update-history.md` 等），已在 merge commit 解決。
  - #154：寫入政策預設由 `new-books-only` 改為 `normal`；`cli.py`、`run.py` 只更新說明註解。
- 本報告撰寫時的文件核對（未修正，見「未解決事項」）：
  - DEP-B21 的狀態與 PR #149 內文不一致：本分支已補上（見上）。
  - v12 §10 的 P3 條目沒有狀態標示；狀態只記在 `crawler/docs/backlog.md`（部分完成）。
