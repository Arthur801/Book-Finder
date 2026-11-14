# Mcp 待辦

> 建立：2026-11-14。本文件只記錄工作，不代表已實作。順序與驗收條件見 [book-finder-mcp-server.md §4](../../Docs/plans/book-finder-mcp-server.md)。

| ID | 項目 | 狀態 |
|---|---|---|
| MCP-B01 | MCP-002：單一 `/mcp` 的 per-tool HTTP 401 Spike；不可行時改雙 endpoint（D-04） | 下一步 |
| MCP-B02 | MCP-003：OpenIddict 與 Client Registration ADR（預註冊→CIMD） | 待 MCP-002 |
| MCP-B03 | M1：`search_books`、`McpUrlBuilder`；加入第一支 Tool 時移除空的 `WithListToolsHandler`，改用 `WithTools` | 可開始 |
| MCP-B04 | M2～M4：OAuth、`recommend_books`、`get_recommendation_result` | 待 MCP-003 |
| MCP-B05 | 公開搜尋沒有輸入長度、rate limit、查詢 timeout，比照網站搜尋（D-06）；若之後要加，網站與 MCP 一起加 | 已知缺口 |
| MCP-B06 | SDK 回應固定為 SSE；production 開啟前確認 nginx／Cloudflare 不緩衝、`Authorization` header 原樣轉發 | 上線前確認 |
| MCP-B07 | 是否升級 SDK 到 2.4.0 以上（目前 2.3.1）；升級時重跑契約測試 | 改善提案 |
