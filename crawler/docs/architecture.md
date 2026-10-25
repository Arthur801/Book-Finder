# Crawler 架構與選型

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。核心來源依原始基準靜態閱讀；host 另依上述 merge-target snapshot；本次未執行 build、測試、部署、外部服務或真實抓取。

[Crawler authority](../../Docs/modules/crawler.md)、[資料契約](../../Docs/data/data-model.md)、[部署](../../Docs/deployment/deployment.md)、[測試策略](../../Docs/testing/test-plan.md)、[名詞](../../CONTEXT.md)；ADR-002 見 [ADR](../../Docs/architecture/architecture-decisions.md)。分類榜補 Catalog，不是 Bestseller。

| 責任／來源 | caller、callee 與 contract |
|---|---|
| [cli](../books_crawler/cli.py) | env → 驗證 → RunDependencies → runner；exit 0 成功／部分成功、1 FAILED、2 設定錯誤；finally close |
| [run](../books_crawler/run.py) | orchestration；注入 fetcher、parser、connect、clock、sleep；outcome 送 ledger；`_resolve_row` 是 Books adapter：提供 `fetch_draft`（detail 抓取與 parse，限制級為不重試的 skip）、`on_attempt_failed`（既有 attempt 行）與 URL drift 的 WARNING，其餘交給 `catalog_core/service`；不再持有 identity、touch、寫入或重試規則 |
| [fetcher](../books_crawler/fetcher.py)、[browser](../books_crawler/browser.py) | get(url)→HTML、close；FetchError 與 BrowserUnavailableError 分類 |
| [parsers](../books_crawler/parsers.py)、[normalize](../books_crawler/normalize.py)、[urls](../books_crawler/urls.py) | HTML→RankingRow／BookDraft；URL canonicalization、語言、日期精度；博客來角色標籤表 `ROLE_MAP` 與 `map_contributor_role` 屬於本 adapter（ISBN 與共用 `clean_text`／`normalize_role_label` 見 catalog_core） |
| [catalog_core](../catalog_core/) | provider-neutral 型別（models）、Source identity 矩陣（identity）、ISBN 正規化與 provider-neutral 文字 helper（normalize：`clean_text`、`normalize_role_label`，不含任何 provider 的角色詞彙）、Unicode 15.1 表（unicode_15_1）；books_crawler 使用，之後 Kingstone 共用 |
| [catalog_core/page_list](../catalog_core/page_list.py) | 共用的 page list 檔案規則（`load_url_list`）：UTF-8 BOM、註解、空行、trim、依 provider canonical 值去重並保留首見順序、可選上限；非法行只報檔名與行號、不回顯內容；由各 provider 提供 canonicalize 與錯誤用語 |
| [identity](../catalog_core/identity.py) | Source identity 矩陣（data-model §7.3）；純函式，DB 查詢由 `catalog_core/persistence` 提供 |
| [ledger](../books_crawler/ledger.py) | CatalogResolution→Catalog counts；RunLedger 再決定 RankingDecision、streak、snapshot、status；PagesLedger 只用 CatalogResolution；無 DB |
| [catalog_core/persistence](../catalog_core/persistence.py) | provider-neutral 持久化，每個函式明確接收 `provider`（無模組層級 PROVIDER）：`connect`、`provider_enabled`、`resolve_source_identity`（依 provider 查 external_id 與 URL）、`touch_source`（`GREATEST(last_seen_at, now)`，限定該 provider 的 Source；不符合或不存在時拋 `SourceTouchConflict` 且不改任何列）、`find_books_by_isbn`、`persist_new_source`（寫入 `external_id`）；autocommit + 顯式交易，不做 DDL |
| [db](../books_crawler/db.py) | Books.com.tw 專屬：`replace_bestsellers`（榜單替換與 BOOKS_COM_TW ownership 驗證）與 `SnapshotValidationError`；不 re-export catalog_core 函式 |
| [catalog_core/session](../catalog_core/session.py) | `DatabaseSession`（自 `books_crawler/session.py` 移入，provider-neutral）：連線 closed／broken 時以注入的 connect 重連（§13.1）；每次 run 一個，無模組層級狀態 |
| [catalog_core/service](../catalog_core/service.py) | provider-neutral item 解析 `resolve_item`：identity → EXISTING 時 touch（不抓 detail）或 NEW 時 fetch／parse → ISBN 比對 → 寫入；CONFLICT 不抓不寫；共用 attempts、clock 與 retry 語意；寫入失敗後下一次先重新解析 identity（commit 不確定）：EXISTING 回報已 commit、NEW 繼續有限重試、CONFLICT 以 `source_identity_conflict` 結束，不再查 ISBN 或寫入（v11 計畫 §5；博客來沒有 `external_id`，不會走到 CONFLICT）。依賴 `CatalogStore` port（Protocol）與呼叫端注入的 `fetch_draft` callback；不含 HTML、ranking、psycopg 連線，也不記 log（由呼叫端依回傳值與 `on_attempt_failed` 記錄）。`ItemFailed.identity_warning` 攜帶 identity 的 warning，touch 失敗時仍可回報 |
| [catalog_core/store](../catalog_core/store.py) | `SessionCatalogStore`：以 `DatabaseSession` 與 `catalog_core/persistence` 實作 `CatalogStore`；每個方法在呼叫時取 `session.conn`（重連後仍有效）；`touch_source` 遇 `SourceTouchConflict` 回傳 `False`，其餘例外（含 `psycopg.Error`）原樣上拋給 service |
| [page_list](../books_crawler/page_list.py) | books.com.tw 專屬：環境變數與預設檔路徑、books.com.tw 分類榜 URL 規則；檔案規則委派給 `catalog_core/page_list`（行為與訊息不變）；非法／空清單在請求前失敗 |
| [kingstone/urls](../kingstone/urls.py) | 金石堂 URL grammar（CB-07）：`canonical_list_url`（`/book/<2–4 字母>/?dis=list&page=<n>[&sort=<key>]`，代碼轉小寫；`sort=sa_desc`（預設）canonical 時移除，與省略 sort 相同，其他 key 保留）、`detail_url`、`km_code_from_href`；純函式，不連線 |
| [kingstone/page_list](../kingstone/page_list.py) | 金石堂分類列表頁檔（`crawler/kingstone-pages.txt`，最多 200 個 URL）；檔案規則委派給 `catalog_core/page_list`；尚未接到任何入口 |
| [kingstone/models](../kingstone/models.py) | 金石堂 adapter 的資料型別：`ListedItem`、`ListPage`，以及 `KingstoneParseError`、`ProductNotFound`；尚無 parser（Phase 2 另行加入） |
| [Dockerfile](../Dockerfile) | Python 3.14、UID 10001、runtime 依賴與清單 |
| [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) | host scheduling、SSM secret retrieval、daily/pages serialization、DB maintenance coordination、deployment state gate、Docker execution 與 pages schedule state |

## 選型、替代與代價

| 面向 | 現行依據 | 替代差異（本次分析，非 ADR 決策） | 代價／維護 |
|---|---|---|---|
| one-shot batch | ADR-002 | queue／常駐 worker 需新服務與重送協定 | host 排程與觀測；無失敗佇列 |
| curl 預設、browser 診斷 | crawler §12 核准決策 | browser 資源較高；禁止自動切換規避 | preset 與 HTML fixtures 回歸 |
| 循序節流與三次 retry | §13／12 | 並行增加來源負載並改 contract | 執行可能久，避免 backoff 重複等待 |
| URL identity、ISBN 正規化與 distinct 比對 | §6、data-model §7 | 模糊書名合併有 edition 誤判風險，未授權 | 只依 ISBN 值比對；命中 1 本才附加，附加只補 NULL；≥2 本建立新 Book |
| 連線斷開時重連、寫入前重新解析 | §13.1、§6.1 | 讀取（既有 Source 的 SELECT）不重連，維持 run FAILED；重連後若前次寫入已 commit，回報 EXISTING，原 resolution 無法還原；touch 匹配不到本 provider 的 Source（`SourceTouchConflict`）不屬資料庫錯誤，不重試，直接以 `source_identity_conflict` 跳過 | 連線以 psycopg 的 closed／broken 判斷；寫入重試前先 resolve_source_identity，避免重複插入 |
| ISBN NFKC 固定 Unicode 15.1 | data-model §7.1 | 使用 runtime 的 Unicode 資料會讓 16.0 新增的分解改變 key | 未指派 code point 分段保留；`catalog_core/unicode_15_1.py` 由 `.github/scripts/unicode_tables.py` 產生（CI `--check`）；啟動時檢查 NFKC(U+1E030)，低於 15.0 即 exit 2 |
| 每書與榜單分開交易 | §9／14.4 | 全 run 長交易會擴大鎖與失敗損失 | FAILED 仍可累積 Catalog |
| EF 唯一 schema owner | data-model §9 | Python 自管 DDL 造成雙 truth | DB integration 須使用真 EF schema |
| 兩種 ledger | 程式可見選擇；歷史 refactor 可查 | 混合 I/O 會使政策更難隔離 | 不可把 daily 限制套到 pages |
| Docker＋host cron | [target deployment §8](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/deployment/deployment.md) | systemd timer／scheduler 需另案 | 依賴 image 預載、狀態檔、時區與權限 |
| Deployment/crawler coordination | crawler run.lock → maintenance shared lock → state gate；deploy migration 用同一 lock 的 exclusive mode | 先讀 state 再鎖會讓 pause／migration 與啟動交錯 | shared lock 持有至 Docker 完成；timeout exit 3、paused／dirty exit 6、state 無法解析 exit 2；state 缺少保留 pre-CD gate 行為 |

## 核心不變條件

以下條件原列於 root `AGENTS.md` §1.3（`f6ac094` 以前），AGENTS.md 改為 router 後改由本模組持有；修改任一條件須先提出規格變更，不可靜默改行為。

- 每日取得博客來中文書 7 日 TOP 100；排行榜頁必須完整解析 100 筆，否則整次失敗。
- 博客來 Book Source 以商品 URL 判斷是否已存在；新來源依正規化 ISBN 對到的 distinct Book 數量決定附加或建立新 Book。既有 Book 不因每日榜單刷新重新抓完整 metadata。
- New Source 詳細頁最多嘗試 3 次（含第一次），仍失敗則跳過；限制級會員頁直接跳過、不重試、不算錯誤。連續一般錯誤超過 20 本才中止；進入榜單（含重用）與限制級均重設計數，榜內重複算一般錯誤，非連續錯誤無累計上限。
- Bestseller 只保留最新榜單；rank 保留博客來原始排名，被跳過的排名缺號、不重新編號。新榜單尚未成功驗證前，不破壞上一份有效榜單。
- Fetcher 預設 curl_cffi Chrome fingerprint（使用者 2026-10-11 核准），循序請求，每次請求（含重試）隨機等待目標 3～30 秒；保留 Playwright 診斷入口。
- 抓取政策（#108，使用者決定）：browser stealth、`navigator.webdriver` 修補、CAPTCHA 代解或代理 IP 輪替可以使用；目前實作沒有這些功能，是否採用見 deploy DEP-B01。
- 測試不連線博客來；真實抓取驗證須有當前任務授權。

## 邊界與差距

只寫 books、book_sources、book_identifiers、book_contributors、book_subjects、bestsellers。SQL 參數化；不寫 users、AI／推薦資料、不做 DDL。簡介／目錄可存但只能供 AI，Web 必須排除公開回應；crawler 不提供 HTTP。subtitle NULL，optional 不推測，ISBN 命中 1 本時只附加 Source 並依 §7.4 補 NULL（不做 canonical merge）；命中 2 本以上則建立新 Book。

榜單交易先驗證 source ownership 再 DELETE／INSERT（`last_seen_at` 已於逐項處理時獨立 touch）；schema 與 ledger 保證 rank／Book uniqueness。空 snapshot 合法。不含 cache；Web cache 行為不是此模組已驗證責任。時間採注入 UTC clock，排程採 epoch 與 UTC cron。沒有取消 token；EXIT trap 不能推論 SIGKILL 也會清理。

本里程碑（Kingstone P1 M2）對 Books 的唯一行為變更：existing Source 的 touch 改為 `last_seen_at = GREATEST(last_seen_at, now)`，時鐘倒退時不再把 `last_seen_at` 往回拉；touch 限定 BOOKS_COM_TW，Source 已不存在時視為 `source_identity_conflict` 跳過（不重試、不抓詳細頁）。其餘 Books 寫入內容不變（`external_id` 對 Books 草稿仍為 NULL）。

Host coordination 以 target wrapper 為準：先取 shared maintenance lock 才讀 state，與 deploy 的 exclusive migration lock 形成 concurrency boundary。`crawler.paused != null` 或 `schema.dirty is True` 在 SSM／Docker 前跳過；state 缺少只省略 state gate，maintenance lock 仍生效。Deployment state.json 與 pages-last-success 是不同 contract：前者保護部署／schema，後者只決定 pages 是否到期。鎖順序、exit 語意與既有測試見 [流程](workflow-diagram.md) 及 CR-T12-B。

Target 的 image 由 CD 依 release.json 管理 GHCR digest，[crawler.conf.example](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/crawler.conf.example) 中 `<digest>` 必須替換為實際值；不要把舊 Docker Hub 手動推送流程視為現行發布政策。

SSM 僅取 DB URL，log／JSON 遮罩；HTML 是原始頁面，PNG 可能含畫面資料，不能稱為全面去識別。目前沒有 stealth、CAPTCHA 代解與 proxy 輪替；政策上允許使用，見「核心不變條件」。

確認字面差距（#113 前的規格）：舊 §16.9 說 pages 不寫任何來源 last_seen_at，但 `_insert_source` 對新建／附加來源 INSERT 初始化 now；既有來源確實不刷新。見 CB-01，未確認功能 bug。artifact 無清理政策實作，deployment 已明示另管，屬 CB-02 改善提案。EC2、SSM／IAM、GHCR／CD、cron 安裝、來源可抓性本次未驗證（CB-03），不能由設定存在推定已部署。

金石堂（KINGSTONE）crawler 尚未實作；已決定的來源契約與計畫見 [backlog](backlog.md) CB-07。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
