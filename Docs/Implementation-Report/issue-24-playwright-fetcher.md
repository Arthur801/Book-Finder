# Issue #24 實作報告：Crawler Playwright 瀏覽器 fetcher

- Issue：#24
- Branch：issue-24-playwright-fetcher
- 實作 agent：Claude Haiku（subagent）
- 日期：2026-10-11

## 變更檔案

| 檔案 | 類型（新增/修改/刪除） | 說明 |
|---|---|---|
| `crawler/books_crawler/fetcher.py` | 修改 | 新增 `PlaywrightFetcher`（headless Chromium，同步 API）、`BrowserUnavailableError`、challenge 判斷 `_is_challenge_page`；`HttpFetcher` 新增 `close()`（關閉 session），其餘行為不變。 |
| `crawler/books_crawler/cli.py` | 修改 | 預設使用 `PlaywrightFetcher`；`CRAWLER_FETCHER=http` 切回 `HttpFetcher`；其他值 exit 2；`run_once` 外以 `try/finally` 保證 `fetcher.close()`。run 流程、exit code 1/0 不變。 |
| `crawler/requirements.txt` | 修改 | 加入 `playwright==1.63.0`（已於 WSL Python 3.14.4 安裝驗證）。 |
| `crawler/README.md` | 新增 | 安裝（含 `python -m playwright install chromium`）、`DATABASE_URL` / `CRAWLER_FETCHER` 設定、執行與測試指令。 |
| `crawler/tests/test_playwright_fetcher.py` | 新增 | 25 個測試：本機 HTTP server 上的瀏覽器測試（14 個，Chromium 不可用時 skip）、challenge 判斷單元測試、CLI 接線測試（無需瀏覽器）。 |
| `Docs/Implementation-Report/issue-24-playwright-fetcher.md` | 新增 | 本報告。 |

未變更：`run.py`、`db.py`、`ranking.py`、`parsers.py`、`Docs/modules/crawler.md`（§15 已描述本實作，無需改規格）、任何 C# 程式與 EF migration。

## 實作思路

### 生命週期

- `PlaywrightFetcher()` 建構時不啟動任何東西；第一次 `get` 才啟動 Playwright driver、Chromium 與一個 browser context，之後整個 instance 共用。
- 每次 `get` 在共用 context 中開一個 page，取得 HTML 後立即關閉該 page。
- `close()` 依序關閉 context → browser → Playwright driver，每一步都在 `try/finally` 中，任一步失敗仍會嘗試後續步驟；可重複呼叫，未啟動過時為 no-op。
- 支援 `with PlaywrightFetcher() as f:`，離開 `with` 區塊（含例外）即 `close()`。
- CLI：`fetcher.close()` 放在 `run_once(deps)` 的 `finally`，因此 SUCCESS、FAILED、以及例外都會關閉瀏覽器。
- `browser` 唯讀屬性僅供測試確認瀏覽器確實關閉；啟動前與關閉後為 `None`。

### 等待策略

- 使用 `page.goto(url, wait_until="load", timeout=...)`。理由：spec 寫「頁面載入完成後的 HTML」，`load` 等待 page script 執行完成（含會在 load 前後改寫 DOM 的腳本），之後 `page.content()` 才是完整 DOM。`domcontentloaded` 較早返回，可能拿到尚未執行完的 challenge 腳本頁面。代價是等待時間較長，由 timeout 限制。
- 導覽逾時預設 30 秒（`DEFAULT_NAVIGATION_TIMEOUT_MS`），建構參數 `navigation_timeout_ms` 可設定。

### Challenge 判斷

依序檢查，任一成立即拋出 `FetchError`（不做任何繞過）：

1. 導覽回應 header `cf-mitigated` 的值（忽略大小寫與前後空白）為 `challenge`。
2. 導覽回應為 `None`，或 HTTP status 不是 200（`HTTP <code>`）。
3. 載入完成後，`_is_challenge_page(title, has_page_content)` 為真：標題包含「歡迎光臨博客來」**且** 頁面沒有 `.main_column`（排行榜頁與商品頁的主要內容容器，已由真實 fixtures 確認存在）。標題單獨出現、但頁面仍有主要內容時不視為 challenge（有測試覆蓋此邊界）。

導覽時的 Playwright `Error`（含 timeout、net::ERR_*）包成 `FetchError`，訊息為 `GET <url> failed: <ExceptionClassName>`。

注意：「歡迎光臨博客來」標題取自 issue 描述，尚未在真實博客來頁面上觀察驗證（依 AGENTS.md 不得連線博客來）；`.main_column` 則由既有 fixtures 確認。

### 間隔與可注入的 sleep / clock

- 循序請求。第一次 `get` 不等待；之後每次 `get` 前，計算 `delay_seconds - (clock() - 上一次 get 結束時間)`，若為正才 `sleep`。
- 以「上一次 get 結束」為基準（比「開始對開始」嚴格）：即使兩次 `get` 之間已有時間流逝，仍保證至少間隔設定的秒數。
- `sleep`（預設 `time.sleep`）與 `clock`（預設 `time.monotonic`）皆為建構參數；測試以假 clock/sleep 驗證，不實際等待。預設間隔 1.0 秒。

### User-Agent 與語系

- `BROWSER_USER_AGENT`：一般桌面 Chrome UA（Windows 10 x64）。主版本號 153 對應本次安裝的 Chromium（`chromium-1243`，Chrome for Testing 153.0.8010.12），升級 `playwright` 時需同步更新。
- `new_context(user_agent=..., locale="zh-TW")`。`HttpFetcher` 的 `DEFAULT_USER_AGENT` 未修改。
- 未使用任何 stealth / anti-detection 設定：未修改 `navigator.webdriver`、未加入 `--disable-blink-features` 等啟動參數、未使用 stealth 外掛、CAPTCHA 代解或 proxy。未加入 `--no-sandbox`（見未解決事項）。

### 規格未定義而自行決定之處（明確列出）

1. `wait_until="load"`（而非 `domcontentloaded`）。
2. 導覽 timeout 預設 30 秒。
3. 間隔以「上一次 `get` 結束」為基準。
4. challenge 判斷的具體規則（header 優先；標題 + 無 `.main_column`）。
5. `BrowserUnavailableError(RuntimeError)`：Chromium 無法啟動時拋出，訊息包含 `python -m playwright install chromium`。它不是 `FetchError`，因此不會被當成「單頁抓取失敗」而進入重試/跳過；目前 `run_once` 會以 `except Exception` 記為整次 FAILED。
6. 每次 `get` 開新 page、用完即關，而非重用同一個 page。
7. `CRAWLER_FETCHER` 值不合法 → exit code 2（沿用既有 `EXIT_CONFIG_ERROR`）；大小寫與前後空白不敏感；未設定預設 `browser`。
8. 新增 `HttpFetcher.close()` 與 CLI 的 `finally`，讓兩種 fetcher 有一致的關閉行為。
9. 版本 pin：`playwright==1.63.0`（PyPI 目前最新穩定版，`pip install --dry-run` 確認可在 Python 3.14 安裝）。

## 執行紀錄（Log）

1. 讀取 issue #24（`gh api repos/Arthur801/Book-Finder/issues/24 --jq .body`）、AGENTS.md、CONTEXT.md、ADR-006、`crawler.md` §1/§6/§15、deployment §3、test-plan、既有 fetcher/cli/tests 與 fixtures README。確認 worktree 乾淨，位於 `issue-24-playwright-fetcher`。
2. `pip install --dry-run playwright` → 解析為 `playwright-1.63.0`，可於 Python 3.14 安裝。
3. `pip index versions playwright` → 最新 1.63.0。
4. `pip install playwright==1.63.0`（共用 venv `~/Documents/vs_repos/Book-Finder/.venv`）→ `Successfully installed greenlet-3.5.6 playwright-1.63.0 pyee-13.0.1`。
5. `python -m playwright install chromium` → 下載 Chrome for Testing 153.0.8010.12（`chromium-1243`）與 Chrome Headless Shell，exit 0。未使用 sudo。
6. 煙霧測試：以 `sync_playwright` 啟動 headless Chromium，`set_content` 後 `page.content()` 正常，版本 153.0.8010.12。**不需要 `install-deps`，即系統函式庫已足夠。**
7. 實作 `fetcher.py`、`cli.py`，修改 `requirements.txt`，撰寫 `tests/test_playwright_fetcher.py`、`crawler/README.md`。
8. `pytest crawler/tests -q -p no:cacheprovider`（第一次完整執行）→ `172 passed in 32.66s`，無 skip。
9. `pytest crawler/tests/test_playwright_fetcher.py -v` → 25 passed（見驗證結果）。
10. 以 `PLAYWRIGHT_BROWSERS_PATH=/tmp/no-such-browsers` 模擬 Chromium 缺失 → `11 passed, 14 skipped`；skip 訊息含 `python -m playwright install chromium` 與 `sudo ... install-deps chromium` 指令。不依賴 Chromium 的 11 個測試仍全部通過。
11. `dotnet build`（worktree 根目錄）→ `0 Warning(s)`、`0 Error(s)`。
12. `docker ps -a` 檢查 → 無殘留 testcontainers（僅有既有開發用容器 `book-finder-db-1`，於本工作開始前即已運行）。
13. 未執行 CLI 端到端（會連線博客來，違反 AGENTS.md 與 issue 規定）；CLI 接線以單元測試驗證。

## 驗證結果

### Acceptance criteria（issue #24）

| 條件 | 結果 | 對應測試 |
|---|---|---|
| 正常頁面 → 回傳完整 HTML | ✅ | `test_normal_page_returns_html_after_load` |
| 模擬 challenge 頁 → 拋出 fetch 失敗例外 | ✅ | `test_cloudflare_challenge_raises_fetch_error[/challenge-title]`、`[/challenge-header]`、`[/challenge-header-403]`；邊界：`test_challenge_title_on_a_page_with_content_is_not_a_challenge` |
| HTTP 非 200 → 拋出 fetch 失敗例外 | ✅ | `test_non_200_response_raises_fetch_error[/missing-HTTP 404]`、`[/unavailable-HTTP 503]` |
| 逾時 → 拋出 fetch 失敗例外 | ✅ | `test_navigation_timeout_raises_fetch_error` |
| 連續兩次 `get` 至少間隔設定秒數（可注入 sleep / clock，不真的等待） | ✅ | `test_consecutive_gets_are_separated_by_the_delay_without_real_waiting` |
| 例外發生時瀏覽器仍會被關閉 | ✅ | `test_browser_is_closed_when_a_get_raises`、`test_browser_is_closed_when_an_unrelated_exception_escapes`；CLI：`test_cli_closes_fetcher_when_the_run_raises`、`test_cli_closes_fetcher_when_the_run_fails_normally` |
| 既有 run 流程測試（fake fetcher）全部通過 | ✅ | 既有 `test_run_unit.py`、`test_e2e_real_fixtures.py` 等，全套 172 通過 |
| Chromium 缺失時瀏覽器測試以明確訊息 skip，不影響其他測試 | ✅ | 以空 browsers 目錄模擬：`11 passed, 14 skipped`（skip 訊息見執行紀錄 10） |
| `pytest` 通過 | ✅ | 見下方 pytest 摘要 |
| 實作報告寫入 `Docs/Implementation-Report/` | ✅ | 本檔 |

另有：`test_missing_chromium_raises_browser_unavailable_with_install_hint`（不需 Chromium 即可執行，確認缺少瀏覽器時的錯誤訊息）、`test_browser_uses_desktop_user_agent_and_zh_tw_locale`、`test_one_browser_is_reused_across_gets`、`test_close_without_any_get_is_a_safe_no_op`、`test_challenge_detection_needs_the_title_and_no_page_content`（4 組參數）、`test_cli_uses_browser_fetcher_by_default`、`test_cli_switches_to_http_fetcher_with_environment_variable`、`test_cli_rejects_unknown_fetcher_as_configuration_error`。

### 瀏覽器測試是否實際執行

- **實際執行**。Chromium 153.0.8010.12 已安裝於 `~/.cache/ms-playwright`，未使用 sudo。全套測試中沒有 skip。
- 本次安裝不需要 `playwright install-deps`。若在其他機器上缺少系統函式庫，測試會 skip 並顯示：`sudo ~/Documents/vs_repos/Book-Finder/.venv/bin/python -m playwright install-deps chromium`。

### 指令結果

- `~/Documents/vs_repos/Book-Finder/.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`（worktree 根目錄）：
  **`172 passed in 32.66s`**
- `python -m pytest crawler/tests/test_playwright_fetcher.py -v`：`25 passed in 6.61s`
- `dotnet build`：0 Warning(s)，0 Error(s)
- 測試容器殘留：無。

## 未解決事項與後續注意

1. **EC2 實測（屬 #21）**：未在 EC2 驗證；從雲端 IP 存取博客來仍可能被 challenge（ADR-006 Migration impact）。本實作未處理。
2. **Docker image（未做）**：crawler image 需含 Chromium 與 Playwright（建議官方 Playwright Python image，deployment §3）。本 issue 不在範圍。
3. **沙箱設定**：未加入 `--no-sandbox`。若在 root 容器內執行，Chromium 可能無法啟動，需以非 root 使用者執行，或由 image 設定 user namespace；不應為此直接關閉沙箱而不評估。
4. **challenge 信號未實機驗證**：「歡迎光臨博客來」標題與 `cf-mitigated` header 是依 issue 與 ADR-006 的描述；本次未連線博客來確認真實 challenge 頁的樣貌。上線前應由人工以 EC2 或本機瀏覽器觀察一次，必要時調整 `CHALLENGE_TITLE` / `PAGE_CONTENT_SELECTOR`。
5. **與 issue #7（重試與跳過）的介面**：#7 應只把 `FetchError` 視為「單頁抓取失敗」並進入重試。`BrowserUnavailableError` 不是 `FetchError`，會直接使整次 run 失敗，這是預期行為（瀏覽器不可用不應被當成個別書籍跳過）。
6. **瀏覽器版本與 UA**：`BROWSER_USER_AGENT` 的 Chrome 主版本需與 `playwright` pin 所安裝的 Chromium 同步更新。
7. **Log 中的 `using browser fetcher`**：CLI 新增一行 INFO log，未改變其他 log 或 exit code。
8. **未修改 spec**：`Docs/modules/crawler.md` §15 與 ADR-006 已與實作一致，未做改動。`crawler/tests/fixtures/README.md` 未改動。（註：後續審查修正時，§15 與 ADR-006 已依使用者決定更新，見下方。）

## Code Review 與修正

本節記錄協調者審查（Standards + Spec）中與 #24 fetcher 相關的發現與修正。修正由 #7 agent 在整合分支（`issue-7-crawler-retry-skip`，#24 之上）完成，提交於 #7 之後。

| 項目 | 發現 | 處理 |
|---|---|---|
| UA 決定（D1） | 桌面 Chrome UA 與 `zh-TW` 語系需要使用者決定 | 使用者核准保留（2026-10-11）。ADR-006 補充此決定；`AGENTS.md` §1.3 與 `crawler.md` §15 加入一句；其他反偵測措施（stealth 外掛、`navigator.webdriver` / fingerprint 修補、CAPTCHA 代解、代理輪替）仍禁止 |
| 例外包裝（A1） | `new_page()` 位於 try 之外；`page.close()` 失敗可能遮蔽原始錯誤；只有部分 Playwright 錯誤被包裝；driver / Chromium 啟動失敗未包裝 | `new_page()` 移入 try；所有 `PlaywrightError`（含 `TargetClosedError`，它是 `Error` 的子類）包成 `FetchError`，因此瀏覽器崩潰會進入 #7 的重試與跳過；`page.close()` 與 context / browser / driver 的 close 由 `_close_quietly` 記錄但不拋出；driver 與 launch 失敗包成 `BrowserUnavailableError`，它仍不是 `FetchError`，因此不會被重試（有 run 層級測試） |
| 導覽逾時可設定 | 預設 30 秒，無法在執行時調整 | 新增環境變數 `CRAWLER_NAV_TIMEOUT_MS`（整數 1～300000，空值為預設，其他值 exit 2）；`crawler/README.md` 與 `Docs/deployment/deployment.md` §5 已記錄 |
| `CRAWLER_FETCHER` 值 | 字串比對 | 改為 `FetcherKind`（StrEnum：`browser` / `http`，值不變）；未知值仍 exit 2 |
| 測試的 skip 訊息 | 寫死開發者的 venv 路徑 | 改為通用指令 `sudo python -m playwright install-deps chromium`（於已安裝 Playwright 的環境執行） |
| 新增測試 | — | 非瀏覽器測試：new_page 崩潰、導覽崩潰、page.close 失敗不遮蔽、driver 啟動失敗、launch 失敗會停止 driver、context close 失敗仍停止 driver、timeout 參數傳遞、非法 timeout、`FetcherKind` 值；瀏覽器測試：瀏覽器中途消失 → `FetchError`，之後 `close()` 安全 |

### 未處理的後續事項（本次審查新增的註記）

- 瀏覽器中途崩潰後，`PlaywrightFetcher` 不會自動重新啟動瀏覽器；之後每次 `get` 都是 `FetchError`。在 #7 的 early abort 下會快速變成 FAILED。詳見 `issue-7-crawler-retry-skip.md` 的未解決事項。

## 後續更新（2026-10-11）：預設改用 curl_cffi，Playwright 改為診斷用

> 本節接續原報告，記錄 PR #26 合併後依使用者指示所做的變更。上文保留當時的實作紀錄。上文提到的 ADR-006，以及之後的 ADR-007、ADR-008，已於 2026-10-11 從 `Docs/architecture/architecture-decisions.md` 刪除；現行規則一律以 `Docs/modules/crawler.md` §15 為準。上文與本節有衝突時（例如「預設使用 `PlaywrightFetcher`」「預設間隔 1.0 秒」），以本節與 `crawler.md` 為準。

### 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `crawler/books_crawler/fetcher.py` | 修改 | 新增 `CurlCffiFetcher`；三種 fetcher 改用隨機間隔；新增網站連線異常頁的判斷 |
| `crawler/books_crawler/cli.py` | 修改 | `FetcherKind` 新增 `curl`，並設為預設；新增 `first_book` 參數 |
| `crawler/books_crawler/first_book.py` | 新增 | 只匯入榜首的入口（`crawler.md` §13.1） |
| `crawler/books_crawler/inspect_page.py` | 新增 | 用 Playwright 抓單一頁面並保存驗證頁診斷，不存取 DB、不重試 |
| `crawler/requirements.txt` | 修改 | 加入 `curl_cffi==0.16.3` |
| `crawler/tests/test_curl_fetcher.py` | 新增 | curl fetcher 的離線測試 |
| `crawler/tests/test_playwright_fetcher.py` | 修改 | 隨機間隔、診斷輸出與 CLI 接線 |
| `.gitignore` | 修改 | 忽略 `/crawler/artifacts/`（診斷輸出） |

### 正式 curl_cffi fetcher

- `CRAWLER_FETCHER=curl` 為預設。釘選 `curl_cffi==0.16.3`，整個 run 共用一個 `Session(impersonate="chrome")`，使用 zh-TW Accept-Language，保留 TLS 驗證，timeout 30 秒。循序執行，不自動跟隨 redirect，3xx 一律視為抓取失敗。
- 以下情況都包成 `FetchError`：非 200、`cf-mitigated: challenge`、challenge 標題且缺主要內容容器，以及沒有內容的網站連線異常頁（即使是 HTTP 200）。
- 一般 HTTP、challenge 或網站錯誤時保存原始 HTML 與部分 JSON 資訊，不提供 PNG；保存失敗不會取代原本的抓取例外。
- curl 不執行 JavaScript，也不會自動切換 fingerprint。

### 可選的 Playwright fetcher

- `CRAWLER_FETCHER=browser` 仍是上文描述的 headless Chromium 同步 API 實作，並沿用使用者核准的一般桌面 Chrome UA 與 zh-TW locale；`CRAWLER_NAV_TIMEOUT_MS` 可設定 1～300000 ms，預設 30000。
- 遇到 `cf-mitigated: challenge`，或 challenge 標題且沒有 `.main_column` 時，在 page 關閉前保存 HTML、PNG 與 JSON。檔名使用 timestamp 加 UUID，避免重試互相覆蓋。只保存指定的回應 headers，不保存 cookie 或 request headers。檔案放在被 Git 忽略的 `crawler/artifacts/challenges/`。單一輸出失敗不影響其他輸出，也不會遮蔽 `FetchError`。

### 節流

- 三種 fetcher（curl、browser、http）預設每次請求（含第一次與重試）都獨立取樣 uniform(3,30) 秒，取代上文的固定 1.0 秒。
- 從前一次請求結束起算，解析、DB 工作與 backoff 的時間都計入間隔；若已超過目標就不再額外 sleep，所以實際間隔可能超過 30 秒。
- clock 與 sleep 可注入，方便離線驗證；固定 delay 只供 browser／http 的本機診斷使用。

### 入口

- 每日：`python -m books_crawler`
- 只匯入榜首：`python -m books_crawler.first_book`（只寫 Catalog，不更新榜單）
- 查看驗證頁：`python -m books_crawler.inspect_page URL --output-dir PATH`（使用 Playwright，不存取 DB、不重試）

重試與中止由 run 負責：單本最多三次；限制級直接跳過並重設計數；連續一般錯誤第 21 本才中止，累計錯誤沒有上限（見 `issue-7-crawler-retry-skip.md` 的後續更新）。

仍未使用 stealth 外掛、`navigator.webdriver` 修補、CAPTCHA 代解或代理 IP 輪替。`http` 是手動的 requests 診斷入口，仍沿用 requests 的自動 redirect 行為；只有正式的 curl fetcher 明確禁止 redirect。

### 驗證

- `test_curl_fetcher.py` 用 fake session 與 clock 驗證：session 設定、第一次與重試的節流、3／30 秒邊界、WAF 的 HTTP 200 頁、非 200、拒絕 redirect、例外遮罩與診斷失敗。
- `test_playwright_fetcher.py` 用本機頁面與 fake context 驗證：DOM、challenge 截圖、檔名唯一、逾時、cleanup 與 CLI 接線。測試不連線博客來。
- 2026-10-11 執行 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **258 passed in 38.64s**，沒有 skip。`git diff --check` 通過。
- 使用者授權的真實本機 run 保存在 `crawler/artifacts/verification/top100-random-20261011T001507Z/summary.json`：完整處理 100 個排名，實際請求 85 個不同的來源 URL，重用 15、成功新增 66、限制級 13、一般錯誤 6；最終 Catalog 與 Bestseller 各 81 筆。前一次請求完成到下一次開始的最短間隔為 3.133 秒，取樣值都在 3～30 秒內。這是改成連續錯誤政策之前的結果，也不代表每一本書都能抓到。

### 未解決事項更新

1. 原第 1 項（EC2 實測）仍未完成，驗證對象改為預設的 curl fetcher。人工用 Chrome 能進入，不代表 headless browser 或其他 IP／session 也能通過；最初的 browser 抓取曾收到 `cf-mitigated` 並保存了診斷。
2. 原第 2 項（Docker image）仍未實作。預設的 curl 模式不需要 Chromium，但 `fetcher.py` 在模組頂層 import playwright，所以 Playwright Python 套件仍是必要依賴（2026-10-11 code review 指出）。
3. 原第 3～8 項維持不變。其中第 4 項（challenge 信號未在真實頁面驗證）也適用於 curl fetcher，因為它沿用同樣的 challenge 標題判斷；其餘各項只與可選的 browser fetcher 有關。
4. 每日 cron 與 production 尚未驗證。

### Code Review 與修正（2026-10-11）

依雙軸 code review 修正下列項目，行為不變：

| 項目 | 發現 | 修正 |
|---|---|---|
| 重複程式碼 | `CurlCffiFetcher._save_failure` 與 `PlaywrightFetcher._save_challenge` 各自組出 timestamp／UUID 檔名，也各自篩選並遮罩回應 headers | 抽出 `_new_diagnostic_base()`（建立目錄並回傳唯一檔名）、`_diagnostic_headers()` 與常數 `DIAGNOSTIC_HEADERS`，兩個 fetcher 共用；檔名格式、保存的欄位與 log 訊息不變 |
| 寫法不一致 | `_wait_for_request`、`CurlCffiFetcher.__init__` 與 `session.get(...)` 用對齊縮排，與檔案內其他函式「一參數一行、結尾逗號」的寫法不同 | 統一為既有寫法 |
| import 順序 | `fetcher.py` 的 stdlib import 未排序；`cli.py`、`test_playwright_fetcher.py` 的 `CurlCffiFetcher` 不在字母順序上；`test_playwright_fetcher.py` 的 `json` 排在 `socket` 後面，另在 fake 的 `screenshot()` 內 import `Path` | 依字母順序排列，`Path` 改在檔案頂端 import |
| 測試替身命名 | `test_curl_fetcher.py` 的 fake 叫 `Response`、`Session`，不符合 `tests/fakes.py` 的 `Fake*` 慣例 | 改名為 `FakeCurlResponse`、`FakeCurlSession`（`FakeResponse` 已被 Playwright fake 使用） |
| 引號 | `test_curl_fetcher.py` 使用單引號字串，既有程式用雙引號 | 改為雙引號；含雙引號的字串維持原樣 |

重跑 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **259 passed**；`git diff --check` 通過。

第二輪修正（同日，行為不變）：

| 項目 | 發現 | 修正 |
|---|---|---|
| 隱性旗標 | `_wait_for_request(delay=None)` 的 `None` 同時代表「每次隨機取樣」與「第一次請求也要等」，三個 fetcher 也各自保存 `_last_finished`、`_sleep`、`_clock` | 改為 `_RequestPacer` 類別：`fixed_delay=None` 時，取樣函式與「第一次也等待」分別存成 `_next_target`、`_wait_before_first` 兩個具名屬性；三個 fetcher 都只呼叫 `wait()` 與 `finished()`。移除 `PlaywrightFetcher._wait_for_delay` |
| 私有函式跨模組引用 | `inspect_page.py` import 了 `cli._configure_logging` | 改名為公開的 `cli.configure_logging()`，並補上 docstring |

重跑 `.venv/bin/python -m pytest crawler/tests -q -p no:cacheprovider`，結果 **259 passed**；`git diff --check` 通過。
