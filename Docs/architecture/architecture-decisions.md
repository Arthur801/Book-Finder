# Architecture Decisions

> Path: `Docs/architecture/architecture-decisions.md`
> Authority: 已決定的架構取捨。每條決策一節；推翻時新增一節並將舊節標為 Superseded，不直接改寫歷史。

---

## ADR-001 — Modular Monolith，不拆微服務

**Status**: Accepted

單一產品領域、單一主要資料庫、個人專案規模，拆服務只會帶來 service discovery、服務間認證、分散式交易與多服務部署成本，沒有對應收益。因此 Web 採單一 ASP.NET Core MVC deployable，內部依業務能力（Identity、Catalog、Bestseller、Recommendation、Library）分模組，模組間以 Application 層介面互動。

- **Alternatives**: 依模組拆微服務；AI Recommendation 獨立服務。
- **Trade-offs**: 無法獨立擴縮模組；Web 單點故障。換得部署與除錯簡單。
- **Migration impact**: 若日後拆分，以既有模組邊界為切點；模組間不得直接存取彼此的資料表以保留此路徑。

---

## ADR-002 — Python crawler 直接寫共用 PostgreSQL，schema 只由 EF Core 管理

**Status**: Accepted

Crawler 以 Python 撰寫並作為每日 one-shot batch，直接寫入 Web 使用的同一個 PostgreSQL，而非透過 Web API。Schema 唯一擁有者是 EF Core migration；crawler 不執行 DDL，只寫 Catalog 與 Bestseller 相關資料表。

- **Alternatives**: Crawler 呼叫 Web 的內部 ingest API；crawler 自有資料庫再同步。
- **Trade-offs**: 兩種語言共用同一份 schema 契約，schema 變更須同步檢查 crawler；換得不需為 crawler 開 Web 寫入端點與服務間認證。
- **Migration impact**: 任何 Catalog / Bestseller schema 變更必須先更新 `Docs/data/data-model.md` 並驗證 crawler。

---

## ADR-003 — Embedding 與所有 OpenAI 呼叫只在 C# Web Application

**Status**: Accepted

OpenAI 整合（需求解析、embedding、排序、推薦理由、Book AI Profile）集中於 C# Recommendation 模組。Crawler 新增的 Book 沒有 embedding，由 C# 端補齊。

- **Alternatives**: Crawler 寫入新書時一併產生 embedding。
- **Trade-offs**: 新書在補齊前無法被向量檢索；換得 OpenAI 金鑰、模型版本與 prompt 只存在一處，crawler 不需持有 AI secrets。
- **Migration impact**: 若改由 crawler 產生 embedding，須將 embedding model 與維度變成跨語言共享契約。

---

## ADR-004 — JWT 以 HttpOnly cookie 傳遞

**Status**: Accepted

前端為 Razor server-rendered 頁面，一般頁面導覽不會攜帶 `Authorization` header。JWT 由伺服器簽發並存放於 `HttpOnly`、`Secure`、`SameSite=Lax` cookie，JWT Bearer middleware 從 cookie 讀取；所有改變狀態的請求須通過 ASP.NET Core antiforgery 驗證。

- **Alternatives**: JWT 存於 localStorage 並以 `Authorization` header 傳遞。
- **Trade-offs**: 需要 CSRF 防護；換得 JavaScript 無法讀取 token（降低 XSS 竊取風險），且 Razor 頁面導覽可直接取得使用者身分。
- **Migration impact**: 若日後提供給非瀏覽器 client 的 API，可另外接受 `Authorization` header，不影響 cookie 流程。

---

## ADR-005 — 使用 process-local `IMemoryCache`，不引入 Redis

**Status**: Accepted

MVP 只有單一 Web instance。Cache 只存可由 PostgreSQL 重建的唯讀資料（例如目前 Bestseller、Book detail），restart 清空可接受；不作為 source of truth。Crawler 與 Web 之間沒有 invalidation 通道，以短 TTL 讓 Bestseller cache 自然過期。

- **Alternatives**: Redis / ElastiCache。
- **Trade-offs**: 多 instance 時 cache 不一致；換得不多一個基礎服務與成本。
- **Migration impact**: 水平擴充 Web 前須改為分散式 cache。

---

## ADR-006 — CD：tag 觸發、核准後以 SSH forced command 部署到單台 EC2

**Status**: Accepted

**Context**：web 原本以 systemd 原生執行（`deployment.md` §3.1），crawler 以 Docker Hub image 加 cron 執行。產品範圍（`product-requirements.md` §2）原本將 CD 列為延後。使用者決定：web 改為 container、以 SSH key 連到 EC2、推送 `v*` tag 觸發、經 production 環境核准後部署，且 migration 併入同一流程。部署目標只有一台 EC2，沒有 staging。

**Decision**：
- 發布與部署分離。`v*` tag 觸發 CI 測試、建置 web 與 crawler image、attestation、發布 Immutable Release。部署以 `production` environment 的 required reviewer 核准。
- GitHub Actions 以 SSH 連到 EC2。兩組 key（plan 與 deploy）各自用 `authorized_keys` 的 forced command 限制：plan key 只能執行 plan 與 status，deploy key 可以執行 deploy 與 status。
- 狀態機是 EC2 上的 host 程式（`deploy/host/`），而不是 CI 的 shell 腳本。它維護 `state.json`（目前 production 狀態）與 `history.jsonl`（append-only 的結果紀錄），並以 transient systemd unit 執行，結果以 history 為準。
- Migration 併入流程。forward 時先 pause crawler、取得 db-maintenance lock、建立 snapshot、設 dirty，再執行 image 內的 `efbundle`。失敗時 schema 保持 dirty，只能人工解除（N2）。
- Image 來自 GHCR，以 digest 指定。Release metadata 與 SQL 是 Immutable Release 的 asset，host 不執行 release 內的程式來讀取 metadata。
- 首次從 systemd 切換到 Docker 是獨立的 L4 操作：`bootstrap-state`（人工建立 state）、再以 `cutover` dispatch。
- 操作細節與人工程序見 `deploy/README.md`。

**Alternatives considered**：
- **OIDC 加 SSM Run Command（取代 SSH）**：不需要長期 SSH key，審計更完整。但需要 IAM role、SSM agent 與 trust policy 的設定，且 host 狀態機的 transient unit、forced command 與 history 模型都要重新設計。本次選擇 SSH，以 forced command 限制權限。之後若要改用 SSM，host 程式可以保留，只換傳輸層。
- **Docker Hub（取代 GHCR）**：與既有 crawler 流程一致。但 GitHub Actions 的 `GITHUB_TOKEN` 可以直接推送 GHCR 並產生 attestation，不需要另外的 Docker Hub 帳號與 token。
- **nginx 放進 container（取代 host nginx）**：部署單元更一致。但 TLS 憑證由 host 上的 `acme.sh` 管理，且 nginx 設定需要和 web 容器的 `KnownNetworks` 協調。本次保留 host nginx，web 只綁定 `127.0.0.1:5000`。
- **kit 放進 image（取代 host-only 邏輯）**：讓 host 只負責呼叫。但 host 的決策（state、lock、回滾）必須在 image 之外才能在 web 壞掉時仍然運作，所以狀態機留在 host，只有 metadata 與 compose 檔隨 release 發布。

**Trade-offs**：
- 單台 EC2 是單點故障，部署期間有短暫的停機（切換 container）。換得部署與除錯簡單。
- SSH key 是長期憑證。以 forced command、key-only 與 `restrict` 限制，但 sudo 環境變數等細節必須在 EC2 上驗證（見 `deploy/README.md` §7）。
- Migration 失敗後沒有自動回滾（I5），需要人工介入。換得不會在資料已變更時，把舊版程式套用到新 schema 上。
- Immutable Release 讓 tag 名稱不能重用，發布錯誤只能發新的 patch。

**Migration impact**：
- 第一次切換需要 `bootstrap-state` 與 `cutover`（L4）。之後的 host 程式升級經 `install-host`，並受 `HOST_API_RANGE` 的相容範圍限制（N4）。
- 任何改變 state.json 格式、history 格式或 exit code 的變更，都必須更新本 ADR 與 `deploy/README.md`。

**Invariants**（每條的理由是一行摘要；設計過程與 review 紀錄見 `Docs/Implementation-Report/issue-92-cd.md`）：

| # | 內容 | 理由 |
|---|---|---|
| I1 | state 分為 runtime 與 schema，兩者都以實際狀態（`docker inspect`、`systemctl`、`__EFMigrationsHistory`）為準，CAS 檢查 revision、runtime、schema | 不能只相信 state 檔的內容 |
| I2 | 第一次 cutover 只接受 in-sync，失敗時可以 `systemctl start` 回到舊版 | 切換前後的 DB 與程式必須一致 |
| I3 | migration 前設 dirty；dirty 期間 plan、deploy、crawler 都拒絕 | 中斷的 migration 不能被當成完成 |
| I4 | chain 只接受兩種前綴關係，其他都是 divergent | 歷史分岔時不能猜測要執行什麼 |
| I5 | 套用 migration 後禁止自動回滾 | 舊版程式可能不認識新 schema |
| I6 | 回滾使用舊 release 的 image 加上 compose，先驗證 compose 雜湊；清理時保留被 state 引用的 image 與目錄 | 回滾必須是當初發布的那一套 |
| I7 | 沿用既有 image 前必須通過 `gh attestation verify` | label 不能當作來源證明 |
| I8 | plan 只讀 allowlist 的 metadata，用 `docker create` 加不帶 `-L` 的 `docker cp`，只接受一般檔案，絕不執行 release 的程式 | plan 不能讓 release 內容在 host 上執行 |
| S1 | 併入 N7：transient unit 不使用 `--pipe`（v5 合併，編號保留） | 避免 SSH 斷線時 unit 被中止 |
| S2 | 併入 I6：GC 保留被 state 引用的 image 與目錄（v5 合併，編號保留） | 回滾與 schema rebuild 需要的 image 不能被清除 |
| S3 | 同 I8（metadata 讀取規則） | 同上 |
| S4 | state 一律 atomic write，每次寫入遞增 revision | 寫入中斷不能留下半個 state |
| S5 | 完成 cutover 後，任何模式遇到 systemd 都視為 drift | 避免兩個 web 搶同一個埠 |
| S6 | target 一律要通過 forward smoke，包括 schema-ahead | 沒有 override 的安全檢查 |
| S7 | schema-ahead 部署不改動 crawler；`crawler_digest` 必須等於 state | 舊版 crawler 在較新 schema 上的行為無法證明 |
| S8 | 人工指令採用與 deploy 相同的 started、completed 協定；只有 started 時為 indeterminate | 人工操作中斷時不能假裝完成 |
| S9 | host 程式放在 `host-versions/<id>/`，`/opt/book-finder/host` 是 symlink，以 rename 原子替換 | 任何時間點 crash 都指向完整的一套程式 |
| S10 | 人工指令失敗時，只有能證明「完全沒改變」才能寫 failed | 未知結果不能被記成失敗 |
| S11 | crawler 自己記錄來源（digest、雜湊、source_release、paused），與 web runtime 分開 | web 與 crawler 的版本可以不同步 |
| N1 | schema 保存能重建它的 bundle digest（`schema.rebuild`），compat 用它重建，而非用目前的 runtime | 套用 migration 的版本與正在執行的版本可能不同 |
| N2 | dirty 不能靠讀 history 自動解除，只能人工 `reconcile-schema --mark-clean`（唯一的自動路徑是 efbundle 結束碼為 0 且 DB 與目標相符） | history 無法證明 DDL 與資料一致 |
| N3 | forward 期間 crawler 保持 paused；crawler 先拿 shared lock 再讀 state | 先讀再拿 lock 會有 TOCTOU |
| N4 | HOST_API 是相容範圍 `[min, max]`，`install-host` 在 current 或 previous 超出新範圍時拒絕 | 升級 host 後仍能回滾到舊 release |
| N5 | migration 身分以 immutable source hash 判定，SQL hash 只作 audit | EF 升級會改變產生的 SQL |
| N6 | 第一次 cutover 的 state 由人工 `bootstrap-state` 建立，CD 從不建立 state | 信任假設必須由人確認 |
| N7 | deploy 以 transient unit 執行，不用 `--pipe`；history 是結果的唯一來源，`indeterminate` 需要人工 `resolve-run` | SSH 斷線與 unit 被回收都不能改變結果 |
| N8 | pending SQL 來自 target 的 immutable release asset，runner 不重新產生 | 審閱的 SQL 必須與實際執行的 release 一致 |
