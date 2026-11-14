# Mcp 流程

> 建立：2026-11-14（MCP-001）；MCP-002 加入授權閘門。app 目前仍沒有 Tool（`tools/list` 回空陣列）；三支 Tool 的流程在之後的票加入。

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

## 3. 授權閘門（POST `/mcp`）

```mermaid
flowchart TD
    A[POST /mcp] --> B[清除網站 cookie 身分]
    B --> C{有 Authorization header?}
    C -- 有 --> D{McpBearer 驗證成功?}
    D -- 否 --> X1[401 + WWW-Authenticate resource_metadata]
    D -- 是 --> E[context.User = token principal]
    C -- 無 --> F
    E --> F{body ≤ 256 KiB?}
    F -- 否 --> X2[413]
    F -- 是 --> G{受保護 Tool 呼叫？<br/>body、Mcp-Name header、或無法解析}
    G -- 否 --> SDK[SDK 處理]
    G -- 是 --> H{已認證?}
    H -- 否 --> X1
    H -- 是 --> I{scope 含 books:recommend?}
    I -- 否 --> X3[403 insufficient_scope]
    I -- 是 --> SDK
```

拒絕路徑（X1～X3）都不呼叫 SDK，所以 Tool handler 不會執行。

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Gate as 授權閘門
    participant Meta as /.well-known/oauth-protected-resource/mcp
    Client->>Gate: tools/call recommend_books（無 token）
    Gate-->>Client: 401 WWW-Authenticate: Bearer resource_metadata="https://khwebsc.com/.well-known/oauth-protected-resource/mcp"
    Client->>Meta: GET
    Meta-->>Client: resource https://khwebsc.com/mcp、authorization_servers [https://khwebsc.com/]、scopes_supported [books:recommend]
    Note over Client: 之後的 OAuth 流程由 M2（OpenIddict）提供
```

