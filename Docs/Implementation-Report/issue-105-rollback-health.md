# Issue #105：回滾健康檢查與切換失敗的診斷

## 變更檔案

- `deploy/host/bookfinder_host/machine.py`：
  - `_health()` 成為切換後與回滾共用的唯一健康檢查，回傳 `None` 或 `_HealthFailure(stage, status)`（失敗的階段 `local`／`public` 與最後狀態碼；0 表示沒有回應）。預算不變：本機 90 秒，再 `PUBLIC_URL` 90 秒。
  - `_switch()` 健康檢查失敗時，在 `compose down` 或回滾之前寫入 journal：階段、最後狀態碼、web container log 最後 80 行（先遮蔽 secret）。
  - `_rollback()` 回滾後的健康檢查失敗時，寫入階段與最後狀態碼。
  - `_render_env()` 記錄本次 run 的 secret 字串（`_secret_strings`：三個值本身，加上連線字串中 `Password=` 的值，依長度由長到短）。
- `deploy/host/bookfinder_host/ports.py`：`Docker` 介面新增 `web_containers(project)` 與 `logs(container, tail)`。
- `deploy/host/bookfinder_host/adapters.py`：`RealDocker` 實作上述兩者；`logs` 回傳 stdout 加 stderr，`docker logs` 失敗為 `EffectFailed`。
- `deploy/host/bookfinder_host/runtime.py`：找 web container 的 compose label 查詢抽成 `web_container_ids()`，`observe_docker` 改用它（行為不變）。
- `deploy/host/bookfinder_host/testing.py`：`FakeDocker` 新增 `container_ids`、`logs_text`、`logs_error`、`logs_calls`，`docker.logs` 寫入 trace。
- `deploy/tests/host/test_machine.py`：回滾預算（docker 與 cutover、本機與 public、延後恢復、永不恢復）、診斷的內容與順序、secret 遮蔽、`docker logs` 失敗與多個 container 的單行說明。
- `deploy/tests/host/test_adapters.py`：`docker logs` 與 `web_containers` 的 argv 與失敗行為。
- `deploy/README.md`：§3.4 第 9 步、§3.6（切換失敗的診斷）、§4.1 結果表、§6（journal 的內容）。

## 實作思路

- **回滾預算**：審查現有程式時發現，issue 描述的「回滾後只試 3 次、每次 5 秒」與 `651e643` 的行為不符。`_probe_tries`（3 次、每次 5 秒）只用在第 1 步的執行前探測。`_rollback()` 呼叫的 `_health()` 已經是與切換後相同的 90 秒預算。因此這次沒有改預算，而是把「共用同一個函式」寫成明確的 contract，並用測試釘住：回滾在第 3 次輪詢恢復即 `rolled-back`；永不恢復時輪詢 46 次（0 到 90 秒，每 2 秒一次）才 `failed-down`；cutover 與 docker 路徑相同；public 階段的等待也一樣。
- **診斷的時機**：`compose down`（cutover）與 `compose up` 舊 release（docker）都會移除或取代失敗的 container，連同它的 log。所以診斷在 `_switch()` 內、`_web_failed()` 呼叫 `_rollback()` 之前完成。測試用 trace 順序確認 `docker.logs` 在第二次 `compose.up` 或 `compose.down` 之前。
- **遮蔽**：先把 secret 字串逐字換成 `***`，才寫入任何從 container 取得的文字（log 與 `docker logs` 的錯誤訊息）。長的字串先換，避免連線字串的一部分（`Password=`）先被換掉而留下另一部分。env 檔的內容從不寫入。
- **失敗不阻斷**：`docker logs` 或 `docker ps` 失敗、或找到的 container 數量不是 1，都只寫一行說明，然後繼續回滾。
- 只有 `_health()` 失敗才寫 container log。`compose up` 本身失敗不寫，因為那時沒有 container 可以讀。

## 決策

- 沒有改 `HEALTH_BUDGET_S`、`HEALTH_INTERVAL_S` 或 `PROBE_TRIES`。這些值與 README 既有說明一致。
- 沒有為 `RealHttp` 增加例外文字的回報：它把例外轉成狀態碼 0（既有 contract）。journal 因此寫 `0 (no response)`，不寫例外訊息。
- 遮蔽是字串比對。若 secret 在 log 中以不同編碼（例如 URL 編碼）出現，不會被遮蔽。
- 遮蔽在長度極短的 secret（例如單一字元）時也會遮蔽無關文字。這是刻意的：寧可多遮蔽。

## 執行紀錄（Log）

- 分支 `issue-105-rollback-health`，基底 `651e643`（origin/main）。TDD：先寫 13 個 `test_machine.py` 的新測試；實作前 9 個失敗，其餘 4 個回滾預算測試已經通過，證實既有行為。之後再實作。`test_adapters.py` 的 3 個測試是在 adapter 實作之後才補上，沒有先看過紅燈。
- 提交（皆帶 `(#105)`，未 push、未 tag、未 amend）：
  - `569c485` fix(deploy): journal health diagnostics before rollback, mask secrets (#105)
  - `754f3b7` docs(deploy): describe rollback budget and switch diagnostics in the journal (#105)
- 事故背景（cutover run `40074225630-1`，2026-10-24）：新的 web container 沒有通過健康檢查，host 依設計回滾（`compose down`，再 `systemctl start`）。回滾後的健康檢查被記為 `failed-down`（exit 5），但 systemd 版本幾秒後就回 200。根本原因是 SSM 的連線字串格式錯誤，新 container 因此啟動失敗。`compose down` 把 container 與 log 一起刪掉，journal 只留下最後一行，最後只能在 EC2 手動重現才找到原因。本 issue 的診斷會在刪除前把 log 寫入 journal；回滾的判定則與切換後相同。

## 驗證結果

（以下為本次執行的實際輸出。）

- `.venv/bin/python -m pytest .github/scripts/tests deploy/tests -q`：`693 passed, 7 skipped in 6.15s`
- `uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -q`：`624 passed, 7 skipped in 5.78s`
- compileall：`python -m compileall -q deploy/host`（.venv 的 Python）與 `uv run --no-project --python 3.12 python -m compileall -q deploy/host`，皆無錯誤。
- ruff（`uv run --no-project --python 3.12 --with ruff`）：
  - `ruff check --config deploy/ruff.toml deploy`：`All checks passed!`
  - `ruff format --config deploy/ruff.toml --check deploy`：`46 files already formatted`（修正 `test_machine.py` 的一處格式後）
- `BOOKFINDER_IT=1 .venv/bin/python -m pytest deploy/tests -m integration -q -s`：`7 passed, 624 deselected in 264.08s (0:04:24)`，`EXIT=0`。情境 c（壞掉的 web image 回滾）通過，耗時與改動前相同：回滾的健康檢查本來就使用 90 秒預算，因此不需要調整情境 c 的時間預期。
- 清理：`bf-*` 的 container、image、volume、network 皆為 0。`.venv` 未觸碰，`.env` 未讀取。

## 未解決事項

- 遮蔽只是字串比對，無法處理 secret 以 URL 編碼或其他編碼出現在 log 中的情況（見「決策」）。
- 本次沒有在 EC2 上實際重現 cutover 的失敗情境；systemd 路徑只有 unit 測試，整合測試不涵蓋（與既有限制相同）。
- ~~`Docs/Implementation-Report` 的事故紀錄沒有加入 `deploy/README.md` §7.2 的事故表~~：已於下方「2026-10-24 User-Agent 事故與修正」補上（§7.2 第 21 項）。

## 2026-10-24 User-Agent 事故與修正

### 事故

- 兩次 cutover（含 `failed-down`）都在切換後的公開階段失敗。根本原因不是應用程式：host 的健康檢查使用 `urllib`，未設定 User-Agent，送出 `Python-urllib/3.x`。production 站台（edge）對它回 403。
- 驗證：EC2 上 `RealHttp.status(PUBLIC_URL)` 得 403；`curl -A 'Python-urllib/3.12'` 得 403；一般 curl 得 200。
- 本機階段只檢查 `127.0.0.1:5000`，因此從未發現問題。公開階段在 production 從未通過，兩次都因此 `failed-down`。
- 原本的 journal 只寫 `failed at the public stage; last status 403`，沒有說明 403 來自 edge 的 User-Agent 規則。

### 修正（commit `2fb5e27`）

- `config.host_user_agent()`：回傳 `book-finder-deploy/<HOST_API_RANGE 的 max>`，常數 `HOST_USER_AGENT_PRODUCT` 集中在一處。
- `RealHttp`：每個請求預設帶此 UA；呼叫端自行設定的 User-Agent（任何大小寫）保留不覆寫。仍不跟隨 redirect。
- `machine._journal_health_failure()`：公開階段為 4xx 時，額外寫一行 `stage=public status=403 — the edge refused the request; check nginx/WAF rules for the User-Agent`（切換與回滾兩處皆然）。本機階段或 5xx 不寫。
- 測試：`test_adapters.py` 以記錄 header 的本機 `http.server` 驗證送出的 UA、預設值為 HOST_API max、呼叫端 UA 保留、no-redirect 不受影響；`test_machine.py` 驗證公開 403 的提示行（切換與回滾）以及本機失敗不含提示。
- 文件：`deploy/README.md` §3.4（第 3、7 步的 UA 與 edge 放行要求）、§3.6（診斷的 4xx 提示行）、§7.2 第 7 項（nginx 不得依 UA 拒絕）與第 21 項（事故紀錄）。

### 決策

- UA 只在 `RealHttp` 設定一次，不改每個健康檢查呼叫端，因此 `machine.py` 的呼叫點不變。
- 提示行針對所有 4xx，不只 403；文字中的狀態碼取實際值。

### 驗證結果

- `.venv/bin/python -m pytest .github/scripts/tests deploy/tests -q`：`701 passed, 7 skipped`
- `uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -q`：`632 passed, 7 skipped`
- `ruff check --config deploy/ruff.toml deploy`：`All checks passed!`；`ruff format --check`：`46 files already formatted`

### 未驗證

- 尚未在 EC2 上以修正後的 release 實際切換。需確認 host nginx/WAF 放行 `book-finder-deploy/*`（§7.2 第 7、21 項）後，再由人工授權下一次 cutover。
