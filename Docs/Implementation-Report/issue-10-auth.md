# Issue #10 註冊、登入、登出：實作報告

- Issue：#10 註冊、登入、登出（AUTH-01～05）
- Branch：`issue-10-auth`（from `main` `ca87237`）
- 規格：`Docs/modules/identity-auth.md`、`Docs/api/api-spec.md` §1～§2、ADR-004、`Docs/ui/ui-flow.md`
- 使用者決定（2026-10-20，已寫入 `93c7294` 的規格更新）：
  - `pendingAction=add-to-library` 原樣保留、不處理（屬 #11）。
  - `/api` 401 以測試專用端點驗證，不新增正式 API。
  - 登入 / 註冊 rate limiting 暫緩，記錄於 `Docs/TODO.md`。
  - 本機 JWT key 放 `.env` 的 `Jwt__SigningKey`，由 shell 載入；程式本身不讀 `.env`。
  - email 規則：`[EmailAddress]`、最多 320 字元、保留大小寫。
  - 密碼 8～40 碼。
  - display_name 以 code point 計算，1～100。
  - 已登入者進入登入或註冊頁時導向 `/`。
  - ClockSkew = 0。
- 日期：2026-10-20
- 分工：主 agent 規劃、派工、驗收、撰寫文件；A1～A9 由 Haiku subagent 以 TDD 實作。每個模組完成後，主 agent 親自執行 build 與測試並閱讀程式碼。

模組依賴：A1 欄位規則、A2 密碼雜湊、A3 使用者資料存取 → A4 帳號服務；A5 Token 簽發 → A6 認證管線；A4 + A5 + A6 + A7 returnUrl → A8 帳號頁面 → A9 導覽列。

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/modules/identity-auth.md` | 修改以下各節：<br>• §3：密碼 8～40 碼；email 與 display_name 細則；同時註冊造成的 unique 衝突也顯示「此 email 已被註冊」。<br>• §5：ClockSkew 0；claims 加上 `nbf`、`iss`、`aud`；只從 cookie 讀 token；非 GET 請求被 challenge 時不帶 returnUrl。<br>• §6：已登入者導向 `/`。<br>• §7：標記暫緩。<br>• §8 第 9 條：標記暫緩。 |
| `Docs/requirements/product-requirements.md` | AUTH-01 改為「密碼 8～40 碼」 |
| `Docs/deployment/deployment.md` | §1、§5 寫明 `Jwt:SigningKey`（環境變數 `Jwt__SigningKey`）、啟動檢查，以及本機用 shell 載入 `.env` |
| `Docs/TODO.md` | 新增。記錄 rate limiting 暫緩：原規格、未完成的 AC、恢復時要做的事 |
| `README.md` | 新增「本機開發」：如何產生 JWT key、如何載入 `.env`、VS Code 的 `envFile` |

## A1 帳號欄位規則

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Identity/AccountInputRules.cs` | 新增 | 純函式 `ValidateRegistration`、`ValidateLogin`，回傳正規化後的值與欄位錯誤 |
| `tests/UnitTests/AccountInputRulesTests.cs` | 新增 | 26 個測試 |

### 實作思路
- 不碰 DB 或 HTTP。錯誤的 key 是 `email`、`password`、`displayName`，每個欄位最多一個錯誤。
- email：先 Trim，再依序檢查必填、長度（>320）、格式。長度放在格式之前檢查，避免超長字串進入格式驗證。
- 密碼不 Trim，以 `Length` 判斷 8～40 碼。display_name 以 `EnumerateRunes()` 計數，和 PostgreSQL 的 `varchar(100)` 一致。
- 登入只檢查必填，不檢查格式與長度，讓所有帳密錯誤都能顯示同一個訊息。

### 執行紀錄（Log）
- `e4c47e4`：紅燈是編譯失敗（型別不存在）；轉綠後 113 個測試通過。

### 驗證結果
- 密碼 7 / 8 / 40 / 41 碼的邊界、中文 100 / 101 字、emoji 100 個、只有空白的輸入、三個欄位同時錯誤，皆有測試，全部通過。

### 未解決事項
- 無。

### Code Review 與修正
- 無需修正。

## A2 密碼雜湊

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Identity/IPasswordHashing.cs` | 新增 | port 與 `PasswordCheck { Failed, Success, SuccessRehashNeeded }` |
| `Infrastructure/Identity/AspNetPasswordHashing.cs` | 新增 | 包裝 `PasswordHasher<User>`（PBKDF2） |
| `tests/UnitTests/AspNetPasswordHashingTests.cs` | 新增 | 5 個測試 |

### 實作思路
- 沒有導入完整的 ASP.NET Core Identity。`PasswordHasher<T>` 已包含在 shared framework，不需要加套件。
- hasher 的 user 參數不會被使用，所以傳入一個 static placeholder。

### 執行紀錄（Log）
- `c8ce8ba`：紅燈是編譯失敗；轉綠後 118 個測試通過。

### 驗證結果
- 雜湊後可以驗證成功；密碼錯誤時回傳 Failed；有加 salt；雜湊值不含明文；IdentityV2 的舊格式雜湊會回傳 SuccessRehashNeeded。

### 未解決事項
- 無。

### Code Review 與修正
- 無需修正。

## A3 使用者資料存取

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Identity/IUserStore.cs` | 新增 | `FindByEmailAsync`、`AddAsync`（回傳 `AddUserResult`）、`UpdatePasswordHashAsync` |
| `Infrastructure/Persistence/EfUserStore.cs` | 新增 | EF 實作（internal sealed） |
| `tests/DatabaseIntegration/EfUserStoreTests.cs` | 新增 | 7 個測試 |

### 實作思路
- 不新增 migration。唯一索引 `ux_users_email_lower` 早已由既有的 migration 建立。
- 查詢使用 `FromSqlInterpolated("... WHERE lower(email) = lower({email})")`，兩邊都由 PostgreSQL 轉小寫，和唯一索引用同一套規則。
- 違反唯一索引時（SqlState 23505 且 ConstraintName 為 `ux_users_email_lower`），回傳 `DuplicateEmail`，並 detach 該 entity，讓同一個 DbContext 還能繼續使用。
- 更新雜湊用 `ExecuteUpdateAsync`，只更新 `password_hash` 與 `updated_at`。

### 執行紀錄（Log）
- `c1af3d6`：初版。
- `020ff13`：主 agent 驗收時退回。初版在 C# 端用 `ToLower()`，結果會受 CurrentCulture 影響：在 tr-TR 下，`IAN` 會變成 `ıan`，查不到使用者。修正前 tr-TR 測試失敗（紅燈），修正後通過。

### 驗證結果
- 測試涵蓋：查詢不分大小寫並保留原始大小寫、找不到時回傳 null、`A@x.com` 已存在時新增 `a@x.com` 會回傳 DuplicateEmail 且之後仍能新增其他 email、更新雜湊、tr-TR 語系、非 ASCII 字母 Ä/ä。DatabaseIntegration 共 19 個測試全部通過。

### 未解決事項
- 沒有用 EXPLAIN 驗證查詢確實使用了索引。依 SQL 的寫法判斷，`lower(email) = lower($1)` 可以使用這個索引。

### Code Review 與修正
- 無其他修正。

## A4 帳號服務

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Application/Identity/AccountService.cs` | 新增 | `RegisterAsync`、`LoginAsync`；結果型別 `RegisterResult` 與 `LoginResult` |
| `tests/UnitTests/AccountServiceTests.cs` | 新增 | 10 個測試，使用手寫 fake |

### 實作思路
- 結果用 abstract record 階層：`Succeeded`、`InvalidInput`、`InvalidCredentials`。每種結果是不同型別，呼叫端無法從失敗的結果中拿到 User。這和 A1 單一 record 加 `IsValid` 的寫法不同，主 agent 認可這個選擇。
- 註冊時不先查詢 email 是否存在，重複與否由唯一索引判斷。`Id` 為 `Guid.CreateVersion7(now)`，`users.id` 沒有 DB 預設值；時間取自 `TimeProvider`。
- 登入時，「email 不存在」和「密碼錯誤」回傳同一種 `InvalidCredentials`，訊息是「帳號或密碼錯誤」。email 不存在時仍會對一個假雜湊做一次 Verify，讓兩種情況的耗時相近。
- 遇到 `SuccessRehashNeeded` 時更新雜湊。

### 執行紀錄（Log）
- `65aa450`：初版。
- `13abf86`：主 agent 驗收時退回。初版的假雜湊是每個實例各有一個 `Lazy`，但 AccountService 是 scoped，所以每個 request 都會多算一次 PBKDF2，email 不存在時的耗時反而是密碼錯誤的兩倍。改成 static 加 `LazyInitializer`，整個 process 只算一次。「第二個實例不會呼叫 Hash」的測試在修正前失敗（紅燈）。

### 驗證結果
- 註冊時：輸入錯誤不會呼叫 hasher 與 store；重複 email 回傳欄位錯誤；寫入的欄位值正確。
- 登入時：兩種失敗的結果相等；email 不存在時仍會 Verify；rehash 會更新雜湊；欄位為空時不查 DB。

### 未解決事項
- 每個 process 第一次以不存在的 email 登入時，會多算一次假雜湊。這只發生一次，無法用來探測 email 是否已註冊，因此接受（Spec review 提出）。

### Code Review 與修正
- 無其他修正。

## A5 Token 簽發

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Book-Finder.csproj` | 修改 | 新增 `Microsoft.AspNetCore.Authentication.JwtBearer` 10.0.12 |
| `Infrastructure/Identity/JwtOptions.cs` | 新增 | 設定、32 bytes 檢查、signing key、`CreateValidationParameters()`、常數（`Issuer`、`Audience`、`NameClaim`、`TokenLifetime`） |
| `Infrastructure/Identity/AuthTokenIssuer.cs` | 新增 | 以 `JsonWebTokenHandler` 簽發 HS256 token |
| `tests/UnitTests/JwtOptionsTests.cs`、`AuthTokenIssuerTests.cs` | 新增 | 共 11 個測試 |

### 實作思路
- token 的格式只在 `JwtOptions` 定義，簽發和驗證共用同一份設定：只接受 HS256；`ClockSkew = 0`；檢查 issuer 與 audience；`NameClaimType = "name"`。
- claims 有 `sub`、`name`、`iat`、`nbf`、`exp`，不含 email。所有時間明確取自 `TimeProvider`。
- `iss` 與 `aud` 規格沒有定義，主 agent 決定都固定為 `book-finder`，並已補進 identity-auth §5。

### 執行紀錄（Log）
- `c13d862`：紅燈是編譯失敗；轉綠後 139 個測試通過，沒有 NuGet audit 警告。

### 驗證結果
- token 的內容正確；`exp - iat` 等於 1 天；同一把 key 驗證有效、不同 key 無效；31 bytes 的 key 無效、32 bytes 有效（以 UTF-8 bytes 計算）。

### 未解決事項
- 無。

### Code Review 與修正
- `3134b7a`：`"name"` 原本在兩處以字面值寫死，抽成 `JwtOptions.NameClaim`（Standards review）。

## A6 認證管線

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Infrastructure/Identity/AuthCookie.cs` | 新增 | `bf_auth` cookie 的寫入與刪除，所有屬性只在這裡定義 |
| `Infrastructure/Identity/AuthServiceCollectionExtensions.cs` | 新增 | `AddBookFinderAuth()`：options 檢查、DI、JWT Bearer、antiforgery |
| `Infrastructure/Identity/AntiforgeryProblemDetailsFilter.cs` | 新增 | `/api` 路徑下 antiforgery 驗證失敗時改回 ProblemDetails |
| `Infrastructure/Identity/ApiRequest.cs` | 新增 | 共用的 `/api` 路徑判斷 |
| `Program.cs` | 修改 | 呼叫 `AddBookFinderAuth`；在 `UseRouting` 與 `UseAuthorization` 之間加上 `UseAuthentication()` |
| `tests/UnitTests/AuthCookieTests.cs` | 新增 | cookie 屬性測試 |
| `tests/WebIntegration/AuthPipelineTests.cs`、`TestOnlyAuthController.cs` | 新增 | 14 個測試；測試專用的 controller 只在測試 host 中加入 |
| `tests/WebIntegration/WebFixture.cs`、`WebIntegration.csproj` | 修改 | 每次測試執行都隨機產生 signing key；新增 `Microsoft.Extensions.TimeProvider.Testing` 10.11.0 |

### 實作思路
- **cookie**：`HttpOnly`、`Secure`、`SameSite=Lax`、`Path=/`，`Max-Age` 為 1 天。刪除時使用相同的屬性。
- **只從 cookie 讀 token**：`OnMessageReceived` 在沒有 cookie 時呼叫 `NoResult()`，防止 handler 改讀 `Authorization` header。
- **自訂 `LifetimeValidator`**：時間改用注入的 `TimeProvider`，不用框架預設的系統時間，所以測試可以控制「剛好 1 天」的時間點。
- **未登入時（`OnChallenge`）**：
  - `/api` 回 401 ProblemDetails，type 為 `/errors/unauthenticated`，含 traceId。
  - GET / HEAD 頁面導向 `/account/login?returnUrl=<原路徑>`。
  - 其他 method 導向 `/account/login`，不帶 returnUrl。
- **signing key 檢查**：用 `ValidateOnStart`，key 缺少或短於 32 bytes 時啟動失敗，錯誤訊息不含 key。
- **antiforgery**：
  - 全域套用 `AutoValidateAntiforgeryTokenAttribute`，header 名稱為 `RequestVerificationToken`，antiforgery cookie 一律 Secure。
  - 驗證失敗時，`/api` 回 400 ProblemDetails，type 為 `/errors/antiforgery`；頁面維持框架預設的 400。

### 執行紀錄（Log）
- `6a2dbc7`、`40ec61a`、`2437ca7`：初版。pipeline 的 9 個測試在實作前全部失敗。
- `88d06c5`：主 agent 驗收時退回。subagent 誤以為 `IAntiforgeryValidationFailedResult` 不是 public，改用比對介面名稱的反射。主 agent 用反射確認它是 public（namespace 為 `Microsoft.AspNetCore.Mvc.Core.Infrastructure`），改為直接用 `is` 判斷型別。
- `e530787`：Spec review 發現，token 過期後按「登出」會導向 `returnUrl=/account/logout`，登入後瀏覽器以 GET 開啟這個只接受 POST 的路由而出錯。改為非 GET / HEAD 的請求不帶 returnUrl。這次先寫測試確認失敗（紅燈）再修正。
- `3134b7a`：抽出 `ApiRequest.IsApi`；測試 helper 補上 `Async` 後綴。

### 驗證結果
- 已驗證的行為：
  - 沒有 cookie 時，頁面回 302 並帶 returnUrl，`/api` 回 401 ProblemDetails。
  - token 有效時正常存取。
  - 1 天減 1 秒仍有效，剛好 1 天即失效。
  - 用其他 key 簽的 token、格式錯誤的 token、放在 Bearer header 的 token，都視為未登入。
  - 缺少 antiforgery token 時，頁面和 `/api` 都回 400，且 `/api` 回 ProblemDetails。
  - token 有效時 POST 成功；跨 session 的 token 會被拒絕。
  - key 為空或只有 31 bytes 時啟動失敗。
  - 非 GET 請求被 challenge 時不帶 returnUrl。

### 未解決事項
- 頁面請求的 antiforgery 驗證失敗時，只回框架預設的空白 400，沒有友善的錯誤頁。規格只要求回 400。

### Code Review 與修正
- 見上方執行紀錄的 `e530787`（Spec review）和 `3134b7a`（Standards review）。

## A7 returnUrl 檢查

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Infrastructure/Identity/SafeReturnUrl.cs` | 新增 | `Resolve(returnUrl, IUrlHelper)`，不合法時回傳 `/` |
| `tests/UnitTests/SafeReturnUrlTests.cs` | 新增 | 用真的框架 `UrlHelper` 跑 Theory |

### 實作思路
- 判斷完全交給框架的 `IsLocalUrl`，不自己寫 URL 解析規則。
- 原計畫把它放在 Application 層，但它依賴 MVC 的 `IUrlHelper`，所以改放在 Infrastructure。

### 執行紀錄（Log）
- `5d2113a`：紅燈是編譯失敗。subagent 回報 `/%09/evil.example` 會被框架接受。主 agent 判斷這不是漏洞：`%09` 在 Location 中保持編碼，瀏覽器仍視為本站路徑。
- `482f16d`：補上解碼後含控制字元的輸入，這才是真正危險的形式：`"/\t/evil.example"`、`"/\n/..."`、`"/\r\n/..."`、`"/\t\\..."`。框架全部拒絕，作為回歸測試。

### 驗證結果
- 接受：`/`、`/books/123`、`/search?q=a&page=2`、`/ai`、`~/books/1`。
- 拒絕：null、空白、`https://evil`、`http://evil`、`//evil`、`/\evil`、`\\evil`、`books/1`、`javascript:`、上述 4 種含控制字元的形式。UnitTests 共 161 個，全部通過。

### 未解決事項
- 無。

### Code Review 與修正
- 無需修正。

## A8 帳號頁面

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Controllers/AccountController.cs` | 新增 | `GET`／`POST` `/account/login`、`/account/register`，以及 `POST /account/logout`（`[Authorize]`） |
| `Models/LoginForm.cs`、`RegisterForm.cs` | 新增 | 不使用 DataAnnotations 的 form model |
| `Views/Account/Login.cshtml`、`Register.cshtml` | 新增 | 繁中表單；form tag helper 自動輸出 antiforgery token |
| `tests/WebIntegration/AccountPagesTests.cs` | 新增 | 13 個測試 |
| `tests/WebIntegration/AccountFlow.cs` | 新增 | 共用的註冊、登入、POST form helper，#11 也可以使用 |
| `tests/WebIntegration/HtmlPage.cs` | 修改 | 新增 `AntiforgeryToken`、`InputValue`、`ValidationSummary` |
| `tests/WebIntegration/WebFixture.cs` | 修改 | 測試 host 改用 `NullFileProvider` 作為 web root |

### 實作思路
- Controller 沒有業務規則，只把 `AccountService` 的結果轉成 cookie、導向或重新顯示表單。驗證完全交給 `AccountService`，避免出現兩套規則。
- 成功時簽發 cookie，並以 `SafeReturnUrl.Resolve` 決定導向位置（PRG）。帳密錯誤顯示為表單層級的錯誤。
- 重新顯示表單時保留 email、displayName、returnUrl、pendingAction，不回填密碼。`pendingAction` 只放在 hidden field 和登入、註冊之間的切換連結中。
- `WebFixture` 的調整：layout 的 `asp-append-version` 會替每個 test host 建立檔案監看，整套測試跑下來會碰到 inotify 的上限（128）而出現 500。這和既有的 `reloadConfigOnChange` 修正屬於同一類問題，只影響測試。

### 執行紀錄（Log）
- `6faf1e2`：實作前 13 個測試全部失敗（404 或 405）。原本建議拆成 2～3 個 commit，subagent 合併成一個，因為拆開的中間版本測試會失敗。
- `a57d58d`：Standards review 指出兩個問題，已修正：form 的註解說錯了規則所在的位置（應為 `AccountInputRules`）；AccountPagesTests 與 NavbarTests 的帳號流程 helper 重複，抽成 `AccountFlow`。

### 驗證結果
對照 #10 的 AC 與 identity-auth §8：

| AC / §8 | 結果 |
|---|---|
| 7 碼密碼註冊失敗並顯示欄位錯誤；8 碼成功並自動登入 | ✅ |
| 已有 `A@x.com` 時以 `a@x.com` 註冊失敗 | ✅ |
| 錯誤密碼與不存在的 email 顯示相同訊息 | ✅ 錯誤區塊的 HTML 完全相同 |
| cookie 具備 HttpOnly、Secure、SameSite=Lax | ✅ |
| token 過期後頁面導向登入頁、JSON 回 401 | ✅（A6） |
| 缺少 antiforgery token 的 POST 回 400 | ✅ |
| `returnUrl=https://evil.example` 導向 `/` | ✅ |
| 同 IP 一分鐘內第 6 次登入回 429 | ⏸ 暫緩，見 `Docs/TODO.md` |
| 導覽列顯示顯示名稱與登出按鈕 | ✅（A9） |
| §8 第 8 條：`pendingAction` 登入後自動加入書單 | ⏸ 屬於 #11 |
| `dotnet test` 通過 | ✅ |

另外驗證了：已登入者進入登入或註冊頁會被導向 `/`；登出後 cookie 失效；重新顯示的表單不含密碼；DB 中存的是雜湊而非明文，email 保留原始大小寫。

### 未解決事項
- token 過期的使用者按「登出」時，會先被導向登入頁，不會直接回到 `/`。cookie 的 Max-Age 和 token 效期相同，這時瀏覽器也已經刪掉 cookie，所以實際上沒有影響。

### Code Review 與修正
- 見上方執行紀錄的 `a57d58d`。

## A9 導覽列

### 變更檔案
| 檔案 | 類型 | 說明 |
|---|---|---|
| `Views/Shared/_Layout.cshtml` | 修改 | 右側依登入狀態切換：未登入顯示「登入 / 註冊」；已登入顯示 `User.Identity.Name` 和登出 form |
| `tests/WebIntegration/NavbarTests.cs` | 新增 | 4 個測試 |

### 實作思路
- display_name 取自 JWT 的 `name` claim，以 Razor 預設的 HTML 編碼輸出。登出是帶 antiforgery token 的 POST form。

### 執行紀錄（Log）
- `0b60633`：紅燈時 3 個失敗、1 個通過（未登入的情況原本就正確）。

### 驗證結果
- 測試涵蓋：未登入和已登入時的導覽列內容；`<script>alert(1)</script>` 會被編碼成 `&lt;script&gt;`；用導覽列的 token 登出後，導覽列恢復未登入狀態。

### 未解決事項
- 無。

### Code Review 與修正
- 無需修正。

## 最終驗證

- `dotnet build`：0 Warning(s)，0 Error(s)。
- `dotnet test`：UnitTests 161、DatabaseIntegration 19、WebIntegration 126，全部通過。
- 兩軸 code review（Standards、Spec）的每項發現，主 agent 都已親自驗證。決定接受、不修改的有：
  - 欄位錯誤的 key 使用字串字面值。
  - Controller 中 GET 與 InvalidInput 分支的小重複。
  - `ReturnUrl` 與 `PendingAction` 總是一起出現（#11 處理 pendingAction 時再評估）。
  - 簽 key 的 helper 與 `NewUser()` 在兩個測試專案各有一份（程式碼很小，跨專案共用不划算）。
- `e4c47e4` 與 `c8ce8ba`（A1、A2）的 Co-Authored-By 寫成 Claude Opus 5.5，但程式由 Haiku 撰寫。這是主 agent 的指示錯誤，A3 起已改用 subagent 自己的署名。為避免改寫歷史，前兩個 commit 未修改。
