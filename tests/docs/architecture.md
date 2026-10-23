# tests 架構與選型

> 查核日 2026-10-24；HEAD `91333c3`；本次僅靜態查核，沒有測試通過結論。

## Authority 與責任

[test-plan](../../Docs/testing/test-plan.md) 管理分層與隔離；[CONTEXT](../../CONTEXT.md) 管理用語。具體斷言依 [API](../../Docs/api/api-spec.md)、[data model](../../Docs/data/data-model.md)、[auth](../../Docs/modules/identity-auth.md)、[recommendation](../../Docs/modules/recommendation.md)。本目錄不重新定義產品 contract。

呼叫方是 .NET runner／CI；被呼叫方是純規則、Application、EF store、ASP.NET host。`Shared` 是 Compile Link 共用原始碼，非獨立 project。

| 位置 | 輸入與輸出 contract |
|---|---|
| [UnitTests.csproj](../UnitTests/UnitTests.csproj) | net10.0、xUnit；規則／service 輸入與 fake 結果 → return、exception、calls、logs |
| [DatabaseIntegration.csproj](../DatabaseIntegration/DatabaseIntegration.csproj) | disposable DB → migration、SQL、mapping、store；constraints.sql 複製到 output |
| [WebIntegration.csproj](../WebIntegration/WebIntegration.csproj) | request／cookie／form → status、headers、Razor／JSON 與 DB 差異 |
| [Shared](../Shared) | fake parser／embedding／ranker／profile、CallGate、1536 維 SimilarityVectors |
| [CatalogSeed](../WebIntegration/CatalogSeed.cs)、[AccountFlow](../WebIntegration/AccountFlow.cs)、[HtmlPage](../WebIntegration/HtmlPage.cs) | 測資與表單／HTML helpers，不是 JavaScript engine |
| [OpenAiTestTransport](../UnitTests/OpenAiTestTransport.cs) | SDK transport 替身，查核 payload／error mapping，不連 OpenAI |

## 選型與維護代價

下表替代方案是本次分析；未找到 ADR 記錄的部分僅描述程式可見選擇，不推定原作者意圖。

| 面向 | 現況與依據 | 替代方案差異 | 代價與維護 |
|---|---|---|---|
| 分層 runner | 三個 xUnit 2.9.3 projects，參照主專案 | 合併 project 較少設定，但純 unit 不易單獨選擇 | Shared helper 必須維護 Compile Link |
| DB 真實性 | Testcontainers.PostgreSql 4.16.0、pgvector 0.8.7-pg17 | InMemory／SQLite 無法證明 PostgreSQL constraint／vector SQL | Docker 與 image 可用性；CI checker 比對 compose image |
| Schema | 初始化 MigrateAsync | EnsureCreated 不涵蓋 migration 路徑 | migration 失敗會阻擋 collection；不使用開發／production DB |
| Web 隔離 | collection 序列、逐案 reset、新 host／cache | 共用 host 較快但 cache／DI 狀態可能污染 | reset 僅限 disposable DB；host 必須 dispose |
| watchers | 關閉 reload、NullFileProvider；歷史 f233b9d | 真實 provider 可驗證 asset version，但耗用 inotify | 現有 harness 不涵蓋靜態資產 |
| 外部 AI | 四個 ports 替換、fake Calls 與 CallGate | live API 有成本與非決定性，違反 test-plan | 新 external port 必須納入替換；parser 預設 echo，要明確設定硬條件 |
| 時間 | FakeTimeProvider 與 CallGate | real sleep 慢且易抖動 | 等 Gate.Entered 再 Advance；取消與逾時分開斷言 |
| 向量 | SimilarityVectors 可控制 cosine，1536 維 | 隨機向量難以穩定驗證門檻 | 驗證等於／剛高／剛低，注意 float 精度 |
| 結果 | CI TRX、crawler JUnit、compat JSON | 僅看綠燈無法區分 skip | artifact 缺檔可 warn，需查執行與 skipped 數 |

## 目錄外分佈

| 位置 | 實際責任 | 入口 |
|---|---|---|
| [crawler/tests](../../crawler/tests) | pytest、HTML fixture、DB、local Chromium 與 browser fake | CI Crawler tests；不隨 dotnet test |
| [.github/scripts/tests](../../.github/scripts/tests) | 版本同步、migration manifest checker | CI lint pytest |
| [deploy/tests](../../deploy/tests) | Python host 與部署工具，CI Python 3.14 與 3.12 | CI lint pytest |
| [web-smoke.sh](../../deploy/smoke/web-smoke.sh) | Docker internal network HTTP、container replacement key persistence 與負控制 | CI Docker job |
| [compat.sh](../../deploy/migration-test/compat.sh) | base／target migration 與 runtime 相容性報告 | PR 指定 migration／checker 路徑變更時執行 |

crawler Playwright 不是網站 E2E。CI checker 可讀 GitHub release metadata；這不代表業務測試能呼叫真實 OpenAI／Google Books／博客來。

## 安全、一致性與限制

Web signing key 為每 run 隨機測試值，OpenAI key 是 placeholder。四個 AI ports 均由 fake 取代。保留 auth 與 antiforgery 負面測試；不以關閉安全檢查來解決 fixture 問題。書籍簡介與目錄不應由 View／JSON 洩漏。DB 與 Web fixture 各自 container，不共用 seed。

test-plan Web「骨架」描述落後於目前 Auth／Library／AI API/history coverage；CI 章節也未完整列出新增 Docker／deploy／checker checks。規格要求 Google Books fallback，但現有 RecommendationService 與測試尚無對應 adapter 流程，不能宣稱完整 REC-03 保護。詳見待辦。本次未量測時間、讀取實際 CI run、驗證 Docker／browser 或 production。

[流程](workflow-diagram.md) · [待辦](backlog.md) · [歷史](update-history.md) · [案例](test-suite.md)
