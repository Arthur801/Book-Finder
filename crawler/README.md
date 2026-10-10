# 博客來 crawler

每日取得博客來中文書 7 日 TOP 100，更新 Bestseller 榜單（`Docs/modules/crawler.md`）。頁面以 Playwright 驅動的 headless Chromium 取得（`Docs/architecture/architecture-decisions.md` ADR-006）。

## 安裝

在 `crawler` 目錄執行：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Linux 若回報缺少系統函式庫，需以 root 執行一次（僅限本機或 EC2 初次設定）：

```bash
sudo python -m playwright install-deps chromium
```

## 設定

| 環境變數 | 說明 |
|---|---|
| `DATABASE_URL` | 共用 PostgreSQL 連線字串（必填；不會寫入 log）。 |
| `CRAWLER_FETCHER` | 頁面取得方式：`browser`（預設，headless Chromium）或 `http`（requests，僅供除錯；博客來會回傳 Cloudflare challenge）。其他值為設定錯誤（exit code 2）。 |
| `CRAWLER_NAV_TIMEOUT_MS` | 瀏覽器導覽逾時，單位毫秒，整數 1～300000，預設 `30000`。空值使用預設；非整數、0、負數或超過上限為設定錯誤（exit code 2）。只影響 `browser` fetcher。 |

## 執行

```bash
cd crawler
DATABASE_URL=postgresql://... python -m books_crawler
```

Exit code：0 = SUCCESS 或 PARTIAL_SUCCESS（榜單已替換；PARTIAL_SUCCESS 表示有 1～10 本被跳過），1 = FAILED（榜單不變），2 = 設定錯誤。

## 測試

```bash
cd crawler
pytest
```

- 測試不連線博客來；瀏覽器測試只開啟本機測試伺服器的頁面。
- 資料庫測試需要 Docker（Testcontainers）與 dotnet SDK。
- 若 Chromium 無法啟動，瀏覽器測試會 skip 並顯示安裝指令，其餘測試照常執行。
