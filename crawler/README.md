# 博客來 crawler

每日取得博客來中文書 7 日 TOP 100，更新 Bestseller 榜單（`Docs/modules/crawler.md`）。正式預設以 curl_cffi 的 Chrome fingerprint 取得頁面，每次請求使用 3～30 秒的隨機間隔，包含第一次和重試，循序抓取。

## 安裝

Docker Hub → EC2 → cron 的完整步驟見 [部署說明](deploy/README.md)，使用 [Dockerfile](Dockerfile) 與 `deploy/` 內的執行腳本、cron、logrotate 範本。

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
| `CRAWLER_PAGES_FILE` | 分類榜補書模式（`books_crawler.pages`）的分類頁清單路徑。未設定或空白時使用 `crawler/category-pages.txt`；相對路徑以執行時的工作目錄解析。其他模式忽略此變數。 |

本 README 提供三個執行入口：

| 指令（於 `crawler/` 執行） | 用途 | 規則 |
|---|---|---|
| `python -m books_crawler` | 每日完整榜單 | `crawler.md` §1～§12 |
| `../.venv/bin/python -m books_crawler.first_book` | 只匯入排行榜第一名 | `crawler.md` §13.1 |
| `python -m books_crawler.pages` | 分類榜補書 | `crawler.md` §16 |

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

## 分類榜補書（pages mode）

從博客來各分類的 7 日暢銷榜頁面補充 Catalog 的新書。此模式不是 Bestseller：不寫入 `bestsellers`，不更新 `last_seen_at`，不保存分類排名（`crawler.md` §16）。

```bash
cd crawler
python -m books_crawler.pages
```

分類頁清單是 `crawler/category-pages.txt`（或 `CRAWLER_PAGES_FILE` 指向的檔案）。編輯方式：

- 每行一個 URL，例如 `https://www.books.com.tw/web/sys_saletopb/books/01/?attribute=7&loc=P_0002_002`。
- 以 `#` 開頭的行是註解；空行會被忽略；前後空白會被去除；重複的 URL 只保留第一次。
- URL 必須是 `https://www.books.com.tw/web/sys_saletopb/books/<兩位數分類>/?attribute=7`，可加上 `loc` 參數；其他 query 參數不允許。
- 新增或移除分類只要修改這個檔案，不需要改程式。

清單在發出任何請求前驗證；有任何不合格的行、檔案無法讀取或清單為空時，log 會列出原因，exit code 為 2。

單一分類頁抓取或解析失敗（抓取重試 3 次後仍失敗，或頁面不是分類榜）會被跳過，其餘分類頁照常處理。只有無法繼續的情況（例如資料庫查詢錯誤、browser 無法啟動，或所有分類頁都失敗）才會 FAILED。Exit code：0 = SUCCESS 或 PARTIAL_SUCCESS，1 = FAILED，2 = 設定錯誤。log 以 `mode=pages` 開頭，格式見 `crawler.md` §16.8。

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
ruff check .
ruff format --check .
```

- `ruff check .` 與 `ruff format --check .` 與 CI 的 `Lint and format` 相同（ruff 版本由 `requirements.txt` 釘定）。
- 測試不連線博客來；瀏覽器測試只開啟本機測試伺服器的頁面。
- 資料庫測試需要 Docker（Testcontainers）與 dotnet SDK。
- 若 Chromium 無法啟動，瀏覽器測試會 skip 並顯示安裝指令，其餘測試照常執行。
