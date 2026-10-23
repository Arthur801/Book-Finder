# Models 文字測試案例庫

> 查核日期：2026-10-24；基準：`91333c3`；目標：`Models/`。本次只做靜態閱讀，未執行 build、測試、Mermaid renderer、資料庫或外部服務。開始時來源無未提交修改；其他代理既有的 `Controllers/docs/` 不屬本文件範圍。

## Fixture 與執行邊界

純模型案例使用固定 GUID（不同 Book／User 各一個）、UTC `2026-10-24T00:00:00Z`、中文／英文／空白文字及空集合。JSON 使用 JsonDocument，於 Parse 同步完成後釋放；序列化需用 MVC 實際 options 驗證 camelCase，不能用預設 JsonSerializer options 代替 HTTP contract。

Web 案例沿用 [WebFixture](../../tests/WebIntegration/WebFixture.cs)、[CatalogSeed](../../tests/WebIntegration/CatalogSeed.cs)、[AccountFlow](../../tests/WebIntegration/AccountFlow.cs)：Docker Testcontainers disposable pgvector、每測試新 host、collection 串行、清空 disposable tables，OpenAI 使用 fake、背景補齊關閉。以 FakeTimeProvider 控制日期，測試 user A/B 分離；修改回應需登入及 antiforgery header。不得用開發／production DB 或真實 API。

以下已有測試皆指「原始碼有斷言，本次未執行」，不表示通過。待補強／未實作項目不可列為現有 coverage。命令供另次授權執行：

```bash
dotnet test tests/UnitTests/UnitTests.csproj --filter 'FullyQualifiedName~LibraryPatchParserTests|FullyQualifiedName~PageNumberTests|FullyQualifiedName~PageWindowTests|FullyQualifiedName~ContributorDisplayTests|FullyQualifiedName~LoginLinkTests'
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~BookDetailPageTests|FullyQualifiedName~RecommendationApiTests|FullyQualifiedName~LibraryApiTests|FullyQualifiedName~AiHistoryDetailTests|FullyQualifiedName~AiHistoryListTests|FullyQualifiedName~SearchPageTests|FullyQualifiedName~LibraryPageTests|FullyQualifiedName~BookLibrarySectionTests|FullyQualifiedName~AccountPagesTests'
```

第一個 project 不需外部服務；第二個需 Docker 與相容 .NET SDK（見 global.json），只允許 disposable DB；可能產生 build artifacts，因此本文件任務未執行。

## 已有斷言的案例

### M-T01：PATCH 省略、清除與設定（L2；已有測試，本次未執行）

- 目標／規格：[LibraryPatchParser](../LibraryPatchParser.cs)；[API](../../Docs/api/api-spec.md) §4。
- Given：依序準備 `{}`、`{"rating":null}`、`{"readingStatus":"READING","rating":4}`。
- When：呼叫 LibraryPatchParser.Parse(document.RootElement)。
- Then：分別為 Valid(null, Unchanged)、Valid(null, Clear)、Valid(Reading, Set(4))；無 I/O。以 API 執行 `{}` 時 updatedAt 不變，null 清評分且不清狀態。
- 來源：[LibraryPatchParserTests](../../tests/UnitTests/LibraryPatchParserTests.cs) 的 Empty_object／Missing_rating／Rating_null／Status_and_rating；[LibraryApiTests](../../tests/WebIntegration/LibraryApiTests.cs) 的 Empty_object_returns_the_entry_unchanged_and_keeps_updated_at。

### M-T02：PATCH 負面、錯誤聚合與欄名（L2；已有測試，本次未執行）

- 目標／規格：同 M-T01。
- Given：null、陣列、字串；status=null／小寫代碼；rating=0／6／3.0／3.5／字串；兩欄同時無效；未知欄位與大寫欄名。
- When：Parse；另以登入與 CSRF 有效的 PATCH 呼叫合法 Book。
- Then：非 object 為 Invalid 且空 key；其餘錯誤 key 精確為 readingStatus／rating，可同時回報；未知與大小寫不符欄位忽略。API 400 不改資料，不因無 Content-Type 回415；空物件仍200。
- 來源：[LibraryPatchParserTests](../../tests/UnitTests/LibraryPatchParserTests.cs)、[LibraryApiTests](../../tests/WebIntegration/LibraryApiTests.cs)。

### M-T03：頁碼與視窗（L2；已有測試，本次未執行）

- 目標／規格：[PageNumber](../PageNumber.cs)、[PageWindow](../PageWindow.cs)；Catalog §3.3、UI §3.4。
- Given：null、abc、0、-1、2、遠超 Int32 的正整數；totalPages=0／10／11／25。
- When：Parse；For(13,25)、For(99,25)、For(0,25)。
- Then：頁碼依序為1／1／1／1／2／int.MaxValue；0頁空集合，10頁全列，25頁中央為1、省略號、11到15、省略號、25；超頁只 clamp window。無 service／DB 呼叫。
- 來源：[PageNumberTests](../../tests/UnitTests/PageNumberTests.cs)、[PageWindowTests](../../tests/UnitTests/PageWindowTests.cs)。

### M-T04：一般搜尋映射與空值（L2；已有測試，本次未執行）

- 目標／規格：[SearchResultsViewModel](../SearchResultsViewModel.cs)；[Catalog](../../Docs/modules/book-catalog.md) §3。
- Given：CatalogSeed 的作者、出版社、年精度日期、空封面、description／TOC sentinel；含前後空白與 `&` 的 query；另準備零結果及21筆符合結果。
- When：GET /search 的適當 encoded query 與 page=2／超頁。
- Then：只顯示作者角色、年份、trim query；空欄略過；query／頁碼 URL 正確 percent／HTML encode；第二頁總數21且一筆；超頁302最後頁；零結果無 pager／summary；不出現 sentinel。
- 來源：[SearchPageTests](../../tests/WebIntegration/SearchPageTests.cs)。

### M-T05：Book detail、Contributor 與安全來源（L2；已有測試，本次未執行）

- 目標／規格：[BookDetailViewModel](../BookDetailViewModel.cs)、[ContributorDisplay](../ContributorDisplay.cs)；Catalog §4、BOOK-05。
- Given：亂序 ContributorName，Author／Translator／Other；BookDetail 有 ISBN13／10、空白 subjects、空欄、合法來源及 unsafe URL。
- When：GroupByRole；透過 BookDetailPageTests fixture GET /books/{id}。
- Then：依 Order 與角色首次出現順序，標籤六角色對應；未知 role 擲 ArgumentOutOfRangeException；來源只留 http(s)，博客來首筆主按鈕，無博客來改 Google 首筆；空欄略過、簡介／目錄不出現。OTHER identifier 到模型時為 InvalidOperationException，該直接 factory 邊界另需補測。
- 來源：[ContributorDisplayTests](../../tests/UnitTests/ContributorDisplayTests.cs)、[BookDetailPageTests](../../tests/WebIntegration/BookDetailPageTests.cs)；OTHER 直接 factory 斷言為待補強。

### M-T06：Library 三態與跨使用者隔離（L3；已有測試，本次未執行）

- 目標／規格：[LibrarySectionViewModel](../LibrarySectionViewModel.cs)、[LibraryPageViewModel](../LibraryPageViewModel.cs)；[Library](../../Docs/modules/user-library.md) §4–5。
- Given：匿名、登入A未收藏、登入A收藏Reading／4分、B獨有 Entry；filter=READING 與未知代碼。
- When：GET Book detail 與 /library?status=READING。
- Then：匿名只有 pending add 登入連結；未收藏有隱藏預設Controls；收藏有選中狀態／四星；本人讀不到B項目；未知filter顯示全部並active；editLoginUrl保留filter；書目快取不可帶入另一使用者的個人狀態。
- 來源：[BookLibrarySectionTests](../../tests/WebIntegration/BookLibrarySectionTests.cs)、[LibraryPageTests](../../tests/WebIntegration/LibraryPageTests.cs)。

### M-T07：JSON 白名單與時區（L3；已有測試，本次未執行）

- 目標／規格：[LibraryEntryResponse](../LibraryEntryResponse.cs)、[RecommendationResponse](../RecommendationResponse.cs)；API §3–4。
- Given：UTC時間、本人Entry、已排序候選、無profile／已儲存profile兩種 fixture；登入與CSRF有效。
- When：PUT Library；POST recommendations；於worker存profile後再次POST。
- Then：Library camelCase五欄，ReadingStatus為精確代碼、rating可null、時間offset +08:00；推薦包含白名單book、relevance，缺difficulty為null，後續為儲存難度。results可空且≤10由上游保障；目前fallbackUsed=false。不回傳 userId、簡介／目錄。
- 來源：[LibraryApiTests](../../tests/WebIntegration/LibraryApiTests.cs)、[RecommendationApiTests](../../tests/WebIntegration/RecommendationApiTests.cs) 的 Happy_path／First_recommendation／Next_recommendation。全面遞迴型別 guard 尚待 M-T10。

### M-T08：歷史快照、空值與降級（L3；已有測試，本次未執行）

- 目標／規格：[AiHistoryListViewModel](../AiHistoryListViewModel.cs)、[AiHistoryDetailViewModel](../AiHistoryDetailViewModel.cs)；Recommendation §12、UI §3.4。
- Given：A有21筆搜尋、B另有紀錄；固定UTC時間；結果有rank／reason／relevance；改目前Book title；缺profile及讀profile失敗兩種情況。
- When：GET /ai、/ai/history-list?page=超頁、/ai/history/{id}。
- Then：每頁20、按新到舊、台北分鐘時間；整頁超頁302，片段直接最後頁；A不能讀B。title顯示目前值，rank／reason／relevance保留快照；relevance=null省略相關度，profile缺或失敗顯示「—」，成功讀得最新難度；0結果顯示專用空狀態。
- 來源：[AiHistoryListTests](../../tests/WebIntegration/AiHistoryListTests.cs)、[AiHistoryDetailTests](../../tests/WebIntegration/AiHistoryDetailTests.cs)。

### M-T09：表單、登入連結與錯誤資訊（L3；已有測試，本次未執行；Error VM 直接案例待補強）

- 目標／規格：[LoginForm](../LoginForm.cs)、[RegisterForm](../RegisterForm.cs)、[LoginLink](../LoginLink.cs)、[ErrorViewModel](../ErrorViewModel.cs)；Identity §3–6、UI §3.5。
- Given：錯密碼、email、returnUrl含query、pendingAction固定add-to-library；RequestId=null／empty／trace字串。
- When：POST表單失敗；LoginLink.For；直接建ErrorViewModel。
- Then：重顯保留email／hidden欄但password無值；returnUrl僅作一個escaped query值，安全重導由SafeReturnUrl判斷。ShowRequestId依序false／false／true，無stack trace欄位。
- 來源：[AccountPagesTests](../../tests/WebIntegration/AccountPagesTests.cs)、[LoginLinkTests](../../tests/UnitTests/LoginLinkTests.cs)；Error直接斷言待建。

## 待補強與尚未實作

### M-T10：所有公開 DTO／VM 排除私人內容（L3；待補強；M-B01）

- 規格：BOOK-05、API §3–4；入口擴充 UnitTests 新 guard，參考現有 [BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs)。
- Given：architecture 列出的 response／頁面 root type 及自有子模型白名單，含新增型別的刻意失敗 fixture。
- When：遞迴列出 public property，依 MVC options 序列化 response；再執行各頁 sentinel 測試。
- Then：無 Description／TableOfContents 欄位或內容；新增禁欄能使測試失敗；清單增減須顯式維護；不將Password輸入form納入公開response。

### M-T11：封面 URL 政策矩陣（L2；待驗證；M-B02）

- 規格：Catalog §4安全外連、UI各頁；入口擴充 BookDetailPageTests／AiHistoryDetailTests／SearchPageTests。
- Given：null、空白、relative、javascript、`HTTP://example.test/a`、`https://example.test/a`、`https://`。
- When：以同一Book fixture經各From及對應View渲染。
- Then：先記錄現況差異，不把尚未決定的統一policy寫成pass標準；現有BookDetail必須拒絕非絕對http(s)，未知需求先決策。統一後以核准矩陣驗收所有入口，無真實HTTP請求。

### M-T12：fallback flag 與候選門檻（L3；未實作；M-B03）

- 規格：Recommendation §2、§6、§8；入口 RecommendationApiTests，Google Books fake 與相關情境待建。
- Given：候選數4／5，Google fake回可normalize的書，固定embedding與門檻；另配置quota用完及外部失敗。
- When：呼叫POST recommendations。
- Then：5筆不fallback；4筆依規格補齊後過同硬條件與門檻，fallbackUsed反映實際使用；達上限無外部呼叫；失敗無Search保存。不得用目前固定false當完成證據。

### M-T13：Pager 工廠獨立邊界（L2；待補強；M-B04）

- 規格：Catalog §3.3、UI §3.4；UnitTests 新PagerViewModelTests待建。
- Given：urlFor(p)回固定 `/test?page=p` 並記錄參數；(current,total)為(1,0)、(1,1)、(2,3)、(99,3)。
- When：PagerViewModel.For。
- Then：0頁無鏈結；1頁current項無URL且previous／next=null；2/3有previous1／next3；99/3 previous最多3、無next，CurrentPage仍99且無current頁標記，記錄caller前置條件而不擅自改factory。callback不接受null省略號。

另有 Bestseller 原rank／空狀態／台北更新時間由 [BestsellerPageTests](../../tests/WebIntegration/BestsellerPageTests.cs)、[LayoutAndHomeTests](../../tests/WebIntegration/LayoutAndHomeTests.cs)、[TaipeiTimeZoneTests](../../tests/UnitTests/TaipeiTimeZoneTests.cs) 覆蓋相關斷言，本次未執行；模型無持久化，DB constraints 案例應歸 Entity／Infrastructure 文件，不在此重複。

相關文件：[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [測試案例](test-suite.md)。
