# 實作報告：金石堂 crawler Phase 3 — HTTP acquisition

> 實作紀錄，不是規格。規格以 `crawler/docs/*`（現行 authority）與 [v11 計畫](../plans/kingstone-category-crawler.md) §6～§7、§9 為準；待辦見 `crawler/docs/backlog.md` CB-07「Phase 3 留下的待辦」。

## 變更檔案

| 模組 | 分支／commit | 檔案 | 內容 |
|---|---|---|---|
| P3 acquisition | `kingstone-p3-acquisition` `3dad48d`；merge #137 `9c31d2a`；backlog 前言 `ea95214` | 新增 `crawler/kingstone/acquisition.py`、`crawler/tests/test_kingstone_acquisition.py`；M `crawler/kingstone/urls.py`（`km_code_from_detail_url` 已於 Phase 2 加入）；M `crawler/docs/{architecture,backlog,test-suite,update-history}.md` | `Transport` port、`CurlTransport`、`KingstoneFetcher`：URL 守門、pacing、重試、budget、回應分類；`AcquisitionError`／`AcquisitionFailure` |
| P3 review 修正（程式） | `a9a4c20` | M `crawler/kingstone/acquisition.py`、`crawler/kingstone/urls.py`（新增 `SITE_HOST`）、`crawler/tests/test_kingstone_acquisition.py`（+9 測試，共 96） | budget 每次請求前檢查；libcurl `MAXFILESIZE_LARGE` 與 code 63 映射；移除 IP literal 判斷；Retry-After 數字分支簡化；OVERSIZE helper；docstring 改為實際等待規則 |
| P3 review 修正（docs 與本報告） | 本次 commit | M `crawler/docs/{architecture,backlog,test-suite,update-history}.md`；新增 `Docs/Implementation-Report/kingstone-phase3-acquisition.md` | architecture 還原列表頁與詳細頁段落（與 `kingstone-p2-m4-report` 原文逐字相同）、acquisition 段落精確化；backlog 補 Phase 3 已知缺口；CR-K05 更新；update-history 補列 |

## 實作思路

- **兩層設計**：`Transport` 只負責一次 GET 並回傳 `RawResponse` 或丟出 transport 例外；`KingstoneFetcher` 承擔策略（URL 守門、等待、重試、budget、分類）。`CurlTransport` 是唯一接觸 curl_cffi 的地方，因此策略層可用 fake transport 完整測試。
- **等待合併**：每次請求（含重試）前的等待 = `max(sample_delay − 距上一次請求結束的秒數, retry floor)`，取較大者，不相加。pacing 從上一次請求結束起算；retry floor（backoff 或 Retry-After）從收到失敗回應的當下起算，之後不縮減。這是保守的實作：floor 不扣除 elapsed，因此實際等待可能略長於「從失敗回應起算的最小間隔」。
- **Retry-After**：只在 429、503 且仍會重送時讀取；秒數與 HTTP-date 都支援，HTTP-date 以注入的 wall clock 換算。超過 120 秒（含任何長度的數字）→ `RETRY_AFTER_TOO_LONG`，不提早重送。最後一次嘗試的 Retry-After 不讀，直接 `HTTP_STATUS`。
- **Budget**：每次請求前檢查，包括不需等待的請求。`budget_remaining() <= 0` 或等待超過剩餘 budget → `BUDGET_EXHAUSTED`，不睡、不送。Phase 3 預設 `math.inf`，run 接上前只有單元測試。
- **TLS**：curl `SSLError`（含 `CertificateVerifyError`、`SSL_CONNECT_ERROR`）不重試，直接 `TRANSPORT`。理由是憑證問題不會因重送而消失；這是計畫未明列的實作決定。
- **大小上限（H）**：curl_cffi 的 stream 會把 body 放進背景 thread 的 queue，消費端計數本身擋不住記憶體成長，因此新增 libcurl 層的第一道上限。查證結果見下表。

### H 查證（curl_cffi 0.16.3，`crawler/.venv/lib/python3.14/site-packages/curl_cffi/`）

| 問題 | 證據（檔名:行號） | 結論 |
|---|---|---|
| 能否設定 curl option | `requests/session.py:246`（`Session.__init__` 接受 `curl_options`）、`:276`（存為 `self.curl_options`）、`:755` 與 `:1445`（每次請求的 `set_curl_options(... curl_options=self.curl_options)`）、`requests/utils.py:1042–1044`（逐一 `c.setopt`） | 支援，但只能在 **Session 建立時** 設定，對該 session 的所有請求生效 |
| 能否每個請求設定 | `requests/session.py:850–889`（`request()` 參數表沒有 `curl_options`）；`:1198` 的 `curl_options` 屬於 WebSocket connect，不是 HTTP | **不支援**逐請求設定。因此 `MAXFILESIZE_LARGE` 以 `MAX_RESPONSE_BYTES` 在建立 session 時設定；per-call `max_bytes` 仍由串流計量強制 |
| 選項常數 | `const.py:115`（`MAXFILESIZE_LARGE = 30000 + 117`） | 存在 |
| 超過上限的錯誤碼 | `const.py:544`（`FILESIZE_EXCEEDED = 63`） | 與 libcurl `CURLE_FILESIZE_EXCEEDED` 同值 |
| 63 對應的 Python 例外 | `requests/exceptions.py:176–220`（`CODE2ERROR` 表，不含 63）、`:224–226`（`code2error` 未命中則回傳 `RequestException`）；`exceptions.py:13`（`RequestException(CurlError, OSError)`）；`curl.py:52–59`（`CurlError.code`） | 63 是**基底類別** `RequestException`，以 `.code == CurlECode.FILESIZE_EXCEEDED` 辨識。`CurlTransport` 的 `except RequestException` 分支只攔截 code 63，其他原樣重新丟出 |
| 串流中的錯誤路徑 | `requests/session.py:778–786`（stream 的 `perform` 把 `CurlError` 經 `code2error` 包成例外放入 queue） | 63 在 `iter_content` 中也以同一型別出現，因此串流與請求兩處都要對應 |
| 其他分類（供重試範圍） | `exceptions.py:191`（`SSL_CONNECT_ERROR`→`SSLError`）、`:201`（`RECV_ERROR`→`ConnectionError`，但訊息含 "CONNECT" 時 `code2error` 回 `ProxyError`，`:224–226`）、`:212`（`HTTP2_STREAM`→`HTTPError`）、`:218`（`PARTIAL_FILE`→`IncompleteRead`，`:54`）、`:62`（`DNSError` 為 `ConnectionError` 子類）、`:196`（`GOT_NOTHING`→`ConnectionError`） | 已依此表寫入 architecture 的重試範圍 |

**未驗證**：libcurl 本身在傳輸中（特別是無 Content-Length 的回應）是否依 `MAXFILESIZE_LARGE` 中止，無法在本機以實際傳輸確認（開發環境禁止連網，且未建立 loopback 測試伺服器）。因此：

- 第 (2) 道（libcurl 上限）是額外保護，單元測試只驗證「選項有傳入」與「63 的對應」。
- 第 (3) 道（串流計量超過 per-call `max_bytes` 即中止）是保證 5 MiB 記憶體上限的依據，且有既有測試。
- 此限制已寫入 architecture 與 backlog。

## 執行紀錄（Log）

- `3dad48d` 在整理 Phase 3 文件時，誤刪 `crawler/docs/architecture.md`「金石堂 adapter」下的 **列表頁**（`parse_list_html`）與 **詳細頁**（`parse_detail_html`）整段（Phase 2 的解析契約）。review 發現後，從 `kingstone-p2-m4-report` 原樣取回，放回 Acquisition 段之前；backlog 中「見 architecture『金石堂 adapter』的列表頁段落／詳細頁段落」的指標現在都有對應。
- `ea95214` 是使用者對 #137 的 review：`docs/backlog.md`「CB-07 來源契約」的標題與前言仍寫「尚無金石堂程式」，已改為「已實作的部分以 architecture 為 authority，run／ingestion／runner 仍依本節」。CR-K01 中同樣的敘述也已改寫（grep 確認 `crawler/` 與 `Docs/` 中已無「尚無金石堂」字樣）。
- 本輪 review 修正分兩個 commit：程式（`a9a4c20`）與 docs／本報告（本次 commit）。兩者都在 `kingstone-p3-acquisition` 分支上新增，未 amend，未 push。
- 流程：每項程式修正先寫失敗測試，確認失敗後再實作（TDD）。新增 9 個測試中，6 個在修正前失敗（budget 兩個參數化案例、curl session 的 `MAXFILESIZE_LARGE` 選項、63 映射兩個、63 不重試一個）。其餘 3 個在修正前已通過，保留為迴歸測試：正值 budget 下 wait 為 0 的路徑、其他 curl 例外原樣傳出、Retry-After 極長數字（舊的 sentinel 寫法本來就會回 `RETRY_AFTER_TOO_LONG`）。
- 未讀取 `.env`，未連網，未 push，未修改 `deploy/`、Dockerfile、`books_crawler/*` 行為，未 commit `.venv`。

## 驗證結果

- 完整 pytest（`crawler/`，`../.venv/bin/python -m pytest -q -p no:cacheprovider -rs`）：最後一行 `20151 passed in 84.87s (0:01:24)`，0 skipped（`-rs` 無 SKIPPED 行）。程式 commit `a9a4c20` 與本次 docs commit 的測試數相同（docs commit 不改測試）。
- `test_kingstone_acquisition.py`：96 個測試（`--collect-only` 確認），修正前 87 個。
- `../.venv/bin/ruff check .`：`All checks passed!`。
- `../.venv/bin/ruff format --check .`：`82 files already formatted`。
- `.venv/bin/python .github/scripts/unicode_tables.py --check`（repo 根目錄）：`unicode tables OK (3 file(s))`。
- 未執行：真站抓取、Docker build、部署、dotnet build／test。全部測試離線，使用 fake transport、fake curl session、fake clock 與記錄型 fake sleep。

## 未解決事項

Phase 3 留下的待辦已記入 `crawler/docs/backlog.md` CB-07「Phase 3 留下的待辦」：

- 診斷檔（限額）未實作：計畫 §6 要求有限額，需另定內容、數量與保留期限。
- challenge／CAPTCHA 分類待 fixture：目前 200 照常回傳，由 parser fail closed。
- `budget_remaining` 由 Phase 4 run 提供；Phase 3 預設 `math.inf`，run 接上前 budget 行為只有單元測試。
- 本輪新增：
  - libcurl 傳輸中的大小上限未以真實傳輸驗證（禁止連網），第一道只有選項與錯誤對應的單元測試。
  - TLS 握手中被 reset 若以 `RECV_ERROR` 回報，會被歸為 `ConnectionError` 而重試；此分支沒有測試，也未經真站確認。
  - 最後一次嘗試的 Retry-After 不讀，失敗記為 `HTTP_STATUS`，原因分類可能失真。

## Code Review 與修正

以兩軸 review（Standards：是否符合 repo 文件與程式標準；Spec：是否符合 CB-07、v11 計畫與 Phase 3 規格）檢查 Phase 3 後，依下表處理。「處理」欄為實際落點。

| 軸 | 發現 | 處理 |
|---|---|---|
| Standards | `3dad48d` 誤刪 architecture 的列表頁與詳細頁段落（Phase 2 契約） | 還原（`git show kingstone-p2-m4-report:` 原樣取回，逐字比對相同），本次 commit |
| Standards | `_wait_before_request` 與 class docstring 描述的等待規則與程式不一致（floor 不扣 elapsed） | 保留程式行為（保守），改寫模組 docstring、class docstring 與 architecture：pacing 從上一次結束起算；backoff 與 Retry-After 從收到失敗回應起算；取較大者（`a9a4c20`、本次 commit） |
| Standards | `_HOST` 與 `kingstone/urls.py` 的 `_SITE_HOST` 重複；`_is_ip_literal` 為 dead code（host 完全相等已排除 IP literal） | 新增公開常數 `SITE_HOST`，`urls.py` 與 acquisition 共用，刪除 `_HOST`、`_is_ip_literal` 與 `ipaddress`；docstring 說明原因；IP literal 拒絕測試保留並通過（`a9a4c20`） |
| Standards | Retry-After 的 `{1,9}` 與 sentinel `MAX_RETRY_AFTER_SECONDS + 1` 寫法複雜 | 改為 `[0-9]+` 直接 `float(value)`；新增 20 位數字 → `RETRY_AFTER_TOO_LONG` 測試（`a9a4c20`） |
| Standards | `except TypeError, ValueError, IndexError:` | **未照做**：改為括號寫法後 `ruff format --check` 會把它改回無括號（ruff 的 `target-version = "py314"` 對無 `as` 的 tuple 採 PEP 758 寫法），兩者無法同時成立。保留 formatter 的寫法（與原本相同），因為 format check 是 repo 的檢查。若要括號寫法，需先改 ruff 設定或 target-version，屬於另一個決定 |
| Standards | OVERSIZE 訊息在兩處重複 | 抽成 `_oversize(url, attempt, status=None)`（`a9a4c20`） |
| Standards | `backlog` 標題與前言仍寫「尚無金石堂程式」（#137 review） | `ea95214` 已修正；CR-K01 同步修正（本次確認無殘留） |
| Standards | 常數表不完整（缺 `BACKOFF_BASE_SECONDS`、`RETRYABLE_STATUSES`、`RETRY_AFTER_STATUSES`） | architecture 常數列補上（本次 commit） |
| Standards | `KingstoneFetcher._get` 過長 | **保留**（判斷題）：重試決策、Retry-After 與錯誤分類共用 `attempt` 與 `status` 狀態，拆成多個函式會增加傳遞參數與狀態同步風險；目前測試覆蓋各分支 |
| Spec | parser 契約（列表頁與詳細頁段落）被誤刪，違反 backlog 指標 | 還原（同上） |
| Spec | budget 在不需等待時沒檢查（計畫 §7「每次請求前檢查 soft budget：不足時不發請求」） | 每次請求前檢查 `remaining <= 0 or wait > remaining`；測試覆蓋 pacing 已過但 budget 為 0 與 −1 的兩個參數化案例，以及正值 budget 的正常路徑（`a9a4c20`） |
| Spec | 錯誤訊息描述不精確（未說明只含 URL、狀態與 Location path） | architecture 精確化；程式行為本來已符合，測試既有（本次 commit） |
| Spec | 5 MiB 記憶體上限：串流 queue 無上限，消費端計數擋不住 | 查證（見上表），加入 libcurl `MAXFILESIZE_LARGE` 與 63 映射；Content-Length 預檢與串流計量保留；libcurl 行為未以真實傳輸驗證，寫入 architecture 與 backlog（`a9a4c20`、本次 commit） |
| Spec | 診斷檔有限額未實作 | 記入 backlog CB-07 Phase 3 待辦（已存在，本次確認） |
| Spec | cookie 說明不精確 | 寫明：單次執行內記憶體保存 `Set-Cookie`，與博客來相同；不寫檔、不跨 run；沒有 cookie 子系統（本次 commit） |
| Spec | 重試範圍說明不精確 | 依 curl_cffi `CODE2ERROR` 表寫明重試與不重試的類別；TLS 握手 reset 的分類已知限制寫入 backlog（本次 commit） |
| Spec | 最後一次 Retry-After 的分類可能失真 | **保留**，寫明於 architecture 與 backlog；若要區分需另定錯誤類別，屬於待決策 |
| Spec | 未列入計畫的實作決定（嚴格 UTF-8、Accept-Language、Content-Length 預檢、TLS 不重試、最後一次 Retry-After 不讀、等待取較大者） | architecture「刻意的實作決定」清單逐條標註（本次 commit） |
| 使用者 review #137 | backlog「尚無金石堂程式」（`ea95214`，連同 CR-K01） | 已修正（`ea95214`），本次確認 `crawler/` 與 `Docs/` 無殘留 |
