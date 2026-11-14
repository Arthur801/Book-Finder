# Mcp 架構

> 建立：2026-11-14（MCP-001，`e618edb`、`4c1b047`）。實作計畫：[book-finder-mcp-server.md](../../Docs/plans/book-finder-mcp-server.md)（計畫不是 contract；本文件描述目前已實作的狀態）。

## 1. 模組責任

`Mcp/` 是遠端 MCP（Model Context Protocol）Server 的協定層，與網站在同一個 ASP.NET Core process。

- 負責：MCP transport 註冊、`/mcp` 路由、設定（`McpOptions`）；之後的票加入 Tool 參數驗證、DTO、錯誤對應與對外連結。
- 不負責：商業規則、資料存取、AI 呼叫。Tool 只能呼叫 Application 層的 service／port，不得使用 `AppDbContext`、自行下 SQL 或呼叫 OpenAI。

## 2. 目前組成

| 檔案 | 責任 |
|---|---|
| `McpOptions.cs` | `Mcp` 設定：`Enabled`（預設 false）、`PublicBaseUrl`；`HasValidPublicBaseUrl` 在啟動時驗證 |
| `McpServiceCollectionExtensions.cs` | `AddBookFinderMcp`：綁定並驗證設定、註冊官方 SDK（Streamable HTTP、Stateless）；`MapBookFinderMcp`：`Enabled` 為 true 才 `MapMcp("/mcp")` |

`Program.cs` 只有兩個接點：`AddBookFinderMcp`（在 `AddRecommendationJobs` 之後）與 `MapBookFinderMcp`（在 `UseAuthorization` 之後、MVC route 之前）。

## 3. 架構決策

| 項目 | 目前狀態 | 理由 |
|---|---|---|
| SDK | `ModelContextProtocol.AspNetCore` **2.3.1**（精確釘版） | 協定由官方 SDK 實作；2.4.0 發布未滿兩週，先用較穩的 patch 版 |
| Transport | Streamable HTTP、`Stateless = true` | 不保存 MCP session；之後以 Job ID 跨呼叫追蹤 |
| 回應格式 | 一律 SSE（`text/event-stream`，一個 `event: message`） | SDK 2.3.1 的 `HttpServerTransportOptions` 沒有 JSON response 選項；回應帶 `Cache-Control: no-store, no-cache` 與 `X-Accel-Buffering: no`，nginx 不會緩衝 |
| 開關 | `Mcp:Enabled` 在啟動時讀取；false 時 `/mcp` 完全不 map | 與網站其他未 map 的路徑行為相同（GET 404、POST 405） |
| 認證 | 目前全部匿名 | 授權在 MCP-002／M2 加入，必須使用獨立的 `McpBearer` scheme（預設 cookie scheme 對非 `/api` 路徑回 302，不能用於 OAuth challenge） |
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
