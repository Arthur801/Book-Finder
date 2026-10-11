# 重構實作報告：Fetcher interface

- 來源：2026-10-11 架構檢視的候選 3「讓 Fetcher interface 說出真正的契約」
- Issue：無（重構，使用者決定不開 issue）
- Branch：直接在 `main`（使用者決定）
- 實作：主 session 以 TDD 直接實作
- 日期：2026-10-11

## 背景

- `Fetcher` Protocol 只寫了 `get`。`cli` 還得呼叫 `close()`、知道三個類別各自的建構參數，並宣告 `HttpFetcher | PlaywrightFetcher | CurlCffiFetcher` 的 Union；`BrowserUnavailableError` 只寫在說明文字裡。
- 三個 adapter：`curl`（正式）、`browser`（Playwright，診斷）、`http`（requests，除錯，會被博客來的 challenge 擋下）。
- 回應判斷各寫一份：curl 判斷 challenge header、challenge 標題且缺內容、連線異常頁；browser 只判斷 header、狀態碼與標題，**不辨識 HTTP 200 的連線異常頁**；http 不判斷 challenge。
- `fetcher.py` 與 `tests/fakes.py` 在模組頂層 import playwright，只用 curl 也必須安裝 Playwright。
- 約 11 個 CLI 測試 monkeypatch 具體類別或 `run_once`；5 處測試直接改寫 `fetcher._context`、`_playwright`。

## 設計決定（使用者逐題確認）

| # | 決定 |
|---|---|
| Q1 | `Fetcher` Protocol 加上 `close()`，docstring 寫明 `FetchError`（單頁失敗）與 `BrowserUnavailableError`（環境無法使用瀏覽器，整次 FAILED） |
| Q2 | `fetcher.create_fetcher(kind, *, navigation_timeout_ms)` 負責建構；`cli` 只解析設定與決定 exit code |
| Q3 | 刪除 `HttpFetcher`；`CRAWLER_FETCHER=http` 改為設定錯誤（exit 2）；移除 `requests` 依賴 |
| Q4 | curl 與 browser 共用回應分類；browser 也把 HTTP 200 的連線異常頁判為 `FetchError`（原本是解析錯誤） |
| Q5 | `PlaywrightFetcher` 搬到 `books_crawler/browser.py`，只有選 browser 時才 import；curl 路徑不需要 Playwright |
| Q6 | `PlaywrightFetcher` 可注入「啟動瀏覽器」的參數，測試不再改寫私有欄位 |
| Q7 | `classify_page(status, headers, html)` 回傳問題種類或 `None`，順序為 challenge → 連線異常頁 → 非 200；錯誤訊息由同一個 helper 產生；browser 對每一種分類失敗都存診斷（含 PNG） |
| Q8 | `create_fetcher(kind, *, navigation_timeout_ms=預設)`；`FetcherKind` 只剩 `CURL`、`BROWSER`；`inspect_page.py` 直接建構 `browser.PlaywrightFetcher` |
| Q9 | `PlaywrightFetcher(..., launch=...)`：`launch` 回傳 `(driver, browser, context)`，預設真的啟動 Chromium；包成 `BrowserUnavailableError` 與關閉順序留在 `PlaywrightFetcher` |
| Q10 | `test_fetcher.py` 改測 `create_fetcher`／`classify_page`；CLI 測試搬到 `test_cli.py`、只替換 `create_fetcher`；browser 測試改用 `launch`，並新增連線異常頁測試 |
| Q11 | README、`deployment.md`、`crawler.md` §15 同步更新；TDD → 雙軸 review → commit 在 `main` |

開工前已告知使用者的兩處調整：

1. Playwright 的 fake 放在獨立的 `tests/browser_fakes.py`（而非 browser 測試檔），因為 `test_db_integration.py` 的瀏覽器崩潰重試測試也要用；`fakes.py` 不再 import Playwright。
2. 「Chromium 啟動失敗會停掉 driver」是預設 `launch` 自己的清理行為，所以這個測試保留替換 Playwright 入口點（`books_crawler.browser.sync_playwright`）；其他測試都用注入的 `launch`。

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/books_crawler/fetcher.py` | 重寫 | `Fetcher`（`get`／`close`＋錯誤契約）、`FetcherKind`（curl／browser）、`create_fetcher`、`PageProblem`／`classify_page`／`page_error`、`save_failure_diagnostics`、`RequestPacer`、`CurlCffiFetcher`；刪除 `HttpFetcher`、`PlaywrightFetcher`、`DEFAULT_USER_AGENT` |
| `crawler/books_crawler/browser.py` | 新增 | `PlaywrightFetcher`（`launch` seam、`diagnostic_dir`）、`launch_chromium`、`BROWSER_USER_AGENT`／`BROWSER_LOCALE` |
| `crawler/books_crawler/cli.py` | 修改 | 改呼叫 `create_fetcher`；docstring 只列 curl／browser |
| `crawler/books_crawler/inspect_page.py` | 修改 | 改從 `browser` import；參數改名 `diagnostic_dir` |
| `crawler/requirements.txt` | 修改 | 移除 `requests` |
| `crawler/tests/test_fetcher.py` | 重寫 | `create_fetcher`、`classify_page`（11 種情況）、錯誤訊息、診斷不拋例外、curl 路徑不載入 Playwright（以全新 Python 行程驗證） |
| `crawler/tests/test_cli.py` | 新增 | CLI 設定、exit code 與 fetcher 關閉，只替換 `cli.create_fetcher` |
| `crawler/tests/browser_fakes.py` | 新增 | `FakeResponse`、`FakePage`、`FakeBrowserContext`、`FakeBrowser`、`FakeDriver`、`launching()` |
| `crawler/tests/test_playwright_fetcher.py` | 修改 | 改用 `launch`；真實瀏覽器的失敗測試改寫到 `tmp_path`；新增連線異常頁、內容讀不到的 header challenge、fake browser 生命週期測試；CLI 與純函式測試移出 |
| `crawler/tests/fakes.py` | 修改 | 移除 Playwright 相關 fake 與 import |
| `crawler/tests/test_db_integration.py` | 修改 | 瀏覽器崩潰測試改用 `launch=launching(context)` |
| `crawler/tests/test_first_book.py` | 修改 | CLI 測試改替換 `create_fetcher` |
| `Docs/modules/crawler.md` | 修改 | §15 介面、共用分類、不再提供 `http`；§15.1 browser 模組、Playwright 只在 browser 模式載入、失敗即存診斷 |
| `Docs/deployment/deployment.md`、`crawler/README.md` | 修改 | `CRAWLER_FETCHER` 只剩 `curl`／`browser`；README 的診斷說明改為共用分類 |

## 實作思路

- **interface 誠實且小**：caller 只需要 `create_fetcher(kind)`、`get`、`close` 與兩種錯誤。seam 有兩個真的 adapter（curl、browser），加上測試的 fake。
- **共用但不洩漏私有名稱**：browser 需要的節流、分類、錯誤訊息與診斷保存都以公開名稱提供（`RequestPacer`、`classify_page`、`page_error`、`save_failure_diagnostics`），沒有跨模組 import 底線開頭的名稱。
- **Playwright 只在需要時載入**：`create_fetcher` 在選 browser 時才 import `browser`（有註解說明的刻意函式內 import）。
- **診斷永不取代原本的錯誤**：每個輸出各自 try；metadata 也在 JSON 輸出的 try 內才組，任何意外只會少一個檔。
- **browser 讀不到 DOM 時**：若狀態碼或 header 已足以判定失敗（例如 header challenge 的頁面正在跳轉），以空內容分類、照樣存診斷並回報 challenge；否則照常包成 `FetchError`。

## 執行紀錄（Log）

1. 讀 `fetcher.py`、`cli.py`、`inspect_page.py`、browser 測試、`fakes.py`、DB 測試與 first-book 測試，確認耦合點。
2. 兩輪 grilling（Q1～Q11），使用者全部採用建議。
3. 先寫 `test_fetcher.py`、`test_cli.py`、`browser_fakes.py`，改寫 browser 測試與其他呼叫點（紅：`books_crawler.browser` 不存在）。
4. 重寫 `fetcher.py`、新增 `browser.py`、改 `cli.py`／`inspect_page.py` → 277 passed（含真實 Chromium 測試，沒有 skip）。
5. 確認沒有殘留引用、測試沒有寫進 repo 的 artifacts 資料夾；移除 `requests`；更新文件。
6. 雙軸 code review，修正後重跑（見下節）。

## 驗證結果

- `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`：**280 passed**，沒有 skip。
- `git diff --check` 通過；import 檢查只剩 `create_fetcher` 的刻意函式內 import（原本 HEAD 的 `test_playwright_fetcher.py:588` 已隨 CLI 測試移除）。

| 設計要求 | 結果 | 對應測試 |
|---|---|---|
| `FetcherKind` 只有 curl、browser；`http` 為設定錯誤 | ✅ | `test_fetcher_kinds_are_the_documented_values`；`test_unknown_fetcher_is_a_configuration_error[http]` |
| `create_fetcher` 依 kind 建構，browser 不啟動 | ✅ | `test_curl_kind_builds_the_production_fetcher`、`test_browser_kind_builds_the_playwright_fetcher_without_starting_it` |
| curl 路徑不載入 Playwright | ✅ | `test_the_curl_path_does_not_import_playwright` |
| 共用分類的順序與各情況 | ✅ | `test_classify_page`（11 組） |
| 錯誤訊息一致 | ✅ | `test_page_error_messages` |
| 診斷失敗不取代原本錯誤 | ✅ | `test_diagnostics_never_raise_even_when_the_metadata_cannot_be_built`；curl 與 browser 既有的目錄失敗測試 |
| browser 辨識連線異常頁並存診斷 | ✅ | `test_connection_error_page_is_a_fetch_error_and_saves_diagnostics` |
| browser 讀不到 DOM 時 header challenge 仍回報並存診斷 | ✅ | `test_header_challenge_is_reported_and_saved_even_when_the_page_content_cannot_be_read` |
| browser 非 200 也存診斷 | ✅ | `test_non_200_response_raises_fetch_error_and_saves_diagnostics` |
| CLI 只替換 `create_fetcher`；各種 fetcher 都會關閉 | ✅ | `test_cli.py` 全部 |
| 測試不再改寫私有欄位 | ✅ | `grep` 無 `_context =`／`_playwright =` |
| curl 的請求參數、節流、重試與跳過不變 | ✅ | `test_curl_fetcher.py`、DB 與真實 fixture 整合測試 |

## Code Review 與修正

雙軸審查（Standards、Spec）平行執行，兩軸都沒有硬性違規；主 session 核對後處理：

| 軸 | 發現 | 處理 |
|---|---|---|
| Spec | `save_failure_diagnostics` 的 metadata 在 try 外組成，出錯會取代原本的 `FetchError` | 移進 JSON 輸出的 try；新增測試先紅後綠 |
| Spec | browser 先讀 `page.content()`：header challenge 的頁面若正在跳轉，會變成通用錯誤且不存診斷（比舊版退步） | 讀不到 DOM 時以狀態碼與 header 分類；新增測試先紅後綠 |
| Spec | fake launch 回傳的 browser 是 `None`，與 `browser` 屬性說明不符 | 新增 `FakeBrowser`；新增測試 |
| Spec／Standards | `crawler.md` §15.1 仍寫「介面不變：`get`」，與 §15 不一致 | 改為「同 §15（`get` 與 `close`）」 |
| Standards | `DEFAULT_CHALLENGE_DIR` 名稱已不準 | 改名 `DEFAULT_DIAGNOSTIC_DIR`（路徑不變，註解說明資料夾名稱的由來） |
| Standards | `BrowserSession = tuple[Any, Any, Any]` 與欄位退化為 `Any` | alias 改為精確型別，欄位恢復 `Playwright | None` 等 |
| Standards | `PageProblem` 的字串值沒有用到 | 改用 `auto()` |
| Standards | 「取例外訊息第一行再遮罩」重複兩次 | 抽成 `_first_line` |
| Standards | `ACCEPT_LANGUAGE` 公開但只有本模組使用 | 改為 `_ACCEPT_LANGUAGE` |
| Standards | `test_cli.py` 的 `FakeFetcher` 與 `fakes.FakeFetcher` 同名；`stub` 名稱太籠統 | 改名 `FakeClosingFetcher`、`stub_factory_and_run` |
| Standards | browser 建構測試沒有 try／finally | 補上 |
| Spec | `challenge_dir` 改名 `diagnostic_dir`、browser 診斷 JSON 多了 `fetcher` 欄位、curl 改為每個檔各記一行 log 且 HTML 失敗仍會寫 JSON | 保留：讓兩個 adapter 的參數、欄位與行為一致 |
| Standards | `url, status, headers, html` 常一起傳（Data Clumps）；兩個 adapter 的 `get` 都是 wait／try／finished 的包裝 | 保留：只有三個函式、兩個 adapter，包成值物件或共用基底的收益不大 |

修正後重跑：**280 passed**；`git diff --check` 通過。

## 未解決事項

1. **資料夾名稱**：診斷檔仍放在 `crawler/artifacts/challenges/`，現在也包含連線異常頁與非 200 的頁面。改路徑會影響使用者既有的查看習慣，本次只改了常數名稱。
2. **`fetcher.py` 的公開面變寬**：為了讓 `browser.py` 不 import 私有名稱，節流、分類與診斷都改為公開。若日後想讓 seam 更窄，可以把這些共用部分抽到獨立模組。
3. **EC2 實測（#21）**：仍未完成；本次重構不影響正式 curl fetcher 的請求方式。
