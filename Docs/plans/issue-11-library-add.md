# #11 加入書單與書單頁：實作計劃

> 規格：`Docs/modules/user-library.md`、`Docs/modules/identity-auth.md` §6、`Docs/api/api-spec.md` §4、`Docs/ui/ui-flow.md` §2/§3.3/§3.5、`Docs/data/data-model.md` §5.10。
> 風險：L3（碰到 auth 後的待辦動作流程與跨使用者資料隔離）。

## 1. 要做什麼

- 已登入的人可以在書籍頁按「加入書單」，書會以「想讀」加入個人書單（Library）。
- 沒登入的人按「加入書單」會先去登入；登入或註冊完成後，系統自動把書加進去，再回到原本的書籍頁。
- `/library` 列出自己的書，可以依閱讀狀態篩選；沒有書時顯示空狀態。

不在這張票：修改狀態、評分、移除（#12）。本票的書單頁與書籍頁只**顯示**狀態與評分，不能修改。

## 2. 模組總覽

```text
            ┌──────────── Web 層 ────────────────────────────────────────┐
            │ M3 LibraryApiController   M4 書籍頁書單區塊   M6 /library 頁 │
            │        (PUT JSON)            (+ library.js)      (Razor)    │
            │                     M5 登入後待辦動作                       │
            └──────────┬───────────────┬───────────────┬────────────────┘
                       │ 只呼叫         │               │
                       ▼               ▼               ▼
            ┌─────────── Application ────────────────────────────────────┐
            │ M1 LibraryService  ──用──▶  ReadingStatusCode（純函式）     │
            │        │                                                    │
            │        ▼ 介面 ILibraryStore                                 │
            └────────┼───────────────────────────────────────────────────┘
                     ▼
            ┌─────────── Infrastructure ─────────────────────────────────┐
            │ M2 EfLibraryStore（PostgreSQL）                             │
            └────────────────────────────────────────────────────────────┘
```

規則只有一份，放在 M1；Web 層的三個入口（JSON、書籍頁、書單頁）和登入後待辦動作都呼叫同一個 `LibraryService`，不各自寫 SQL。

## 3. 各模組

### M1 Library 核心（Application）

**職責**：定義書單的操作與規則，不知道資料庫或 HTTP 的存在。

**檔案**：`Application/Library/`

**接口**：

```csharp
// 閱讀狀態代碼與中文名稱的轉換（純函式）
static class ReadingStatusCode
    string ToCode(ReadingStatus)            // WANT_TO_READ / READING / FINISHED
    bool TryParse(string? code, out ReadingStatus)
    string Label(ReadingStatus)             // 想讀 / 閱讀中 / 已讀

// 書單的一筆資料（給頁面與 API 用的唯讀資料）
record LibraryItem(Guid BookId, string Title, IReadOnlyList<string> Authors,
                   string? ThumbnailUrl, ReadingStatus Status, short? Rating,
                   DateTime AddedAt, DateTime UpdatedAt)

// 資料存取介面（由 M2 實作）
interface ILibraryStore
    Task<LibraryEntry?> AddIfMissingAsync(LibraryEntry entry, ct)  // 由服務組好新 Entry；已存在回傳既有的、不覆寫；書不存在回 null
    Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, ct)
    Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, ct)

// 對外服務
class LibraryService(ILibraryStore, TimeProvider)
    Task<AddToLibraryResult> AddAsync(Guid userId, Guid bookId, ct)  // Added(entry) | BookNotFound
    Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, ct)
    Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, ct)
```

**規則**：

- 加入時狀態固定 `WANT_TO_READ`、評分 `null`；已存在就原樣回傳，不改任何欄位（idempotent）。
- `userId` 只來自呼叫端傳入的目前使用者；介面上沒有任何「指定別人」的參數。

**測試**：UnitTests，用 in-memory fake store 驗證服務規則；`ReadingStatusCode` 的往返轉換與不合法代碼。

### M2 EF 書單存取（Infrastructure）

**職責**：把 `ILibraryStore` 對應到 `user_books` 表。

**檔案**：`Infrastructure/Persistence/EfLibraryStore.cs`

**重點**：

- `AddIfMissingAsync` 用 `INSERT … ON CONFLICT (user_id, book_id) DO NOTHING`，同時兩個請求加入同一本書也不會報錯。書不存在（FK 違反或事先查無）回 `null`。
- `ListAsync` 依 `updated_at` 新到舊；只查 `user_id = 目前使用者`；作者沿用既有 `BookAuthors` 的取法。

**測試**：DatabaseIntegration——重複加入不改狀態、書不存在、篩選、排序、A 看不到 B 的書。

### M3 加入書單 JSON 端點（Web）

**職責**：`PUT /api/library/{bookId}` 的 HTTP 轉換。

**檔案**：`Controllers/LibraryApiController.cs`、`Models/LibraryEntryResponse.cs`

**接口**：

- Request：無 body；需要登入與 antiforgery header。
- Response 200：`{ bookId, readingStatus, rating, addedAt, updatedAt }`（時間以 +08:00 表示，與 `RecommendationResponse` 一致）。
- 錯誤：401、404（`/errors/not-found`，`bookId` 不是 GUID 也算 404）、400 antiforgery。

**測試**：WebIntegration——200 格式、第二次 PUT 狀態不變、401、404、缺 antiforgery 400。

### M4 書籍頁的書單區塊（Web + JS）

**職責**：在 `/books/{id}` 的 `<section id="library">` 顯示書單狀態或「加入書單」按鈕。

**檔案**：`Views/Books/_LibrarySection.cshtml`、`BooksController`、`wwwroot/js/library.js`

**規則**：

- 書籍資料本身有快取（`CachedBookDetailReader`）；書單狀態因人而異，**另外**用 `LibraryService.FindAsync` 讀，不放進快取。
- 已登入且在書單中：顯示目前狀態（中文）與評分。
- 已登入但不在書單中：按鈕 → `library.js` 送 `PUT`，成功後就地換成狀態顯示。
- 未登入：按鈕是一般連結，指向 `/account/login?returnUrl=/books/{id}&pendingAction=add-to-library`。
- JSON 收到 401（例如 token 過期）：導向 `/account/login?returnUrl=<目前路徑>`。
- `library.js` 只負責「送請求、換畫面」，不判斷任何規則。#12 會在同一個檔案加上修改功能。

**測試**：WebIntegration 檢查三種情況的 HTML（按鈕、連結 URL、antiforgery token、狀態文字）；JS 用瀏覽器手動驗證（`run` skill）。

### M5 登入／註冊後的待辦動作（Web）

**職責**：登入或註冊成功時，若帶著 `pendingAction=add-to-library` 且 `returnUrl` 是 `/books/{id}`，先加入書單再導回書籍頁。

**檔案**：`Application/Library/PendingLibraryAction.cs`（純函式）、`AccountController` 小改

**接口**：

```csharp
static class PendingLibraryAction
    // 只有 action 完全等於 "add-to-library" 且 returnUrl 完全符合 /books/{GUID} 時回傳 bookId，其餘回 null
    Guid? TryGetBookToAdd(string? pendingAction, string? returnUrl)
```

**失敗語意（重要）**：登入／註冊成功是主要操作；待辦動作只是 best-effort 的後續步驟，**不得把已成功的登入／註冊變成失敗**。

- 否則會出現「部分成功」：例如註冊時帳號已建立，但加入書單時 DB 逾時 → 500 → 使用者以為註冊失敗，再註冊一次又得到「此 email 已被註冊」。
- 所以 `AccountController.SignInAndRedirect` 的順序是：
  1. 先發 cookie。
  2. 有 bookId 時呼叫 `LibraryService.AddAsync`，用 try/catch 包住。書不存在（`BookNotFound`）或任何例外都只記 Warning log（含 userId、bookId，不含密碼或 email），不改變後續流程。只有 request 被取消時才往外傳。
  3. 照常導向 `returnUrl`。書沒加進去時，書籍頁會顯示「加入書單」，使用者可以自己再按一次（最小實作，不另外顯示錯誤訊息）。

**測試**：

- UnitTests：各種 action / returnUrl 組合（大小寫、外站 URL、多餘路徑、查詢字串）。
- WebIntegration：
  - 「未登入 → 登入 → 書已在書單、導回原書籍頁」，註冊路徑同樣一條。
  - 不認得的 action 被忽略。
  - **加入書單拋例外時**（WebFixture 換成會拋例外的 `ILibraryStore` fake）：登入與註冊仍然 302 導回 `returnUrl`、有 auth cookie、不是 500；註冊的帳號確實存在。

### M6 `/library` 頁面（Web）

**職責**：顯示自己的書單。

**檔案**：`Controllers/LibraryController.cs`、`Models/LibraryPageViewModel.cs`、`Views/Library/Index.cshtml`

**規則**：

- `[Authorize]`，未登入導向登入頁（既有 pipeline）。
- `?status=WANT_TO_READ|READING|FINISHED` 篩選；篩選列：全部／想讀／閱讀中／已讀。
- 每筆：封面、書名（連到 `/books/{id}`）、作者、狀態、評分。本票只顯示，#12 再換成可修改的控制項。
- 空書單（含篩選後為空）：「還沒有加入任何書」＋前往 `/bestsellers` 的連結。

**測試**：WebIntegration——排序、篩選、A/B 隔離、空狀態、未登入導向。

### M7 文件與報告

- 規格同步：`user-library.md`、`ui-flow.md`、`identity-auth.md` 補上本票的預設決定（見 §5）；`identity-auth.md` §6 補上「待辦動作失敗不影響登入／註冊結果」。
- `LoginForm.cs` 註解中「login flow does not act on PendingAction yet」改掉。
- 兩軸 review、`Docs/Implementation-Report/issue-11-library-add.md`、更新 memory `issue-10-auth-decisions`（pendingAction 已完成）。

## 4. 模組之間的關係

- M1 是唯一的規則來源；M2 只實作 M1 定義的介面；M3～M6 只呼叫 `LibraryService`，彼此不互相呼叫。
- M4、M6 共用同一份狀態顯示邏輯（`ReadingStatusCode.Label`），#12 會把它換成共用的可編輯 partial。
- 換掉資料庫實作只影響 M2；換掉頁面只影響 M4/M6。

## 5. 預設決定（局部、可逆；如不同意請指出）

1. `/library?status=` 的值不合法（例如 `foo`）時視為「全部」，不回錯誤。
2. 狀態中文名稱：想讀／閱讀中／已讀（取自 `user-library.md` §4 的篩選標籤）。
3. 評分在本票顯示為「★★★☆☆」或「未評分」。
4. PUT 回應的時間欄位用 Asia/Taipei（+08:00），與 `POST /api/recommendations` 一致。

## 6. 實作步驟

依 [README §3](README.md#3-共通的實作步驟每個模組都一樣) 的流程，每個模組一個分支、一個 PR（base 為 `main`，由使用者合併；分支一層疊一層，不等合併）：

1. M1 `issue-11-m1-library-core` — UnitTests。
2. M2 `issue-11-m2-ef-library-store` — DatabaseIntegration。
3. M3 `issue-11-m3-put-endpoint` — WebIntegration。
4. M4 `issue-11-m4-book-library-section` — WebIntegration + 瀏覽器手動驗證。
5. M5 `issue-11-m5-pending-action` — UnitTests + WebIntegration；L3，做 mutation 抽查（例如拿掉 returnUrl 檢查、拿掉 try/catch，對應測試必須失敗）。
6. M6 `issue-11-m6-library-page` — WebIntegration。
7. M7 `issue-11-report` — 完整 `dotnet build` + `dotnet test`、瀏覽器手動驗證、review、文件、報告；關閉 #11。
