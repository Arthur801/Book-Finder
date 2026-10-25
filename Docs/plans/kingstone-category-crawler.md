# Kingstone Crawler — v10 精簡實作計畫

> Baseline：原始 v10 為 `main @ cfb606eb15f23e781d48ffe381887057cd243dfb`；2026-10-25 依 `main @ de52793` 現況核對並修正（見文末「現況核對紀錄」）。
> 來源：使用者提供的 Final Accepted Implementation Plan v10；本文件合併重複說明，保留執行契約。取代先前的修訂版（baseline `ee29e02`，留在 git 歷史）。
> **計畫可開始 E0；程式實作待 E0 通過；production activation 待 P1–P5。**
> 本文件是實作計畫，不代表功能已實作、測試已通過或取得 production 授權。E0 的有限真站抓取已於 2026-10-25 由使用者授權（§2）。

## 1. 目標、現況與範圍

完成金石堂分類 discovery→detail→Catalog ingestion；來源 acquisition／parsing 集中於 `crawler/kingstone/`，共用 identity、ISBN、NULL enrichment、transaction 與 retry recovery，不複製 core。

Baseline：PR3（#119）與 PR4（#123）已合併，KINGSTONE registry row 預設 disabled。**migration 011 已在 repo，production 也已套用（v0.0.7）**，schema 上已能寫入 KINGSTONE；本次不實作 migration，金石堂 runtime 仍須做 post-011 schema read-only preflight（§8）。Python persistence 已只寫 `source_code`、ISBN 只查 `ISBN` 型別，但仍依賴 module-global `PROVIDER=BOOKS_COM_TW`（`crawler/books_crawler/db.py`、`ledger.py`），需改為明確傳入 provider。現行 authority 依 AGENTS.md §3.2 為 module-local docs（`crawler/docs/*`、`deploy/docs/*`）；root `Docs/`（含 `Docs/data/data-model.md`、`Docs/modules/crawler.md`）是 archived reference，只作歷史背景。

In scope：provider-neutral core、金石堂 adapter／CLI、持久化分類進度與 repair queue、有限 acquisition、Docker／runner、writer fencing、report／alert hook、離線與 DB 測試、文件。

Out of scope：DDL／schema、金石堂 Bestseller、Offer／價格／庫存、登入與跨 run cookies、CAPTCHA 代解／proxy rotation、平行爬取、item-level detail queue、mutation receipt／audit manifest／GC、自動資料回滾、新雲端服務。首次 canary 不啟用自動排程。

## 2. E0 — Source evidence 與 authority gate

在 parser／runtime 實作前，先完成 evidence-only phase：

1. 收集去識別 fixtures：category root／child／terminal／multi-page／empty、product card／detail、代表性 HTTP error；challenge 僅在實際觀察到時收錄。
2. 由 committed fixtures 凍結 origins、category／product identity 與 URL grammar、external ID、pagination、encoding、required fields、challenge／error classification；不自行發明 selector 或 URL 規則。
3. 選擇 `HTTP_ONLY` 或 `HTTP_PLUS_BROWSER`：只有證據顯示一般 HTTP 無法可靠取得必要內容時才加入 browser。
4. 凍結 bounds，寫進 `crawler/docs/` 五份文件（architecture、workflow-diagram、test-suite、backlog、update-history）；影響 runner／host 的部分同步 `deploy/docs/`。不更新 archived root `Docs/`。

**Exit：** fixtures 對 identity／navigation 具有單一可測解釋，contract review 通過；自動測試不需真站。取得 fixture 的真實抓取仍須當次授權；2026-10-25 已授權 E0 有限抓取：循序請求、總數上限約 60 次、每次請求（含重試）前隨機等待 3～30 秒、不登入、不代解 CAPTCHA、不用 proxy。

## 3. 模組與型別邊界

```text
kingstone acquisition / parser / traversal
                  ↓ typed contracts
catalog_core identity / normalization / service / persistence
                  ↓
PostgreSQL item transaction
```

| Module | 責任 |
|---|---|
| `crawler/catalog_core/{models,identity,normalize,persistence,service}.py` | provider、Source identity matrix、ISBN、CatalogResolution、NULL-only enrichment、touch、transaction、commit-uncertain recovery |
| `crawler/books_crawler/` | 博客來 discovery／parser、RunLedger、Bestseller、來源 response classification；改用共用 core，外部行為不變 |
| `crawler/kingstone/{__main__,models,adapter,discovery,parser,acquisition,state,run}.py` | 金石堂 URL／category graph／pagination／card／detail／classification、traversal、report；不含 Catalog SQL |
| runner／deployment | shared locks、writer fencing、watchdog、mounts、alert delivery |

共用 persistence 明確接收 provider／external_id，不讀 module-global `PROVIDER`。Provider HTML 不穿過 core interface；category metadata 僅屬 observation/job context。

- `ProviderCode`：至少 BOOKS_COM_TW、KINGSTONE。
- `DiscoveredItem`：provider、canonical source URL、external_id、category_id context。
- `SourceBookDraft`：provider／URL／external_id、title、optional publisher／日期與精度／language／description／目錄／頁數／thumbnail、identifiers／contributors／subjects。

## 4. Catalog、交易與 replay

先依既有 matrix 同查 provider＋external_id／URL：Existing→touch、不抓 detail；New→detail、normalize、所有 ISBN 查 distinct Books。

| ISBN 命中 | `normal` | `new-books-only`（僅 canary） |
|---|---|---|
| 0／無 ISBN | 建 Book＋Source | 同左 |
| 1 | 附加 Source、只補 NULL；缺 AUTHOR 才補 AUTHOR，補 identifiers／來源 subjects | `POLICY_SKIPPED_EXISTING_BOOK`；不建 Source、不 enrichment |
| ≥2 | 新建 Book＋Source，不改 ambiguous Books | 同左 |

每個 New Source 的 Book／Source／補值／identifiers／contributors／subjects 在**同一 transaction**；commit 完整落地、rollback 零半套 mutation。Existing touch 獨立，原子執行 `last_seen_at=max(current, observed_at)`，確認恰為預期 provider Source。測正向、時鐘倒退、重複 touch、uncertain ACK。現行 `db.touch_source` 是 `SET last_seen_at = now WHERE id = …`（不單調、不檢查 provider），改共用 core 後博客來的 touch 也變單調；這是 Books 唯一的行為變更，須同步更新 `crawler/docs/architecture.md`、`workflow-diagram.md` 與 Books 測試。

Commit 結果不確定時丟棄／重連 connection，**下次寫入前重新 resolve identity，不盲目重播 transaction**：

- Existing：不重播，回報 `RECOVERED_COMMIT`；不要求重建原 IMPORTED／ISBN_ATTACHED 計數。
- New：依 shared recovery／transaction identity 保護與剩餘 budget 有限重試。
- Conflict／查詢不可用：不再寫該 item，category incomplete。

Crash 在 DB commit 後、state checkpoint 前：同分類 replay，再由 identity 去重。state 可落後已 commit effects，不可提前宣稱 coverage 完成；不建立跨資源 receipt log，也不承諾逐欄位 forensic rollback。

## 5. Acquisition 與安全

- HTTP：最多3次、request timeout30秒、backoff最多60秒、Retry-After最多120秒、response最多5MiB。retry限 timeout／connection reset／429／500／502／503／504；所有等待受 soft budget 限制。
- Pacing：循序請求，請求之間的隨機等待由 E0 依實際回應（429、Retry-After、challenge）凍結並寫入 `crawler/docs/architecture.md`；E0 抓取期間先沿用博客來的 3～30 秒（`crawler/docs/architecture.md`、`RequestPacer`）。凍結值決定每個 soft budget 能涵蓋的請求數，category bounds 依此評估。
- Retry-After 超出可等待範圍時不得提早重送；以 defer／本次 incomplete 處理。以 fake clock 驗證 delay 與 budget。
- 每次 navigation 前檢查 HTTPS、fixture-approved origins、無 userinfo／IP literal、核准 path grammar；redirect後再驗 final URL，off-origin拒絕，無任意 HTML URL acquisition。
- Browser 僅於 E0 選定：每 invocation 一個 context、無跨 run state／登入／私人帳號、non-root、TLS on、有限 CPU／memory／PID；無持鎖期間的人工作業。
- 互動 CAPTCHA→`CAPTCHA_REQUIRED`、category incomplete／repair，依 terminal matrix 決定 run；不新增 cookie subsystem。
- `HTTP_ONLY` 不新增 Playwright production dependency；browser方案須凍結 Playwright／Chromium／OS packages／limits，通過離線 local startup smoke，博客來 image 不受影響。
- 不輸出 DB URL／cookies／secret；只用必要 Catalog DB 權限，無 DDL。診斷有限額，state 與 diagnostics 分開 mount。

## 6. Sweep、state 與 repair

無 ACTIVE sweep 才執行 bounded target discovery：記憶體內建立完整 target set、偵測 category cycles、驗 identity、deterministic sort；完整成功才發布 snapshot。失敗不發布半套 sweep、不由該 target set 寫 Catalog。

Bounds：category nodes1000、depth10、pages/category100。

State host path：`/var/lib/book-finder/crawler/state/kingstone/state.json`；container mount：`/app/crawler/state/`，UID10001、restricted permissions、非 symlink、跨 `--rm` 保留。

```text
v1: state_version, revision, provider_code=KINGSTONE,
    coverage_config, targets[], target_set_fingerprint,
    sweep_id, sweep_status=ACTIVE|COMPLETED, next_primary_index,
    repair_queue[], started_at, updated_at, completed_at?
```

無 `active_work`。ACTIVE sweep沿用已持久化 targets／coverage_config；host coverage設定變更下個 sweep 才生效。明確 abandon須 KINGSTONE disabled、持鎖、確認零 writer並記 reason；operator不手改 JSON。

State寫入：canonical serialize→temp→fsync file→atomic replace→fsync directory；同一run.lock下以expected revision N發布N+1。corrupt／unknown version／conflict→FAILED，不自動 reset、不再 acquisition／mutation。checkpoint IO失敗立即終止；舊state可能使分類 replay。

### PRIMARY

`next_primary_index`唯一語意：尚未達 durable safe boundary 的第一個target index，初始0。

- configured coverage完整才 FULL_SUCCESS。
- page／detail failure、CAPTCHA、category內budget interruption→INCOMPLETE。
- FULL_SUCCESS，或 incomplete＋repair entry，須與index=i+1在同次durable checkpoint發布。
- checkpoint前crash→index不變、分類replay；不得因單條SQL成功推進。

### REPAIR

Entry：repair_id、category_id、target fingerprint、attempt_count、budget_interrupt_count、last_error、created_at／last_attempted_at。logical unique key為(category_id, fingerprint)，重複失敗合併。

每次repair先取head→attempt+1→移tail→durable write→外部作業；成功移除，失敗更新reason留tail，避免crash讓同分類永久佔head。repair與primary各有bounded phase。

當index==target_count且repair空，durably標COMPLETED；本invocation不開下一sweep，下一次再discover。

## 7. 設定、budget 與 terminal status

`crawler.conf`為金石堂設定來源；只在kingstone mode驗證，不讓Books新增必填金石堂設定。

| Key | Default |
|---|---|
| `KINGSTONE_WRITE_POLICY` | `new-books-only` |
| `KINGSTONE_SOFT_RUN_BUDGET_SECONDS` | 3300 |
| `KINGSTONE_REPAIR_BUDGET_SECONDS` | 600 |
| `CRAWLER_RUN_HARD_LIMIT_SECONDS` | 3600 |
| `KINGSTONE_HTTP_TIMEOUT_SECONDS` / `KINGSTONE_HTTP_MAX_ATTEMPTS` | 30 / 3 |
| `KINGSTONE_BROWSER_TIMEOUT_SECONDS` / `KINGSTONE_BROWSER_MAX_ATTEMPTS` | 45 / 2，僅browser方案 |
| `KINGSTONE_MAX_RESPONSE_BYTES` / `KINGSTONE_MAX_DOM_BYTES` | 5MiB / 10MiB |
| `KINGSTONE_DIAGNOSTIC_MAX_BYTES` | 2MiB |
| `KINGSTONE_REPAIR_ALERT_AGE_HOURS` | 24 |
| `CRAWLER_ALERT_COMMAND` | dev可unset；host設定 |

外部工作前驗證：repair<soft<hard、durations/counts>0、bytes finite。attempt開始前budget不足：不改state、不發request、結束phase；分類間到期乾淨停止、不產repair。分類內到期：完成／取消當前bounded operation→repair＋checkpoint→停該phase。

一個集中函式決定terminal：

| Status | 條件 | Exit |
|---|---|---|
| FAILED | fatal config／registry／schema／state／discovery／security contract／required-browser failure、watchdog／orphan，或work expected但零useful progress | 1；config／provider-disabled維持2 |
| PARTIAL_SUCCESS | 無fatal、有useful progress、仍有repair／category failure／CAPTCHA／中途budget coverage未完成 | 0 |
| SUCCESS | sweep完成；或無未解repair debt且分類間正常bounded continuation；或new-books-only合法全policy-skip、無acquisition/state error | 0 |

`new-books-only`可零mutation但不可作為promotion到normal的證據；report須區分policy skip與真正零進度。

## 8. Runner、writer fencing 與報告

Invocation order：config→run.lock→maintenance shared lock／既有deployment gate→orphan check→DB secret→provider enabled→post-011 schema read-only preflight→state→必要時discover／發布sweep→REPAIR→PRIMARY→terminal report→alert delivery／container終止確認→放鎖。

provider／schema／state驗證前無Catalog mutation；schema preflight失敗為`SCHEMA_PREREQUISITE_MISSING`、config failure、零HTTP／mutation。provider預設disabled。

待決（Phase 6）：runner 現有 `CRAWLER_ENABLED` 是整台 host 的開關，production 目前為 `false`（博客來封鎖 EC2，`crawler/docs/backlog.md` CB-03）；金石堂經 runner 也會被它擋下。Phase 6 須決定金石堂是否使用獨立的 host 開關，並同步 `crawler.conf.example`、deployment。

- runner新增`kingstone`；Books沿用`CRAWLER_IMAGE`，金石堂用`KINGSTONE_CRAWLER_IMAGE`，可為HTTP-only或browser image。
- 所有provider共享run.lock與maintenance shared lock；container固定name=`book-finder-crawler-active`、label=`com.bookfinder.role=catalog-crawler`、cidfile與mode/provider labels。
- running／restarting／paused writer阻擋start；exited／dead deterministic container安全清理後再啟動。
- migration取maintenance exclusive lock，檢查deterministic writer及legacy candidates；shared/exclusive lock避免inspect/start race。
- hard limit：stop實際container→bounded grace→必要時kill→inspect確認不再running→放鎖。無法證明writer終止→`ORPHAN_WRITER`，未來crawler／migration皆fail closed；不只kill docker client。

每run一份sanitized terminal JSON，stdout＋state目錄atomic `last-run.json`：run/provider/status/exit；sweep/index/target count；repair backlog/oldest age；discovered/details；existing/new Source、policy-skip、mutation/recovered commit；HTTP attempts/failures、browser escalation/CAPTCHA；zero_progress_reason、alert_reasons。

Host alert command為absolute root-owned executable，只收sanitized event JSON path，不收secret。FAILED／NO_BOOK_ACQUIRED／orphan／state／schema／required-browser問題、CAPTCHA threshold、repair age、normal反覆零ingestion均須觸發。production須注入測試事件並由named owner確認收到；僅log不足，delivery失敗阻擋PRODUCTION_READY。

## 9. 實作順序與驗證

| Phase | 工作與完成條件 |
|---|---|
| 0 Evidence | fixtures→source contract／strategy／bounds→authority；E0 PASS才開程式實作 |
| 1 Core | provider-neutral types／identity／normalize／persistence、monotonic touch、改Books caller；除 touch 單調化外 Books 行為不變；全Books regression PASS |
| 2 Adapter | 金石堂URL、category／detail parser；fixture/unit/contract全離線 |
| 3 Acquisition | HTTP bounds／URL security／選定的browser；failure suite PASS |
| 4 Traversal | complete-target publication、state v1／revision、index、repair fairness、budget；state fault suite PASS |
| 5 Ingestion | composition、雙policy、commit recovery；post-011真DB integration／atomicity／replay／Bestseller protection PASS |
| 6 Operations | runner mode／mount／container identity／watchdog／legacy orphan guard／report／alerts；deploy tests PASS |
| 7 Acceptance | 全金石堂、必要DB零skip、Books、Docker smoke與docs；標記IMPLEMENTATION_VERIFIED |

自動測試不連真站；HTTP／clock／sleep可fake，DB用EF schema的disposable PostgreSQL，browser用local fixtures。

| Acceptance／failure | 必測行為 |
|---|---|
| discovery→detail→DB | 真fixture＋真parser＋真DB全流程；category graph/cycle/order/pagination/empty／encoding／URL-ID／classification |
| HTTP／browser | retry／Retry-After／budget／oversize／off-origin／browser unavailable／DOM ceiling／CAPTCHA／無跨run session |
| shared core／DB | 兩provider共用E/U完整matrix、0／1／≥2 ISBN、無ISBN、NULL／AUTHOR／identifiers／subjects／monotonic touch |
| Atomicity | Book／Source／fill／identifier／contributor／subject後與commit前注入失敗，零半套mutation |
| Uncertain commit／replay | 真commit＋ACK lost不二次mutation；真rollback可bounded retry；re-resolve unavailable不blind write；第二run Source不增加、既有detail=0 |
| State／budget | discovery crash、checkpoint前crash、queue＋index原子發布、repair rotation/crash/success、fsync/conflict/corrupt/version/config change、completion/rollover、各phase前中後budget |
| Host stop | watchdog stop/kill、精確container inspect、orphan blocking、migration fence、durable mounts |
| Books／Bestseller | daily/pages/first_book原contract與report/retry不變；Kingstone三種status前後Bestseller邏輯一致 |
| Docs | 五份crawler/docs與deploy/docs的module／CLI／config／state/status／path一致 |

## 10. Production gates 與 rollback

Production保持disabled，全部通過才activation：

- **P1**：011已部署（v0.0.7，2026-10-25 已完成）；剩金石堂 runtime 的 schema preflight 在 production 通過。
- **P2**：crawler只有必要Catalog read/write、無DDL權限。
- **P3**：production-like host驗證UID／state mount／Docker limits／watchdog／fencing。
- **P4**：注入critical event，named owner實際收到alert。
- **P5**：當次授權後controlled enable KINGSTONE，以new-books-only手動canary；需discovered>0、實際new Source、無duplicate／Bestseller／state/deploy異常。再controlled normal，使用合適資料驗證exact-one ISBN attach／NULL enrichment；全部skip不算promotion證據。手動 canary 最長佔用 run.lock 3600 秒，須避開博客來 cron（daily 20:00 UTC、pages 21:00 UTC）；金石堂若同樣封鎖 EC2，依 rollback 停用、不採規避技術。

首canary無自動schedule；normal驗證後才另處理排程啟用。

Rollback：disable KINGSTONE→確認writer停止→必要時回復runner/image tuple；Books維持既有enabled狀態。本次不做schema rollback；保留state與已commit Catalog，不自動反轉NULL enrichment。資料修復另行調查、比對backup與當前資料，禁止blind rollback。

**設計原則：state可以落後DB effects；推進時必須已完成coverage，或已durably排入repair。Crash依靠replay＋Source identity idempotency，不新增receipt／audit subsystem。**

## 現況核對紀錄（2026-10-25，`main @ de52793`）

| # | 核對結果 | 處理 |
|---|---|---|
| D1 | 011 已合併並部署到 production（v0.0.7），原 baseline「011 是寫入前置」過時 | 修正 §1、§10 P1 |
| D2 | `db.py`、`ledger.py` 仍用 module-global `PROVIDER` | 計畫正確，Phase 1 照做 |
| D3 | `touch_source` 不單調、不檢查 provider | §4 註明 Books 行為變更與文件同步 |
| D4 | v10 沒定義金石堂請求間隔 | §5 加 Pacing，E0 凍結 |
| D5 | 新舊兩份計畫並存 | 本文件取代舊版，刪除根目錄副本 |
| D6 | runner 尚無 container name／label／cidfile／hard limit | 與計畫一致，屬 Phase 6 新增 |
| D7 | 共用 run.lock 符合 data-model §7.5；長 run 會讓博客來 cron 排隊 | §10 P5 註明避開時段 |
| D8 | archived `Docs/data/data-model.md` §7.2 的 ISBN 查詢已註明 011 後只查 `ISBN`，與程式一致 | 無需處理 |
| D10 | AGENTS.md 已改為 module-local docs 為 authority（PR #126），v10 原本要求更新 root `Docs/` 規格 | §1、§2、§4、§5 改寫為 `crawler/docs/`、`deploy/docs/` |
| D9 | host `CRAWLER_ENABLED` 為全域開關，production 為 `false` | §8 列為 Phase 6 待決 |
