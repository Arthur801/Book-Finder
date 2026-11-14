# Mcp 流程

> 建立：2026-11-14（MCP-001）。目前只有協定握手與空的 Tool 列表；三支 Tool 的流程在之後的票加入。

## 1. 啟動

```mermaid
flowchart TD
    A[Program.cs: AddBookFinderMcp] --> B[綁定 Mcp 設定 + ValidateOnStart]
    B --> C[AddMcpServer + WithHttpTransport Stateless]
    D[Program.cs: MapBookFinderMcp] --> E{Mcp:Enabled?}
    E -- false --> F[不 map；/mcp 同一般未知路徑]
    E -- true --> G[MapMcp /mcp]
```

`Mcp:Enabled = true` 但 `PublicBaseUrl` 不合法時，host 啟動失敗（`OptionsValidationException`）。

## 2. 匿名請求（目前唯一的流程）

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Mcp as /mcp（SDK）
    Client->>Mcp: POST initialize（Accept: application/json, text/event-stream）
    Mcp-->>Client: 200 SSE：serverInfo、capabilities.tools
    Client->>Mcp: POST tools/list
    Mcp-->>Client: 200 SSE：{"tools": []}
```

- `Accept` 必須同時包含 `application/json` 與 `text/event-stream`，只給一種會回 406。
- Stateless：不需要 session header；`tools/list` 不帶 `MCP-Protocol-Version` 也可以。
- 不設 cookie、不需要 antiforgery token、不碰資料庫。
