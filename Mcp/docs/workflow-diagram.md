# Mcp 流程

> 建立：2026-11-14（MCP-001）；MCP-002 加入授權閘門。M1 加入 `search_books`；M3 加入 `recommend_books`；`get_recommendation_result` 在 M4 加入。

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
    Mcp-->>Client: 200 SSE：{"tools": [search_books]}
```

- `Accept` 必須同時包含 `application/json` 與 `text/event-stream`，只給一種會回 406。
- Stateless：不需要 session header；`tools/list` 不帶 `MCP-Protocol-Version` 也可以。
- 不設 cookie、不需要 antiforgery token、不碰資料庫。

## 3. 授權閘門（POST `/mcp`）

```mermaid
flowchart TD
    A[POST /mcp] --> B[清除網站 cookie 身分]
    B --> C{有 Authorization header?}
    C -- 有 --> D{OpenIddict validation 成功?<br/>audience、到期、撤銷}
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

## 4. `search_books`（公開）

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Gate as 授權閘門
    participant Tool as BookSearchTools
    participant Svc as McpBookSearchService
    participant Port as IBookSearch（EfBookSearch）
    Client->>Gate: tools/call search_books {query}
    Gate->>Tool: 公開 Tool，放行（帶無效 Bearer 則 401）
    Tool->>Svc: SearchAsync(query)
    alt SearchQuery.Parse 為 Empty
        Svc-->>Tool: VALIDATION_FAILED（不碰 DB）
        Tool-->>Client: isError true、errorCode VALIDATION_FAILED
    else 關鍵字或 ISBN
        Svc->>Port: SearchAsync(q, page 1, pageSize 50)
        Port-->>Svc: Hits（≤50）、TotalCount
        Svc-->>Tool: totalCount、returnedCount、hasMore、searchUrl、books[bookUrl]
        Tool-->>Client: structuredContent + 文字摘要
    end
```

- 只查本地 DB，沒有外部 fallback；0 本時 `books = []`，仍有 `searchUrl`。

## 5. `recommend_books`（需要 `books:recommend`）

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Gate as 授權閘門
    participant Tool as RecommendationTools
    participant Svc as McpRecommendationService
    participant Job as RecommendationJobService
    Client->>Gate: tools/call recommend_books {requirement_text, idempotency_key?} + Bearer
    alt 無 token／無效／缺 scope
        Gate-->>Client: 401／403（不建立 Job）
    else 驗證通過
        Gate->>Tool: principal（sub = 使用者 ID）
        Tool->>Svc: SubmitAsync(userId, text, key)
        alt RecommendationJobs:Enabled = false
            Svc-->>Client: SERVICE_UNAVAILABLE
        else 文字空白或超過 500 字
            Svc-->>Client: VALIDATION_FAILED（requirement_text）
        else
            Svc->>Job: SubmitAsync（額度與 idempotency 在 store 交易內）
            Job-->>Svc: Accepted／InvalidIdempotencyKey／IdempotencyConflict／DailyLimitReached
            Svc-->>Client: queued + jobId + statusUrl，或對應錯誤碼
        end
    end
```

- 只排入 Job，不同步呼叫 OpenAI；Worker 之後執行（既有 Recommendation Job 流程）。
- 額度與網站共用（D-07）：網站 `/api/recommendations/jobs` 提交的 Job 與 MCP 的 Job 一起計數。
