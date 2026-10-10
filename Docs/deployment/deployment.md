# Deployment

> Path: `Docs/deployment/deployment.md`
> Authority: Runtime 環境、AWS 資源、Docker、secrets、TLS、migration、排程、備份
> 系統拓樸見 `Docs/architecture/system-architecture.md`。
> 本文件涉及的 production 操作屬 `AGENTS.md` L4：需明確授權，agent 不得自行執行。

## 1. 環境

| 環境 | Database | Secrets |
|---|---|---|
| Local | `compose.yaml` 的 `pgvector/pgvector:pg17`（只綁 `127.0.0.1`） | `.env`（不進 repository）、`dotnet user-secrets` |
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

## 3. Containers（EC2 上的 compose）

| Service | Image | 說明 |
|---|---|---|
| `nginx` | nginx | 對外 80 / 443；TLS 終止；80 只做 ACME 驗證與轉址 HTTPS；轉發至 `web` |
| `web` | 自建 ASP.NET Core | 只在 compose 內部網路曝露，不直接對外 |
| `crawler` | 自建 Python，含 Playwright 與 Chromium（ADR-006） | 不常駐；由 cron 以 `docker compose run --rm crawler` 啟動。建議以 Playwright 官方 Python image 為基礎；執行期間需約 1 GB 記憶體 |

`web` 必須設定 Forwarded Headers，只信任 `nginx` 的位址（`identity-auth.md` §7 rate limiting 依賴正確的 client IP）。

`web` image 必須包含 tzdata（`/usr/share/zoneinfo`），並保留 ICU（除非以 invariant globalization 執行），以便以 `Asia/Taipei` 顯示 `captured_at`（`bestseller.md` §4）。若執行環境找不到該時區，程式會退回固定 UTC+08:00（台灣無夏令時間，顯示結果相同），不會因此回 500。

## 4. TLS（nginx + ZeroSSL）

- 憑證由 host 上的 `acme.sh` 向 ZeroSSL 簽發（需先以 email 註冊 ZeroSSL 帳號），使用 webroot 驗證（nginx 提供 `/.well-known/acme-challenge/`）。
- `acme.sh` 自帶的 cron 自動續期；續期後執行 `docker compose exec nginx nginx -s reload`。
- nginx：只開 TLS 1.2 / 1.3；HTTP 一律 301 至 HTTPS；`web` 端另有 HSTS。
- 網域名稱以 `<your-domain>` 表示，不寫入 repository。

## 5. Secrets

| 參數（SSM path 範例） | 用途 |
|---|---|
| `/book-finder/prod/db-connection` | RDS 連線字串 |
| `/book-finder/prod/openai-api-key` | OpenAI |
| `/book-finder/prod/google-books-api-key` | Google Books |
| `/book-finder/prod/jwt-signing-key` | JWT HS256 key（至少 32 bytes 隨機值） |

- 部署 / 啟動時由 host script 以 EC2 IAM role 讀取 SSM，寫入 `/run/book-finder/env`（tmpfs，`chmod 600`），compose 以 `env_file` 注入。
- Crawler 只拿 DB 連線字串，不拿 OpenAI / Google Books / JWT key。
- 任何 secret 不得進 repository、image、log。

## 6. Migration

- 使用 `dotnet ef migrations bundle` 產生 `efbundle` 可執行檔，隨版本一起建置。
- 部署時作為**獨立步驟**手動執行，成功後才啟動新版 `web`；`web` 啟動時**不**自動 migrate。
- 對 production RDS 執行前需明確授權（`AGENTS.md` §2.3）。
- 執行前先在拋棄式資料庫（本機 compose 或 Testcontainers）以相同 bundle dry run。
- Migration 應向後相容（先擴充、後收縮），讓舊版 `web` 在 migration 後仍可運作，以便回滾 image。

## 7. 部署步驟

```text
1. 本機：dotnet test、pytest 通過
2. 建置 web / crawler image（帶版本 tag）與 efbundle
3. 推送 image 至 EC2（registry 或 docker save / load）
4. 若有 migration：dry run → 取得授權 → 對 RDS 執行 efbundle
5. 更新 compose 的 image tag，docker compose up -d web nginx
6. 檢查：首頁 200、登入、暢銷榜、log 無錯誤
```

回滾：compose 改回上一個 image tag 重啟。Migration 已套用且不相容時，依該 migration 的 rollback 計畫處理（L4，需授權）。

## 8. 排程

Crawler 每日 **04:00 (GMT+8)**。EC2 host 時區維持 UTC，crontab：

```cron
# 04:00 Asia/Taipei = 20:00 UTC（前一日）
0 20 * * * cd /opt/book-finder && docker compose run --rm crawler >> /var/log/book-finder/crawler.log 2>&1
```

- 非 0 exit code 代表 run FAILED（`crawler.md` §11）。
- 同時間只會有一個 crawler（每日一次、run 時間遠小於 24 小時），MVP 不加鎖。
- **啟用排程前須在 EC2 上實測**：手動執行一次 crawler，確認瀏覽器 fetcher 從 EC2 能取得排行榜頁與商品頁，沒有停在 Cloudflare challenge（ADR-006、#21）。若被擋下，不啟用排程，回到 #21 評估替代方案。

## 9. Log 與備份

- 所有 container log 輸出至 stdout，使用 Docker `json-file` driver 並設定 `max-size` / `max-file` 輪替；MVP 不接 CloudWatch。
- RDS 自動備份保留 7 天；正式資料修復屬 L4。
