# Issue #92 CD（自動部署）：實作報告

- Issue：#92 CD（自動部署）
- 規格：設計計畫（v5.1，I1～I8、S3～S11、N1～N8；計畫檔為本機 `~/.claude/plans/cheerful-finding-shell.md`，不在 repository 中）。本報告引用其中的決策與查證結果；長期規格以 `Docs/deployment/deployment.md`、`Docs/architecture/architecture-decisions.md`（ADR-006）、`Docs/testing/test-plan.md` §6 與 `deploy/README.md` 為準。
- 日期：2026-10-23
- 分工：
  - 主 agent：規劃、派工、驗收、以 review 結果決定修正範圍。
  - Haiku subagent：依 TDD 實作各模組，並在每輪 review 後修正。
  - 文件模組（本報告 PR）由 subagent 撰寫，所有數字與程式陳述以程式碼與實際執行結果為準；無法從程式確認的內容標為「待確認」。
- 背景：`product-requirements.md` 把 CD 列為延後項目。web 原本以 systemd 原生執行，crawler 以 Docker Hub image 加 cron 執行。

## 使用者決定

- **web 改為 container**，以 compose 管理；host nginx 負責 TLS。
- **以 SSH key 連到 EC2**，由 forced command 限制權限（plan key 與 deploy key 分開）。
- **推送 `v*` tag 觸發，經 `production` 環境核准後部署**。核准即為 L4 授權。
- **migration 併入同一個部署流程**，forward 時由 host 狀態機執行。
- **SDK 安裝在 Dockerfile 內**，從 checksum 固定的 tarball 安裝（`dotnet-sdk-<版本>-linux-x64.tar.gz`），版本必須等於 `global.json`。

## 變更檔案

以內容區域分組（不依 PR 歸屬）。`git diff --stat 2248309 HEAD` 為 82 個檔案，+16717 / -74 行。

| 區域 | 檔案 | 說明 |
|---|---|---|
| web image 與 app 設定 | `Dockerfile`、`.dockerignore`、`deploy/release/compose.prod.yaml`、`deploy/release/build-manifest.sh` | 多階段 build；efbundle、migration SQL、`migrations.txt`、`RELEASE_API` 放入 `/opt/release/`；compose 以 digest 指定 image，綁定 `127.0.0.1:5000` |
| web 設定 | `Program.cs`、`Infrastructure/Hosting/HostingSetup.cs`、`tests/UnitTests/HostingSetupTests.cs` | `ForwardedHeaders:KnownNetworks` 與 `DataProtection:KeysPath`，兩者皆由環境變數設定 |
| CI 與版本檢查 | `.github/workflows/ci.yml`、`.github/scripts/check_version_sync.py`、`.github/scripts/check_migrations.py`、`.github/dependabot.yml`、`.gitignore`（新增 deploy 相關忽略項目） | Docker image job（smoke、control）、compat 觸發、`workflow_call`；Dockerfile SDK 與 global.json 同步檢查；已發布 migration 不可修改、禁止 `suppressTransaction` 與 `CONCURRENTLY`；Dependabot 監控根目錄 Dockerfile |
| migration compat | `deploy/migration-test/compat.sh`、`deploy/lib/*.sh`、`deploy/migration-test/seeds/*.sql`、`deploy/smoke/web-smoke.sh` | 依 `schema.rebuild` 重建、seed、升級、資料與 schema 檢查、forward smoke；`compat_plan.sh` 定義各分類的檢查 |
| host 程式與狀態機 | `deploy/host/deploy-entry`、`deploy/host/bookfinder_host/{commands,machine,state,history,runs,locks,runtime,manifest,release_content,adapters,ports,config,exit_codes,images,safefile}.py`、`HOST_API_RANGE` | SSH 指令語法、plan 與 status、deploy 的 transient unit、狀態機、state 與 history、lock、指令的 allowlist |
| 人工指令與安裝 | `deploy/host/book-finder-admin`、`deploy/host/bookfinder_host/operator_cli.py` | `bootstrap-state`、`reconcile-schema`、`resume-crawler`、`resolve-run`、`install-host`；operator 協定；版本目錄與 symlink 原子替換 |
| 爬蟲 | `crawler/deploy/run-crawler.sh`、`crawler/deploy/README.md`、`crawler/tests/test_deploy.py` | 先取 shared `db-maintenance.lock` 再讀 state；paused 與 dirty 以 exit 6 跳過 |
| CD workflow | `.github/workflows/cd.yml`、`.github/scripts/cd_release.py` | tag 與 dispatch 兩種觸發；guard、build、resolve、plan、compat、deploy；immutable release 流程；`plan-outputs` 與 `deploy-follow` |
| 測試 | `deploy/tests/**`、`.github/scripts/tests/**`、`deploy/tests/integration/test_local_integration.py`、`deploy/integration/*`、`crawler/tests/test_deploy.py` | pytest（stub 與 fakes）、本機整合測試（`BOOKFINDER_IT=1`，情境 a～e 與 probe）、本機 edge stub |
| 文件 | `deploy/README.md`、`Docs/deployment/deployment.md`、`Docs/architecture/architecture-decisions.md`、`Docs/requirements/product-requirements.md`、`Docs/testing/test-plan.md`、`crawler/deploy/README.md`、`Docs/Implementation-Report/issue-92-cd.md` | runbook、ADR-006、需求與測試計畫更新、本報告 |

## PR

- #93 M1：web image 與 app 設定。
- #94 M2：migration compat。
- #95 M3a：host 核心（config、state、history、lock、runtime、manifest）。
- #96 M3b：deploy 狀態機與 transient unit。
- #97 M3c：人工指令、install-host、爬蟲 lock、本機整合測試、compose 的 raw env_file probe。
- #98 M4：`cd.yml`、`cd_release.py`、`ci.yml` 的 `workflow_call`。
- 本報告 PR：runbook、ADR-006、需求與測試計畫、爬蟲 README、本報告。

## 實作思路

### 信任邊界與 state

- Host 程式在 EC2 上，是唯一能改動 production 的東西；CD 只經 forced command 與它互動。
- Release 的 metadata（`migrations.txt`、`RELEASE_API`）以 `docker create` + `docker cp`（不帶 `-L`）取出，先檢查一般檔案；plan 絕不執行 release 內的程式。
- state.json 有 `runtime`、`previous_runtime`、`schema`（applied、rebuild、dirty）、`crawler`（digest、雜湊、source_release、paused）。每次寫入都是 CAS（revision 相符才寫入），並以 atomic rename 完成（S4）。
- history.jsonl 是 append-only，每次部署寫 `started` 與 `completed`，每行小於 `PIPE_BUF`，寫入後 fsync。部署結果以 history 為準，unit 狀態只用來判斷「是否仍在執行」（N7）。

### 部署流程（host 狀態機）

- 順序：deploy lock → CAS 與 gate（revision、runtime、schema、dirty、release_api、chain）→ 健康檢查 → 物化 release → 寫入暫存 env → forward 時 db-maintenance lock、pause crawler、snapshot、dirty、efbundle、確認 DB id → 切換 web（cutover 時先 stop systemd）→ 健康檢查 → crawler 更新 → 寫入 `runtime`、`crawler` 與 completed。
- 失敗分支：in-sync 與 schema-ahead 的 web 失敗會回滾（exit 1 或 exit 5）；forward 的 web 失敗不回滾（I5，exit 5）。
- 每個已知結果都寫一筆 completed；未預期例外則讓 run 維持 indeterminate（exit 8）。

### Migration 與 chain

- chain 只接受 in-sync、forward、schema-ahead 三種前綴關係，其他都是 divergent（I4）。身分以 source hash 判定（N5）；SQL hash 只作 audit。
- 每個 migration 在自己的 transaction 中執行（實測，見驗證結果第 4 項），因此失敗時 DB 停在 migration 邊界。
- 第一次 cutover 只接受 in-sync（I2）。`bootstrap-state` 由人工執行（N6），CD 從不建立 state。

### Crawler 協調

- 部署在 forward migration 前取得 exclusive `db-maintenance.lock`，在鎖內 pause crawler（N3）。
- `run-crawler.sh` 先取得 shared `db-maintenance.lock`，再讀 state；paused 或 dirty 時 exit 6。
- crawler 的 provenance 記在 `state.crawler`，與 web runtime 分開（S11）。schema-ahead 不改動 crawler（S7）。

### 人工程序（M3c）

- 人工指令採用 deploy 的 started/completed 協定（S8）：先寫 `operator-started` 並 fsync，才改動任何東西，最後寫 `operator-completed`。
- 只有能證明「完全沒改動」才可寫 failed（S10）。其他情況維持 indeterminate，直到 `resolve-run`。
- `install-host`：版本目錄先完整寫入並 fsync，再以 rename 替換 symlink（S9）；舊版普通目錄以 `renameat2(RENAME_EXCHANGE)` 替換，不支援時拒絕。

### CD workflow（M4）

- Tag 與 dispatch 兩種觸發。guard 驗證 tag 格式，並確認 commit 在 `origin/main` 上；dispatch 額外要求 `ref == main` 且 release 已 published。
- build：沿用既有 image 前必須通過 attestation（I7）；`publish-release` 採用 draft → upload → publish，已發布的 release 必須與本次 build 一致。
- plan 與 compat 在核准前執行；`deploy` job 只在 `production` 核准後連到 host。
- pending SQL 來自 target release 的 asset，runner 不重新產生（N8）。

### Compose 與 raw env_file

- web 的三個 secret（DB 連線字串、OpenAI key、JWT key）寫入暫存 env file，並以 `env_file: format: raw` 注入。`format: raw` 讓 compose 不做插值與引號處理，`$`、引號、`#` 都會原樣保留。
- Compose 版本不固定下限。改以 capability probe 驗證：每次 plan 與 deploy 前，以 `docker compose config` 渲染一個含特殊字元的 probe，若值不符即拒絕（exit 2）。

## 執行紀錄（Log）

- **M1～M3 的 review 修正**：
  - 不變式從 v2 逐步加入到 v5.1：v2 處理 8 點，v3 處理 14 點，v4 加入 I1～I8 與 S1～S6，v5 加入 N1～N8（見計畫檔的版本說明）。
  - #94：pg_dump 的 `\restrict` 隨機 key 造成 schema 比對誤判，改為正規化後比對，並讓空輸出不能與空輸出相等。compat 的觸發路徑擴大到 `deploy/lib`、`deploy/smoke`、`deploy/release`、`Dockerfile`、`.dockerignore`。schema-ahead 的分支獨立處理。
  - #95、#96：NaN 與 inf 被 `float()` 接受，會讓有界的等待永不逾時。設定與 lock 都改為拒絕非有限的正數。
  - #96：unit 一啟動就先寫 `started`，之後才拿 lock、讀 state。lock 逾時、state 缺失或損毀、被其他 indeterminate 擋下都寫 completed。這樣同一個 run id 的結果不會因 systemd 回收 unit 而改變。
- **#97 review**：
  - 人工指令改用 operator 協定（S8、S10），未知結果維持 open。
  - `install-host` 的 crash safety：版本目錄與 symlink 替換（S9）。
  - schema-ahead 的 crawler 不改動，並由 `crawler_digest` 的 gate 強制（S7）。
  - crawler provenance 記在 state（S11），不從 web runtime 推導。
  - compose 的 raw env_file 與 capability probe：原本以版本下限判斷，改為實際渲染驗證。
- **M4**：
  - `cd.yml` 的 `deploy` 只在核准後連線；`plan` 與 `compat` 在核准前完成。
  - 各 action 以完整 SHA pin，權限依 job 最小化（`permissions: {}` 為預設）。
- **本報告 PR**：
  - runbook（`deploy/README.md`）、ADR-006、`deployment.md` §3、§5～§8、需求與測試計畫、爬蟲 README。
  - 文件中的指令、設定鍵、退出碼與 check 名稱都對照程式碼核對。

## 驗證結果

### 本次文件 PR 中實際執行的測試

| 指令 | 結果 |
|---|---|
| `.venv/bin/python -m pytest .github/scripts/tests deploy/tests -q`（Python 3.14.4） | 614 passed, 6 skipped（skip 為 `BOOKFINDER_IT` 未設定的整合測試） |
| `uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -q` | 552 passed, 6 skipped（同上） |
| `dotnet test tests/UnitTests/UnitTests.csproj` | 707 passed, 0 failed |

- `Program.cs` 與 `HostingSetup` 的設定讀取由 UnitTests 的 `HostingSetupTests` 覆蓋。`DatabaseIntegration` 與 `WebIntegration` 未在本次執行（需要本機 Docker，Testcontainers）。
- 本次未執行 `BOOKFINDER_IT=1` 的本機整合測試（情境 a～e 與 probe）。
- 本次未執行 GitHub Actions 的 CI 與 CD，也未在 EC2 上驗證。

### 計畫 §7 的查證結果（2026-10-23）

1. **`gh attestation verify`**：gh 2.103.0 的 help 列出 `--signer-workflow`、`--source-ref`、`--source-digest`、`--deny-self-hosted-runners`。本機 gh 2.46 沒有 `attestation`，因此驗證只在 CI runner 上執行（I7）。
2. **Immutable Releases**：開啟後，publish 之後 asset 不能修改或刪除，tag 鎖定在原 commit，也不能刪除。只對開啟後發布的 release 生效。刪除 release 後 tag 名稱不能重用。尚未確認是否已 GA。
3. **`docker cp` 與 symlink**：不帶 `-L` 時複製出來的是連結本身。實測 `/opt/release/migrations.txt -> /etc/shadow` 複製後仍是指向 host `/etc/shadow` 的連結。因此讀取前以 `lstat` 拒絕 symlink。
4. **efbundle 的 transaction**：支援 `efbundle <MIGRATION>`。從 AiProfile 升級，pending 為 Indexes 與 RequireRecommendationUser；故意塞入 NULL 讓後者失敗，結果 exit 1，Indexes 已 commit，RequireRecommendationUser 完整 rollback。每個 migration 各自在一個 transaction 中執行。
5. **systemd-run**：`--collect` 且不加 `--pipe` 時，launcher 被 kill -9 後 unit 仍會跑完。unit 被回收後，`systemctl show` 回傳 `inactive`/`success`，與不存在的 unit 看起來相同，因此結果必須以 history 為準（N7）。本次是用 `--user` manager 測試的，system manager 的語意相同，正式環境要在 EC2 上再確認。

### 文件與程式的對照

- `deploy/README.md` 的 host.conf 鍵、退出碼、operator 指令、check 名稱與 IAM 呼叫，都從 `config.py`、`commands.py`、`operator_cli.py`、`adapters.py`、`compat.sh`、`compat_plan.sh` 直接取得。
- 文件中引用的路徑以 `ls` 核對（見本報告提交前的檢查）。

## 未解決事項

- **sudo 與 `SSH_ORIGINAL_COMMAND`（上線前必須確認）**：`deploy-entry` 讀取 `SSH_ORIGINAL_COMMAND`，但 `sudo` 預設清除它。程式內的測試直接設定環境變數，不經過 sudo，因此不會被測試發現。runbook §2.6 列出候選修正，待 EC2 上以 plan key 執行 `status` 驗證。
- **systemd-run 以 root 執行**、`INVOCATION_ID` 是否由 systemd 設定、SSH 斷線後 unit 是否存活：本機只以 `--user` 驗證（上節第 5 項）。
- **psql 容器能否連到 RDS**：未在 EC2 上驗證。
- **Compose 版本**：raw env_file 由 probe 在執行時驗證；EC2 上的版本號待記錄。
- **host nginx 設定**：不在本 repository 中。`PUBLIC_URL` 的健康檢查依賴它正確轉發並加上 `X-Forwarded-Proto`。
- **Web 的 `KnownNetworks`**：`172.31.250.0/24` 是否涵蓋 host nginx 經 docker-proxy 的來源位址，待確認。
- **GHCR visibility**：public 或 private 尚未決定；private 時 host 需要登入。
- **Immutable Releases GA**：尚未確認。
- **`production-plan` 的 reviewer**：未決定（程式不依賴）。
- **Google Books SSM 參數**：`deployment.md` 的範例參數，程式中未找到讀取位置（待確認）。
- **不變式 S1、S2**：設計計畫中沒有定義（只有 S3～S11）。本報告與文件都沒有引用它們，是否遺漏需使用者確認。
- **整合測試尚未在 CI 執行**：`BOOKFINDER_IT=1` 需要本機 Docker，目前是人工執行。
- **drift 修復**：程式只回報 drift 並拒絕部署，沒有修復指令。修復流程需人工判斷（`deploy/README.md` §5.4）。
- **snapshot 保留**：程式不刪除 snapshot；保留數量與清理由操作者手動處理。

## Code Review 與修正

（兩軸 review 後補上）
