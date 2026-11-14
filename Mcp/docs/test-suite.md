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
| `tests/UnitTests/McpRecommendationServiceTests.cs`、`RecommendationToolsTests.cs` | Unit | 開關關閉、文字空白／超過 500 code points（含 emoji）時不呼叫 store；trim 後送出；四種提交結果的對應；handler 沒有已認證使用者時回 `UNAUTHORIZED` 且不呼叫 service |
| `tests/WebIntegration/McpRecommendBooksTests.cs` | HTTP + DB | 真實 token 提交 → DB 有 1 筆 QUEUED Job、`user_id` 正確、不呼叫 AI fake；idempotency 重送與衝突；key 格式錯；文字驗證；每日額度（含網站提交的 Job 一起計數）；開關關閉；匿名 401；2026-07-28；`tools/list` 契約（inputSchema、annotations、`securitySchemes` 頂層與 `_meta`） |
| `tests/UnitTests/McpRecommendationResultServiceTests.cs`、`RecommendationToolsTests.cs` | Unit | 開關、非 GUID 不呼叫 store；各狀態欄位；rank 排序（亂序輸入）；0 本；search 讀不到／SearchId 為 null → `INTERNAL_ERROR`；失敗文案與 `AiJobViewModel.FailureMessageFor` 一致；null 欄位不輸出；handler 無使用者 → `UNAUTHORIZED` |
| `tests/WebIntegration/McpRecommendationResultTests.cs` | HTTP + DB | queued、running、succeeded 1／3／10 本（反向 rank 寫入）、0 本、failed 三種 code；別人的 Job、未知 GUID、非 GUID 的回應完全相同；匿名 401；2026-07-28；`tools/list` 契約；端到端：`recommend_books` → Worker（AI fake）→ 輪詢到 succeeded，書籍與 DB 一致 |
| `tests/UnitTests/McpToolAuthorizationMiddlewareTests.cs` | Unit | 閘門判斷：受保護名稱（含大小寫、JSON escape、重複 key、batch）、無法解析的 body（含註解、尾逗號）都算受保護；`tools/list`、`initialize`、公開 Tool、`arguments` 內的同名欄位不算；`Mcp-Name` header |
| `tests/WebIntegration/McpAuthorizationTests.cs` | HTTP | 以真實 OAuth 流程取得的 token（MCP-202）：匿名列出 Tool；匿名公開 Tool 200；匿名受保護 Tool 401（非 302、無 Location）；resource metadata 內容；有效 token 進入 handler 且 sub 等於使用者 ID（2025-11-25 與 2026-07-28）；竄改、隨機字串、網站 JWT、只有 `bf_auth` cookie、另一個 host 簽發的 token 都 401；過期（FakeTimeProvider 前進 61 分鐘）401；撤銷 authorization 後 401；token 放在 query string 或 form body 401；validation 的 audience 設定為 `{base}/mcp`，且只從 Authorization header 取 token（直接斷言 options，因為閘門本身只在有 header 時才驗證）；公開 Tool 帶有效 token 200、無效 401；body 300 KiB 413；網站頁面 302 與 `/api` 401 不變。每個案例都斷言 DB 的 `recommendation_jobs` 筆數（M3 起改用真正的 `recommend_books`；拒絕 0 筆、成功 1 筆且 `user_id` 為 token 使用者） |

`McpAuthorizationTests` 只在測試 host 註冊測試專用 Tool（`tests/WebIntegration/McpTestTools.cs`：`public_ping`、`recommend_books`），透過 BookFinderFactory 的 `ConfigureMcp` hook；token 由 `tests/WebIntegration/OAuthTestClient.cs` 走完整 OAuth 流程（註冊、登入、authorize、consent、PKCE 交換）取得，`OAuthFlowTests` 也共用它。缺 scope 的 token 無法由本站流程取得，改由 `HasScope` 的 unit test 涵蓋。

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
- Mutation 抽查（MCP-202，2026-11-14）：拿掉 authorization entry validation、允許 query string 取 token、允許 form body 取 token，各讓 `McpAuthorizationTests` 1 個失敗（後兩者在補上 options 斷言後才被抓到）。
- Mutation 抽查（M3，2026-11-14）：忽略 `RecommendationJobs:Enabled`（unit 1、web 1 失敗）、跳過文字驗證（unit 5、web 4）、handler 接受未認證 principal（unit 2；整合測試由閘門先擋，屬預期）。
- Mutation 抽查（M4，2026-11-14）：拿掉 rank 排序（unit 2 失敗；EF 讀出時已依 rank，整合測試不受影響）、search 讀不到時當成功（unit 1；整合測試無法造出此不一致）。
