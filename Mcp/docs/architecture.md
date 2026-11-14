# Mcp 架構

> 建立：2026-11-14（MCP-001，`e618edb`、`4c1b047`）；MCP-002 授權閘門（`df9e333`～`7485e53`）；M1 `search_books`（`da0d0c7`）。實作計畫：[book-finder-mcp-server.md](../../Docs/plans/book-finder-mcp-server.md)（計畫不是 contract；本文件描述目前已實作的狀態）。

## 1. 模組責任

`Mcp/` 是遠端 MCP（Model Context Protocol）Server 的協定層，與網站在同一個 ASP.NET Core process。

- 負責：MCP transport 註冊、`/mcp` 路由、設定（`McpOptions`）；之後的票加入 Tool 參數驗證、DTO、錯誤對應與對外連結。
- 不負責：商業規則、資料存取、AI 呼叫。Tool 只能呼叫 Application 層的 service／port，不得使用 `AppDbContext`、自行下 SQL 或呼叫 OpenAI。

## 2. 目前組成

| 檔案 | 責任 |
|---|---|
| `McpOptions.cs` | `Mcp` 設定：`Enabled`（預設 false）、`PublicBaseUrl`；`HasValidPublicBaseUrl` 在啟動時驗證 |
| `McpServiceCollectionExtensions.cs` | `AddBookFinderMcp`：綁定並驗證設定、註冊官方 SDK（Streamable HTTP、Stateless）與 MCP 認證；`MapBookFinderMcp`：`Enabled` 為 true 才加入授權閘門、resource metadata 與 `MapMcp("/mcp")` |
| `McpUrlBuilder.cs` | 對外連結的唯一來源：`{base}/search?q=`（trim + `Uri.EscapeDataString`）、`/books/{id}`、`/ai/jobs/{id}`、`/ai/history/{id}`、`/ai` |
| `Services/McpBookSearchService.cs` | `search_books` 的 adapter：`SearchQuery.Parse`，`Empty` 回 `VALIDATION_FAILED` 且不碰 DB；其他呼叫 `IBookSearch.SearchAsync(q, 1, 50)`，排序與網站相同 |
| `Tools/BookSearchTools.cs` | `search_books` Tool（公開、`readOnlyHint`）；成功回 structured content + 文字摘要，錯誤 `isError = true` |
| `Services/McpRecommendationService.cs` | `recommend_books` 的 adapter：依序檢查 `RecommendationJobs:Enabled`（關閉 → `SERVICE_UNAVAILABLE`）、`RecommendationInputRules`（→ `VALIDATION_FAILED`）、再呼叫 `RecommendationJobService.SubmitAsync`；對應 `IDEMPOTENCY_CONFLICT`、`DAILY_LIMIT_REACHED`。額度與 idempotency 完全由 Application 處理 |
| `Services/McpRecommendationResultService.cs` | `get_recommendation_result` 的 adapter：開關 → `Guid.TryParse`（失敗同 `NOT_FOUND`）→ `RecommendationJobService.GetAsync`（不存在與別人的同 `NOT_FOUND`）→ 依狀態：queued／running 只回狀態與連結；succeeded 以 `IRecommendationHistory.GetAsync` 讀已保存結果（依 rank、最多 10 本）；succeeded 但讀不到 search → `INTERNAL_ERROR` 並 log id（不產生連結）；failed 回 `errorCode` 與網站 Job 頁相同的文案。只讀，不寫入 |
| `Tools/RecommendationTools.cs` | `recommend_books` 與 `get_recommendation_result` Tool（都需 `books:recommend`）；`failed` 是「查詢成功、工作失敗」，回 `isError = false`，只有 `NOT_FOUND`、`INTERNAL_ERROR`、`UNAUTHORIZED`、`SERVICE_UNAVAILABLE` 回 `isError = true`；使用者只取自 `JsonRpcRequest.Context.User`，沒有已認證使用者時回 `UNAUTHORIZED` 且不呼叫 service（閘門之後的第二道防線）；成功回 `queued`、`jobId`、`statusUrl`、`historyListUrl`、`created`，不含推薦結果 |
| `Security/ToolSecuritySchemes.cs` | outgoing message filter：只改寫 `tools/list` 結果，替每支 Tool 加上 ChatGPT 的 `securitySchemes`（頂層與 `_meta` 各一份）。名單**只有一份**：在 `McpAuthSetup.ProtectedToolNames` 的 Tool 為 `oauth2` + `books:recommend`，其他為 `noauth`（M5）；新增 Tool 時預設拒絕測試會要求明確歸類。SDK 2.3.1 的 `Tool` 沒有可放頂層欄位的 extension data，所以用 filter |
| `Contracts/*.cs` | 對外 DTO（lowerCamelCase）：`BookSearchToolResult`、`RecommendationSubmitToolResult`、`RecommendationStatusToolResult`（null 欄位由 `McpJsonUtilities.DefaultOptions` 省略）、`McpToolError` |
| `Security/McpAuthSetup.cs` | Bearer scheme 常數（指向 OpenIddict validation 的 scheme，MCP-202）、SDK 的 challenge scheme 與 Protected Resource Metadata；受保護 Tool 名稱、`books:recommend` scope |
| `Security/McpToolAuthorizationMiddleware.cs` | POST `/mcp` 的授權閘門：在 SDK 讀 body 前決定 401／403／413 或放行 |

`Program.cs` 只有兩個接點：`AddBookFinderMcp`（在 `AddRecommendationJobs` 之後）與 `MapBookFinderMcp`（在 `UseAuthorization` 之後、MVC route 之前）。

## 3. 架構決策

| 項目 | 目前狀態 | 理由 |
|---|---|---|
| SDK | `ModelContextProtocol.AspNetCore` **2.3.1**（精確釘版） | 協定由官方 SDK 實作；2.4.0 發布未滿兩週，先用較穩的 patch 版 |
| Transport | Streamable HTTP、`Stateless = true` | 不保存 MCP session；之後以 Job ID 跨呼叫追蹤 |
| 回應格式 | 一律 SSE（`text/event-stream`，一個 `event: message`） | SDK 2.3.1 的 `HttpServerTransportOptions` 沒有 JSON response 選項；回應帶 `Cache-Control: no-store, no-cache` 與 `X-Accel-Buffering: no`，nginx 不會緩衝 |
| 開關 | `Mcp:Enabled` 在啟動時讀取；false 時 `/mcp` 完全不 map | 與網站其他未 map 的路徑行為相同（GET 404、POST 405） |
| 認證 | OpenIddict validation（同 process 的 local server，MCP-202）驗證同站簽發的 access token（JWE）：audience 必須是 `{base}/mcp`，並查 token 與 authorization 記錄（撤銷即失效）；token **只**從 `Authorization: Bearer` 讀取（關閉 query string 與 form body）；網站 cookie 身分在 `/mcp` 一律被清除 | 預設 cookie scheme 對非 `/api` 路徑回 302，不能用於 OAuth challenge；網站 JWT 的 issuer／audience 與 MCP 不同，不能冒用 |
| 單一 endpoint 的 per-tool 授權 | 自訂閘門（計畫 §3.5 選項 2），不用 SDK 的 `[Authorize]` | SDK 的 `[Authorize]` 只回 JSON-RPC 錯誤，MCP Client 不會因此啟動 OAuth；MCP-002 證明閘門可在 2025-11-25 與 2026-07-28 兩個協定版本回 HTTP 401（D-04 採單一 `/mcp`） |
| 閘門判斷 | 讀 body（上限 256 KiB，超過 413）；任一 JSON-RPC 訊息是受保護名稱的 `tools/call`（method、key、名稱都不分大小寫，重複 key 全檢查）、或 `Mcp-Name` header 是受保護名稱、或 body 無法解析，就視為受保護 | fail closed：比閘門寬鬆的 parser 也無法匿名抵達受保護 Tool |
| 閘門結果 | 帶 `Authorization` 但驗證失敗 → 401（公開 Tool 也一樣）；受保護且未認證 → 401 `WWW-Authenticate: Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"`；缺 scope → 403 `insufficient_scope`；拒絕時不呼叫 SDK | 未授權時 Tool handler 不會執行，不會建立 Job 或扣額度 |
| Resource metadata | 自行 `MapGet` `/.well-known/oauth-protected-resource/mcp`，內容來自設定 | SDK 只有在 `ResourceMetadataUri` 未設定時才自動服務，且那時 URI 取自 request host |
| Scope 判斷 | `HasScope` 讀 OpenIddict 的 `oi_scp`（每個 scope 一個 claim）以及 `scope`／`scp` 空白分隔字串 | 不依賴 token 用哪一種形式 |
| Tool 取得使用者 | `RequestContext<CallToolRequestParams>.JsonRpcRequest.Context?.User` | stateless HTTP 下 SDK 帶入閘門設定的 principal |
| Tool | `WithTools<BookSearchTools>()`、`WithTools<RecommendationTools>()`：`search_books`、`recommend_books`、`get_recommendation_result` | 選填參數（`idempotency_key`）必須是 nullable 且有預設值 `null`，否則 SDK 把它當必填；inputSchema 為 `["string","null"]` |
| Tool 輸出 | 手動設定 `CallToolResult.StructuredContent`（`McpJsonUtilities.DefaultOptions`），不宣告 outputSchema | SDK 的 `UseStructuredContent = true` 會產生不準確的通用 outputSchema |
| 一般搜尋上限 | 最多 50 本；`totalCount` 為實際符合筆數、`hasMore = totalCount > 50`；不另設輸入長度、rate limit、timeout | 比照網站搜尋（D-06）；網站每頁 20 本不變 |
| 對外連結 | `PublicBaseUrl` 必須是 https 根網址（開發可用 `http://localhost`、`127.0.0.1`），不得有 path、query、fragment；只由 `McpUrlBuilder` 產生 | 連結只從設定產生，不讀 Host header |

## 4. 相依方向

```text
Program.cs → Mcp（AddBookFinderMcp / MapBookFinderMcp）→ ModelContextProtocol.AspNetCore
Mcp → Application（Catalog：SearchQuery、IBookSearch；Recommendation：RecommendationJobService、RecommendationInputRules、RecommendationJobOptions、IRecommendationHistory、RecommendationJobErrorCodes）
Mcp → OpenIddict 套件（只用 validation 的 scheme 常數與 `OpenIddictConstants` 的 scope claim 型別；token 驗證由 Infrastructure 註冊）
Mcp → Infrastructure/Identity（只有 `CurrentUser.CurrentUserId()`，與 Controllers 相同的讀 `sub` 方式）
```

`Mcp` 不被 Application、Infrastructure、Controllers 參照。

## 5. 執行環境

- 設定預設值在 `appsettings.json`：`Mcp:Enabled = false`、`Mcp:PublicBaseUrl = https://khwebsc.com`。
- production 自 v0.0.13 開啟（#214：`deploy/release/compose.prod.yaml` 的 `Mcp__Enabled`、OAuth 憑證路徑與三個預註冊 Client）；2026-11-15 使用者以 ChatGPT、Claude、VS Code 實測通過（MCP-203）。開關只能隨 release 改變。
- `/mcp` POST 不經 MVC，所以不受全域 antiforgery filter 影響，也不設 cookie。
- 2026-07-28 協定的 request 必須帶 `Mcp-Method`、`Mcp-Name` header，且 `params._meta` 含 protocolVersion、clientInfo、clientCapabilities；SDK 檢查 header 與 body 一致。2025-11-25 在 stateless 下不經 initialize 也能直接 `tools/call`。

- 使用者文件：網站的 `/mcp-guide`（[Views/McpGuide/Index.cshtml](../../Views/McpGuide/Index.cshtml)）寫給終端使用者，列出 MCP 網址、三個預註冊 client_id、Tool 用途、500 字與 50 本上限、每日額度、token 效期與錯誤碼。這些值改變時（Tool、錯誤碼、OAuth Client、額度、效期）要同步修改該頁。

## 6. MCP-ADR-007：OpenIddict 與 Client Registration（MCP-003，2026-11-14）

**狀態**：Accepted（D-02、D-03）。下列「待實測」項目在 MCP-201／MCP-203 確認後更新本節。

### 6.1 決定

- Authorization Server：同站 **OpenIddict 7.8.0**（最新穩定版，2026-11-03；8.0 仍為 preview）。issuer `https://khwebsc.com/`；authorize `/oauth/authorize`、token `/oauth/token`；只開 Authorization Code + PKCE（S256）與 refresh token。
- Client Registration：**預註冊優先；Client 不支援預註冊時用 CIMD；不做 DCR**（不公開 `registration_endpoint`）。
- Resource：`https://khwebsc.com/mcp`（access token 的 `aud`）；scope 只有 `books:recommend`。

### 6.2 三類 Client 的註冊方式（依公開文件，待 MCP-203 實測）

| Client | 預註冊 | CIMD | redirect URI | 本專案採用 |
|---|---|---|---|---|
| Claude（claude.ai 自訂 connector） | 支援：Advanced settings 可填 OAuth Client ID／Secret（secret 可留空） | 支援（預設「Claude's published identity」） | `https://claude.ai/api/mcp/auth_callback` | **預註冊** public client |
| ChatGPT（connector／plugin） | 文件列出「predefined OAuth clients」，但沒有說明在哪裡填 client_id | 支援且優先：`client_id` 為 `https://chatgpt.com/oauth/client.json`（或 callback 專屬變體），token 交換用 `none` + PKCE | `https://chatgpt.com/connector_platform_oauth_redirect`（AS 支援 RFC 9207 `iss` 時），否則 `https://chatgpt.com/connector/oauth/{callback_id}` | 先試預註冊；**找不到填 client_id 的介面就改 CIMD** |
| VS Code（IDE） | 支援：`mcp.json` 的 `oauth.clientId`；優先順序為設定的 client ID → CIMD → DCR | 支援：`https://vscode.dev/oauth/client-metadata.json` | 待實測確認（loopback 與 vscode.dev 兩種） | **預註冊** public client |

### 6.3 OpenIddict 必須提供的 metadata（ChatGPT 文件明列，其他 Client 依 MCP 規格）

- `code_challenge_methods_supported` 含 `S256`（ChatGPT：缺少就不支援該 server）。
- `authorization_response_iss_parameter_supported: true`，且每個 authorization response（含錯誤）都帶 `iss`，與 issuer 完全一致——ChatGPT 才會用穩定的 redirect URI。**待確認 OpenIddict 7.8 是否原生支援**。
- 接受 `resource=https://khwebsc.com/mcp`（authorize 與 token 兩個 request 都會帶），token 的 `aud` 等於它。**待確認 OpenIddict 對 RFC 8707 resource 參數的處理**；不支援時以自訂 handler 驗證 resource 並設定 audience。
- `token_endpoint_auth_methods_supported` 含 `none`（public client + PKCE）。
- 採用 CIMD 時加 `client_id_metadata_document_supported: true`。

### 6.4 CIMD（只在需要時實作）

OpenIddict 沒有原生 CIMD 支援（只有第三方 ABP 套件與提案）。需要時自行實作：

- `client_id` 是 HTTPS URL 時才走 CIMD；**allowlist** 只接受已知的 Client metadata URL（例如 `https://chatgpt.com/oauth/client.json`），不抓任意 URL，避免 SSRF。
- 抓取限制：只 HTTPS、大小上限、逾時、不跟隨跨網域轉址；文件內 `client_id` 必須與 URL 完全相同；`redirect_uri` 必須在文件的 `redirect_uris` 內。
- 結果快取並存成 OpenIddict application（public client），之後的流程與預註冊相同。

### 6.5 風險：ChatGPT 對「部分 Tool 需要登入」的處理

ChatGPT 文件描述兩種機制：

1. HTTP 401 + `WWW-Authenticate`（指向 resource metadata）：「讓 Client 重新執行 OAuth」——MCP-002 的閘門即此機制。
2. Tool 層：Tool 描述帶 `securitySchemes`（例如 `[{"type":"oauth2","scopes":["books:recommend"]}]`），未授權時回 `isError: true` 且 `_meta["mcp/www_authenticate"]` 含 `error` 與 `error_description`，ChatGPT 才會顯示連結帳號 UI。

**決定**：維持 HTTP 401 閘門（Claude、VS Code 依 MCP 規格處理）；`recommend_books`、`get_recommendation_result` 的描述一律加上 `securitySchemes`（對其他 Client 無害）。MCP-203 若證實 ChatGPT 在 HTTP 401 下不會啟動連結流程，再評估針對 ChatGPT 改回 Tool 層錯誤（需確認如何可靠識別 ChatGPT，並保持「未授權不執行 handler」）。

### 6.6 影響

- 新增 OpenIddict 資料表（applications、authorizations、scopes、tokens）→ EF migration + `deploy/migration-test/seeds/<head>.sql`（DEP-B25），L3。
- 簽章與加密金鑰（D-11、D-12）：production 用兩張**不設密碼**的 PKCS#12 憑證，放在 external named volume `book-finder-oauth-certs`（`/var/lib/docker/volumes` 只有 host root 進得去；檔案擁有者是 container 使用者 UID 1654、權限 0400，因為 container 不以 root 執行），container 唯讀掛載於 `/oauth-certs`（與 Data Protection keys 相同保護方式）；不進 repo、不進 image；需要輪替與備份程序（L4，需使用者授權）。開發與測試用 ephemeral key。
- 預註冊 Client 以設定或 seed 建立（client_id、redirect URI、scope），無 client secret。
- Consent 頁：沿用網站版面與 `bf_auth` 登入；顯示 Client 名稱與 scope。
- `/mcp` 的 bearer 驗證改用 OpenIddict validation（已完成，MCP-202）。

來源（2026-11-14 讀取）：[OpenAI Authentication](https://developers.openai.com/plugins/build/auth)、[Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)、[Zuplo VS Code 相容性](https://zuplo.com/learn/mcp/compatibility/clients/vs-code)、[MCP Client Registration 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)、[AuthEndpoints #428](https://github.com/madeyoga/AuthEndpoints/issues/428)。表中標「待實測」的項目不是已驗證事實。
