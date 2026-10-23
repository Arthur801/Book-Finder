# Crawler 架構與選型

> 查核 2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。依當前工作樹靜態閱讀；本次未執行 build、測試、部署、外部服務或真實抓取。

[Crawler authority](../../Docs/modules/crawler.md)、[資料契約](../../Docs/data/data-model.md)、[部署](../../Docs/deployment/deployment.md)、[測試策略](../../Docs/testing/test-plan.md)、[名詞](../../CONTEXT.md)；ADR-002 見 [ADR](../../Docs/architecture/architecture-decisions.md)。分類榜補 Catalog，不是 Bestseller。

| 責任／來源 | caller、callee 與 contract |
|---|---|
| [cli](../books_crawler/cli.py) | env → 驗證 → RunDependencies → runner；exit 0 成功／部分成功、1 FAILED、2 設定錯誤；finally close |
| [run](../books_crawler/run.py) | orchestration；注入 fetcher、parser、connect、clock、sleep；outcome 送 ledger |
| [fetcher](../books_crawler/fetcher.py)、[browser](../books_crawler/browser.py) | get(url)→HTML、close；FetchError 與 BrowserUnavailableError 分類 |
| [parsers](../books_crawler/parsers.py)、[normalize](../books_crawler/normalize.py)、[urls](../books_crawler/urls.py) | HTML→RankingRow／BookDraft；URL canonicalization、ISBN、語言、日期精度 |
| [ledger](../books_crawler/ledger.py) | outcome→counts、status、snapshot；RunLedger 與 PagesLedger 分開政策，無 DB |
| [db](../books_crawler/db.py) | autocommit connection + 顯式交易；URL／ISBN 查詢、每書寫入、榜單替換 |
| [page_list](../books_crawler/page_list.py) | UTF-8 BOM、註解、空行、首次順序去重；非法／空清單在請求前失敗 |
| [Dockerfile](../Dockerfile)、[wrapper](../deploy/run-crawler.sh) | Python 3.14、UID 10001、runtime 依賴與清單；cron／SSM／flock |

## 選型、替代與代價

| 面向 | 現行依據 | 替代差異（本次分析，非 ADR 決策） | 代價／維護 |
|---|---|---|---|
| one-shot batch | ADR-002 | queue／常駐 worker 需新服務與重送協定 | host 排程與觀測；無失敗佇列 |
| curl 預設、browser 診斷 | crawler §15 核准決策 | browser 資源較高；禁止自動切換規避 | preset 與 HTML fixtures 回歸 |
| 循序節流與三次 retry | §6／15 | 並行增加來源負載並改 contract | 執行可能久，避免 backoff 重複等待 |
| URL identity、ISBN13→10 | §5、data-model §6 | 模糊書名合併有 edition 誤判風險，未授權 | 新來源只 attach，不改既有 metadata |
| 每書與榜單分開交易 | §9／10 | 全 run 長交易會擴大鎖與失敗損失 | FAILED 仍可累積 Catalog |
| EF 唯一 schema owner | data-model §7 | Python 自管 DDL 造成雙 truth | DB integration 須使用真 EF schema |
| 兩種 ledger | 程式可見選擇；歷史 refactor 可查 | 混合 I/O 會使政策更難隔離 | 不可把 daily 限制套到 pages |
| Docker＋host cron | deployment §8 | systemd timer／scheduler 需另案 | 依賴 image 預載、狀態檔、時區與權限 |

## 邊界與差距

只寫 books、book_sources、book_identifiers、book_contributors、book_subjects、bestsellers。SQL 參數化；不寫 users、AI／推薦資料、不做 DDL。簡介／目錄可存但只能供 AI，Web 必須排除公開回應；crawler 不提供 HTTP。subtitle NULL，optional 不推測，ISBN 命中不 canonical merge。

榜單交易先驗證 source ownership 再 DELETE／INSERT／last_seen_at；schema 與 ledger 保證 rank／Book uniqueness。空 snapshot 合法。不含 cache；Web cache 行為不是此模組已驗證責任。時間採注入 UTC clock，排程採 epoch 與 UTC cron。沒有取消 token；EXIT trap 不能推論 SIGKILL 也會清理。

SSM 僅取 DB URL，log／JSON 遮罩；HTML 是原始頁面，PNG 可能含畫面資料，不能稱為全面去識別。禁止 stealth、CAPTCHA 代解與 proxy 輪替。

確認字面差距：§16.9 說 pages 不寫任何來源 last_seen_at，但 `_insert_source` 對新建／附加來源 INSERT 初始化 now；既有來源確實不刷新。見 CB-01，未確認功能 bug。artifact 無清理政策實作，deployment 已明示另管，屬 CB-02 改善提案。EC2、SSM／IAM、Docker Hub、cron 安裝、來源可抓性本次未驗證（CB-03），不能由設定存在推定已部署。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
