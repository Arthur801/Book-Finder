# deploy/ 待辦：優化與 debug

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M3（#120）補記：2026-10-25 更新；程式變更以 `d249c07`、`6e70e93`、`b99b368` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M4（#120）補記：2026-10-25 更新；gate 9 與 manual recovery smoke 的程式變更以 `89d983e`、`7c8899d` 記入 update-history §3.14。原查核基準保留，未重新審查其餘內容。

> 目標：`deploy/` 與分散的 CD 來源（見 [architecture.md §2](architecture.md)）。
> 查核基準：2026-10-25，HEAD `5563d80`（#121 的程式 commit；前一基準 `01db2d7`，tag `v0.0.4`）。證據來自程式、測試、git 與 runbook；營運觀察以「營運觀察，非本次驗證」標示。
> 本文件只列有證據、可判定結案的項目。已完成的歷史修復（pg_dump 假陽性、`sudo` 的 `env_keep`、urllib 預設 User-Agent 的程式修正）不列為未完成；其中 User-Agent 在 production 的生效仍列為 DEP-B02。

## 0. 欄位與詞彙

- **優先序**：專案文件未定義優先序詞彙。本文件採用 P1（影響下一次上線或正在進行的營運）、P2（影響正確性、安全或恢復能力，應在下一次相關變更前處理）、P3（改善或文件同步）。
- **風險級別**：沿用 [AGENTS.md §4.1](../../AGENTS.md)，L1 到 L4。實作與驗證的風險不同時，分開標示（例如「實作 L2／啟用 L4」）。
- **狀態**：`已確認缺口`、`已重現`、`待驗證`、`待決策`、`改善提案`、`明確暫緩`。
- **測試入口**：列出 [test-suite.md](test-suite.md) 的案例 ID；「待建」表示尚無對應測試。
- 本文件是待辦清單，不是執行授權。列出的命令或 L4 操作需要使用者當下明確授權。

## 1. 項目總覽

| ID | 優先序 | 風險 | 狀態 | 主題 |
|---|---|---|---|---|
| DEP-B01 | P1 | 實作 L2／營運 L4 | 已確認缺口（營運觀察）＋待決策 | EC2 IP 被博客來封鎖，crawler 停用 |
| DEP-B02 | P1 | L4 | 待驗證 | 公開健康檢查的 User-Agent 在 edge 與 host 版本上未確認 |
| DEP-B03 | P2 | L4（啟用）／L3（設計） | 已確認缺口（設計限制） | `DB_CA_BUNDLE` 啟用後，回滾下限為 v0.0.3 |
| DEP-B04 | P1 | L4 | 待驗證 | forward migration、snapshot、dirty 路徑未在 production 執行 |
| DEP-B05 | P3 | L4（刪除）／L2（設計） | 改善提案 | GHCR 的 `build-*` staging tag 只能手動清理 |
| DEP-B06 | P2 | L4 | 待驗證 | release tag 的 digest 不變式只在本機 registry 驗證；發布前設定未記錄 |
| DEP-B07 | P3 | L3 | 改善提案 | 沒有 drift 修復指令，只能人工程序 |
| DEP-B08 | P2 | L3 | 已確認不一致（程式閱讀）＋待驗證 | 損壞的 history 尾端：operator 回 exit 3，plan 與 unit 回 exit 8 |
| DEP-B09 | P3 | L2 | 改善提案 | 大型模組（`operator_cli.py`、`cd_release.py`）的可維護性 |
| DEP-B10 | P3 | L2 | 改善提案 | `plan` job 的 12 個字串 output 與人工解析 |
| DEP-B11 | P3 | L2 | 改善提案 | `cd.yml` 中 plan 與 deploy 的 SSH 設定重複 |
| DEP-B12 | P2 | L3 | 待驗證 | secret 遮蔽只做字面替換 |
| DEP-B13 | P2 | L3 | 待驗證（repo 內無證據） | Cloudflare 與 `CF-Connecting-IP`（issue #27） |
| DEP-B14 | P2 | L3 | 已發生（營運觀察）＋待驗證 | SSM 連線字串的跳脫問題 |
| DEP-B15 | P3 | L2 | 改善提案 | `/etc/book-finder` 目錄權限未由程式檢查 |
| DEP-B17 | P3 | L3 | 改善提案 | exit 3 同時對應 history 的 `drift` 與 `rejected` |
| DEP-B18 | P1 | L4（部署）／L3（seed 與測試） | 程式與測試已完成（#120）；011 部署待 gate | Multi-source migration 010／011 的 seed、gate 與恢復程序 |
| DEP-B19 | P3 | L2 | 改善提案（#120 review） | compat contract allowance 與 gate 9 script 的結構整理 |

## 2. 項目

### DEP-B01 EC2 IP 被博客來封鎖，crawler 停用

- **優先序／風險**：P1／實作 L2，營運啟用 L4。
- **狀態**：已確認缺口（營運觀察，2026-10-24 手動試跑失敗）；待決策（替代資料管道）。
- **證據與影響**：runbook [§7.2 #19](../README.md) 記錄；[deployment.md §8](../../Docs/deployment/deployment.md) 要求「啟用排程前須在 EC2 實測」，被擋下時「不啟用排程，評估授權資料管道」；`run-crawler.sh` 在 `CRAWLER_ENABLED=false` 時於任何鎖之前 exit 0 並輸出 `skipped=disabled`（[run-crawler.sh](../../crawler/deploy/run-crawler.sh) 第 53 行起）。影響：每日榜單不更新，`bestseller` 資料停止新增。
- **spec／source**：`Docs/deployment/deployment.md` §8；`Docs/modules/crawler.md` §12；[crawler/deploy/README.md §5.1](../../crawler/deploy/README.md)。
- **調查方向**：(1) 在 EC2 上以唯讀方式執行一次 `run-crawler.sh daily`，記錄是否取得頁面（需授權）；(2) 若仍被擋，需要產品與授權層級的決策：替代資料來源、授權管道、或維持停用。抓取政策自 `3101dd1`（#108）起已允許（現由 [crawler 架構](../../crawler/docs/architecture.md)「核心不變條件」持有） browser stealth、`navigator.webdriver` 修補、CAPTCHA 代解或代理 IP 輪替；是否採用、採用哪一種仍是本項的待決策事項，且真實抓取驗證須有當前任務授權。
- **前置決策**：是否接受停用期間的榜單缺口；替代資料來源是否需要獨立 ADR（AGENTS §2.4）。
- **驗收條件**：(a) 在 EC2 手動執行成功並取得 `ranking_count=100`（依 crawler/deploy/README §6）；(b) 將 `CRAWLER_ENABLED` 改為 `true` 後，排程至少觀察一次成功；(c) 若選擇替代管道，有 ADR 與對應規格。
- **測試入口**：DEP-CRW-GATE-07、DEP-CRW-GATE-08（`CRAWLER_ENABLED` 的 true、false 與非法值）；DEP-PROD-02（營運觀察）。真實抓取測試需當前任務授權。

### DEP-B02 公開健康檢查的 User-Agent 在 edge 與 host 版本上未確認

- **優先序／風險**：P1／L4。
- **狀態**：待驗證。
- **證據與影響**：營運觀察中，兩次 cutover 都因公開階段 403 而 `failed-down`；原因是 urllib 預設的 `Python-urllib/3.x`。修正 commit `2fb5e27`（#105）讓 `RealHttp` 送出 `book-finder-deploy/<HOST_API_RANGE max>`（[adapters.py](../host/bookfinder_host/adapters.py) 的 `RealHttp`、[config.py](../host/bookfinder_host/config.py) 的 `host_user_agent`），`2fb5e27` 是 `v0.0.4` 的祖先（已確認）。未確認的部分：(1) EC2 上 host 程式是否以含此修正的版本安裝（host 程式由 `install-host` 安裝，與 release tag 獨立；營運觀察未記錄安裝來源）；(2) Cloudflare 或 nginx 的規則是否放行 `book-finder-deploy/*`（runbook §7.2 #7 待確認）；(3) 自訂 UA 可能被 WAF 規則誤擋（營運觀察提醒）。
- **spec／source**：runbook §3.4 step 3 與 step 7、§3.6、§7.2 #7；`test-suite` 的 DEP-HTTP 系列。
- **調查方向**：(a) 在 EC2 以 `host-versions` 的 `HOST_API_RANGE` 或 `book-finder-admin` 版本資訊確認安裝來源（唯讀）；(b) 由 EC2 執行 `curl -sI -A 'book-finder-deploy/1' <PUBLIC_URL>`，同時比對瀏覽器 UA；(c) 若 edge 依 UA 拒絕，應在 edge 設定放行規則，而不是改用偽裝瀏覽器 UA。
- **前置決策**：edge 規則由誰維護（使用者）；是否需要不依 UA 的替代健康端點（新功能，需要 ADR 與規格）。
- **驗收條件**：(a) `curl -sI -A 'book-finder-deploy/1' <PUBLIC_URL>` 回 200；(b) 下一次 deploy 或 rollback 的 journal 不含 `stage=public status=403`；(c) 記錄 host 程式的版本與安裝時間於 runbook 或 state 外的部署紀錄。
- **測試入口**：DEP-HTTP-01 到 DEP-HTTP-04（單元，已有）；DEP-HEALTH-03（journal 的 403 提示，已有）；DEP-PROD-03（營運觀察）。公開階段的真實驗證屬 L4，需授權。

### DEP-B03 `DB_CA_BUNDLE` 啟用後，回滾下限為 v0.0.3

- **優先序／風險**：P2／啟用 L4，設計 L3。
- **狀態**：已確認缺口（設計限制，程式行為已由測試覆蓋）。
- **證據與影響**：`_rollback` 在 `DB_CA_BUNDLE` 已設定、且舊 release 沒有 `compose.ca-bundle.yaml` 時，以 `failed-down` 拒絕回滾（[machine.py](../host/bookfinder_host/machine.py) 的 `_rollback`）。git tree 確認：`v0.0.1` 與 `v0.0.2` 只有 `build-manifest.sh` 與 `compose.prod.yaml`；`v0.0.3` 起有 `compose.ca-bundle.yaml`。runbook §7.2 #20 記錄 EC2 尚未啟用 `DB_CA_BUNDLE`。影響：啟用後，回到 v0.0.1 或 v0.0.2 不再是可自動回滾的目標，需要人工處理。
- **spec／source**：runbook §2.3、§2.4（`DB_CA_BUNDLE` 行）、§3.6、§7.2 #20。
- **調查方向**：(a) 在 runbook 明確寫出「啟用 `DB_CA_BUNDLE` 後的最低回滾版本為 v0.0.3」；(b) 或在啟用前發布 override 版本，並確認舊版不再是回滾目標。
- **前置決策**：是否接受此下限（使用者）。
- **驗收條件**：runbook 的 `DB_CA_BUNDLE` 列寫明最低回滾版本，並與 `test_configured_bundle_refuses_rollback_to_a_release_without_the_override` 的行為一致。
- **測試入口**：DEP-ROLL-03（已有）、DEP-ROLL-04（已有）、DEP-REL-01（已有）。

### DEP-B04 forward migration、snapshot、dirty 路徑未在 production 執行

- **優先序／風險**：P1（在下一個含 migration 的 release 之前）／實作 L3，production 執行 L4。
- **狀態**：待驗證。
- **證據與影響**：production 目前只記錄 cutover（`in-sync`）與 crawler 停用。forward 路徑（pause、`create-db-snapshot`、`wait db-snapshot-available`、dirty、efbundle、`mark_migrated`）只在單元測試（fake world）與本機整合情境 a 到 d（需 `BOOKFINDER_IT=1`）中執行過；`adapters.RealAws` 的真實 AWS CLI 呼叫沒有在 production 驗證（runbook §5.7、§7.2 #4 的 psql 連線待確認）。
- **spec／source**：`Docs/deployment/deployment.md` §6；ADR-006 I3、I5、N2、N3；runbook §1.4、§5.2、§5.6。
- **調查方向**：(a) 在開發機以 `BOOKFINDER_IT=1 bash deploy/integration/run-local.sh` 驗證情境 a 到 d（需 Docker，不連 production）；(b) 首次含 migration 的 release 前，寫出 rollback 與 snapshot 的人工計畫，並確認 `rds:CreateDBSnapshot` 與 `rds:DescribeDBSnapshots` 的 IAM（runbook §2.2）已存在。
- **前置決策**：首次 forward 的時間與授權（使用者）。
- **驗收條件**：(a) 情境 a 到 d 在開發機通過並記錄結果（記錄於 PR 或 issue，不寫入 repository）；(b) 第一次 forward 的 `history` 含 `snapshot_id` 與 completed，且 runbook §5.2 的檢查清單完成。
- **測試入口**：DEP-FWD-01 到 DEP-FWD-06（單元，已有）；DEP-INT-A 到 DEP-INT-D（整合，已有，本次未執行）。

### DEP-B05 GHCR 的 `build-*` staging tag 只能手動清理

- **優先序／風險**：P3／清理 L4，設計 L2。
- **狀態**：改善提案。確切的 GHCR 網頁路徑在 runbook 標為「待確認」。
- **證據與影響**：`cd.yml` 的 staging push 以 `build-<run_id>-<attempt>` 命名，程式不刪除；runbook §1.6 規定只能刪除版本上所有 tag 都是 `build-*` 的版本。影響：GHCR 儲存與版本列表會累積。
- **spec／source**：runbook §1.6、§7.2 #18；[cd.yml](../../.github/workflows/cd.yml) 的 `Build and push` 步驟；`cd_release.py` 的 `STAGING_TAG_RE`。
- **調查方向**：確認 GHCR 的實際路徑後，寫成手動步驟。若要自動化，需要 `packages:delete` 權限，風險 L4，需要授權。
- **驗收條件**：runbook §1.6 的路徑改為已確認的實際位置；刪除前的檢查清單（版本上所有 tag 都是 `build-*`）保留。
- **測試入口**：DEP-REL-07（待建；目前沒有測試）。

### DEP-B06 release tag 的 digest 不變式只在本機 registry 驗證；發布前設定未記錄

- **優先序／風險**：P2／L4。
- **狀態**：待驗證。
- **證據與影響**：`--prefer-index=false` 的行為由 `imagetools-roundtrip.sh` 在本機 registry 驗證（DEP-IMG-01，已有）。runbook §7.2 #17 要求「第一次正式 release 在 GHCR 上的 end-to-end 確認」；營運觀察顯示 v0.0.1 至 v0.0.4 已存在，但 runbook 與營運紀錄沒有記錄 `Confirm the web release tag` 與 `Confirm the crawler release tag` 步驟的結果。runbook §2.8 與 §7.2 #11 要求確認 Immutable Releases 已啟用，沒有記錄。
- **spec／source**：runbook §1.6、§2.8、§2.9、§7.2 #11、#17；`cd.yml` 的 `Confirm` 步驟；ADR-006 Trade-offs。
- **調查方向**：(a) 從 GitHub Actions 的既有執行紀錄（唯讀）確認 `v0.0.1` 至 `v0.0.4` 的 `Confirm` 步驟通過；(b) 在 repository 設定確認 Immutable Releases（唯讀）；(c) 把結果寫入 runbook §7.2 #11、#17 的狀態。
- **驗收條件**：runbook §7.2 #11、#17 的「待確認」改為有日期與來源的結果；若任一項不通過，依 §1.6 處理（L4）。
- **測試入口**：DEP-IMG-01（已有）、DEP-CD-CONFIRM-01（`test_confirm_release_digest_requires_the_attested_digest`，已有）；GHCR 實際結果為 DEP-PROD-06（營運觀察）。

### DEP-B07 沒有 drift 修復指令，只能人工程序

- **優先序／風險**：P3／L3。
- **狀態**：改善提案（runbook §5.4 已將其列為「待辦」）。
- **證據與影響**：`book-finder-admin` 只有五個子指令（`bootstrap-state`、`reconcile-schema`、`resume-crawler`、`resolve-run`、`install-host`），沒有 drift 修復（[operator_cli.py](../host/bookfinder_host/operator_cli.py) 的 `build_parser`）。runbook §5.4 要求人工逐步處理，且手動 runtime 操作不寫入 history。
- **spec／source**：runbook §5.4、§6；ADR-006 I1、S5；`Docs/deployment/deployment.md` §6。
- **調查方向**：先決定是否需要新指令。若需要，必須依 S8、S10 的 operator 協定，並寫入 history；不能讓 agent 或 CI 自動修復 drift。
- **前置決策**：是否新增指令（使用者與 ADR）。
- **驗收條件**：若採用，新指令遵守 `_perform` 協定，有 ADR、runbook、單元測試與 negative cases（例如 schema drift 拒絕）。若不採用，runbook §5.4 明確標示為「不提供」。
- **測試入口**：DEP-OP-PROTO-01（待建）。

### DEP-B08 損壞的 history 尾端：operator 回 exit 3，plan 與 unit 回 exit 8

- **優先序／風險**：P2／L3。
- **狀態**：已確認不一致（程式閱讀）；待驗證（缺少測試覆蓋）。文件已於 PR #107 依現行行為對齊（runbook §1.5、§5.1），程式行為的統一仍待決策。
- **證據與影響**：`operator_cli._refuse_while_indeterminate` 在 `records.tail_corrupt` 時以 `DRIFT`（3）拒絕，訊息要求先執行 `resolve-run`。`plan` 與 `run_deploy_unit` 在相同情況下以 `INDETERMINATE`（8）拒絕或不寫入。runbook §1.5 的 exit 8 定義為「有未解決的 indeterminate run 或 operator operation」，沒有列出 operator 的尾端情況。影響：操作者看到的退出碼與文件不一致，可能誤判為 drift 並嘗試重新 plan。
- **spec／source**：runbook §1.5、§5（「若只有 started 沒有 completed」）；`operator_cli.py` 的 `_refuse_while_indeterminate`；`commands.py` 的 `run_deploy_unit`；ADR-006 S8、S10。
- **調查方向**：(a) 寫出一個 operator 指令在損壞尾端下的測試，預期結果以 runbook 為準；(b) 若決定統一為 8，修改 operator 路徑並更新 runbook §1.5。
- **前置決策**：統一為 exit 8 或更新文件（使用者決定；兩者都會改變退出碼的 public contract，需同步 runbook 與 ADR）。
- **驗收條件**：測試同時覆蓋 plan、deploy、operator 三條路徑；退出碼與 runbook §1.5 一致。
- **測試入口**：DEP-GATE-14（plan 的 exit 8，已有）；DEP-OP-14（operator 的損壞尾端，待補強）。

### DEP-B09 大型模組的可維護性

- **優先序／風險**：P3／L2。
- **狀態**：改善提案。
- **證據與影響**：行數（`wc -l`）：`operator_cli.py` 1061、`cd_release.py` 1005、`commands.py` 703、`machine.py` 702、`state.py` 447、`testing.py` 459。`cd_release.py` 同時負責 release 記錄、attestation、plan 解讀、compat 摘要與 deploy 跟隨。大型模組增加審查成本；目前沒有證據顯示已造成錯誤。
- **spec／source**：`architecture.md` §3；`AGENTS.md` §2.4（既定模組內可重構）。
- **調查方向**：以功能切分（例如 `cd_release` 的 attestation 與 follow）。切分時不得改變退出碼、JSON 欄位與 GitHub output 名稱。
- **驗收條件**：切分前後 `pytest .github/scripts/tests deploy/tests -q` 與 `python -m pytest deploy/tests -q` 結果相同；公開 contract 不變。
- **測試入口**：DEP-CD-* 系列（已有）、DEP-OP-* 系列（已有）。

### DEP-B10 `plan` job 的 12 個字串 output 與人工解析

- **優先序／風險**：P3／L2。
- **狀態**：改善提案。
- **證據與影響**：`cd.yml` 的 `plan` job 有 12 個 `outputs`（`revision`、`expect_runtime`、`expect_schema`、`chain`、`pending`、`applied_last`、`rebuild_tag`、`rebuild_web_digest`、`runtime_web_digest`、`state_crawler_digest`、`crawler_for_deploy`、`cutover_ok`），由 `cd_release.py plan-outputs` 寫入。`pending` 等欄位以字串傳遞，後續 job 再解析。
- **spec／source**：`cd.yml`（`plan` job 的 `outputs`）；`cd_release.py` 的 `plan_outputs` 與 `write_outputs`。
- **調查方向**：評估是否改為單一 JSON output 加上 `fromJSON`。需要確認 GitHub output 的大小限制仍在範圍內。
- **驗收條件**：deploy job 收到的值與目前相同；`write_outputs` 仍拒絕換行（`test_write_outputs_rejects_newlines`）。
- **測試入口**：`test_cli_plan_outputs_success_writes_github_output`、`test_write_outputs_rejects_newlines`（已有）。

### DEP-B11 `cd.yml` 中 plan 與 deploy 的 SSH 設定重複

- **優先序／風險**：P3／L2。
- **狀態**：改善提案。
- **證據與影響**：`plan` job（寫入 `plan_key`、`known_hosts`，`ssh -i ... -o UserKnownHostsFile=...`）與 `deploy` job（寫入 `deploy_key`、`known_hosts`，同樣的 `ssh` 選項）各有一份。兩份必須保持一致，尤其是 `IdentitiesOnly`、`UserKnownHostsFile` 與清理步驟。
- **spec／source**：`cd.yml` 的 `Write the plan SSH files` 與 `Write the deploy SSH files`；runbook §2.8。
- **調查方向**：抽成 composite action 或共用腳本；`cd_release.py` 的 `status_ssh_argv` 已統一 status 的選項。
- **驗收條件**：兩處的 SSH 選項集合相同（可由 grep 檢查）；shellcheck 與 CI 的 lint 通過。
- **測試入口**：`test_status_ssh_argv_uses_the_plan_key_options`（已有）；workflow 本身的檢查為待建（DEP-CI-01）。

### DEP-B12 secret 遮蔽只做字面替換

- **優先序／風險**：P2／L3。
- **狀態**：待驗證。
- **證據與影響**：`machine._mask` 只以 `str.replace` 替換三個 secret 的原始值；`_PASSWORD_PART` 只遮蔽連線字串中 `Password=` 的值。若輸出中出現的是同一密碼的 URL 編碼形式、或被 psql 或 docker 以不同形式輸出，字面替換不會遮蔽。目前可能寫入 journal 的內容：`_journal_container_log` 的 80 行 log 與 `_journal_health_failure`。`web-RUN.env` 不寫入 journal。
- **spec／source**：runbook §3.6（「env 檔中三個 secret 的值…都會先以 `***` 取代」）；`Docs/deployment/deployment.md` §5；`machine.py` 的 `_secret_strings` 與 `_mask`。
- **調查方向**：(a) 列出所有寫入 journal 或 stderr 的來源，確認是否可能含 secret；(b) 增加 URL 編碼形式與去除首尾空白形式的遮蔽，並加上 negative test；(c) 若無法證明完整遮蔽，改為不輸出 container log。
- **前置決策**：是否保留 container log（diagnostics 與遮蔽之間的取捨，使用者決定）。
- **驗收條件**：新測試在 URL 編碼密碼的 log 中斷言不出現原值；既有測試 `test_secret_values_are_masked_in_the_container_log_and_never_printed` 仍通過。
- **測試入口**：DEP-SEC-01（已有）、DEP-SEC-02（待補強，本文件新增的案例）。

### DEP-B13 Cloudflare 與 `CF-Connecting-IP`（issue #27）

- **優先序／風險**：P2／L3。
- **狀態**：待驗證。repository 內沒有 `CF-Connecting-IP` 或 issue #27 的文字；此項來自營運討論，本文件無法核對 issue 內容。
- **證據與影響**：web 的 Forwarded Headers 只信任 `KnownNetworks`（`compose.prod.yaml` 與 `Program.cs`）。rate limiting 依賴正確的 client IP（`Docs/deployment/deployment.md` §3）。若 Cloudflare 位於 nginx 之前，client IP 可能只在 `CF-Connecting-IP` 中，且只能在受信任來源時採用。runbook §7.2 #8 也待確認 `172.31.250.0/24` 是否涵蓋 nginx 經 docker-proxy 的來源。
- **spec／source**：`Docs/deployment/deployment.md` §3；`identity-auth.md` §7（rate limiting）；`deploy/release/compose.prod.yaml`；`Infrastructure/Hosting/HostingSetup.cs`；runbook §7.2 #8。
- **調查方向**：(a) 讀取 issue #27 的內容（需使用者授權或提供內容）；(b) 確認 web 只在 `KnownNetworks` 內的來源時採用 `CF-Connecting-IP`；(c) 以 integration test 驗證不受信任來源的偽造標頭被忽略。
- **前置決策**：Cloudflare 的 IP 範圍由誰維護，如何同步到 `KnownNetworks`（使用者與 ADR）。
- **驗收條件**：web 的 ForwardedHeaders 測試包含 `CF-Connecting-IP` 的受信任與不受信任兩種情況；runbook §7.2 #8 有結果。
- **測試入口**：DEP-REL-04（`test_known_networks_equals_web_network_subnet`，已有）；DEP-WEB-FH-01（`ForwardedHeadersTests.cs`，已有檔案，待確認是否涵蓋 CF 標頭；本次未讀取該檔）；DEP-WEB-FH-02（待補強）。

### DEP-B14 SSM 連線字串的跳脫問題

- **優先序／風險**：P2／L3。
- **狀態**：已發生（營運觀察，2026-10-24）；修正未在 repository 中找到證據，待驗證。
- **證據與影響**：營運觀察記錄 SSM 連線字串的跳脫問題。runbook §2.3 規定 `SSM_DB_CONNECTION` 必須單行、無控制字元，但沒有規定 .NET 連線字串中密碼的跳脫（例如含 `;`、`=`、空白）。host 只檢查非空與控制字元（`machine._render_env`）。
- **spec／source**：runbook §2.3；`machine._render_env`；`config.py` 的 `SSM_*` 檢查。
- **調查方向**：(a) 寫出 SSM 參數值的建立規則（何種字元需要跳脫，哪一種格式可被 .NET 解析）；(b) 考慮在 host 端以唯讀方式解析連線字串（不輸出值），在寫入 env 前拒絕不合法格式。
- **前置決策**：是否在 host 增加解析（新檢查，需要規格與測試）。
- **驗收條件**：runbook 有可操作的 SSM 格式規則；若新增檢查，含 negative test（未跳脫的分號被拒絕）且不輸出值。
- **測試入口**：DEP-GATE-23（換行被拒絕，已有）；DEP-SEC-03（連線字串格式，待建）。

### DEP-B15 `/etc/book-finder` 目錄權限未由程式檢查

- **優先序／風險**：P3／L2。
- **狀態**：改善提案。事件本身已由文件與 DB_CA_BUNDLE 檢查處理（runbook §2.5）；PR #107 已把「目錄權限由操作者負責、程式不檢查」寫入 runbook §2.5 並附檢查指令。程式檢查仍為改善提案。
- **證據與影響**：營運觀察中，`install -d` 把既有目錄從 0755 改成 0750，導致 web 服務使用者無法讀取 CA bundle（500）。runbook 已禁止重新執行 `install -d`。`config.check_ca_bundle` 只檢查 CA 檔案本身（一般檔案、非 symlink、others 可讀），不檢查目錄是否可穿越。
- **spec／source**：runbook §2.5、§7.2 #20；`config.py` 的 `check_ca_bundle`。
- **調查方向**：評估是否檢查 CA 路徑每一層目錄的穿越權限（others 的 execute bit）。
- **驗收條件**：若採用，目錄權限不足時在任何變更前以 exit 2 拒絕，並有測試。
- **測試入口**：DEP-CFG-02（`test_check_ca_bundle_accepts_a_public_regular_file_up_to_one_mebibyte`，已有）；目錄檢查為待建（DEP-CFG-03）。

### DEP-B17 exit 3 同時對應 history 的 `drift` 與 `rejected`

- **優先序／風險**：P3／L3（`result` 字串是磁碟上 history 的格式，`exit_codes.py` 註明為 on-disk format）。
- **狀態**：改善提案。PR #107 已在 runbook §1.5 列出現行對照，文件與程式不再不一致。
- **證據與影響**：`exit_codes.RESULT_BY_EXIT[DRIFT]` 為 `rejected`，用於 gate 失敗；`commands.run_deploy_unit` 的 lock 逾時與 state 不存在、`machine._execute` 的 step 0 與 step 1 失敗、`machine` 的 `_Stop(DRIFT, "drift", …)` 直接寫 `drift`；`operator_cli._resolve_run` 以 `RESOLVE_EXIT` 寫 `drift`。影響：同為 exit 3，以 `result` 篩選 history 的人會得到不同集合。
- **調查方向**：決定是否統一。統一會改變已寫入 history 的解讀（需要說明），或把 gate 路徑改寫 `drift`。
- **前置決策**：使用者與 ADR（history 格式與 public contract）。
- **驗收條件**：若統一，所有 exit 3 路徑的 `result` 有斷言；runbook §1.5、architecture §5.1 同步更新。
- **測試入口**：DEP-HIST-03（待補強）。

### DEP-B18 Multi-source migration 010／011 的 seed、gate 與恢復程序

- **優先序／風險**：P1／seed 與 compat 測試 L3，010 與 011 的 production 部署 L4。
- **狀態**：程式、seed、preflight、contract allowance 與 gate 9 本機證據已於 #120（PR4 M1～M4）完成；剩下 011 在 production 的 gate 確認與部署（L4）。
- **目標**：[data-model §11](../../Docs/data/data-model.md) 與 [deployment §6.1](../../Docs/deployment/deployment.md)：010（expand，含雙向 trigger）與 011（contract）分屬不同 release；每個成為已發布 schema head 的 migration 都有 `deploy/migration-test/seeds/<id>.sql`；011 只在 gate 全部通過、使用者明確關閉 v0.0.4 rollback window 後部署；011 之後若新 runtime 失敗，不還原 snapshot，手動 dispatch PR3 release 並 `resume-crawler`。
- **目前差距**（010 seed 已於 `22bebf5` 補上；011 seed、contract allowance、gate 7 preflight 已於 M3 補上）：`deploy/migration-test/seeds/` 已有 010 與 011 的 seed；compat 的 runtime smoke 依 I5 只是 INFO，無法證明「PR3 runtime 在 011 上可運作」與 manual recovery compatibility；runbook 沒有 010／011 專屬的恢復步驟，也沒有「新版寫入 `ISBN` 後舊版 crawler 必須保持停用」的操作提示。
- **方向**：PR2 新增 010 的 seed（含 v0.0.4 形式的 `source_type`-only 資料，驗證 trigger 回填）；PR4 新增 011 的 seed、ISBN conversion preflight（dry-run SELECT）與 manual recovery compatibility 測試（[test-plan §7](../../Docs/testing/test-plan.md) #13、#14、#20），並在 runbook 補 011 gate checklist 與恢復程序。
- **前置決策**：011 的部署時間與 rollback window 的關閉由使用者決定（L4）。
- **驗收條件**：010 與 011 的 compat 在 CI 通過；gate checklist 每項有可檢查的證據；PR3 Web／crawler 在 011 的 smoke 通過且不需 snapshot restore。
- **測試入口**：010 seed 已建（`deploy/migration-test/seeds/20261024160045_MultiSourceCatalog.sql`）；011 seed、preflight（`deploy/migration-test/preflight/`）與 contract allowance（`deploy/migration-test/contract/`）已於 M3 建立。recovery compat 已由 PR4 M4 在本機建立（`prev-release-on-contract.sh`，test-plan §7 #13、#14），尚未納入 CI；是否納入 CI 待決策。

### DEP-B19 compat contract allowance 與 gate 9 script 的結構整理

- **狀態**：改善提案（#120 兩軸 review 的判斷題，未在 PR4 處理）。
- **現況**：`deploy/migration-test/compat.sh` 在 `load_contract_allowances`、`snapshot_contract_tables`、`check_data_preserved` 三處各自解析 `allow.tsv`；`check_data_preserved` 同時處理一般、drop-column、rewrite 三組規則。`prev-release-on-contract.sh` 的 `expected_checks=15`、crawler 6 項、seed 4 本書與 `prev_crawler_driver.py`、011 seed 重複；Detail 檢查與 `expect_body` 邏輯重複。
- **方向**：在 `deploy/lib/contract_allowance.sh` 提供列出 rewrite 表、drop 欄位的 helper，三處共用；把 `check_data_preserved` 的 allowance 分支抽成函式；gate 9 的檢查數由 driver 回報，不在 script 寫死。
- **驗收條件**：`deploy/tests` 的 allowance 測試與 gate 9 整合測試不變且通過；shellcheck 通過。

## 3. 已處理（PR #107）

| 項目 | 處理 |
|---|---|
| DEP-B16：runbook 與程式、營運狀態不同步（C1、C2、C5、C6） | 已於 PR #107 修正：C1 健康探測的次數、逾時與間隔；C2 exit 6 與 `run-crawler.sh` 退出碼；C5 營運觀察證據（標示為營運觀察，非自動化測試）；C6 版本指引（移除過時的「發布 v0.0.2」建議）。同次 PR 也對齊了 C3、C4、C7 的文件說明，新的程式問題分別列為 DEP-B17、DEP-B08、DEP-B15 |

## 4. 已列為歷史、不列為待辦的項目

| 項目 | 處理 |
|---|---|
| pg_dump 失敗或空輸出被當成相等（`faf6d2b`） | 已修正，`test_failing_pg_dump_is_an_error_with_its_stderr` 等覆蓋 |
| `sudo` 的 `env_keep` 行（`0bcbfe7`、`6106d82`） | 文件與錯誤訊息已修正；營運觀察已確認 plan key 的 `status 1-1` 回傳 `not-started`（runbook §7.2 #1，PR #107 同步） |
| 健康檢查的 urllib 預設 User-Agent（`2fb5e27`） | 程式已修正；在 production 的生效列為 DEP-B02 |
| `DB_CA_BUNDLE` 的容器權限與 `install -d` 事件（`439b80e`、`222c7ce`） | 功能與文件已修正；程式未檢查目錄權限列為 DEP-B15 |
| `CRAWLER_ENABLED` 不被 `run-crawler.sh` 支援（`3637cff`） | 已實作；`v0.0.2` 起包含。停用本身列為 DEP-B01 |

## 5. 不列為待辦的候選項目

- **Migration 的交易邊界**：CI 的 `check_migrations.py` 禁止 `suppressTransaction` 與 `CONCURRENTLY`（已有測試），不是缺口。
- **compat 的 runtime smoke**：依 test-plan §6.1 只供參考，不阻擋部署，這是規格而非缺陷。
- **history 的 pipe 限制**：已有測試，不是缺口。
