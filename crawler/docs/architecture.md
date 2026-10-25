# Crawler 架構與選型

**版本範圍**：crawler 核心以 `91333c3` 為原始查核基準；host wrapper／deployment coordination 另查核 PR #100 merge target `main` 的 `ce7b4f46c0889db6b10216294cac658136796ad7`（2026-10-24 擷取）。下述 host 流程描述合併後的 target 行為，不表示文件分支內較早的 wrapper 已變更；target 證據使用固定 SHA 連結。未執行 build、測試、部署或真實抓取。

> 查核 2026-10-24；核心基準 `91333c3`。核心來源依原始基準靜態閱讀；host 另依上述 merge-target snapshot；本次未執行 build、測試、部署、外部服務或真實抓取。

[Crawler authority](../../Docs/modules/crawler.md)、[資料契約](../../Docs/data/data-model.md)、[部署](../../Docs/deployment/deployment.md)、[測試策略](../../Docs/testing/test-plan.md)、[名詞](../../CONTEXT.md)；ADR-002 見 [ADR](../../Docs/architecture/architecture-decisions.md)。分類榜補 Catalog，不是 Bestseller。

| 責任／來源 | caller、callee 與 contract |
|---|---|
| [cli](../books_crawler/cli.py) | env → 驗證 → RunDependencies → runner；exit 0 成功／部分成功、1 FAILED、2 設定錯誤；finally close |
| [run](../books_crawler/run.py) | orchestration；注入 fetcher、parser、connect、clock、sleep；outcome 送 ledger |
| [fetcher](../books_crawler/fetcher.py)、[browser](../books_crawler/browser.py) | get(url)→HTML、close；FetchError 與 BrowserUnavailableError 分類 |
| [parsers](../books_crawler/parsers.py)、[normalize](../books_crawler/normalize.py)、[urls](../books_crawler/urls.py) | HTML→RankingRow／BookDraft；URL canonicalization、ISBN、語言、日期精度 |
| [identity](../books_crawler/identity.py) | Source identity 矩陣（data-model §7.3）；純函式，DB 查詢由 `db` 提供 |
| [ledger](../books_crawler/ledger.py) | CatalogResolution→Catalog counts；RunLedger 再決定 RankingDecision、streak、snapshot、status；PagesLedger 只用 CatalogResolution；無 DB |
| [db](../books_crawler/db.py) | autocommit connection + 顯式交易；URL／ISBN 查詢、每書寫入、榜單替換 |
| [session](../books_crawler/session.py) | run 持有的 `DatabaseSession`：連線 closed／broken 時以注入的 connect 重連（§13.1）；每次 run 一個，無模組層級狀態 |
| [page_list](../books_crawler/page_list.py) | UTF-8 BOM、註解、空行、首次順序去重；非法／空清單在請求前失敗 |
| [Dockerfile](../Dockerfile) | Python 3.14、UID 10001、runtime 依賴與清單 |
| [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) | host scheduling、SSM secret retrieval、daily/pages serialization、DB maintenance coordination、deployment state gate、Docker execution 與 pages schedule state |

## 選型、替代與代價

| 面向 | 現行依據 | 替代差異（本次分析，非 ADR 決策） | 代價／維護 |
|---|---|---|---|
| one-shot batch | ADR-002 | queue／常駐 worker 需新服務與重送協定 | host 排程與觀測；無失敗佇列 |
| curl 預設、browser 診斷 | crawler §12 核准決策 | browser 資源較高；禁止自動切換規避 | preset 與 HTML fixtures 回歸 |
| 循序節流與三次 retry | §13／12 | 並行增加來源負載並改 contract | 執行可能久，避免 backoff 重複等待 |
| URL identity、ISBN 正規化與 distinct 比對 | §6、data-model §7 | 模糊書名合併有 edition 誤判風險，未授權 | 只依 ISBN 值比對；命中 1 本才附加，附加只補 NULL；≥2 本建立新 Book |
| 連線斷開時重連、寫入前重新解析 | §13.1、§6.1 | 讀取（既有 Source 的 SELECT）不重連，維持 run FAILED；重連後若前次寫入已 commit，回報 EXISTING，原 resolution 無法還原 | 連線以 psycopg 的 closed／broken 判斷；寫入重試前先 resolve_source_identity，避免重複插入 |
| ISBN NFKC 固定 Unicode 15.1 | data-model §7.1 | 使用 runtime 的 Unicode 資料會讓 16.0 新增的分解改變 key | 未指派 code point 分段保留；`unicode_15_1.py` 由 `.github/scripts/unicode_tables.py` 產生（CI `--check`）；啟動時檢查 NFKC(U+1E030)，低於 15.0 即 exit 2 |
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

Host coordination 以 target wrapper 為準：先取 shared maintenance lock 才讀 state，與 deploy 的 exclusive migration lock 形成 concurrency boundary。`crawler.paused != null` 或 `schema.dirty is True` 在 SSM／Docker 前跳過；state 缺少只省略 state gate，maintenance lock 仍生效。Deployment state.json 與 pages-last-success 是不同 contract：前者保護部署／schema，後者只決定 pages 是否到期。鎖順序、exit 語意與既有測試見 [流程](workflow-diagram.md) 及 CR-T12-B。

Target 的 image 由 CD 依 release.json 管理 GHCR digest，[crawler.conf.example](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/crawler.conf.example) 中 `<digest>` 必須替換為實際值；不要把舊 Docker Hub 手動推送流程視為現行發布政策。

SSM 僅取 DB URL，log／JSON 遮罩；HTML 是原始頁面，PNG 可能含畫面資料，不能稱為全面去識別。目前沒有 stealth、CAPTCHA 代解與 proxy 輪替；政策上允許使用，見「核心不變條件」。

確認字面差距（#113 前的規格）：舊 §16.9 說 pages 不寫任何來源 last_seen_at，但 `_insert_source` 對新建／附加來源 INSERT 初始化 now；既有來源確實不刷新。見 CB-01，未確認功能 bug。artifact 無清理政策實作，deployment 已明示另管，屬 CB-02 改善提案。EC2、SSM／IAM、GHCR／CD、cron 安裝、來源可抓性本次未驗證（CB-03），不能由設定存在推定已部署。

## 金石堂（KINGSTONE）source contract — E0 凍結，尚未實作

> 2026-10-25 E0 凍結。**尚無金石堂程式**；以下是之後實作必須遵守的來源契約，不是現有行為。實作計畫見 [kingstone-category-crawler.md](../../Docs/plans/kingstone-category-crawler.md)（v11），待辦見 [CB-07](backlog.md)。
> 證據：使用者授權的有限真站抓取，2026-10-25 03:39–03:55 UTC，31 次循序請求（curl_cffi Chrome、不跟隨 redirect、3～30 秒隨機等待），沒有 429、challenge、Retry-After 或登入頁。原始回應在 `crawler/artifacts/kingstone-e0/`（不 commit）；fixture 見 [kingstone fixtures](../tests/fixtures/kingstone/README.md)。

**範圍**（使用者 2026-10-25 決定）：比照博客來分類榜。使用者在清單提供金石堂分類列表頁，crawler 只抓清單上每一頁列出的書；不探索分類樹、不跟分頁、沒有跨 run 進度狀態檔。

**Acquisition**：`HTTP_ONLY`。需要的頁面都是 server-rendered HTML（200），不需要 browser，不新增 Playwright production dependency。只允許 origin `https://www.kingstone.com.tw`；robots.txt 禁止的 `/api/`、`/bms/`、`/dks/`、`/cart/`、`/Refund/`、`/einvoice/`、`/wp-admin/` 都不使用。循序請求，每次請求（含重試）前隨機等待 **3～10 秒**（使用者 2026-10-25 依 E0 證據決定）。不跟隨 redirect。

**URL grammar**（其他 URL 一律拒絕）：

| 用途 | Canonical URL | 規則 |
|---|---|---|
| 列表頁（清單項目） | `/book/<code>/?dis=list&page=<n>[&sort=<key>]` | `code` 為 ASCII 字母 2～4 個，canonical 轉小寫（伺服器也接受大寫，`<link rel="canonical">` 指向小寫；`/normal/book/<code>` 是同內容別名，不接受）。`n` 為正整數。`key` 只能是頁面提供的 `sa_desc`（預設，依銷售）、`pu_desc`、`pu_asc`、`pr_desc`、`pr_asc` |
| 詳細頁 | `/basic/<km_code>/` | `km_code` 為 13 位數字；列表連結的 `?lid=`、`&actid=` 追蹤參數不進 canonical source URL |

**列表頁解析**：

- 商品卡只取 `section#allProducts #displayCSS > .productGrid > .mod_prod_card[data-prodno]`（每頁最多 48 張）。`#allProducts` 外的輪播卡、空頁巢狀 `section.prodSlider` 內的推薦卡都不是列表商品。
- 每張卡的 external_id 是 `data-prodno`，必須等於卡片 `.coverbox a` 連結的 `km_code`。
- 總頁數在 `input#totalPages` 的 `value`，總筆數在「共計<span>n</span>筆」；只作 report，不跟分頁。
- **合法空頁**：沒有 `.productGrid`，且 `#displayCSS > .emptyCategory` 顯示「此分類沒有相關商品唷！」（例如頁碼超過總頁數）。這是成功的零列頁。
- 既沒有 `.productGrid` 也沒有 `.emptyCategory` → parse error，不是空頁。
- 卡片有書名、作者、出版社、出版日，**沒有 ISBN**，所以 New Source 一定要抓詳細頁。

**詳細頁解析**：

| 欄位 | 來源 | 規則 |
|---|---|---|
| external_id | JSON-LD `Product` 的 `sku` | 必須等於 URL 的 `km_code`，否則 parse error |
| title | JSON-LD `name` | 必要；缺少即 parse error |
| ISBN | JSON-LD `isbn`（缺少時 `gtin13`） | 依共用 ISBN 規則正規化；不驗證前綴（非書商品 `4711664071805` 也會寫入，範圍由使用者的清單控制） |
| publisher | JSON-LD `publisher.name` | 去除前後空白（觀察到尾端空白） |
| 出版日 | JSON-LD `datePublished`（`YYYY-MM-DD`） | 精度 `DAY` |
| thumbnail | JSON-LD `image[0]` | |
| 語言 | 規格表 `li.table_th`「語言」相鄰的 `li.table_td` | **不使用** JSON-LD `inLanguage`（簡體書也標 `zh-TW`）；中文繁體→`zh-TW`、中文簡體→`zh-CN`，其他值為 NULL |
| contributors | `li.basicunit` 中 `.title_basic` 為「作者：」的連結，以及「譯者：」的純文字 | 不使用 JSON-LD `author`（只有第一個連結）。作者欄排除「追蹤」與「?」；整段被括號包住的連結是原文姓名（例如「(Gao Junqing)」），不建立 contributor；一個連結或譯者值可能用「、」串多人，要拆開；`角色/姓名` 前綴（例如「審訂/張素惠」）拆出角色，無法對應的角色歸 `OTHER` |
| 頁數 | 規格表「頁數」 | 選填；正整數 |
| 目錄、簡介 | `.catalog` 區塊、內容簡介 | 選填，只供 AI，不公開 |
| subjects | `.basic-category-breadcrumb a` 的名稱 | 頁面上出現兩次，依順序去重後，去掉根節點「中文書」（例如 `童書/青少年`、`繪本`、`同儕相處`） |

規格表另有「分級」欄（E0 的 7 本都是「普通級」），可作為之後辨識限制級的依據；E0 沒有觀察到限制級頁，規則待有 fixture 再定。

**錯誤分類**（不跟隨 redirect）：

| 觀察到的回應 | 分類 | 處理 |
|---|---|---|
| 列表頁的分類不存在：302，`Location: /book/` | page failure | 跳過該頁、不重試 |
| 商品不存在：200 soft 404，`<title>` 只有「金石堂」、沒有 Product JSON-LD | product not found | 跳過、不重試、不寫入 |
| 200 但缺少預期結構 | parse error | 不猜測、不寫入 |
| challenge、CAPTCHA、限制級頁 | E0 未觀察到 | 出現時以 parse error fail closed，收錄新的 fixture 再定分類 |

**背景（不實作）**：E0 也觀察了分類樹：`/book/` 下有 21 個第一層分類，分類頁的 `nav.nav1b_classlevel` 列出直接子分類，代碼長度不代表層級（`nkl` 是 `ssss` 的第二層），子分類的筆數剛好切分父分類。v11 改由使用者提供清單，這些觀察只供使用者挑選網址時參考，不是 crawler 的行為。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
