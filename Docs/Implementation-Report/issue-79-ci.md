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

- `ci.yml` 於 PR 與 push 到 `main` 時執行，同一 ref 的舊 PR 執行會被取消。
- `.NET build and tests`：`dotnet restore`、`dotnet build -c Release`、`dotnet test --no-build`，trx 結果上傳為 artifact。整合測試以 Testcontainers 啟動 pgvector，ubuntu-latest 提供 Docker。
- `Crawler tests`：需要 .NET SDK，因為 `crawler/tests/conftest.py` 會執行 `dotnet tool restore`、`dotnet build` 與 `dotnet ef` 來產生 schema。安裝 Playwright Chromium 後執行 pytest，JUnit XML 上傳為 artifact。
- NuGet 快取：專案沒有 `packages.lock.json`，`setup-dotnet` 內建的快取無法產生 key，因此改用 `actions/cache` 直接快取 `~/.nuget/packages`。
- pip 快取：使用 `setup-python` 的 `cache: pip`。

### M2：格式與 lint（#81）

- `dotnet format Book-Finder.slnx --verify-no-changes`：`.editorconfig` 的規則；本模組修正 `SchemaTests.cs` 的空白。
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

## Code Review 與修正

- 主 agent 已逐一審查各模組：以 actionlint 檢查 workflow，重跑 lint，比對 `books_crawler/` 的變更確認行為不變，以 `gh api` 確認 action 版本，並以 schema 驗證 `dependabot.yml`。
- 兩軸 Code Review（Standards／Spec）結果：待補
