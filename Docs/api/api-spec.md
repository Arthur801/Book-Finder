# API Spec

> Path: `Docs/api/api-spec.md`
> Authority: JavaScript 呼叫的 JSON 端點、request / response、錯誤格式、驗證規則
> 頁面路由見 `Docs/ui/ui-flow.md`；行為規則見各 module 文件。

## 1. 通則

- 只有 `ui-flow.md` §1 列出的互動使用 JSON 端點；其他功能為 Razor 頁面。
- 路徑前綴 `/api`。JSON 欄位使用 camelCase。
- 認證：HttpOnly cookie 中的 JWT（ADR-004）。未登入 → 401（不重導）。
- CSRF：所有非 GET 請求必須帶 `RequestVerificationToken` header（值由 Razor 頁面輸出），缺少或錯誤 → 400。
- 成功回應 `application/json`；錯誤回應 `application/problem+json`。

## 2. 錯誤格式

使用 ASP.NET Core ProblemDetails（RFC 9457）：

```json
{
  "type": "/errors/daily-limit-exceeded",
  "title": "今天的 AI 推薦次數已用完",
  "status": 429,
  "traceId": "..."
}
```

驗證錯誤使用 `ValidationProblemDetails`：

```json
{
  "type": "/errors/validation",
  "title": "輸入資料有誤",
  "status": 400,
  "errors": { "rating": ["評分必須介於 1 到 5"] },
  "traceId": "..."
}
```

| Status | `type` | 情境 |
|---:|---|---|
| 400 | `/errors/validation` | 欄位驗證失敗 |
| 400 | `/errors/antiforgery` | CSRF token 缺少或錯誤 |
| 401 | `/errors/unauthenticated` | 未登入或 token 過期 |
| 404 | `/errors/not-found` | 資源不存在或不屬於目前使用者 |
| 429 | `/errors/daily-limit-exceeded` | AI 推薦每日上限 |
| 429 | `/errors/rate-limited` | 登入 / 註冊頻率限制 |
| 502 | `/errors/ai-unavailable` | OpenAI 呼叫失敗 |
| 504 | `/errors/ai-timeout` | 推薦超過 60 秒 |
| 500 | `/errors/internal` | 其他伺服器錯誤（不含 stack trace） |

## 3. AI 推薦

### `POST /api/recommendations`

Request：

```json
{ "requirementText": "想看輕鬆的推理小說" }
```

| 欄位 | 規則 |
|---|---|
| `requirementText` | 必填；去除前後空白後 1～500 字 |

Response `200`：

```json
{
  "searchId": "uuid",
  "createdAt": "2026-10-11T12:00:00+08:00",
  "fallbackUsed": false,
  "results": [
    {
      "rank": 1,
      "book": {
        "id": "uuid",
        "title": "書名",
        "authors": ["作者"],
        "thumbnailUrl": "https://... | null"
      },
      "reason": "推薦理由",
      "relevance": 0.82,
      "difficulty": 3
    }
  ]
}
```

- `results` 0～10 筆；`difficulty` 可為 `null`。
- 錯誤：400、401、429（daily-limit-exceeded）、502、504。
- 失敗時不建立 Recommendation Search（`recommendation.md` §8）。

AI 搜尋紀錄列表與詳情為 Razor 頁面，不提供 JSON 端點。

## 4. Library

`{bookId}` 為 `books.id`。`user_id` 一律取自目前使用者。

### `PUT /api/library/{bookId}` — 加入

無 body。Idempotent：已存在則不變。

Response `200`：

```json
{ "bookId": "uuid", "readingStatus": "WANT_TO_READ", "rating": null, "addedAt": "...", "updatedAt": "..." }
```

錯誤：401、404（Book 不存在）。

### `PATCH /api/library/{bookId}` — 修改狀態 / 評分

Request（欄位皆可省略；省略表示不變）：

```json
{ "readingStatus": "READING", "rating": 4 }
```

| 欄位 | 規則 |
|---|---|
| `readingStatus` | `WANT_TO_READ` / `READING` / `FINISHED` |
| `rating` | 1～5 的整數，或 `null`（清除評分） |

`rating` 欄位「省略」與「明確為 `null`」意義不同：前者不變，後者清除。

- `readingStatus: null`、不是三個代碼之一（大小寫須相符）、或不是字串 → 400，`errors.readingStatus`。
- `rating` 為 0、6、小數（含 `3.0`）、字串或其他型別 → 400，`errors.rating`。
- body 不是 JSON 物件（空 body、格式錯誤、陣列、字串等）→ 400，錯誤放在 `errors[""]`（整個 body）。不論 `Content-Type`，body 一律以 JSON 解析。
- 未知欄位忽略。`{}` → 200，原樣回傳，不更新 `updatedAt`。
- `{bookId}` 不是 GUID → 404。

Response `200`：同加入的 Entry 格式。錯誤：400、401、404（Entry 不存在或不屬於目前使用者）。

### `DELETE /api/library/{bookId}` — 移除

Idempotent。Entry 不存在、不屬於目前使用者，或 `{bookId}` 不是 GUID 時也回 `204`（不影響任何資料）。Response `204`。錯誤：401。

## 5. 變更規則

- 新增、修改、刪除端點或欄位，必須同步更新本文件與呼叫端 JavaScript（`AGENTS.md` §2.3）。
- 欄位改名或移除視為 breaking change，需在 PR 中說明。
