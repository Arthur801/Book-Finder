# deploy/ 測試案例庫（AI 可操作的文字案例）

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M3（#120）補記：2026-10-25 更新；程式變更以 `d249c07`、`6e70e93`、`b99b368` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 目標：`deploy/`（host 程式、CD 腳本、compat、整合測試）與分散的 CD 來源。
> 查核基準：2026-10-24，HEAD `01db2d7`。本次文件任務**沒有執行任何測試命令**；狀態「已有測試」只表示測試存在，不表示本次通過。
> 規格來源：[deploy/README.md](../README.md)（runbook）、[Docs/deployment/deployment.md](../../Docs/deployment/deployment.md)、[ADR-006](../../Docs/architecture/architecture-decisions.md)、[test-plan §6](../../Docs/testing/test-plan.md)。
> 待辦與案例 ID 的對應見 [backlog.md](backlog.md)；流程與退出碼見 [workflow-diagram.md](workflow-diagram.md)；責任與 contract 見 [architecture.md](architecture.md)。

## 0. 證據類別（不可混用）

| 代號 | 類別 | 可以證明什麼 | 不能證明什麼 |
|---|---|---|---|
| S | 靜態檢查（lint、shellcheck、版本同步、migration 不可變檢查、Dockerfile 與 compose 內容、Unicode 15.1 表格與 vendored 資料一致性 `unicode_tables.py --check`） | 文字與格式符合規則 | 執行時行為 |
| M | 替身單元（fake world、fake clock、ScriptedRunner） | 狀態機分支與順序 | 真實 docker、systemd、AWS 的行為 |
| I | 拋棄式整合（`BOOKFINDER_IT=1`，真實 docker 與 pgvector，AWS 與 nginx 為替身） | 真實 image、compose、unit body 與 history 的互動 | systemd system manager、真實 SSM、真實 RDS、真實 nginx |
| O | 營運觀察（2026-10-24 operator 工作階段） | production 曾發生的事件 | 本次驗證；不可當作測試通過 |

狀態只使用以下四種（與 test-plan §6 一致）：**已有測試但本次未執行**、**待補強**、**未實作**、**明確暫緩**。營運觀察以「營運觀察」標示，不屬於上述狀態。

## 1. 共同 fixture、隔離與可控時間

**host 單元測試**（`deploy/tests/host/`，類別 M）

- `make_world(tmp_path, state=..., target=..., release_api=..., db_ids=..., now=...)`（[worlds.py:113](../tests/host/worlds.py)）回傳 `World` 物件，內含 settings（`build_settings`，[worlds.py:42](../tests/host/worlds.py)，鎖逾時 0.2 秒）與替身；細節以 worlds.py 為準。
- 替身：`FakeDocker`、`FakeCompose`、`FakeAws`、`FakeSsm`、`FakeSystemd`、`FakeHttp`、`TracingFiles`（[testing.py](../host/bookfinder_host/testing.py)）。`ScriptedRunner` 為腳本化的命令執行替身（[testing.py:20](../host/bookfinder_host/testing.py)）。
- `write_release(directory, migrations, release_api, compose)`（[testing.py:189](../host/bookfinder_host/testing.py)）產生 release 目錄。
- 時間：只能用 `FakeClock`（`sleep` 會推進時間，`monotonic` 可控）。測試不呼叫真實 `time.sleep`（`test_timeout_uses_injected_clock_so_tests_do_not_sleep`）。
- 檔案：一律使用 pytest 的 `tmp_path`；host 測試不寫入 `/opt`、`/var`、`/etc`。
- 測試 hook：`BOOKFINDER_HOST_TEST_FAKES` 只在非 root 下可用，root 執行時拒絕（`test_test_hook_is_refused_for_root`）。

**crawler 測試**（`crawler/tests/test_deploy.py`，類別 M）

- fixture `host` 寫入 `crawler.conf`、`stubs.sh`（以 bash function 取代 `aws`、`docker`、`flock` 等外部命令），`PATH` 固定。不連網、不連 AWS、不連博客來。

**CI 腳本測試**（`.github/scripts/tests/`，類別 M/S）

- `conftest.py` 提供測試共用的 fixture（逐一內容未核對）；`check_migrations` 的測試以臨時目錄放置 migration 檔案（見各測試函式）。

**整合測試**（`deploy/tests/integration/`，類別 I，需 `BOOKFINDER_IT=1`）

- 所有 docker 物件以 `bf-it-*` 命名，module fixture 結束後移除；registry 為 `127.0.0.1`；AWS 為可執行替身；nginx 為 `deploy/integration/edge_stub.py`。
- `deploy/tests/conftest.py` 註冊 `integration` marker，未設 `BOOKFINDER_IT=1` 時跳過。

**禁止事項**：文件任務與本案例庫的命令，不得連到真實 AWS、RDS、SSM、GHCR、EC2 或博客來。真實抓取、production 寫入與 secret 讀取屬 L4，需當前任務授權。

## 2. 執行命令（來自 CI、runbook 與 test-plan）

| 命令 | 來源 | 前置條件與安全範圍 | 本次狀態 |
|---|---|---|---|
| `pytest .github/scripts/tests deploy/tests -q` | `ci.yml` 的 `lint` job（Python 3.14） | 本機 venv；不需 Docker；單元測試不連網 | 已有測試但本次未執行 |
| `python -m pytest deploy/tests -q` | `ci.yml` 的 `lint` job（Python 3.12，對應 Ubuntu 24.04） | 同上；`uv` 或系統 Python 3.12 | 已有測試但本次未執行 |
| `cd crawler && pytest` | `ci.yml` 的 `crawler` job | 需 `requirements.txt`；Playwright 測試需 Chromium，否則跳過 | 已有測試但本次未執行 |
| `cd crawler && pytest tests/test_deploy.py -q` | 同上（單檔） | 同上 | 已有測試但本次未執行 |
| `ruff check --config deploy/ruff.toml deploy` 與 `ruff format --check --config deploy/ruff.toml deploy` | `ci.yml` `lint` job | ruff 版本依 `crawler/requirements.txt` 固定 | 已有檢查但本次未執行 |
| `shellcheck deploy/release/build-manifest.sh deploy/smoke/web-smoke.sh deploy/lib/manifest.sh deploy/lib/smoke.sh deploy/lib/schema_dump.sh deploy/lib/compat_plan.sh deploy/lib/contract_allowance.sh deploy/migration-test/compat.sh deploy/integration/imagetools-roundtrip.sh` | `ci.yml` `lint` job | 需 shellcheck | 已有檢查但本次未執行 |
| `python .github/scripts/check_version_sync.py` | `ci.yml` `lint` job | 讀取 `global.json`、`Dockerfile`、compose | 已有檢查但本次未執行 |
| `python .github/scripts/check_migrations.py [--released-manifest FILE]` | `ci.yml` `lint` job | 比對已發布的 `migrations.txt` | 已有檢查但本次未執行 |
| `BOOKFINDER_IT=1 bash deploy/integration/run-local.sh` | test-plan §6.2 與 runbook | 需本機 Docker；建立 `bf-it-*` 容器；使用 port 5000；**不在 CI** | 已有測試但本次未執行（不列為 production 證據） |
| `docker build --build-arg GIT_COMMIT=… -t book-finder-web:ci .` 與 `bash deploy/smoke/web-smoke.sh book-finder-web:ci`（含 `--control-no-keys`） | `ci.yml` `docker` job | 需 Docker；內部網路；placeholder secrets | 已有測試但本次未執行 |
| `bash deploy/integration/imagetools-roundtrip.sh` | `ci.yml` `docker` job | 需 Docker 與本機 registry（`127.0.0.1`） | 已有測試但本次未執行 |
| `deploy/migration-test/contract/20261025120000_ContractMultiSourceCatalog/`（allow.tsv、verify.sql）| 011 的 reviewed allowance；只在 011 為 pending 時套用。`verify.sql` 必須回傳 0 列 | `test_contract_allowance.py`（解析、非 pending 忽略、drop-column 仍存在、判定）；`ContractMigration011VerifyTests`（每種違規都回傳一列）；本地 compat 通過（見 update-history） |
| `deploy/migration-test/preflight/20261025120000_ContractMultiSourceCatalog.sql`（011 gate 7，唯讀） | production 在 010 時由操作者執行（`deploy/README.md` §4.4）。不由 CI 執行 | `ContractMigration011PreflightTests`（test-plan row 20） |
| `deploy/migration-test/seeds/20261024160045_MultiSourceCatalog.sql`（010 head seed）| compat 在 applied 為 010 時必須有此 seed；本次只以 Testcontainers 驗證可載入並列數（`book_sources` 5 筆、`book_subjects` 3 筆、`book_offers` 2 筆） | 待 CI compat 證據 |
| `bash deploy/migration-test/compat.sh --rebuild-image IMG --target-image IMG [--runtime-image IMG\|none] --applied FILE --seeds-dir DIR --report OUT.json` | CD `compat` job；`ci.yml` 在 PR 條件下執行 | 需 Docker 與 GHCR digest；拋棄式 DB | 已有測試但本次未執行 |
| `BOOKFINDER_IT=1 python -m pytest deploy/tests/integration/test_prev_release_on_contract.py -m integration -q -s`，或 `bash deploy/migration-test/prev-release-on-contract.sh --target-image IMG --prev-web-image IMG --prev-crawler-image IMG` | gate 9 與 manual recovery（`deploy/README.md` §4.5）；不在 CI | 需 Docker；建立並移除 `bf-prev-*` 的容器、內部網路與 volume；離線（不連博客來）；前一個 release 的 image 以 digest 指定 | 本次已執行（M4，見 update-history §3.13） |
| `ssh -i <plan key> -o IdentitiesOnly=yes deployer@<EC2_HOST> "status 1-1"`（預期 `not-started`，exit 0） | runbook §2.6（上線前驗證） | 只讀；不改變 state | 營運觀察（上線前驗證的結果未記錄） |

**未在 CI 或 runbook 中找到的命令**：`actionlint`。`ci.yml` 沒有呼叫它；只有 `Docs/Implementation-Report/` 的歷史報告提到（DEP-CI-01 列為未實作）。

## 3. 案例

### 3.1 HTTP 探測與 User-Agent（host，類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-HTTP-01 | `RealHttp` 的 headers 不含 User-Agent | 呼叫 `status(url, headers, timeout)` | 送出的 UA 為 `book-finder-deploy/<max>`，不是 `Python-urllib` | `test_adapters.py::test_http_probe_sends_the_host_user_agent_not_the_urllib_default` | 已有測試但本次未執行（M） |
| DEP-HTTP-02 | `HOST_API_RANGE` 為 `1 1` | 取得預設 UA | 值為 `book-finder-deploy/1` | `test_adapters.py::test_default_http_probe_user_agent_is_the_host_api_max` | 已有測試但本次未執行（M） |
| DEP-HTTP-03 | 呼叫端自帶 User-Agent | 呼叫 `status` | 保留呼叫端的 UA | `test_adapters.py::test_http_probe_keeps_a_caller_provided_user_agent_in_any_case` | 已有測試但本次未執行（M） |
| DEP-HTTP-04 | 目標回 301 | 呼叫 `status` | 回傳 301，不跟隨 redirect | `test_adapters.py::test_http_probe_keeps_the_no_redirect_rule_with_the_user_agent` | 已有測試但本次未執行（M） |

### 3.2 健康檢查與回滾預算（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-HEALTH-01 | 步驟 1 的本機探測三次都非 200 | 執行 `run_state_machine` | exit 3（drift），未改變 runtime、未 migrate、未寫 release | `test_machine.py::test_step1_health_failure_is_drift_and_changes_nothing` | 已有測試但本次未執行（M） |
| DEP-HEALTH-02 | in-sync 切換後公開 URL 持續非 200 | 執行切換 | 進入回滾，結果 `rolled-back`（exit 1）當舊 runtime 恢復 | `test_machine.py::test_post_switch_public_health_failure_rolls_back` | 已有測試但本次未執行（M） |
| DEP-HEALTH-03 | 公開階段回 403，本機回 200 | 切換失敗 | journal 含 `health check failed at the public stage` 與 `stage=public status=403 — the edge refused the request` | `test_machine.py::test_public_403_is_journaled_with_the_edge_hint` | 已有測試但本次未執行（M） |
| DEP-HEALTH-04 | 回滾後的 docker 舊 runtime 從不回應 | 執行回滾 | 依預算輪詢完整時間後 `failed-down`（exit 5） | `test_machine.py::test_docker_rollback_that_never_answers_polls_the_full_budget_then_fails_down` | 已有測試但本次未執行（M） |
| DEP-HEALTH-05 | 回滾的本機健康在第二次輪詢恢復 | 執行回滾 | `rolled-back`（exit 1） | `test_machine.py::test_docker_rollback_is_rolled_back_when_local_answers_on_a_later_poll` | 已有測試但本次未執行（M） |
| DEP-HEALTH-06 | 切換失敗（健康失敗） | 進入回滾前 | journal 先寫階段、狀態碼與 log 尾端，才 `compose down` | `test_machine.py::test_failed_switch_journals_stage_status_and_log_tail_before_the_rollback` | 已有測試但本次未執行（M） |
| DEP-HEALTH-07 | 公開 URL 無回應 | 寫 journal | 狀態碼記為 `0 (no response)` | `test_machine.py::test_no_response_is_journaled_as_status_zero` | 已有測試但本次未執行（M） |

### 3.3 切換、回滾與 schema-ahead（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-SW-01 | 目前是 systemd、chain in-sync、cutover=true | 執行切換 | 先 `systemctl stop`，再 `compose up`，最後 promote 為 docker | `test_machine.py::test_cutover_stops_systemd_before_compose_up_and_promotes_docker` | 已有測試但本次未執行（M） |
| DEP-SW-02 | in-sync、全部步驟成功 | 執行 `run_state_machine` | 步驟順序正確，state 乾淨（dirty 與 paused 為空） | `test_machine.py::test_in_sync_success_runs_steps_in_order_and_leaves_clean_state` | 已有測試但本次未執行（M） |
| DEP-SW-03 | in-sync 成功 | 同上 | 未呼叫 AWS 與 efbundle | `test_machine.py::test_in_sync_success_never_calls_aws_or_efbundle` | 已有測試但本次未執行（M） |
| DEP-SW-04 | 切換期間 | compose 讀取 env 檔時 | env 檔存在；結束後刪除 | `test_machine.py::test_env_file_exists_while_compose_reads_it_and_is_removed_at_the_end` | 已有測試但本次未執行（M） |
| DEP-SW-05 | schema-ahead、crawler digest 與 state 相同 | 執行成功路徑 | web 切換，crawler 不 pull、不安裝、digest 不變（S7） | `test_machine.py::test_schema_ahead_success_skips_the_crawler_and_keeps_its_digest` | 已有測試但本次未執行（M） |
| DEP-SW-06 | schema-ahead、web 健康失敗 | 執行 | 進入回滾（與 in-sync 相同） | `test_machine.py::test_schema_ahead_web_failure_also_rolls_back` | 已有測試但本次未執行（M） |
| DEP-ROLL-01 | 舊 runtime 的 compose 雜湊與 state 不符 | 執行回滾 | `failed-down`（exit 5），不啟動舊版 | `test_machine.py::test_rollback_refused_when_the_previous_compose_file_does_not_match_state` | 已有測試但本次未執行（M） |
| DEP-ROLL-02 | 回滾後健康失敗 | 執行 | `failed-down`（exit 5） | `test_machine.py::test_rollback_health_failure_is_failed_down` | 已有測試但本次未執行（M） |
| DEP-ROLL-03 | 設定 `DB_CA_BUNDLE`，舊 release 無 `compose.ca-bundle.yaml` | 執行回滾 | `failed-down` 並說明原因，不自動回滾 | `test_machine.py::test_configured_bundle_refuses_rollback_to_a_release_without_the_override` | 已有測試但本次未執行（M） |
| DEP-ROLL-04 | 設定 `DB_CA_BUNDLE`，舊 release 有 override | 執行回滾 | 回滾成功 | `test_machine.py::test_configured_bundle_rolls_back_to_a_release_that_ships_the_override` | 已有測試但本次未執行（M） |
| DEP-ROLL-05 | cutover 的 compose up 失敗 | 執行 | systemd unit 被重新啟動，結果 `rolled-back` 或 `failed-down` 依健康結果 | `test_machine.py::test_cutover_compose_failure_brings_the_systemd_unit_back` | 已有測試但本次未執行（M） |
| DEP-ROLL-06 | forward 後 web 失敗 | 執行 | 不自動回滾，`failed-down`（exit 5），crawler 保持 paused（I5） | `test_machine.py::test_forward_web_failure_never_rolls_back` | 已有測試但本次未執行（M） |

### 3.4 forward migration（類別 M；整合見 3.10）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-FWD-01 | forward、snapshot 成功、efbundle exit 0、DB ids 相同 | 執行 | 順序：取 exclusive lock、pause、snapshot、dirty、efbundle、mark_migrated、釋放 lock | `test_machine.py::test_forward_success_orders_pause_snapshot_dirty_efbundle_and_releases_the_lock` | 已有測試但本次未執行（M） |
| DEP-FWD-02 | snapshot 失敗 | 執行 | 未 migrate，crawler 恢復，exit 3 | `test_machine.py::test_forward_snapshot_failure_resumes_crawler_and_migrates_nothing` | 已有測試但本次未執行（M） |
| DEP-FWD-03 | efbundle exit 非 0 | 執行 | dirty 與 paused 保留，exit 4，runtime 未切換 | `test_machine.py::test_forward_efbundle_nonzero_keeps_dirty_and_paused_and_touches_no_runtime` | 已有測試但本次未執行（M） |
| DEP-FWD-04 | efbundle exit 0，但 DB ids 與 manifest 不同 | 執行 | exit 4（failed-migration） | `test_machine.py::test_forward_exit_zero_with_wrong_database_ids_is_failed_migration` | 已有測試但本次未執行（M） |
| DEP-FWD-05 | db-maintenance lock 被占用 | 執行 | exit 3，state 未變更 | `test_machine.py::test_forward_lock_busy_is_drift_before_any_state_change` | 已有測試但本次未執行（M） |
| DEP-FWD-06 | efbundle 中途例外 | 執行 | 無 completed，之後 plan 判定 indeterminate（exit 8） | `test_machine.py::test_crash_during_efbundle_writes_no_completed_record_and_blocks_later_runs` | 已有測試但本次未執行（M） |

### 3.5 crawler 更新與 pause（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-CRW-01 | in-sync，web 成功，crawler 的 cron 安裝失敗 | 執行 | web promote；crawler paused；exit 7 | `test_machine.py::test_in_sync_crawler_failure_promotes_web_and_pauses_the_crawler` | 已有測試但本次未執行（M） |
| DEP-CRW-02 | forward，crawler 更新失敗 | 執行 | exit 7；crawler 保持 paused | `test_machine.py::test_forward_crawler_failure_is_partial_and_keeps_the_crawler_paused` | 已有測試但本次未執行（M） |
| DEP-CRW-03 | crawler smoke 失敗 | 執行 | 未安裝任何 crawler 檔案 | `test_machine.py::test_smoke_failure_stops_before_any_install` | 已有測試但本次未執行（M） |
| DEP-CRW-04 | 更新成功 | 執行 | state 的 `crawler.runner_sha256`、`cron_sha256` 為安裝後檔案的雜湊 | `test_machine.py::test_success_records_the_hashes_of_the_installed_files_and_the_source_release` | 已有測試但本次未執行（M） |
| DEP-CRW-05 | release 未附 `crawler.cron` | 執行 | 該檔案標為 skipped，state 保留原雜湊 | `test_machine.py::test_a_file_the_release_does_not_ship_keeps_its_recorded_hash` | 已有測試但本次未執行（M） |
| DEP-CRW-06 | `crawler.conf` 只有 `CRAWLER_IMAGE=` 那一行改變 | 改寫 | 其他行與權限不變 | `test_machine.py::test_crawler_conf_rewrite_keeps_other_lines_and_mode` | 已有測試但本次未執行（M） |

### 3.6 爬蟲 host 端閘門（`run-crawler.sh`，類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-CRW-GATE-01 | state 的 `crawler.paused` 不為 null | 執行 `daily` | 不啟動容器；exit 6；輸出 `skipped=paused` | `crawler/tests/test_deploy.py::test_paused_state_skips_before_docker` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-02 | `schema.dirty` 為 true | 執行 | exit 6，`skipped=dirty` | `crawler/tests/test_deploy.py::test_dirty_schema_skips_before_docker` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-03 | state 不存在 | 執行 | 照舊執行（pre-CD 行為） | `crawler/tests/test_deploy.py::test_absent_state_keeps_pre_cd_behaviour` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-04 | state 存在但損毀 | 執行 | fail closed，exit 2 | `crawler/tests/test_deploy.py::test_unreadable_state_fails_closed` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-05 | 維護鎖被 exclusive 持有超過等待上限 | 執行 | exit 3，`maintenance=busy` | `crawler/tests/test_deploy.py::test_maintenance_wait_timeout_exits_3` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-06 | 任何 state 狀態 | 執行 | 鎖在讀 state 之前取得（N3 的 TOCTOU 規則） | `crawler/tests/test_deploy.py::test_lock_is_taken_before_state_is_read` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-07 | `CRAWLER_ENABLED=false` | 執行 `daily` | 輸出 `skipped=disabled`，exit 0，不取鎖、不改 pages 排程 | `crawler/tests/test_deploy.py::test_crawler_disabled_exits_before_any_external_work` 與 `…::test_crawler_disabled_daily_does_not_touch_pages_schedule` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-08 | `CRAWLER_ENABLED=maybe` | 執行 | exit 2 | `crawler/tests/test_deploy.py::test_crawler_enabled_rejects_invalid_values` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-09 | `DB_CA_BUNDLE` 為符號連結 | 執行 | exit 2，不跟隨連結 | `crawler/tests/test_deploy.py::test_ca_bundle_that_is_a_symlink_exits_2_without_following_it` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-10 | `DB_CA_BUNDLE` 合法且 others 可讀 | 執行 | 以唯讀 bind mount 掛到同一路徑 | `crawler/tests/test_deploy.py::test_configured_ca_bundle_is_mounted_read_only_at_the_same_path` | 已有測試但本次未執行（M） |
| DEP-CRW-GATE-11 | host 寫入的 paused 或 dirty state | 由 `run-crawler.sh` 讀取 | 與 host 寫入的格式相容，exit 6 | `deploy/tests/host/test_run_crawler_contract.py::test_host_written_paused_state_is_skipped_with_exit_6` 與 `…::test_wrapper_reads_the_fields_the_host_writes` | 已有測試但本次未執行（M） |

### 3.7 plan、status、deploy 閘門（類別 M；入口見 3.9）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-GATE-01 | state 的 crawler paused | 執行 deploy 的 step 0 | exit 3，未變更 | `test_machine.py::test_paused_crawler_from_an_earlier_run_refuses_the_deploy` | 已有測試但本次未執行（M） |
| DEP-GATE-02 | plan，crawler paused | 執行 `plan` | exit 3，blocked 指出 `resume-crawler` | `test_commands.py::test_plan_paused_crawler_exits_3_and_names_the_blocker` | 已有測試但本次未執行（M） |
| DEP-GATE-03 | plan，schema dirty | 執行 | exit 6 | `test_commands.py::test_plan_dirty_exits_6` | 已有測試但本次未執行（M） |
| DEP-GATE-04 | plan，chain divergent | 執行 | exit 2 | `test_commands.py::test_plan_divergent_exits_2` | 已有測試但本次未執行（M） |
| DEP-GATE-05 | plan，release_api 超出 HOST_API 範圍 | 執行 | exit 2 | `test_commands.py::test_plan_release_api_outside_host_range_exits_2` | 已有測試但本次未執行（M） |
| DEP-GATE-06 | deploy 的 `--expect-revision` 與 state 不符 | 執行 | exit 3；run 的 completed 寫入 | `test_commands.py::test_deploy_cas_revision_mismatch_exits_3_and_records_the_run` | 已有測試但本次未執行（M） |
| DEP-GATE-07 | systemd runtime，未帶 `--cutover` | 執行 deploy | exit 3（S5） | `test_commands.py::test_systemd_runtime_without_cutover_is_drift_s5` | 已有測試但本次未執行（M） |
| DEP-GATE-08 | 帶 `--cutover`，chain 為 forward | 執行 deploy | exit 2 | `test_commands.py::test_cutover_requires_in_sync_chain` | 已有測試但本次未執行（M） |
| DEP-GATE-09 | schema-ahead，crawler digest 與 state 不同 | 執行 SSH 端 deploy | 在啟動 unit 前拒絕，exit 2 | `test_commands.py::test_schema_ahead_with_another_crawler_is_refused_before_any_launch` | 已有測試但本次未執行（M） |
| DEP-GATE-10 | deploy lock 被占用 | 執行 | exit 3 | `test_commands.py::test_deploy_lock_busy_exits_3` | 已有測試但本次未執行（M） |
| DEP-GATE-11 | 無 state 檔 | 執行 plan | exit 3，未寫任何檔案 | `test_commands.py::test_plan_without_state_needs_bootstrap_and_touches_nothing` | 已有測試但本次未執行（M） |
| DEP-GATE-12 | state 損毀 | 執行 plan | exit 3 | `test_commands.py::test_plan_with_corrupt_state_exits_3` | 已有測試但本次未執行（M） |
| DEP-GATE-13 | 有未解決的 indeterminate run | 執行 plan | exit 8 | `test_commands.py::test_plan_blocked_by_unresolved_indeterminate_run_exits_8` | 已有測試但本次未執行（M） |
| DEP-GATE-14 | history 最後一行不完整 | 執行 plan | exit 8 | `test_commands.py::test_plan_blocked_by_corrupt_history_tail_exits_8` | 已有測試但本次未執行（M） |
| DEP-GATE-15 | 同一 run id 已有任何 history 紀錄 | 執行 deploy | exit 3，不寫入、不啟動 | `test_commands.py::test_deploy_refuses_a_run_id_with_any_history_and_writes_nothing` | 已有測試但本次未執行（M） |
| DEP-GATE-16 | plan key 送出 `deploy` | 經 `deploy-entry --plan-only` | exit 2，不執行 | `test_commands.py::test_plan_only_mode_refuses_deploy_with_exit_2` 與 `test_entry.py::test_deploy_is_refused_by_plan_key` | 已有測試但本次未執行（M） |
| DEP-GATE-17 | SSH 指令含注入字元 | 經 entry 執行 | exit 2，不執行任何命令 | `test_commands.py::test_injection_attempt_exits_2_and_runs_no_command` 與 `test_entry.py::test_injection_through_the_entry_exits_2` | 已有測試但本次未執行（M） |
| DEP-GATE-18 | 空的 `SSH_ORIGINAL_COMMAND`，經 sudo | 執行 | 錯誤訊息指出 sudoers 的 `env_keep` 修正 | `test_commands.py::test_empty_command_under_sudo_names_the_sudoers_fix` 與 `test_entry.py::test_entry_under_sudo_without_command_names_the_sudoers_fix` | 已有測試但本次未執行（M） |
| DEP-GATE-19 | forward，applied 是 target 的前綴 | 執行 plan | pending 列出 target 中多出的 id | `test_commands.py::test_plan_forward_lists_pending_ids` | 已有測試但本次未執行（M） |
| DEP-GATE-20 | schema-ahead | 執行 plan | exit 0，可部署 | `test_commands.py::test_plan_schema_ahead_is_deployable` | 已有測試但本次未執行（M） |
| DEP-GATE-21 | web container 已停止 | 執行 plan | exit 3，drift 指出 runtime | `test_commands.py::test_plan_stopped_web_container_is_drift_exit_3` | 已有測試但本次未執行（M） |
| DEP-GATE-22 | compose 會插值 env_file 的值 | 執行 probe | 拒絕，不改變任何東西 | `test_machine.py::test_probe_that_is_interpolated_refuses_before_anything_changes` 與 `test_compose_probe.py::test_interpolated_value_is_refused` | 已有測試但本次未執行（M） |
| DEP-GATE-23 | SSM 值含換行 | 執行 `_render_env` | 拒絕，不留下 env 檔 | `test_machine.py::test_secret_value_with_a_newline_is_refused_and_no_env_file_is_left` | 已有測試但本次未執行（M） |
| DEP-GATE-24 | SSM 讀取失敗 | 執行 | exit 3 | `test_machine.py::test_ssm_read_failure_is_drift` | 已有測試但本次未執行（M） |
| DEP-GATE-25 | release 內含 symlink | 取出並驗證 | 拒絕，且不讀取 symlink 目標 | `test_machine.py::test_release_with_a_symlink_is_refused_and_its_target_is_never_read` | 已有測試但本次未執行（M） |
| DEP-GATE-26 | release 超過 2 MiB | 取出並驗證 | 拒絕 | `test_machine.py::test_release_larger_than_two_mebibytes_is_refused` | 已有測試但本次未執行（M） |
| DEP-GATE-27 | 同 digest 的 release 目錄，compose 雜湊不同 | 執行 | exit 3（drift） | `test_machine.py::test_existing_release_directory_with_a_different_compose_file_is_drift` | 已有測試但本次未執行（M） |

### 3.8 status 與 history（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-ST-01 | history 有 completed | `status run` | `completed:<result>` | `test_commands.py::test_status_reports_completed_result` | 已有測試但本次未執行（M） |
| DEP-ST-02 | 無 completed，unit active | `status` | `running` | `test_commands.py::test_status_reports_running_for_active_unit` | 已有測試但本次未執行（M） |
| DEP-ST-03 | 有 started，無 completed，unit 不在執行中 | `status` | `indeterminate` | `test_commands.py::test_status_reports_indeterminate_for_dead_unit_without_completed` | 已有測試但本次未執行（M） |
| DEP-ST-04 | 無任何紀錄 | `status` | `not-started` | `test_commands.py::test_status_reports_not_started_for_unknown_run` | 已有測試但本次未執行（M） |
| DEP-ST-05 | history 為 completed，unit 仍 active | `status` | 以 history 為準（`completed:…`） | `test_commands.py::test_status_prefers_history_over_a_conflicting_unit` | 已有測試但本次未執行（M） |
| DEP-ST-06 | 任何 run | `status`（經 entry） | JSON 為 exit 0；部署結果只看 `status` 欄位 | `test_entry.py::test_status_of_unknown_run_is_not_started`（只斷言 `not-started`） | 待補強（缺 exit 0 的明確斷言） |
| DEP-HIST-01 | 新 history 檔 | append 一筆 | 單行 JSON，權限 0600 | `test_history.py::test_append_writes_one_json_line_with_mode_0600` | 已有測試但本次未執行（M） |
| DEP-HIST-02 | 紀錄長度達 PIPE_BUF | append | 拒絕 | `test_history.py::test_append_refuses_a_record_at_or_above_pipe_buf` | 已有測試但本次未執行（M） |
| DEP-HIST-03 | exit 3 的各發生點（drift 路徑與 gate 失敗路徑） | 寫 completed | `result` 與 README §1.5「exit 3 的 history 對照」一致：gate 失敗為 `rejected`，lock 逾時、state 不存在、step 0 與 step 1 失敗為 `drift`。文件已對齊（PR #107），程式未統一，見 DEP-B17 | 待建（現有測試未斷言 exit 3 的 result 字串） | 待補強（文件已對齊；程式統一見 DEP-B17） |
| DEP-HIST-04 | 最後一行無換行 | `read` | 標為 tail corrupt，不列入 records | `test_history.py::test_last_line_without_newline_is_tail_corrupt_and_excluded` | 已有測試但本次未執行（M） |
| DEP-HIST-05 | completed 與 active unit 同時存在 | `status` | completed 勝出 | `test_history.py::test_completed_wins_even_when_unit_reports_active` | 已有測試但本次未執行（M） |
| DEP-HIST-06 | started 與不在執行中的 unit，無 completed | `status` | `indeterminate` | `test_history.py::test_started_with_dead_unit_is_indeterminate` | 已有測試但本次未執行（M） |
| DEP-HIST-07 | 有 open operator operation | 列出 | 阻擋 unresolved，並列於 runs 之後 | `test_history.py::test_open_operation_blocks_unresolved_and_is_listed_after_runs` | 已有測試但本次未執行（M） |
| DEP-HIST-08 | history 為符號連結 | `read` | 拒絕 | `test_history.py::test_read_rejects_symlink` | 已有測試但本次未執行（M） |

### 3.9 SSH 入口與 unit 本體（類別 M，含 systemd-run 替身）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-LAUNCH-01 | 有效的 deploy 指令 | 建立 `systemd-run` argv | argv 精確、不含 secret | `test_launch.py::test_systemd_run_argv_is_exact_and_carries_no_secrets` | 已有測試但本次未執行（M） |
| DEP-LAUNCH-02 | `--detach`，unit 寫入 started | 等待接手 | 回報 `launched`，exit 0 | `test_launch.py::test_detach_reports_launched_as_soon_as_the_unit_has_written_started` | 已有測試但本次未執行（M） |
| DEP-LAUNCH-03 | `--detach`，unit 未接手 60 秒 | 等待 | 回報 `launched`，stderr 含 `poll status` | `test_launch.py::test_detach_is_bounded_to_sixty_seconds_when_the_unit_never_acknowledges` | 已有測試但本次未執行（M） |
| DEP-LAUNCH-04 | `--detach`，unit 不存在且無 started，超過 30 秒寬限 | 等待 | `not-started`，exit 3 | `test_launch.py::test_detach_unit_gone_without_started_is_not_started_after_the_grace_period` | 已有測試但本次未執行（M） |
| DEP-LAUNCH-05 | SSH 端被殺掉 | 之後查 status | status 可計算，unit 仍執行 | `test_launch.py::test_killed_ssh_side_leaves_status_computable_and_the_unit_running` | 已有測試但本次未執行（M） |
| DEP-LAUNCH-06 | unit 消失且無 completed | 查 status | `indeterminate`，不是 success | `test_launch.py::test_unit_gone_without_completed_is_indeterminate_not_success` | 已有測試但本次未執行（M） |
| DEP-LAUNCH-07 | unit body 經由 SSH_ORIGINAL_COMMAND 呼叫 | 執行 | 拒絕 | `test_launch.py::test_unit_body_refuses_a_command_that_came_from_ssh` | 已有測試但本次未執行（M） |

### 3.10 整合測試（類別 I，需 `BOOKFINDER_IT=1`，本次未執行）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-INT-A | 真實 docker、pgvector、本 checkout 的 image、加兩個 migration | forward 部署 | snapshot、crawler pause、成功後 crawler 恢復 | `deploy/tests/integration/test_local_integration.py::test_a_forward_upgrade_with_snapshot_and_crawler_pause` | 已有測試但本次未執行（I） |
| DEP-INT-B | schema-ahead | 部署較舊 release | rebuild 與 target 保留，crawler digest 不變 | `…::test_b_schema_ahead_deploy_keeps_rebuild_target_and_the_crawler` | 已有測試但本次未執行（I） |
| DEP-INT-C | 壞掉的 web image | 切換後 | 回滾，exit 1，runtime 恢復 | `…::test_c_broken_web_image_rolls_back` | 已有測試但本次未執行（I） |
| DEP-INT-D | migration 失敗 | 之後 | dirty 與 paused 保留，直到 reconcile 與 resume | `…::test_d_failed_migration_keeps_dirty_and_paused_until_reconciled` | 已有測試但本次未執行（I） |
| DEP-INT-E | 中斷的 run | plan | indeterminate（exit 8），直到 resolve-run | `…::test_e_killed_run_is_indeterminate_until_the_operator_resolves_it` | 已有測試但本次未執行（I） |
| DEP-INT-PROBE | `format: raw` 的 env file | `docker compose config` | 原樣輸出（含 `$`、引號、`#`），不啟動服務 | `…::test_local_compose_renders_raw_env_file_literally` | 已有測試但本次未執行（I） |
| DEP-IMG-01 | 本機 registry，index 與 manifest 兩種來源 | `docker buildx imagetools create --prefer-index=false` | release tag 解析到相同 digest；不加旗標的對照組改變 digest | `deploy/tests/integration/test_imagetools_roundtrip.py::test_release_tag_keeps_the_attested_digest` 與 `deploy/integration/imagetools-roundtrip.sh`（CI 直接執行） | 已有測試但本次未執行（I） |
| DEP-SMOKE-01 | web image（placeholder secrets，內部網路） | `web-smoke.sh` 與 `--control-no-keys` | 正常 image 通過；對照組的 antiforgery 失敗 | `deploy/smoke/web-smoke.sh`（無 pytest；CI `docker` job） | 已有測試但本次未執行（I） |
| DEP-COMPAT-E2E-01 | 已套用 migration 與目標 image | `compat.sh` | report 的 `forward_ok` 為 true；data preserved；schema matches fresh install | `deploy/migration-test/compat.sh`（CD `compat` job；CI 僅 PR 條件） | 已有測試但本次未執行（I） |

### 3.11 人工指令與 operator 協定（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-OP-01 | 非 root，非測試環境 | 執行任一人工指令 | 拒絕 | `test_operator_cli.py::test_operator_commands_refuse_non_root_outside_tests` | 已有測試但本次未執行（M） |
| DEP-OP-02 | `--reason` 為空或含控制字元 | 執行 | 拒絕 | `test_operator_cli.py::test_reason_is_required_and_must_be_printable_text` | 已有測試但本次未執行（M） |
| DEP-OP-03 | 無 state，systemd unit active，DB ids 與 manifest 相同 | `bootstrap-state` | 寫入 revision 1，runtime systemd | `test_operator_cli.py::test_bootstrap_writes_revision_one_systemd_state` | 已有測試但本次未執行（M） |
| DEP-OP-04 | 缺 `run-crawler.sh` 或 `crawler.cron` | `bootstrap-state` | 拒絕，不寫入 | `test_operator_cli.py::test_bootstrap_refuses_without_both_crawler_files` | 已有測試但本次未執行（M） |
| DEP-OP-05 | `crawler.conf` 的 digest 與 `--crawler-digest` 不符 | `bootstrap-state` | 拒絕 | `test_operator_cli.py::test_bootstrap_refuses_when_crawler_conf_pins_another_digest` | 已有測試但本次未執行（M） |
| DEP-OP-06 | DB ids 與 manifest 不同 | `bootstrap-state` | 拒絕 | `test_operator_cli.py::test_bootstrap_refuses_when_database_ids_differ_from_manifest` | 已有測試但本次未執行（M） |
| DEP-OP-07 | schema dirty，DB 與 state 一致 | `reconcile-schema --mark-clean` | 只改寫 state 與 history，不修改 DB | `test_operator_cli.py::test_reconcile_never_touches_the_database` | 已有測試但本次未執行（M） |
| DEP-OP-08 | schema 不是 dirty | `reconcile-schema` | 拒絕 | `test_operator_cli.py::test_reconcile_refuses_a_clean_schema` | 已有測試但本次未執行（M） |
| DEP-OP-09 | crawler paused，schema 不是 dirty，檔案與 state 相同 | `resume-crawler` | 清除 pause，保留 provenance | `test_operator_cli.py::test_resume_clears_the_pause_and_keeps_the_recorded_provenance` | 已有測試但本次未執行（M） |
| DEP-OP-10 | schema dirty | `resume-crawler` | 拒絕 | `test_operator_cli.py::test_resume_refuses_a_dirty_schema` | 已有測試但本次未執行（M） |
| DEP-OP-11 | 確認值與顯示值不符 | 執行 | 拒絕，不變更 | `test_operator_cli.py::test_confirmation_must_match_the_value_shown` | 已有測試但本次未執行（M） |
| DEP-OP-12 | 確認期間 state 被改變 | 執行 | CAS 衝突，不變更 | `test_operator_cli.py::test_state_changed_during_confirmation_is_a_cas_conflict` | 已有測試但本次未執行（M） |
| DEP-OP-13 | history 最後一行不完整，有 started | `resolve-run` | 修復尾端（保存 sidecar）並寫入結果 | `test_operator_cli.py::test_resolve_repairs_an_incomplete_history_tail` | 已有測試但本次未執行（M） |
| DEP-OP-14 | history 最後一行不完整，執行 `reconcile-schema` 或 `resume-crawler` | 執行 | 退出碼與 runbook §1.5、§5.1 一致（現行為 exit 3，見 DEP-B08） | 待建（現有測試只涵蓋 plan 與 deploy） | 待補強（統一與否見 DEP-B08） |
| DEP-OP-15 | operator operation 為 started 而無 completed | 執行任一人工指令（除 resolve-run） | 全部拒絕，exit 8 | `test_operator_cli.py::test_open_operation_refuses_every_operator_command_but_resolve` | 已有測試但本次未執行（M） |
| DEP-OP-16 | operation 寫入後失敗且無法證明未變更 | 執行 | 保持 open，不寫 failed | `test_operator_cli.py::test_failed_completion_after_a_real_change_stays_indeterminate` | 已有測試但本次未執行（M） |
| DEP-OP-PROTO-01 | 需要 drift 修復指令（DEP-B07） | — | — | 待建（尚無此指令） | 明確暫緩（待決策，見 DEP-B07） |

### 3.12 install-host（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-INST-01 | 版本目錄已寫入，symlink 尚未替換 | 在每一步模擬中斷 | `/opt/book-finder/host` 指向完整的一套程式（S9） | `test_install_host.py::test_crash_at_every_step_of_a_linked_install_leaves_a_complete_tree` | 已有測試但本次未執行（M） |
| DEP-INST-02 | 舊版是普通目錄 | 在每一步模擬中斷 | 仍為完整的一套程式 | `test_install_host.py::test_crash_at_every_step_of_the_legacy_migration_leaves_a_complete_tree` | 已有測試但本次未執行（M） |
| DEP-INST-03 | 已有 current 與 previous | 完成安裝 | 保留兩者，其他版本清除 | `test_install_host.py::test_current_and_previous_are_kept_and_older_versions_are_pruned` | 已有測試但本次未執行（M） |

### 3.13 設定與 release 檔案（類別 M／S）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-CFG-01 | `PUBLIC_URL` 為 `http://` 非 loopback | 載入設定 | 拒絕；loopback 允許 | `test_config.py::test_public_url_allows_plain_http_only_on_loopback` | 已有測試但本次未執行（M） |
| DEP-CFG-02 | `DB_CA_BUNDLE` 為一般檔案，others 可讀，≤ 1 MiB | 檢查 | 接受；其他情況拒絕 | `test_config.py::test_check_ca_bundle_accepts_a_public_regular_file_up_to_one_mebibyte` 與 `…::test_check_ca_bundle_refuses_a_file_that_others_cannot_read` | 已有測試但本次未執行（M） |
| DEP-CFG-03 | `/etc/book-finder` 為 0750（CA 檔案為 0644） | 載入設定 | 拒絕並說明目錄權限 | 待建 | 未實作（DEP-B15） |
| DEP-CFG-04 | host.conf 含重複鍵或未知鍵 | 載入 | 拒絕 | `test_config.py::test_db_ca_bundle_duplicate_key_is_refused`（僅覆蓋 `DB_CA_BUNDLE` 的重複鍵） | 待補強（其他鍵未覆蓋） |
| DEP-REL-01 | `compose.ca-bundle.yaml` | 檢查 | web 的 override 為唯讀 bind，且不含路徑字串 | `test_release_files.py::test_ca_override_is_a_read_only_bind_on_web_and_holds_no_path` | 已有測試但本次未執行（S） |
| DEP-REL-02 | `compose.prod.yaml` | 檢查 | 只發布 loopback，不含 secret | `test_release_files.py::test_compose_publishes_only_loopback_and_holds_no_secrets` | 已有測試但本次未執行（S） |
| DEP-REL-03 | `compose.prod.yaml` | 檢查 | image 與 env_file 由 host 提供 | `test_release_files.py::test_compose_takes_image_and_env_file_from_the_host` | 已有測試但本次未執行（S） |
| DEP-REL-04 | `compose.prod.yaml` 與 web 網路 | 檢查 | `KnownNetworks` 等於 web 網路子網 | `test_release_files.py::test_known_networks_equals_web_network_subnet` | 已有測試但本次未執行（S） |
| DEP-REL-05 | `Dockerfile` | 檢查 | 只複製兩個 crawler host 檔案 | `test_release_files.py::test_dockerfile_copies_only_the_two_crawler_host_files` | 已有測試但本次未執行（S） |
| DEP-REL-06 | 有 docker compose | `docker compose config` 解析 override | web 唯讀掛載 bundle | `test_release_files.py::test_real_compose_mounts_the_bundle_read_only_on_web` | 已有測試但本次未執行（I，需 Compose） |
| DEP-REL-07 | GHCR 上的 `build-*` staging tag | 清理 | 只刪除所有 tag 都是 `build-*` 的版本 | 待建 | 未實作（DEP-B05） |

### 3.14 compat、manifest、schema、lock（類別 M／S）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-COMPAT-01 | applied 與 target 的關係為 forward 或 in-sync | 規劃 compat | 執行全部升級檢查 | `test_compat_plan.py::test_forward_and_in_sync_run_every_upgrade_check` | 已有測試但本次未執行（M） |
| DEP-COMPAT-02 | schema-ahead | 規劃 | 不執行 target bundle | `test_compat_plan.py::test_schema_ahead_never_runs_the_target_bundle` | 已有測試但本次未執行（M） |
| DEP-COMPAT-03 | 未規劃的分類 | 規劃 | 拒絕 | `test_compat_plan.py::test_unplanned_classification_is_rejected` | 已有測試但本次未執行（M） |
| DEP-COMPAT-04 | allow.tsv 含未知指令、欄位數錯誤或非小寫 identifier | 解析 | 失敗，並附行號，不輸出任何指令 | `test_contract_allowance.py::test_unknown_or_malformed_directives_fail_with_the_line_number` | 已有測試（M3，本次執行 pytest） |
| DEP-COMPAT-05 | allowance 的 migration 不在 pending | 選擇 | 忽略（INFO），不解析 | `test_contract_allowance.py::test_an_allowance_for_a_migration_that_is_not_pending_is_ignored` | 已有測試（M3，本次執行 pytest） |
| DEP-COMPAT-06 | allowed drop-column 升級後仍存在，或升級前就不存在 | 判定 | 失敗 | `test_contract_allowance.py::test_drop_problems_report_an_allowed_column_that_still_exists` 與 `…::test_drop_problems_report_an_allowance_for_a_column_that_never_existed` | 已有測試（M3，本次執行 pytest） |
| DEP-COMPAT-07 | verify.sql 回傳 1 列以上 | 判定 | fail | `test_contract_allowance.py::test_verify_passes_only_with_zero_rows` | 已有測試（M3，本次執行 pytest） |
| DEP-COMPAT-08 | 升級後的 schema 比對 | 順序 | compat_before 在 schema 比對前移除（靜態檢查 main 的順序，失敗路徑也會繼續到移除） | `test_contract_allowance.py::test_compat_before_is_dropped_before_the_schema_comparison_even_when_the_data_check_fails` | 已有測試（M3，本次執行 pytest） |
| DEP-COMPAT-09 | 011 allowance 與 verify | 本地 compat（需 Docker） | `compat checks passed`；allowance 與 verify 都在報告中 | 本地 `deploy/migration-test/compat.sh`（M3 的 update-history 記錄結果） | 本次已執行（M3，見 update-history） |
| DEP-MAN-01 | 有效與無效的 manifest | 以 Python 與 bash 同時驗證 | 接受與拒絕結果一致 | `host/test_manifest_parity.py::test_valid_and_invalid_manifests_agree_on_acceptance` | 已有測試但本次未執行（M） |
| DEP-MAN-02 | 相同 manifest | 計算 digest | Python 與 bash 的 digest 相同 | `host/test_manifest_parity.py::test_digest_matches_bash_for_every_valid_manifest` | 已有測試但本次未執行（M） |
| DEP-MAN-03 | applied 落後 target 一個 id | classify | forward；同 id 不同 hash 為 divergent | `host/test_manifest.py`（`classify` 系列）與 `test_manifest_lib.py::test_classify_same_id_different_hash_is_divergent` | 已有測試但本次未執行（M） |
| DEP-SCHEMA-01 | `pg_dump` 失敗 | 正規化 schema | 錯誤，並附 stderr | `test_schema_dump.py::test_failing_pg_dump_is_an_error_with_its_stderr` | 已有測試但本次未執行（M） |
| DEP-SCHEMA-02 | `pg_dump` 輸出為空或只有註解 | 比對 | 錯誤，兩個失敗不相等 | `test_schema_dump.py::test_empty_output_is_an_error` 與 `…::test_two_failed_dumps_do_not_compare_equal` | 已有測試但本次未執行（M） |
| DEP-LOCK-01 | 另一程序持有 shared lock | 取得 exclusive 並逾時 | 逾時，不阻塞 | `host/test_locks.py::test_exclusive_times_out_while_another_process_holds_shared` | 已有測試但本次未執行（M） |
| DEP-LOCK-02 | 逾時設為 NaN、0 或負數 | 設定 | 拒絕 | `test_config.py::test_rejects_lock_timeout_that_is_not_a_finite_positive_number` 與 `test_locks.py::test_rejects_non_finite_or_non_positive_timeout` | 已有測試但本次未執行（M） |
| DEP-LOCK-03 | 鎖檔為符號連結 | 取得 | 拒絕 | `host/test_locks.py::test_lock_file_symlink_is_refused` | 已有測試但本次未執行（M） |

### 3.15 CD 腳本（類別 M，`.github/scripts/tests/test_cd_release.py`）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-CD-01 | 目標 image 的 attestation signer、source ref 或 commit 不符 | `verify-attestation` | 失敗（只有完整政策通過才成功） | `test_cd_release.py::test_verify_attestation_passes_only_with_the_full_policy` | 已有測試但本次未執行（M） |
| DEP-CD-02 | release tag 解析到的 digest 與 attested 不同 | `confirm-release` | 失敗 | `test_cd_release.py::test_confirm_release_digest_requires_the_attested_digest` | 已有測試但本次未執行（M） |
| DEP-CD-03 | staging tag 格式錯誤 | `validate-staging-tag` | 拒絕；只接受 run 與 attempt 數字 | `test_cd_release.py::test_staging_tag_accepts_only_run_and_attempt_numbers` | 已有測試但本次未執行（M） |
| DEP-CD-04 | image 中的 SQL 為 symlink | `extract-release` | 拒絕 | `test_cd_release.py::test_extract_release_rejects_a_symlink_in_the_image` | 已有測試但本次未執行（M） |
| DEP-CD-05 | in-sync、chain 相符 | `plan-outputs` | crawler 為目標 crawler | `test_cd_release.py::test_in_sync_docker_uses_the_target_crawler` | 已有測試但本次未執行（M） |
| DEP-CD-06 | schema-ahead | `plan-outputs` | crawler 維持 state 的 digest | `test_cd_release.py::test_schema_ahead_keeps_the_state_crawler` | 已有測試但本次未執行（M） |
| DEP-CD-07 | plan 為 divergent、dirty 或 drift | `plan-outputs` | 拒絕，summary 寫入原因 | `test_cd_release.py::test_divergent_dirty_and_drift_are_refused` | 已有測試但本次未執行（M） |
| DEP-CD-08 | 目標的 pending 與 release 不符 | `plan-outputs` | 拒絕 | `test_cd_release.py::test_pending_must_match_the_target_release` | 已有測試但本次未執行（M） |
| DEP-CD-09 | pending SQL 檔案被改動 | `pending-sql-summary` | 拒絕 | `test_cd_release.py::test_pending_sql_summary_rejects_a_changed_file_and_a_wrong_pending_list` | 已有測試但本次未執行（M） |
| DEP-CD-10 | deploy 已 completed 成功 | `deploy-follow` | 不再輪詢，成功 | `test_cd_release.py::test_follow_completed_success_without_polling` | 已有測試但本次未執行（M） |
| DEP-CD-11 | SSH 斷線（255） | 輪詢 | 繼續輪詢直到 completed | `test_cd_release.py::test_follow_polls_after_a_dropped_ssh_until_completed` | 已有測試但本次未執行（M） |
| DEP-CD-12 | `not-started` | 輪詢 | 寬限 120 秒後才是最終結果 | `test_cd_release.py::test_not_started_waits_for_the_grace_period_before_it_is_final` | 已有測試但本次未執行（M） |
| DEP-CD-13 | 跟隨逾時 | 結束 | failure，unknown 狀態 | `test_cd_release.py::test_follow_times_out_as_failure_and_unknown_status_fails` | 已有測試但本次未執行（M） |
| DEP-CD-14 | 跟隨預算 | 檢查常數 | 160 分鐘，小於 180 分鐘 job timeout | `test_cd_release.py::test_follow_budget_is_160_minutes_and_fits_the_180_minute_job` | 已有測試但本次未執行（M） |
| DEP-CD-15 | host 回傳非 255 的 status 失敗 | 輪詢 | job 失敗（不重試） | `test_cd_release.py::test_deploy_follow_retries_ssh_255_and_refuses_other_status_failures` | 已有測試但本次未執行（M） |
| DEP-CD-16 | status 的 SSH 呼叫 | 建立 argv | 使用 plan key 的選項 | `test_cd_release.py::test_status_ssh_argv_uses_the_plan_key_options` | 已有測試但本次未執行（M） |
| DEP-CD-17 | compat report 缺失或有效 | `summarize-compat` | 兩種情況都輸出可讀摘要 | `test_cd_release.py::test_summarize_compat_handles_missing_and_valid_reports` | 已有測試但本次未執行（M） |
| DEP-CD-18 | 寫入 GitHub output 的值含換行 | `write_outputs` | 拒絕 | `test_cd_release.py::test_write_outputs_rejects_newlines` | 已有測試但本次未執行（M） |

### 3.16 CI 靜態檢查（類別 S）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-MIG-01 | 已發布的 migration 原始檔被修改 | `check_migrations.py --released-manifest` | 拒絕 | `test_check_migrations.py::test_modified_released_migration_is_rejected` | 已有測試但本次未執行（S） |
| DEP-MIG-02 | migration 含 `suppressTransaction` | 檢查 | 拒絕 | `test_check_migrations.py::test_suppress_transaction_is_rejected` | 已有測試但本次未執行（S） |
| DEP-MIG-03 | migration 含 `CONCURRENTLY`（大小寫不敏感） | 檢查 | 拒絕 | `test_check_migrations.py::test_concurrently_is_rejected_case_insensitively` | 已有測試但本次未執行（S） |
| DEP-VER-01 | Dockerfile 的 SDK 與 `global.json` 不同 | `check_version_sync.py` | 拒絕，並指出兩個檔案 | `test_check_version_sync.py::test_dockerfile_sdk_mismatch_names_both_files` | 已有測試但本次未執行（S） |
| DEP-CI-01 | `.github/workflows/*.yml` | 以 actionlint 檢查 | 無錯誤 | 未實作（CI 沒有 actionlint） | 未實作 |
| DEP-CI-02 | `cd.yml` 內 plan 與 deploy 的 SSH 選項 | 比對 | 相同 | 待建（DEP-B11） | 未實作 |

### 3.17 Web 的 forwarded headers（類別 M，屬 web 測試）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-WEB-FH-01 | 受信任的 nginx 來源 | 送出 `X-Forwarded-For` 與 `X-Forwarded-Proto` | web 採用 | `tests/WebIntegration/ForwardedHeadersTests.cs`（本次未讀取內容） | 已有測試但本次未執行（M） |
| DEP-WEB-FH-02 | 來自不受信任來源的 `CF-Connecting-IP` | 送出請求 | 忽略該標頭（DEP-B13） | 待建 | 待補強（DEP-B13） |

### 3.18 secret 遮蔽（類別 M）

| ID | Given | When | Then | 測試位置 | 狀態 |
|---|---|---|---|---|---|
| DEP-SEC-01 | container log 含三個 secret 的原值 | 寫 journal | 原值以 `***` 取代 | `test_machine.py::test_secret_values_are_masked_in_the_container_log_and_never_printed` | 已有測試但本次未執行（M） |
| DEP-SEC-02 | container log 含 secret 的 URL 編碼形式 | 寫 journal | 不出現原值或編碼形式 | 待建 | 待補強（DEP-B12） |
| DEP-SEC-03 | SSM 連線字串的密碼含 `;` 或未跳脫字元 | 寫 env 前 | 拒絕（不輸出值） | 待建 | 未實作（DEP-B14） |
| DEP-SEC-04 | secret 值含控制字元 | `_render_env` | 拒絕 | `test_machine.py::test_carriage_return_in_a_secret_is_refused` | 已有測試但本次未執行（M） |
| DEP-SEC-05 | secret 值原樣寫入 env 檔 | 讀取 | 不被插值或改寫 | `test_machine.py::test_secret_values_reach_the_env_file_verbatim` | 已有測試但本次未執行（M） |

### 3.19 產線觀察（類別 O，非測試；不得當作通過）

| ID | 觀察內容 | 來源 | 狀態 |
|---|---|---|---|
| DEP-PROD-01 | cutover 的 run 40078171943 完成，state revision 2，runtime docker `v0.0.4` | operator 工作階段（2026-10-24） | 營運觀察，非本次驗證 |
| DEP-PROD-02 | crawler 以 `CRAWLER_ENABLED=false` 停用，因博客來封鎖 EC2 IP | 同上；runbook §7.2 #19 | 營運觀察，非本次驗證 |
| DEP-PROD-03 | 兩次 cutover 在公開階段得到 403（urllib UA），之後 `failed-down` | 同上；runbook §3.4 第 7 步、§7.2 #7 | 營運觀察，非本次驗證（修正後的結果未記錄） |
| DEP-PROD-04 | `/etc/book-finder` 權限被改為 0750，web 出現 500 | 同上；runbook §2.5、§7.2 #20 | 營運觀察，非本次驗證 |
| DEP-PROD-05 | SSM 連線字串跳脫問題 | 同上 | 營運觀察，非本次驗證（DEP-B14） |
| DEP-PROD-06 | GitHub releases v0.0.1 至 v0.0.4 存在；本地 git tag 也存在 | 本次 `git tag` 查核（本地），GitHub 狀態未查 | 本地 git 證據；GitHub 端見 DEP-PROD-08（營運觀察） |
| DEP-PROD-07 | cutover 的 run `40078171943` 以 transient unit `book-finder-deploy-40078171943-1` 完成（以 SSH `--detach` 啟動），寫入 `completed:success` | operator 工作階段（2026-10-24） | 營運觀察，非本次驗證（runbook §7.2 #2、#3） |
| DEP-PROD-08 | Immutable Releases 已啟用（release 為 `immutable=true`）；`Confirm the web/crawler release tag` 對 v0.0.1 至 v0.0.4 通過 | 同上 | 營運觀察，非本次驗證（runbook §7.2 #11、#17） |

### 3.20 Gate 9：上一個 release 在 011 上（類別 I，本機，需 `BOOKFINDER_IT=1`）

Gate 9（`Docs/data/data-model.md` §11.3）與 test-plan §7 #13、#14。Given：目標 bundle 建置的 image、拋棄式 pgvector DB、v0.0.6 的 Web 與 crawler image（digest 固定）。When：`deploy/migration-test/prev-release-on-contract.sh` 執行。Then：下列 15 項都輸出 `PASS`，exit 0。測試位置：`deploy/tests/integration/test_prev_release_on_contract.py::test_previous_release_runs_on_the_011_contract_schema`（要求全部 15 項的名稱都出現在 PASS 行）。

| ID | 檢查（script 輸出的名稱） | 證明 | 狀態 |
|---|---|---|---|
| DEP-G9-01 | `migrate: efbundle applied to 011 on an empty database` | 目標 bundle 從空 DB 升到 011，exit 0，history 的最後一筆是 011 | 本次已執行（M4） |
| DEP-G9-02 | `migrate: migration history ends at 011 and source_type is gone` | `source_type` 在 `book_sources`、`book_subjects` 都不存在 | 本次已執行（M4） |
| DEP-G9-03 | `seed: 011 seed loaded` | 011 seed 載入，`books` 4 筆 | 本次已執行（M4） |
| DEP-G9-04 | `web: GET / -> 200` | v0.0.6 Web 在 011 上健康（`X-Forwarded-Proto: https`） | 本次已執行（M4） |
| DEP-G9-05 | `web: GET /books -> 200` | 書庫頁可讀 | 本次已執行（M4） |
| DEP-G9-06 | `web: keyword search finds the seeded Book` | 關鍵字 Search 找到 seed 的 Book（`/books/…0004`） | 本次已執行（M4） |
| DEP-G9-07 | `web: hyphenated ISBN search finds the seeded Book` | `978-626-3100-002` 正規化後走 ISBN 模式，找到同一本 Book | 本次已執行（M4） |
| DEP-G9-08 | `web: detail shows the ISBN and the books.com.tw source link` | Detail 同時顯示 ISBN 值與 `books.com.tw` 來源連結 | 本次已執行（M4） |
| DEP-G9-09 | `web: no unhandled exception in the container log` | container log 沒有 unhandled exception | 本次已執行（M4） |
| DEP-G9-10 | `crawler: existing Source resolves by URL and touch advances last_seen_at` | v0.0.6 `resolve_source_identity` 以 URL 找到 Existing Source；`touch_source` 使 `last_seen_at` 前進 | 本次已執行（M4） |
| DEP-G9-11 | `crawler: ISBN row matches the draft, the Source is attached and no Book is created` | `find_books_by_isbn`（`identifier_type = ANY(ISBN, ISBN_10, ISBN_13)`）對到既有 `ISBN`；`persist_new_source` 附加到該 Book，不建立新 Book | 本次已執行（M4） |
| DEP-G9-12 | `crawler: new Source with a fresh ISBN creates a Book with source_code BOOKS_COM_TW` | 無匹配時建立 Book；`book_sources.source_code` 為 `BOOKS_COM_TW`、`external_id` 為 NULL；寫入 `ISBN` 列 | 本次已執行（M4） |
| DEP-G9-13 | `crawler: 100-row ranking validates and replaces the bestsellers` | `validate_ranking` 接受 100 筆；`replace_bestsellers` 替換整份清單（rank 1..100，seed 的 Bestseller 消失） | 本次已執行（M4） |
| DEP-G9-14 | `crawler: incomplete ranking is rejected` | 99 筆的榜單被 `RankingValidationError` 拒絕（負面案例） | 本次已執行（M4） |
| DEP-G9-15 | `crawler: Source of another Book is rejected and the bestseller list is unchanged` | 來源屬於其他 Book 時 `SnapshotValidationError`，清單仍為 100 筆且 rank 1 不變（負面案例） | 本次已執行（M4） |

負面驗證：把 crawler image 換成 Web image 時，script 輸出 `FAIL crawler: driver`、`RESULT FAIL`，exit 1，且容器、網路與 volume 都被移除（M4 本機執行）。

## 4. 覆蓋摘要與缺口

- **正常路徑**：in-sync 成功（DEP-SW-02）、forward 成功（DEP-FWD-01）、schema-ahead 成功（DEP-SW-05）、crawler 成功（DEP-CRW-04）。
- **負面與邊界**：DEP-GATE 系列、DEP-HIST-04、DEP-LAUNCH-03 與 DEP-LAUNCH-04。
- **失敗恢復**：回滾（DEP-ROLL 系列）、forward 失敗（DEP-FWD-02 到 06）、indeterminate（DEP-HIST-06、DEP-LAUNCH-06）。
- **隔離**：unit body 拒絕 SSH 來源（DEP-LAUNCH-07）、plan key 拒絕 deploy（DEP-GATE-16）、測試 hook 拒絕 root。
- **待補強與未實作**（與 backlog 對應）：DEP-ST-06、DEP-HIST-03、DEP-OP-14、DEP-CFG-03、DEP-CFG-04、DEP-REL-07、DEP-WEB-FH-02、DEP-SEC-02、DEP-SEC-03、DEP-CI-01、DEP-CI-02、DEP-OP-PROTO-01（明確暫緩）。
- **沒有任何測試覆蓋的 production 路徑**：systemd system manager 的 transient unit（runbook §7.2 #2、#3；營運觀察已有證據，見 DEP-PROD-07，但仍不是自動化測試）、真實 SSM 與 RDS、真實 nginx 與 Cloudflare、真實 GHCR 的 `imagetools`。這些只能以 I 或 O 類別證據處理，不能列為通過。
