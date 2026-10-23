# Deployment

> Path: `Docs/deployment/deployment.md`
> Authority: Runtime 環境、AWS 資源、Docker、secrets、TLS、migration、排程、備份
> 系統拓樸見 `Docs/architecture/system-architecture.md`。
> CD 流程、host 狀態機、退出碼與人工程序見 `deploy/README.md`；決策理由見 `Docs/architecture/architecture-decisions.md` ADR-006。
> 本文件涉及的 production 操作屬 `AGENTS.md` L4：需明確授權，agent 不得自行執行。

## 1. 環境

| 環境 | Database | Secrets |
|---|---|---|
| Local | `compose.yaml` 的 `pgvector/pgvector:0.8.7-pg17`（只綁 `127.0.0.1`） | `.env`（不進 repository）、`dotnet user-secrets`；JWT key 與 `OPENAIAPI_KEY` 見 §5 |
| Test | Testcontainers 拋棄式資料庫 | 不需要 |
| Production | AWS RDS PostgreSQL + pgvector | AWS SSM Parameter Store |

MVP 沒有 staging；L4 變更以本機或拋棄式資料庫 dry run 取代。

## 2. AWS 資源

| 資源 | 設定 |
|---|---|
| EC2 | 單台，Docker + Docker Compose；附 IAM role（讀取 SSM 參數） |
| RDS | PostgreSQL + pgvector；private subnet；Security Group 只允許 EC2 的 SG 連 5432；自動備份保留 7 天 |
| SSM Parameter Store | standard tier `SecureString` |
| 網域 | 使用者自有網域，A record 指向 EC2（Elastic IP） |

不使用 S3、ALB、ElastiCache（延後 / 不需要）。

## 3. Containers（EC2）

CD 部署後的配置（`deploy/README.md` §1）：

| 元件 | 執行方式 | 說明 |
|---|---|---|
| `nginx` | host 上的 systemd 服務，**不在 compose 中** | 對外 80 / 443；TLS 終止；80 只做 ACME 驗證與轉址 HTTPS；轉發至 `127.0.0.1:5000` |
| `web` | compose（`deploy/release/compose.prod.yaml`，project `book-finder`），image 由 CD 以 digest 指定（GHCR） | 只綁定 `127.0.0.1:5000`，容器內 8080；compose 檔隨 web image 的 `/opt/release/` 發布 |
| `crawler` | 非常駐，由 host cron 呼叫 `run-crawler.sh`，以 `docker run --rm` 執行 | image 來自 GHCR，digest 由 CD 寫入 `crawler.conf`。正式 image 只支援 curl；browser 診斷另需 Playwright／Chromium |

切換前（舊版）web 是 systemd 服務，見 §3.1。

`web` 必須設定 Forwarded Headers，只信任 `nginx` 的位址（`identity-auth.md` §7 rate limiting 依賴正確的 client IP）。

`web` image 必須包含 tzdata（`/usr/share/zoneinfo`），並保留 ICU（除非以 invariant globalization 執行），以便以 `Asia/Taipei` 顯示 `captured_at`（`bestseller.md` §4）。若執行環境找不到該時區，程式會退回固定 UTC+08:00（台灣無夏令時間，顯示結果相同），不會因此回 500。

### 3.1 原生發布（暫時使用dotnet publish + systemd）— 已由 §3 的 CD 部署取代

> 狀態：首次切換（`deploy/README.md` §3）成功後，本節不再適用。切換前仍是現行狀態。systemd unit 切換後應停用（`deploy/README.md` §3.7）。

使用者已核准先以原生發布取代 EC2 containers（2026-10-11）：本機發布 `linux-x64`、framework-dependent 的 .NET 10 應用；EC2 安裝 ASP.NET Core Runtime 10，以 systemd 執行 `dotnet Book-Finder.dll`，監聽 `127.0.0.1:5000`，host nginx 負責 HTTPS 與反向代理。RDS、SSM secrets 與獨立 migration 步驟維持原規則。

`Program.cs` 在 HSTS 與 HTTPS redirection 前處理 `X-Forwarded-For`、`X-Forwarded-Proto`，保留框架預設的 loopback proxy 信任範圍，適用於 host nginx。未來若恢復 container 部署，必須另行設定 nginx 的受信任位址，不可清空 proxy 信任限制來接受任意來源。

實際實作會以docker為主，這部分為暫時使用。

## 4. TLS（nginx + ZeroSSL）

- 憑證由 host 上的 `acme.sh` 向 ZeroSSL 簽發（需先以 email 註冊 ZeroSSL 帳號），使用 webroot 驗證（nginx 提供 `/.well-known/acme-challenge/`）。
- `acme.sh` 自帶的 cron 自動續期；續期後在 host 上執行 `sudo nginx -s reload`（nginx 在 host 上，不在 compose 中）。
- nginx：只開 TLS 1.2 / 1.3；HTTP 一律 301 至 HTTPS；`web` 端另有 HSTS。
- 網域名稱以 `<your-domain>` 表示，不寫入 repository。

## 5. Secrets

| 參數（SSM path 範例） | 用途 |
|---|---|
| `/book-finder/prod/db-connection` | RDS 連線字串 |
| `/book-finder/prod/openai-api-key` | OpenAI（注入環境變數 `OPENAIAPI_KEY`） |
| `/book-finder/prod/google-books-api-key` | Google Books（#14 Google Books fallback 實作時才使用；目前程式未讀取，host 也不注入） |
| `/book-finder/prod/jwt-signing-key` | JWT HS256 key（至少 32 bytes 隨機值） |

- CD 的 deploy 由 host 程式以 EC2 IAM role 讀取 SSM，寫入 `/run/book-finder/web-<run_id>.env`（`chmod 600`），compose 以 `env_file`（`format: raw`）注入；每次部署結束（成功或失敗）都會刪除此檔（`machine.py` 的 `_discard_env`）。secret 值不寫入 history、journal 或 log。
- host.conf 以鍵名指定 SSM 參數：`SSM_DB_CONNECTION`、`SSM_OPENAI_KEY`、`SSM_JWT_KEY`，以及 host 的 psql 用參數 `DATABASE_URL_PARAMETER`（唯讀查詢 migration 歷史）。格式與權限見 `deploy/README.md` §2.3。
- 獨立 crawler 的 `run-crawler.sh` 每次執行讀取專用 PostgreSQL URL 參數（例如 `/book-finder/prod/crawler-database-url`），寫入 `/run/book-finder/crawler-env.*`（600），透過 Docker `--env-file` 注入，結束後刪除；不共用包含 Web secrets 的 env file。
- Crawler 只拿 DB 連線字串（secret，經 SSM 注入）與下列非機密的 crawler 設定，不拿 OpenAI / Google Books / JWT key。
- Web 以設定鍵 `Jwt:SigningKey` 讀取 JWT key（環境變數 `Jwt__SigningKey`）；缺少或短於 32 bytes 時啟動失敗。本機放在 `.env`，啟動前以 `set -a; . ./.env; set +a` 載入 shell（程式本身不讀 `.env`）。
- Web 以環境變數 `OPENAIAPI_KEY` 讀取 OpenAI key，host script 寫入 env file 時使用此變數名稱；缺少時 web 啟動失敗（與 `Jwt:SigningKey` 相同，啟動時驗證）。本機放在 `.env`，同樣需要 `OPENAIAPI_KEY=<your-openai-api-key>`，只放格式示意，不放真實值。
- Web 的 embedding 補齊非機密設定：`Embedding__Model`（預設 `text-embedding-3-small`）、`Embedding__Interval`（預設 `00:10:00`）、`Embedding__BatchSize`（預設 `100`）、`Embedding__BackfillEnabled`（預設 `true`）。可直接寫在 compose 檔的 `environment`，不需經 SSM。`Interval` ≤ 0、`BatchSize` ≤ 0 或 `Model` 空白時啟動失敗。
- 任何 secret 不得進 repository、image、log。非機密設定可直接寫在 compose 檔的 `environment`，不需經 SSM。

Crawler 非機密環境變數（`crawler/README.md`）：

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `CRAWLER_FETCHER` | `curl` | 頁面取得方式：`curl`（curl_cffi）或 `browser`（headless Chromium，僅供診斷）。其他值 → exit code 2。 |
| `CRAWLER_NAV_TIMEOUT_MS` | `30000` | 瀏覽器導覽逾時（毫秒，1～300000；空值為預設）。不合法 → exit code 2。 |
| `CRAWLER_PAGES_FILE` | `crawler/category-pages.txt` | 分類榜補書模式（`crawler.md` §16）的分類頁清單路徑；僅 `books_crawler.pages` 使用。清單不合法 → exit code 2。 |

`DATABASE_URL` 仍是 secret，不在此表中。

## 6. Migration

- `dotnet ef migrations bundle` 產生的 `efbundle` 放在 web image 內（`/app/efbundle`），每個 release 都隨 image 發布。
- web 啟動時**不**執行 migration。
- CD 的 deploy 在核准後，由 host 狀態機執行 forward migration（`deploy/README.md` §1、§4）。流程：
  1. 取得 `db-maintenance` lock（exclusive），並把 crawler 設為 paused（爬蟲在 shared lock 下檢查 state，見 §8）；
  2. 建立 RDS snapshot 作為 recovery point（還原屬 L4，一律人工）；
  3. 設定 schema dirty；
  4. 執行 efbundle；只有結束碼為 0 **且** DB 的 migration id 與目標 manifest 相同，才清除 dirty。
- 失敗時 schema 保持 dirty、crawler 保持 paused，只能用人工的 `reconcile-schema --mark-clean` 與 `resume-crawler` 解除（`deploy/README.md` §5）。
- 已套用的 migration 不自動回滾（I5）。舊版 web 可能不認識新 schema。
- 每個 migration 在自己的 transaction 中執行。本專案禁止 `suppressTransaction` 與 `CONCURRENTLY`（`.github/scripts/check_migrations.py`），這個前提才成立。
- Migration 應向後相容（先擴充、後收縮）。這是規則，不是程式強制；它的理由是 schema-ahead 部署時舊版 web 會在較新的 schema 上運行（S6）。
- 部署前的驗證由 **compat check** 負責（CI 的 `Docker image` job 與 CD 的 `compat` job），在拋棄式 DB 上執行：以 `schema.rebuild` 的 bundle 重建目前的 schema、載入 seed、用目標 bundle 升級、驗證資料與 schema，並跑 forward smoke。細節見 `Docs/testing/test-plan.md` §6。
- 只有 DB 的 migration 歷史與 state 不一致（drift 或 divergent）時，CD 才會拒絕，不會自動修正。

## 7. 部署步驟

```text
1. 在 main 上的 commit 推送 tag（vX.Y.Z）
2. CI（與 PR 相同的測試）→ 建置 web / crawler image，先推送 staging tag → attestation 與驗證 → 建立 release tag（`docker buildx imagetools create --prefer-index=false`，commit point）→ confirm 確認 release tag 解析到 attest 的 digest → 發布 Immutable Release（含 release.json、migrations.txt、各 migration 的 SQL）。細節見 `deploy/README.md` §1.6
3. plan（host 唯讀）與 compat（runner 上）→ 人工檢查 CD summary
4. 在 production 環境核准
5. CD 以 `deploy --detach` 啟動 host 的 deploy，確認接手後由 `deploy-follow` 每 30 秒輪詢 status；host 執行：forward 時 pause crawler、snapshot、migration；切換 web；健康檢查；更新 crawler
6. 驗證：首頁 200、登入、暢銷榜、log 無錯誤
```

完整流程、退出碼與人工程序見 `deploy/README.md`。

回滾：dispatch 較舊的已發布 release。若 DB 比它新，會以 schema-ahead 部署：web 換成舊版，不跑 migration，crawler 不變（S7）。已套用的 migration 不自動回滾（I5），需人工處理（L4）。

## 8. 排程

Crawler 每日 **04:00 (GMT+8)** 執行完整榜單，分類補書每三天執行。EC2 host 時區維持 UTC，使用 `crawler/deploy/crawler.cron` 安裝到 `/etc/cron.d/book-finder-crawler`：

```cron
# 04:00 Asia/Taipei = 20:00 UTC（前一日）
0 20 * * * root /opt/book-finder/run-crawler.sh daily >> /var/log/book-finder/crawler-daily.log 2>&1
0 21 * * * root /opt/book-finder/run-crawler.sh pages --scheduled >> /var/log/book-finder/crawler-pages.log 2>&1
```

- Exit 0 為 SUCCESS 或 PARTIAL_SUCCESS，1 為 FAILED，2 為設定錯誤；Docker／AWS 等啟動錯誤另依其 exit code 記錄。不能只靠 exit 0 判斷所有書都成功，需檢查 summary。
- 分類補書每天台灣時間 05:00 檢查：距上次 exit 0 的 run 啟動時間至少 72 小時才執行，第一次沒有紀錄即執行；非 0 在下一個每日檢查時再試。手動成功執行 pages 也更新紀錄。紀錄保存於 `/var/lib/book-finder/crawler/pages-last-success`，跨月與重啟保留；關機期間不補跑，等待下一次 cron 檢查。
- 兩種模式共用 host `flock`，等待前一次完成才開始。若等待鎖或 EC2 停機，實際開始時間可延後。cron day-of-month `*/3` 不作為三天間隔。
- **與 CD 的協調（N3）**：`run-crawler.sh` 先取得 `db-maintenance.lock`（shared，等待上限 `DB_MAINTENANCE_WAIT_S`，預設 7200 秒），才讀取 state。state 的 `crawler.paused` 或 `schema.dirty` 為真時，以 exit 6 跳過並記錄 `skipped=paused` 或 `skipped=dirty`。state 不存在（尚未 bootstrap）時照舊執行；state 無法讀取時 exit 2（fail closed）。forward migration 期間持有 exclusive lock 的 deploy 會讓爬蟲等待，不會與 migration 交錯。
- **Image 與設定由 CD 管理**：CD 的部署會把 `crawler.conf` 的 `CRAWLER_IMAGE=` 改寫為 GHCR 的 digest，並安裝該 release 的 `run-crawler.sh` 與 `crawler.cron`（release 未附上時跳過）。不要手動改 image tag；手動修改後需以 `resume-crawler` 檢查（`deploy/README.md` §5.3）。
- **啟用排程前須在 EC2 上實測**：手動執行一次 crawler，確認預設 curl fetcher 從 EC2 能取得排行榜頁與商品頁，沒有停在 Cloudflare challenge（`crawler.md` §15）。若被擋下，不啟用排程，評估授權資料管道等替代方案。
- **分類頁清單需隨 crawler runtime 存在**：分類榜補書模式需要 `crawler/category-pages.txt`（預設路徑），或以 `CRAWLER_PAGES_FILE` 指向的檔案存在於執行環境中。
- `crawler/Dockerfile` 打包清單到 `/app/crawler/category-pages.txt`；更新清單需重新發布 image。
- 建置、GHCR 的 digest 管理、EC2 設定、手動驗證與啟用排程的指令見 [crawler 部署說明](../../crawler/deploy/README.md)。啟用前先確認 Docker、AWS CLI、cron service 與 logrotate 可用，且 RDS schema 已由 EF migration 建立。

## 9. Log 與備份

- 所有 container log 輸出至 stdout，使用 Docker `json-file` driver 並設定 `max-size` / `max-file` 輪替；MVP 不接 CloudWatch。
- 一次性 crawler 以 `--rm` 刪除 container，因此歷史 log 由 cron 的 stdout/stderr redirect 保存在 host。`crawler/deploy/crawler.logrotate` 每天輪替、保留 14 份，採 copytruncate（輪替瞬間可能有極短遺失窗口）。Cloudflare 等診斷 HTML／JSON 經 bind mount 保存至 `/var/lib/book-finder/crawler/artifacts/challenges`，需另行管理其磁碟空間與保留期限。
- RDS 自動備份保留 7 天；正式資料修復屬 L4。
