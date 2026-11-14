# Mcp 待辦

> 建立：2026-11-14。本文件只記錄工作，不代表已實作。順序與驗收條件見 [book-finder-mcp-server.md §4](../../Docs/plans/book-finder-mcp-server.md)。

| ID | 項目 | 狀態 |
|---|---|---|
| MCP-B01 | MCP-002：單一 `/mcp` 的 per-tool HTTP 401 Spike | 已完成（2026-11-14）：可行，採單一 `/mcp` |
| MCP-B02 | MCP-003：OpenIddict 與 Client Registration ADR（預註冊→CIMD） | 已完成（2026-11-14）：見 architecture.md §6 |
| MCP-B03 | M1：`search_books`、`McpUrlBuilder` | 已完成（2026-11-14） |
| MCP-B04 | M2～M4：OAuth、`recommend_books`、`get_recommendation_result` | 待 MCP-003 |
| MCP-B05 | 公開搜尋沒有輸入長度、rate limit、查詢 timeout，比照網站搜尋（D-06）；若之後要加，網站與 MCP 一起加 | 已知缺口 |
| MCP-B06 | SDK 回應固定為 SSE；production 開啟前確認 nginx／Cloudflare 不緩衝、`Authorization` header 原樣轉發 | 上線前確認 |
| MCP-B07 | 是否升級 SDK 到 2.4.0 以上（目前 2.3.1）；升級時重跑契約測試 | 改善提案 |
| MCP-B08 | `McpBearer` 尚無簽章金鑰（任何 token 都失敗）；MCP-201 接上 OpenIddict 的驗證金鑰 | 待 M2 |
| MCP-B09 | 401 的 `WWW-Authenticate` 沒有 `error="invalid_token"`（SDK handler 不加）；目標 Client 若需要再補 | 待 MCP-203 實測 |
| MCP-B10 | RFC 9207：metadata 已宣告 `authorization_response_iss_parameter_supported = true`（201a），回應實際帶 `iss` 待 201b 驗證；RFC 8707：OpenIddict 以 `RegisterResources` 支援，201b 註冊 `https://khwebsc.com/mcp` | 進行中 |
| MCP-B11 | ChatGPT 的預註冊介面位置不明；MCP-203 找不到時實作 allowlist 版 CIMD（architecture.md §6.4） | 待 MCP-203 |
| MCP-B12 | AI Tool 描述加 `securitySchemes`；MCP-203 確認 ChatGPT 對 HTTP 401 的處理，必要時評估 Tool 層錯誤（architecture.md §6.5） | 待 M3／MCP-203 |
| MCP-B13 | production 簽章／加密憑證的存放、輪替與備份程序（L4，需使用者授權） | 待 M2 上線前 |
| MCP-B14 | metadata 的 `scopes_supported` 目前含 `openid`、`offline_access`（OpenIddict 預設）。ChatGPT 預設會要求宣告的 OIDC scope，client 沒有該權限時授權會失敗；201b 決定移除宣告或允許，並確認 refresh token 是否需要 `offline_access` | 待 201b |
