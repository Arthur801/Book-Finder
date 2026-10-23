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

密碼的特殊字元需 URL encode；不要把 .NET 的 `Host=...;Username=...` 字串原樣給 crawler。使用資料庫 host name，container 裡的 `localhost` 是 container 自己。此範例要求 TLS；若環境採 `verify-full`，需另外掛載 RDS CA 檔並設定 `sslrootcert`，不要關閉憑證驗證繞過錯誤。

`run-crawler.sh` 每次執行以 host IAM role 讀取此參數，寫入 `/run/book-finder` 的臨時 env file（權限 600），用 `--env-file` 注入 container，結束後刪除。重開機後下次執行會重新產生，cron 不依賴 SSH session 的 `export`。參考 [SSM IAM 設定](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-setting-up.html) 與 [get-parameter](https://docs.aws.amazon.com/cli/latest/reference/ssm/get-parameter.html)。

## 4. 首次安裝檔案（bootstrap 前）

本機只需將 `crawler/deploy/` 上傳，不必將整個 repository 複製到 EC2：

```bash
scp -r crawler/deploy EC2_USER@EC2_HOST:~/crawler-deploy
```

若 SSH 需要 key，依環境加入 `-i /path/to/key.pem`。以下在 EC2 執行：

```bash
sudo install -d -m 0755 /opt/book-finder
sudo install -d -m 0700 /etc/book-finder /var/lib/book-finder/crawler
sudo install -d -m 0750 /var/log/book-finder
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
```

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
