# Controllers：面向 AI 的文字測試案例庫

版本日期：2026-10-24；程式基準：`91333c3`。用途：讓後續 AI 能依固定資料、操作與斷言補寫或執行測試。這是案例規格，不是測試執行報告，也不取代 [test-plan.md](../../Docs/testing/test-plan.md)、[api-spec.md](../../Docs/api/api-spec.md) 與各 module 規格。

## 1. 使用規則與測試環境

1. 先選案例，再讀對應 Controller、module 及列出的測試檔；不為局部案例預載所有文件。
2. 下表的每一列均為獨立案例；含多個輸入的列要拆為參數化測試，每筆資料獨立 reset。共同前置條件與各列的 Given 合併使用。
3. 只使用 `tests/WebIntegration/WebFixture.cs` 的 disposable pgvector Testcontainer 與 EF migrations。`ResetDatabaseAsync` 只對 fixture DB 執行，禁止拿開發／production connection string 替代。
4. 每案以 fresh `BookFinderFactory` 隔離 IMemoryCache；只有 cache 案例刻意在同一 factory 內連續請求。collection 依現有 `WebCollection` 序列執行。
5. HTTP client 使用 `https://localhost`、`AllowAutoRedirect=false` 與各自 cookie container；驗 302 時檢查 Location，不讓自動重導掩蓋原回應。
6. A、B 表示不同已註冊使用者；驗登入流程以外的案例可沿用 `AccountFlow` helper。unsafe requests 預設已登入且提供同一 session 的合法 CSRF header；只有認證／CSRF 案例刻意移除。表單 POST 使用 hidden token。
7. 外部 adapter 使用 `FakeRequirementParser`、`FakeEmbeddingGenerator`、`FakeRecommendationRanker`、`FakeBookProfileGenerator`，讀 Calls 驗證沒有額外呼叫。背景 embedding 關閉。Google Books 目前尚無接入流程，future 案例須待 adapter 完成後才可驗證呼叫數。
8. 用 `FakeTimeProvider` 推進 Taipei 午夜或 60 秒 budget，不實際等待一分鐘。profile worker 的結果用可等待的測試同步條件，不靠任意 sleep 猜測。
9. 同時斷言 HTTP、資料庫前後差異、fake calls；validation / 未授權 / 未找到案例不能只驗 status。API 錯誤應驗 `application/problem+json`、`status`、`type`、非空 `traceId`；validation 另驗 `errors` key。204 不驗 JSON。
10. status 定義：**已有測試**＝找到相應自動化案例，未在本次重跑；**待補強**＝現有檔案是擴充入口，尚無此完整斷言的通過證據；**未實作／暫緩**＝未來驗收，不得報通過。

基本測資：Book `B1`、`B2` 使用不同 GUID；`U` 為不存在 GUID；`bad` 為 `not-a-guid`。私有欄位 sentinel 用 `PRIVATE_DESCRIPTION_SENTINEL`、`PRIVATE_TOC_SENTINEL`。AI 向量為 1536 維，可控制 similarity；候選門檻讀測試設定，不憑模型實際結果判斷。

## 2. 共用認證與錯誤管線

依據：identity-auth §5、API §1–2。入口：`AuthPipelineTests.cs`、`ApiExceptionProblemDetailsFilterTests.cs`（後者在 UnitTests）。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| PIPE-01／已有測試 | 無 cookie；GET 需登入頁，帶 page 或 status query | 302 登入；returnUrl 解碼後等於原 path/query；不是 API 401。 |
| PIPE-02／已有測試 | 無 cookie；POST 需登入頁（如登出） | 302 `/account/login`，沒有 returnUrl；不把 POST-only 路由拿去 GET。 |
| PIPE-03／待補強（HTTP 已有測試，本次未執行） | 無 cookie；呼叫受保護 API | 401 `/errors/unauthenticated`、無登入 redirect 的 HTTP 斷言已有來源；完整 production endpoint 矩陣的 DB 不變／依賴未呼叫需逐項補證，不能由 test-only status 推論。 |
| PIPE-04／已有測試 | 有效 cookie、僅 Bearer header、錯簽章、破損 token 各自請求 | 僅有效 cookie 驗證成功；其餘視為匿名；Bearer header 不能代替 cookie。 |
| PIPE-05／已有測試 | fake clock 在簽發後一天前一秒及剛好一天，讀 protected page / API | 前者有效；到一天立即過期，頁面 302／API 401；無 ClockSkew 寬限。 |
| PIPE-06／待補強（HTTP 已有測試，本次未執行） | 已登入 API 缺 CSRF header 或使用另一 session 的 token | 400 `/errors/antiforgery` 已有來源；推薦缺 header 的外部 calls、Library 缺 header 的資料不變另有案例。跨 session／所有 production endpoints 的 service call 與副作用矩陣仍待補強。 |
| PIPE-07／已有測試 | 表單 POST 缺 token；再以同 session 合法 token 重試 | 缺少時框架 400；合法時才進 action。不要要求頁面錯誤一定是 problem+json。 |
| PIPE-08／已有測試 | API action 拋 AiUnavailableException／AiTimeoutException／一般例外 | 分別為 502 `ai-unavailable`、504 `ai-timeout`、500 `internal`；無 stack trace／secret。 |
| PIPE-09／已有測試 | RequestAborted 已取消，在 API exception filter 測試中傳入例外 | filter 不吞取消、不建立 500 result；不是 AI timeout 的替代情境。 |

PIPE-03／PIPE-06 證據分層（均未在本次執行）：[AuthPipelineTests](../../tests/WebIntegration/AuthPipelineTests.cs) 主要驗證 test-only endpoint 的 HTTP status／ProblemDetails。production [RecommendationApiTests](../../tests/WebIntegration/RecommendationApiTests.cs) 的 `Not_signed_in_returns_401_and_calls_no_external_service`、`Signed_in_request_without_antiforgery_header_returns_400_and_calls_no_external_service` 斷言 parser／embedding／ranker Calls 為零，未直接斷言 Search DB rows 或 spy service 入口。[LibraryApiTests](../../tests/WebIntegration/LibraryApiTests.cs) 的 `Not_signed_in_returns_401_and_saves_nothing`、`Signed_in_add_without_antiforgery_header_returns_400_and_saves_nothing` 斷言 Entry count 為零；`Patch_and_delete_without_antiforgery_header_return_400_and_change_nothing` 讀回既有 Entry rating 未變。這些局部斷言不等於所有資料／依賴皆無副作用。

## 3. HomeController 與 BestsellersController

依據：bestseller §2–7。入口：`BestsellerPageTests.cs`、`LayoutAndHomeTests.cs`、`CachedBestsellerReaderTests.cs`（UnitTests）。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| BEST-01／已有測試 | seed 100 筆 rank；GET `/` 與 `/bestsellers` | 首頁前 10 筆，完整頁 100 筆、不分頁；皆依 rank 原值排序。 |
| BEST-02／已有測試 | 前十名內缺一 rank、仍有 rank 11；讀兩頁 | 首頁仍取排序後 10 筆，包含 11；缺號保留、不重編。 |
| BEST-03／已有測試 | 空榜；讀兩頁 | 200、顯示「榜單尚未建立」，不變成伺服器錯誤。 |
| BEST-04／已有測試 | 作者／譯者混排、固定 captured_at；讀榜單 | 僅 AUTHOR 依 contributor_order 顯示；書連到 detail，時間顯示 Taipei。 |
| BEST-05／已有測試 | 在 reader unit test 用 fake clock 暖快取並改底層資料 | 非空 1 小時、空榜 5 分鐘；到期重新讀；Controller 不另維護一份 cache。 |
| HOME-01／待補強 | 直接讀 `/Home/Error`；另在非 Development host 注入頁面 action 例外 | 兩者分開記錄 status；Error 有 RequestId、NoStore，不回傳 stack trace；原始例外由 exception handler 處理。 |

## 4. SearchController

依據：book-catalog §3。入口：`SearchPageTests.cs`，純規則見 `SearchQueryTests.cs`、`PageNumberTests.cs`。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| SEARCH-01／已有測試 | q 缺少、空白或只有空格 | 200 空狀態、不列全部 Book、不呼叫 embedding／LLM／Google Books。Google 未接入前以依賴與 calls 檢查為限。 |
| SEARCH-02／已有測試 | ISBN 含連字號、空白、小寫 x 或全形字元；另有 OTHER identifier 相同值 | 只命中正規化後相應 ISBN_10／ISBN_13；不命中 OTHER、不互轉 10／13。 |
| SEARCH-03／已有測試 | 12 位數字 q；Book ISBN_13 以此為前綴 | 不當作 ISBN 精確命中該 Book。 |
| SEARCH-04／已有測試 | q 是書名片段或 contributor 名片段；另有僅 description／publisher 命中者 | 只命中 title／contributor；原 q 整段比較，不搜尋 description／publisher。 |
| SEARCH-05／已有測試 | q 含 `%`、`_`、反斜線 | 當字面字元，不能擴大成 LIKE wildcard。 |
| SEARCH-06／已有測試 | 精確書名、不同日期、NULL 日期且都命中 | 精確書名（不分大小寫）優先，再日期 DESC、NULL 最後；同條件穩定排序。 |
| SEARCH-07／已有測試 | 21 筆命中；讀 page 1、2 | 分別 20、1 筆，總數 21；pager 不產生末頁以外連結。 |
| SEARCH-08／已有測試 | page 非整數、0、負數；另以超過 64-bit 正整數請求非空結果 | 前者第 1 頁；超大值 302 最後頁，q 保留且編碼正確。 |
| SEARCH-09／已有測試 | 查無結果但 page 超大 | 200 空狀態、不重導、不顯示 pager。 |
| SEARCH-10／已有測試 | q 含 HTML 特殊字元；seed 私有 sentinel | raw HTML 中 q／連結正確編碼；不包含 description／TOC sentinel；頁面預填 trim 後 q。 |

## 5. BooksController

依據：book-catalog §4–5、BOOK-05、user-library §5。入口：`BookDetailPageTests.cs`、`BookLibrarySectionTests.cs`、`BookDetailContractTests.cs`（UnitTests）。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| BOOK-01／已有測試 | detail 的 id 為 bad 或 U | 同類型 404 NotFound View；不是 200 錯誤文案。 |
| BOOK-02／已有測試 | B1 有基本資料，日期精度 YEAR／MONTH／DAY、缺少選填欄位 | 分別顯示年／年月／年月日；缺值整列省略；無封面有 placeholder；標題為書名。 |
| BOOK-03／已有測試 | 多角色 contributors、多來源 ISBN／subjects | 依角色與 contributor_order 分組；只顯示 ISBN_13／ISBN_10；分類去空白並排序。 |
| BOOK-04／已有測試 | 匿名、A 未加入、A 已加入、僅 B 加入四種狀態 | 匿名登入連結帶 pendingAction；A 未加入有按鈕；A 已加入顯示本人狀態／評分；B 的 Entry 不讓 A 看見。完整同 cache 多 session 場景見 DBG-04。 |
| BOOK-05／已有測試 | 多個博客來來源與 Google 來源，包括 javascript／非絕對 URL | 只產生 http(s) 絕對連結；最早合格博客來優先，否則 Google；新分頁且 rel 有 noopener noreferrer；危險封面用 placeholder。 |
| BOOK-06／已有測試 | 任一來源 Book 的 description／TOC 有 sentinel | HTML 不含 sentinel；公開 ViewModel／JSON contract 不含兩欄位，不因來源不同而放寬。 |
| BOOK-07／已有測試 | 同一 app 讀 detail、改 DB 書名、TTL 內再讀 | 書目仍是快取值；個人 Library 狀態不可納入此斷言。TTL 邊界另由 CachedBookDetailReader unit tests 驗證。 |

## 6. AccountController 與登入待辦

依據：identity-auth §3–6。入口：`AccountPagesTests.cs`、`PendingLibraryActionTests.cs`；邊界 pure rules 在 `AccountInputRulesTests.cs`、`SafeReturnUrlTests.cs`、`PendingLibraryActionTests.cs`（UnitTests）。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| AUTH-01／已有測試 | 註冊密碼 7、8 字元；unit rules 再測 40、41 | 7／41 拒絕；8／40 可通過密碼長度規則；成功註冊寫 hash 而非明文並直接登入。 |
| AUTH-02／已有測試 | 已有 `A@x.com`，註冊 `a@x.com`；登入用錯密碼／不存在 email | 重複 email 欄位錯誤；兩種登入失敗統一「帳號或密碼錯誤」，不透露帳號是否存在。 |
| AUTH-03／已有測試 | 正確登入或註冊 | cookie 為 HttpOnly、Secure、SameSite=Lax、Path=/；有效期一天；後續 protected request 可驗證。 |
| AUTH-04／已有測試 | returnUrl 為本站 path、外站 URL 或不安全變體 | 只導向 Url.IsLocalUrl 接受的本站值；其餘回 `/`。 |
| AUTH-05／已有測試 | 已登入 GET login／register；POST logout | GET 回 `/`；logout 刪 cookie 並回 `/`；下一次 protected page 需登入。已登入 POST 分支可另補強。 |
| AUTH-06／已有測試 | 登入或註冊驗證失敗，附 returnUrl／pendingAction | 重顯欄位錯誤並保留 email／回跳資訊；HTML 不含原密碼。 |
| AUTH-07／已有測試 | 正確登入／註冊，待辦是 add-to-library，returnUrl 精確 `/books/{D GUID}` | cookie + 302 原 Book；Entry 為 WANT_TO_READ、rating null；原有 Entry 不變。 |
| AUTH-08／已有測試 | 未知 action、非 Book path、query／fragment／尾斜線／非標準 GUID 變體 | 登入照常成功；不執行待辦；仍按安全 returnUrl 規則導向。精確 path 變體主要由 pure unit cases 驗證。 |
| AUTH-09／待補強（登入結果已有測試，本次未執行） | 待辦 Book 不存在或 Library store 拋一般例外 | 仍發 cookie 與 redirect 已有 Web 案例；一般失敗不拋出、caller cancellation 傳遞有 unit 來源。Warning 與 log 不含 email／password／JWT 的完整斷言待建，不能以登入成功視為已驗證。 |
| AUTH-F01／暫緩 | 同 IP 登入／註冊第 6 次；不同 IP／window | 目標為每 IP 每分鐘 5 次後 429；共用額度／成功計數須先決策，現階段不得宣稱已通過。見 CTL-02。 |

AUTH-03 的 cookie 屬性與 max-age 證據為 [AuthCookieTests](../../tests/UnitTests/AuthCookieTests.cs)；登入／後續 protected request 另查 [AccountPagesTests](../../tests/WebIntegration/AccountPagesTests.cs) 與 AuthPipelineTests。AUTH-09 的 [PendingLibraryActionTests](../../tests/WebIntegration/PendingLibraryActionTests.cs) 驗證 Book 不存在／store 拋例外仍有 Set-Cookie 與 redirect；[LibraryServiceTests](../../tests/UnitTests/LibraryServiceTests.cs) 使用 NullLogger，未驗 Warning／敏感內容。後續須用 recording logger 補 Warning level 與敏感資料排除斷言。

## 7. LibraryController 與 LibraryApiController

依據：user-library §2–5、API §4。入口：`LibraryPageTests.cs`、`LibraryApiTests.cs`；PATCH pure cases 在 `LibraryPatchParserTests.cs`。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| LIB-01／已有測試 | A、B 各有 Entry；GET `/library` | 只有 A 資料，updated_at 新到舊、不分頁；空時有「還沒有加入任何書」與榜單連結。 |
| LIB-02／已有測試 | status 缺少／未知／三個有效大寫代碼 | 缺少與未知看全部；有效代碼只顯示相應狀態，tab active 正確；edit login URL 保留 filter query。 |
| LIB-03／已有測試 | A 對存在 B1 PUT，無 body | 200 Entry shape：bookId、readingStatus、rating、addedAt、updatedAt；預設 WANT_TO_READ／null；時間 +08:00；DB 一筆。 |
| LIB-04／已有測試 | A 的 B1 已 READING／rating 4；重複 PUT | 200 同一 Entry；不改狀態、評分、addedAt／updatedAt，不新增 duplicate。 |
| LIB-05／已有測試 | PUT bad 或 U | 404 `/errors/not-found`，無新增；B 的 Entry 不會被當作 A 的 Entry 使用。 |
| LIB-06／已有測試 | PATCH 含有效 readingStatus／rating，分別或同時送 | 200 與 PUT 同 shape；只改指定欄位，更新 updatedAt；任何 Reading Status 都可評分。 |
| LIB-07／已有測試 | rating 原為 4；PATCH 省略 rating、明確 null 分別測 | 省略保留 4；null 清除；`readingStatus:null` 不可清除而回欄位 validation 400。 |
| LIB-08／已有測試 | rating 為 0、6、小數、`3.0`、字串、bool | 400 `errors.rating`；body 其他有效欄位也不得部分寫入；原 Entry 不變。 |
| LIB-09／已有測試 | readingStatus 小寫／未知字串／數字／null | 400 `errors.readingStatus`，不修改任何欄位。 |
| LIB-10／已有測試 | PATCH 空 body、破損 JSON、陣列、字串等非物件 | 400 `/errors/validation`，`errors[""]` 表示整體 body，不變成未定義 500。 |
| LIB-11／已有測試 | PATCH 合法或破損 JSON，不帶 Content-Type 或帶 text/plain | 一律嘗試 JSON 解析；合法物件依欄位處理，破損 JSON 整體 body 400，不因 header 回 415。 |
| LIB-12／已有測試 | PATCH `{}` 或僅未知欄位；另測把狀態設為原值 | no-op 原樣回傳、updatedAt 不變；有效欄位明確設同值仍更新 updatedAt。未知欄位不成為可寫 userId。 |
| LIB-13／已有測試 | PATCH bad、A 無 Entry、只有 B 有 Entry | 404；B 的 Entry 內容完全不變；使用者只來自 JWT。 |
| LIB-14／已有測試 | A DELETE 已有 Entry，再 DELETE 一次；另測 bad／U／僅 B 有 Entry | 每次 204、body 空；A 的 Entry 與 rating 消失；bad 不碰 store，B 資料保留。 |
| LIB-15／已有測試 | PUT／PATCH／DELETE 分別移除登入或 CSRF | 無登入 401；已登入缺 CSRF 400；無 DB 變化，不能用 DELETE 冪等語意繞過 Authorize。 |

## 8. RecommendationsController

依據：API §3、recommendation §2–13。入口：`RecommendationApiTests.cs`、`RecommendationServiceTests.cs`、`RankingRulesTests.cs`、`EfCandidateSearchTests.cs`。下層案例仍列在此處，因其結果是 endpoint contract 的必要證據。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| AI-01／已有測試 | 匿名，或已登入但缺 CSRF，POST 合法需求 | 分別 401／400；所有推薦 fake Calls 為 0；不保存搜尋。 |
| AI-02／已有測試 | requirementText 缺少、null、空白、body 空或破損 | 400 `/errors/validation`，`errors.requirementText`；不呼叫 parser／embedding／ranker。額外 binding 變體見 DBG-01。 |
| AI-03／已有測試 | trim 後 500／501 code points，另以 emoji 驗 pure rules | 500 接受、501 拒絕；用 code points 而非 UTF-16 Length 計算；送入 service 的文字已 trim。 |
| AI-04／已有測試 | 有效需求與可控候選、ranker 回合法順序 | 200 含 searchId、createdAt +08:00、fallbackUsed、results；每筆 rank、book、reason、relevance、difficulty；DB 一份 Search 與對應 Results。目前 fallbackUsed=false。 |
| AI-05／已有測試 | 有作者硬條件；另有滿足硬條件但 similarity 低於 T 的 Book | 只有同時滿足兩者者可送 ranker／出現在 response；不相關書不進候選。 |
| AI-06／已有測試 | ranker 回非候選、重複、空理由、超過 10 筆、超範圍 relevance | 非候選／空理由丟棄；重複保留第一次有效；最多 10，rank 重新編 1..n；relevance 依 RankingRules 正規化。不得用 Bestseller rank 或 profile 排序。 |
| AI-07／已有測試 | 本地候選 0；目前尚無 fallback | 不呼叫 ranker；200 空 results，仍保存成功搜尋並計入當日。未來接 fallback 後改為 fallback 重檢仍為 0 的情境。 |
| AI-08／已有測試 | parser／embedding／ranker 各注入 AI unavailable | 502 `/errors/ai-unavailable`；不執行後續步驟，不保存 Search／Results。 |
| AI-09／已有測試 | 保存前核心依賴拋一般例外 | 500 `/errors/internal`，沒有 stack trace；保存前失敗不存 Search。post-save 一般 enrichment 失敗降級，caller 取消則屬 AI-11，不由此案例推定資料未保存。 |
| AI-10／已有測試 | 保存前 parser／ranker fake 工作尚未完成，推進 60 秒 | 504 `/errors/ai-timeout`；無 Search／Results，不計額度；不是只測 parser 自訂逾時訊息。 |
| AI-11／待補強 | client cancellation 與 60 秒 timeout 分別觸發，覆蓋保存／保存後邊界 | 依 CTL-07：取消不偽裝成 AI timeout；已保存後一般 difficulty／queue 失敗降級，caller cancellation 可傳遞但已存 Search／Results 保留。commit 交界需查 DB/outcome，維持待補強，不只看 response。 |
| AI-12／已有測試 | A 今日已有 20 次成功搜尋，另有昨日搜尋與 B 今日搜尋 | A 下一次 429 `daily-limit-exceeded`，所有外部 fake 不呼叫；昨日與 B 不計入 A 今日。 |
| AI-13／已有測試 | clock 從 Taipei 23:59:59 推到 00:00 | 新一天額度重設；failed search 不計數，0 結果成功搜尋仍計數。 |
| AI-14／已有測試 | 無 profile，但 generator 立即回覆；推薦一次再等 worker 完成後再推薦 | 首次 difficulty 為 null（先讀快照再排隊）；後次可見儲存的 difficulty；profile 不改書籍簡介／目錄。 |
| AI-F01／未實作 | 本地候選 5、4、0 本，分案測 | 5 本不呼叫 Google；4／0 本才呼叫；以 fake 驗 calls，不能因固定 false 而報通過。 |
| AI-F02／未實作 | Google volume 包含既有 ISBN、新書、低 similarity、缺 embedding | normalize 並寫入；ISBN 去重；補 embedding 後重跑同一檢索，僅通過硬條件／門檻者進 Candidate Set。 |
| AI-F03／未實作 | Google 失敗或逾時；本地仍有候選 | 本地候選繼續排序；fallback 行為／flag 符合規格；不因 Google 失敗就把推薦整次視為 OpenAI 502。 |

## 9. AiController 歷史頁與片段

依據：UI §3.4、recommendation §12。入口：`AiPageTests.cs`、`AiHistoryListTests.cs`、`AiHistoryDetailTests.cs`。

| ID / 狀態 | Given / When | Then |
|---|---|---|
| HIST-01／已有測試 | A、B 均有搜尋；GET `/ai` | 僅列 A，新到舊；表單、results、history 區塊存在；URL 中 requirement 查詢不被當作輸入。 |
| HIST-02／已有測試 | A 有 21 筆；讀第 1／2 頁、非法 page、超大 page | 20／1 筆；非法 page 第 1 頁；超頁完整頁 302 末頁；日期 Taipei，列含需求、結果數、detail link。 |
| HIST-03／已有測試 | 同一資料分別讀 `/ai` 及 `/ai/history-list`；另讀 fragment 超頁 | partial 不含 layout，與完整頁 history 區塊一致；超頁回末頁 HTML 200，不回 302。 |
| HIST-04／已有測試 | A 無搜尋，以正常／超大頁讀列表 | 顯示「還沒有 AI 搜尋紀錄」、無 pager；不導向不存在末頁。 |
| HIST-05／已有測試 | 讀本人搜尋，再改 Book 書名並再讀 | 保留原 rank／reason／relevance；書名、作者、封面取目前 Book；不是把所有 metadata 都當搜尋快照。 |
| HIST-06／已有測試 | 本人 0 結果搜尋；他人 id／U／bad 分別讀 detail | 本人顯示「這次沒有找到符合的書」；其他三種相同 404，不透露是否存在。 |
| HIST-07／已有測試 | profile 尚無值、後來新增；再注入 profile read 一般失敗 | 沒值顯示「—」；下次讀即見 difficulty；一般失敗仍 200 與原 results，只降級 difficulty。 |
| HIST-08／已有測試 | 匿名讀三個 AI 頁面入口 | 均 302 login 並保留原 path/query；history detail 不會先透露他人資料。 |

## 10. 內容洩漏與瀏覽器邊界

| ID / 狀態 | Given / When | Then / 驗證入口 |
|---|---|---|
| CONTENT-01／待補強 | 對 B1 注入兩個 private sentinel；讀所有會顯示書籍的頁面、推薦 JSON、歷史 partial/detail | raw response 與 JSON property 全面檢查，不含 description／TOC；理由不可大段照抄；現有 Book／Search／DTO 測試只是部分證據，需跨頁覆蓋。 |
| UI-01／待補強 | 在瀏覽器首頁填 AI 需求，登入後進 `/ai` | 需求透過 sessionStorage 預填後清除，URL／returnUrl 無需求；Web tests 只能驗 markup，不足以證明實際 JS 流程。 |
| UI-02／待補強 | 瀏覽器送推薦，分別成功／0 本／429／502／504 | loading 與 disabled 可恢復；成功刷新 page=1 history 並改回 `/ai`；失敗保留輸入與原列表。 |
| UI-03／待補強 | Library 控制項遇 401、修改篩選列狀態、移除最後一本 | 401 回登入；加入帶待辦；篩選列修改後保留至重整；移除最後列顯示空狀態。MVP 不新增 E2E framework，可在授權後做人工瀏覽器驗證。 |

## 11. Debug 專用調查案例

這些案例是觀測計畫，未有實際重現結果。預期規格未定義的部分要先記錄結果，不能自動「修正」為 AI 偏好的行為。

| ID / 待辦 | Given / When | 要收集的證據與結案條件 |
|---|---|---|
| DBG-01／CTL-05 | 推薦 body 型別錯誤、非 JSON Content-Type、合法欄位後多餘 JSON token | status／media type／errors、fake Calls、DB 搜尋差異；分開記錄 binding 400 與 formatter 415，確認 contract 後才決定修正。 |
| DBG-02／CTL-06 | 未知 API path、錯誤 HTTP method、超限 body、非 action 階段失敗 | 完整 status／body／traceId；判斷是否走到 MVC filter；不得直接要求所有 404 都回 resource not-found。 |
| DBG-03／CTL-07 | 注入 cancellable store 與 profile steps，在保存前／後取消 | transaction commit 狀態、Search／Results 計數、clock、日額度與 log；區分 request cancellation／server timeout。 |
| DBG-04／CTL-08 | 同 factory 先匿名暖 B1 書目，再 A／B 輪流讀取與修改 Entry | metadata cache 可共用，Library 全程只反映當前人且即時變化；匿名 Library store Calls=0。 |
| DBG-05／CTL-09 | conventional actions 使用 GET／HEAD／合法 CSRF 的 POST 等方法 | 實際 endpoint method metadata、status、body、Allow header；先盤點再決定是否限縮 methods。 |
| DBG-06／CTL-10 | fake history 讓 fragment 第一次超頁、第二次資料清空或新增 | ListAsync 呼叫參數／次數、ViewModel pager、HTML；不 crash、不導向迴圈；必要修正須維持已定義空態與分頁規則。 |

## 12. 後續執行方式與結果格式

本次只建立文件，**未執行下列命令**。未來獲准測試時，在 repository root 執行；Testcontainers 需要本機 Docker，且不得換用現有正式 DB。

```bash
dotnet test tests/UnitTests/UnitTests.csproj
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~RecommendationApiTests'
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~LibraryApiTests'
dotnet test tests/WebIntegration/WebIntegration.csproj --filter 'FullyQualifiedName~AiHistory'
dotnet test tests/WebIntegration/WebIntegration.csproj
```

依案例可再執行 `tests/DatabaseIntegration/DatabaseIntegration.csproj` 的受影響測試。不以只跑 UnitTests 代表 HTTP pipeline 通過，也不以 Web tests 代表 production 或真實 AI 品質驗證。

每次報告至少包含：案例 ID、commit、執行命令、fixture／fake 設定、預期值、實際值、HTTP＋DB＋Calls 證據、PASS／FAIL／NOT RUN／BLOCKED，以及未覆蓋的範圍。若是調查案例，先寫觀測結果與對照的規格，不虛構通過結果。
