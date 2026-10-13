# Crawler：Docker Hub → EC2 → cron

此流程使用主機 cron 啟動一次性的 Docker container。`run_once` 每天執行，`run_pages` 每三天執行；程式入口與 parser 不需再修改。以下從 repository 根目錄執行本機指令，EC2 指令另行標示。

## 1. Dockerfile 與本機驗證

`crawler/Dockerfile` 使用 Python 3.14，只安裝 curl 模式的 runtime dependencies。工作目錄為 `/app/crawler`，分類清單包含在 image 的 `/app/crawler/category-pages.txt`。以 UID/GID `10001` 執行，stdout 即為 log。不提供 Chromium；需要 browser 診斷時使用 README 的獨立環境。

`ENTRYPOINT ["python", "-m"]` 配合預設 `CMD ["books_crawler"]`，可以在 image 名称後覆寫要執行的 module：

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

## 2. 推送 Docker Hub

先在 Docker Hub 建立 `book-finder-crawler` repository。以下將 `YOUR_DOCKERHUB_USER` 換成帳號，release tag 每次發布遞增；不要覆寫目前正式使用的版本。

```bash
docker login --username YOUR_DOCKERHUB_USER
docker buildx build --platform linux/amd64 \
  -t YOUR_DOCKERHUB_USER/book-finder-crawler:2026-10-12.1 \
  --push crawler
```

這個指令適用於 x86_64 EC2。若 EC2 是 Graviton／aarch64，改成 `--platform linux/arm64`。本機的架構不一定與 EC2 相同，先在 EC2 用 `uname -m` 確認。Docker 支援直接將 build 結果推送 registry，見 [Docker buildx](https://docs.docker.com/reference/cli/docker/buildx/build/) 與 [多平台建置](https://docs.docker.com/build/building/multi-platform/)。

更新程式或內建分類清單後，要重新 build、push 新 tag，再在 EC2 pull 並修改 `crawler.conf`。回滾時改回已下載的上一版 image tag。

## 3. EC2 前置條件

- Docker Engine 正常執行並開機自動啟動；另需 AWS CLI v2、bash、`flock`（util-linux）、cron、logrotate。套件安裝方式依 EC2 的 Linux 發行版而定：Ubuntu 通常為 `cron`，Amazon Linux 為 `crond`。
- EC2 host 時區維持 UTC（`timedatectl` 檢查），才能直接套用附帶的 cron。
- RDS Security Group 允許 EC2 的 Security Group 連 TCP 5432；EC2 能連到 RDS、SSM、Docker Hub 與來源網站。crawler 不需要開放任何 inbound port，也不需要 `-p`。
- 正式 schema 已透過 EF migration 建立；crawler 不負責 migration。
- EC2 IAM role 能 `ssm:GetParameter` 讀指定的資料庫參數；若用 customer managed KMS key，需該 key 的 `kms:Decrypt` 權限。使用 host 的 instance role，不需要把 AWS keys 放進 container。

在 SSM 建立專用 `SecureString`，例如 `/book-finder/prod/crawler-database-url`，內容是 psycopg 的 PostgreSQL URL：

```text
postgresql://CRAWLER_USER:URL_ENCODED_PASSWORD@RDS_ENDPOINT:5432/book_finder?sslmode=require
```

密碼的特殊字元需 URL encode；不要把 .NET 的 `Host=...;Username=...` 字串原樣給 crawler。使用資料库 host name，container 裡的 `localhost` 是 container 自己。此範例要求 TLS；若環境採 `verify-full`，需另外掛載 RDS CA 檔並設定 `sslrootcert`，不要關閉憑證驗證繞過錯誤。

`run-crawler.sh` 每次執行以 host IAM role 讀取此參數，寫入 `/run/book-finder` 的臨時 env file（權限 600），用 `--env-file` 注入 container，結束後刪除。重開機後下次執行會重新產生，cron 不依賴 SSH session 的 `export`。參考 [SSM IAM 設定](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-setting-up.html) 與 [get-parameter](https://docs.aws.amazon.com/cli/latest/reference/ssm/get-parameter.html)。

## 4. 複製部署檔案並拉取 image

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

修改三個非機密設定：`CRAWLER_IMAGE`（實際 image tag）、`AWS_REGION`（SSM 所在 region）、`DATABASE_URL_PARAMETER`（SSM parameter name）。`crawler.conf` 由 root 擁有，只讓 root 編輯，因為 script 會 source 此檔。

```bash
# private Docker Hub repository 才需要登入；排程用 root，所以用 sudo login。
sudo docker login --username YOUR_DOCKERHUB_USER
sudo docker pull YOUR_DOCKERHUB_USER/book-finder-crawler:2026-10-12.1
```

wrapper 使用 `--pull=never`：先手動下載明確版本，再啟用該版本，避免每次 cron 自動更換 image。

## 5. 手動驗證，再啟用 cron

以下會真實抓取博客來並寫入目前 SSM 指向的資料庫，請在確認目標資料庫後手動執行：

```bash
sudo /opt/book-finder/run-crawler.sh daily > /tmp/crawler-daily-check.log 2>&1
echo $?
sudo tail -n 50 /tmp/crawler-daily-check.log

sudo /opt/book-finder/run-crawler.sh pages > /tmp/crawler-pages-check.log 2>&1
echo $?
sudo tail -n 50 /tmp/crawler-pages-check.log
```

每日模式應有 `ranking_count=100` 與最终 report；pages 模式應有 `mode=pages`、頁數與書籍計數。需確認 EC2 能取得實際書籍頁面；如果是 Cloudflare challenge／網站連線異常，不要先啟用排程。`PARTIAL_SUCCESS` 的 exit code 也是 0，仍要看 skipped 與 error_count。不要只看 container 曾啟動或單一 `WARNING`。

成功驗證後才安裝排程與日誌輪替：

```bash
sudo install -m 0644 ~/crawler-deploy/crawler.cron /etc/cron.d/book-finder-crawler
sudo install -m 0644 ~/crawler-deploy/crawler.logrotate /etc/logrotate.d/book-finder-crawler
sudo logrotate --debug /etc/logrotate.d/book-finder-crawler
```

確認發行版的 cron service 已啟動並開機自動啟動：Ubuntu 可使用 `sudo systemctl enable --now cron`；Amazon Linux 則使用 `sudo systemctl enable --now crond`（先安裝对应套件）。`/etc/cron.d` 檔案已包含 `root` 使用者欄位，**不要原樣貼進 `crontab -e`**；不需要同時建立第二份排程。

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

## 6. 檢查 log 與診斷檔案

```bash
sudo tail -n 100 /var/log/book-finder/crawler-daily.log
sudo tail -n 100 /var/log/book-finder/crawler-pages.log
sudo tail -f /var/log/book-finder/crawler-daily.log
sudo rg 'status=|exit_code=|ERROR|schedule=not-due' /var/log/book-finder/crawler-*.log
sudo ls -l /var/lib/book-finder/crawler/artifacts/challenges
```

若 EC2 沒有 `rg`，上述搜尋可用 `grep -E`。Python INFO／WARNING／ERROR 輸出與 wrapper 的 `container=start`、`container=end exit_code=...` 都會保留。若只有 start 而沒有 end，檢查接續的 AWS／Docker error 或程序是否仍在執行。`schedule=not-due` 是正常的三天間隔略過。

`--rm` 結束後 container 已刪除，因此使用主機 log 查看歷史紀錄。logrotate 每天檢查、保留 14 份輪替日誌並壓縮；主機要有定期執行 logrotate 的 timer／cron。採 `copytruncate` 讓長時間運行的程序繼續寫同一 log，但輪替瞬間有極短的可能遺失窗口。

Cloudflare／非 200 等診斷 HTML、JSON 經 bind mount 留在主機 artifacts 目錄，不因 container 刪除而消失；目前不自動刪除，需定期檢查磁碟空間並管理保留期限。log 不含 DATABASE_URL，但 Docker daemon 管理者仍可讀取容器環境，不要把 Docker 管理權限開放给非管理者。

## 7. 更新與停用

發布新 tag 後在 EC2 `sudo docker pull` 新版本，再修改 `/etc/book-finder/crawler.conf` 的 image。正在運行的 container 繼續完成原版本，下一次執行使用新版本。更新前用不連外的 smoke check 確认入口，再依需要手動驗證。

暫停後續排程可執行 `sudo mv /etc/cron.d/book-finder-crawler /opt/book-finder/crawler.cron.disabled`；已開始的 container 仍會執行。恢復時將檔案放回 `/etc/cron.d`。不要透過刪除資料庫或 schema 停止爬蟲。
