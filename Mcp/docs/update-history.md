# Mcp 修改歷史

| 日期 | Commit | 內容 | 檔案 |
|---|---|---|---|
| 2026-11-14 | `e618edb`、`4c1b047` | MCP-001：引入 `ModelContextProtocol.AspNetCore` 2.3.1；`McpOptions`、`AddBookFinderMcp`、`MapBookFinderMcp`；`/mcp` 受 `Mcp:Enabled` 控制，Stateless、匿名、無 Tool | `Mcp/McpOptions.cs`、`Mcp/McpServiceCollectionExtensions.cs`、`Program.cs`、`appsettings.json`、`Book-Finder.csproj` |
| 2026-11-14 | `df9e333`、`7b59f46`、`f2d8a17`、`7485e53` | MCP-002：`McpBearer` scheme、SDK challenge scheme、resource metadata、POST `/mcp` 授權閘門（fail closed） | `Mcp/Security/McpAuthSetup.cs`、`Mcp/Security/McpToolAuthorizationMiddleware.cs`、`Mcp/McpServiceCollectionExtensions.cs` |
