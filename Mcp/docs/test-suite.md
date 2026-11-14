# Mcp 測試

> 建立：2026-11-14（MCP-001）。計畫的完整矩陣見 [book-finder-mcp-server.md §5](../../Docs/plans/book-finder-mcp-server.md)；這裡只列已存在的測試。

## 1. 已有測試

| 測試 | 層級 | 驗證 |
|---|---|---|
| `tests/UnitTests/McpOptionsTests.cs` | Unit | `HasValidPublicBaseUrl`：關閉時任何值合法；開啟時 null、空白、相對路徑、ftp、非 localhost 的 http、含 query／fragment／path 都不合法；https 根網址與 `http://localhost:port` 合法 |
| `tests/WebIntegration/McpEndpointTests.cs` | HTTP | 關閉時 GET `/mcp` 404、POST 與未 map 的路徑狀態碼相同；開啟時匿名 `initialize` 回 `serverInfo`、`tools/list` 回空陣列；POST 不設 cookie、不需要 antiforgery；開啟時首頁仍 200 |

| `tests/UnitTests/McpUrlBuilderTests.cs` | Unit | 搜尋網址的 trim 與 percent-encoding（中文、空格、`&`、`?`、`#`、`%`、`+`）；base 有無尾 `/`；書籍、Job、紀錄連結格式 |
| `tests/UnitTests/McpBookSearchServiceTests.cs` | Unit | 空白／null 回 `VALIDATION_FAILED` 且不呼叫 `IBookSearch`；關鍵字與 ISBN 分類；固定 page 1、pageSize 50；totalCount 0／1／49／50／51／100 的 `returnedCount`、`hasMore` |
| `tests/WebIntegration/McpSearchBooksTests.cs` | HTTP + DB | 匿名呼叫；0 本仍有 `searchUrl`；51 本只回 50、`hasMore`；排序與網站搜尋一致；空白 query 為 `isError`；無效 Bearer 401；2026-07-28 成功呼叫；`tools/list` 中 `search_books` 的 name、inputSchema（`query` string、required） |
| `tests/UnitTests/McpToolAuthorizationMiddlewareTests.cs` | Unit | 閘門判斷：受保護名稱（含大小寫、JSON escape、重複 key、batch）、無法解析的 body（含註解、尾逗號）都算受保護；`tools/list`、`initialize`、公開 Tool、`arguments` 內的同名欄位不算；`Mcp-Name` header |
| `tests/WebIntegration/McpAuthorizationTests.cs` | HTTP | 17 個：匿名列出兩支 Tool；匿名公開 Tool 200；匿名受保護 Tool 401（非 302、無 Location）；resource metadata 內容；有效 token 進入 handler 且 sub 正確；缺 scope 403；過期／錯 issuer／錯 audience／錯簽章 401；網站 JWT 當 Bearer 401；只有 `bf_auth` cookie 401；公開 Tool 帶無效 token 401；body 300 KiB 413；2025-11-25 與 2026-07-28 各跑 401 與成功案例；網站頁面 302 與 `/api` 401 不變。每個案例都斷言受保護 Tool 的執行次數 |

`McpAuthorizationTests` 只在測試 host 註冊測試專用 Tool（`tests/WebIntegration/McpTestTools.cs`：`public_ping`、`recommend_books`），透過 BookFinderFactory 的 `ConfigureMcp` hook 並移除 app 的空 `tools/list` handler；以測試金鑰簽 JWT，`PostConfigure<JwtBearerOptions>("McpBearer")` 注入驗證金鑰。

`McpEndpointTests` 以 raw HTTP 送 JSON-RPC，並同時能解析 SSE 與 JSON 回應。WebFixture 的 `McpEnabled` 控制 `Mcp:Enabled`（預設 false），`Mcp:PublicBaseUrl` 固定為 `https://khwebsc.com`。

## 2. 執行

```bash
dotnet test tests/UnitTests --filter FullyQualifiedName~McpOptions
dotnet test tests/WebIntegration --filter FullyQualifiedName~McpEndpoint   # 需要 docker
```

## 3. 已知缺口

- `McpEndpointTests` 只驗證 `2025-11-25` 的 `initialize`；`2026-07-28` 只在授權測試中涵蓋 `tools/call`。
- 尚無 SDK client（`HttpClientTransport`）測試；`search_books` 的契約只斷言 name 與 inputSchema，未比對 description 全文。
- Mutation 抽查（MCP-002，2026-11-14）：拿掉匿名 challenge、scope 一律通過、無效 token 當匿名、拿掉 body 上限，各自讓 `McpAuthorizationTests` 失敗（4／1／6／1 個）。
- 尚無真實 OAuth token（M2）與真實 Client 測試（MCP-203）。
- Mutation 抽查（M1，2026-11-14）：`IBookSearch` 的 pageSize 改成 20，讓 `McpBookSearchServiceTests` 5 個、`McpSearchBooksTests` 2 個失敗。
