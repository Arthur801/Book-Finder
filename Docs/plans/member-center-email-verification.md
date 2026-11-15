# 會員中心、Email 驗證、忘記密碼、刪除帳號：實作規劃

> 狀態：2026-11-15 使用者核准；A～D 已全部合併（#216～#228），實作報告見 [Implementation-Report](../Implementation-Report/member-center-email-verification.md)，SES 步驟見 [deploy/ses-setup.md](../../deploy/ses-setup.md)。本檔是**實作計畫**，不是規格；current contract 以各模組 `docs/` 為準。

## Context

使用者提出四項需求：

1. 新增會員中心 `/account`，由上到下是「個人書單」「AI 剩餘次數與 AI 搜尋紀錄」「帳號安全」。
2. Header 的「個人書單」移到會員名稱左邊，會員名稱連到 `/account`。
3. 註冊時寄 Email 驗證信，驗證完成才能登入。
4. 忘記密碼：輸入 Email 後寄出重設連結，重設後讓舊的登入權杖失效（2026-11-15 使用者修正：原本的「登入後修改密碼」改成「忘記密碼」）；另外新增刪除帳號。

HANDOFF.md 顯示 MCP 已上線、沒有 open PR，所以這是下一個功能。

和使用者原計畫有出入、以程式碼為準的事實：

- 網站沒有任何寄信程式，也沒有 rate limiter。`PublicBaseUrl` 只有 `Mcp:PublicBaseUrl` 一個，屬於 MCP 模組。
- `AuthServiceCollectionExtensions` 沒有 `OnTokenValidated`。重設密碼或刪除帳號之後，舊 Cookie 最多還能用 1 天；MCP access token 最多還能用 1 小時。
- OpenIddict 有開 entry validation（`OAuthServiceCollectionExtensions.cs:129-130`）。因此只要把 DB 裡的 authorization／token 撤銷，access token 會立即失效。
- 刪除 User 時，`user_books`、`recommendation_searches`、`recommendation_jobs` 都會 cascade 刪除。
  - 刪除發生在 Job 執行中：heartbeat 或 commit 會 lease lost，Runner 不會寫入任何東西（`RecommendationJobRunner.cs:34-43`）。
  - 刪除發生在 Job commit 中：推論可能 deadlock，錯誤會被 retry 吸收，結果仍是安全的，但要補測試。
- `NavbarTests.cs`、`LayoutAndHomeTests.cs:23-25` 會檢查 header 的 HTML，必須一起修改。
- `ai.js` 的 `refreshHistory()` 會 `replaceState('/ai')`，所以 `ai.js` 不能載入到 `/account`。
- 正式環境的設定只能隨 release 改變（DEP-B26），發佈前必須經過 prev-release-on-new-schema 相容性測試。

## 使用者已決定（2026-11-15）

| # | 決策 |
|---|---|
| U-01 | 舊會員視為已驗證。「舊會員」指 Email 驗證開關開啟之前註冊的所有帳號，包含 Release N～N+1 之間註冊的帳號，以及 rollback 期間舊版建立的帳號。他們不會被要求驗證、不會被擋在登入之外，也不會收到驗證信 |
| U-02 | 寄信服務使用 Amazon SES。正式環境的網域、DKIM、IAM、sandbox 設定屬 L4，由使用者授權並親自操作 |
| U-03 | 會員中心「AI 搜尋紀錄」只列 Recommendation Job，不提供舊 Search 的入口；舊的 `/ai/history/{id}` 保留 |
| U-04 | `/ai` 的 Job 列表與舊搜尋紀錄都保留，會員中心再顯示一份；兩處共用同一個 partial |
| U-05 | 「修改密碼」改成公開的「忘記密碼」。重寄驗證信與忘記密碼都只需要輸入 Email，同一個 Email、同一種信，1 小時只能申請一次 |

## 本規劃自訂的預設（可逆、低風險，需要時再修改）

- **D-A 開關**：新增 `EmailVerification:Enabled`，預設 false，和 `RecommendationJobs`、`Mcp` 的上線方式相同。
  - 開關關閉時：註冊後立即寫入 `email_verified_at = now` 並登入（行為與現在相同）；登入不檢查是否已驗證；「忘記密碼」與「重寄驗證信」的連結都不顯示，對應的 endpoint 回 404。
  - 開關開啟時：才寄驗證信，並要求驗證後才能登入。
  - **不變條件（U-01）**：開關開啟的那一刻，資料庫中每個既有帳號都必須已經有 `email_verified_at`。只有開關開啟之後註冊的帳號，才可能是未驗證。以下流程只會作用在這類帳號上：「請先驗證 Email」的登入阻擋、重寄驗證信。
  - 這個條件靠三層保證：
    1. Release N 的 migration 回填既有帳號。
    2. 開關關閉期間，註冊時直接寫入 `email_verified_at = now`。
    3. 開關開啟的那個 release 帶一支 data migration，再回填一次 `WHERE email_verified_at IS NULL`，補上 rollback 期間舊版建立、欄位為 NULL 的帳號。
  - 刪除帳號不需要寄信，不受開關影響。
- **D-B 只需 Email 的申請頁不洩漏帳號是否存在**（U-05）：重寄驗證信與忘記密碼都是匿名頁面，只要輸入 Email。不論 Email 是否註冊、是否已驗證、是否還在 1 小時限制內，畫面都顯示同一段訊息：「如果這個 Email 已註冊，我們已寄出信件，請收信」。實際只有在條件符合時才會寄信：
  - 重寄驗證信：帳號存在且尚未驗證。依 D-A 的不變條件，這只會是開關開啟後註冊的新帳號；舊會員已驗證，輸入 Email 也不會收到信。
  - 忘記密碼：帳號存在。
  - 未驗證帳號登入（密碼正確）時，顯示「請先驗證 Email」並附上重寄頁的連結，不會自動寄信。
- **D-C 節流**（U-05）：
  - 同一個帳號、同一種信，1 小時內只發一張 token。以 DB 中最後一張 token 的 `created_at` 判斷，`AccountActionTokenOptions.RequestInterval` 預設 1 小時，可以設定。
  - 註冊時寄出的第一封驗證信也算在內，所以註冊後 1 小時內無法重寄。
  - 另外以 ASP.NET 內建 RateLimiter 依 IP 限制 register、login、resend、forgot、verify、reset 的 POST，防止有人大量輸入不同的 Email。這是 in-memory 節流，因為目前只有單一 instance。
- **D-D 驗證後延續原動作**：驗證信連結只附帶通過 `PendingLibraryAction.TryGetBookToAdd` 的 `/books/{guid}` returnUrl。其他 returnUrl 一律捨棄。
- **D-E 刪除帳號**：輸入目前密碼並勾選「了解不可復原」，立即硬刪除。不設緩衝期，共用的 Book 不受影響。
  - 執行中 Job 依現有 lease 機制自然中止。已經送出的那一次 AI 呼叫費用不追回。
- **D-F 新設定** `Site:PublicBaseUrl`（https，啟動時驗證），用來組信件連結，不讀 Host header。`Mcp:PublicBaseUrl` 不動。

## 模組拆分

照慣例：一個模組一個 worktree、一個 PR，branch 疊在前一個上面，base 一律 `main`。程式由 Haiku 以 TDD 撰寫，每個 PR 都包含所屬模組 `docs/*` 的更新。

### Feature A：會員中心（L2）

**A1 共用 partial 與可設定的 URL**
- `Models/LibraryPageViewModel.cs:25,30`：基底路徑改為參數（`/account`），篩選連結帶 `#library`。
- `Models/AiJobListViewModel.cs:40`：`UrlFor` 改用 base path，並保留其他 query（`status`）。
- `Views/Ai/_AiJobList.cshtml` 移到 `Views/Shared/_RecommendationJobList.cshtml`，標題作為參數傳入。`/ai` 的畫面維持不變（U-04）。
- `Views/Library/Index.cshtml` 抽出 `Views/Shared/_LibraryContent.cshtml`，保留 `library.js` 的 DOM 契約（`.library-item`、`.library-empty`、`[data-library-*]`）以及單一 AntiForgeryToken。

**A2 `RecommendationQuotaReader`（Application/Recommendation）**
- 計算方式：`remaining = max(0, DailyLimit − CountSinceAsync(userId, TaipeiTimeZone.StartOfDayUtc(now)))`，回傳 `(Used, Limit, Remaining)`。
- 和 `RecommendationService.cs:26-27` 用同一套公式，再加 unit tests。

**A3 `MemberController`：`GET /account` 頁面、redirect、Header**
- `[Authorize]`，依 `status`、`jobsPage` 組出 `MemberPageViewModel`，三個區塊固定 id：`#library`、`#ai-history`、`#account-security`。
- Job 區塊沿用 `AiController.JobListAsync` 的「超過最後一頁就退回」邏輯，抽成共用 helper。`RecommendationJobs:Enabled` 為 false 時，顯示「尚未開放」。
- `/library` 改成 302 到 `/account?status=…#library`。原本的 `LibraryController.Index` 移除，`LibraryApiController` 不動。實作時用 grep 找出其他寫死 `/library` 的地方（Views、MCP guide、tests）。
- `_Layout.cshtml`：
  - 左側移除「個人書單」。
  - 右側在登入時依序顯示「個人書單 `/account#library`」「會員名稱 `<a href="/account">`」「登出」「MCP 說明」。
  - 未登入時維持原樣。
- 同步修改 `NavbarTests`、`LayoutAndHomeTests`、`LibraryPageTests`；新增 `MemberPageTests`。

### Feature B：安全基礎（L3）

**B1 Schema migration（只新增，不刪改既有結構）**
- `users.email_verified_at timestamptz NULL`：在 migration 中 `UPDATE users SET email_verified_at = created_at`（U-01）。開關開啟前的第二次回填見 Feature E 第 3 步。
- `users.auth_version integer NOT NULL DEFAULT 0`。
- 新增 `account_action_tokens` 表：
  - 欄位：`id`、`user_id`（FK cascade）、`purpose varchar(32)`、`token_hash char(64) UNIQUE`、`created_at`、`expires_at`、`consumed_at`。
  - 索引 `(user_id, purpose, created_at)`。
- 需要修改的檔案：`Domain/Entities/User.cs`、新增 `Domain/Entities/AccountActionToken.cs`（加上 purpose 常數）、`UserConfiguration.cs`、新的 configuration、`AppDbContext.cs`，以及 migration。
- 驗證：
  - migration up/down 測試。
  - `deploy/migration-test` 的 compat 測試：前一版 image 在新 schema 上的首頁、登入、註冊都要正常。

**B2 Cookie JWT 失效機制**
- `AuthTokenIssuer.cs`：新增 `auth_version` claim。
- `AuthServiceCollectionExtensions.cs`：新增 `OnTokenValidated`，以 `IUserStore.FindByIdAsync` 檢查 User 仍存在，且 `auth_version` 一致；不符合就 `ctx.Fail` 並刪除 Cookie。
  - 舊 Cookie 沒有這個 claim，視為 0。這樣部署時不會把所有人登出。
  - 開關開啟時發的 Cookie 一定來自已驗證的 User，所以不另外檢查是否已驗證（見 D-A）。
- 測試放 `AuthPipelineTests`：版本不符、User 已刪除、缺少 claim 三種情況。

**B3 OAuth 憑證撤銷 port**
- Application 層定義 `IExternalCredentialRevoker`。
- Infrastructure 以 `AppDbContext` 的 OpenIddict entity set，依 subject 撤銷或刪除 authorization 與 token。它和呼叫端在同一個 DbContext，因此可以放進同一個 transaction。
- 實作前要先確認目前 OpenIddict 版本可用的 API；不行就直接用 `ExecuteUpdate`／`ExecuteDelete`。
- 測試用 `McpAuthorizationTests` 的模式：撤銷之後，`/mcp` 的 access token 立即回 401，refresh 回 `invalid_grant`。

### Feature C：Email（L3）

**C1 寄信 port 與 adapter**
- Application 層定義 `IEmailSender.SendAsync(EmailMessage)`。
- Infrastructure 提供兩種實作：
  - `SesEmailSender`：使用 `AWSSDK.SimpleEmailV2`，以預設 credential chain 取得 instance role 的權限。
  - `FakeEmailSender`：給 local 與 CI 使用，`BookFinderFactory` 透過它把信件內容提供給測試。
- 新增 `EmailOptions`（From、Region）、`Site:PublicBaseUrl`、`EmailVerification:Enabled`。
- 信件範本使用繁中純文字＋HTML，不含密碼，也不記錄 token。

**C2 `AccountActionTokenService` 與 `EfAccountActionTokenStore`**
- 原始 token 以 32 bytes CSPRNG 產生並轉成 base64url，DB 只存 SHA-256。
- 用途：`EMAIL_VERIFICATION`、`PASSWORD_RESET`，兩種 token 不能互用。
- 每種用途各有 TTL，可以設定：驗證信 24 小時、重設密碼 1 小時。重設密碼的 TTL 和申請間隔一樣長，避免連結過期後還要再等才能重新申請。
- 發新 token 時，把同 User、同用途尚未使用的舊 token 標為已消耗。
- `IssueAsync` 回傳 `Issued(rawToken)` 或 `Throttled`，1 小時限制見 D-C。判斷與寫入放在同一個 transaction，並鎖住 users 那一列（`FOR UPDATE`），讓同時送出的兩次申請最多只發出一張 token。
- 消耗 token 用條件式 `UPDATE … WHERE token_hash=@h AND purpose=@p AND consumed_at IS NULL AND expires_at>now RETURNING user_id`，所以同時送兩次最多只有一次成功。
- 測試：DB 整合測試涵蓋過期、重放、用途錯誤、併發消耗、1 小時內第二次申請、第 60 分鐘的邊界（用 FakeTimeProvider）、併發申請。

**C3 註冊驗證流程**（`AccountService`、`AccountController`，或新增 `AccountVerificationController`）
- 開關開啟時，註冊流程改為：
  1. 建立 User（`email_verified_at` 為 NULL）並 commit，然後寄信。
  2. 不發 Cookie，顯示「請收信」頁。
  3. 寄信失敗時保留帳號，並在「請收信」頁附上重寄頁的連結。寄信失敗時，那張 token 也要標為已消耗或刪除，不能算進 1 小時限制，否則使用者會被卡住。
- `GET /account/verify-email?token=` 只顯示確認按鈕，不消耗 token。`POST` 時才消耗 token、寫入 `email_verified_at`，然後導向登入頁（依 D-D 帶入 returnUrl 與 pendingAction）。
- 重寄驗證信：`GET /account/verification/resend` 顯示 Email 欄位，`POST` 後依 D-B、D-C 處理，結果一律顯示同一段訊息。
- `LoginAsync` 新增結果 `EmailNotVerified`：只有密碼正確時才回傳，畫面顯示「請先驗證 Email」並附上重寄頁連結（D-B）。
- token 頁面加上 `Cache-Control: no-store` 與 `Referrer-Policy: no-referrer`，做成共用的 filter attribute。另外檢查 layout 是否載入第三方資源。
- 測試：新增 `EmailVerificationFlowTests`，修改 `AccountPagesTests`、`AccountFlow`。
  - `AccountFlow.RegisterAsync` 要先確認目前 fixture 的開關預設值：預設關閉，既有測試就不必改。

**C4 忘記密碼**（U-05；新增 `PasswordResetService`、`PasswordResetController`）
- 入口：
  - 登入頁的「忘記密碼？」連結。
  - 會員中心「帳號安全」區塊的「重設密碼」連結，指到同一個頁面。
  - 不另外做一個需要登入的「修改密碼」流程。
- `GET /account/password/forgot` 只顯示 Email 欄位；匿名即可使用，也不會因為已登入就導回首頁。
- `POST /account/password/forgot`：需要 CSRF token，依 D-B、D-C 處理（帳號存在才寄信，同一個帳號 1 小時一次），回應一律顯示同一段訊息。
  - 為了不讓回應時間洩漏帳號是否存在，寄信改在 response 送出後才做（in-process 背景佇列），或以固定的最短回應時間處理。實作時選其中一種，並補上測試。
- `GET /account/password/reset?token=` 顯示「新密碼」與「確認密碼」表單，此時不消耗 token。
- `POST /account/password/reset`：
  - 沿用 `AccountInputRules` 的 8–40 規則，並檢查兩次輸入一致；私有的 `ValidatePassword` 改為 internal 或 public 以便重用。
  - 以下全部在同一個 transaction 內完成：
    1. 消耗 token。
    2. 更新 `PasswordHash`。
    3. `auth_version += 1`。
    4. 若 `email_verified_at` 為 NULL 就補上：能點開重設信，就表示擁有這個信箱。
    5. 執行 B3 的 OAuth 撤銷。
  - 完成後刪除這個瀏覽器的 Cookie，導向登入頁並顯示「密碼已重設，請重新登入」。
- 信件內容說明「如果不是你本人申請，可以忽略這封信」。
- 測試：新增 `PasswordResetFlowTests`。
  - 已註冊、未註冊、1 小時內第二次申請三種情況，畫面都一樣；寄出的信件數分別為 1、0、0。
  - 重設成功後，舊密碼、所有裝置的舊 Cookie、MCP token 都不能再用。
  - token 重放、過期、用途錯誤（拿驗證信的 token 來重設）都會被拒絕。

### Feature D：刪除帳號（L3）

**D1 `AccountDeletionService`、`IUserStore.DeleteAsync`、確認頁**
- `GET /account/delete` 確認頁說明會刪除哪些資料；`POST` 要求 CSRF、目前密碼、勾選確認。
- Transaction：先 `SELECT … FOR UPDATE` 鎖住 users 那一列（與 Job 提交使用同一把鎖，見 async-jobs D-01），再撤銷並刪除 OpenIddict 資料，最後刪除 User，其餘由 cascade 處理。完成後刪除 Cookie，導向首頁。
- 測試：
  - DB 整合測試：該 User 的 user_books、jobs、searches、results、tokens、openiddict 資料都被清除；Books 與其他會員的資料不變。
  - 刪除發生在 Job commit 中時，worker 不會拋出未處理的例外，也不會留下孤兒資料。
- Web 測試：新增 `AccountDeletionTests`。刪除之後，舊 Cookie 打 `/account`、`/api/recommendations/jobs`，以及舊 MCP token 打 `/mcp`，都會被拒絕。

### Feature E：上線（L4，每一步都需要使用者授權）

1. **Release N**：包含 A～D 與 migration，`EmailVerification:Enabled=false`。
   - 會員中心、刪除帳號、權杖失效機制可以直接使用。
   - 「忘記密碼」與「重寄驗證信」先不開放（D-A）。
2. **使用者在 AWS 上操作**（用 `wizard` skill 帶步驟）：
   - SES 驗證 `khwebsc.com` 網域，設定 DKIM 與 SPF/DMARC，申請 production access。
   - 在 instance role 加上 `ses:SendEmail` 權限，並限定 identity。
   - 確認 IMDSv2 hop limit ≥ 2，讓 container 拿得到 role。不行的話，改用 SES SMTP 憑證並存到 SSM（屆時再決定）。
3. **Release N+1**：帶一支 data migration `BackfillLegacyEmailVerification`，執行 `UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL`。這支 migration 可以重跑，並附 up/down 測試（U-01 的第 3 層保證）。接著在 `compose.prod.yaml` 開啟 `EmailVerification__Enabled` 並設定 From。
   - 上線前，請你在 production 確認 `SELECT count(*) FROM users WHERE email_verified_at IS NULL` 為 0。agent 沒有 production DB 連線，這一步由你執行。
   - 上線後抽一個舊會員帳號，確認不必驗證就能直接登入。在 production 實際寄信，走完註冊驗證、重寄驗證信、忘記密碼三個流程，並確認 1 小時內第二次申請不會再收到信。回退方式：重新部署 Release N。

## 文件同步

每個 PR 都要更新所屬模組的 `docs/*`，涉及的模組有 Controllers、Application、Infrastructure、Domain、Models、Views、wwwroot、tests、deploy。

- 新的安全契約（token、權杖失效、刪除帳號）寫進 `Application/docs/architecture.md` 與 `Infrastructure/docs/architecture.md`。
- `Mcp/docs` 補上「重設密碼或刪除帳號會撤銷 OAuth 憑證」。
- 計畫本身存到 `Docs/plans/member-center-email-verification.md`，並更新 `Docs/plans/README.md`。
- 實作報告存到 `Docs/Implementation-Report/`。

## 驗證

- 每個模組：`dotnet build --no-incremental`（0 warning），加上受影響的 unit、DB、web 測試。
- 最後一個 PR 跑完整 gate：`dotnet test tests/{UnitTests,DatabaseIntegration,WebIntegration}`，基準是 1143／254／448 全過；`.venv/bin/python -m pytest -q deploy/tests`；lint 照 CI 的執行位置。
- 本機實際跑網站，用瀏覽器確認：
  - `/account` 三個區塊的順序、書單 CRUD、最後一筆刪除後的空狀態。
  - 書單篩選與 Job 分頁互不干擾、`/library` redirect、header 排列。
  - 舊會員：先在開關關閉時註冊，再用舊版 image 在新 schema 上註冊一個帳號，然後套用 N+1 的 migration 並打開開關。兩個帳號都能直接登入；對它們送出重寄驗證信，寄出 0 封。
  - 把開關打開、使用 fake sender，從 log 或測試 endpoint 取得連結，走完註冊驗證、重寄驗證信、忘記密碼三個流程，並用 FakeTimeProvider 確認 1 小時的限制。
- 兩軸 code review（Standards＋Spec），主 agent 親自驗證每一項 finding。
- CodeQL：所有 redirect 都使用 `LocalRedirect`，避免 `cs/url-redirection`。
