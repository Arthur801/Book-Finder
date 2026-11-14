# Mcp 測試

> 建立：2026-11-14（MCP-001）。計畫的完整矩陣見 [book-finder-mcp-server.md §5](../../Docs/plans/book-finder-mcp-server.md)；這裡只列已存在的測試。

## 1. 已有測試

| 測試 | 層級 | 驗證 |
|---|---|---|
| `tests/UnitTests/McpOptionsTests.cs` | Unit | `HasValidPublicBaseUrl`：關閉時任何值合法；開啟時 null、空白、相對路徑、ftp、非 localhost 的 http、含 query／fragment／path 都不合法；https 根網址與 `http://localhost:port` 合法 |
| `tests/WebIntegration/McpEndpointTests.cs` | HTTP | 關閉時 GET `/mcp` 404、POST 與未 map 的路徑狀態碼相同；開啟時匿名 `initialize` 回 `serverInfo`、`tools/list` 回空陣列；POST 不設 cookie、不需要 antiforgery；開啟時首頁仍 200 |

`McpEndpointTests` 以 raw HTTP 送 JSON-RPC，並同時能解析 SSE 與 JSON 回應。WebFixture 的 `McpEnabled` 控制 `Mcp:Enabled`（預設 false），`Mcp:PublicBaseUrl` 固定為 `https://khwebsc.com`。

## 2. 執行

```bash
dotnet test tests/UnitTests --filter FullyQualifiedName~McpOptions
dotnet test tests/WebIntegration --filter FullyQualifiedName~McpEndpoint   # 需要 docker
```

## 3. 已知缺口

- 只驗證協定版本 `2025-11-25` 的 `initialize`；其他版本（含 2026-07-28）由 MCP-002 補。
- 尚無 SDK client（`HttpClientTransport`）測試與 Tool 契約 snapshot；第一支 Tool 加入時補。
- 尚無任何授權測試（MCP-002）。
