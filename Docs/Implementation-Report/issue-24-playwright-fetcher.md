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
8. **未修改 spec**：`Docs/modules/crawler.md` §15 與 ADR-006 已與實作一致，未做改動。`crawler/tests/fixtures/README.md` 未改動。
