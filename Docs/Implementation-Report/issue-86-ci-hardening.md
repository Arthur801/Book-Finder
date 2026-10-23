# Issue #86 CI 強化：實作報告

- Issue：#86 CI 強化（版本與 pin 的一致性）
- 規格：本票無獨立計劃文件。依 `Docs/testing/test-plan.md` §6（CI 執行）、`Docs/deployment/deployment.md` 與 `AGENTS.md` §4（風險等級與驗證）實作；延續 #79 CI 的既有 workflow，不改變 CI 的 job 結構。
- 日期：2026-10-23
- 分工：
  - 主 agent：規劃、派工、驗收、以 `gh api` 反查 action SHA、以 `gh run` 確認 CI log、撰寫文件。
  - Haiku subagent：實作 M1～M4，以及 review 後的修正。
  - 每個模組完成後，主 agent 親自執行 actionlint、重跑 sync 檢查的正反案例、比對 SDK 與 EF 工具版本。
- 背景與優先順序：
  - P1：`dotnet-ef` 10.0.12 落後 EF Core 10.0.13。Dependabot PR #85 只更新 csproj，不會更新 `dotnet-tools.json`，兩者版本會分岔。
  - P2：GitHub Actions 使用 mutable major tag（如 `@v7`），tag 移動時 CI 行為會改變而無紀錄。
  - P3：.NET SDK 未固定。`setup-dotnet` 會安裝的 SDK 取決於 runner 當下的版本。
  - P3（評估後由 P2 降級）：`compose.yaml` 的 `pgvector/pgvector:pg17` 是浮動 tag。`pg17` 不是 SemVer，單純把 compose 加入 Dependabot 不會產生更新；真正的問題是同一個浮動 tag 寫死在 5 處。
- 使用者決定：版本不一致時 CI 失敗；四項（M1～M4）全做。
- PR：每個模組一個 PR，base 都是 `main`，後一個 PR 疊在前一個之上。
  - #87 M1：dotnet-ef 版本同步與 sync 檢查腳本。
  - #88 M2：Actions 改為完整 commit SHA pin。
  - #89 M3：pgvector image 固定為 `0.8.7-pg17`，並新增 Dependabot `docker-compose` ecosystem。
  - #90 M4：新增 `global.json`，固定 .NET SDK 版本。
  - 本報告另開 PR。

## 變更檔案

| 模組 | 檔案 | 說明 |
|---|---|---|
| M1 #87 | `dotnet-tools.json` | dotnet-ef 10.0.12 → 10.0.13 |
| M1 #87 | `.github/scripts/check_version_sync.py`（新增） | 版本同步檢查，stdlib only；`CHECKS` 清單；錯誤輸出 `::error::` 並 exit 1；可傳入 repo root 供測試 |
| M1 #87 | `.github/workflows/ci.yml` | `lint` job 執行 sync 檢查 |
| M2 #88 | `.github/workflows/ci.yml`、`.github/workflows/codeql.yml` | 17 行 `uses:` 改為 40 字元 SHA，同行加上 `# vX.Y.Z` 版本註解 |
| M3 #89 | `compose.yaml` | `pgvector/pgvector:pg17` → `pgvector/pgvector:0.8.7-pg17` |
| M3 #89 | `tests/DatabaseIntegration/PostgresFixture.cs`、`tests/WebIntegration/WebFixture.cs`、`crawler/tests/conftest.py` | 測試用 image 與 compose 同步為 `0.8.7-pg17` |
| M3 #89 | `.github/dependabot.yml` | 新增 `docker-compose` ecosystem（schema 驗證通過） |
| M3 #89 | `.github/scripts/check_version_sync.py` | 新增第二項檢查：測試用 image 必須等於 compose 的 image |
| M3 #89 | `.github/workflows/ci.yml` | `lint` job 另以 ruff 檢查 `.github/scripts`（範圍外，見 Code Review） |
| M3 #89 | 3 份文件 | 同步記載 pgvector image 版本 |
| M4 #90 | `global.json`（新增） | `"version": "10.0.113"`，`rollForward: latestPatch` |
| M4 #90 | `.github/workflows/ci.yml` | 4 處 `setup-dotnet` 改用 `global-json-file` |
| M4 #90 | 文件 | 記載 SDK 版本與手動升級流程 |
| 本報告 | `Docs/Implementation-Report/issue-86-ci-hardening.md` | 本檔 |

## 實作思路

### M1：dotnet-ef 版本同步（#87）

- `dotnet-tools.json` 的 dotnet-ef 升至 10.0.13，與 EF Core 10.0.13 一致。
- 驗證：`dotnet ef migrations script --idempotent` 在升級前後的輸出 byte-identical；原本「tools older than runtime」的警告消失。
- `check_version_sync.py`：
  - 以 `CHECKS` 清單集中定義檢查項目，之後新增檢查只需加入清單。
  - 第一項：`dotnet-tools.json` 的 dotnet-ef 版本必須等於 csproj 中 `Microsoft.EntityFrameworkCore.Design` 的版本。
  - 任一檢查失敗時輸出 `::error::`（GitHub Actions annotation）並 exit 1。
  - 接受 repo root 作為參數，測試時可指向暫存目錄。
  - 只用標準函式庫，不需要額外安裝步驟。

### M2：Actions 完整 SHA pin（#88）

- 17 行 `uses:` 改為完整 40 字元 commit SHA，並在同一行保留 `# vX.Y.Z` 註解，方便人工辨識版本。
- 6 個 action 的 SHA 皆與當時 major tag 指向的 commit 相同，行為不變：

  | action | 版本 |
  |---|---|
  | `actions/checkout` | v7.0.1 |
  | `actions/setup-dotnet` | v6.0.0 |
  | `actions/setup-python` | v7.1.0 |
  | `actions/cache` | v6.1.0 |
  | `actions/upload-artifact` | v7.0.2 |
  | `github/codeql-action` | v4.39.1 |

- 每個 SHA 以 `gh api repos/<owner>/<repo>/commits/<tag>` 反查，確認與 tag 指向一致。

### M3：pgvector image 固定（#89）

- `pgvector/pgvector:pg17`（浮動 tag）改為 `pgvector/pgvector:0.8.7-pg17`。兩者 digest 同為 `sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d`，因此實際映像檔內容不變。
- 同一版本寫死在 compose 與 3 個測試來源（`PostgresFixture.cs`、`WebFixture.cs`、`conftest.py`）。sync 檢查第二項要求測試來源必須與 compose 相同，之後只改其中一處時 CI 會失敗。
- Dependabot 新增 `docker-compose` ecosystem，可追蹤 compose 中的 image 更新。
- 範圍外：`lint` job 另以 ruff 檢查 `.github/scripts/`。範圍小且合理，保留（見 Code Review）。

### M4：.NET SDK 固定（#90）

- 新增 `global.json`，指定 SDK 10.0.113。
- 4 處 `setup-dotnet` 改用 `global-json-file`，CI 不再依賴 runner 上的預設 SDK。
- 選用 `rollForward: latestPatch`（而非原計畫的 `latestFeature`），原因見執行紀錄。
- 不加入 Dependabot `dotnet-sdk` ecosystem。自動升級會讓 apt 尚未跟上的本機 SDK 無法建置，因此 SDK 升級改為手動。
- 代價：本機必須是 10.0.1xx band 且版本 ≥ 10.0.113。原計畫是任何 10.x 皆可。

## 執行紀錄（Log）

- **`rollForward: latestFeature` 無效（M4，review 後修正）**：
  - 原計畫使用 `latestFeature`。Standards 與 Spec review 皆指出 CI 仍會安裝 10.0.402。
  - 主 agent 讀取 setup-dotnet v6.0.0 `src/setup-dotnet.ts` 的 `getVersionFromGlobalJson` 確認：`latestFeature` 會被對應為 `${major}.${minor}`（即 `10.0`），取得最新的 band；`latestPatch` 對應為 `${major}.${minor}.${feature}xx`（即 `10.0.1xx`）。
  - 改為 `latestPatch`（commit `404c284`）。之後 PR #90 的 CI log 顯示下載 `dotnet-sdk-10.0.113-linux-x64.tar.gz`，確認符合預期。
- **修正前的實際差異**：修正前 CI 安裝的是 SDK 10.0.402，本機為 10.0.113。兩者的 runtime 皆為 10.0.13（依 Microsoft release metadata，10.0.13 release 同時包含 SDK 10.0.402 與 10.0.113）。這證實 P3 不只是理論風險。
- **sync 腳本 review 修正（commit `89e2eb3`）**：
  - csproj 解析錯誤原本會輸出 Python traceback，改為 `::error::` 訊息。
  - EF Design 套件沒有 `Version` 屬性時，給出明確的錯誤訊息，而非 KeyError。
  - compose 的 regex 改為只認未註解的 `image:` 行，並容許引號包住的值。
- **sync 腳本正反案例驗證**：
  - 反例（應失敗）：dotnet-ef 與 EF Core 版本不一致；tool 未宣告；package 未宣告；compose 升為 `0.8.8` 但測試來源仍為 `0.8.7`（3 個錯誤）；單一測試檔仍為 `pg17`；compose 沒有 pgvector image；csproj 格式錯誤；EF Design 沒有 `Version`；被註解掉的 `image:` 行。
  - 正例（應通過）：目前 repo 狀態；引號包住的 image 值。

## 驗證結果

- 本機測試（M3 狀態）：UnitTests 697 passed、DatabaseIntegration 113 passed、WebIntegration 261 passed。
- crawler：371 passed。
- actionlint：0 error。
- sync 檢查：正反案例皆符合預期（見執行紀錄）。
- `dotnet ef migrations script --idempotent`：M1 升級前後 byte-identical。
- Action SHA：以 `gh api` 反查 6 個 action 的 tag，SHA 皆一致；13 個 SHA 皆有同行版本註解且與 tag 相符。
- `dependabot.yml`：`docker-compose` ecosystem 通過 schema 驗證。
- GitHub CI：#87、#88、#89 的所有 checks 皆通過；#90 的 CI log 顯示 SDK 為 10.0.113。

## 未解決事項

- **Dependabot 與 sync 檢查的衝突（使用者選擇的取捨）**：Dependabot 升級 EF 或 compose image 的 PR 會被 sync 檢查擋下，需要由人工補上另一處的版本修改 commit。這是版本不一致時 CI 失敗的刻意設計。
- **SDK band 升級需手動**：不加入 Dependabot `dotnet-sdk` ecosystem，升級 `global.json` 時需同步確認本機 SDK。
- **image 未以 digest 固定**：`pgvector/pgvector:0.8.7-pg17@sha256:...` 的寫法未採用。sync 檢查的 regex 遇到 `@sha256` 會判定為不一致，需先調整檢查邏輯。
- **可選的 repo 設定**：「Require actions to be pinned to a full-length commit SHA」尚未啟用，由使用者決定是否開啟。
- **Python 3.14 patch 版本未固定**：`setup-python` 仍使用 minor 版本，patch 版本隨 runner 而變。

## Code Review 與修正

- 兩軸 Code Review，範圍 `origin/main...issue-86-m4-global-json`。

- **Standards**：
  - 已修正：
    - SDK 文件與註解宣稱 CI 安裝 10.0.113，實際為 10.0.402（同上 `rollForward` 問題）。
    - `ci.yml` 中 sync 步驟的註解只提到 dotnet-ef，未涵蓋 compose 與測試來源。
    - `Docs/testing/test-plan.md` 未列出 `docker-compose` Dependabot 與 sync 檢查。
    - 腳本錯誤處理三項（見執行紀錄）。
  - 判斷題，未處理：
    - digest pin（見未解決事項）。
    - `CHECKS` 與 `TEST_IMAGE_FILES` 寫死在腳本中。判定為可接受：這兩處是刻意的集中定義，新增檢查時修改即可。
  - 確認無誤：13 個 SHA 皆有同行版本註解，且與 tag 一致。

- **Spec**：
  - 已修正：
    - AC「CI 安裝的 SDK 為 10.0.113」原本不成立，改以 `rollForward: latestPatch` 達成後由 CI log 確認。
    - `test-plan.md` 的 Dependabot 清單未更新。
  - 範圍外，保留：`lint` job 以 ruff 檢查 `.github/scripts/`。範圍小、與本次新增的腳本直接相關，視為合理的 scope。
  - 其餘 AC 皆有證據滿足（M1～M4 的驗證紀錄）。
