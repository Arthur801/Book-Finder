# Application 文字測試案例庫

> 查核日期：2026-10-24；Git 基準 `91333c3`。目標 `Application/`；本次僅靜態查核，未執行 build、測試、資料庫或外部服務。規格、實作與測試證據分開記錄。

## 執行策略與共同fixture

依[test-plan](../../Docs/testing/test-plan.md)：Unit使用xUnit與fake ports；時間用FakeTimeProvider與[CallGate](../../tests/Shared/CallGate.cs)，先等呼叫進入才推進時間，不用sleep。固定Book/user GUID、UTC時刻、可控1536維向量；record call順序與參數；禁止真OpenAI、Google Books、博客來。每案重設fake狀態；AccountService靜態dummy hash可能已初始化，不依測試順序斷言首次Hash次數。

[PostgresFixture](../../tests/DatabaseIntegration/PostgresFixture.cs)使用`pgvector/pgvector:0.8.7-pg17` disposable container並由EF migration建schema，不用development/production連線。Web fixture替換外部adapter並關閉背景embedding；profile相關測試也需控制queue/worker，避免競態。測試實作與執行證據分開標記；所有案例均為 `Not executed in this audit`，沒有本次通過結果。

| 狀態欄位 | 固定值 | 語意 |
|---|---|---|
| 測試實作 | `Implemented` | 已找到相關 test source，不表示本次執行或每個交界都有完整證據 |
| 測試實作 | `Missing` | 所需測試尚未建立 |
| 測試實作 | `Pending` | 已有相關測試，但本案例所需的交界斷言仍待補強 |
| 前置 | `Blocked by APP-B01` | fallback implementation 尚不存在，須先完成 APP-B01 |
| 證據 | `Needs stronger evidence` | 現有來源不足以證明完整案例，不標 fully verified |
| 執行 | `Not executed in this audit` | 本次只查核文件與來源，未執行測試 |

未來獲得測試執行任務時可用下列真實project入口；需.NET SDK，integration/web另需Docker與可用container image。此次未執行，亦未restore或產生build artifacts：

```sh
dotnet test tests/UnitTests/UnitTests.csproj
dotnet test tests/DatabaseIntegration/DatabaseIntegration.csproj
dotnet test tests/WebIntegration/WebIntegration.csproj
```

## 可操作案例

### APP-T01 — Catalog空輸入與頁碼

- 風險／狀態：L2；**測試實作：Implemented；執行：Not executed in this audit**。規格：[book-catalog](../../Docs/modules/book-catalog.md) §3。
- **Given**：null或空白input，page為0/負數；recording IBookSearch。
- **When**：呼叫BookSearchService.SearchAsync(input,page,ct)。
- **Then**：page=1、PageSize=20、TotalCount=0、hits空；search port零呼叫。
- 測試來源／擴充入口：[BookSearchServiceTests.cs](../../tests/UnitTests/BookSearchServiceTests.cs)。

### APP-T02 — 搜尋型別與公開內容

- 風險／狀態：L2；**測試實作：Implemented；執行：Not executed in this audit**。規格：[book-catalog](../../Docs/modules/book-catalog.md) §3～4、BOOK-05。
- **Given**：全形ISBN含空白連字號、一般keyword、無效Unicode；BookDetail contract。
- **When**：SearchQuery.Parse；檢視BookDetail序列化公開欄位與PublishedDateText.Format。
- **Then**：ISBN正規化；keyword保留原內部文字；invalid Unicode不throw；detail沒有description/目錄；precision缺少回null。
- 測試來源／擴充入口：[SearchQueryTests.cs](../../tests/UnitTests/SearchQueryTests.cs)、[BookDetailContractTests.cs](../../tests/UnitTests/BookDetailContractTests.cs)、[PublishedDateTextTests.cs](../../tests/UnitTests/PublishedDateTextTests.cs)。

### APP-T03 — Account驗證與登入分支

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[identity-auth](../../Docs/modules/identity-auth.md) §3～4。
- **Given**：fake store/hash、可控time；無效輸入、duplicate email、未知email、錯密碼、rehash-needed。
- **When**：分別RegisterAsync/LoginAsync。
- **Then**：無效不寫入；email/name trim但password不trim；duplicate為email error；未知/錯密碼同訊息；未知仍Verify；rehash更新hash與UTC。
- 測試來源／擴充入口：[AccountInputRulesTests.cs](../../tests/UnitTests/AccountInputRulesTests.cs)、[AccountServiceTests.cs](../../tests/UnitTests/AccountServiceTests.cs)。

### APP-T04 — Bestseller保留缺號與空榜

- 風險／狀態：L2；**測試實作：Implemented；執行：Not executed in this audit**。規格：[bestseller](../../Docs/modules/bestseller.md) §2～5。
- **Given**：reader回原rank缺號snapshot或空榜CapturedAt=null。
- **When**：GetTopAsync(10,ct)與GetAllAsync(ct)。
- **Then**：Top取排序後前10筆，rank不重編；All保留全部；空榜無例外；不寫資料。
- 測試來源／擴充入口：[BestsellerServiceTests.cs](../../tests/UnitTests/BestsellerServiceTests.cs)。

### APP-T05 — Library冪等及user scope

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[user-library](../../Docs/modules/user-library.md) §2～3。
- **Given**：userA/B、存在/缺失Book、A已有Reading且rating4 Entry、fake time。
- **When**：AddAsync、FindAsync、ListAsync、RemoveAsync。
- **Then**：新Entry WantToRead/null；重複回原值；缺Book回BookNotFound；每port帶正確userId；移除不存在仍成功。
- 測試來源／擴充入口：[LibraryServiceTests.cs](../../tests/UnitTests/LibraryServiceTests.cs)。

### APP-T06 — Library change三態與pending安全

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[user-library](../../Docs/modules/user-library.md) §3、identity-auth §6。
- **Given**：空change、rating Clear/Set；canonical books URL、外部URL/query/尾斜線；store故障與cancelled ct。
- **When**：UpdateAsync；AddPendingAsync。
- **Then**：空change只Find不改updatedAt；非空傳目前UTC；不合法pending不呼叫store；一般故障warning且登入繼續；caller取消傳遞。
- 測試來源／擴充入口：[LibraryServiceTests.cs](../../tests/UnitTests/LibraryServiceTests.cs)、[PendingLibraryActionTests.cs](../../tests/UnitTests/PendingLibraryActionTests.cs)。

### APP-T07 — 配額先於外部呼叫與台北日界線

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §11。
- **Given**：FakeTimeProvider固定UTC時刻，usage=20或19；DailyLimit=20；recording parser/embedding/ranker/store。
- **When**：RecommendAsync(userId,text,ct)。
- **Then**：20回DailyLimitReached，無parser/embedding/ranker/save；CountSince是當日台北00:00對應UTC；19走流程；失敗搜尋不計入usage由DB/web測試補證。
- 測試來源／擴充入口：[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)、[TaipeiTimeZoneTests.cs](../../tests/UnitTests/TaipeiTimeZoneTests.cs)。

### APP-T08 — filter與retrieval fallback

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §4～5。
- **Given**：parser回反向年份/頁數、非正頁數、空字串fields、空retrievalText。
- **When**：RecommendAsync；RequirementFilters.Sanitize。
- **Then**：不合理值移除並記dropped；空白null；embedding使用原需求；候選port收到sanitized filters/threshold/TopK；不是SQL字串。
- 測試來源／擴充入口：[RequirementFiltersTests.cs](../../tests/UnitTests/RequirementFiltersTests.cs)、[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)。

### APP-T09 — Candidate與ranking驗證

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §5/§7、REC-06。
- **Given**：可控候選；ranker回越界/重複/空理由/超過10；NaN或越界relevance。
- **When**：RankingRules.Number/Validate；RecommendAsync。
- **Then**：只回候選；有效第一筆claim編號，無效空理由不claim；最多10；rank連續；relevance限0～1且NaN為0；空候選不呼叫ranker但保存空結果。
- 測試來源／擴充入口：[RankingRulesTests.cs](../../tests/UnitTests/RankingRulesTests.cs)、[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)。

### APP-T10 — 保存前失敗、60秒與caller取消

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §8/§13。
- **Given**：CallGate hold parser/ranker；FakeTimeProvider；各port可拋例外。
- **When**：等gate進入後推進59/60秒或cancel caller，再await RecommendAsync。
- **Then**：59秒可完成；60秒timer取消轉AiTimeoutException且未save；caller取消維持OperationCanceledException；parser/embedding/search/ranker失敗不進save；一次failure log無需求原文。
- 測試來源／擴充入口：[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)。

### APP-T11 — 保存後difficulty與排程順序

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §9.1/§13。
- **Given**：非空成功結果、recording store/profile reader/queue、即時完成generator；另備空結果。
- **When**：RecommendAsync成功保存後觀測calls。
- **Then**：先save→讀difficulty快照→schedule；ranking輸入無profile；空結果不讀/排；一般profile錯誤不使已存搜尋失敗；save後timer觸發仍可成功。
- 測試來源／擴充入口：[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)。

### APP-T12 — Profile disabled、降級與正規化

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §9、data-model §5.6。
- **Given**：Enabled=false；reader throw；missing/fresh/stale source；difficulty0/6；無真目錄卻official；超10章。
- **When**：ScheduleAsync、ReadAsync、GenerationService.GenerateAsync、BookProfileRules.Normalize。
- **Then**：disabled不查store不入列；讀失敗空dict加warning；caller取消傳遞；missing/fresh不generator；invalid difficulty=null；無目錄official=false；章節最多10；Upsert正規化profile/hash/model/prompt。
- 測試來源／擴充入口：[BookProfileSchedulerTests.cs](../../tests/UnitTests/BookProfileSchedulerTests.cs)、[BookDifficultyReaderTests.cs](../../tests/UnitTests/BookDifficultyReaderTests.cs)、[BookProfileGenerationServiceTests.cs](../../tests/UnitTests/BookProfileGenerationServiceTests.cs)、[BookProfileRulesTests.cs](../../tests/UnitTests/BookProfileRulesTests.cs)。

### APP-T13 — Embedding deterministic文字與失敗計數

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §10。
- **Given**：固定metadata、emoji長簡介、pending列表；fake vectors1536或錯維度；5連錯/交錯成功/取消。
- **When**：BookEmbeddingText.Build/Hash；RunOnceAsync(ct)。
- **Then**：簡介截2000 code points；hash可重現；逐本生成保存；5連錯停止；成功歸零；caller取消不列失敗；錯維度warning仍呼叫save，DB可能拒絕。
- 測試來源／擴充入口：[BookEmbeddingTextTests.cs](../../tests/UnitTests/BookEmbeddingTextTests.cs)、[EmbeddingBackfillServiceTests.cs](../../tests/UnitTests/EmbeddingBackfillServiceTests.cs)。

### APP-T14 — Application atomic contract 的 adapter 實現與歷史隔離

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §8/§12、data-model。
- **Given**：disposable pgvector資料庫、userA/B、合法及FK失敗results、兩筆時間相同歷史。
- **When**：IRecommendationStore.SaveAsync；IRecommendationHistory.ListAsync/GetAsync。
- **Then**：adapter 落實 IRecommendationStore 定義的 Search／全部 Results atomic contract，無半成品；空結果可保存；list newest created_at/id；他人/不存在detail均null；history理由rank snapshot、Book欄位即時。
- 測試來源／擴充入口：[../DatabaseIntegration/EfRecommendationStoreTests.cs](../../tests/DatabaseIntegration/EfRecommendationStoreTests.cs)、[../DatabaseIntegration/EfRecommendationHistoryTests.cs](../../tests/DatabaseIntegration/EfRecommendationHistoryTests.cs)。

### APP-T15 — Fallback少於5與邊界

- 風險／狀態：L3；**測試實作：Missing；前置：Blocked by APP-B01；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §6、REC-03。
- **Given**：本地0/4/5候選；待建 Catalog ingestion capability fake、Catalog-owned normalizer 與 embedding fake；有ISBN重複volume。
- **When**：未來RecommendAsync接入Google流程。
- **Then**：5本Google零呼叫；0/4觸發；Recommendation 呼叫 Catalog capability，由 Catalog normalize、identity resolution 並寫 Book/BookSource，完成後 Recommendation 再 embed 並重查；低similarity或違硬條件仍不得入候選；真實fallback telemetry。
- 測試來源／擴充入口：RecommendationServiceTests.cs（擴充入口）；Recommendation 編排與 Catalog-owned normalization／identity／persistence 測試待建。

### APP-T16 — Fallback故障降級與配額隔離

- 風險／狀態：L3；**測試實作：Missing；前置：Blocked by APP-B01；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §6/§8/§11。
- **Given**：待建 Catalog ingestion capability fake 回報 Google 例外/timeout，既有本地候選；另quota已滿；Google已寫Book後ranker失敗。
- **When**：未來RecommendAsync。
- **Then**：Google失敗使用本地候選並記log；quota已滿全外部零呼叫；推薦失敗不保存search，先前Google寫Book保留。
- 測試來源／擴充入口：[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)、[RecommendationApiTests.cs](../../tests/WebIntegration/RecommendationApiTests.cs)（擴充入口）。

### APP-T17 — DB commit與保存後caller取消

- 風險／狀態：L3；**測試實作：Pending；證據：Needs stronger evidence；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §8/§9.1/§13。
- **Given**：disposable DB與可控commit gate；另在save完成後hold difficulty reader或scheduler；caller token可取消。
- **When**：提交前/中/後推進timer；save後取消caller再await。
- **Then**：提交前失敗無半成品；提交後取消可傳遞但已保存search/results仍存在；不能概括所有exception都未保存；若已commit卻timeout先記contract衝突；分開斷言outcome與rows。
- 測試來源／擴充入口：[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)、[EfRecommendationStoreTests.cs](../../tests/DatabaseIntegration/EfRecommendationStoreTests.cs)（擴充入口）。

### APP-T18 — 推薦輸入與設定防線

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[api-spec §3](../../Docs/api/api-spec.md)、[recommendation §13](../../Docs/modules/recommendation.md)。
- **Given**：null、空白、500/501 code points需求（包含emoji）；ChatModel空白、threshold為NaN或超出0～1、TopK為0、ResultLimit為0/11、DailyLimit為0；有效對照設定。
- **When**：呼叫RecommendationInputRules.ValidateRequirementText，以及RecommendationOptions的HasValid系列函式；startup整合入口另由HostingSetup/OpenAI registration測試查核。
- **Then**：有效需求trim後保留；空白/501拒絕且不得進RecommendationService；500有效；無效設定判定false；RequestTimeout固定60秒；不能用UTF-16 Length替代code point計數。
- 來源：[RecommendationInputRulesTests](../../tests/UnitTests/RecommendationInputRulesTests.cs)、[RecommendationOptionsTests](../../tests/UnitTests/RecommendationOptionsTests.cs)、[HostingSetupTests](../../tests/UnitTests/HostingSetupTests.cs)。

### APP-T19 — Profile文字、hash與可重現性

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation §9.2](../../Docs/modules/recommendation.md)。
- **Given**：固定BookProfileSource，含空欄位、重複分類、依來源順序的contributors、超過2000 code points簡介/目錄；另一份相同metadata。
- **When**：BookProfileText.Build、Hash、HasTableOfContents；BookProfileRules.Normalize處理空白summary/key_topics/framework sections。
- **Then**：空值整行省略；contributors保序且保留重複、subjects去重；簡介/目錄各截2000 code points；相同輸入文字與SHA256相同；空目錄不宣稱official；key_topics去空白去重且保留首次順序；model/prompt變更本身不改metadata hash。
- 來源：[BookProfileTextTests](../../tests/UnitTests/BookProfileTextTests.cs)、[BookProfileRulesTests](../../tests/UnitTests/BookProfileRulesTests.cs)、[CodePointsTests](../../tests/UnitTests/CodePointsTests.cs)。

## 明確暫緩與證據限制

Auth的Google登入/email驗證/忘記密碼/個資修改/refresh token依identity-auth §1明確暫緩；browser E2E依test-plan §2 MVP不做，沒有冒充可執行案例。APP-T15/T16對應APP-B01，APP-T17對應APP-B02；既有quota並行小幅超額是規格接受行為，不暗加嚴格reservation驗收。

本案例庫的unit/mock、disposable DB與Web測試證據不可推論真實provider或production部署成功。本次只檢查來源與文件連結，無測試通過紀錄。

## 導覽

[流程](workflow-diagram.md)・[架構](architecture.md)・[待辦](backlog.md)・[歷史](update-history.md)・[案例](test-suite.md)
