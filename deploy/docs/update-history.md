# deploy/ 修改歷史（Git 證據）

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M3（#120）補記：2026-10-25 更新；程式變更以 `d249c07`、`6e70e93`、`b99b368` 記入本文件 §3.12。原查核基準保留，未重新審查其餘內容。

> 查核日期：2026-10-24。查核基準 HEAD：`01db2d7`（merge PR #106；tag `v0.0.4`；`origin/main` 同一 commit）。
> 工作樹：clean，僅有既存的未追蹤 `.venv`（不屬於本文件，也不屬於 `deploy/`）。本文件是新增的未追蹤檔案，尚未提交。
> 本次未執行任何部署、migration、爬取或真實外部 API；摘要只來自 git 歷史與 diff 內容，不推定測試或部署結果。

## 1. 範圍、命令與日期語意

**來源路徑（包含）**

`deploy`、`Dockerfile`、`.dockerignore`、`.github/workflows/cd.yml`、`.github/workflows/ci.yml`、`.github/scripts`、`crawler/deploy`

**排除**：`:(exclude)deploy/docs`（本文件與其他輸出文件自己的 commit 不計入實作變更）。

**命令（可重跑）**

```bash
git log --reverse --no-merges --date=short --format='%h %ad %an %s' -- \
  deploy Dockerfile .dockerignore .github/workflows/cd.yml .github/workflows/ci.yml \
  .github/scripts crawler/deploy ':(exclude)deploy/docs'
```

每個 commit 的檔案與行數：

```bash
git log --reverse --no-merges --format='@@%h' --numstat -- <同上路徑>
```

**結果**：102 個非 merge commit，時間範圍 2026-10-13（`082cd80`）至 2026-10-24（`5e68d6e`）。全部 author 為 `Arthur801`。

**與前次任務數字的差異**：任務描述提到 87 個非 merge commit。以上述路徑（包含 `crawler/deploy`、`.github/scripts`、`Dockerfile`、`.dockerignore`）重跑得到 102 個。差異來自路徑集合不同；本文件以 102 為準，並可由上列命令重現。

**日期語意**：`%ad` 是 **author date**（作者撰寫的時間），`--date=short` 以該 commit 記錄的時區顯示。committer date 未列入。排序為 `git log --reverse` 的預設拓撲順序（非依日期），因此同一天內的順序以 git 為準。

**`--follow` 與改名**：未使用 `--follow`。`git log --diff-filter=R` 在上列路徑中沒有任何改名紀錄，因此不需要 `--follow`。

**淺複製**：`git rev-parse --is-shallow-repository` 回傳 `false`，歷史完整。

**未提交的變更**：無。本次未修改任何 tracked 檔案。

**其他說明**

- `.github/workflows/ci.yml` 的歷史包含整體 CI（.NET、crawler、lint）的變更。下表只列與部署相關的 commit，並標示「CI 通用」。
- `deploy/README.md` 的歷史與 `deploy/` 其他程式碼同列（它是 runbook，也是 CD 規格的一部分）。
- `Docs/` 的規格（`deployment.md`、`architecture-decisions.md`、`test-plan.md`）不在上列路徑中。它們的相關變更列於 §5「相關依賴歷史」。

## 2. 維護轉折

1. **2026-10-13**：crawler 首次以 Docker 部署（`082cd80`），`run-crawler.sh` 進入 repository。
2. **2026-10-23**：整體 CI 建立（`eb216f8` 起）、版本同步檢查與 `global.json` 的 SDK 固定（`cde2afd`、`7f53884`、`404c284`、`89e2eb3`）。
3. **2026-10-23（#92 主體）**：CD 相關的主要實作，包括 web image、migration compat、host 程式（config、state、history、lock、runtime、manifest）、deploy 狀態機、人工指令、`cd.yml` 與 `cd_release.py`。這是 `deploy/` 的主體。
4. **2026-10-24（#92 的修正）**：第一輪 CD 試跑後的修正，主要在 staging tag、`--detach`、`--prefer-index=false`、plan 的 paused 判定、bootstrap 與 crawler.conf 的比對、以及文件對齊。
5. **2026-10-24（#101、#103、#105）**：production 營運事件後的修正：`CRAWLER_ENABLED`（#101）、`DB_CA_BUNDLE`（#103）、health check 的 User-Agent 與 rollback 診斷（#105，PR #106 合併於 `01db2d7`）。

**issue #92 的里程碑**：`Docs/Implementation-Report/issue-92-cd.md` 列出 M1（#93）、M2（#94）、M3a（#95）、M3b（#96）、M3c（#97）、M4（#98）。報告中沒有 M5 的條目，因此本文件不假設 M5 的存在。下方的分組以主題為主，只在報告有明確對應時標示里程碑。

## 3. 逐 commit 歷史（依主題分組）

欄位：日期（author date）、SHA、主旨（原文）、影響檔案（`numstat` 的 `+`/`-` 行數，路徑已簡寫）、目標內 diff 摘要。

### 3.1 crawler 首次部署（2026-10-13）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-13 | `082cd80` | Deploy crawler with docker | `crawler/deploy/README.md`（+146）、`crawler.conf.example`（+5）、`crawler.cron`（+7）、`crawler.logrotate`（+9）、`run-crawler.sh`（+73） | 建立 host 端的 crawler 部署檔案：cron 排程、logrotate、設定範例，以及第一版 `run-crawler.sh`（`daily`、`pages` 模式） |

### 3.2 整體 CI 與版本同步（2026-10-23，CI 通用，與部署相關的部分）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `eb216f8` | ci: 新增 GitHub Actions CI（dotnet 與 crawler 測試、快取、測試結果上傳） | `ci.yml`（+83） | CI 通用：建立 `ci.yml` 的 `dotnet` 與 `crawler` job，後續 CD 以 `workflow_call` 重用 |
| 2026-10-23 | `09dc3fa` | ci: 新增 lint job（dotnet format、ruff） | `ci.yml`（+35） | 建立 `lint` job，後續 deploy 的 ruff 與 shellcheck 步驟加在此 job |
| 2026-10-23 | `6872ffc` | ci: 依 code review 修正 CI（crawler NuGet 快取、push 不互相取消、ruff pin 檢查、註解） | `ci.yml`（+13/-3） | CI 通用：修正 concurrency 與 pin 檢查 |
| 2026-10-23 | `cde2afd` | ci: 新增版本同步檢查（dotnet-ef 與 EF Core） | `check_version_sync.py`（+74）、`ci.yml`（+3） | 新增 `check_version_sync.py`，並在 lint job 執行 |
| 2026-10-23 | `9ffd8aa` | ci: 將 GitHub Actions 固定為 commit SHA | `ci.yml`（+13/-13） | 所有 action 改為 commit SHA 固定 |
| 2026-10-23 | `c2697e5` | ci: Dependabot 監控 compose.yaml，版本同步檢查涵蓋測試 image | `check_version_sync.py`（+46/-2） | 版本同步涵蓋 pgvector 測試 image 與 compose.yaml |
| 2026-10-23 | `1bb24f3` | ci: lint job 以 ruff 檢查 .github/scripts | `ci.yml`（+5） | `.github/scripts` 納入 ruff |
| 2026-10-23 | `7f53884` | ci: 以 global.json 固定 .NET SDK 10.0.113 | `ci.yml`（+4/-3） | CI 的 SDK 版本來源改為 `global.json` |
| 2026-10-23 | `89e2eb3` | fix(ci): 版本同步檢查的錯誤處理與 compose 解析，更新註解與文件 | `check_version_sync.py`（+13/-6）、`ci.yml`（+1/-1） | 錯誤處理與 compose 解析修正 |
| 2026-10-23 | `404c284` | fix(ci): global.json 改為 latestPatch，讓 CI 固定在 10.0.1xx band | `ci.yml`（+1/-1） | CI 的 SDK band 設定 |

### 3.3 #92 基礎：image、migration 檢查與 compat（M1、M2 的主題）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `051a6f0` | feat(release): migration manifest and immutability check (#92) | `check_migrations.py`（+135）、`build-manifest.sh`（+56）、`.github/scripts/tests/*`（+179） | 新增 migration manifest 的建置與不可變檢查（已發布的 migration 不得修改；禁止 `suppressTransaction` 與 `CONCURRENTLY`） |
| 2026-10-23 | `bd142f1` | feat(docker): web image with release manifest and SQL scripts (#92) | `Dockerfile`（+64）、`.dockerignore`（+16）、`check_version_sync.py`（+38） | 建立 web image，並把 release manifest 與 SQL 放入 `/opt/release/`；版本同步加入 Dockerfile SDK 檢查 |
| 2026-10-23 | `7a598e6` | test(deploy): web image smoke test against pgvector on an internal network (#92) | `deploy/smoke/web-smoke.sh`（+226） | 新增 web smoke 測試（含 `--control-no-keys` 對照組） |
| 2026-10-23 | `a9db548` | ci: build the web image, smoke test it and check migrations (#92) | `ci.yml`（+40） | `docker` job：建置、smoke、migration 檢查 |
| 2026-10-23 | `3148fff` | fix(ci): fail the migration check on release API errors; review fixes (#92) | `.dockerignore`（+2）、`ci.yml`（+15/-3）、`Dockerfile`（+1/-1） | 修正 release API 錯誤時的失敗行為 |
| 2026-10-23 | `f6c8f5e` | feat(deploy): manifest helpers for the migration compat check (#92) | `deploy/lib/manifest.sh`（+108）、`test_manifest_lib.py`（+228） | 新增 bash 的 manifest 函式庫與測試 |
| 2026-10-23 | `7e5b524` | test(deploy): representative seeds for migration compat checks (#92) | `seeds/*.sql`（+73、+77） | 兩份 seed SQL（`RequireRecommendationUser`、`Embedding`） |
| 2026-10-23 | `447df76` | refactor(deploy): share smoke helpers between web and compat checks (#92) | `deploy/lib/smoke.sh`（+105）、`web-smoke.sh`（+23/-61） | 抽出共用 smoke 函式 |
| 2026-10-23 | `10a2774` | fix(deploy): make helper libraries shellcheck-clean (#92) | `manifest.sh`（+8/-8）、`smoke.sh`（+4） | shellcheck 修正 |
| 2026-10-23 | `f8f8e3a` | style(deploy): format manifest tests with ruff (#92) | `test_manifest_lib.py`（+25/-15） | 格式調整 |
| 2026-10-23 | `22b3b48` | feat(deploy): migration compat check for the release image (#92) | `deploy/migration-test/compat.sh`（+575） | 新增 compat 腳本：在拋棄式 DB 上重建、載入 seed、升級、比對 |
| 2026-10-23 | `b74fe28` | ci: run the migration compat check for PRs that change migrations (#92) | `ci.yml`（+73/-5） | PR 條件下執行 compat |
| 2026-10-23 | `3da79b7` | feat(deploy): host manifest port with bash parity tests (#92) | `manifest.py`（+147）、`ports.py`（+76）、`exit_codes.py`（+27）、`safefile.py`（+35）、`testing.py`（+52）、`test_manifest.py`（+289）、`test_manifest_parity.py`（+132） | host 端的 manifest 解析，與 bash 版本做對等測試；`exit_codes.py` 首次定義退出碼 |
| 2026-10-23 | `33d167e` | feat(deploy): classify the compat plan per migration relation (#92) | `compat_plan.sh`（+38）、`test_compat_plan.py`（+87）、`ci.yml`（+1/-1） | compat 依 chain 分類規劃 |
| 2026-10-23 | `dd41a2d` | fix(deploy): never run the target bundle on a schema-ahead database (#92) | `compat.sh`（+79/-9） | schema-ahead 時不執行目標 bundle（避免降級） |
| 2026-10-23 | `e3fa9cd` | ci: run the migration compat check when the checker changes (#92) | `ci.yml`（+19/-8） | compat 的 PR 條件納入 checker 檔案變更 |
| 2026-10-23 | `faf6d2b` | fix(deploy): fail the schema gate when pg_dump fails or prints nothing (#92) | `schema_dump.sh`（+58）、`compat.sh`（+15/-6）、`test_schema_dump.py`（+100） | pg_dump 失敗或空輸出視為錯誤（已修正，見 backlog §4） |

### 3.4 #92 host 核心（M3a 的主題）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `f8b29a4` | feat(deploy): host state file with CAS writes and pure transitions (#92) | `state.py`（+405）、`testing.py`（+31）、`test_state.py`（+221） | 新增 `state.json` 的解析、CAS 寫入與純轉換函式（`mark_dirty`、`mark_migrated`、`pause_crawler`、`promote_runtime`） |
| 2026-10-23 | `c5e6a5f` | feat(deploy): append-only run history with N7 status rules (#92) | `history.py`（+162）、`test_history.py`（+170） | history 的 append、讀取、tail 判定與 status 規則 |
| 2026-10-23 | `5fa94d4` | feat(deploy): flock helpers with bounded polling (#92) | `locks.py`（+46）、`test_locks.py`（+104） | flock 包裝與有界輪詢 |
| 2026-10-23 | `c26afaa` | feat(deploy): observe docker, systemd and schema before deciding (#92) | `runtime.py`（+116）、`test_runtime.py`（+129） | 觀察 docker、systemd 與 schema 的實際狀態 |
| 2026-10-23 | `2370c6c` | feat(deploy): host configuration parser and digest-pinned psql query (#92) | `config.py`（+167）、`HOST_API_RANGE`（+1）、`test_config.py`（+110） | host.conf 解析與白名單；psql 查詢（URL 只經環境變數傳遞） |

### 3.5 #92 指令與狀態機（M3b 的主題）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `fb2fed4` | feat(deploy): host command grammar, plan/status/deploy gates (#92) | `commands.py`（+514）、`state.py`（+5/-5）、`testing.py`（+113）、`deploy-entry`（+14）、`test_commands.py`（+482）、`test_entry.py`（+116） | 指令語法、plan、status、deploy gates 與 `deploy-entry` 入口 |
| 2026-10-23 | `aef8cb0` | ci: lint and test the host program on Python 3.12 (#92) | `ci.yml`（+15/-2） | host 在 Python 3.12 上執行測試（對應 Ubuntu 24.04） |
| 2026-10-23 | `bb06f08` | fix(deploy): find the web container by compose labels; require digest-pinned images (#92) | `config.py`（+5）、`images.py`（+20）、`runtime.py`（+36/-8）、測試 | 以 compose label 找 web container；image 必須是 digest |
| 2026-10-23 | `7ab05d9` | fix(deploy): pull the release image explicitly and create with --pull=never (#92) | `manifest.py`（+8/-4）、`test_manifest.py`（+35/-3） | 明確拉取 release image，建立時 `--pull=never` |
| 2026-10-23 | `428149a` | fix(deploy): take the run id from CD and refuse any reused run id (#92) | `commands.py`（+13/-7）、測試 | run id 由 CD 傳入，重複的 run id 拒絕 |
| 2026-10-23 | `1c2df5e` | feat(deploy): deploy state machine in the transient unit, SSH launch and follow (#92) | `machine.py`（+479）、`adapters.py`（+237）、`runs.py`（+98）、`release_content.py`（+64）、`commands.py`（+196/-132）、`test_machine.py`（+608）、`test_launch.py`（+274）等 | 狀態機（steps 0 到 7）、transient unit 啟動、SSH 跟隨；adapters 首次實作真實呼叫 |
| 2026-10-23 | `0ccbd8a` | chore(deploy): lint host code for Python 3.12 with deploy/ruff.toml (#92) | `ci.yml`（+7/-3）、`adapters.py`（+1/-3）、`ruff.toml`（+4） | ruff 設定（target py312） |
| 2026-10-23 | `a5c8e51` | feat(deploy): bound the SSH-side follow and order the crawler sub-steps (#92) | `machine.py`（+61/-21）、`commands.py`（+4）、`config.py`（+10）、測試 | SSH 端跟隨有上限；crawler 子步驟順序 |
| 2026-10-23 | `d724d12` | feat(deploy): crawler waits for the maintenance lock and skips while paused or dirty (N3) (#92) | `run-crawler.sh`（+37） | crawler 先取 shared maintenance lock，再讀 state；paused 或 dirty 以 exit 6 跳過（N3） |
| 2026-10-23 | `084069a` | feat(deploy): ship compose.prod.yaml and the crawler host files in the release (#92) | `Dockerfile`（+6）、`.dockerignore`（+6/-1）、`compose.prod.yaml`（+38）、`test_release_files.py`（+42） | release 隨 image 發布 compose 檔與 crawler host 檔案 |
| 2026-10-23 | `34fe2b3` | feat(deploy): configurable AWS CLI, loopback PUBLIC_URL and a non-root config override (#92) | `adapters.py`（+9/-7）、`commands.py`（+13/-3）、`config.py`（+39/-4）、測試 | `AWS_CLI` 設定、`PUBLIC_URL` 限制、非 root 的設定覆寫（測試用） |
| 2026-10-23 | `0a60780` | fix(deploy): read env_file in raw format and refuse a Compose older than the minimum (#92) | `adapters.py`、`commands.py`、`machine.py`（+27）、`ports.py`、`compose.prod.yaml`（+5/-1）、測試 | `format: raw` 的 env_file；後續在 `3b21c71` 改為能力探測 |
| 2026-10-23 | `e3877f1` | fix(deploy): derive N7 status from the records before the unit state (#92) | `exit_codes.py`（+3/-1）、`history.py`（+18/-8）、`machine.py`（+7/-3）、`runs.py`（+10/-5）、測試 | status 先看 history，再看 unit（N7 ①–④） |
| 2026-10-23 | `5cee827` | fix(deploy): make every known outcome of a started unit a completed record (#92) | `commands.py`（+53/-25）、`test_launch.py`（+101） | 已知結果一律寫 completed（N7） |
| 2026-10-23 | `48adfc4` | test(deploy): prove secret fidelity inside the web container and run secrets through raw env (#92) | `test_local_integration.py`（+31/-7） | 整合測試驗證 secret 原值保真 |
| 2026-10-23 | `3b21c71` | fix(deploy): replace the Compose version floor with a raw env_file capability probe (#92) | `adapters.py`（+5）、`commands.py`（+3/-1）、`machine.py`（+43/-18）、`compose_probe` 測試（+113） | 以 probe 取代 Compose 版本下限 |
| 2026-10-23 | `ebcf729` | fix(#92): schema-ahead keeps the current crawler | `commands.py`（+20）、`machine.py`（+23/-7）、`history.py`（+1/-1）、測試（+49） | schema-ahead 保留目前 crawler digest（S7） |
| 2026-10-23 | `a87f2e4` | feat(#92): plan JSON exposes the state crawler digest for schema-ahead deploys | `commands.py`（+1/-1）、`test_commands.py`（+3） | plan 的 JSON 含 state 的 crawler digest |


### 3.6 #92 人工指令、install-host、整合測試（M3c 的主題）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `11faa9d` | feat(deploy): operator commands behind book-finder-admin (N2, N3, N4, N6, N7) (#92) | `book-finder-admin`（+14）、`history.py`（+20）、`operator_cli.py`（+549）、`test_operator_cli.py`（+586） | 五個人工指令（`bootstrap-state`、`reconcile-schema`、`resume-crawler`、`resolve-run`、`install-host`） |
| 2026-10-23 | `f708850` | test(deploy): local integration scenarios a-e against real docker (#92) | `edge_stub.py`（+51）、`run-local.sh`（+15）、`conftest.py`（+8）、`test_local_integration.py`（+767） | 整合情境 a 到 e |
| 2026-10-23 | `4c5a38f` | fix(deploy): keep the bytes resolve-run removes from history in a fsynced sidecar (#92) | `history.py`（+35/-10）、`operator_cli.py`（+23/-15）、測試（+59） | `resolve-run` 修復尾端前保存 sidecar |
| 2026-10-23 | `c659902` | test(deploy): pin integration images by digest and start each PASS line at column 0 (#92) | `test_local_integration.py`（+8/-4） | 整合測試的 image 以 digest 指定 |
| 2026-10-23 | `6681752` | fix(deploy): reject non-finite and non-positive timeouts (#92) | `config.py`（+16/-4）、`locks.py`（+4）、測試 | 拒絕 NaN、0 與負數的 timeout |
| 2026-10-23 | `e39334b` | fix(#92): operator commands record started before any change | `history.py`（+90/-11）、`operator_cli.py`（+287/-53）、`runs.py`（+8/-2）、測試 | operator-started 在變更前寫入（S8）；record 以 `phase` 欄位區分 |
| 2026-10-23 | `a35a69e` | style(#92): format test_history after operator protocol tests | `test_history.py`（+0/-1） | 格式 |
| 2026-10-23 | `ff5ec97` | fix(#92): install-host swaps a versioned link so the host never disappears | `operator_cli.py`（+212/-32）、`test_install_host.py`（+152） | install-host 以 versioned link 交換（S9） |

### 3.7 #92 CD 工作流程與 CD 腳本（M4 的主題）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `bbe9f5b` | ci(#92): ci.yml can be called by the CD workflow | `ci.yml`（+5） | 加入 `workflow_call` |
| 2026-10-23 | `fb68719` | feat(#92): cd_release.py validates release records, host plans and deploy results | `cd_release.py`（+882）、`test_cd_release.py`（+663） | CD 腳本首次建立（release 記錄、plan 解讀、follow、compat 摘要） |
| 2026-10-23 | `a5f3194` | feat(#92): cd.yml builds, attests, plans and gates production deploys | `cd.yml`（+495） | `cd.yml` 首次建立（guard、test、build、resolve、plan、compat、deploy） |
| 2026-10-23 | `e431b22` | feat(#92): publish-release runs the immutable release flow | `cd_release.py`（+58/-3）、測試（+76） | `publish-release` 流程（draft、上傳、publish） |
| 2026-10-23 | `21e8e95` | fix(#92): plan-outputs parses the whole plan file | `cd_release.py`（+2/-1） | plan 檔案完整解析 |
| 2026-10-23 | `b53b6d4` | fix(#92): GHCR login through env, packages read for resolve and compat | `cd.yml`（+18/-1） | GHCR 登入經環境變數；resolve 與 compat 有 packages 讀取權限 |
| 2026-10-23 | `61f49a2` | fix(#92): an unverified operator failure stays indeterminate | `operator_cli.py`（+13/-4）、測試（+73） | 未驗證的人工失敗保持 indeterminate |
| 2026-10-23 | `998b270` | fix(#92): crawler provenance is recorded in state, not taken from the web runtime | `machine.py`（+35/-4）、`operator_cli.py`（+84/-14）、`state.py`（+44/-2）、測試 | crawler provenance 記入 state（S11）；`_recorded_crawler` 讀回已安裝檔案的雜湊 |
| 2026-10-23 | `6106d82` | fix(#92): name the sudoers fix when SSH_ORIGINAL_COMMAND is empty under sudo | `commands.py`（+9/-1）、測試（+35） | 空的 `SSH_ORIGINAL_COMMAND` 時指出 sudoers 修正 |
| 2026-10-23 | `0bcbfe7` | docs(#92): fix the sudo env_keep step, add the drift procedure and the ADR gap note | `deploy/README.md`（+93/-12） | runbook：修正 sudo `env_keep`、新增 drift 程序 |
| 2026-10-24 | `a4a8f3e` | fix(#92): build the images through a staging tag before the release tag | `cd_release.py`（+41）、`test_cd_release.py`（+28）、`cd.yml`（+64/-11） | 先推送 staging tag，attest 與 verify 後才建立 release tag（commit point） |
| 2026-10-24 | `596ed1d` | fix(#92): deploy --detach returns once the run is acknowledged | `commands.py`（+41/-4）、`runs.py`（+9）、`test_launch.py`（+94）、測試 | `--detach` 旗標；等待接手後回報 `launched`（上限 60 秒） |
| 2026-10-24 | `b393746` | fix(#92): CD starts the deploy with --detach and deploy-follow is the only follower | `cd_release.py`（+20/-5）、`cd.yml`（+7/-3）、測試（+35） | CD 以 `--detach` 啟動，`deploy-follow` 為唯一的跟隨者 |
| 2026-10-24 | `e7330b3` | fix(#92): edge stub relays only status and body (CodeQL py/http-response-splitting) | `edge_stub.py`（+5/-3） | 整合測試的 edge stub 只轉送 status 與 body |
| 2026-10-24 | `01b94f7` | fix(#92): make plan report a paused crawler as drift before approval | `cd_release.py`（+15/-4）、`commands.py`（+9/-3）、測試 | plan 在核准前回報 paused crawler |
| 2026-10-24 | `1dc9bbb` | fix(#92): bootstrap-state checks crawler.conf against --crawler-digest | `operator_cli.py`（+29/-18）、測試（+25/-3） | bootstrap 比對 crawler.conf 與 `--crawler-digest` |
| 2026-10-24 | `e65bac2` | test(#92): lock run-crawler.sh to the host state schema | `test_run_crawler_contract.py`（+95） | run-crawler.sh 與 host 寫入的 state 格式契約測試 |
| 2026-10-24 | `8d0769b` | docs(#92): replace plan and milestone citations in code comments with in-repo references | 多個 host 檔案與測試（各 1 至 8 行） | 註解改為 repository 內的引用（去除 Implementation-Report 的引用） |
| 2026-10-24 | `eab5e4d` | docs(#92): drop report citations from specs and document deliberate deviations | `deploy/README.md`（+18/-5） | 規格中移除報告引用；記錄刻意偏離（runbook §7.1） |

### 3.8 #92 文件、build commit point 與 imagetools

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-23 | `8e1001d` | docs(#92): record ADR-006, move CD into MVP, describe CI and compat | `deploy/README.md`（+4/-4） | runbook 小幅修正（ADR-006 的引用） |
| 2026-10-23 | `a17d415` | docs(#92): update deployment and crawler docs for GHCR and CD | `crawler/deploy/README.md`（+59/-36） | crawler 文件加入 GHCR 與 CD |
| 2026-10-23 | `be54182` | docs(#92): add the CD runbook for deploy/ | `deploy/README.md`（+578） | 首次建立 runbook |
| 2026-10-23 | `48ce5c9` | docs(#92): add the issue-92 implementation report | `deploy/README.md`（+1/-1） | 小幅修正（報告的連結） |
| 2026-10-23 | `7667a1a` | docs(#92): correct the security group guidance in the runbook | `deploy/README.md`（+1/-1） | 安全群組說明修正 |
| 2026-10-24 | `f159054` | docs(#92): document the build commit point and detached deploys | `deploy/README.md`（+39/-8） | commit point 與 detach 的說明 |
| 2026-10-24 | `5ff8a51` | fix(#92): release tags keep the attested digest (--prefer-index=false) | `cd.yml`（+7/-3） | `imagetools create --prefer-index=false`，release tag 保留 attested digest（commit point 不變式） |
| 2026-10-24 | `1821f34` | test(#92): imagetools round trip against a throwaway local registry | `ci.yml`（+5/-1）、`imagetools-roundtrip.sh`（+129）、`test_imagetools_roundtrip.py`（+27） | 本機 registry 的 round trip 測試 |
| 2026-10-24 | `96f48fa` | test(#92): imagetools round trip covers index and single-manifest sources | `imagetools-roundtrip.sh`（+104/-20）、測試（+3/-2） | 同時涵蓋 index 與 manifest 來源（含對照組） |
| 2026-10-24 | `4508fe4` | docs(#92): imagetools keeps the digest only with --prefer-index=false | `deploy/README.md`（+3/-3） | runbook §1.6 |
| 2026-10-24 | `bda4ebd` | docs(#92): align the runbook with bootstrap, publication order, schema-ahead and GA facts | `crawler/deploy/README.md`（+1/-1）、`deploy/README.md`（+8/-6） | runbook 與 bootstrap、發布順序、schema-ahead 對齊 |
| 2026-10-24 | `3dd0c13` | docs(#92): GHCR digest in the crawler example and fix section references | `crawler.conf.example`（+3/-2）、`deploy/README.md`（+4/-4） | crawler 範例改為 GHCR digest |
| 2026-10-24 | `4a7c060` | docs(#92): status always exits 0; the crawler example holds a digest placeholder | `crawler/deploy/README.md`（+1/-1）、`deploy/README.md`（+1/-1） | `status` 固定 exit 0 |

### 3.9 #101：`CRAWLER_ENABLED`（2026-10-24）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-24 | `3637cff` | feat(crawler): add CRAWLER_ENABLED switch to skip scheduled runs (#101) | `crawler/deploy/run-crawler.sh`（+15） | `CRAWLER_ENABLED`：`false` 時輸出 `skipped=disabled` 並 exit 0；非法值 exit 2；在任何鎖之前判定。此 commit 是 `v0.0.2` 的祖先（已確認） |
| 2026-10-24 | `26a6272` | test(deploy): keep CRAWLER_ENABLED through crawler.conf rewrite (#101) | `test_machine.py`（+11/-3） | `crawler.conf` 改寫時保留 `CRAWLER_ENABLED` |
| 2026-10-24 | `b52b80b` | docs: document CRAWLER_ENABLED switch for blocked EC2 hosts (#101) | `crawler/deploy/README.md`（+11）、`crawler.conf.example`（+3）、`deploy/README.md`（+3/-1） | 文件說明停用開關 |

### 3.10 #103：`DB_CA_BUNDLE`（2026-10-24）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-24 | `439b80e` | feat(deploy): optional DB_CA_BUNDLE for host config, efbundle, psql and web compose (#103) | `adapters.py`（+37/-7）、`config.py`（+43/-1）、`machine.py`（+11/-1）、`release_content.py`（+5/-1）、測試（+248） | 選填的 CA bundle：host 在變更前檢查（一般檔案、非 symlink、0644、≤ 1 MiB）；efbundle、psql 與 web 以唯讀路徑掛載；未在 `v0.0.2` 內（此 commit 不是其祖先） |
| 2026-10-24 | `a11a2c6` | feat(release): ship compose.ca-bundle.yaml read-only bind for web (#103) | `Dockerfile`（+2/-2）、`compose.ca-bundle.yaml`（+13）、`test_release_files.py`（+54/-1） | 新增 `compose.ca-bundle.yaml`；`v0.0.3` 起包含（git 已確認） |
| 2026-10-24 | `f636a29` | feat(crawler): optional read-only DB_CA_BUNDLE mount in run-crawler.sh (#103) | `run-crawler.sh`（+27） | crawler 以唯讀 bind 掛載同一路徑；非法路徑 exit 2 |
| 2026-10-24 | `222c7ce` | docs(deploy): document DB_CA_BUNDLE and never re-run install -d on existing dirs (#103) | `crawler/deploy/README.md`（+12/-4）、`crawler.conf.example`（+2）、`deploy/README.md`（+20/-7） | 文件：`DB_CA_BUNDLE`，並禁止對既有目錄重跑 `install -d` |

### 3.11 #105（PR #106）：rollback 與 health check 診斷（2026-10-24）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-24 | `569c485` | fix(deploy): journal health diagnostics before rollback, mask secrets (#105) | `adapters.py`（+13）、`machine.py`（+75/-9）、`ports.py`（+6）、`runtime.py`（+7/-2）、`testing.py`（+15）、測試（+201） | 切換失敗時，先寫入階段、狀態碼、log 尾端（80 行，secret 已遮蔽）再回滾；回滾健康預算的常數見 architecture §6 |
| 2026-10-24 | `754f3b7` | docs(deploy): describe rollback budget and switch diagnostics in the journal (#105) | `deploy/README.md`（+11/-5） | 文件 |
| 2026-10-24 | `2fb5e27` | fix(deploy): health checks send an explicit User-Agent (#105) | `adapters.py`（+9/-1）、`config.py`（+11）、`machine.py`（+4）、測試（+88） | `RealHttp` 送出 `book-finder-deploy/<HOST_API max>`；4xx 在公開階段寫入 edge 提示。此 commit 是 `v0.0.4` 的祖先（已確認） |
| 2026-10-24 | `5e68d6e` | docs(deploy): record the User-Agent incident and edge requirement (#105) | `deploy/README.md`（+6/-4） | 文件：記錄事件與 edge 需求 |

**`01db2d7`**（HEAD）是 PR #106 的 merge commit，不是非 merge commit，因此不在 102 個列表中。它的第二個父 commit 是 `5e68d6e`。

### 3.12 #120 PR4 M3：contract allowance、011 seed 與 gate 7 preflight（2026-10-25）

| 日期 | SHA | 主旨 | 影響檔案（+/-） | diff 摘要 |
|---|---|---|---|---|
| 2026-10-25 | `d249c07` | feat(compat): reviewed contract allowance for migration 011 | `deploy/lib/contract_allowance.sh`（新增）、`deploy/migration-test/compat.sh`（+162/-12）、`deploy/migration-test/contract/`（新增，011 的 `allow.tsv`、`verify.sql`）、`deploy/tests/test_contract_allowance.py`（新增）、`.github/workflows/ci.yml`（summary 與 shellcheck 清單） | 只有 pending 的 migration 能使用 allowance；rewrite table 在升級前複製到 `compat_before`，升級後 `verify.sql` 必須 0 列，升級後 schema 比對前移除複本；drop-column 的欄位仍存在或不存在都失敗；report 增加 `contract_allowances` |
| 2026-10-25 | `6e70e93` | test(compat): 011 seed and gate 7 preflight with its DB test | `deploy/migration-test/seeds/20261024160045_MultiSourceCatalog.sql`（+3，Book 1 同時有 ISBN_13 與 ISBN）、`seeds/20261025120000_ContractMultiSourceCatalog.sql`（新增）、`deploy/migration-test/preflight/20261025120000_ContractMultiSourceCatalog.sql`（新增）、`tests/DatabaseIntegration/ContractMigration011PreflightTests.cs`（新增） | 010 seed 讓 compat 的 011 升級同時驗證轉換與去重；011 seed 為 011 形狀；preflight 是唯讀的 gate 7 檢查，測試對 010 資料比對估計值並與升級後的實際列數一致 |
| 2026-10-25 | `b99b368` | test(db): cover 011 verify.sql, the 011 seed and the preflight files | `tests/DatabaseIntegration/ContractMigration011VerifyTests.cs`（新增）、`RepositoryPath.cs`（新增） | verify.sql 對每種違規回傳一列；011 seed 能在 011 上載入並保持 011 形狀 |

本地 compat（M3 驗證）：base 為 `347e5b0`（`git merge-base origin/main HEAD`），target 為本分支的 `book-finder-web:ci`，指令與 `ci.yml` 相同，結果 `compat checks passed (forward_ok=true)`。報告中的 allowance 為 `20261025120000_ContractMultiSourceCatalog`，dropped columns 為 `book_sources.source_type`、`book_subjects.source_type`，rewritten table 為 `book_identifiers`，verify 0 列。

## 4. 目前工作樹與未提交差異

- `git status --porcelain`：只有既存的 `?? .venv`。
- 本文件與其他四份文件是本次任務新增的未追蹤檔案，尚未加入 Git index，也未提交。
- 本次未修改任何 tracked 檔案。

## 5. 相關依賴歷史（不在上列路徑中）

| 路徑 | 與 `deploy/` 的關係 | commit（2026-10-23 以後） |
|---|---|---|
| `Docs/deployment/deployment.md` | 部署規格 authority | `a17d415`、`0bcbfe7`、`f159054`、`4508fe4`、`b52b80b`（2026-10-23 至 10-24 範圍內，`git log -- <path>` 可重現） |
| `Docs/architecture/architecture-decisions.md` | ADR-006 | `8e1001d`（建立 ADR-006）、`0bcbfe7`、`eab5e4d`（2026-10-23 至 10-24 範圍內） |
| `Docs/testing/test-plan.md` | test-plan §6 | `485eaad`（CI 報告與 §6 更新）、`dccad53` 之後的測試條款（`git log -- <path>` 可重現） |
| `global.json` | .NET SDK 固定（與 `check_version_sync.py` 的 Dockerfile 檢查相關） | `7f53884`、`404c284`（僅 `ci.yml` 在上列路徑內） |
| 測試 fixture 的 pgvector image（與 `compose.yaml`） | 版本同步（`check_version_sync.py` 檢查） | `dccad53`（pgvector 固定為 0.8.7-pg17，7 個檔案，含 `tests/` 的 fixture） |
| 2026-10-25 | `22bebf5` | test(deploy): add CD compat seed for migration 010 | `deploy/migration-test/seeds/20261024160045_MultiSourceCatalog.sql`（新增，覆蓋 010 head 的 source_type-only 與 source_code-only 寫法、ISBN、book_offers） |
| 2026-10-25 | `aa792bf` | fix(catalog): pin ISBN NFKC to Unicode 15.1 independent of the runtime | `.github/workflows/ci.yml`：新增 `unicode_tables.py --check` 步驟（與 scripts tests 同一 job） |

2026-10-11 至 2026-10-21 的 `Docs/` 規格歷史（crawler、embedding、auth）與 `deploy/` 的關係只有間接關聯（例如 `deployment.md` 的 crawler 章節），本文件未逐一列出。

## 6. 歷史限制

- **不推測日期**：只使用 author date。沒有 Git 證據的部署時間、GHCR 發布時間、EC2 上 host 程式的安裝時間，本文件不列出。
- **營運事件的時間**：2026-10-24 的 production 事件（cutover、403、`/etc/book-finder` 權限）只見於 runbook 與 commit message，不在本文件的日期推算範圍內。
- **merge commit**：排除於上列命令之外。`01db2d7` 是 PR #106 的 merge commit。
- **compat 與 GHCR 的實際結果**：本文件不推定 `Confirm` 步驟或 GHCR 上的結果（見 backlog DEP-B06）。
- **已修復的歷史問題不列為待辦**：見 [backlog.md §4](backlog.md)。

## 7. 重跑與驗證

- 重跑命令見 §1。以 `git cat-file -t <sha>` 可確認本文件中每個 SHA 都能解析。
- 本文件的所有 SHA 已在寫入前後以 `git cat-file -t` 核對（見交付說明）。
