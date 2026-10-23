# Issue #79 CI：實作報告

- Issue：#79 CI（GitHub Actions 持續整合）
- 規格：本票無獨立計劃文件。依 `Docs/testing/test-plan.md` §6（執行）與 `AGENTS.md` §4（風險等級與驗證）實作；CD 不在範圍內。
- 日期：2026-10-23
- 分工：
  - 主 agent：規劃、派工、驗收、repo 設定、撰寫文件。
  - Haiku subagent：實作 M1～M3，以及 CI 失敗後的修正。
  - 每個模組完成後，主 agent 親自執行 actionlint、重跑 lint、比對 `books_crawler/` 的變更、以 `gh api` 確認 action 版本，並以 schema 驗證 `dependabot.yml`。
- PR：每個模組一個 PR，base 都是 `main`。
  - #80 M1：CI workflow（`.github/workflows/ci.yml`，.NET 與 crawler 兩個 job）。
  - #81 M2：格式與 lint（修正 .NET 與 Python 的格式違規，新增 `lint` job）。
  - #82 M3：安全性（Dependabot 與 CodeQL）。
  - 本報告另開 PR。

## 變更檔案

| 模組 | 檔案 | 說明 |
|---|---|---|
| M1 #80 | `.github/workflows/ci.yml` | 新增 `.NET build and tests` 與 `Crawler tests` 兩個 job；NuGet 與 pip 快取；trx 與 JUnit XML 上傳為 artifact（`if: always()`） |
| M1 #80 | `.gitignore` | 忽略 `/crawler/test-results/` |
| M2 #81 | `.github/workflows/ci.yml` | 新增 `Lint and format` job |
| M2 #81 | `tests/DatabaseIntegration/SchemaTests.cs` | `dotnet format` 修正空白 |
| M2 #81 | `crawler/ruff.toml`（新增） | target `py314`、line-length 165 |
| M2 #81 | `crawler/requirements.txt` | 釘定 `ruff==0.17.2` |
| M2 #81 | `crawler/` 下 19 個檔案 | `ruff format`；AST 比對無差異 |
| M2 #81 | `crawler/` 下 56 處違規 | ruff 修正（production code 行為不變，見下） |
| M3 #82 | `.github/dependabot.yml`（新增） | nuget、pip、github-actions、docker 四種 ecosystem |
| M3 #82 | `.github/workflows/codeql.yml`（新增） | csharp（manual build）、python、actions 三種語言 |
| 本報告 | `Docs/testing/test-plan.md` §6、`crawler/README.md`、`Docs/requirements/product-requirements.md` | 說明實際 CI，並更正「無 CI」的敘述 |

## 實作思路

### M1：CI workflow（#80）

- `ci.yml` 於 PR 與 push 到 `main` 時執行，同一 ref 的舊 PR 執行會被取消。push 到 `main` 則依 commit 分組，每個 merge commit 各自保有結果（review 後修正）。
- `.NET build and tests`：`dotnet restore`、`dotnet build -c Release`、`dotnet test --no-build`，trx 結果上傳為 artifact。整合測試以 Testcontainers 啟動 pgvector，ubuntu-latest 提供 Docker。
- `Crawler tests`：需要 .NET SDK，因為 `crawler/tests/conftest.py` 會執行 `dotnet tool restore`、`dotnet build` 與 `dotnet ef` 來產生 schema。安裝 Playwright Chromium 後執行 pytest，JUnit XML 上傳為 artifact。
- NuGet 快取：專案沒有 `packages.lock.json`，`setup-dotnet` 內建的快取無法產生 key，因此改用 `actions/cache` 直接快取 `~/.nuget/packages`。`.NET build and tests` 與 `Crawler tests` 兩個 job 都有此快取（review 後為 crawler job 補上）。
- pip 快取：使用 `setup-python` 的 `cache: pip`。

### M2：格式與 lint（#81）

- `dotnet format Book-Finder.slnx --verify-no-changes`：使用 dotnet format 內建的預設規則（repo 沒有 `.editorconfig`）；本模組修正 `SchemaTests.cs` 的空白。
- ruff：
  - `ruff==0.17.2` 釘定在 `crawler/requirements.txt`，CI 由該檔案讀取版本，作為單一來源。
  - `crawler/ruff.toml`：target `py314`、line-length 165。
  - 修正 56 個 ruff 違規，`ruff format` 處理 19 個檔案。
- line-length 165 的理由：既有程式中有 40 行超過 120 字元、11 行超過 140 字元。以 `ruff format --diff` 比較，變動行數在 120 時為 370、140 時為 293、165 時為 265，165 是變動最少的設定。
- production code 只有三類變動，行為不變：
  - `timezone.utc` 改為 `UTC`。
  - 移除未使用的 import。
  - `books_crawler/run.py` 有三處刻意的 broad except，加上 `# noqa: BLE001` 與理由。crawler 的錯誤計數規則（`AGENTS.md` §1.3、CRAWL-05）需要這些 except。
- 測試端的調整：
  - `BookDraft` 補 import。它只用於 annotation，因為有 `from __future__ import annotations`，原本的測試即使缺少 import 也能通過。
  - `check=False` 明示預設值。
  - 未使用的解包變數改為 `_`。
  - `dict()` 改為 literal。
  - 合併巢狀 `with`。

### M3：安全性（#82）

- `dependabot.yml`：
  - 四種 ecosystem：nuget（根目錄與 `/tests/*`）、pip（`/crawler`）、github-actions、docker（`/crawler`，repo 中唯一的 Dockerfile）。
  - 每週一更新，上限 5 個 PR。
  - minor 與 patch 分組，減少 PR 數量。
- `codeql.yml`：
  - csharp 使用 manual build 模式，因為 CodeQL 的 autobuild 無法可靠地偵測 .NET 10。
  - python 與 actions 使用 `build-mode: none`。
  - 於 PR、push 到 `main` 與每週一 03:27 UTC 執行。

## 執行紀錄（Log）

- **首次 CI 失敗（crawler job）**：GitHub 上 crawler job 結果為 320 passed、51 errors。
  - 原因：`crawler/tests/conftest.py` 執行的 `dotnet ef migrations script` 經過 `Program.cs:21-22`，要求 `ConnectionStrings:DefaultConnection`。本機這個值由 user-secrets 提供，CI 上沒有。
  - 修正（commit `0e0e7a5`）：只對該 subprocess 傳入 placeholder `ConnectionStrings__DefaultConnection`，一律覆寫，讓 schema 不依賴開發者的 secrets。
  - 驗證：placeholder 產生的 SQL 與本機產生的 SQL byte-identical。以 `ASPNETCORE_ENVIRONMENT=CI DOTNET_ENVIRONMENT=CI` 模擬沒有 user-secrets 的環境，結果 371 passed。
  - 修正後以 merge forward 同步至 M2（`conftest.py` 衝突，保留 `check=False` 與 `env=env`）與 M3。
- **Playwright 安裝耗時**：PR #80 首次執行 `playwright install --with-deps chromium` 花了 8 分 40 秒。log 顯示 apt 下載 25.9 MB 的速度只有 51.7 kB/s，判斷是鏡像站偶發變慢。之後各次 crawler job 總計約 1.5～2 分鐘，未另行處理。

## 驗證結果

- 本機測試：UnitTests 697 passed、DatabaseIntegration 113 passed、WebIntegration 261 passed（0 skipped）。
- crawler：371 passed。
- actionlint：0 error。
- `dependabot.yml`：通過 schemastore `dependabot-2.0` schema 驗證。
- GitHub 上 #80、#81、#82 的所有 checks 皆通過；CI log 中 crawler 結果均為 371 passed。
- Repo 設定（由使用者於 GitHub 完成）：
  - Dependabot alerts 已開啟（API 回傳 204）。
  - ruleset `Main protection`（active，套用於 default branch）：
    - 禁止 force push 與刪除分支。
    - 必須經 PR 合併，0 approvals。
    - required checks 為 `.NET build and tests`、`Crawler tests`、`Lint and format`，不要求 up to date。
    - code scanning 使用 CodeQL，門檻為 errors 與 high_or_higher。

## 未解決事項

- CD 未做（L4，需要 production 授權與部署計畫，見 `Docs/deployment/deployment.md`）。
- `Analyze (…)` 未列為 required check，由 ruleset 的 code scanning rule 涵蓋。
- Playwright 瀏覽器未快取，偶發變慢時會拖長 `Crawler tests` job。
- 各 job 未設定 `timeout-minutes`，使用預設值 360 分鐘。
- 各 job 重複 `setup-dotnet` 與 NuGet 快取步驟；未抽成 composite action，也未建立 `global.json`。屬判斷題，本次未處理。
- Dependabot docker 只涵蓋 `crawler/Dockerfile`，未涵蓋 `compose.yaml` 中的 `pgvector/pgvector:pg17` image。

## Code Review 與修正

- 主 agent 已逐一審查各模組：以 actionlint 檢查 workflow，重跑 lint，比對 `books_crawler/` 的變更確認行為不變，以 `gh api` 確認 action 版本，並以 schema 驗證 `dependabot.yml`。
- 兩軸 Code Review（範圍 `23f7aeb...60948db`），主 agent 逐項驗證：
  - Standards：無違反文件規範（AGENTS.md §2.3：無 secret、未關閉安全機制、`permissions: contents: read`、使用 `pull_request` 而非 `pull_request_target`；`books_crawler/` 行為不變，broad except 保留）。
    - 已修正：`ci.yml` 註解引用不存在的 `.editorconfig`（報告同步修正）；lint job 以 grep 取 ruff pin，找不到時改為明確失敗。
    - 不成立：「`ruff.toml` 未 select，只跑預設 E/F，`# noqa: BLE001` 無作用」——以 `ruff check --show-settings` 確認 ruff 0.17.2 讀取 `crawler/ruff.toml`、啟用 407 條規則，含 BLE001、PLW1510、UP017、SIM117；「cache key 的 `dotnet-tools.json` 不在根目錄」——該檔位於 repo 根目錄。
    - 判斷題未處理：各 job 重複 setup-dotnet＋NuGet cache；dependabot 各 ecosystem 設定重複（不支援 anchor）；`test_page_list.py` 分類表被 ruff 拆成每行一對。
  - Spec：#79 範圍內項目皆已實作；第二次執行命中快取（main push run 39918278421 有 `Cache hit for: nuget-Linux-…`，pip 由 restore-key 還原）。
    - 已修正：crawler job 缺少 NuGet 快取；main 的 push run 被 concurrency 取消（run 39918259137，merge #81），改為 push 依 commit 分組。
    - 範圍外但合理保留：CodeQL 每週排程、concurrency 設定、Dependabot 分組與上限。
