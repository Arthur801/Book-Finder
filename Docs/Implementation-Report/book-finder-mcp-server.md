# Book-Finder MCP Server 實作報告

> 計畫：[Docs/plans/book-finder-mcp-server.md](../plans/book-finder-mcp-server.md)（v1.6，使用者決定 D-01～D-12）。日期：2026-11-14。
>
> 本報告是實作紀錄，不是規格；current contract 以各模組 `docs/` 為準（AGENTS.md §3.2），特別是 [Mcp/docs/](../../Mcp/docs/architecture.md) 與 Infrastructure docs 的「MCP OAuth Authorization Server」一節。
>
> **production 狀態（2026-11-15）：** v0.0.12 已帶 migration `20261114082838_AddOpenIddict`（開關關閉，上線手冊步驟 1）；開啟 MCP 的 compose 變更已備妥（步驟 3），部署前必須先完成步驟 2 的憑證 volume。開啟步驟見文末「上線手冊」，每一步都需要使用者授權。

## 變更檔案

| 模組 | 檔案 | 票 |
|---|---|---|
| Mcp（新） | `McpOptions.cs`、`McpServiceCollectionExtensions.cs`、`McpUrlBuilder.cs` | MCP-001、M1 |
| Mcp | `Security/McpAuthSetup.cs`、`Security/McpToolAuthorizationMiddleware.cs`、`Security/ToolSecuritySchemes.cs` | MCP-002、MCP-202、M3、M5 |
| Mcp | `Tools/BookSearchTools.cs`、`Tools/RecommendationTools.cs` | M1、M3、M4 |
| Mcp | `Services/McpBookSearchService.cs`、`McpRecommendationService.cs`、`McpRecommendationResultService.cs` 與結果型別 | M1、M3、M4 |
| Mcp | `Contracts/*`（對外 DTO） | M1、M3、M4 |
| Infrastructure | `Identity/OAuth/OAuthOptions.cs`、`OAuthServiceCollectionExtensions.cs`、`OAuthClientSync.cs`；`Persistence/AppDbContext.cs`（`UseOpenIddict`）；migration `20261114082838_AddOpenIddict`；`Persistence/EfUserStore.cs`（`FindByIdAsync`） | MCP-201a、201b、202 |
| Application | `Identity/IUserStore.cs`（`FindByIdAsync`） | MCP-201b |
| Controllers／Views／Models | `OAuthController.cs`、`Views/OAuth/Consent.cshtml`、`OAuthConsentViewModel.cs` | MCP-201b |
| 根目錄 | `Program.cs`（註冊與 `MapBookFinderMcp`）、`appsettings.json`（`Mcp` 區塊）、`Book-Finder.csproj`（MCP SDK 2.3.1、OpenIddict 7.8.0、EF Core 10.0.14）、`dotnet-tools.json`（dotnet-ef 10.0.14）、`CONTEXT.md` | 多張 |
| deploy | `migration-test/seeds/20261114082838_AddOpenIddict.sql` | MCP-201a |
| tests | UnitTests、DatabaseIntegration、WebIntegration 新增 MCP／OAuth 測試；`tests/Shared` 新增 fake | 全部 |

PR：#203（計畫）、#204（MCP-001）、#205（MCP-002）、#206（M1）、#207（MCP-003 ADR）、#208（MCP-201a）、#209（MCP-201b）、#210（MCP-202）、#211（M3）、#212（M4）、本 PR（M5）。

## 實作思路

- **Modular monolith**：MCP 與網站同一個 process、同一個網域；`Mcp/` 只做協定轉換，搜尋與推薦都呼叫既有的 Application service（`IBookSearch`、`RecommendationJobService`、`IRecommendationHistory`），不碰 DB、不呼叫 OpenAI。
- **單一 `/mcp`，per-tool 授權（D-04）**：SDK 的 `[Authorize]` 只回 JSON-RPC 錯誤，MCP Client 不會因此啟動 OAuth，所以在 `MapMcp` 前加一層閘門，SDK 讀 body 之前就決定 401／403／413。閘門 fail closed：無法解析的 body、大小寫不同的 method、`Mcp-Name` header 都當成受保護呼叫。
- **兩套認證分離**：網站仍是 `bf_auth` cookie；MCP 只接受 `Authorization: Bearer`，由 OpenIddict validation（local server）驗證同站簽發的 JWE。audience 必須是 `https://khwebsc.com/mcp`，並檢查 token 與授權記錄（撤銷即失效）。網站 JWT 不能冒充 MCP token，MCP token 也不能登入網站。
- **同站 OpenIddict（D-02、D-03）**：Authorization Code + PKCE（只有 S256）、refresh token；不做 DCR；Client 從設定預註冊。登入沿用 `/account/login`；consent 記住到撤銷（D-10）。
- **AI 推薦非同步**：`recommend_books` 只排入既有的 Recommendation Job，`get_recommendation_result` 讀結果；額度與網站共用（D-07）。
- **對外連結只來自設定**：`Mcp:PublicBaseUrl` 與 OpenIddict issuer 都不讀 Host header。

## 執行紀錄（Log）

| 票 | 重點 |
|---|---|
| MCP-001 | SDK 2.3.1 回應一律是 SSE，沒有 JSON response 選項；沒有 Tool 時 SDK 不提供 `tools/list`，暫時用空 handler |
| MCP-002 | 確認單一 `/mcp` 可行；驗收時把閘門改成 fail closed（`7485e53`）；2026-07-28 協定需要 `Mcp-Method`／`Mcp-Name` header 與 `params._meta` |
| MCP-003 | 研究三類 Client：Claude、VS Code 可預註冊；ChatGPT 優先 CIMD，預註冊介面不明 |
| MCP-201a | OpenIddict 7.8.0 需要 EF Core 10.0.14（升級）；discovery 端點改從 issuer 產生，避免 Host header 注入 |
| MCP-201b | 驗收時發現 consent 頁可被他站 iframe（clickjacking），加 `X-Frame-Options: DENY` 與 `frame-ancestors 'none'`（`a93db00`）；#209 被 CodeQL ruleset 擋下（URL redirection），改用 `LocalRedirect`（`1829507`） |
| MCP-202 | OpenIddict 發的是 JWE，JwtBearer 無法驗證，改用 OpenIddict validation；OpenIddict 預設也從 query string 與 form body 讀 token，已關閉並以 options 斷言鎖住 |
| M3 | SDK 的 `Tool` 沒有地方放頂層 `securitySchemes`，用 outgoing filter 加上（頂層與 `_meta`）；選填參數必須是 nullable 且預設 `null` |
| M4 | `failed` 是查詢成功、工作失敗，回 `isError = false` |
| M5 | 兩軸 code review 與修正（見下） |

## 驗證結果

每個模組都由主 agent 以 `dotnet build --no-incremental`（0 warning）與受影響的測試專案重跑驗收；L3 模組做 mutation 抽查，每個 mutation 都有測試抓到（必要時補測試）。數字見各 PR 與 [Mcp/docs/test-suite.md](../../Mcp/docs/test-suite.md)。

M5 完整驗證（2026-11-14，分支 `mcp-m5-report`）：

| 項目 | 結果 |
|---|---|
| `dotnet build --no-incremental` | 0 warning、0 error |
| UnitTests | 1143 passed |
| DatabaseIntegration | 254 passed |
| WebIntegration | 444 passed |
| `deploy/tests` | 722 passed、17 skipped |

開工前（`8c8e3ab`）的基準是 984／249／337；新增的測試全部與 MCP、OAuth 有關。

尚未驗證：真實 MCP Client（ChatGPT、Claude、IDE）的端到端流程（MCP-203），需要 production 發布。

## 未解決事項

| 項目 | 狀態 |
|---|---|
| MCP-203 真實 Client 實測（D-01、D-08） | 待 production 授權；見上線手冊 |
| ChatGPT 的連結帳號 UI 由 Tool 錯誤 `_meta["mcp/www_authenticate"]` 觸發，不是 HTTP 401；授權後是否重送原請求未記載（MCP-B12） | MCP-203 實測後決定 |
| ChatGPT 預註冊介面不明，可能需要 allowlist 版 CIMD（MCP-B11） | MCP-203 |
| 憑證密碼的注入方式 | 已決定（D-12）：不設密碼，external volume `book-finder-oauth-certs`（檔案屬 container 使用者 UID 1654、權限 0400）；host 不需新增 secret |
| 全站 framing 政策（MCP-B16） | 待使用者決定 |
| OAuth endpoint 防暴力嘗試（MCP-B20，與 CTL-02 一起） | 待決策 |
| 撤銷授權管理頁（D-10） | 本期不做 |
| Tool 契約 snapshot、重複程式整理（MCP-B19、B22） | 改善提案 |

## Code Review 與修正

範圍：`8c8e3ab...mcp-m4-result`（35 個 commit），Standards 與 Spec 兩軸平行審查，主 agent 逐項確認。

**Standards**

- 依賴方向乾淨：Infrastructure、Application、Controllers 都不參照 Mcp；Mcp 不碰 `AppDbContext`／SQL／OpenAI；唯一的 log 只記 id。
- 修正：
  - `Mcp/docs/architecture.md` 的依賴方向漏列 `IRecommendationHistory` 與 OpenIddict（文件 drift）→ 已補。
  - 受保護 Tool 名單散在閘門、`ToolSecuritySchemes`、Tool attribute 三處（Shotgun Surgery；新增 Tool 時漏改閘門會變成匿名可用）→ `securitySchemes` 改由 `McpAuthSetup.ProtectedToolNames` 推導；主 agent 驗收時發現 subagent 的一致性測試從同一份名單推導、抓不到漏列，另補**預設拒絕**測試（每支 Tool 必須明確列為公開或在受保護名單內；mutation 驗證有效）。
  - `books:recommend` 兩處常數 → 以 unit test 鎖住相同值。
  - 三份重複的 fake job store／history → 移到 `tests/Shared/`。
  - 過時註解。
- 不改（記 MCP-B21、B22）：`Mcp:Enabled` 字串讀取（依賴方向的取捨）、helper 與 status 對應的重複、失敗文案兩份（已有 unit test 比對，MCP-B18）。

**Spec**

- 核對通過：未授權 0 Job 0 額度、`NOT_FOUND` 不洩漏、連結只來自設定、50 本與 `hasMore`、D-06／D-07／D-09／D-10／D-11、網站 JWT 不能冒用、log 不含需求文字。
- 修正：
  - `get_recommendation_result` 描述補「不要向使用者索取帳號密碼或 token」（計畫 §3.3）。
  - 補「MCP token 不能登入網站」的 HTTP 測試（計畫 §2）。
  - `CONTEXT.md` 補 MCP Tool、MCP Client、MCP Access Token、`books:recommend` scope（計畫 §8）。
  - 過時的 test-suite 敘述與計畫狀態。
  - backlog 補 Tool 契約 snapshot（MCP-B19）、OAuth 防暴力嘗試（MCP-B20）。
- 接受的偏離：T11（缺 scope → 403）只有 unit test（本站流程拿不到缺 scope 的 token）；帶無效 Bearer 呼叫公開 Tool 也 401、handler 層 `UNAUTHORIZED`、回應多出 `created`／`historyListUrl` 等欄位，都是防禦性或資訊性，已記在 Mcp docs。

## 上線手冊

前提：#203～本 PR 都已合併。**每一步都需要使用者執行或明確授權**（L4）。

1. **部署開關關閉的版本**：
   - 打 tag，CD 部署。這個 release 帶 migration `20261114082838_AddOpenIddict`（只新增四張表），`Mcp:Enabled` 為 false，網站行為不變。
   - 部署前在 EC2 執行 `df -h /`（DEP-B24）；plan 應為 `pending` 含 `20261114082838_AddOpenIddict`，compat 載入 `20261114032619_AddRecommendationJobs.sql`。
   - Smoke：網站首頁、搜尋、登入、`/ai` 正常；`/mcp`、`/oauth/authorize`、`/.well-known/oauth-authorization-server` 都是未 map（404／405）。
2. **在 EC2 建立 OpenIddict 憑證**（D-12；`wizard` 帶步驟）：產生簽章與加密兩張**不設密碼**的 PKCS#12 憑證，放進 external named volume `book-finder-oauth-certs`（host 上只有 root 進得去；檔案擁有者必須是 container 使用者 UID 1654、權限 0400，否則非 root 的 container 讀不到），container 唯讀掛載於 `/oauth-certs`；憑證要帶 keyUsage（簽章 `digitalSignature`、加密 `keyEncipherment`），以 `X509CertificateLoader` 不帶密碼載入（本機以 OpenIddict 7.8.0 驗證過）；憑證不進 repo、不進 image；記錄備份方式與輪替程序（MCP-B13）。
3. **開啟 MCP 的 release**（PR 修改 `deploy/release/compose.prod.yaml`；`Mcp:PublicBaseUrl` 沿用 appsettings 的 `https://khwebsc.com`，client_id 為 `claude`、`vscode`、`chatgpt`；VS Code redirect URI 先列 `http://127.0.0.1:33418` 與 `https://vscode.dev/redirect`）：
   - `environment`：`Mcp__Enabled: "true"`、`Mcp__PublicBaseUrl: "https://khwebsc.com"`、`OAuth__SigningCertificatePath`、`OAuth__EncryptionCertificatePath`（指向唯讀掛載的 volume；不設 `OAuth__CertificatePassword`）；
   - `OAuth__Clients__N__ClientId／DisplayName／RedirectUris__M`：Claude（`https://claude.ai/api/mcp/auth_callback`）、VS Code（實測確認 redirect URI）、ChatGPT（`https://chatgpt.com/connector_platform_oauth_redirect`，或改 CIMD）；
   - `volumes`：唯讀掛載憑證 volume；
   - 合併、打 tag、CD 部署。
4. **host 端確認**：nginx／Cloudflare 把 `/mcp`、`/oauth/*`、`/.well-known/*` 轉到 web container；`Authorization` header 原樣轉發；SSE 回應不被緩衝（MCP-B06）。
5. **MCP-203 實測**（會呼叫真實 OpenAI，需使用者當下授權）：ChatGPT、Claude、IDE 各走一次：匿名 `search_books` → 呼叫 `recommend_books` 觸發登入 → consent → 提交 → `get_recommendation_result` 取得書籍與紀錄連結；記錄每個 Client 是否在授權後自動重送原請求（MCP-B12）。
6. **觀察**：401 次數、OAuth 錯誤、Job 排隊時間、`/mcp` 錯誤率；EC2 CPU、記憶體與 DB 連線。
7. **回退**：發布不含 `Mcp__Enabled` 的 release，或以 CD dispatch 重新部署前一版；`/mcp` 與 `/oauth/*` 消失，網站與推薦 Job 照常。OpenIddict 表與資料保留；撤銷 token 或刪除授權資料需另外授權。
