# deploy/ 架構：責任、選型與已知差距

> 目標：`deploy/`（EC2 host 程式、release 內容、CI/CD 來源、compat 與整合測試），外加分散的 CD 來源（見 §2）。
> 查核基準：2026-10-25，HEAD `5563d80`（#121 的程式 commit；前一基準 `01db2d7`，tag `v0.0.4`）。工作樹 clean（僅既存未追蹤 `.venv`）。
> 文件修正：PR #107 依程式對照修正 C1 至 C7（見 §8）；程式未改動。
> 營運觀察（2026-10-24 operator 工作階段）以「營運觀察，非本次驗證」標示；本文件未在 EC2、AWS、GHCR 或 Cloudflare 上執行任何指令。

## 1. authority 與名詞路由

| 問題 | 先讀 | 說明 |
|---|---|---|
| 部署整體規格、環境、secret、migration 原則 | [Docs/deployment/deployment.md](../../Docs/deployment/deployment.md) | 本文件的 authority；§3.1 原生發布已標示為被取代 |
| CD 流程、host 狀態機、退出碼、人工程序、已知限制 | [deploy/README.md](../README.md) | operator runbook；與程式不一致時以程式為準（runbook 自述） |
| 為什麼用 SSH forced command、GHCR、host nginx、狀態機在 host | [architecture-decisions.md ADR-006](../../Docs/architecture/architecture-decisions.md) | 含 I1 到 I8、S1 到 S11、N1 到 N8 不變式 |
| compat 檢查的分類與檢查項目 | [Docs/testing/test-plan.md §6、§6.1](../../Docs/testing/test-plan.md) | compat 與 CI 的規格 |
| 系統拓樸（web、crawler、RDS） | [Docs/architecture/system-architecture.md](../../Docs/architecture/system-architecture.md) | 本次未讀取全文；僅作為拓樸參照 |
| 爬蟲行為（fetcher、重試、榜單） | [Docs/modules/crawler.md](../../Docs/modules/crawler.md)、[crawler/deploy/README.md](../../crawler/deploy/README.md) | 本文件只讀 crawler 的 host 端閘門 |
| Implementation report | `Docs/Implementation-Report/issue-92-cd.md`、`issue-101-crawler-enabled.md`、`issue-103-ca-bundle.md`、`issue-105-rollback-health.md` | **歷史與證據，不是 authority**（AGENTS §1 與 Implementation-Report 規定）。本文件只用來確認里程碑歸屬 |
| 領域名詞 | [CONTEXT.md](../../CONTEXT.md) | 目前不含部署名詞；本文件沿用 runbook 的詞彙（runtime、chain、dirty、paused） |

## 2. 來源盤點（實際路徑）

| 區域 | 路徑 | 角色 |
|---|---|---|
| host 程式 | [deploy/host/](../host/)：`deploy-entry`、`book-finder-admin`、`bookfinder_host/*.py`、`bookfinder_host/HOST_API_RANGE`（內容 `1 1`） | EC2 上的狀態機與人工指令（stdlib-only，靜態 import 掃描確認） |
| release 內容 | [deploy/release/](../release/)：`compose.prod.yaml`、`compose.ca-bundle.yaml`、`build-manifest.sh` | 隨 web image 的 `/opt/release/` 發布，host 以 `docker create` + `docker cp` 取出 |
| 共用 shell 函式庫 | [deploy/lib/](../lib/)：`manifest.sh`、`smoke.sh`、`schema_dump.sh`、`compat_plan.sh` | compat 與 smoke 的共用函式 |
| compat | [deploy/migration-test/](../migration-test/)：`compat.sh`、`seeds/*.sql` | 在拋棄式 DB 上驗證 migration |
| smoke | [deploy/smoke/web-smoke.sh](../smoke/web-smoke.sh) | web image 的 HTTP 煙霧測試 |
| 整合測試 | [deploy/integration/](../integration/)：`run-local.sh`、`edge_stub.py`、`imagetools-roundtrip.sh` | 真實 docker、替身 AWS 與 nginx |
| 測試 | [deploy/tests/](../tests/)：`host/`（unit）、`integration/`（`BOOKFINDER_IT=1`）、`test_*.py` | pytest |
| lint 設定 | [deploy/ruff.toml](../ruff.toml) | target py312 |
| 操作文件 | [deploy/README.md](../README.md) | runbook |
| Dockerfile | [Dockerfile](../../Dockerfile)、[.dockerignore](../../.dockerignore) | web image，含 `/opt/release/` 與 `efbundle` |
| CD | [.github/workflows/cd.yml](../../.github/workflows/cd.yml)、[.github/scripts/cd_release.py](../../.github/scripts/cd_release.py) | 發布、attestation、plan、compat、deploy、follow |
| CI | [.github/workflows/ci.yml](../../.github/workflows/ci.yml) 的 `lint`、`docker`、`crawler` job | 與部署相關的 lint、compat、image smoke、版本同步（`workflow_call` 也被 CD 使用） |
| CI 檢查腳本 | [.github/scripts/check_migrations.py](../../.github/scripts/check_migrations.py)、[check_version_sync.py](../../.github/scripts/check_version_sync.py)、`.github/scripts/tests/` | migration 不可變、SDK 與 EF 版本同步 |
| 爬蟲 host 端 | [crawler/deploy/run-crawler.sh](../../crawler/deploy/run-crawler.sh)、[crawler.cron](../../crawler/deploy/crawler.cron)、[crawler.conf.example](../../crawler/deploy/crawler.conf.example)、[crawler/tests/test_deploy.py](../../crawler/tests/test_deploy.py) | cron 入口、N3 閘門、CD 改寫的 `CRAWLER_IMAGE=` |

## 3. 責任與 caller／callee

| 元件 | 責任 | caller | callee | 主要輸入輸出 |
|---|---|---|---|---|
| `cd.yml` | 編排 job、環境核准、secret 寫入暫存檔 | GitHub（tag、dispatch） | `cd_release.py`、`ci.yml`（workflow_call）、SSH | job outputs（plan 有 12 個字串 output）、Immutable Release |
| `cd_release.py` | release 記錄、attestation 驗證、plan 解讀、compat 摘要、deploy 跟隨 | `cd.yml` 各 step | `gh`、`docker`、`ssh` | `release.json`、`plan.json`、`compat-report.json`、`GITHUB_OUTPUT` |
| `deploy-entry` | SSH forced command 的入口，解析 `SSH_ORIGINAL_COMMAND`，拒絕 plan key 的 deploy | sshd（經 sudo） | `commands.main` | 指令 token，退出碼 |
| `commands.py` | 指令語法、plan、status、deploy SSH 端、unit 本體、gates | `deploy-entry` | `machine`、`runs`、`history`、`state`、`runtime`、`locks`、`adapters` | JSON（stdout）、退出碼 |
| `machine.py` | 狀態機 step 0 到 7、forward migration、切換、回滾、crawler 更新 | `commands._deploy_locked` | `ports.Effects`（docker、compose、systemd、aws、ssm、http、files） | `state.json`、`history` completed、`web-RUN.env` |
| `operator_cli.py` | 五個人工指令、operator 協定、install-host 的 symlink 交換 | `book-finder-admin` | `history`、`state`、`locks`、`runtime`、`adapters` | `operator-started` 與 `operator-completed` |
| `history.py` | append-only JSONL、tail 修復、status 規則 | `commands`、`runs`、`operator_cli` | 檔案系統 | 單行 JSON，單行上限 < PIPE_BUF |
| `state.py` | `state.json` 的解析（拒絕重複鍵、未知鍵）、CAS 寫入、純轉換 | 各處 | 檔案系統 | `state.json` |
| `runtime.py` | 觀察實際的 web container、systemd unit、schema（`__EFMigrationsHistory`） | `commands`、`machine` | `ports.Effects` | drift 清單 |
| `config.py` | host.conf 解析、鍵白名單、值字元集、DB_CA_BUNDLE 檢查、User-Agent | 各處 | 檔案系統 | `Settings` |
| `manifest.py` | release metadata 與 migration 的解析、classify、pending | `commands`、`machine` | — | `ReleaseMetadata` |
| `release_content.py` | 取出後的內容驗證（symlink、大小、必要檔案） | `machine._materialize_release` | — | `ReleaseContent` |
| `adapters.py` | 真實的外部呼叫（AWS CLI、docker、compose、systemctl、urllib、檔案） | `ports` 介面 | OS | — |
| `locks.py` | flock 包裝，有界輪詢，拒絕 symlink 鎖檔 | `commands`、`machine`、`operator_cli` | fcntl | 鎖 |
| `runs.py` | unit 名稱（`book-finder-deploy-<run_id>`）、unit 狀態、indeterminate 清單 | `commands`、`machine` | `systemctl` | — |
| `ports.py`、`testing.py`、`tests/host/worlds.py` | 介面（ports）與測試替身（fake world、fake clock） | 測試與 `machine` | — | — |
| `run-crawler.sh` | crawler 的 cron 入口、lock、state 閘門、SSM DB URL、docker run | cron | `aws`、`docker`、`python3 -I`（讀 state） | 日誌、退出碼 |

## 4. 選型表

面向列出：目前選擇、依據（有記錄者標出處；無記錄者標「程式可見的選擇，理由未記錄」）、替代方案、代價。

| 面向 | 目前選擇 | 依據 | 替代方案 | 代價與維護重點 |
|---|---|---|---|---|
| 部署傳輸 | SSH，兩組 key（plan、deploy），`authorized_keys` 的 forced command 與 `restrict` | ADR-006 Decision | OIDC + SSM Run Command（ADR-006 Alternatives） | 長期 SSH key；`sudo` 的 `env_keep` 必須在 EC2 驗證（runbook §2.6）。ADR 註明未來可換傳輸層，host 程式保留 |
| 狀態機位置 | EC2 上的 host 程式（`deploy/host`），不在 CI shell | ADR-006 Decision（web 壞掉時仍要能運作） | 把狀態機放 CI；放進 image（ADR-006 Alternatives） | host 程式版本需 `install-host` 升級（L4），受 `HOST_API_RANGE` 限制（N4） |
| 執行單位 | `systemd-run --unit=book-finder-deploy-<run_id> --collect`，不使用 `--pipe` | N7、S1 | 在 SSH 連線內直接執行 | 結果不依賴 SSH 連線；代價是 system manager 行為只在 EC2 驗證（runbook §7.2 #2、#3 仍標「待確認」） |
| 結果來源 | `history.jsonl` append-only，`started` 與 `completed` 各一；unit 狀態只作輔助 | N7、ADR-006 | 以 unit 退出碼當結果 | `indeterminate` 需人工 `resolve-run`；不能自動重送 |
| state 寫入 | 臨時檔、fsync、rename，revision 每次 +1，CAS 檢查 | S4、`state.py` | 直接覆寫 | 寫入失敗保留舊版；CAS 失敗回 exit 3 |
| host 程式安裝 | `host-versions/<16 hex>/` 加 `/opt/book-finder/host` symlink，以 rename（`RENAME_EXCHANGE` 或 link 交換）替換 | S9，`operator_cli._swap_install` | 原地覆寫目錄 | 殘留 `host.new-*` 會拒絕下次安裝（runbook §2.7） |
| 容器 registry | GHCR，以 digest 指定；release tag 由 `imagetools create --prefer-index=false` 建立 | ADR-006、commit `5ff8a51`（保留 attested digest） | Docker Hub（ADR-006 Alternatives） | 依賴 `imagetools` 行為；CI 的 `imagetools-roundtrip.sh` 在本機 registry 驗證；GHCR 版本刪除會連同 tag 一起刪（runbook §1.6） |
| 來源證明 | `actions/attest-build-provenance` 加 `verify-attestation` 在 CD 端；host 不驗證 | I7、runbook §5.2、§7.1 | host 以 `gh` 驗證 | host 無 `gh` 與 sigstore；人工 `--rebuild-web-digest` 與 `--adopt-*` 的 provenance 由操作者負責 |
| 反向代理與 TLS | host nginx（不在 repository），web 綁 `127.0.0.1:5000`；TLS 由 `acme.sh` | ADR-006 Alternatives（保留 host nginx） | nginx 放進 container | nginx 規則不在本 repository（runbook §7.2 #7 待確認）；Cloudflare 位於前方（營運觀察） |
| compose 設定注入 | `env_file` `format: raw`，啟動前以 probe 確認 Compose 支援（不使用版本下限） | `machine.compose_raw_env_check`、commit `3b21c71`（以能力探測取代版本下限） | 版本下限；Compose 插值 | 每次 plan 與 deploy 都會呼叫 `docker compose config`；probe 失敗即拒絕 |
| secret 來源 | host 以 EC2 IAM role 讀 SSM；寫 `web-RUN.env`（600），用後刪除；設定 `SSM_MIGRATION_CONNECTION` 時另寫 `migrate-RUN.env`（600，只供 efbundle）；crawler 另有自己的 DB URL 參數 | deployment.md §5、runbook §2.3 | 把 secret 放進 host.conf 或 compose | 值不寫入 history 與 journal；遮蔽只做字面替換（見 DEP-B12） |
| migration 時機 | 只在 forward 時由 host 執行 image 內 `efbundle`；web 啟動不跑 migration | deployment.md §6 | web 啟動時自動 migrate | 失敗後 dirty，只能人工解除（N2、I3）；不自動回滾（I5） |
| 人工指令的並行 | `operator-started` 寫入後才變更；未完成的 operation 讓後續指令拒絕（exit 8） | S8、S10 | 不記錄 started | 人工中斷會造成 operator operation 保持 open，必須 `resolve-run` |
| 爬蟲與 migration 的互斥 | `db-maintenance.lock`：deploy 取 exclusive，crawler 取 shared，且先取鎖再讀 state | N3 | 只靠 paused 旗標 | 爬蟲等待上限 7200 秒；兩端預設值需一致（runbook §7.2 #16） |
| 爬蟲 pause 的範圍 | in-sync 的 crawler 步驟失敗也會 pause（與 N3 原文不同） | runbook §7.1（刻意偏離，已記錄） | 只在 forward pause | 由 `run-crawler.sh` 閘門執行；恢復需 `resume-crawler`（L4） |
| 健康檢查 | 本機 `127.0.0.1:5000` 先，再 `PUBLIC_URL`；每段 90 秒；送出 `book-finder-deploy/<max>` UA，不跟隨 redirect | machine.py 常數、commit `2fb5e27`（#105） | 只檢查本機 | 公開階段依賴 edge 放行 UA（見 DEP-B02） |
| 爬蟲 fetcher | curl_cffi（預設）；browser 僅供診斷 | deployment.md §5、crawler.md §12 | — | EC2 的 IP 被博客來封鎖（營運觀察，見 DEP-B01） |

## 5. 公開 contract 對照

### 5.1 退出碼與 history result

來源：[exit_codes.py](../host/bookfinder_host/exit_codes.py)、[operator_cli.py](../host/bookfinder_host/operator_cli.py)（`RESOLVE_EXIT`）。

| 碼 | 名稱 | history result | 來源常數 |
|---|---|---|---|
| 0 | OK | `success` | `OK` |
| 1 | ROLLED_BACK | `rolled-back` | `ROLLED_BACK` |
| 2 | BAD_INPUT | `rejected` | `BAD_INPUT` |
| 3 | DRIFT | `drift` 或 `rejected`，依發生點（對照見 [README §1.5](../README.md)） | `DRIFT` |
| 4 | FAILED_MIGRATION | `failed-migration` | `FAILED_MIGRATION` |
| 5 | FAILED_DOWN | `failed-down` | `FAILED_DOWN` |
| 6 | DIRTY | `rejected` | `DIRTY` |
| 7 | PARTIAL_CRAWLER | `partial-crawler` | `PARTIAL_CRAWLER` |
| 8 | INDETERMINATE | `blocked-indeterminate` 或無 completed | `INDETERMINATE` |

`status` 固定退出碼 0；部署結果看 JSON 的 `status`。`deploy --detach` 成功接手時輸出 `launched` 與 exit 0，不是結果。

**exit 3 與 `result` 的對應（現行行為，文件已對齊）**：`RESULT_BY_EXIT[DRIFT]` 為 `rejected`，用於 gate 失敗（`GateFailure`）；狀態機的 `_Stop(DRIFT, "drift", …)`、unit 本體的 lock 逾時與 state 不存在寫 `drift`；SSH 入口與 `plan` 的 exit 3 不寫 history；`resolve-run --result drift` 也寫 `drift`。完整對照見 [README §1.5](../README.md) 的「exit 3 的 history 對照」。程式未改動；兩種 `result` 是否統一列為 DEP-B17。

### 5.2 history 紀錄（JSON Lines，單行）

| 類型 | 寫入者 | 主要欄位 | 規則 |
|---|---|---|---|
| `started` | unit 本體（`run_deploy_unit`） | `run_id`、`unit`、`at`、`target`（tag、web_digest、crawler_digest）、`expected_revision` | 在任何 lock 與 state 讀取之前，fsync |
| `completed` | `finish_run`、`resolve-run` | `run_id`、`result`、`exit_code`、`at`、`state_summary`、`snapshot_id`、`crawler_substeps` | 每個 run 最多一筆（N7） |
| `operator-started` | `operator_cli._perform` | `op_id`、`action`、`operator`、`reason`（最多 400 字）、`intended`、`before` | 變更前 fsync |
| `operator-completed` | `operator_cli._complete` | `op_id`、`result`、`before`、`after`、可選 `tail_repair` | 只在成功或經驗證未變更時 |

單行上限低於 PIPE_BUF（`test_append_refuses_a_record_at_or_above_pipe_buf`）；錯誤訊息截斷到 500 字（`MAX_ERROR_CHARS`）。

### 5.3 state.json（`schema`、`runtime`、`crawler`、`pause`）

來源：[state.py](../host/bookfinder_host/state.py)。`load_state` 拒絕重複鍵、未知頂層鍵、缺鍵、符號連結、負數 revision、dirty 無 metadata 的組合，以及 `schema.digest` 與 applied 不符。欄位摘要：

- `revision`：整數，每次寫入 +1。
- `runtime`：`docker`（tag、web_digest、crawler_digest、compose_sha256、release_dir、release_api）或 `systemd`（unit、version）；`previous_runtime` 保存上一個。
- `schema`：`applied`（id 與 source_hash 陣列）、`digest`、`rebuild`（tag、web_digest）、`dirty`、`dirty_since`、`dirty_release`。
- `crawler`：`digest`、`runner_sha256`、`cron_sha256`、`source_release`（tag、web_digest）、`paused`（release、reason、since）或 null。

### 5.4 host.conf 鍵（只列名稱）

必填：`STATE_FILE`、`HISTORY_FILE`、`DEPLOY_LOCK_FILE`、`WEB_IMAGE_REPOSITORY`、`PSQL_IMAGE`、`DATABASE_URL_PARAMETER`、`AWS_REGION`、`SYSTEMD_UNIT`、`PUBLIC_URL`、`RDS_INSTANCE_ID`、`SSM_DB_CONNECTION`、`SSM_OPENAI_KEY`、`SSM_JWT_KEY`、`CRAWLER_IMAGE_REPOSITORY`。
選填：`DB_CA_BUNDLE`、`SSM_MIGRATION_CONNECTION`（只供 efbundle；未設定時沿用 `SSM_DB_CONNECTION`）、`COMPOSE_PROJECT`、`LOCK_TIMEOUT_S`、`FOLLOW_TIMEOUT_S`、`CRAWLER_CONF`、`DB_MAINTENANCE_LOCK`、`RELEASES_DIR`、`RUN_DIR`、`CRAWLER_RUNNER`、`CRON_FILE`、`AWS_CLI`。
字元與大小限制見 [runbook §2.4](../README.md)；重複或未知鍵拒絕，檔案上限 64 KiB。

### 5.5 release 與 CD 記錄

- `release.json` 的鍵（`RELEASE_KEYS`）：`schema_version`、`tag`、`commit`、`web_digest`、`crawler_digest`、`release_api`、`migrations`、`sql_assets`。
- `migrations.txt`：每行 `<id> <source_hash>`，`id` 格式 `14 位時間戳_名稱`。
- `compat-report.json`：`schema_version: 1`、`classification`、`pending`、`checks`、`forward_ok`、`runtime_smoke`（見 test-plan §6.1）。
- CD `plan` 輸出的 12 個 step output（`revision`、`expect_runtime`、`expect_schema`、`chain`、`pending`、`applied_last`、`rebuild_tag`、`rebuild_web_digest`、`runtime_web_digest`、`state_crawler_digest`、`crawler_for_deploy`、`cutover_ok`）。

### 5.6 plan 與 status JSON

- `plan`：單一 JSON 物件，含 `revision`、`runtime`（state 與 observed）、`drift`、`schema`、`crawler`、`compose_version`、`target`、`classification`、`pending`、`blocked`。
- `status`：`{"run_id": ..., "status": "completed:<result>" | "running" | "indeterminate" | "not-started"}`，退出碼 0。

## 6. 安全、一致性、時間與錯誤邊界

**安全**

- SSH：plan 與 deploy 分開 key；forced command 只接受固定入口；`sudoers` 只允許 `deployer` 以 root 執行 `deploy-entry`（runbook §2.6）。`sudo` 的 `env_keep` 只對該指令保留 `SSH_ORIGINAL_COMMAND`。
- secret：host 以 IAM role 讀 SSM，不經 CD；CD 的 SSH 相關 secret 只有 SSH key 與 `SSH_KNOWN_HOSTS`（environment secret），另有 GitHub token。CI 不使用 secret。
- 測試保護：`BOOKFINDER_HOST_TEST_FAKES` 測試 hook 對 root 拒絕（`test_test_hook_is_refused_for_root`）。
- 遮蔽：`machine._mask` 以字面字串替換三個 secret 值與 `Password=` 的值；`_secret_strings` 只保留非空值。見 DEP-B12。
- TLS：`PUBLIC_URL` 必須是 `https://`，或僅限 `127.0.0.1` 的 `http://`（`test_public_url_allows_plain_http_only_on_loopback`）。DB 連線採用 `verify-full` 與 `DB_CA_BUNDLE`，不放寬為 `Require`（runbook §2.3）。

**一致性**

- 每次部署的變更順序：gates、step 1 健康、release 取出、env 寫入、migration（forward）、切換、crawler。
- forward 之後不自動回滾（I5）；schema-ahead 不 migrate、不動 crawler（S6、S7）。
- state 與 history 的寫入順序決定了 `indeterminate` 的判定（`started` 早於任何變更）。
- 清理：`web-RUN.env` 在每條路徑的 `finally` 刪除；release 目錄以 digest 命名，同 digest 的 compose 雜湊必須一致。

**時間預算（常數來源）**

| 項目 | 值 | 來源 |
|---|---|---|
| 本機健康探測（step 1） | 最多 3 次，每次逾時 5 秒，次之間等 1 秒；3 次都失敗即 drift（未改動） | `machine.py` `PROBE_TRIES`、`PROBE_TIMEOUT_S`、`PROBE_INTERVAL_S` |
| 切換後與回滾後的健康預算 | 本機 90 秒，再 `PUBLIC_URL` 90 秒（各自到期判定；每次請求逾時 5 秒，請求間隔 2 秒，到期時最後一次回應即判定） | `machine.py` `HEALTH_BUDGET_S`、`HEALTH_INTERVAL_S`、`PROBE_TIMEOUT_S` |
| `deploy --detach` 等待接手 | 最多 60 秒；`not-started` 寬限 30 秒 | `commands.DETACH_ACK_TIMEOUT_S`、`NOT_STARTED_GRACE_S` |
| 不帶 `--detach` 的跟隨 | 預設 6000 秒（`FOLLOW_TIMEOUT_S`） | host.conf 預設值 |
| CD 跟隨 | 每 30 秒，最多 160 分鐘；`not-started` 寬限 120 秒 | `cd_release.py` 常數，`test_follow_budget_is_160_minutes_and_fits_the_180_minute_job` |
| CD job timeout | build 90 分鐘，deploy 180 分鐘 | `cd.yml` |
| deploy lock | `LOCK_TIMEOUT_S` 預設 10 秒 | runbook §2.4 |
| 爬蟲等待 maintenance lock | 7200 秒 | `run-crawler.sh` `DB_MAINTENANCE_WAIT_S` |
| 分類補書間隔 | 距上次成功 72 小時 | `run-crawler.sh`（`259200` 秒） |

**錯誤邊界**

- 已知結果：每個 `started` 之後的已知路徑寫一筆 `completed`。未預期例外不寫 completed，該 run 之後判定為 `indeterminate`（`test_crash_during_efbundle_writes_no_completed_record_and_blocks_later_runs`）。
- 人工指令：只有經驗證未變更才寫 `failed`；其他情況 operation 保持 open。
- 網路：SSH 255 視為暫時無回應；其他 status 失敗使 CD job 失敗並以 `unknown` 回報。

## 7. 已知差距與未驗證事項

詳細項目與驗收條件見 [backlog.md](backlog.md)。摘要：

- **production 未驗證的路徑**：forward migration、RDS snapshot、efbundle 寫入 dirty、`resolve-run`、`reconcile-schema --mark-clean`、`resume-crawler --adopt-release`、rollback 的 docker 分支。（DEP-B04）
- **爬蟲在 EC2 不可用**：博客來封鎖 EC2 IP，`CRAWLER_ENABLED=false`（營運觀察）。（DEP-B01）
- **公開健康檢查**：User-Agent 修正（#106 已合併）需在 EC2 的 host 程式與 edge 規則生效；營運觀察未記錄 EC2 上 host 程式的版本。（DEP-B02）
- **回滾下限**：`DB_CA_BUNDLE` 啟用後，`v0.0.1` 與 `v0.0.2` 不可作為回滾目標（已以 git tree 確認這兩個 tag 沒有 `compose.ca-bundle.yaml`）。（DEP-B03）
- **runbook 待確認項目**：§7.2 的 #1 至 #5、#11、#17 已由 2026-10-24 營運觀察確認（PR #107 同步，見 DEP-B16）；其餘（如 #6 至 #10、#12、#15、#16、#18、#20）仍待確認或待決定。
- **結構性**：`operator_cli.py` 1061 行、`cd_release.py` 1005 行、`commands.py` 703 行、`machine.py` 702 行；`cd.yml` 的 SSH 設定重複兩次。（DEP-B09、DEP-B11）

## 8. 文件與程式衝突

以下衝突已於 2026-10-24 逐項對照程式與 git，並由 PR #107 處理。處理欄只描述文件變更；**程式未改動**。

| # | 位置 | 衝突 | 程式或 git 證據 | 嚴重度 | 處理 |
|---|---|---|---|---|---|
| C1 | [deploy/README.md §3.4](../README.md) step 3 與 step 7 | 寫「三次，每次 5 秒」，語意不清 | `machine.py`：step 1 探測最多 3 次，每次逾時 5 秒，次之間等 1 秒（`PROBE_TRIES`、`PROBE_TIMEOUT_S`、`PROBE_INTERVAL_S`）；健康預算 90 秒（`HEALTH_BUDGET_S`），輪詢間隔 2 秒（`HEALTH_INTERVAL_S`） | 低（文件措辭） | 已修正文件（PR #107）：step 3 改為逐項的次數、逾時與間隔；step 7 補上判定預算與請求參數；§6 的時間預算表同步 |
| C2 | [deploy/README.md §1.5](../README.md) exit 6 | 只寫 `run-crawler.sh` 以 exit 6 跳過 `dirty` | `run-crawler.sh`：`paused` 與 `dirty` 都 exit 6；`CRAWLER_ENABLED=false` 為 exit 0（`skipped=disabled`）；非法值與非法 `DB_CA_BUNDLE` 為 exit 2 | 低（文件遺漏） | 已修正文件（PR #107）：exit 6 列出 paused 與 dirty；新增 `run-crawler.sh` 退出碼表 |
| C3 | [deploy/README.md §1.5](../README.md) exit 3 與 history `result` | 表格寫 exit 3 對應 `drift`；`RESULT_BY_EXIT` 寫 `rejected` | `exit_codes.py` 的 `RESULT_BY_EXIT[DRIFT]` 為 `rejected`，用於 gate 失敗；`commands.py` 的 unit 本體（lock 逾時、state 不存在）與 `machine.py` 的 `_Stop(DRIFT, "drift")` 直接寫 `drift`；`resolve-run` 也可寫 `drift` | 中 | 已修正文件（PR #107）：README §1.5 新增「exit 3 的 history 對照」表，列出每個發生點寫入的 `result` 與不寫 history 的路徑；說明 `status` 使用者要一起看 `exit_code` 與 `result`。**程式未改**；統一列為 DEP-B17 |
| C4 | [deploy/README.md §5.1](../README.md) 與 §1.5 | 文件未說明損壞的 history 尾端；實作中 operator 指令回 exit 3，plan 與 unit 本體回 exit 8 | `operator_cli._refuse_while_indeterminate`（`DRIFT`）；`runs.indeterminate_reasons` 與 `commands.run_deploy_unit`（`INDETERMINATE`）；測試 `test_plan_blocked_by_corrupt_history_tail_exits_8` | 中 | 已修正文件（PR #107）：§1.5 的 exit 8 與 exit 3 說明補上尾端情況；§5.1 說明差異與修復（`resolve-run`，碎片保存到 sidecar）。**程式未改**；統一與否仍為 DEP-B08（待決策） |
| C5 | [deploy/README.md §7.2](../README.md) #1 至 #5、#11、#17 | 仍寫「待確認」；營運觀察已有證據 | 僅營運觀察（非本次驗證）：run `40078171943` 以 transient unit 完成並寫入 `completed:success`；plan key `status 1-1` 回傳 `not-started`；host `plan` 讀取 RDS 的 migration 歷史；Compose 5.6.1 的 raw env_file probe 通過；`Confirm the web/crawler release tag` 對 v0.0.1 至 v0.0.4 通過；Immutable Releases 的 release 為 `immutable=true` | 低（文件可能過時） | 已修正文件（PR #107）：上述 7 項標示「已由營運確認（2026-10-24）」並附證據；其餘保持待確認。營運觀察不是自動化測試 |
| C6 | [deploy/README.md §3.1](../README.md) 第 5 項 | 寫 `v0.0.1` 尚未支援 `CRAWLER_ENABLED`，建議發布 `v0.0.2` | `git merge-base --is-ancestor 3637cff v0.0.2` 成立；`v0.0.2` 的 `run-crawler.sh` 含 `CRAWLER_ENABLED`；`DB_CA_BUNDLE` 自 `v0.0.3`（`compose.ca-bundle.yaml`）；UA 修正（`2fb5e27`）是 `v0.0.4` 的祖先 | 低（操作指引已過時） | 已修正文件（PR #107）：改為現行版本說明（`CRAWLER_ENABLED` 自 v0.0.2、`DB_CA_BUNDLE` 自 v0.0.3、目前 production 為 v0.0.4），移除「請發布 v0.0.2」的建議 |
| C7 | [deploy/README.md §2.5](../README.md) 與程式 | 文件要求 `/etc/book-finder` 為 0755，程式不檢查目錄權限 | `config.check_ca_bundle` 只檢查 CA 檔案（`lstat`、一般檔案、others 可讀、大小） | 低（文件要求未自動化） | 已修正文件（PR #107）：§2.5 明確說明目錄權限為操作者要求、程式不檢查，並給出 `stat -c %a /etc/book-finder`。**程式未改**；自動檢查列為改善提案 DEP-B15 |
| C8 | [Docs/deployment/deployment.md §3.1](../../Docs/deployment/deployment.md) | 仍有「原生發布」段落，已標示為被取代 | 內文自述 | 無（已標示） | 無變更 |

## 9. 維護重點

- 修改 state、history、exit code 或 `HOST_API_RANGE` 時，必須同步更新 ADR-006、runbook 與本文件（ADR-006「Migration impact」）。
- 修改 `run-crawler.sh` 的閘門順序時，必須確認 N3（先取鎖、再讀 state）仍成立，並執行 crawler 的 `test_deploy.py`。
- 修改 `cd.yml` 的 commit point 或 `imagetools` 旗標時，必須執行 `imagetools-roundtrip.sh` 的對照組（test-plan §6）。
- 新增人工指令時，必須採用 `_perform` 的 operator 協定（S8、S10），並加入 runbook §5。
