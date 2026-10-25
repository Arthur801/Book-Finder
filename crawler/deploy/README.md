# Crawler：GHCR → CD 管理 digest → EC2 → cron

此流程使用主機 cron 啟動一次性的 Docker container。`run_once` 每天執行，`run_pages` 每三天執行；程式入口與 parser 不需再修改。以下從 repository 根目錄執行本機指令，EC2 指令另行標示。

> 正式部署（image 發布、digest 寫入 `crawler.conf`、腳本與排程更新）由 CD 負責，流程與人工程序見 [`deploy/README.md`](../../deploy/README.md)。本文件只保留本機建置、EC2 前置條件、首次安裝與爬蟲的運行規則。

## 1. Dockerfile 與本機驗證

`crawler/Dockerfile` 使用 `python:3.14-slim-bookworm`，只安裝 curl 模式的 runtime dependencies。工作目錄為 `/app/crawler`，分類清單包含在 image 的 `/app/crawler/category-pages.txt`。以 UID/GID `10001` 執行，stdout 即為 log。不提供 Chromium；需要 browser 診斷時使用 README 的獨立環境。

`ENTRYPOINT ["python", "-m"]` 配合預設 `CMD ["books_crawler"]`，可以在 image 名稱後覆寫要執行的 module：

```bash
docker build -t book-finder-crawler:local crawler

# 不提供 DATABASE_URL：應顯示設定錯誤並回傳 2；不會抓網頁或連 DB。
docker run --rm book-finder-crawler:local
echo $?

# 單純驗證依賴與分類清單，不連外。
docker run --rm --entrypoint python book-finder-crawler:local -c \
  'import psycopg, curl_cffi, bs4; from books_crawler.page_list import load_page_urls, DEFAULT_PAGES_FILE; print("pages:", len(load_page_urls(DEFAULT_PAGES_FILE)))'
```

一般的正式執行為 `docker run ... IMAGE books_crawler`；分類補書為 `docker run ... IMAGE books_crawler.pages`。不要在 Dockerfile 寫入 DATABASE_URL，也不要把 `.env` COPY 進 image。`.dockerignore` 只允許程式、runtime requirements 與分類清單進入 build context。

本機建置的 image 不推送。正式 image 只由 CD 建置、以 GHCR 發布（見 §2）。

## 2. 映像發布（GHCR，由 CD 管理）

- Image：`ghcr.io/arthur801/book-finder-crawler`。CD 在推送 `v*` tag 時建置。順序：先將 image 推送至每次 workflow attempt 專屬的 `build-<run_id>-<run_attempt>` staging tag，取得 digest 後建立並驗證 attestation；驗證成功後才以 `docker buildx imagetools create --prefer-index=false` 建立正式 `v*` release tag（commit point），並確認該 tag 解析到同一 digest。digest 寫入該 release 的 `release.json`。完整流程見 `deploy/README.md` §1.6。
- **不要手動推送。** 需要使用的 digest 來自 release 的 `release.json`，或 CD 的 plan summary。
- 每次部署只使用 digest（`image@sha256:…`），不使用可變的 tag。
- 若 EC2 需要拉取 private package，見 `deploy/README.md` §2.8（GHCR visibility）。

## 3. EC2 前置條件

- Docker Engine 正常執行並開機自動啟動；另需 AWS CLI v2、bash、`flock`（util-linux）、cron、logrotate。套件安裝方式依 EC2 的 Linux 發行版而定：Ubuntu 通常為 `cron`，Amazon Linux 為 `crond`。
- EC2 host 時區維持 UTC（`timedatectl` 檢查），才能直接套用附帶的 cron。
- RDS Security Group 允許 EC2 的 Security Group 連 TCP 5432；EC2 能連到 RDS、SSM 與 GHCR，以及來源網站。crawler 不需要開放任何 inbound port，也不需要 `-p`。
- 正式 schema 已透過 EF migration 建立；crawler 不負責 migration。
- EC2 IAM role 能 `ssm:GetParameter` 讀指定的資料庫參數；若用 customer managed KMS key，需該 key 的 `kms:Decrypt` 權限。使用 host 的 instance role，不需要把 AWS keys 放進 container。

在 SSM 建立專用 `SecureString`，例如 `/book-finder/prod/crawler-database-url`（範例名稱），內容是 psycopg 的 PostgreSQL URL：

```text
postgresql://CRAWLER_USER:URL_ENCODED_PASSWORD@RDS_ENDPOINT:5432/book_finder?sslmode=require
```

密碼的特殊字元需 URL encode；不要把 .NET 的 `Host=...;Username=...` 字串原樣給 crawler。使用資料庫 host name，container 裡的 `localhost` 是 container 自己。此範例要求 TLS；若環境採 `verify-full`，改用下列 URL，並在 `crawler.conf` 設定 `DB_CA_BUNDLE`（§4）。`run-crawler.sh` 會以唯讀方式把該檔掛到容器內的同一路徑，所以 `sslrootcert` 指的是容器內也存在的路徑。不要關閉憑證驗證繞過錯誤（`sslmode=require` 不驗證憑證，安全性較低）：

```text
postgresql://CRAWLER_USER:URL_ENCODED_PASSWORD@RDS_ENDPOINT:5432/book_finder?sslmode=verify-full&sslrootcert=/etc/book-finder/global-bundle.pem
```

`run-crawler.sh` 每次執行以 host IAM role 讀取此參數，寫入 `/run/book-finder` 的臨時 env file（權限 600），用 `--env-file` 注入 container，結束後刪除。重開機後下次執行會重新產生，cron 不依賴 SSH session 的 `export`。參考 [SSM IAM 設定](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-setting-up.html) 與 [get-parameter](https://docs.aws.amazon.com/cli/latest/reference/ssm/get-parameter.html)。

## 4. 首次安裝檔案（bootstrap 前）

本機只需將 `crawler/deploy/` 上傳，不必將整個 repository 複製到 EC2：

```bash
scp -r crawler/deploy EC2_USER@EC2_HOST:~/crawler-deploy
```

若 SSH 需要 key，依環境加入 `-i /path/to/key.pem`。以下在 EC2 執行：

只建立不存在的目錄。已存在的目錄不要再執行 `install -d -m`，因為它會改寫權限（2026-10-24 production 因此出現 500，見 `deploy/README.md` §2.5）。`/etc/book-finder` 必須是 `0755`，讓 web 能讀取 CA bundle：

```bash
[ -d /opt/book-finder ] || sudo install -d -m 0755 /opt/book-finder
[ -d /etc/book-finder ] || sudo install -d -m 0755 /etc/book-finder
[ -d /var/lib/book-finder/crawler ] || sudo install -d -m 0700 /var/lib/book-finder/crawler
[ -d /var/log/book-finder ] || sudo install -d -m 0750 /var/log/book-finder
sudo install -m 0755 ~/crawler-deploy/run-crawler.sh /opt/book-finder/run-crawler.sh
sudo install -m 0600 ~/crawler-deploy/crawler.conf.example /etc/book-finder/crawler.conf
sudoedit /etc/book-finder/crawler.conf
```

`crawler.conf` 內要設定三個非機密值：

| 鍵 | 說明 |
|---|---|
| `CRAWLER_IMAGE` | `ghcr.io/arthur801/book-finder-crawler@sha256:<digest>`（digest 由 release.json 取得；範例檔中的 `<digest>` 必須替換為實際 digest） |
| `AWS_REGION` | SSM 所在 region |
| `DATABASE_URL_PARAMETER` | 上節的 SSM parameter name |
| `CRAWLER_ENABLED` | 選填。`true`（預設，未寫入時即為 true）或 `false`；見下節「暫停排程」。空字串或其他值會以 exit 2 拒絕 |
| `DB_CA_BUNDLE` | 選填。RDS CA bundle 的絕對路徑（例如 `/etc/book-finder/global-bundle.pem`）。有設定時，須為一般檔案、不能是 symlink、權限 `0644`（容器的非 root 使用者要能讀）；不符合即 exit 2，且在任何變更之前拒絕。通過後以唯讀方式掛到容器內的同一路徑。未設定時不掛載，行為與之前相同 |

`crawler.conf` 由 root 擁有，只讓 root 編輯，因為 script 會 source 此檔。

```bash
# private GHCR package 才需要登入；排程用 root，所以用 sudo。
sudo docker pull ghcr.io/arthur801/book-finder-crawler@sha256:<digest>
```

wrapper 使用 `--pull=never`，因此 image 必須事先用 digest 拉取。CD 之後的部署會自動拉取（`deploy/README.md` §3.1 的 bootstrap 前置條件也是如此）。

## 5. 共用鎖、paused 與 dirty（N3）

`run-crawler.sh` 每次執行的順序：

1. 取得 `run.lock`（本腳本自己的互斥，避免兩個爬蟲同時跑）。
2. 取得 `db-maintenance.lock`（**shared**，等待上限 `DB_MAINTENANCE_WAIT_S`，預設 7200 秒）。超過時 exit 3。
3. **之後才讀取 state**（`BOOKFINDER_STATE_FILE`，預設 `/var/lib/book-finder/state.json`）：
   - `crawler.paused` 不是 null → 記錄 `skipped=paused`，exit 6；
   - `schema.dirty` 為 true → 記錄 `skipped=dirty`，exit 6；
   - state 存在但無法讀取 → exit 2（fail closed）；
   - state 不存在（尚未 bootstrap）→ 記錄 `state=absent`，照舊執行。
4. 執行 container，取得 pages 的成功紀錄，釋放 lock。

為什麼先拿 lock 再讀 state：部署在 forward migration 前會取得 exclusive `db-maintenance.lock`，並在 lock 內把 crawler 設為 paused。若先讀 state 再拿 lock，爬蟲可能在檢查之後、取得 lock 之前，與 migration 交錯。

- 部署（CD）在 forward migration 失敗、forward 之後的 web 失敗，或爬蟲更新部分失敗時，會保持 paused；爬蟲會跳過，直到人工以 `resume-crawler` 恢復（`deploy/README.md` §5.3）。
- 爬蟲跳過（exit 6）不是錯誤，只是 log 中會有 `skipped=paused` 或 `skipped=dirty`。

## 5.1 暫停排程（不影響部署）

若 EC2 被來源網站擋下（例如博客來封鎖 EC2 的 IP），把 `/etc/book-finder/crawler.conf` 加上 `CRAWLER_ENABLED=false`：

- 每次 cron 觸發仍會執行 wrapper，但它在取得 lock、讀取 state、呼叫 AWS 與 Docker 之前就結束，回傳 exit 0，並寫入 `YYYY-MM-DDTHH:MM:SSZ mode=daily skipped=disabled`（pages 為 `mode=pages`）。
- `pages-last-success` 不會被更新，也不會有 container。
- 部署不受影響：CD 只改寫 `CRAWLER_IMAGE=`，`CRAWLER_ENABLED=false` 會保留；也不會把 crawler 設為 paused（paused 會讓部署被拒絕）。
- 恢復時把這一行改為 `true` 或刪除即可，不需要重新安裝 cron。
- 值只接受 `true` 與 `false`，其他值（包括空字串）會以 exit 2 拒絕並寫入 stderr。

## 6. 手動驗證，再啟用 cron

以下會真實抓取博客來並寫入目前 SSM 指向的資料庫，請在確認目標資料庫後手動執行。若 state 為 paused 或 dirty，手動執行也會以 exit 6 跳過：

```bash
sudo /opt/book-finder/run-crawler.sh daily > /tmp/crawler-daily-check.log 2>&1
echo $?
sudo tail -n 50 /tmp/crawler-daily-check.log

sudo /opt/book-finder/run-crawler.sh pages > /tmp/crawler-pages-check.log 2>&1
echo $?
sudo tail -n 50 /tmp/crawler-pages-check.log

sudo /opt/book-finder/run-crawler.sh first_book > /tmp/crawler-first-book-check.log 2>&1
echo $?
sudo tail -n 50 /tmp/crawler-first-book-check.log
```

`first_book` 是手動診斷入口：只匯入排行榜第一名，不替換榜單，不安裝到 cron。它與 daily、pages 共用同一把 `run.lock`、maintenance shared lock 與 state gate；paused 或 dirty 時同樣以 exit 6 跳過。summary 行以 `mode=first-book` 開頭，並帶 `job_name=first-book`。

每日模式應有 `ranking_count=100` 與最終 report；pages 模式應有 `mode=pages`、頁數與書籍計數。需確認 EC2 能取得實際書籍頁面；如果是 Cloudflare challenge／網站連線異常，不要先啟用排程。`PARTIAL_SUCCESS` 的 exit code 也是 0，仍要看 skipped 與 error_count。不要只看 container 曾啟動或單一 `WARNING`。

成功驗證後才安裝排程與日誌輪替：

```bash
sudo install -m 0644 ~/crawler-deploy/crawler.cron /etc/cron.d/book-finder-crawler
sudo install -m 0644 ~/crawler-deploy/crawler.logrotate /etc/logrotate.d/book-finder-crawler
sudo logrotate --debug /etc/logrotate.d/book-finder-crawler
```

確認發行版的 cron service 已啟動並開機自動啟動：Ubuntu 可使用 `sudo systemctl enable --now cron`；Amazon Linux 則使用 `sudo systemctl enable --now crond`（先安裝對應套件）。`/etc/cron.d` 檔案已包含 `root` 使用者欄位，**不要原樣貼進 `crontab -e`**；不需要同時建立第二份排程。

排程以 UTC 表達：

```cron
0 20 * * * root /opt/book-finder/run-crawler.sh daily >> /var/log/book-finder/crawler-daily.log 2>&1
0 21 * * * root /opt/book-finder/run-crawler.sh pages --scheduled >> /var/log/book-finder/crawler-pages.log 2>&1
```

- 每日榜單：台灣時間每天 04:00。
- 分類補書：台灣時間每天 05:00 檢查一次，距離上次成功啟動時間至少 72 小時才執行；沒有紀錄時第一次即執行。`SUCCESS` 和 `PARTIAL_SUCCESS`（exit 0）會記錄，FAILED／設定錯誤會在下一個每日檢查時再試。手動成功執行 pages 也會更新這個紀錄。
- 時間紀錄保存在 `/var/lib/book-finder/crawler/pages-last-success`，重新建立 container 或 EC2 reboot 不會歸零；EC2 關機期間 cron 不會執行，開機後下一個排程時間才會檢查，不補跑每一個遺漏時段。
- 共用 `flock` 鎖：若分類補書還沒完成，每日榜單等待鎖，實際開始時間可能延後。鎖等待／EC2 停機造成延遲時，pages 每日檢查可能晚於整整 72 小時。
- 不使用 day-of-month 的 `*/3`：它在每個月內取步進，不是連續的三天間隔。見 [crontab 語法](https://man7.org/linux/man-pages/man5/crontab.5.html)。

## 7. 檢查 log 與診斷檔案

```bash
sudo tail -n 100 /var/log/book-finder/crawler-daily.log
sudo tail -n 100 /var/log/book-finder/crawler-pages.log
sudo tail -f /var/log/book-finder/crawler-daily.log
sudo rg 'status=|exit_code=|ERROR|schedule=not-due|skipped=' /var/log/book-finder/crawler-*.log
sudo ls -l /var/lib/book-finder/crawler/artifacts/challenges
```

若 EC2 沒有 `rg`，上述搜尋可用 `grep -E`。Python INFO／WARNING／ERROR 輸出與 wrapper 的 `container=start`、`container=end exit_code=...` 都會保留。若只有 start 而沒有 end，檢查接續的 AWS／Docker error 或程序是否仍在執行。`schedule=not-due` 是正常的三天間隔略過；`skipped=paused` 與 `skipped=dirty` 表示爬蟲在等待人工處理（見 §5）。

`--rm` 結束後 container 已刪除，因此使用主機 log 查看歷史紀錄。logrotate 每天檢查、保留 14 份輪替日誌並壓縮；主機要有定期執行 logrotate 的 timer／cron。採 `copytruncate` 讓長時間運行的程序繼續寫同一 log，但輪替瞬間有極短的可能遺失窗口。

Cloudflare／非 200 等診斷 HTML、JSON 經 bind mount 留在主機 artifacts 目錄，不因 container 刪除而消失；目前不自動刪除，需定期檢查磁碟空間並管理保留期限。log 不含 DATABASE_URL，但 Docker daemon 管理者仍可讀取容器環境，不要把 Docker 管理權限開放給非管理者。

## 8. 更新與停用

- **更新**：不需手動操作。CD 部署新版時會把 `crawler.conf` 的 `CRAWLER_IMAGE=` 改寫為新 digest，並安裝該 release 的 `run-crawler.sh` 與 `crawler.cron`（release 未附上時保留原檔）。正在運行的 container 繼續完成原版本，下一次執行使用新版本。
- **不要手動修改 `CRAWLER_IMAGE`**。手動修改後，`resume-crawler` 會拒絕，直到設定與 state 一致（`deploy/README.md` §5.3）。
- **部分失敗**：CD 在爬蟲更新中途失敗時，會保持 paused（結果 `partial-crawler`，exit 7）。此時先查 history 的 `crawler_substeps` 與 journal，再以 `resume-crawler` 處理。
- **暫停後續排程**：可執行 `sudo mv /etc/cron.d/book-finder-crawler /opt/book-finder/crawler.cron.disabled`；已開始的 container 仍會執行。恢復時將檔案放回 `/etc/cron.d`。注意：CD 下次部署若附上 `crawler.cron`，會重新安裝它。
- 不要透過刪除資料庫或 schema 停止爬蟲。要阻止爬蟲執行，使用 paused（由 CD 或 `deploy/README.md` 的人工程序處理）。

## 9. 本地 runner（Phase 6，金石堂與博客來）

v12 計畫（`Docs/plans/kingstone-category-crawler.md` §8）改由使用者的本機（WSL2／Linux＋Docker）手動執行 crawler。`deploy/local/run-local-crawler.sh` 經 SSH 隧道連到 RDS，所有 provider 共用同一把本地 `run.lock`，並套用 writer fencing 與 hard-limit watchdog。這個 runner 不會被 cron 呼叫，也不改變 EC2 上的 `run-crawler.sh`。EC2 的 crawler cron 另案移除，目前維持 `CRAWLER_ENABLED=false`。

### 9.1 前置條件

- **SSH**：`~/.ssh/config` 有 EC2 主機的 alias（填入 `EC2_SSH_HOST`），金鑰只在本機。runner 以 `BatchMode=yes` 執行，不會互動式詢問密碼。
- **AWS 或 secret 檔（擇一）**：
  - `DB_SECRET_SOURCE=ssm`：本機的 AWS profile 要有 `ssm:GetParameter`（與 `kms:Decrypt`，若使用客戶管理金鑰）權限，讀取與 EC2 相同的 `DATABASE_URL_PARAMETER`；
  - `DB_SECRET_SOURCE=file`：`DB_SECRET_FILE` 指向本機的檔案，權限必須是 `600` 且 owner 是自己；內容是 psycopg 的 PostgreSQL URL（與 SSM 參數相同格式）。
- **CA bundle**：RDS CA bundle 放在本機（`DB_CA_BUNDLE`），權限 `0644`。runner 以唯讀方式掛到容器內 `/etc/book-finder/rds-ca-bundle.pem`，`sslrootcert` 指向這個路徑。
- **Docker**：daemon 正常執行；image 需已存在於本機（runner 使用 `--pull=never`）。
- **Artifacts 目錄**：`CRAWLER_LOCAL_ARTIFACTS_DIR` 掛到容器內 `/app/crawler/artifacts`。容器以 UID 10001 執行，因此目錄須屬於 `10001`（`sudo chown 10001:10001 <dir>`）或為 world-writable；否則 runner 以 exit 10 拒絕。

### 9.2 設定檔

範例：`deploy/local/crawler-local.conf.example`（只有佔位值，不含 secret）。複製到 `~/.config/book-finder/crawler-local.conf`（或以 `CRAWLER_LOCAL_CONF` 指定其他路徑），權限 `0600`。runner 以 shell 讀取此檔，因此只寫 `KEY=value`。

| 鍵 | 必要 | 說明 |
|---|---|---|
| `CRAWLER_ENABLED` | 否 | `true`（未設定即為 true）或 `false`。`false` 時不做任何外部工作，exit 0，log `skipped=disabled`。其他值 exit 10 |
| `CRAWLER_IMAGE` | 博客來 | 博客來 image（digest）；daily、pages、first_book 使用 |
| `KINGSTONE_CRAWLER_IMAGE` | 金石堂 | HTTP-only image（`crawler/Dockerfile` 的 `kingstone` target） |
| `CRAWLER_LOCAL_ARTIFACTS_DIR` | 是 | 絕對路徑；掛到容器內 `/app/crawler/artifacts`（見 §9.1） |
| `EC2_SSH_HOST` | 是 | EC2 的 SSH alias；用於唯讀讀取 deploy state 與建立隧道 |
| `EC2_STATE_FILE` | 是 | EC2 上的 deploy `state.json`（與 `BOOKFINDER_STATE_FILE` 相同路徑） |
| `RDS_ENDPOINT` | 是 | RDS 的 host name（不含 port）。它是 TLS 主機名稱，憑證以此比對 |
| `LOCAL_DB_PORT` | 是 | 本機隧道埠，1024–65535 |
| `DB_CA_BUNDLE` | 是 | 本機 RDS CA bundle 的絕對路徑（`0644`，不能是 symlink） |
| `DB_SECRET_SOURCE` | 是 | `ssm` 或 `file` |
| `AWS_PROFILE`／`AWS_REGION`／`DATABASE_URL_PARAMETER` | ssm 時 | 讀取 SSM 參數 |
| `DB_SECRET_FILE` | file 時 | 600 權限的 secret 檔 |
| `CRAWLER_RUN_HARD_LIMIT_SECONDS` | 否 | 金石堂的 hard limit（預設 9000）；同時以 `--env` 傳給 container，須大於 container 的 soft budget（預設 7200） |
| `BOOKS_RUN_HARD_LIMIT_SECONDS` | 否 | 博客來的 hard limit（預設 3600，見 backlog） |
| `CRAWLER_STOP_GRACE_SECONDS` | 否 | watchdog 的 `docker stop -t`（預設 30） |
| `TUNNEL_WAIT_SECONDS` | 否 | 等待隧道埠可連的上限（預設 20） |
| `CRAWLER_LOCAL_STATE_DIR` | 否 | `run.lock` 所在目錄（預設 `$XDG_STATE_HOME/book-finder-crawler`） |
| `CRAWLER_LOCAL_RUNTIME_DIR` | 否 | 600 env file 與 cidfile 的暫存目錄（預設 `$XDG_CACHE_HOME/book-finder-crawler/run`，700） |

### 9.3 執行

```bash
CRAWLER_LOCAL_CONF=~/.config/book-finder/crawler-local.conf \
  crawler/deploy/local/run-local-crawler.sh kingstone

# 博客來：daily、pages、first_book 與 EC2 相同的模組對應
crawler/deploy/local/run-local-crawler.sh daily
```

執行順序（任一步失敗即停止，並在 exit 前清理）：

1. 讀設定；`CRAWLER_ENABLED=false` 即結束；其他必要值驗證失敗 exit 10。
2. 取得本地 `run.lock`（非阻塞；已被持有即 exit 11）。
3. 經 SSH 唯讀讀取 EC2 `state.json`，paused／dirty 則 exit 6；讀不到（含檔案不存在）fail closed，exit 12。
4. orphan check：固定 container 名稱 `book-finder-crawler-active`、label `com.bookfinder.role=catalog-crawler`。running、restarting、paused、removing 拒絕啟動（exit 13，`ORPHAN_WRITER`）；exited、dead、created 先 `docker rm`。
5. 取得 DB secret（SSM 或 600 檔），不寫入 argv、log 或 env。
6. 改寫連線字串，寫入 600 的 env file（只含 `DATABASE_URL`），用後刪除。
7. 啟動 `ssh -N -o ExitOnForwardFailure=yes ... -L 127.0.0.1:<port>:<RDS>:5432`，等待本機埠可連；失敗 exit 16。
8. 以 `docker run --network host --pull=never --init` 啟動 container（名稱與 labels 如上，`--cidfile` 指向 runtime 目錄）；kingstone 使用預設 CMD，博客來使用對應 module。
9. watchdog：超過 hard limit、或收到 SIGINT／SIGTERM → `docker stop -t` → 仍 running 則 `docker kill` → 再確認停止。無法確認 → `ORPHAN_WRITER`，exit 14，之後的啟動會被第 4 步擋下。
10. 正常結束也會確認狀態後 `docker rm`；關閉隧道、刪除 env file、釋放鎖。

**連線字串的 TLS 設計**：`host` 保留為 RDS endpoint（憑證主機名比對），`hostaddr=127.0.0.1` 指定實際連線位址，埠改為本機隧道埠，並加上 `sslmode=verify-full` 與 `sslrootcert=/etc/book-finder/rds-ca-bundle.pem`。secret 中的 host 必須等於 `RDS_ENDPOINT`，否則拒絕（exit 17），以免隧道連到其他主機。密碼等 userinfo 保留原樣，不解碼，因此 URL 中的特殊字元須已 percent-encode。

### 9.4 Exit code

| Exit | 意義 |
|---|---|
| 0 | container 成功（SUCCESS 或 PARTIAL_SUCCESS），或 `CRAWLER_ENABLED=false` 跳過 |
| 1 | container FAILED（容器自身的結果，見 `kingstone` 或 `books_crawler` 的說明） |
| 2 | container 設定錯誤（DB URL、設定、清單或 provider；由容器回傳） |
| 6 | 跳過：EC2 deploy state 為 paused 或 dirty |
| 10 | runner 設定或用法錯誤（缺值、格式錯誤、CA bundle、artifacts 權限、`CRAWLER_ENABLED` 非法） |
| 11 | 另一個本地 run 持有 `run.lock` |
| 12 | 無法讀取 EC2 deploy state（fail closed；本 runner 不沿用 EC2 的 exit 2，以免與 container 的設定錯誤混淆） |
| 13 | 偵測到 writer container 仍在運作（`ORPHAN_WRITER`）或處於 busy 狀態；未啟動任何 container |
| 14 | watchdog 無法確認 writer 已停止（`ORPHAN_WRITER`）；之後的啟動會被擋下，需人工確認 container 狀態 |
| 15 | DB secret 無法讀取或無效（SSM 失敗、secret 檔權限或 owner 錯誤、secret 為空） |
| 16 | SSH 隧道無法轉發（ssh 立即退出，或等待逾時） |
| 17 | 連線字串改寫失敗（不是 PostgreSQL URL，或 host 與 `RDS_ENDPOINT` 不符） |
| 18 | Docker 無法使用（orphan check 時） |
| 20 | watchdog 因 hard limit 停止 writer（已確認停止） |
| 21 | 被 SIGINT／SIGTERM 中斷；已先停止 writer（若尚未啟動 container 則直接退出） |

其他值（例如 container 內部的 125）為 Docker 或 container 自身的 exit code，原樣傳回。

### 9.5 手動 canary（金石堂）

金石堂第一次真站驗證只在使用者本機執行，且不得與 CD 部署重疊：

1. 確認 EC2 deploy state 沒有 paused 或 dirty（runner 會檢查，但部署進行中時請不要啟動）；Phase 6 的 DB advisory lock 尚未由本 runner 取得，因此請自行避開部署窗口。
2. 清單只放 1 頁：暫時把 `crawler/kingstone-pages.txt` 改為只有一行，`docker build --target kingstone -t kingstone:canary crawler`，設定 `KINGSTONE_CRAWLER_IMAGE=kingstone:canary`。測試完成後還原清單檔，並重建 image。
3. 確認寫入策略為 `new-books-only`。這是程式的預設值（`KINGSTONE_WRITE_POLICY` 未設定即是），本 runner 不轉傳此變數；不要在 image 或環境中改為 `normal`。
4. 執行 `run-local-crawler.sh kingstone`，確認 exit code、`artifacts/kingstone/last-run.json`（M5 之後）與 log 中的 `container=end exit_code=...`。
5. 成功後還原清單與 image tag，再視需要以 `normal` 進行下一步（另案）。

金石堂若封鎖本地 IP，依 rollback 停用（`CRAWLER_ENABLED=false`），不採取規避技術。
