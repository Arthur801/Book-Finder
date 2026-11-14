# Mcp 架構

> 建立：2026-11-14（MCP-001，`e618edb`、`4c1b047`）；MCP-002 授權閘門（`df9e333`～`7485e53`）。實作計畫：[book-finder-mcp-server.md](../../Docs/plans/book-finder-mcp-server.md)（計畫不是 contract；本文件描述目前已實作的狀態）。

## 1. 模組責任

`Mcp/` 是遠端 MCP（Model Context Protocol）Server 的協定層，與網站在同一個 ASP.NET Core process。

- 負責：MCP transport 註冊、`/mcp` 路由、設定（`McpOptions`）；之後的票加入 Tool 參數驗證、DTO、錯誤對應與對外連結。
- 不負責：商業規則、資料存取、AI 呼叫。Tool 只能呼叫 Application 層的 service／port，不得使用 `AppDbContext`、自行下 SQL 或呼叫 OpenAI。

## 2. 目前組成

| 檔案 | 責任 |
|---|---|
| `McpOptions.cs` | `Mcp` 設定：`Enabled`（預設 false）、`PublicBaseUrl`；`HasValidPublicBaseUrl` 在啟動時驗證 |
| `McpServiceCollectionExtensions.cs` | `AddBookFinderMcp`：綁定並驗證設定、註冊官方 SDK（Streamable HTTP、Stateless）與 MCP 認證；`MapBookFinderMcp`：`Enabled` 為 true 才加入授權閘門、resource metadata 與 `MapMcp("/mcp")` |
| `Security/McpAuthSetup.cs` | `McpBearer` scheme（只讀 `Authorization: Bearer`，issuer `{base}/`、audience `{base}/mcp`）、SDK 的 challenge scheme 與 Protected Resource Metadata；受保護 Tool 名稱、`books:recommend` scope |
| `Security/McpToolAuthorizationMiddleware.cs` | POST `/mcp` 的授權閘門：在 SDK 讀 body 前決定 401／403／413 或放行 |

`Program.cs` 只有兩個接點：`AddBookFinderMcp`（在 `AddRecommendationJobs` 之後）與 `MapBookFinderMcp`（在 `UseAuthorization` 之後、MVC route 之前）。

## 3. 架構決策

| 項目 | 目前狀態 | 理由 |
|---|---|---|
| SDK | `ModelContextProtocol.AspNetCore` **2.3.1**（精確釘版） | 協定由官方 SDK 實作；2.4.0 發布未滿兩週，先用較穩的 patch 版 |
| Transport | Streamable HTTP、`Stateless = true` | 不保存 MCP session；之後以 Job ID 跨呼叫追蹤 |
| 回應格式 | 一律 SSE（`text/event-stream`，一個 `event: message`） | SDK 2.3.1 的 `HttpServerTransportOptions` 沒有 JSON response 選項；回應帶 `Cache-Control: no-store, no-cache` 與 `X-Accel-Buffering: no`，nginx 不會緩衝 |
| 開關 | `Mcp:Enabled` 在啟動時讀取；false 時 `/mcp` 完全不 map | 與網站其他未 map 的路徑行為相同（GET 404、POST 405） |
| 認證 | 獨立 `McpBearer` scheme；網站 cookie 身分在 `/mcp` 一律被清除 | 預設 cookie scheme 對非 `/api` 路徑回 302，不能用於 OAuth challenge；網站 JWT 的 issuer／audience 與 MCP 不同，不能冒用 |
| 單一 endpoint 的 per-tool 授權 | 自訂閘門（計畫 §3.5 選項 2），不用 SDK 的 `[Authorize]` | SDK 的 `[Authorize]` 只回 JSON-RPC 錯誤，MCP Client 不會因此啟動 OAuth；MCP-002 證明閘門可在 2025-11-25 與 2026-07-28 兩個協定版本回 HTTP 401（D-04 採單一 `/mcp`） |
| 閘門判斷 | 讀 body（上限 256 KiB，超過 413）；任一 JSON-RPC 訊息是受保護名稱的 `tools/call`（method、key、名稱都不分大小寫，重複 key 全檢查）、或 `Mcp-Name` header 是受保護名稱、或 body 無法解析，就視為受保護 | fail closed：比閘門寬鬆的 parser 也無法匿名抵達受保護 Tool |
| 閘門結果 | 帶 `Authorization` 但驗證失敗 → 401（公開 Tool 也一樣）；受保護且未認證 → 401 `WWW-Authenticate: Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"`；缺 scope → 403 `insufficient_scope`；拒絕時不呼叫 SDK | 未授權時 Tool handler 不會執行，不會建立 Job 或扣額度 |
| Resource metadata | 自行 `MapGet` `/.well-known/oauth-protected-resource/mcp`，內容來自設定 | SDK 只有在 `ResourceMetadataUri` 未設定時才自動服務，且那時 URI 取自 request host |
| 簽章金鑰 | **尚未設定**，所以任何 token 都驗證失敗（fail closed） | M2（MCP-201）由 OpenIddict 提供 |
| Tool 取得使用者 | `RequestContext<CallToolRequestParams>.JsonRpcRequest.Context?.User` | stateless HTTP 下 SDK 帶入閘門設定的 principal |
| Tool | 尚無 Tool；`WithListToolsHandler` 回空陣列 | SDK 沒有任何 Tool 時不提供 `tools/list`（回 -32601）。加入第一支 Tool 時改用 `WithTools` 並移除這個 handler |
| 對外連結 | `PublicBaseUrl` 必須是 https 根網址（開發可用 `http://localhost`、`127.0.0.1`），不得有 path、query、fragment | 連結只從設定產生，不讀 Host header（尚無使用者） |

## 4. 相依方向

```text
Program.cs → Mcp（AddBookFinderMcp / MapBookFinderMcp）→ ModelContextProtocol.AspNetCore
Mcp →（之後）Application ports／services
```

`Mcp` 不被 Application、Infrastructure、Controllers 參照。

## 5. 執行環境

- 設定預設值在 `appsettings.json`：`Mcp:Enabled = false`、`Mcp:PublicBaseUrl = https://khwebsc.com`。
- production 尚未開啟（`deploy/release/compose.prod.yaml` 沒有 `Mcp__Enabled`）。開啟須隨 release，並取得使用者授權。
- `/mcp` POST 不經 MVC，所以不受全域 antiforgery filter 影響，也不設 cookie。
- 2026-07-28 協定的 request 必須帶 `Mcp-Method`、`Mcp-Name` header，且 `params._meta` 含 protocolVersion、clientInfo、clientCapabilities；SDK 檢查 header 與 body 一致。2025-11-25 在 stateless 下不經 initialize 也能直接 `tools/call`。
