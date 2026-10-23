# Infrastructure 待辦

> 查核日期：2026-10-24；基準 `91333c3`。本次只做文件靜態檢查，未執行 build、測試、migration、部署或外部服務。

P1 為核心功能缺口、P2 為恢復開發／環境驗證安排、P3 為需求或量測成立後改善；風險 L1–L4 依 [AGENTS](../../AGENTS.md)。本次未重現 runtime bug；待辦不是額外執行授權。

| ID／優先序／風險／狀態 | 證據與影響 | 方向與前置決策 | 驗收與案例／測試入口 |
|---|---|---|---|
| INF-B01／P1／L3／確認缺口：未實作 | [Recommendation §6](../../Docs/modules/recommendation.md)、[Catalog §6](../../Docs/modules/book-catalog.md) 要求 fallback；[store](../Persistence/EfRecommendationStore.cs) 固定 false，無 Google Books adapter。稀少本地候選無補充 | 先確認 Application port，實作 volume normalize、ISBN/source identity resolution、寫入、embedding 與同門檻重查；不得一般搜尋 fallback | 5 候選無外呼、4 候選才外呼；ISBN 命中不重複 Book；不相關書不成候選；外部失敗以本地繼續。INF-T11；新 adapter tests 待建，加 EfCandidateSearchTests／EfRecommendationStoreTests |
| INF-B02／P2／L3／明確暫緩 | [TODO](../../Docs/TODO.md) 與 [EfEmbeddingStore](../Persistence/EfEmbeddingStore.cs)：每輪全量 metadata/hash，Take batch 不限制掃描成本 | 先量測 rows、metadata bytes、時間與記憶體；恢復時確保所有 metadata writer 含 crawler contributors/subjects 都更新 books.updated_at，再預篩與 hash 終判 | 未變更不外呼，所有 metadata 改動不漏書，缺向量優先和穩定排序不變，附前後成本比較。INF-T07、12；EfEmbeddingStoreTests／EmbeddingBackfillServiceTests |
| INF-B03／P2／L3／明確暫緩 | [Identity §7](../../Docs/modules/identity-auth.md)、TODO：登入註冊 rate limiting 暫緩；auth registration 無 limiter | 使用者恢復此範圍後依規格做 IP 視窗，先驗證 proxy IP；不得拿每日推薦 gate 代替 | 同 IP 視窗邊界 429、跨 IP 隔離、可信與偽造 forwarded header 區分、錯誤格式一致。INF-T13；AuthPipelineTests、HostingSetupTests，limiter 測試待建 |
| INF-B04／P2／L4／待驗證 | [HostingSetup](../Hosting/HostingSetup.cs) 可選 CIDR/keys path；[部署規格](../../Docs/deployment/deployment.md) 同時描述暫用 systemd 與 container 目標；本次無 live 證據 | disposable host 核對 nginx source IP、CIDR、key directory 權限與持久 mount；紀錄遮蔽設定與 scheme，不記 token。Production 另需授權 | trusted proxy 取得 HTTPS，untrusted header 忽略；替換 web 後舊 CSRF token 仍有效；壞 CIDR 啟動失敗，附 rollback。INF-T10；HostingSetupTests／ForwardedHeadersTests |
| INF-B05／P3／L3；資源部署另 L4／改善提案 | [ADR-005](../../Docs/architecture/architecture-decisions.md)、[system architecture §7](../../Docs/architecture/system-architecture.md)；queue 與 pending 僅 process-local，store 以單 worker 為前提 | 有多 instance 需求才先提 ADR；比較持久 queue、claim lease、shared cache；先量測 queue 拒絕率／restart 遺失，不逕建 Redis | 雙 worker 同 Book 無未處理競爭，restart 可恢復，至少一次處理冪等，無 Library state 進共享 cache。INF-T08、14；BookProfileQueueTests／BookProfileWorkerTests／EfBookProfileStoreTests |

Debug 證據收集：INF-B04 須保存去識別的 request scheme、來源網段判定、key ring 跨 host 驗證結果，區分程式模擬與實際容器；只有可重現錯誤才改列已重現 bug。其他項目屬功能缺口、已決定暫緩或量測提案。

已修復的 Book FK 誤譯（249c378）、history offset 溢位（fc9bcc3）、embedding scan 多讀 profile 欄位（a4c1fdc）不列成未完成；保留 regression tests 即可。2a74705 已完成設定支援，INF-B04 追的是環境驗證。

## 文件導航

[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [案例](test-suite.md)
