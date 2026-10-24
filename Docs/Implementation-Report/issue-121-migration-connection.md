# 實作報告：#121 efbundle 的 migration 連線與失敗輸出

## 變更檔案

| 檔案 | 變更 |
|---|---|
| `deploy/host/bookfinder_host/config.py` | 新增選填鍵 `SSM_MIGRATION_CONNECTION`（`_OPTIONAL_UNSET`）與 `Settings.ssm_migration_connection`（預設 `None`） |
| `deploy/host/bookfinder_host/machine.py` | 步驟 3 讀取並驗證 migration 連線；寫入獨立的 `migrate-<run_id>.env`（600）；`_discard_env` 刪除兩個檔案；failed-migration 時寫入 efbundle 輸出尾端（遮蔽後 80 行） |
| `deploy/host/bookfinder_host/ports.py` | `Docker.run_efbundle` 回傳 `(exit code, 輸出)` |
| `deploy/host/bookfinder_host/adapters.py` | `RealDocker.run_efbundle` 回傳 `(returncode, stdout + stderr)`；argv 不變 |
| `deploy/host/bookfinder_host/testing.py` | `FakeDocker` 新增 `efbundle_output`，回傳值改為 tuple |
| `deploy/tests/host/test_config.py` | 選填鍵：未設定、有效、空值、不合法字元、重複鍵、近似名稱的未知鍵 |
| `deploy/tests/host/test_adapters.py` | efbundle 回傳 exit code 與輸出 |
| `deploy/tests/host/test_machine.py` | migration 檔案分離、失敗時清除、未設定時不變、讀取失敗為 drift、輸出遮蔽、exit 0 但 id 不符時也寫入輸出 |
| `deploy/README.md` | §2.2 IAM、§2.3 SSM 表（新列與預設權限說明）、§2.4 選填鍵與安裝順序警告、RUN_DIR 列、§7.2 第 22 項（事件與恢復步驟） |
| `Docs/deployment/deployment.md` | §5 的 secret 檔案與 host.conf 鍵 |
| `deploy/docs/architecture.md`、`workflow-diagram.md`、`backlog.md`、`test-suite.md`、`update-history.md` | 查核基準更新為 `5563d80`；架構選項與流程圖；§3.20 測試表；update-history §3.12 |

## 實作思路

- **設定**：比照 `DB_CA_BUNDLE`，放在 `_OPTIONAL_UNSET`。值使用既有的字元規則，因此空值與控制字元會以 `ConfigError` 拒絕。
- **讀取時機**：步驟 3 與其他 SSM 值一起讀取。即使是 in-sync 部署也會讀取，讓錯誤在任何變更之前出現。讀取失敗與驗證失敗沿用既有的 `drift` 與 `rejected` 處理，並且在寫檔前結束。
- **檔案分離**：web 的 env file 維持原本的三個值；migration 值只寫入 `migrate-<run_id>.env`，efbundle 讀取此檔。未設定時 efbundle 讀 web env file，與之前相同。
- **清除**：`_discard_env` 在 `finally` 中刪除兩個路徑（路徑為空時略過）。
- **輸出**：failed-migration 的分支在 `raise` 之前呼叫 `_journal_efbundle_output`，輸出經 `_mask` 遮蔽（與切換失敗診斷使用相同的 `r.secrets`，其中包含 migration 值與其 `Password=` 部分）。exit code、history 結果與 `FAILED_MIGRATION` 的語意都沒有變更。

## 執行紀錄（Log）

- `4a844f8` feat(host): add optional SSM_MIGRATION_CONNECTION host.conf key（TDD：先寫失敗的測試，再實作）
- `5563d80` feat(host): migration connection file for efbundle and journal failed efbundle output（TDD：先寫 machine 與 adapter 測試，確認失敗後實作）
- 測試過程中修正了兩處測試本身的錯誤：tail 行數的 off-by-one（80 行尾端從第 23 行開始），以及讀取失敗的測試把 step 2 的 `docker.extract`（唯讀）誤列為變更。
- `1642e7c` docs(deploy): document SSM_MIGRATION_CONNECTION and the v0.0.6 migration incident (#121)
- 本報告為獨立的 commit。

## 驗證結果

- `.venv/bin/python -m pytest deploy/tests -q`：`645 passed, 7 skipped`（基準為 `632 passed, 7 skipped`）
- `uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -q`：`645 passed, 7 skipped`
- `uvx ruff@0.17.2 check --config deploy/ruff.toml deploy`：`All checks passed!`
- `uvx ruff@0.17.2 format --check --config deploy/ruff.toml deploy`：`51 files already formatted`
- `.venv/bin/python -m pytest .github/scripts -q`：`78 passed`
- `BOOKFINDER_IT=1 .venv/bin/python -m pytest deploy/tests -m integration -q -s`：`7 passed, 645 deselected in 278.30s (0:04:38)`（docker 可用；含 forward、失敗 migration 與 rollback 的真實容器路徑）

## 未解決事項

1. **rollback 會重新執行 `_render_env`**，因此也會重新讀取 `SSM_MIGRATION_CONNECTION`。若讀取在 rollback 期間失敗，會得到 `failed-down`（說明為 rollback 無法渲染環境）。這個情況機率很低，但不是零。目前沒有改動，因為 rollback 的 env 渲染需要同時更新 web 與 migrate 檔（遮蔽所需的 secrets 也要一致）。待 review 決定是否改為只重讀 web 值。
2. **EC2 上的實際權限行為未驗證**：`ALTER DEFAULT PRIVILEGES` 的設定屬於 RDS 管理者的操作，程式無法檢查；設定後的第一次 forward migration 需要營運觀察。
3. **host.conf 順序**：加入 `SSM_MIGRATION_CONNECTION` 前必須先 `install-host`。程式無法在 host.conf 中偵測舊版 host，只能靠文件警告（§2.4）。
4. **efbundle 輸出的遮蔽只做字面替換**：若 EF 或 Npgsql 把密碼以不同的編碼（例如 URL 編碼）印出，不會被遮蔽。這是既有機制的限制，本次沒有擴充遮蔽方式。

## Code Review 與修正

待 review
