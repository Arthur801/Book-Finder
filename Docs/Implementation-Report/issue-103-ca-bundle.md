# Issue #103：DB_CA_BUNDLE（verify-full 的 CA bundle 掛載）

## 變更檔案

- `deploy/host/bookfinder_host/config.py`：可選鍵 `DB_CA_BUNDLE`（無預設值）；解析時限制字元與絕對路徑；`check_ca_bundle()`（lstat、一般檔案、非 symlink、others 可讀、不超過 1 MiB）；`ca_bundle_mount_args()`；`make_psql_query` 加入唯讀掛載。
- `deploy/host/bookfinder_host/adapters.py`：`RealDocker` 的 efbundle `docker run` 加入唯讀掛載；`RealCompose` 在 `up`/`down` 加入 `-f <release>/compose.ca-bundle.yaml` 與 compose 環境變數 `DB_CA_BUNDLE`（僅設定時）。`config --format json`（probe）維持只用 probe 自己的檔案。
- `deploy/host/bookfinder_host/release_content.py`：`COMPOSE_CA_BUNDLE`；`ReleaseContent.ca_bundle_override` 表示 release 是否附帶 override。
- `deploy/host/bookfinder_host/machine.py`：step 2 在搬移 release 目錄之前，若設定 `DB_CA_BUNDLE` 而 release 沒有 override，以 `rejected`（exit 2）拒絕；回滾到 Docker release 時，若設定 `DB_CA_BUNDLE` 而前一個 release 沒有 override，以 `failed-down` 拒絕回滾並說明原因。
- `deploy/release/compose.ca-bundle.yaml`（新增）：`web` 的唯讀 bind mount，source 與 target 皆為 `${DB_CA_BUNDLE:?…}`。
- `Dockerfile`：`COPY` 把 `compose.ca-bundle.yaml` 放進 `/opt/release/`。
- `crawler/deploy/run-crawler.sh`：`DB_CA_BUNDLE` 有設定時驗證（絕對路徑、字元、非 symlink、一般檔案、可讀、mode 的 o+r），通過後加入 `--mount ...,readonly`；在取得 lock 與讀取 state 之前完成驗證。
- `crawler/deploy/crawler.conf.example`：註解範例。
- `deploy/README.md`：§2.3、§2.4（選填鍵表格列）、§2.5（只建立不存在的目錄、權限表）、§7.2 第 20 列（事故紀錄）。
- `crawler/deploy/README.md`：§3 verify-full URL；§4 改為只建立不存在的目錄；設定表新增 `DB_CA_BUNDLE` 列。
- 測試：`deploy/tests/host/test_config.py`、`test_adapters.py`、`test_machine.py`、`test_release_content.py`、`deploy/tests/test_release_files.py`（含真實 `docker compose config` 渲染測試）、`crawler/tests/test_deploy.py`。

## 實作思路

- 單一來源：`DB_CA_BUNDLE` 只在 `host.conf` 與 `crawler.conf` 定義；四種容器都用同一個絕對路徑、唯讀、掛載到容器內相同位置，所以連線字串中的 `Root Certificate=` 不需要因容器而改變。
- 路徑字元限制為 `A-Za-z0-9._/-`，因為路徑會進入 `--mount` 選項與 compose 變數；逗號或等號會破壞 `--mount` 的解析。
- 驗證在任何變更之前完成：host 在 `load_settings`（exit 2 於任何 step 之前）；crawler 在 `source` 後、建立目錄與取得 lock 之前。
- 未設定時的 argv 與 compose 檔案組合與修改前完全相同（測試以 fake 確認）。
- compose 檔案組合：`up`/`down` 共用同一組 `-f`；probe 只渲染自己的一次性檔案，因為 override 指名 `web` 服務，probe 檔案中沒有該服務。
- 回滾：只有 Docker 型前一版 release 需要判斷；systemd 型回滾不經過 compose，不受影響。

## 決策

- **回滾到沒有 override 的 release**（v0.0.1、v0.0.2 都沒有）：設定 `DB_CA_BUNDLE` 時拒絕回滾，回報 `failed-down` 並說明原因（不自動回滾）。理由：啟動沒有掛載的舊 web 會連不上 verify-full 的 RDS。只有在設定 `DB_CA_BUNDLE` 之後的 cutover 才會遇到這個情況，未設定時行為不變。
- **驗證不依 euid**：規格寫「production, euid 0」；實作選擇在任何 euid 都驗證已設定的 bundle（更嚴格，且 `AWS_CLI` 的 root 檢查仍只在 euid 0 執行）。

## 執行紀錄（Log）

- 分支 `issue-103-ca-bundle`，基底 `eea4f73`（origin/main）。TDD：每一步先寫失敗測試，再實作。
- 提交（皆帶 `(#103)`，未 push、未 tag、未 amend）：
  - `439b80e` feat(deploy): optional DB_CA_BUNDLE for host config, efbundle, psql and web compose
  - `a11a2c6` feat(release): ship compose.ca-bundle.yaml read-only bind for web
  - `f636a29` feat(crawler): optional read-only DB_CA_BUNDLE mount in run-crawler.sh
  - `222c7ce` docs(deploy): document DB_CA_BUNDLE and never re-run install -d on existing dirs
  - `9a28cc3` style(crawler): format DB_CA_BUNDLE test helper with ruff
- 途中修正：測試本身的錯誤（目標 release 也要附 override；多餘的 compose 狀態改寫）。
- 文件中發現同樣的 `install -d -m` 問題也在 crawler README §4，已一併改為只建立不存在的目錄。

## 驗證結果

- `.venv/bin/python -m pytest .github/scripts/tests deploy/tests -q`：`677 passed, 7 skipped in 5.84s`（在格式修正的 crawler 提交之前執行；之後僅改格式）。
- `uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -q`：`608 passed, 7 skipped in 5.46s`。
- `cd crawler && ../.venv/bin/python -m pytest tests/test_deploy.py -q --noconftest`：`28 passed in 10.61s`。
- ruff（釘選 0.17.2，來自 `crawler/requirements.txt`）：
  - `ruff check --config deploy/ruff.toml deploy`：`All checks passed!`
  - `ruff format --check --config deploy/ruff.toml deploy`：`46 files already formatted`
  - `ruff check --config crawler/ruff.toml .github/scripts`：`All checks passed!`
  - crawler 目錄 `ruff check .`：`All checks passed!`；`ruff format --check .`：`48 files already formatted`（修正前有一個檔案需要格式化，已在 `9a28cc3` 修正）
- shellcheck：`crawler/deploy/run-crawler.sh` 與 `deploy`、`crawler/deploy` 下的 `.sh` 只有 SC1090（既有警告，`source` 非常數路徑）。
- actionlint 1.7.7（docker 映像）：exit 0，無輸出。
- `docker build -t bf-web-103:verify .`：`BUILD_RC=0`；映像中 `/opt/release/compose.ca-bundle.yaml` 存在。
- `bash deploy/smoke/web-smoke.sh bf-web-103:verify`：`all checks passed`，`SMOKE_RC=0`（web 以 uid 1654 執行）。
- 真實 `docker compose -f compose.prod.yaml -f compose.ca-bundle.yaml config --format json`（Compose v5.6.0，`WEB_IMAGE`、`WEB_ENV_FILE`、`DB_CA_BUNDLE` 為假值與暫存檔）：`web` 的 volumes 含 `{"type":"bind","source":<p>,"target":<p>,"read_only":true}`；未設定 `DB_CA_BUNDLE` 時 interpolation 失敗；不加 override 時無 bind。此為 `test_real_compose_mounts_the_bundle_read_only_on_web`，已在 deploy/tests 中通過。
- `BOOKFINDER_IT=1 .venv/bin/python -m pytest deploy/tests -m integration -q -s`（`DB_CA_BUNDLE` 未設定）：`7 passed, 608 deselected in 261.33s`，`IT_RC=0`。
- 清理：`bf-*` 映像、網路、volume、容器皆為 0。`.venv` 未觸碰。

## 未解決事項

- 尚未在 EC2 上啟用 `DB_CA_BUNDLE`；SSM 的連線字串是否改為 verify-full 由部署者決定（§2.3）。
- 未發布 `v0.0.3`（依指示，本次不 tag）。
- 規格提到 runbook 與「wizard」：repository 中沒有 wizard 檔案，本次只修改 `deploy/README.md` 與 `crawler/deploy/README.md`。
- 驗證的是 `config` 的父目錄路徑：只檢查 bundle 檔案本身的 lstat，沒有檢查父目錄是否為 symlink；§2.5 要求 `/etc/book-finder` 為 0755，並由操作者確認。
- 舊 release（v0.0.1/v0.0.2）沒有 override：在設定 `DB_CA_BUNDLE` 的主機上，這些版本無法部署也無法回滾到，直到有附 override 的新版本發布。

## Code Review 與修正

（review 後補上）
