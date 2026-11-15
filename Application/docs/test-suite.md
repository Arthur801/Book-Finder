# Application 文字測試案例庫

> 會員中心 C3 補記：2026-11-15 更新；程式變更以 `c3f09dc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 會員中心 A2 補記：2026-11-15 更新；程式變更以 `29b6a8b` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 帳號動作 token C2 補記：2026-11-15 更新；程式變更以 `4064680` 記入 update-history。原查核基準保留，未重新審查其餘內容。


> 非同步推薦 Job M6 補記：2026-11-14 更新；程式變更以 `54ad51b`、`0d3b3ac`、`93db136`、`11f86b4`、`c0ac2f6` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M4 補記：2026-11-14 更新；程式變更以 `4b31184`、`5d143b4`、`08d8c9a`、`1f36620`、`ef89755` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M2 補記：2026-11-14 更新；程式變更以 `6717d8f` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> 非同步推薦 Job M3 補記：2026-11-14 更新；程式變更以 `b81a322`、`dc2d903` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> Canonical Category P4 補記：2026-11-14 更新；程式變更以 `c2e5324`、`cec6bd7` 記入 update-history。原查核基準保留，未重新審查其餘內容。

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
- **When**：SearchQuery.Parse；透過 reflection 檢視 `BookDetail*` public contract/properties，並呼叫 PublishedDateText.Format；此 contract guard 不執行序列化。
- **Then**：ISBN正規化；keyword保留原內部文字；invalid Unicode不throw；detail沒有description/目錄；precision缺少回null。
- 測試來源／擴充入口：[SearchQueryTests.cs](../../tests/UnitTests/SearchQueryTests.cs)、[BookDetailContractTests.cs](../../tests/UnitTests/BookDetailContractTests.cs)、[PublishedDateTextTests.cs](../../tests/UnitTests/PublishedDateTextTests.cs)。

### APP-T03 — Account驗證與登入分支

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[identity-auth](../../Docs/modules/identity-auth.md) §3～4。
- **Given**：fake store/hash、可控time；無效輸入、duplicate email、未知email、錯密碼、rehash-needed。
- **When**：分別RegisterAsync/LoginAsync。
- **Then**：無效不寫入；email/name trim但password不trim；duplicate為email error；未知/錯密碼同訊息；未知仍Verify；rehash更新hash與UTC。
- 2026-11-15 B1：註冊成功時 `EmailVerifiedAt` 等於注入時間（UTC），`AuthVersion` 為 0（驗證開關關閉的行為）。
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
- 用量計數本身（含 Job）由 DatabaseIntegration `EfRecommendationUsageTests` 驗證，見 Infrastructure INF-T15（M2，`6717d8f`）。
- 測試來源／擴充入口：[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)、[TaipeiTimeZoneTests.cs](../../tests/UnitTests/TaipeiTimeZoneTests.cs)、[RecommendationApiTests.cs](../../tests/WebIntegration/RecommendationApiTests.cs) 的 `Failed_searches_are_not_counted_and_the_next_attempt_still_fits_under_the_limit`（19 筆成功 → ranker 失敗 502，DB 仍 19 → 重試成功，DB 為 20；本次未執行）。

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

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation](../../Docs/modules/recommendation.md) §9、data-model §6.8。
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
- **Given**：待建 Catalog ingestion capability fake 回報 Google 例外/timeout，原 Local Candidate Set 分別為 0 本與 1～4 本；另備 quota 已滿，以及 Catalog 已寫 Book 後 ranker 失敗的獨立情境。
- **When**：未來RecommendAsync。
- **Then**：Google 失敗／逾時使用原 Local Candidate Set 並記 log；原候選為 0 時 ranker 零呼叫，保存一筆零結果 Recommendation Search；原候選為 1～4 本時只排序這些候選。quota 已滿全外部零呼叫且不保存 Search；ranker 失敗不保存 Search，先前 Catalog 寫入的 Book 保留。
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
- **When**：呼叫RecommendationInputRules.ValidateRequirementText，以及RecommendationOptions的HasValid系列函式；options validation 與 DI registration 由 OpenAiServiceCollectionExtensionsTests 查核（建立 ServiceProvider、讀取 options／解析 ports，不呼叫真實 OpenAI）。
- **Then**：有效需求trim後保留；空白/501拒絕且不得進RecommendationService；500有效；無效設定判定false；RequestTimeout固定60秒；不能用UTF-16 Length替代code point計數。
- 來源：[RecommendationInputRulesTests](../../tests/UnitTests/RecommendationInputRulesTests.cs)、[RecommendationOptionsTests](../../tests/UnitTests/RecommendationOptionsTests.cs)、[OpenAiServiceCollectionExtensionsTests](../../tests/UnitTests/OpenAiServiceCollectionExtensionsTests.cs)：`Invalid_recommendation_setting_fails_validation_at_startup`、`Missing_chat_model_key_fails_validation_at_startup`、`Requirement_parser_and_ranker_resolve_to_the_openai_adapters`；缺 API key 的驗證亦在此檔。

### APP-T19 — Profile文字、hash與可重現性

- 風險／狀態：L3；**測試實作：Implemented；執行：Not executed in this audit**。規格：[recommendation §9.2](../../Docs/modules/recommendation.md)。
- **Given**：固定BookProfileSource，含空欄位、重複分類、依來源順序的contributors、超過2000 code points簡介/目錄；另一份相同metadata。
- **When**：BookProfileText.Build、Hash、HasTableOfContents；BookProfileRules.Normalize處理空白summary/key_topics/framework sections。
- **Then**：空值整行省略；contributors保序且保留重複、subjects去重；簡介/目錄各截2000 code points；相同輸入文字與SHA256相同；空目錄不宣稱official；key_topics去空白去重且保留首次順序；model/prompt變更本身不改metadata hash。
- 來源：[BookProfileTextTests](../../tests/UnitTests/BookProfileTextTests.cs)、[BookProfileRulesTests](../../tests/UnitTests/BookProfileRulesTests.cs)、[CodePointsTests](../../tests/UnitTests/CodePointsTests.cs)。

### APP-T20 — 書庫頁碼、固定參數與首頁樣本

- 風險／狀態：L2；**測試實作：Implemented**；執行結果見 #109 實作報告。規格：[book-catalog](../../Docs/modules/book-catalog.md) §3.6 書庫瀏覽。
- **Given**：recording IBookBrowse；page為0/-1/int.MinValue、1/5/int.MaxValue。
- **When**：BookBrowseService.ListAsync(page,ct)、SampleHomeAsync(ct)。
- **Then**：page小於1時port收到1，正數原值傳入；pageSize固定20；首頁樣本請求10筆；port結果原樣回傳；TotalPages為總數除以20的上取整；TotalCount為int.MaxValue時TotalPages為107374183（不溢位）。
- 測試來源／擴充入口：[BookBrowseServiceTests.cs](../../tests/UnitTests/BookBrowseServiceTests.cs)。

### APP-T21 — 寫入端 ISBN 正規化與共用 fixture

風險 L2；`2a6966b` 已實作。來源：[IsbnNormalizer](../Catalog/IsbnNormalizer.cs)、[IsbnNormalizerTests](../../tests/UnitTests/IsbnNormalizerTests.cs)、[fixture](../../tests/Fixtures/isbn-normalization.json)。

- **Given**：fixture 中每個 vector 的 input 與 expected（逐 byte）；Unicode 15.1 的每個 White_Space code point。
- **When**：`IsbnNormalizer.Normalize`。
- **Then**：73 個 vector 全部相符；U+001C～U+001F、U+180E、U+200B、U+2010、U+2013 保留；全形數字、全形 X、全形連字號與小寫 x 正確；覆蓋測試確認每個 White_Space code point 都有 vector。本次 `dotnet test` UnitTests 通過（806 項）。


## 明確暫緩與證據限制

Auth的Google登入/email驗證/忘記密碼/個資修改/refresh token依identity-auth §1明確暫緩；browser E2E依test-plan §2 MVP不做，沒有冒充可執行案例。APP-T15/T16對應APP-B01，APP-T17對應APP-B02；既有quota並行小幅超額是規格接受行為，不暗加嚴格reservation驗收。

本案例庫的unit/mock、disposable DB與Web測試證據不可推論真實provider或production部署成功。本次只檢查來源與文件連結，無測試通過紀錄。

## 導覽

[流程](workflow-diagram.md)・[架構](architecture.md)・[待辦](backlog.md)・[歷史](update-history.md)・[案例](test-suite.md)

### APP-T22 — Detail 的 ISBN 去重與主要按鈕規則

風險 L2；`d9d8948` 已實作。來源：[BookDetailViewModelTests](../../tests/UnitTests/BookDetailViewModelTests.cs)。

- **Given**：多筆不同值的 `ISBN`、一筆 `OTHER`，`javascript:` 與 `https` 的 KINGSTONE 來源，Google Books 與博客來來源。
- **When**：`BookDetailViewModel.From`。
- **Then**：ISBN 值依值排序全部顯示（PR4 M1，`5052361`，不再有 ISBN-13／ISBN-10 標籤與同值去重）；OTHER 不出現；有博客來時第一筆為主要按鈕，其餘博客來為次要，其他 provider 依來源順序並以 `ProviderDisplayName` 命名；沒有博客來時第一個合格來源（任一 provider）為主要按鈕。本次 `dotnet test` UnitTests 通過。

### APP-T23 — 寫入端 NFKC 與 Unicode 15.1 一致性

風險 L2；`aa792bf` 已實作。來源：[NormalizationConformanceTests](../../tests/UnitTests/NormalizationConformanceTests.cs)、[Unicode151AssignedTests](../../tests/UnitTests/Unicode151AssignedTests.cs)、[IsbnNormalizerTests](../../tests/UnitTests/IsbnNormalizerTests.cs)。

- **Given**：vendored NormalizationTest 15.1 的全部 c1→c4 對（trimmed 檔）；15.1 已指派與未指派的 code point（如 U+1CCF0 OUTLINED DIGIT ZERO 未指派）。
- **When**：`IsbnNormalizer.ComposeCompatibility`；`EnsureRuntimeUnicodeSupported`。
- **Then**：所有 c1 的 NFKC 等於 c4；未指派 code point 原樣保留並分段；runtime 的 Unicode 資料至少 15.0。本次 UnitTests 826 項通過。

### APP-T24 — 分類瀏覽的篩選驗證與頁碼

- 風險／狀態：L2；**測試實作：Implemented；執行：2026-11-14 UnitTests 842 項通過（`c2e5324`）**。規格：[分類計畫](../../Docs/plans/canonical-category-browse.md) §4.2。
- **Given**：fake ICategoryBrowse，記錄每次呼叫與參數。
- **When**：`CategoryBrowseService.BrowseAsync(slug, source, page, ct)`。
- **Then**：
  - 空白值視為未篩選；大小寫不同（`LITERATURE`、`kingstone`）視為不存在；
  - 未知來源 → `UnknownSource`；未知或停用的分類 → `UnknownCategory`；兩者都未知時回 `UnknownSource`；這些情況下都不查書；
  - 頁碼小於 1 時改為 1，pageSize 為 20；
  - 分類清單以來源篩選查詢；查書時傳的是分類 Id（不是 slug）與來源；Found 的每個欄位都有值。
- 測試來源：[CategoryBrowseServiceTests.cs](../../tests/UnitTests/CategoryBrowseServiceTests.cs)。

### APP-T25 — 推薦流程的保存步驟與預算

- 風險／狀態：L2；**測試實作：Implemented；執行：2026-11-14 UnitTests 873、WebIntegration 293 項通過（`dc2d903`）**。規格：[Job 計畫](../../Docs/plans/async-recommendation-jobs.md) §3.3。
- **Given**：`tests/Shared` 的 fake parser／embedding／ranker、測試內的 fake candidate search 與 fake save、`FakeTimeProvider`。
- **When**：`RecommendationPipeline.RunAsync(requirementText, save, ct)`。
- **Then**：
  - `save` 收到的正是驗證後的結果；沒有候選時收到空清單，ranker 不被呼叫；
  - `save` 卡到 60 秒預算之後 → `AiTimeoutException`，沒有保存；
  - `save` 拋出的例外原樣往外傳（同一個 instance），不轉成 timeout；
  - 呼叫端取消 → `OperationCanceledException`，不是 `AiTimeoutException`；
  - 回傳值帶著保存結果與推薦結果。
- 回歸：`RecommendationServiceTests` 只改建構方式（以同一組 fake 組出 pipeline，pipeline 的 log 轉進同一個 recording logger），斷言全部未改、全綠（APP-T07～T17）。
- 測試來源：[RecommendationPipelineTests.cs](../../tests/UnitTests/RecommendationPipelineTests.cs)、[RecommendationServiceTests.cs](../../tests/UnitTests/RecommendationServiceTests.cs)。

### APP-T26 — 推薦工作提交、Idempotency-Key 與額度預約

- 風險／狀態：L3；**測試實作：Implemented；執行：2026-11-14 UnitTests 898、DatabaseIntegration 220 項通過（`ef89755`）**。規格：[Job 計畫](../../Docs/plans/async-recommendation-jobs.md) §3.4、§3.7。
- **Given**：UnitTests 用手寫 fake store 與 `FakeTimeProvider`（2026-10-21T17:30Z，台北已是 10-22）；DatabaseIntegration 用真實 PostgreSQL（見 Infrastructure INF-T22）。
- **When**：`RecommendationJobService.SubmitAsync／ListAsync／GetAsync`；`IdempotencyKeyRules.Validate`。
- **Then**：
  - key：null／空字串視為沒有 key；1 與 128 字元合法；129 字元、空白、`.`、非 ASCII、結尾換行不合法；合法 key 原樣傳回；
  - 不合法 key 不呼叫 store；
  - store 收到 v7 JobId、使用者、需求文字、64 字元小寫 SHA-256、key、時鐘時間、設定的 DailyLimit、台北日界 2026-10-21T16:00Z；
  - 四種 store 結果各自對應；未知結果拋出例外；log 不含需求文字與 key；
  - 列表頁碼小於 1 時改為 1，每頁 20 筆。
- 測試來源：[IdempotencyKeyRulesTests.cs](../../tests/UnitTests/IdempotencyKeyRulesTests.cs)、[RecommendationJobServiceTests.cs](../../tests/UnitTests/RecommendationJobServiceTests.cs)。

### APP-T27 — 推薦工作執行器的結果表與設定

- 風險／狀態：L3；**測試實作：Implemented；執行：2026-11-14 UnitTests 933 項通過（`c0ac2f6`）**。規格：[Job 計畫](../../Docs/plans/async-recommendation-jobs.md) §3.6。
- **Given**：`tests/Shared` 的 fake lease store（記錄每次呼叫）、真的 `RecommendationPipeline` 與 `BookProfileScheduler`（以共用 fake 組成）、`FakeTimeProvider`。
- **Then**：
  - 成功時以 Job 的需求文字經 Pipeline 的 save 步驟 commit 一次，之後排程結果書籍；0 筆結果不排程；排程失敗 Job 仍成功；
  - AI_UNAVAILABLE 第 1／2 次 → requeue；第 2／2 次 → fail；AI 逾時（時間推過 60 秒）→ AI_TIMEOUT requeue；
  - 包在其他例外裡的暫時性 DbException → requeue INTERNAL_ERROR；非暫時性或其他例外 → fail INTERNAL_ERROR；
  - commit 拋出 lease lost、執行中 lease-lost token 被取消 → 不寫入；stopping token 被取消 → 只呼叫 release；
  - log 不含需求文字；
  - 設定：預設值；HeartbeatInterval 等於 LeaseDuration 不合法；MaxAttempts 0 不合法；RetryDelay 0 合法。
- mutation（主 agent）：把重試判斷 `<` 改成 `<=` → `Ai_unavailable_on_attempt_two_of_two_fails_the_job` 失敗，已還原。
- 測試來源：[RecommendationJobRunnerTests.cs](../../tests/UnitTests/RecommendationJobRunnerTests.cs)、[RecommendationJobOptionsTests.cs](../../tests/UnitTests/RecommendationJobOptionsTests.cs)。

### APP-T28 — 推薦額度讀取與台北日界線

- 風險／狀態：L2；**測試實作：Implemented；執行：2026-11-15 UnitTests 1151 項通過（`29b6a8b`）**。規格：[recommendation](../../Docs/modules/recommendation.md) §11；會員中心 A2 計畫。
- **Given**：`FakeRecommendationUsage` 回傳指定已用次數並記錄 `sinceUtc`；`FakeTimeProvider` 固定 UTC 時刻；`IOptions<RecommendationOptions>` 的 DailyLimit 預設 20 或設為 5。
- **When**：`RecommendationQuotaReader.ReadAsync(userId, ct)`。
- **Then**：used 0／1／19／20／25 分別得到 remaining 20／19／1／0／0（不為負）；Limit 與 Used 原樣回傳；DailyLimit=5 時 Limit 為 5；`sinceUtc` 在 `2026-11-15T15:59:59Z` 為 `2026-11-14T16:00Z`，在 `16:00:00Z` 為 `2026-11-15T16:00Z`。
- 測試來源：[RecommendationQuotaReaderTests.cs](../../tests/UnitTests/RecommendationQuotaReaderTests.cs)。

> 會員中心 B3 補記：2026-11-15 更新；程式變更記入 update-history 的 B3 段落。新增的撤銷 port 測試位於 DatabaseIntegration（`OAuthCredentialRevokerTests`）與 WebIntegration（`McpCredentialRevocationTests`），見 Infrastructure 與 Mcp 的 test-suite。

### APP-T29 — 寄信 port、信件範本、站點網址與寄信設定（會員中心 C1）

- 風險／狀態：L2（尚無 flow 使用）；**測試實作：Implemented；執行：見 update-history 的 C1 紀錄**。規格：[會員中心計畫](../../Docs/plans/member-center-email-verification.md) D-A、D-F、C1。
- **Given**：純函式與 `Options.Create`，不需要 host 或資料庫。
- **Then**：
  - 驗證信與重設密碼信的收件人、主旨（不含顯示名稱）、24 小時／1 小時等有效期限文字（由參數決定，60、90、45 分鐘與 24 小時都有測試）；
  - 重設密碼信含「如果不是你本人申請，可以忽略這封信」；
  - 惡意顯示名稱（`<script>`、引號、`&`）在 HTML body 被 encode，純文字 body 保留原文；
  - 連結中的 `"`、`<`、`&` 在 HTML 中被 encode；
  - 空白顯示名稱使用「會員您好」；
  - `SiteOptions`：https 站台根目錄與 localhost http 有效；path、query、fragment、其他 scheme、非 localhost 的 http 無效；
  - `SiteUrlBuilder`：組出絕對連結、結尾斜線不重複、query 值 percent-encode、保留順序；拒絕相對路徑、絕對 URL、`//`、`?`、`#`、空字串；未設定時建構失敗；
  - `EmailOptions.ValidationError`：None 在驗證關閉時有效、在開啟時無效；Ses 需要 From（有效地址、允許顯示名稱）與 Region；Pickup 需要 PickupDirectory；預設 Provider 為 None，驗證預設為關閉。
- 測試來源：[AccountEmailTemplatesTests.cs](../../tests/UnitTests/AccountEmailTemplatesTests.cs)、[SiteOptionsTests.cs](../../tests/UnitTests/SiteOptionsTests.cs)、[EmailOptionsTests.cs](../../tests/UnitTests/EmailOptionsTests.cs)。

### APP-T30 — 帳號動作 token 規則與服務（C2）

- **責任／風險／狀態**：[AccountActionTokenService](../Identity/AccountActionTokenService.cs) 與 [AccountActionTokenRules](../Identity/AccountActionTokenRules.cs)，L3；單元測試已存在並通過（2026-11-15 UnitTests 1180 項通過）。
- **Given**：以 fake store 記錄呼叫；時間用 `FakeTimeProvider`。
- **When／Then**：
  - 原始 token 為 43 個 base64url 字元（解碼後 32 bytes），每次不同；store 只收到 `HashOf(raw)`，且與 raw 不同；
  - 驗證信 lifetime 為 24 小時、重設密碼為 1 小時，回傳的 `ExpiresAtUtc` 與傳給 store 的一致；
  - 節流視窗為 `now − RequestInterval`，`now` 也一併傳入；
  - Throttled 與 UserNotFound 原樣回傳，不回 token；
  - 格式錯誤的 raw（空字串、長度不符、含 `+`、`/`、`=`、空白、`.`）進入 Consume、IsUsable、Discard 時，store 呼叫次數為 0；
  - SHA-256 hex 符合 `^[0-9a-f]{64}$`，且與 FIPS 向量 `abc` 相符；
  - options：預設 1 小時／24 小時／1 小時，section 名為 `AccountActionTokens`，三個值都必須大於 0。
- **入口**：[AccountActionTokenServiceTests](../../tests/UnitTests/AccountActionTokenServiceTests.cs)、[AccountActionTokenRulesTests](../../tests/UnitTests/AccountActionTokenRulesTests.cs)、[AccountActionTokenOptionsTests](../../tests/UnitTests/AccountActionTokenOptionsTests.cs)。
- **證據限制**：本案例只驗證服務規則；鎖、節流 SQL、並發與 cascade 由 INF-T29 驗證。寄信失敗後舊連結的行為尚未定義（APP-B09）。

## 會員中心 D1：帳號刪除（TEST-44 相關）

| 測試 | 位置 | 驗證內容 |
|---|---|---|
| Correct_password_and_confirmation_delete_the_account | `UnitTests/AccountDeletionServiceTests.cs` | 密碼與勾選都正確時，store 只收到該使用者 id，結果為 `Deleted` |
| A_hash_that_needs_rehashing_still_counts_as_the_right_password | 同上 | `SuccessRehashNeeded` 視為正確 |
| Missing_confirmation_is_refused_before_the_password_is_checked | 同上 | 未勾選：不驗證密碼、不呼叫 store |
| Empty_password_is_refused_without_verifying_or_deleting | 同上（Theory：null、空字串、空白） | 密碼空白：不驗證、不呼叫 store |
| Wrong_password_is_refused_and_nothing_is_deleted | 同上 | 錯誤密碼回 `InvalidInput(password)`，不呼叫 store |
| A_user_that_no_longer_exists_is_reported_without_asking_the_store | 同上 | 找不到使用者回 `UserNotFound` |
| A_user_removed_between_the_check_and_the_delete_is_reported_as_not_found | 同上 | store 回 `UserNotFound` 時結果也是 `UserNotFound` |
| A_user_gone_outcome_maps_to_the_user_not_found_case | `UnitTests/RecommendationJobServiceTests.cs` | `JobSubmitOutcome.UserNotFound` 對映為 `RecommendationJobSubmission.UserNotFound` |

- **證據限制**：Application 測試只用 fake，不證明 transaction 或 cascade；那些由 DatabaseIntegration（`EfAccountDeletionStoreTests`、`AccountDeletionRaceTests`）與 WebIntegration（`AccountDeletionTests`）覆蓋。
- **來源**：[AccountDeletionServiceTests](../../tests/UnitTests/AccountDeletionServiceTests.cs)。

## 會員中心 C3：驗證流程與派送（新增案例）

以下案例在 `tests/UnitTests` 中，全部使用 in-memory fake 與 `FakeTimeProvider`，已實作並通過（見 update-history）。

### APP-T31 — 開關與登入閘（AccountService）

| 案例 | Given | When | Then |
|---|---|---|---|
| 註冊、開關開啟 | 空 store，`Enabled=true` | RegisterAsync | 新使用者 `EmailVerifiedAt` 為 null；回 `PendingVerification`，不是 `Succeeded` |
| 未驗證、密碼正確 | 開關開啟，`EmailVerifiedAt` null | LoginAsync（Success） | `EmailNotVerified` |
| 未驗證、密碼錯誤 | 同上 | LoginAsync（Failed） | `InvalidCredentials` |
| 已驗證（legacy） | 開關開啟，`EmailVerifiedAt` 有值 | LoginAsync（Success） | `Succeeded` |
| 開關關閉 | 開關關閉，`EmailVerifiedAt` null | LoginAsync（Success） | `Succeeded`（不檢查驗證） |

### APP-T32 — 驗證信、D-D 與寄信失敗（EmailVerificationService）

| 案例 | Given | When | Then |
|---|---|---|---|
| 寄出一封信 | 未驗證使用者，寄信成功 | SendAsync | `Sent`；收件人為該 email；連結 host 為 `Site:PublicBaseUrl`；store 只收到 hash；過期時間為 +24 小時 |
| D-D 白名單（5 種輸入） | `/books/{guid}`＋`add-to-library` 保留；`https://evil.example`、錯誤動作、帶 query 的路徑、`/search` 都丟棄 | SendAsync | 連結只在合格時含 `returnUrl`、`pendingAction` |
| Normalize | 合格與不合格的組合 | Normalize | 合格回標準形式；不合格或缺少動作回 `(null, null)` |
| 寄信失敗 | 寄信拋出例外 | SendAsync | `SendFailed`；該 token 的 hash 被 `DiscardAsync` |
| 限流 | store 回 Throttled | SendAsync | `NotIssued`；沒有寄信 |
| 格式錯誤 token | 不符合格式的字串或 null | VerifyAsync | `false`；store 未被呼叫 |
| 驗證參數 | 合格 token | VerifyAsync | store 收到 `SHA-256(raw)` 與注入的 now |

### APP-T33 — 佇列派送（AccountEmailDispatcher）

| 案例 | Given | When | Then |
|---|---|---|---|
| 未知 email | 空使用者清單 | DispatchAsync | 不寄信、不發 token |
| 已驗證（U-01） | `EmailVerifiedAt` 有值 | DispatchAsync | 不寄信、不發 token |
| 未驗證 | 未驗證使用者，大小寫不同的 email | DispatchAsync | 寄出 1 封，收件人為儲存的 email |
| 尚未有分支的用途 | `PasswordReset` | DispatchAsync | 拋出 `ArgumentOutOfRangeException`（C4 前不得靜默略過） |

佇列本身的案例（容量、idle hook）屬於 Infrastructure，見 [Infrastructure 測試](../../Infrastructure/docs/test-suite.md) INF-T31。

## 忘記密碼 C4（會員中心計畫）

| 案例 | 測試位置 | 驗證內容 |
|---|---|---|
| APP-T34 — 重設信與重設步驟（9 案例） | `tests/UnitTests/PasswordResetServiceTests.cs` | 寄出一封信，連結在站台 host、只存 hash、有效期 1 小時；節流時不寄信；寄信失敗會 discard；不可用 token 不寫入；密碼 7 碼與 41 碼、兩次不一致時不消耗 token；成功時傳給 store 的是 token 的 hash 與新 hash；store 回 false 時為 `InvalidLink` |
| APP-T35 — 派送分支 PasswordReset（4 案例） | `tests/UnitTests/AccountEmailDispatcherTests.cs` | 未知 Email 不寄信也不發 token；已驗證帳號寄一封重設信；未驗證帳號也寄；1 小時內的第二次申請不寄。取代 C3 中「沒有分支會拋例外」的案例 |

- 已知驗證缺口：`PasswordResetService` 的 1 小時邊界與 token 過期在單元層以 `FakeTimeProvider` 固定（`Send_mails...` 只檢查 `ExpiresAtUtc`）；真正的時間邊界由 WebIntegration 的 `PasswordResetFlowTests`（TEST-50）覆蓋。
