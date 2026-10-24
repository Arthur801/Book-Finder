# Models 架構與選型

> 查核日期：2026-10-24；基準：`91333c3`；目標：`Models/`。本次只做靜態閱讀，未執行 build、測試、Mermaid renderer、資料庫或外部服務。開始時來源無未提交修改；其他代理既有的 `Controllers/docs/` 不屬本文件範圍。

## Authority 與責任

命名以 [CONTEXT](../../CONTEXT.md) 為準；Book 為 edition、Library Entry 為書單項目，Candidate Set 不等同搜尋結果。公開 JSON 以 [API](../../Docs/api/api-spec.md) §3–4 為準，顯示以 [UI](../../Docs/ui/ui-flow.md)、[Catalog](../../Docs/modules/book-catalog.md) §3–4、[Library](../../Docs/modules/user-library.md)、[Recommendation](../../Docs/modules/recommendation.md) §12、[Bestseller](../../Docs/modules/bestseller.md) 為準。認證表單見 [Identity](../../Docs/modules/identity-auth.md) §3–6。

Models 是 HTTP／Razor 的表示層，從 Application read model 或已完成 use case 的結果投影；Domain enum 可被引用，但這不使 record 成為持久化 entity。真正 entity 在 [Domain/Entities](../../Domain/Entities)，EF 設定在 [Infrastructure/Persistence](../../Infrastructure/Persistence)。更改此目錄不等於需要 migration。

完整 caller、入口、來源檔及 mapping 分支見 [流程](workflow-diagram.md)。此層沒有 DI service 註冊；static helper／record factory 由 Controller 直接使用。輸出分 Razor ViewModel、JSON Response、輸入表單與 Request、純 parser／formatter 四群。

## Contract 對照

| 群組 | 來源 → 主要公開資料 | 使用者與限制 |
|---|---|---|
| BookDetail／Contributor | Application BookDetail → 基本書目、角色分組、InfoRows、外連 | 不含簡介／目錄；ISBN reader 必須排除 OTHER |
| Search／Pager／PageNumber | BookSearchPage → Query、Items、TotalCount、Pager | 只做顯示映射；搜尋規則與 Local DB 存取屬 Application |
| 書庫／首頁列表 | BookBrowsePage、BookBrowseItem、BookSearchHit → BookListItemViewModel、BookBrowseViewModel、HomeViewModel | 不依 Bestseller rank；列項不含簡介／目錄；空 Catalog 的 SummaryText 為 null |
| AI history list／detail | RecommendationSearchPage／Detail + difficulty dictionary → 展示文字、頁碼、結果 | 本人隔離先由 history reader／Controller 保證；VM 不做授權 |
| Library page／section／controls | 本人 LibraryItem／LibraryEntry → tabs、rows、edit state | 使用者區塊不得加入共享 catalog cache |
| Recommendation request／response | nullable requirementText → Application 驗證；Outcome → 明列 response 欄位 | 外部服務 gate、Candidate Set、20 次限制不在 DTO |
| Library parser／response | JsonElement → LibraryChange；Entry → 精確 JSON 欄位 | 省略／null／Set 分開，未知欄位忽略 |
| Account forms／LoginLink | nullable 表單欄位與 returnUrl／pendingAction | AccountInputRules、SafeReturnUrl、PendingLibraryAction 執行安全政策 |
| Error | RequestId → ShowRequestId | 追蹤編號可顯示，例外堆疊不屬此模型 |

## 選型與代價

ADR 是已接受決策；以下「程式可見」項目是從 code 推得的選擇，原作者完整理由未記錄；替代方案是本次分析，並非新增核准決策。

| 面向 | 現況與依據 | 替代方案差異 | 代價與維護重點 |
|---|---|---|---|
| 表示層分離 | 明列 sealed record，而非直接序列化 Entity；BookDetail／RecommendationResponse | 直接回 Entity 減少映射，但擴大欄位洩露與循環導覽風險 | 新欄位須同步 factory、View／JS、API 與測試；record 不會自動驗證內容 |
| 表單驗證 | LoginForm／RegisterForm 無 DataAnnotations，AccountService 驗證；程式註解明述 | annotation 可貼近 binding，但容易與 Application 規則重複 | nullable 表單允許無效輸入進入 service，由同一套規則產生欄位錯誤 |
| PATCH 三態 | JsonElement property-by-property + RatingChange union；parser 註解明述 binding 不能分省略與 null | nullable short DTO 會遺失資訊；Optional wrapper 可表達但增加 converter | 保留大小寫、整數字面值與兩欄錯誤聚合；parser 不保留 JsonElement |
| enum 表示 | Domain enum 在 View，API 透過 ReadingStatusCode 轉字串 | 全域 enum converter 影響所有 endpoints | mapping 明確；未知 enum 的錯誤仍須由來源規則攔截 |
| 集合與 null | IReadOnlyList + ToList；不同欄位按展示需求轉 null | ImmutableArray 可增加深不可變保證 | IReadOnlyList 不保證底層不可修改；現有工廠不修改輸入，使用者仍需遵守前置條件 |
| 共用分頁 | PageWindow 純規則 + PagerViewModel + URL callback；894883b | 每個列表自建容易漂移 | 頁碼正規化／重導屬 Controller，避免誤認 PageWindow clamp 會修改 Pager.CurrentPage |
| 時間 | Application/Common/TaipeiTimeZone；9b0a8a1、982ad1c | 各 VM 自轉換或瀏覽器在地化會分散政策 | API offset +08:00、HTML 分鐘精度；輸入 UTC Kind 契約須留意 |
| URL 安全 | BookDetail 用 Uri；AI history 用前綴；其餘多直接帶來源 thumbnail | 共用 helper 可統一政策，但可能改變既有可顯示內容 | 不先假定同一政策已通用；M-B02 先查核及決策 |
| cache 與個資 | [ADR-005](../../Docs/architecture/architecture-decisions.md)：catalog process cache；BooksController 另傳 Library Section | 將個人狀態併入共享模型易跨使用者洩露 | Models 無 cache；保留 anonymous 不讀 Library store 的邊界 |
| SSR 與 cookie | [ADR-004](../../Docs/architecture/architecture-decisions.md)：Razor + HttpOnly JWT + antiforgery | localStorage／SPA 改變 token 與部署邊界 | 此任務不改認證政策；DTO 不應承擔 token 簽發或 CSRF 檢查 |

## 資料、安全與失敗邊界

description／table of contents 不得出現在任何頁面／JSON（BOOK-05）；應使用欄位白名單、HTML sentinel 與型別檢查交互保護，不能把目前 BookDetailContractTests 當所有 Models 的 guard，該測試只掃 Application.Catalog 的 BookDetail* 型別。

RecommendationResponse 的 Difficulty 是成功儲存後取得的字典快照；history 的 Difficulty 則即時讀取，缺 profile 或降級結果顯示「—」。模型不會產生 profile 或推測難度，rank／reason／relevance 不從 profile 重新算。DTO 不自行限制結果筆數或過濾候選；上游必須已完成規則驗證。

Models 無交易、時間來源、外部 I/O、retry 或 cancellation；同步映射拋錯由上層處理。UTC／精度 formatter 屬 Application 共用 helper。錯誤追蹤只輸出 RequestId；登入表單包含 Password 的記憶體物件不可直接 log 或 JSON 回傳，重顯 password 不含值已有 Web 測試。

## 現況差距與驗證限制

fallbackUsed 固定 false 且 Outcome 無 fallback flag，對照規格 fallback 仍有未實作部分（M-B03）。欄位排除 guard 覆蓋範圍與 URL policy 差異列 M-B01／M-B02，不宣稱已重現漏洞。沒有執行 runtime、序列化、時區或 HTML 渲染，本次只確認來源及測試存在。

相關文件：[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [測試案例](test-suite.md)。
