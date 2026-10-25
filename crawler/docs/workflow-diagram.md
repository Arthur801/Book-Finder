# Crawler 工作流程

> 整理日期：2026-10-26；現況基準 `a0decb6d817bbbb094efdbfc9a3eff590679c2b9`。開始時工作樹乾淨；本次僅修改本目錄五份文件並做文件靜態檢查，未執行應用測試、build、migration、部署或真實抓取。先前測試與 canary 紀錄屬歷史證據，未於本次重跑。

## 入口

[文件權責](../../AGENTS.md)、[名詞](../../CONTEXT.md)、[架構](architecture.md)、[測試案例](test-suite.md)。root `Docs/` 的舊 crawler／data-model／deployment／test-plan 連結與裸章節號皆為歷史參考，不能覆蓋本目錄 active docs。

| 入口 | 程式與責任 |
|---|---|
| `python -m books_crawler` | [cli](../books_crawler/cli.py) → `run_once`，每日總榜 |
| `python -m books_crawler.first_book` | [first_book](../books_crawler/first_book.py) → `run_first_book`，只匯入第一名 |
| `python -m books_crawler.pages` | [pages](../books_crawler/pages.py) → `run_pages`，分類補書 |
| `python -m kingstone` | [cli](../kingstone/cli.py) → `run_pages`，金石堂分類列表頁（KINGSTONE，CB-07 Phase 5）；清單檔 `crawler/kingstone-pages.txt`；流程見下方「金石堂入口」 |
| `python -m books_crawler.inspect_page URL` | [inspect_page](../books_crawler/inspect_page.py)，單頁 browser 診斷，無 DB、不重試 |
| EC2 wrapper daily／pages／first_book | [EC2 wrapper](../deploy/run-crawler.sh)，serialization／maintenance locks、state gate、SSM、Docker 與排程 |

## 每日總榜（現行實作）

```mermaid
flowchart TD
 A[CLI 驗證 DB URL 與 fetcher 設定] --> B{有效}
 B -->|否| Z[exit 2 不請求]
 B -->|是| C[建立 fetcher 總榜 fetch 最多三次]
 C --> D{parse 並驗證唯一 URL 與 rank 1 到 100}
 D -->|失敗| F[FAILED 舊榜保留]
 D -->|成功| E[依 rank resolve；Catalog 先 commit，RunLedger 決定 RankingDecision]
 E --> G{連續一般錯誤超過 20}
 G -->|是| F
 G -->|否且還有列| E
 G -->|否且完成| H[交易內檢查 source ownership]
 H --> I[DELETE 舊榜 INSERT snapshot]
 I -->|rollback| F
 I -->|commit| J[SUCCESS 或 PARTIAL_SUCCESS exit 0]
 F --> K[CLI finally 關閉 fetcher]
 J --> K
```

來源：[run](../books_crawler/run.py)、[ranking](../books_crawler/ranking.py)、[ledger](../books_crawler/ledger.py)、[catalog_core/persistence](../catalog_core/persistence.py)、[db](../books_crawler/db.py)，規格 §5～§6、§13～§14、§16。總榜 fetch 失敗才重試；parse／完整性錯誤不重試且在開 DB 前失敗。輸入須 100 列，輸出可缺號甚至空 snapshot；空榜仍替換是已定規則。first-book 仍驗證 100 列，只 resolve rank 1，不替換榜單；一般失敗 FAILED，限制級 PARTIAL_SUCCESS。榜內重複（DUPLICATE_BOOK）在 Catalog 寫入之後由 RunLedger 決定，記為跳過與一般錯誤，不重試。

## 共用單列管線

本流程由 `catalog_core.service.resolve_item` 實作（provider-neutral）；Books 只提供 fetch／parse callback（`books_crawler/run.py` 的 `_fetch_and_parse`）與 log 行（rank 欄位、限制級、attempt、identity warning、ISBN 附加）。下圖即兩者合起來的行為。寫入政策（`write_policy`，預設 `NORMAL`）只在 NEW 路徑的 ISBN 比對後生效：Books 永遠使用 `NORMAL`，因此圖中的「政策跳過」分支不會出現在 Books；金石堂 run 才可能走到它（見下方「金石堂逐頁 run」）。

```mermaid
flowchart TD
 CI_START["解析 provider、URL 與 external_id 身分"] --> CI_ID{"身分結果"}
 CI_ID -->|CONFLICT| CI_CONFLICT["source_identity_conflict；不抓不寫不重試"]
 CI_ID -->|EXISTING| CI_TOUCH["依 mode 決定是否 touch；不抓 detail"]
 CI_TOUCH -->|無匹配 Source| CI_CONFLICT
 CI_TOUCH -->|成功或不需 touch| CI_ACCEPT["回傳 Catalog resolution"]
 CI_ID -->|NEW| CI_DETAIL["fetch detail 並 parse"]
 CI_DETAIL -->|Books 限制級會員頁| CI_RESTRICT["skip；不重試；歸零錯誤"]
 CI_DETAIL -->|可重試錯誤| CI_RETRY{"共用 attempt 未耗盡"}
 CI_RETRY -->|是| CI_WAIT["等待 1 或 2 秒"]
 CI_WAIT --> CI_DETAIL
 CI_RETRY -->|否| CI_FAIL["單列失敗；記一次一般錯誤"]
 CI_DETAIL -->|draft| CI_ISBN["ISBN 正規化；查 distinct Book"]
 CI_ISBN --> CI_POLICY{"寫入政策與命中數"}
 CI_POLICY -->|new-books-only 且恰一本| CI_SKIP["政策跳過；不 persist、不 enrichment"]
 CI_POLICY -->|normal 或零本或至少兩本| CI_WRITE["每書 transaction；建立或附加 Source"]
 CI_WRITE -->|commit| CI_ACCEPT
 CI_WRITE -->|DB 錯誤且尚有 attempt| CI_DB_RETRY["保留 draft；等待；必要時重連；重新解析身分"]
 CI_DB_RETRY -->|EXISTING| CI_ACCEPT
 CI_DB_RETRY -->|CONFLICT| CI_CONFLICT
 CI_DB_RETRY -->|NEW| CI_ISBN
 CI_WRITE -->|三次耗盡| CI_FAIL
 CI_ACCEPT --> CI_MODE{"呼叫端模式"}
 CI_MODE -->|daily| CI_RANK["RunLedger 決定排名；此時 Catalog 已 commit"]
 CI_RANK -->|重複 Book| CI_FAIL
 CI_RANK -->|接受| CI_SUCCESS["成功並歸零錯誤"]
 CI_MODE -->|first_book 或 pages| CI_SUCCESS
```

已存在的 Source 以 `touch_source(provider, source_id, now)` 更新 `last_seen_at`：寫成 `GREATEST(last_seen_at, now)`，且只作用於本 provider（BOOKS_COM_TW）的該 Source。時鐘倒退不會把時間往回拉；touch 匹配不到列時拋 `SourceTouchConflict`，本列記為 `source_identity_conflict` 跳過，不重試、不抓詳細頁；資料庫錯誤仍照三次重試。

fetch／parse／write 共用最多三次嘗試。ISBN lookup 失敗也沿用 draft，在有限 attempt 內重試；圖中略去此回邊。已知 URL 的 `find_source` DB 例外在 retry 外，整次失敗。重複 Book 確定性 skip，不重試，已知 URL 正常成功 attempts=0、ISBN 重複記實際次數。限制級、重用、附加、成功都重設 streak；20 本仍繼續，第 21 本終局一般錯誤才中止，累計錯誤無上限。每書已 commit Catalog 保留；替換交易保護舊榜與既有來源時間。

## Pages 與其他入口

```mermaid
flowchart TD
 A[讀取清單 去重與驗證] -->|無效或空| B[exit 2 不建立 fetcher]
 A -->|有效| C[依序逐頁 fetch 最多三次]
 C -->|失敗| D[skip page]
 C -->|成功| E[parse 不要求 100 列]
 E -->|ValueError| D
 E -->|成功含零列| F[逐列共用 resolver ranked 為空]
 F --> G[PagesLedger 無連續錯誤上限]
 D --> H{還有頁}
 G --> H
 H -->|是| C
 H -->|否| I{全部頁 skip 或有逸出例外}
 I -->|是| J[FAILED 已 commit Catalog 保留]
 I -->|否| K[SUCCESS 或 PARTIAL_SUCCESS]
```

Pages 不保存分類 rank／Bestseller、不刷新既有來源時間；新來源仍初始化 `last_seen_at=now`（CB-01 已結案）。空成功解析頁不是 skipped page；直接 `run_pages(deps, [])` 成功，但 CLI 空清單拒絕。

## EC2 wrapper 與 deployment coordination（保留的執行路徑）

來源：[EC2 wrapper](../deploy/run-crawler.sh)、[部署架構](../../deploy/docs/architecture.md)、[操作說明](../deploy/README.md)。這是保留的 EC2 路徑；目前使用者操作入口為下方本地 runner。三個 mode 共用 `run.lock`；與本地 host 的鎖不是同一把。

```mermaid
flowchart TD
 H[驗證 mode、必要設定與可選 CA bundle] --> ENABLED{CRAWLER_ENABLED}
 ENABLED -->|false| DISABLED[exit 0；skipped=disabled]
 ENABLED -->|非法值| CONFIG[exit 2]
 ENABLED -->|true 或未設定| MODELOCK[取得 crawler run.lock；三個 mode 共用]
 MODELOCK --> MAINT[取得 DB maintenance shared lock；預設等待7200秒]
 MAINT -->|等待失敗| BUSY[exit 3；不讀 state、不啟動 Docker]
 MAINT -->|取得後| STATE{deployment state.json 存在}
 STATE -->|不存在| LEGACY[保留 pre-CD state 行為；仍持有 shared lock]
 STATE -->|存在| READ[讀取 JSON 與 gate 欄位]
 READ -->|讀取或解析失敗| CLOSED[exit 2；fail closed，不啟動 Docker]
 READ -->|可讀| PAUSE{crawler.paused 非 null}
 PAUSE -->|是| SKIP[exit 6；不啟動 Docker]
 PAUSE -->|否| DIRTY{schema.dirty 為 true}
 DIRTY -->|是| SKIP
 DIRTY -->|否| SCHED{pages --scheduled 且有成功時間}
 LEGACY --> SCHED
 SCHED -->|時間非整數| BAD[exit 2；不啟動 Docker]
 SCHED -->|未滿259200秒| NOTDUE[exit 0；本次不執行]
 SCHED -->|到期或無須判斷| ENV[建立600暫存 env；安裝 EXIT cleanup]
 ENV --> SSM[SSM 取專用 DB secret；不輸出值]
 SSM --> DOCKER[Docker run；持有 crawler lock 與 maintenance shared lock]
 DOCKER --> RESULT{pages 且 container exit 0}
 RESULT -->|是| UPDATE[原子更新 pages-last-success 為本次啟動時間]
 RESULT -->|否| KEEP[不前移 pages schedule state]
 UPDATE --> EXIT[保留 container exit；cleanup secret；shell 結束釋放鎖]
 KEEP --> EXIT
```

順序必須是 crawler serialization lock → DB maintenance shared lock → deployment state gate → pages schedule gate → SSM → Docker。Deploy migration 取得同一 maintenance lock 的 exclusive lock；先拿 shared lock 再讀 state，避免讀完 clean state 後 deploy 才 pause／migration、crawler 卻用舊讀值啟動的 race。Shared lock 持有至 Docker 執行結束；不能在 state gate 後提前釋放。

`DB_MAINTENANCE_LOCK` 預設 `/var/lib/book-finder/db-maintenance.lock`，`DB_MAINTENANCE_WAIT_S` 預設 `7200`，`BOOKFINDER_STATE_FILE` 預設 `/var/lib/book-finder/state.json`。`crawler.paused != null` 即跳過；否則檢查 `schema.dirty is True`。這是 wrapper 所讀欄位的 gate，不是完整 host state schema validator。State 不存在只保留舊 state 行為，並未略過 maintenance lock；state 存在但不能讀／解析或缺少 gate 所需欄位則 fail closed。

Paused／dirty exit 6、maintenance timeout exit 3、state 無法解析 exit 2 都在 SSM／Docker 前結束，不更新 pages 成功時間。正常啟動後維持 `--rm --pull=never`、curl、artifact bind mount、container exit passthrough 與 secret cleanup。Cron UTC 20:00／21:00 對應台灣 04:00／05:00；72h 從上次 pages exit 0 的啟動時間計算。以上是程式／測試來源證據，並非 EC2／SSM／正式部署驗證。

Fetcher 每次含首次／重試以 3～30 秒目標循序節流，解析／DB／backoff 抵扣已耗時間；實際可超過 30 秒。無 redirect、保留 TLS。challenge、連線異常頁、非 200／request error 為 FetchError，不切換 adapter；browser 啟動失敗整次 FAILED。不具應用層取消協定。診斷 curl 存原始 HTML 與選定 JSON，browser 加 PNG；診斷失敗不覆蓋原錯誤，inspect_page 一次請求無 DB。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。

## 本地 runner（`deploy/local/`，Phase 6 M4）

入口：`deploy/local/run-local-crawler.sh daily|first_book|pages|kingstone`（使用者在本機手動執行，不經 cron）。順序與 exit code 的完整說明見 [deploy README](../deploy/README.md) §9。

```mermaid
flowchart TD
 LR_START(["手動執行四種 mode 之一"]) --> LR_CONF["讀取本地設定"]
 LR_CONF --> LR_ENABLED{"CRAWLER_ENABLED"}
 LR_ENABLED -->|false| LR_DISABLED["exit 0；skipped=disabled"]
 LR_ENABLED -->|非法值或設定錯誤| LR_CONFIG["exit 10"]
 LR_ENABLED -->|true 或未設定| LR_VALIDATE["驗證必要設定、CA 與 artifacts 權限"]
 LR_VALIDATE -->|無效| LR_CONFIG
 LR_VALIDATE --> LR_LOCK{"取得本地共用 run.lock"}
 LR_LOCK -->|busy| LR_BUSY["exit 11"]
 LR_LOCK -->|取得| LR_STATE["SSH sudo -n cat 讀 EC2 state"]
 LR_STATE -->|讀取或解析失敗| LR_STATE_ERR["exit 12"]
 LR_STATE -->|paused 或 dirty| LR_SKIP["exit 6"]
 LR_STATE -->|clean| LR_ORPHAN{"Docker writer 狀態"}
 LR_ORPHAN -->|Docker 不可用| LR_DOCKER_ERR["exit 18"]
 LR_ORPHAN -->|仍運作| LR_ORPHAN_ERR["ORPHAN_WRITER；record 與 ALERT；exit 13"]
 LR_ORPHAN -->|已停止| LR_REMOVE["移除舊 container"]
 LR_REMOVE -->|失敗| LR_DOCKER_ERR
 LR_REMOVE --> LR_SECRET["SSM 或受限檔案讀取 DB secret"]
 LR_ORPHAN -->|不存在| LR_SECRET
 LR_SECRET -->|失敗| LR_SECRET_ERR["exit 15"]
 LR_SECRET --> LR_URL["改寫 URL；verify-full；600 env file"]
 LR_URL -->|失敗| LR_URL_ERR["exit 17"]
 LR_URL --> LR_TUNNEL["建立 SSH tunnel 並等待本機埠"]
 LR_TUNNEL -->|失敗或逾時| LR_TUNNEL_ERR["exit 16"]
 LR_TUNNEL --> LR_RUN["啟動唯一命名 container；watchdog 每秒檢查"]
 LR_RUN -->|正常結束且已停止| LR_RESULT["保留 container exit code"]
 LR_RUN -->|hard limit、signal 或 client lost| LR_STOP["unpause 如需要；stop；必要時 kill"]
 LR_STOP --> LR_CONFIRM{"確認 writer 已停止"}
 LR_CONFIRM -->|否| LR_UNCONFIRMED["保留 container；record 與 ALERT；exit 14"]
 LR_CONFIRM -->|是| LR_RECORD["record 與 ALERT；hard limit 20、signal 21、client lost 22"]
 LR_RECORD --> LR_RM["移除已停止 container"]
 LR_RESULT --> LR_RM
 LR_RM --> LR_CLEAN["EXIT cleanup：關 tunnel、刪 env 與 cidfile、釋放鎖"]
 LR_UNCONFIRMED --> LR_CLEAN
 LR_STATE_ERR --> LR_CLEAN
 LR_SKIP --> LR_CLEAN
 LR_DOCKER_ERR --> LR_CLEAN
 LR_ORPHAN_ERR --> LR_CLEAN
 LR_SECRET_ERR --> LR_CLEAN
 LR_URL_ERR --> LR_CLEAN
 LR_TUNNEL_ERR --> LR_CLEAN
 LR_CLEAN --> LR_END(["回傳既定 exit code"])
```

圖中 record 指 runner 的 lifecycle record；一般 operational failure（12、15～18）目前沒有 terminal JSON／ALERT，改善列於 CB-07。INT／TERM 在 container 啟動前另走 `SIGNAL_STOP`（21）後 cleanup；SIGKILL 無法保證 trap 執行。

Invocation order（本地）：

1. 讀 `CRAWLER_LOCAL_CONF`。`CRAWLER_ENABLED` 先於其他驗證：`false` → `skipped=disabled`、exit 0、無任何外部工作；其他值非法 → exit 10。必要值與格式、CA bundle（一般可讀檔案、others-read 位元須開啟，建議 `0644`、非 symlink）、artifacts 目錄（owner 10001 或 world-writable）驗證失敗 → exit 10。
2. 本地 `run.lock`，非阻塞，所有 mode 共用；已被持有 → exit 11。
3. SSH 唯讀讀取 EC2 `state.json`（`BatchMode=yes`，遠端以 `sudo -n cat --` 讀取，因為 deploy host 把檔案寫成 root 0600；`python3 -I` 判定，與 `run-crawler.sh` 同規則）：paused／dirty → `skipped=…`、exit 6；讀不到或檔案不存在 → exit 12（fail closed）。
4. Orphan check：`docker ps -a --filter label=com.bookfinder.role=catalog-crawler`。running／restarting／paused／removing → `ORPHAN_WRITER`、exit 13，不取 secret；exited／dead／created → `docker rm` 後繼續；docker 不可用 → exit 18。
5. DB secret：`DB_SECRET_SOURCE=ssm`（`aws ssm get-parameter --with-decryption --profile`）或 `file`（600、owner 為自己、非 symlink）；空值 → exit 15。secret 只經 stdin 與 bash 變數傳遞，不進 argv、log 或 env。
6. 改寫連線字串（`runner_support.py rewrite-url`）：保留 userinfo 與 path（不解碼），host 必須等於 `RDS_ENDPOINT`（否則 exit 17），port 換成 `LOCAL_DB_PORT`，加上 `hostaddr=127.0.0.1`、`sslmode=verify-full`、`sslrootcert=/etc/book-finder/rds-ca-bundle.pem`；寫入 600 的 env file（只含 `DATABASE_URL`，mktemp 建立）。
7. 開 tunnel：`ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o BatchMode=yes -L 127.0.0.1:<port>:<RDS>:5432 <alias>`（背景）；以 `python3 -I` 檢查本機埠，上限 `TUNNEL_WAIT_SECONDS`；ssh 先退出或逾時 → exit 16。
8. 啟動 container：`docker run --rm=false --pull=never --init --network host --name book-finder-crawler-active`，labels `com.bookfinder.role`／`mode`／`provider`，`--cidfile`、`--env-file`，artifacts 與 CA 的 bind mount（CA 唯讀）。kingstone 使用 `KINGSTONE_CRAWLER_IMAGE`、預設 CMD，並傳入 `CRAWLER_RUN_HARD_LIMIT_SECONDS`；博客來使用 `CRAWLER_IMAGE` 與對應 module，傳入 `CRAWLER_FETCHER=curl`。
9. Watchdog：`docker run` 客戶端存活期間每秒檢查，觸發條件為超過 hard limit、收到 INT／TERM，或客戶端已結束但 container 仍在運作。流程為 `docker stop -t <grace>`（paused 先 `docker unpause`）→ 仍在運作則 `docker kill` → 以 `docker ps` 確認；absent、exited、dead、created 才算已停止。確認失敗 → `ORPHAN_WRITER`、exit 14，不 `rm`，下一次啟動於步驟 4 被擋下。確認停止 → exit 20（hard limit）、21（signal）或 22（客戶端已結束而 container 仍運作，`CLIENT_LOST`）。
10. 正常結束：確認 container 已非運作後 `docker rm`，回傳 container 的 exit code（0、1、2，或 Docker 自身的其他值原樣傳回）。
11. 清理（EXIT trap，所有路徑含錯誤與 signal）：關閉 tunnel（kill 後 wait）、刪除 env file 與 cidfile；fd 9 關閉即放鎖。子程序以 `9>&-` 不繼承鎖。

失敗路徑的告警與紀錄（runner 端）：

| 路徑 | stderr | record `reason`（exit） |
|---|---|---|
| 步驟 4，startup orphan | `ALERT reasons=orphan` | `ORPHAN_WRITER`（13） |
| 步驟 9，watchdog 因 hard limit 停止成功 | `ALERT reasons=hard_limit` | `HARD_LIMIT`（20） |
| 步驟 9，hard limit 觸發且無法確認停止 | `ALERT reasons=orphan,hard_limit` | `ORPHAN_WRITER`（14） |
| 步驟 9，signal 或客戶端結束時無法確認停止 | `ALERT reasons=orphan` | `ORPHAN_WRITER`（14） |
| 步驟 9，signal 停止成功 | `ALERT reasons=signal_stop` | `SIGNAL_STOP`（21） |
| signal 於 container 啟動前 | `ALERT reasons=signal_stop` | `SIGNAL_STOP`（21） |
| 客戶端結束但 container 仍在運作，且已停止 | `ALERT reasons=orphan` | `CLIENT_LOST`（22） |
| container 正常結束（0、1、2） | 無 | 無（由 container 的結果負責） |

record 寫入 `artifacts/runner/<mode>-last-run.json`（原子寫入，UTC 時間，不含 secret），同一份 JSON 印在 stdout。寫入失敗只印 `WARNING`，exit code 不變。

Writer fencing 只依 container 名稱與 label 判定：同一時間最多一個 `book-finder-crawler-active`；provider 與 mode 只作為 label，不分別建立鎖。

來源：[run-local-crawler.sh](../deploy/local/run-local-crawler.sh)、[runner_support.py](../deploy/local/runner_support.py)。測試：[test_local_runner.py](../tests/test_local_runner.py)（CR-T20）。

## 金石堂入口（`python -m kingstone`，Phase 5 M2；產物與 ALERT，Phase 6 M5）

```mermaid
flowchart TD
 KS_START(["python -m kingstone"]) --> KS_LOG["設定 stdout logging"]
 KS_LOG --> KS_ENV{"Unicode、DATABASE_URL 與 config 有效"}
 KS_ENV -->|否| KS_EARLY["exit 2；無 terminal record"]
 KS_ENV -->|是| KS_REC["建立 recorder；載入與驗證清單"]
 KS_REC -->|清單無效| KS_CONFIG["pre-run FAILED；exit 2"]
 KS_REC -->|有效| KS_PROVIDER{"查詢 KINGSTONE enabled"}
 KS_PROVIDER -->|DB 查詢錯誤| KS_FAIL["pre-run FAILED；exit 1"]
 KS_PROVIDER -->|停用或未註冊| KS_CONFIG
 KS_PROVIDER -->|True| KS_SESSION["建立 SoftBudget 與 DatabaseSession"]
 KS_SESSION --> KS_LOCK{"首次連線取得 shared migration lock"}
 KS_LOCK -->|busy| KS_BUSY["MAINTENANCE_BUSY；exit 1"]
 KS_LOCK -->|連線或 SQL 錯誤| KS_FAIL
 KS_LOCK -->|成功| KS_SCHEMA{"唯讀 schema preflight"}
 KS_SCHEMA -->|SQL 錯誤| KS_FAIL
 KS_SCHEMA -->|缺少必要 schema| KS_MISSING["SCHEMA_PREREQUISITE_MISSING；exit 2"]
 KS_SCHEMA -->|符合| KS_FETCHER["建立 KingstoneFetcher 與 SessionCatalogStore"]
 KS_FETCHER --> KS_RUN["run_pages；同一 budget 傳給 fetcher"]
 KS_RUN --> KS_CLOSE["finally 關閉 fetcher；離開 session 關閉連線"]
 KS_CLOSE --> KS_REPORT["report：SUCCESS 或 PARTIAL_SUCCESS 為 0；FAILED 為 1"]
 KS_REPORT --> KS_PUBLISH["發布 terminal record；詳見產物圖"]
 KS_CONFIG --> KS_PUBLISH
 KS_FAIL --> KS_PUBLISH
 KS_BUSY --> KS_PUBLISH
 KS_MISSING --> KS_PUBLISH
 KS_PUBLISH --> KS_EXIT(["回傳既定 exit code"])
```

金石堂 terminal 結果的產物與 ALERT（Phase 6 M5）：

```mermaid
flowchart TD
 AR_TERM(["run report 或 config 載入後的 pre-run 結果"]) --> AR_FINAL["finalize：讀取本次之前的 history"]
 AR_FINAL --> AR_ALERT["計算 failed、schema、busy、unclassified_200、zero-card 與 streak reasons"]
 AR_ALERT --> AR_REDACT["加入 alert_reasons；全部字串 redact"]
 AR_REDACT --> AR_STDOUT["stdout 印出一行最終 JSON"]
 AR_STDOUT --> AR_WRITE["同一份 record 原子寫入 last-run.json"]
 AR_WRITE -->|成功| AR_HISTORY["寫入 history 摘要；最多保留 20 份"]
 AR_WRITE -->|失敗| AR_ERROR["log ERROR；保留原 exit code"]
 AR_HISTORY -->|寫入或修剪失敗| AR_ERROR
 AR_HISTORY -->|成功| AR_CHECK{"alert_reasons 非空"}
 AR_ERROR --> AR_CHECK
 AR_CHECK -->|是| AR_WARN["log WARNING：ALERT reasons 與 last_run 路徑"]
 AR_CHECK -->|否| AR_END(["回傳原 exit code"])
 AR_WARN --> AR_END
 AR_FINAL -->|非預期例外| AR_FINAL_ERR["log ERROR；本次不發布 record；保留原 exit code"]
 AR_FINAL_ERR --> AR_END
 subgraph AR_DIAG["run 中途的獨立診斷分支"]
 AR_PARSE["列表或詳細頁 KingstoneParseError"] --> AR_SAVE["save_html：UTF-8 限額與最多 20 份"]
 AR_SAVE -->|寫入失敗| AR_DIAG_WARN["log WARNING；run 繼續"]
 AR_OTHER["soft 404 或 acquisition failure"] --> AR_NO_SAVE["不存診斷 HTML"]
 end
```

- config 載入後的 pre-run 結果（清單無效、provider 停用）也寫 last-run，`pages_not_reached` 為 null，不計入 streak。
- challenge 的 alert 尚未細分（沒有 fixture 可判定）；目前 challenge 落在 `unclassified_200`，見 backlog CB-07。runner 端的 orphan alert 屬 Phase 6 M4。
- stdout 的 JSON 行與 log 行分開：log 有時間戳前綴，不以 `{` 開頭；取出 JSON 時讀以 `{` 開頭的行。

- 「停用」與「未註冊」都是設定錯誤（exit 2），都不建立 fetcher、不發出請求。
- shared lock 或 schema preflight 失敗時 fetcher 尚未建立，沒有 HTTP、沒有寫入。
- Exit 1 來自 provider 查詢、連線或 busy 失敗與 run 的 FAILED（包括清單所有頁都被跳過，以及 run 中途遇到 migration lock busy）。
- `CRAWLER_RUN_HARD_LIMIT_SECONDS` 只被讀取與驗證；強制終止由本地 runner watchdog 執行（Phase 6 M4，見「本地 runner」），本入口不計時、不殺程序。
- 來源：[cli](../kingstone/cli.py)、[run](../kingstone/run.py)、[config](../kingstone/config.py)、[page_list](../kingstone/page_list.py)、[persistence](../catalog_core/persistence.py)（`provider_enabled` 與 `missing_schema_prerequisites` 為讀取；寫入由 run 經 store 呼叫）。

## DB session 與 migration lock（所有 provider，Phase 6 M2）

```mermaid
flowchart TD
 DB_ACCESS(["存取 DatabaseSession.conn"]) --> DB_VALID{"既有連線存在且未 closed 或 broken"}
 DB_VALID -->|是| DB_READY["交出既有連線"]
 DB_VALID -->|否| DB_CLOSE["關閉舊 context；清除連線參照"]
 DB_CLOSE --> DB_CONNECT["connect；autocommit"]
 DB_CONNECT -->|連線失敗| DB_ERROR["原樣拋出；由呼叫端決定處理"]
 DB_CONNECT --> DB_LOCK{"pg_try_advisory_lock_shared 2026102501"}
 DB_LOCK -->|psycopg.Error 或其他例外| DB_LOCK_ERR["關閉該連線；原樣拋出"]
 DB_LOCK -->|False| DB_BUSY["關閉該連線；拋 MigrationLockBusy"]
 DB_LOCK -->|True| DB_READY
 DB_READY --> DB_IO["呼叫端執行查詢或顯式 transaction 寫入"]
 DB_IO -->|下一次存取| DB_ACCESS
 DB_IO -->|run 結束或連線關閉| DB_RELEASE(["session-level shared lock 隨連線釋放"])
```

- Lock 是 session-level：連線關閉即釋放；因此 migration（deploy 端的 exclusive holder）存在時，crawler 不能開始寫入，而寫入中的連線若被切斷，重連時必須重新取得。
- Books：`run_once`、`run_first_book`、`run_pages` 的 `MigrationLockBusy` 落在各自的 `except Exception`，run 以 FAILED 結束，error 含 `migration lock busy`；已 commit 的 Book 保留，其他列不變。
- 金石堂：首次連線 busy → 入口 exit 1；run 中途 busy → `run_pages` 的 fatal → FAILED，exit 1；已 commit 的 Book 保留，下次 replay。
- 本節只描述 crawler 端。deploy 端以存活的 lock session 持有 exclusive lock（`deploy/host/bookfinder_host/`，Phase 6 M3），見 deploy/docs。
- 來源：[session](../catalog_core/session.py)、[migration_lock](../catalog_core/migration_lock.py)、[store](../catalog_core/store.py)；測試 CR-T19。

## 金石堂逐頁 run（Phase 4 M2）

caller：`kingstone.cli.main`（Phase 5 M2），組裝見上節。詳見 [architecture](architecture.md)「Run（逐頁流程）」。

```mermaid
flowchart TD
 KR_START(["run_pages"]) --> KR_INIT["清單依原順序去重；建立 ledger"]
 KR_INIT --> KR_NEXT{"還有列表頁"}
 KR_NEXT -->|否| KR_REPORT["依 ledger 建立 terminal report"]
 KR_NEXT -->|是| KR_BUDGET{"soft budget 耗盡"}
 KR_BUDGET -->|是| KR_STOP["stop_for_budget；剩餘頁 not reached"]
 KR_BUDGET -->|否| KR_FETCH["fetch_list_page；HTTP 層有限重試"]
 KR_FETCH -->|BUDGET_EXHAUSTED| KR_STOP
 KR_FETCH -->|其他 AcquisitionError| KR_SKIP["record_page_skipped"]
 KR_FETCH -->|取得 HTML| KR_PARSE["parse_list_html"]
 KR_PARSE -->|KingstoneParseError| KR_DIAG["保存有限額診斷 HTML"]
 KR_DIAG --> KR_SKIP
 KR_SKIP --> KR_NEXT
 KR_PARSE -->|成功含零卡| KR_PAGE["page_started；累計 items_listed"]
 KR_PAGE --> KR_CARD{"還有卡片"}
 KR_CARD -->|否| KR_COMPLETE["page_completed"]
 KR_COMPLETE --> KR_NEXT
 KR_CARD -->|是| KR_ITEM_BUDGET{"soft budget 耗盡"}
 KR_ITEM_BUDGET -->|是| KR_INTERRUPT["stop_for_budget；本頁 interrupted"]
 KR_ITEM_BUDGET -->|否| KR_RESOLVE["resolve_item；provider、URL、km_code 身分解析"]
 KR_RESOLVE -->|EXISTING| KR_TOUCH["touch；不抓 detail"]
 KR_RESOLVE -->|CONFLICT| KR_CONFLICT["確定性失敗；不抓不寫"]
 KR_RESOLVE -->|NEW；重試已有 draft 則沿用| KR_DRAFT["取得 draft；首次抓取與解析 detail、驗證 km_code；DB 重試沿用 draft"]
 KR_DRAFT -->|detail budget 耗盡| KR_BUDGET_FAIL["記該卡 budget_exhausted 失敗"]
 KR_BUDGET_FAIL --> KR_INTERRUPT
 KR_DRAFT -->|其他 acquisition、soft 404 或 parse 失敗| KR_ITEM_FAIL["記該卡失敗；不在 service 重抓"]
 KR_DRAFT -->|draft| KR_ISBN{"ISBN distinct Book 命中數與政策"}
 KR_ISBN -->|new-books-only 且恰一本| KR_POLICY["ItemPolicySkipped；不 persist、不 enrichment"]
 KR_ISBN -->|normal 或零本或至少兩本| KR_PERSIST["每書 transaction：建立或附加 Source"]
 KR_PERSIST -->|commit| KR_RECORD["record_item"]
 KR_PERSIST -->|DB 可重試且尚有 attempt| KR_RETRY["等待 1 或 2 秒；保留 draft；重新解析 identity"]
 KR_RETRY --> KR_RESOLVE
 KR_PERSIST -->|三次耗盡| KR_ITEM_FAIL
 KR_TOUCH --> KR_RECORD
 KR_CONFLICT --> KR_RECORD
 KR_POLICY --> KR_RECORD
 KR_ITEM_FAIL --> KR_RECORD
 KR_RECORD --> KR_CARD
 KR_STOP --> KR_REPORT
 KR_INTERRUPT --> KR_REPORT
 KR_RESOLVE -->|identity 查詢或其他逸出例外| KR_FATAL["fatal；report.error；保留已 commit Catalog"]
 KR_FATAL --> KR_REPORT
 KR_REPORT --> KR_STATUS{"fatal 或無有效進度"}
 KR_STATUS -->|是| KR_FAILED["FAILED；exit 1"]
 KR_STATUS -->|否；有 skip、failed、interrupted 或 not reached| KR_PARTIAL["PARTIAL_SUCCESS；exit 0"]
 KR_STATUS -->|否；全部完成| KR_SUCCESS["SUCCESS；exit 0"]
 KR_FAILED --> KR_END(["回傳 KingstoneReport"])
 KR_PARTIAL --> KR_END
 KR_SUCCESS --> KR_END
```

- 呼叫端責任：組裝 `KingstoneRunDependencies`（含 `write_policy`，無預設值；config 的預設為 `normal`，Phase 7 起）；把同一個 `SoftBudget` 交給真 fetcher（`budget_remaining=budget.remaining`）；注入 `clock`、`sleep` 與 `run_id`。
- 重跑（replay）：同一份清單再跑一次。Existing 只 touch；未完成的 New 才抓詳細頁。政策跳過的書沒有 Source，因此下一次 run 仍是 New，會再抓一次詳細頁。
- `new-books-only` 的全部政策跳過 run 是合法 SUCCESS，但零寫入：報告以 `write_policy`、`policy_skipped` 與 `zero_progress_reason=null` 與真正零進度區分；它不能作為 promotion 到 `normal` 的證據。
- 圖中省略的 service retry：EXISTING touch 與 NEW 的 ISBN 查詢遇到 `psycopg.Error` 也按最多三次嘗試處理；identity 首次查詢例外與 `MigrationLockBusy` 逸出時為 fatal。詳細語意見 [service](../catalog_core/service.py) 與 CR-T17／CR-K08。
- 結果：`KingstoneReport`；一行 INFO `mode=kingstone …`；FAILED 另有一行 ERROR。exit code 由 `report.exit_code` 決定，由 `kingstone.cli` 回傳（Phase 5 M2）；hard limit 的強制執行由 runner 負責（Phase 6）。
- 報告的計數（Phase 6 M5）：`items_listed`（已解析列表頁的卡片數）、`details_fetched`（每次要求詳細頁抓取即計，失敗也計）、`http_attempts`／`http_failures`（fetcher 送出的請求與沒有可用 body 的請求）。它們與其他欄位一起進入 `last-run.json`（見「金石堂入口」下方的產物流程）。

