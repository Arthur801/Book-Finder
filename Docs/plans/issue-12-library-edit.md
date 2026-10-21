# #12 修改閱讀狀態、評分、移除：實作計劃

> 規格：`Docs/modules/user-library.md` §3、§5、§6、`Docs/api/api-spec.md` §2、§4、`Docs/ui/ui-flow.md` §1、§3.5。
> 前置：#11 已完成（`LibraryService`、`ILibraryStore`、`library.js`、`LibraryApiController`）。
> 風險：L2～L3（JSON contract 的三態欄位、跨使用者隔離）。

## 1. 要做什麼

- 在 `/library` 與書籍頁就地修改閱讀狀態、給 1～5 星或清除評分、移除書。不重新載入頁面。
- `PATCH /api/library/{bookId}`：`readingStatus` 與 `rating` 都可省略。`rating` **省略 = 不變、`null` = 清除**。
- `DELETE /api/library/{bookId}`：硬刪除，不存在也回 204。

## 2. 模組總覽

```text
 瀏覽器                   Web 層                                   Application              Infrastructure
┌────────────────┐ PATCH ┌─────────────────────────────────┐      ┌──────────────────────┐   ┌──────────────────┐
│ M4 共用控制項   │──────▶│ M3 LibraryApiController          │      │ LibraryChange /       │   │                  │
│ _LibraryControls│DELETE │   (PATCH / DELETE)               │      │ RatingChange（M1 定義）│   │                  │
│ + library.js    │       │      │ 1                         │      │                      │   │                  │
└────────────────┘       │      ▼                           │  2   │ M2 LibraryService     │──▶│ M2 EfLibraryStore │
                         │ M1 LibraryPatchParser            │─────▶│ .UpdateAsync/RemoveAsync│  │ （UPDATE/DELETE） │
                         │ （純函式：JSON → LibraryChange）  │      └──────────────────────┘   └──────────────────┘
                         └─────────────────────────────────┘
```

Controller 先用 M1 把 body 轉成 `LibraryChange`（或欄位錯誤），再把變更交給 M2 的服務。

- JSON 的「省略 / `null` / 型別」語意屬於 HTTP wire format，所以解析器放在 **Web 層**。
- Application 只認識 `LibraryChange` 和 `RatingChange`，不知道 JSON 的存在。

## 3. 各模組

### M1 變更描述（Application）與 PATCH body 解析（Web，純函式）

**職責**：把 JSON body 轉成明確的變更描述，並找出欄位錯誤。這是本票最容易出錯的地方（省略 vs `null`），所以獨立成模組。

**檔案**：

- `Application/Library/LibraryChange.cs`：變更描述，不含任何 JSON 型別。
- `Models/LibraryPatchParser.cs`：JSON → `LibraryChange` 的解析器，屬於 Web 層（與 `Models/` 下其他 request/response 型別放在一起）。

**接口**：

```csharp
// Application：rating 有三種狀態：不變、清除、設成某值
abstract record RatingChange { Unchanged; Clear; Set(short value) }

record LibraryChange(ReadingStatus? NewStatus, RatingChange Rating)

// Web：只有這裡認識 JsonElement
static class LibraryPatchParser
    // body 為 null（空 body 或非 JSON 物件）也會回傳錯誤
    LibraryPatchParseResult Parse(JsonElement? body)   // Valid(LibraryChange) | Invalid(IReadOnlyDictionary<string, string> errors)
```

`readingStatus` 代碼的轉換沿用 #11 的 `ReadingStatusCode.TryParse`。

**規則**（欄位名稱即 `errors` 的 key）：

| 輸入 | 結果 |
|---|---|
| `readingStatus` 省略 | 狀態不變 |
| `readingStatus` 為三個代碼之一 | 設定狀態 |
| `readingStatus` 為其他字串、`null`、非字串 | `errors.readingStatus` |
| `rating` 省略 | 評分不變 |
| `rating: null` | 清除評分 |
| `rating` 為 1～5 的整數 | 設定評分 |
| `rating` 為 0、6、3.5、字串 | `errors.rating`「評分必須介於 1 到 5」 |

用 `JsonElement` 解析而不是一般 model binding，因為 model binding 分不出「省略」與「`null`」。

**測試**：UnitTests 逐列覆蓋上表，加上兩個欄位同時錯、多餘欄位被忽略、空物件 `{}`。

### M2 修改與移除（Application + Infrastructure）

**職責**：把變更寫進資料庫，只作用在目前使用者自己的 Entry。

**檔案**：`Application/Library/LibraryService.cs`（擴充）、`ILibraryStore`（擴充）、`EfLibraryStore`（擴充）

**接口**：

```csharp
LibraryService
    Task<LibraryEntry?> UpdateAsync(Guid userId, Guid bookId, LibraryChange change, ct)  // Entry 不存在回 null
    Task RemoveAsync(Guid userId, Guid bookId, ct)                                       // 不存在也正常結束

ILibraryStore
    Task<LibraryEntry?> UpdateAsync(Guid userId, Guid bookId, LibraryChange change, DateTime now, ct)
    Task RemoveAsync(Guid userId, Guid bookId, ct)
```

**規則**：

- 以 `(user_id, book_id)` 為條件更新；別人的 Entry 對目前使用者來說就是「不存在」→ `null` → 404。
- 有任何欄位變更時才更新 `updated_at`；空變更（`{}`）原樣回傳 Entry、不更新時間。
- 移除為硬刪除，評分跟著消失。

**測試**：UnitTests（服務層，fake store）；DatabaseIntegration（三態評分、空變更不動 `updated_at`、A 改不到 B、重複移除）。

### M3 PATCH / DELETE 端點（Web）

**職責**：HTTP 轉換。

**檔案**：`Controllers/LibraryApiController.cs`（擴充）

- `PATCH /api/library/{bookId}`：讀原始 body → M1 解析 → 錯誤時回 `ValidationProblemDetails`（`/errors/validation`、`errors.<欄位>`）→ M2 → 200 Entry（與 PUT 同格式）或 404。
- `DELETE /api/library/{bookId}`：M2 → 204。`bookId` 不是 GUID 時 PATCH 回 404、DELETE 回 204（沒有東西可刪）。
- 兩者都要登入與 antiforgery。

**測試**：WebIntegration——#12 所有 Acceptance criteria（0/6 → 400 + `errors.rating`、`null` 清除、省略不變、`WANT_TO_READ` 可評分、移除後重複 204、A 改 B 回 404、缺 antiforgery 400、未登入 401）。

### M4 共用可編輯控制項（Web + JS）

**職責**：一份可編輯的書單控制項，同時用在書籍頁與 `/library`。

**檔案**：`Views/Shared/_LibraryControls.cshtml`、`wwwroot/js/library.js`（擴充）、`Views/Books/_LibrarySection.cshtml`、`Views/Library/Index.cshtml`

**畫面**：

- 狀態下拉選單（想讀／閱讀中／已讀）。
- 1～5 星按鈕 ＋「清除評分」。
- 「移除」按鈕。

**`library.js` 行為**（只做送出與換畫面，不判斷規則）：

- 改狀態／評分 → `PATCH`，成功後以回應內容更新控制項。
- 移除 → `DELETE`：
  - 書籍頁：換回「加入書單」按鈕（沿用 #11 的加入流程）。
  - `/library`：移除該列；最後一列被移除時顯示空狀態。
- 400 → 在控制項旁顯示伺服器回傳的訊息。
- 401 → 導向 `/account/login?returnUrl=<目前路徑＋查詢字串>`。
- 其他錯誤 → 顯示「操作失敗，請稍後再試」，畫面回復原值。

**測試**：WebIntegration 檢查兩個頁面都輸出相同的控制項（`data-*` 屬性、antiforgery token、目前值被選取）；JS 用瀏覽器手動驗證。

### M5 文件與報告

- `user-library.md` 補上 §5 預設決定；`api-spec.md` §4 補「`readingStatus: null` → 400」與空物件行為。
- 兩軸 review、`Docs/Implementation-Report/issue-12-library-edit.md`。

## 4. 模組之間的關係

- M1 的解析器在 Web 層，只知道 JSON 與 `ReadingStatus`，不知道資料庫；M2 在 Application / Infrastructure，只知道 `LibraryChange`，不知道 JSON。兩者只透過 `LibraryChange` 這個小 record 連接。依賴方向是 Web → Application，沒有反過來。
- M3 是唯一同時呼叫兩者的地方，但只做串接。
- M4 只依賴 HTTP contract（`api-spec.md` §4），換掉後端實作不影響前端。

## 5. 預設決定（局部、可逆；如不同意請指出）

1. `{}` 空物件 → 200，原樣回傳，不更新 `updated_at`。
2. `readingStatus: null` → 400（狀態不能清除）。
3. 設成與目前相同的值仍視為變更，會更新 `updated_at`（實作簡單、書單排序上影響很小）。
4. 移除前不跳確認對話框（規格沒要求；誤刪可再加入，但評分會消失）。

## 6. 實作步驟

依 [README §3](README.md#3-共通的實作步驟每個模組都一樣)：

1. M1 `issue-12-m1-patch-parsing` — UnitTests。
2. M2 `issue-12-m2-update-remove` — UnitTests + DatabaseIntegration。
3. M3 `issue-12-m3-patch-delete-endpoints` — WebIntegration；mutation 抽查（拿掉 `user_id` 條件，A/B 測試必須失敗）。
4. M4 `issue-12-m4-library-controls` — WebIntegration + 瀏覽器手動驗證。
5. M5 `issue-12-report` — 完整 `dotnet build` + `dotnet test`、瀏覽器手動驗證、review、文件、報告；關閉 #12。
