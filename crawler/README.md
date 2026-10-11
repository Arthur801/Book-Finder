# 博客來 crawler

每日取得博客來中文書 7 日 TOP 100，更新 Bestseller 榜單（`Docs/modules/crawler.md`）。正式預設以 curl_cffi 的 Chrome fingerprint 取得頁面，每次請求使用 3～30 秒的隨機間隔，包含第一次和重試，循序抓取。

## 安裝

在 `crawler` 目錄執行：

```bash
pip install -r requirements.txt
# 只有 CRAWLER_FETCHER=browser 或本機瀏覽器測試才需要：
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
| `CRAWLER_FETCHER` | 頁面取得方式：`curl`（預設，curl_cffi Chrome fingerprint）或 `browser`（headless Chromium，僅供診斷）。其他值（含已移除的 `http`）為設定錯誤（exit code 2）。 |
| `CRAWLER_NAV_TIMEOUT_MS` | 瀏覽器導覽逾時，單位毫秒，整數 1～300000，預設 `30000`。空值使用預設；非整數、0、負數或超過上限為設定錯誤（exit code 2）。只影響 `browser` fetcher。 |

## 執行

限制級會員登入頁直接跳過、不重試；log 另列 `restricted_book_count`，不計入 `error_count`，並重設 `consecutive_error_count`；累計錯誤沒有上限，連續 21 本一般錯誤才中止。排名不重新編號。其他 HTTP／解析／DB 錯誤仍遵守重試和榜單保護規則。解析、DB 工作與 retry backoff 計入隨機等待目標；工作超過目標時實際間隔可能超過 30 秒。

```bash
cd crawler
DATABASE_URL=postgresql://... python -m books_crawler
```

Exit code：0 = SUCCESS 或 PARTIAL_SUCCESS（榜單已替換；PARTIAL_SUCCESS 表示有書被跳過，未出現連續 21 本一般錯誤），1 = FAILED（榜單不變），2 = 設定錯誤。

## 只匯入排行榜第一名

沿用上述環境變數，在 `crawler/` 執行：

```bash
../.venv/bin/python -m books_crawler.first_book
```

先抓取並驗證完整的中文書 7 日 TOP 100 排行榜，再只處理 rank 1；其他 99 本不查詢或抓取詳細頁。新書寫入 `books`、`book_sources`、ISBN、作者與分類等關聯資料；既有商品 URL 直接重用，ISBN 命中則只附加來源。此入口不替換 `bestsellers`，不更新既有來源的 `last_seen_at`，不影響每日完整榜單流程。

Exit code：0 = 第一名成功匯入、已存在或為限制級而直接跳過；1 = 抓取／解析／寫入失敗；2 = 設定錯誤。失敗仍沿用最多 3 次嘗試，頁面被判定失敗（challenge、連線異常頁、非 200）時也會保存診斷檔案。log 顯示 `mode=first-book`、第一名 URL、成功的 `book_id` 與 `source_id`。

## 查看 Cloudflare 驗證頁

兩種 fetcher 用同一套規則判定頁面失敗：Cloudflare challenge、無書籍內容的網站連線異常頁（即使 HTTP 200）或非 200。預設 curl fetcher 遇到這些情況會保存 HTML 與診斷 JSON 到 `crawler/artifacts/challenges/`，不產生截圖。以下單頁檢查工具使用 Playwright，需另外安裝 Chromium。

Browser fetcher 判定頁面失敗時，在關閉分頁前自動保存當下的 `.png` 截圖、`.html` DOM 與 `.json` 診斷資料（URL、標題、HTTP status、`cf-mitigated` / `cf-ray` / `content-type`）。預設位置為 `crawler/artifacts/challenges/`，log 會列出絕對路徑；每次嘗試使用不同檔名。保存失敗只記 WARNING，不改變原本的重試／跳過結果。

只查看單一頁面，不需要 `DATABASE_URL`、不寫資料庫、不重試：

```bash
cd crawler
../.venv/bin/python -m books_crawler.inspect_page https://www.books.com.tw/products/0011063006
```

可用 `--output-dir /tmp/books-challenge` 指定輸出位置。Exit code 0 表示正常取得頁面，1 表示抓取失敗（challenge 也算失敗）。以 PNG 查看當時畫面；HTML 保存當下 DOM，不保證離線開啟時外部資源仍可載入。輸出目錄已排除版本控制。

## 測試

```bash
cd crawler
pytest
```

- 測試不連線博客來；瀏覽器測試只開啟本機測試伺服器的頁面。
- 資料庫測試需要 Docker（Testcontainers）與 dotnet SDK。
- 若 Chromium 無法啟動，瀏覽器測試會 skip 並顯示安裝指令，其餘測試照常執行。
