# Identity / Auth Module

> Path: `Docs/modules/identity-auth.md`
> Authority: 註冊、登入、登出、目前使用者、JWT 與 cookie、認證相關安全規則
> Requirements: AUTH-01～05、LIB-02
> 相關 ADR：ADR-004（JWT 以 HttpOnly cookie 傳遞）
> Data contract: `Docs/data/data-model.md` §5.9 `users`

## 1. Scope

- 註冊、登入、登出、取得目前使用者。
- 簽發與驗證 JWT。
- 登入後執行待辦動作（未登入時按「加入書單」）。

MVP 不做：Google 帳號登入、email 驗證、忘記密碼、修改個人資料、refresh token。

## 2. Invariants

1. 密碼只保存雜湊，不保存、不記錄明文。
2. JWT 只存在 `HttpOnly` cookie；JavaScript 無法讀取。
3. 所有改變狀態的請求（表單 POST 與 JSON 端點）必須通過 antiforgery 驗證。
4. 登入失敗訊息不透露 email 是否已註冊。
5. 不為了讓功能能跑而放寬 authorization 或關閉 CSRF 驗證（見 `AGENTS.md` §2.3）。

## 3. 註冊

| 欄位 | 規則 |
|---|---|
| email | 必填；去除前後空白；格式驗證；最多 320 字元；保留原大小寫儲存；`lower(email)` 唯一 |
| password | 必填；8～40 碼；不限制字元種類（上限避免超長輸入拖慢 PBKDF2） |
| display_name | 必填；去除前後空白後 1～100 字（以 Unicode code point 計，與 `varchar(100)` 一致） |

- 雜湊使用 ASP.NET Core `PasswordHasher<User>`（PBKDF2），**不導入完整 ASP.NET Core Identity**。
- email 已存在（含同時註冊造成的 unique 衝突）→ 欄位錯誤「此 email 已被註冊」。註冊端點本來就會透露此資訊，可接受；登入端點不可以。
- 註冊成功後直接登入（簽發 cookie），並依 `returnUrl` 導向（見 §6）。

## 4. 登入 / 登出

登入：

- 以 `lower(email)` 查詢使用者並驗證密碼。
- 失敗 → 統一顯示「帳號或密碼錯誤」。
- `PasswordHasher` 回傳 `SuccessRehashNeeded` 時更新 `password_hash`。

登出：

- 刪除 cookie。伺服器端不撤銷 token；已竊取的 token 在剩餘效期內仍有效（已接受的風險，效期 1 天）。

## 5. JWT 與 Cookie

| 項目 | 值 |
|---|---|
| 演算法 | HS256 |
| Signing key | 來自 secret（SSM / user-secrets），不得進 repository |
| 效期 | 1 天，不滑動延長，無 refresh token；驗證時 ClockSkew = 0 |
| Claims | `sub` = `users.id`、`name` = display_name、`exp`、`iat` |
| Cookie | `HttpOnly`、`Secure`、`SameSite=Lax`、`Path=/`、Max-Age = token 效期 |

- JWT Bearer middleware 設定為從 cookie 讀取 token（`OnMessageReceived`）。
- Token 過期 → 視為未登入：頁面導向 `/account/login?returnUrl=...`；JSON 端點回 401。
- 目前使用者由 `sub` claim 取得；需要最新 display_name 時查 DB。

## 6. returnUrl 與待辦動作

- `returnUrl` 只接受本站相對路徑（`Url.IsLocalUrl`），否則導向 `/`，防止 open redirect。
- 已登入者進入登入 / 註冊頁 → 一律導向 `/`。
- 未登入時在 Book 詳細頁按「加入書單」：導向 `/account/login?returnUrl=/books/{id}&pendingAction=add-to-library`。
- 登入或註冊成功後，若 `pendingAction=add-to-library` 且 `returnUrl` 為 `/books/{id}`：
  1. 依 `user-library.md` 加入規則加入該書（已存在則不變）；
  2. 導向 `/books/{id}`。
- 不認得的 `pendingAction` 忽略。

## 7. Rate Limiting

> **暫緩**（使用者於 2026-10-20 決定）：#10 不實作，見 `Docs/TODO.md`。以下為恢復實作時的目標規格。

- 登入與註冊 POST：每個 IP 每分鐘 5 次（ASP.NET Core rate limiter，fixed window）。
- 超過 → 429，頁面顯示「嘗試次數過多，請稍後再試」。
- `web` 位於 nginx 之後，client IP 取自 `X-Forwarded-For`（只信任 nginx，見 `deployment.md`）。

## 8. Validation

1. 密碼 7 碼 → 欄位錯誤；8 碼 → 成功。
2. `A@x.com` 已存在時以 `a@x.com` 註冊 → 失敗。
3. 錯誤密碼與不存在的 email → 相同錯誤訊息。
4. 登入後 cookie 具備 `HttpOnly`、`Secure`、`SameSite=Lax`。
5. 過期 token → 頁面導向登入、JSON 回 401。
6. 缺 antiforgery token 的 POST → 400。
7. `returnUrl=https://evil.example` → 導向 `/`。
8. `pendingAction=add-to-library` 登入後 → 該書在 Library 中。
9. 第 6 次登入嘗試（同 IP 一分鐘內）→ 429。（暫緩，見 §7）
