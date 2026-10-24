# Infrastructure 待辦

> 查核日期：2026-10-24；基準 `91333c3`。本次只做文件靜態檢查，未執行 build、測試、migration、部署或外部服務。

P1 為核心功能缺口、P2 為恢復開發／環境驗證安排、P3 為需求或量測成立後改善；風險 L1–L4 依 [AGENTS](../../AGENTS.md)。本次未重現 runtime bug；待辦不是額外執行授權。

| ID／優先序／風險／狀態 | 證據與影響 | 方向與前置決策 | 驗收與案例／測試入口 |
|---|---|---|---|
| INF-B01／P1／L3／確認缺口：未實作 | [Recommendation §6](../../Docs/modules/recommendation.md)、[Catalog §6](../../Docs/modules/book-catalog.md) 要求 fallback；[store](../Persistence/EfRecommendationStore.cs) 固定 false，無 Google Books adapter。稀少本地候選無補充 | Recommendation 定義觸發條件與 orchestration port；Catalog 擁有 Google Books normalization、cross-source identity resolution 與 Book persistence 規則。Infrastructure 依 Catalog/Application contract 實現 external API、EF／SQL adapter mechanics，不另定 normalization／merge 規則；Catalog 完成後由 Recommendation 補 embedding、同門檻重查；一般搜尋不得 fallback | 5 候選無外呼、4 候選才外呼；ISBN 命中不重複 Book；不相關書不成候選；外部失敗以本地繼續。INF-T11；新 adapter tests 待建，加 EfCandidateSearchTests／EfRecommendationStoreTests |
| INF-B02／P2／L3／明確暫緩 | [TODO](../../Docs/TODO.md) 與 [EfEmbeddingStore](../Persistence/EfEmbeddingStore.cs)：每輪全量 metadata/hash，Take batch 不限制掃描成本 | 先量測 rows、metadata bytes、時間與記憶體；恢復時確保所有 metadata writer 含 crawler contributors/subjects 都更新 books.updated_at，再預篩與 hash 終判 | 未變更不外呼，所有 metadata 改動不漏書，缺向量優先和穩定排序不變，附前後成本比較。INF-T07、12；EfEmbeddingStoreTests／EmbeddingBackfillServiceTests |
| INF-B03／P2／L3／明確暫緩 | [Identity §7](../../Docs/modules/identity-auth.md)、TODO：登入註冊 rate limiting 暫緩；auth registration 無 limiter | 使用者恢復此範圍後依規格做 IP 視窗，先驗證 proxy IP；不得拿每日推薦 gate 代替 | 同 IP 視窗邊界 429、跨 IP 隔離、可信與偽造 forwarded header 區分、錯誤格式一致。INF-T13；AuthPipelineTests、HostingSetupTests，limiter 測試待建 |
| INF-B04／P2／L4／待驗證 | [HostingSetup](../Hosting/HostingSetup.cs) 可選 CIDR/keys path；[部署規格](../../Docs/deployment/deployment.md) 的 authority 狀態已於 merge target `main@ce7b4f46c0889db6b10216294cac658136796ad7` 更新：[target ADR-006](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/architecture/architecture-decisions.md) 為 Accepted，正式採用 tag-triggered CD、GHCR digest、containerized web、production approval 與 host state machine；[target deployment §3／§3.1](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/Docs/deployment/deployment.md) 的 §3 定義 CD 後配置，§3.1 僅保留首次 cutover 前的既有 systemd runtime；本次無 live 證據 | 追蹤 production CIDR、Data Protection key mount、nginx／TLS 與首次 cutover 的 L4 實證，不是重新決定部署架構。先在 disposable host 核對 source IP、CIDR、key directory 權限與持久 mount，正式 cutover／live 驗證另需授權；紀錄遮蔽設定與 scheme，不記 token | trusted proxy 取得 HTTPS，untrusted header 忽略；替換 web 後舊 CSRF token 仍有效；壞 CIDR 啟動失敗；另附經授權的公開 nginx／TLS 與 cutover／rollback 證據。INF-T10；HostingSetupTests／ForwardedHeadersTests 僅支援設定／管線斷言，不等於正式 cutover 已驗證 |
| INF-B05／P3／L3；資源部署另 L4／改善提案 | [ADR-005](../../Docs/architecture/architecture-decisions.md)、[system architecture §7](../../Docs/architecture/system-architecture.md)；queue 與 pending 僅 process-local，store 以單 worker 為前提 | 有多 instance 需求才先提 ADR；比較持久 queue、claim lease、shared cache；先量測 queue 拒絕率／restart 遺失，不逕建 Redis | 雙 worker 同 Book 無未處理競爭，restart 可恢復，至少一次處理冪等，無 Library state 進共享 cache。INF-T08、14；BookProfileQueueTests／BookProfileWorkerTests／EfBookProfileStoreTests |

Debug 證據收集：INF-B04 須保存去識別的 request scheme、來源網段判定、key ring 跨 host 驗證結果，區分程式模擬與實際容器；只有可重現錯誤才改列已重現 bug。其他項目屬功能缺口、已決定暫緩或量測提案。

已修復的 Book FK 誤譯（249c378）、history offset 溢位（fc9bcc3）、embedding scan 多讀 profile 欄位（a4c1fdc）不列成未完成；保留 regression tests 即可。2a74705 已完成設定支援，INF-B04 追的是環境驗證。

## INF-B06 — 書庫隨機樣本的整表排序成本

- **P3 / L2 / 已量測（#109 M3 baseline）**：首頁隨機樣本（`EfBookBrowse.SampleAsync`）以 `OrderBy(EF.Functions.Random())` 排序整個 Catalog 後才取前 10 筆，資料量增加後成本隨書籍數線性增加。
- 證據：[EfBookBrowse.cs](../Persistence/EfBookBrowse.cs)；基準見 [#109 實作報告 Query plan baseline](../../Docs/Implementation-Report/issue-109-book-browse.md)：開發庫 2884 筆時，樣本查詢 EXPLAIN ANALYZE 約 1.6–1.9 ms（Seq Scan + top-N heapsort），僅為單點觀察。[system architecture §168](../../Docs/architecture/system-architecture.md) 未定義 SLO，因此不設門檻。
- 方向：若基準顯示成本不可接受，再評估以 TABLESAMPLE、主鍵隨機區段或預先快取的隨機種子取代；需先依 AGENTS.md §2.4／§2.5 判斷是否為架構或產品行為變更。
- 驗收：有量測前後資料量與耗時；不改變「只從 Local DB 取樣、不讀 Bestseller rank」的規則。
- 併發壓測（#109 上線關卡，本機 2884 本書）：首頁每個請求的 DB CPU 約 1.0–1.1 ms；`/books` 第 1 頁約 1.4–1.5 ms，最後一頁約 2.8–4.1 ms。併發從 1 到 16 時，每請求成本大致不變，總 CPU 隨流量線性增加；成本低於既有的一般搜尋（6.7–10 ms）。詳見實作報告〈上線關卡〉。未在 RDS 實測。
- 入口：[BookBrowseIntegrationTests](../../tests/WebIntegration/BookBrowseIntegrationTests.cs)（功能）。效能量測方法見實作報告，沒有寫成自動化測試。

## INF-B07 — Multi-source schema 與讀取端（#113 PR2／PR4）

- **P1 / L3 / 確認缺口（目標規格已定，未實作）**。
- 目標：[data-model §6、§11.2～§11.4](../../Docs/data/data-model.md)；migration 010（expand：`source_providers` 四筆、`source_code` 回填與 FK、雙向 trigger、`ISBN` 類型、`book_offers`）手寫或手改，ModelSnapshot 只描述 runtime 目標 model，EF 不 mapping `source_type`；`book_subjects` 的 EF key `(BookId, Subject, SourceCode)` 由 UNIQUE 保證，實體 PK 仍含 `source_type`。
- 目前差距：[BookSourceConfiguration](../Persistence/Configurations/BookSourceConfiguration.cs)、[BookSubjectConfiguration](../Persistence/Configurations/BookSubjectConfiguration.cs) 以 `SourceType` 建 check 與 key；[BookIdentifierConfiguration](../Persistence/Configurations/BookIdentifierConfiguration.cs) 的 partial unique 只針對 ISBN_10／13（010 保留，011 DROP）；[EfBookSearch](../Persistence/EfBookSearch.cs) 與 [EfBookDetailReader](../Persistence/EfBookDetailReader.cs) 只讀 `Isbn13`／`Isbn10`；Detail 來源未 JOIN `source_providers`。
- 方向：PR2 寫 010 migration 與 seed、Search／Detail 讀三種 ISBN 類型、Detail 去重（同值 `ISBN` > `ISBN_13` > `ISBN_10`）、`BookDetailSource` 帶 `SourceCode` 與 `ProviderDisplayName`（JOIN 不以 `enabled` 過濾）、C# ISBN 正規化讀共用 fixture。PR4 寫 011（轉換、DROP trigger 與 `source_type`、換 PK），只讀 `ISBN`。
- 前置決策：`has-pending-model-changes` 不能證明實體 schema（data-model §11.4），每個 migration operation 需人工 review。
- 驗收：[test-plan §7](../../Docs/testing/test-plan.md) #8～#10、#12、#16、#20 通過；`dotnet build`／`dotnet test` 與 CI compat 通過。
- 入口：SchemaTests、StoredEnumTests、constraints.sql、BookDetailPageTests、SearchPageTests；新案例待建。

## INF-B08 — Google Books writer 前的跨 process 序列化（#14 前置）

- **P2 / L3 / 待實作前置**，與 INF-B01 相關。
- 目標：[data-model §7.5](../../Docs/data/data-model.md)：在跨 process 的序列化完成以前，只允許 crawler 一個 writer，PR4 不會解除這個限制；Google Books ingestion 使用 §7.2 比對前，必須依 §7.5 的 protocol：對 draft 每一個正規化 ISBN 算 lock key（SHA-256 前 8 bytes，signed int64），去重並依數值排序後，依序呼叫 `pg_advisory_xact_lock`，再重新查 distinct Book 數量。
- 目前差距：沒有任何 advisory lock；crawler 也未取鎖（目前靠 host `flock`）。
- 驗收：
  - 兩個並行 writer 對同一個 ISBN 只會建立一本 Book。
  - 兩個 writer 的 ISBN 集合只有部分重疊時（例如 [X, Y] 和 [Y, Z]），結果仍然符合 §7.2 的規則。
  - 取 lock 的順序固定，依 key 的數值由小到大，交錯執行也不會 deadlock。
  - lock key 和 crawler 的正規化結果逐 byte 一致。

## 文件導航

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [案例](test-suite.md)
