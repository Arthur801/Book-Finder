# 會員中心、Email 驗證、忘記密碼、刪除帳號 實作報告

> 計畫：[Docs/plans/member-center-email-verification.md](../plans/member-center-email-verification.md)（2026-11-15 使用者核准；決策 U-01～U-05，預設 D-A～D-F）。日期：2026-11-15。
>
> 本報告是實作紀錄，不是規格。current contract 以各模組 `docs/` 為準（AGENTS.md §3.2）。
>
> **production 狀態（2026-11-15）：** 程式已全部合併到 `main`（`3afe87d`），尚未打 release tag。Email 驗證開關 `EmailVerification:Enabled` 預設關閉。開啟前必須先完成 SES 設定，步驟見 [deploy/ses-setup.md](../../deploy/ses-setup.md)；完整上線順序見文末「上線手冊」。

## 變更檔案

| 模組 | 主要檔案 | 票 |
|---|---|---|
| Views／Models | `Shared/_LibraryContent.cshtml`、`Shared/_RecommendationJobList.cshtml`（由 `Ai/_AiJobList` 搬移）；`LibraryPageViewModel`、`AiJobListViewModel` 的 URL 改為可設定 | A1 |
| Application | `Recommendation/RecommendationQuotaReader.cs`、`RecommendationQuota.cs` | A2 |
| Controllers／Views／Models | `MemberController.cs`（`GET /account`、`/library` 轉址）、`RecommendationJobListLoader.cs`、`Views/Member/Index.cshtml`、`MemberPageViewModel.cs`、`_Layout.cshtml`（header） | A3 |
| Domain／Infrastructure | `User.EmailVerifiedAt`、`User.AuthVersion`、`AccountActionToken`、`AccountActionTokenPurpose`；migration `20261115055411_AddEmailVerificationAndAccountTokens`；compat seed | B1 |
| Infrastructure／Controllers | `AuthTokenIssuer`（`auth_version` claim）、`AuthServiceCollectionExtensions`（`OnTokenValidated`）、`ConsentSessionEndedRedirectAttribute.cs` | B2 |
| Application／Infrastructure | `IExternalCredentialRevoker`、`OAuthCredentialRevoker` | B3 |
| Application／Infrastructure | `Email/IEmailSender`、`AccountEmailTemplates`、`EmailOptions`、`Site/SiteOptions`、`SiteUrlBuilder`；`Infrastructure/Email/SesEmailSender`、`PickupDirectoryEmailSender`、`NoEmailSender`；`AWSSDK.SimpleEmailV2` 4.1.0 | C1 |
| Application／Infrastructure | `AccountActionTokenService`、`AccountActionTokenRules`、`AccountActionTokenOptions`、`EfAccountActionTokenStore` | C2 |
| 全部 | `EmailVerificationService`、`AccountEmailDispatcher`、`AccountEmailQueue`／`AccountEmailWorker`、`EfEmailVerificationStore`、`AccountRateLimiting`、`TokenLinkPageAttribute`、`AccountVerificationController`、`Views/AccountVerification/*` | C3 |
| 全部 | `PasswordResetService`、`EfPasswordResetStore`、`PasswordResetController`、`Views/PasswordReset/*`；「密碼已變更」通知 | C4 |
| 全部 | `AccountDeletionService`、`EfAccountDeletionStore`、`AccountDeletionController`、`Views/AccountDeletion/Index.cshtml`；`EfRecommendationJobStore` 的使用者已刪除處理 | D1 |
| deploy | `README.md` 查核清單第 7、8 項；backlog DEP-B27、DEP-B28；`ses-setup.md` | C3、本 PR |

規模：`3877554..3afe87d` 共 188 個檔案，新增約 11,900 行（含測試與文件）。

PR：#216（計畫）、#217（A1）、#218（A2）、#219（B1）、#220（B3）、#221（C1）、#222（B2）、#223（C2）、#224（A3）、#225（D1）、#226（C3）、#227（C4）、#228（通知信與 review 決策）、本 PR（報告與 SES 文件）。

## 實作思路

- **開關先行（D-A）**：所有寄信相關的流程都由 `EmailVerification:Enabled` 控制，預設關閉。開關關閉時，註冊後直接寫入驗證時間並登入，行為和以前相同，新增的 endpoint 回 404。這樣程式可以先上線，SES 就緒後再以一個 release 打開。
- **舊會員永遠不需要驗證（U-01）**：migration 把既有帳號回填為已驗證；開關關閉期間註冊的帳號直接標記為已驗證；開關開啟的 release 會再回填一次 NULL（DEP-B27）。所以登入阻擋與重寄驗證信，只會作用在開關開啟後註冊的帳號。
- **一次性 token（C2）**：原始值 32 bytes，只放進信件連結；DB 只存 SHA-256。消耗以一條條件式 `UPDATE … RETURNING` 完成，同時送出兩次只會成功一次。申請時鎖住 users 那一列，同一個帳號、同一種信 1 小時只發一張（U-05）。寄信失敗時刪除該張 token，不計入限制。
- **不洩漏帳號是否存在（D-B）**：重寄驗證信與忘記密碼的 POST 只把請求放進記憶體佇列就回應，畫面一律相同；查帳號、節流、寄信都在背景 worker 進行，回應時間與帳號是否存在無關。
- **讓舊憑證立即失效**：
  - 網站 cookie 帶 `auth_version`，每個請求都比對 DB 的值（B2）。舊 cookie 沒有這個 claim 時視為 0，所以部署時不會把所有人登出。
  - MCP 的 OAuth 憑證在同一個 transaction 內撤銷（重設密碼）或刪除（刪除帳號）（B3）。OpenIddict 的 entry validation 會立即拒絕已撤銷的 access token。
- **一個 transaction 完成一件事**：重設密碼、Email 驗證、刪除帳號都在 Infrastructure store 內開 transaction。它們都先鎖 users 那一列，順序和 Job 提交相同，避免互相 deadlock。
- **重用既有元件**：書單與 Job 列表抽成 partial，`/ai` 與 `/account` 共用（U-04）；剩餘次數沿用每日上限的計數公式（A2），不新增資料表。

## 執行紀錄（Log）

- 依慣例拆成 12 個模組，每個模組一個 worktree、一個 PR。可以並行的模組同時交給 Haiku subagent 以 TDD 實作：第一波 A1、A2、B1、B3、C1；第二波 B2、C2；第三波 A3、C3、D1；最後是 C4。主 agent 負責規劃、核對 diff、重跑測試、合併分支與開 PR。
- 平行分支的文件編號多次撞號，例如 APP-T28、INF-T25、TEST-39～44、APP-B06、PIPE-07，都在合併前改號。文件衝突一律保留兩邊內容，再以 block check 確認沒有遺失任何一邊的段落。有一次合併把 B3 的歷史列移出了表格，已修正並往後合併。
- 修正過的問題：
  - C1：Pickup 寄信方式如果誤設在正式環境，信件會靜默寫到磁碟。改成只要不是 Development 環境，設定成 Pickup 就無法啟動。
  - B2：CodeQL `cs/user-controlled-bypass`。導回登入頁的判斷曾經依賴 `HasFormContentType`，改成只依登入狀態與 MCP 開關決定（`1d37dba`）。
  - B2：使用者停在 OAuth 同意頁時帳號被刪除，按下同意會得到 antiforgery 400。使用者要求改回登入頁，由 `ConsentSessionEndedRedirect` 處理（`2d3da1b`）。
  - C2：`"24:00:00"` 會被 .NET 解析成 24 天，Email 驗證連結的有效期因此是 24 天。改為 `"1.00:00:00"`，並加上直接讀取正式設定檔的回歸測試（`52394de`；由 C3 的網站測試發現）。
  - D1：刪除帳號後再送出 Job，原本會因外鍵錯誤回 500。改為上鎖後確認使用者存在，不存在時回 401。
  - C3 之後：刪除帳號的密碼確認也套用 `account-auth` 限流（`5c273ae`）。
- 正式環境的 nginx：每 IP 限流需要 app 拿到真實 client IP。查核時發現 nginx 傳給 app 的是 Cloudflare 節點 IP；使用者在 host 加上 Cloudflare real-IP 設定後，確認 `X-Forwarded-For` 等於 `CF-Connecting-IP`（deploy README 查核清單第 7、8 項，DEP-B28）。
- #227 在通知信的 commit push 上去之前就合併了，因此另開 #228，以 cherry-pick 補上。

## 驗證結果

| 項目 | 結果 |
|---|---|
| `dotnet build --no-incremental`（`3afe87d` 上的分支） | 0 warning、0 error |
| UnitTests／DatabaseIntegration／WebIntegration（#228 分支，與 main 相同的程式） | 1330／313／522，全數通過（開始前的基準為 1143／254／448） |
| deploy pytest | 722 passed、17 skipped |
| GitHub CI 與 CodeQL（main `3afe87d`） | 全部成功 |
| Mutation 抽查 | C2 拿掉 `FOR UPDATE` 後並發申請測試失敗；B3 把撤銷改回 `valid` 後 MCP 測試失敗；D1 拿掉使用者存在檢查後競態測試失敗；全部已還原 |

**本機瀏覽器檢查**（拋棄式 pgvector；開關開啟；Pickup 寄信；OpenAI 經不存在的 proxy 失敗，沒有任何請求送出；Playwright，41／41）：

- Header：未登入時沒有「個人書單」；登入後「個人書單」在會員名稱左邊，名稱連到 `/account`，左側沒有「個人書單」。
- 註冊：顯示「請收信」且不登入；寄出 1 封驗證信，連結的 host 是 `Site:PublicBaseUrl`。驗證前登入顯示「請先完成 Email 驗證」與重寄連結。重寄時，已註冊與未註冊的畫面相同，1 小時內不再寄信。
- 驗證頁：回應帶 `Cache-Control: no-store` 與 `Referrer-Policy: no-referrer`；GET 兩次都不消耗 token；確認後導向登入頁並顯示提示。
- 會員中心：三個區塊的順序正確；剩餘次數 20 / 20；沒有載入 `ai.js`；從書籍頁加入 3 本後，可以修改閱讀狀態、評分、用「閱讀中」篩選，網址以 `#library` 結尾；`/library?status=READING` 會轉址；移除最後一本後顯示空狀態。
- AI：送出 1 個 Job 後，會員中心的「AI 搜尋紀錄」列出它，剩餘次數正確。
- 忘記密碼：已註冊與未註冊的畫面相同；寄出 1 封重設信；兩次密碼不一致時顯示錯誤；重設後導向登入頁，並寄出不含 token 的「密碼已變更」通知；另一個瀏覽器的舊 cookie 被導向登入；舊密碼不能登入，新密碼可以。
- 刪除帳號：密碼錯誤時不刪除；正確時回首頁並顯示「帳號已刪除」；之後 `/account` 導向登入，也無法再登入。

第一輪有 2 項失敗，原因是檢查腳本的 selector 點到了 header 的登出按鈕。腳本改為只選 `main form` 後重跑，全部通過。腳本是一次性的，沒有 commit（TEST-B03）。

**沒有驗證**：
- 真實的 SES 寄信（L4，見 `deploy/ses-setup.md`）。
- 不同 IP 的限流隔離（只能在正式環境驗證）。
- 開關關閉時的瀏覽器操作，這部分由既有與新增的 WebIntegration 測試涵蓋。

## 未解決事項

1. **SES 上線**（DEP-B27、INF-B11，L4）：網域驗證、DKIM、production access、IAM、IMDS hop limit，以及開關開啟的 release（含第二次回填 `BackfillLegacyEmailVerification`）。步驟見 `deploy/ses-setup.md`。
2. **Cloudflare 網段更新**（DEP-B28）：host 上的 real-IP 設定是手動產生的，沒有自動更新。
3. **記憶體中的限流與寄信佇列**（APP-B11、INF-B14、INF-B15）：重新啟動後就會消失，多 instance 部署前要重新設計。
4. **刪除帳號與 Job commit 同時發生的 deadlock 路徑沒有測試**（INF-B12）；舊的同步推薦路徑在刪除競態下仍可能回 500（APP-B10，M9 移除舊路徑時一併消失）。
5. **註冊頁的「此 email 已被註冊」會洩漏帳號是否存在**（CTL-13）：這是既有行為，本次沒有改。
6. **新增文案尚未經使用者審閱**（VIEW-B07）。
7. **Code review 的判斷題，可以之後開 refactor PR**：兩個寄信 service 的寫法重複；`if (!Enabled) return NotFound()` 重複 6 次；`FOR UPDATE` 那段查詢出現在 3 個 store；開關名稱 `EmailVerification:Enabled` 同時控制忘記密碼；ViewData 用字串 key 傳值。

## Code Review 與修正

兩軸 review 的範圍是 `3877554...C4`。Standards 與 Spec 兩個 subagent 並行執行，主 agent 逐項核對。

- **Standards**：沒有硬性違規。分層、secret、`LocalRedirect`、文件同步都符合。修正兩處過時的註解（`AccountActionTokenService.ConsumeAsync`、`AccountRateLimitPolicies`）。其餘是程式碼異味的判斷題，列在「未解決事項」第 7 點。
- **Spec**：交易邊界與轉址網址都沒有錯。補上開關開啟前第二次回填的追蹤（DEP-B27）。使用者在 2026-11-15 決定的事項：
  - 保留 `ConsentSessionEndedRedirect`，作為唯一核准的 antiforgery 例外（Controllers architecture §5）；
  - 「個人書單」只在登入後顯示；
  - `account-auth` 每 IP 每分鐘 20 次（CTL-02 已決定、AUTH-F01 結案）；
  - 重設成功後寄「密碼已變更」通知（APP-B13，#228）。

## 上線手冊

每一步都需要使用者授權。打 tag 等於部署到正式環境。

1. **Release v0.0.15（開關關閉）**
   - 前置：確認 EC2 磁碟空間足夠（`df -h /`、`docker system df`）。HANDOFF 曾列為緊急事項。
   - 內容：migration `20261115055411`（回填舊會員）、會員中心、刪除帳號、cookie 失效、限流。註冊與登入的方式和以前相同，不寄任何信。
   - 上線後檢查：
     - 舊會員登入後，會員中心三個區塊正常；
     - `/library` 會轉址；
     - 刪除一個測試帳號，確認刪除後無法再登入；
     - 連續登入失敗會在第 21 次回 429，而且不影響其他 IP。
   - 回退：CD dispatch 重新部署 v0.0.14。新增的欄位和資料表不影響舊版運作。
2. **SES 設定**：使用者依 [deploy/ses-setup.md](../../deploy/ses-setup.md) 在 AWS 與 Cloudflare 上操作。
3. **Release v0.0.16（開關開啟）**：由 agent 準備 PR，內容如下：
   - data migration `BackfillLegacyEmailVerification`（可重跑，附 up/down 測試）；
   - `compose.prod.yaml` 加上 `Site__PublicBaseUrl`、`Email__Provider: Ses`、`Email__From`、`Email__Region`、`EmailVerification__Enabled: "true"`。

   上線前由使用者確認 `SELECT count(*) FROM users WHERE email_verified_at IS NULL` 為 0。上線後實際走一次註冊驗證、重寄、忘記密碼，並確認 1 小時內第二次申請不會再收到信。回退方式是重新部署 v0.0.15。
