# Issue #11 加入書單與書單頁：實作報告

- Issue：#11 加入書單與書單頁（LIB-01～03）
- 計劃：`Docs/plans/issue-11-library-add.md`（模組拆分、預設決定 §5、待辦動作的失敗語意）
- 規格：`Docs/modules/user-library.md`、`Docs/modules/identity-auth.md` §6、`Docs/api/api-spec.md` §4、`Docs/ui/ui-flow.md`、`Docs/data/data-model.md` §5.10
- 日期：2026-10-22
- 分工：主 agent 規劃、派工、驗收、撰寫文件；M1～M6 與 review 修正由 Haiku subagent 以 TDD 實作。每個模組完成後，主 agent 親自執行 build 與測試、閱讀程式碼，L3 模組另做 mutation 抽查。
- PR：每個模組一個 PR，base 都是 `main`，分支依序疊上去：#47 M1 → #48 M2 → #49 M3 → #50 M4 → #51 M5 → #52 M6 → 本報告 PR（M7）。

模組依賴：M1 Library 核心 ← M2 EF 實作；M3 PUT 端點、M4 書籍頁書單區塊、M5 登入後待辦動作、M6 `/library` 頁都只呼叫 M1 的 `LibraryService`，彼此不互相呼叫。

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/modules/identity-auth.md` §6 | 新增三條：<br>• `returnUrl` 必須正好是 `/books/{標準格式 GUID}`。<br>• 待辦動作是 best-effort，失敗只記 Warning log，不影響登入／註冊。<br>• token 過期時按「加入書單」收到 401，也帶 `pendingAction`。 |
| `Docs/modules/user-library.md` §4、§5 | `?status=` 的值、不合法時顯示全部、狀態的中文名稱、評分的星星格式、401 走待辦動作流程 |
| `Docs/ui/ui-flow.md` §3.5 | JSON 401 那一列補上「加入書單」的例外 |
| `Docs/plans/issue-11-library-add.md` | `AddIfMissingAsync` 的簽名同步成實作（`0756d5d`） |
| `Docs/plans/issue-12-library-edit.md` | 加入兩個延後的 review 項目（M3、M4） |

## M1 Library 核心（#47）

### 變更檔案

- `Application/Library/ReadingStatusCode.cs`、`LibraryItem.cs`、`ILibraryStore.cs`、`LibraryService.cs`（新增）
- `tests/UnitTests/ReadingStatusCodeTests.cs`、`LibraryServiceTests.cs`（新增）

### 實作思路

- 書單的規則只放在這裡：加入時固定為 `WANT_TO_READ`、評分為 null；已存在就原樣回傳。
- 資料存取透過 `ILibraryStore` port。`AddIfMissingAsync` 改成傳入整個 `LibraryEntry`：由服務組好 Entry，store 只負責「沒有才寫入」。
- 狀態代碼是 API 與 query string 的契約，所以在 `ReadingStatusCode` 明確列出，不從 enum 名稱或 Infrastructure 的 `StoredEnum` 推導。

### 執行紀錄（Log）

- 紅燈：實作前，測試因缺少型別而編譯失敗。
- 主 agent 驗收：讀過四個檔案，UnitTests 437 個全部通過。

### 驗證結果

- 新增 27 個 UnitTests：
  - 三個代碼可以來回轉換；`TryParse` 拒絕 `WantToRead`、`0`、帶空白的值等。
  - 新加入時的預設值正確；已存在的 READING／4 星不會被覆寫。
  - 書不存在時回 `BookNotFound`。

### 未解決事項

無。

### Code Review 與修正

見文末〈兩軸 Review〉的修正 1。

## M2 EF 書單存取（#48）

### 變更檔案

- `Infrastructure/Persistence/EfLibraryStore.cs`（新增）
- `Program.cs`（註冊 `ILibraryStore`、`LibraryService`）
- `tests/DatabaseIntegration/EfLibraryStoreTests.cs`（新增）

### 實作思路

- 加入用一個 `INSERT … ON CONFLICT (user_id, book_id) DO NOTHING` 語句，兩個請求同時加入同一本書也不會出錯。寫入後再讀回實際存的那一列。
- 「書不存在」的判斷是捕捉 FK 違反（`23503`），不先查再寫。先查再寫的話，兩個步驟之間書可能被刪除。已存在的列會先被 `ON CONFLICT` 跳過，不會走到 FK 這條路。
- 列表只投影頁面要顯示的欄位，所以簡介和目錄不會離開資料庫（BOOK-05）。作者沿用 `BookAuthors.ByBookAsync`。

### 執行紀錄（Log）

- Haiku 把測試與實作一起寫，沒有留下紅燈紀錄。因此主 agent 補做 5 個 mutation，每個都至少讓 1 個測試失敗：
  - 拿掉 `ON CONFLICT`：2 個失敗
  - 拿掉 `user_id` 條件：4 個失敗
  - 拿掉狀態篩選：1 個失敗
  - 排序改成由舊到新：1 個失敗
  - `FindAsync` 不檢查使用者：1 個失敗

### 驗證結果

- DatabaseIntegration 新增 11 個（合計 70），包括從兩個 DbContext 同時加入、A 看不到 B 的資料、排序、篩選、作者欄位。
- WebIntegration 154 個全部通過，確認 DI 註冊不影響網站啟動。

### 未解決事項

無。

### Code Review 與修正

無。

## M3 `PUT /api/library/{bookId}`（#49）

### 變更檔案

- `Controllers/LibraryApiController.cs`、`Models/LibraryEntryResponse.cs`、`Infrastructure/Identity/CurrentUser.cs`（新增）
- `Controllers/RecommendationsController.cs`：改用共用的 `User.CurrentUserId()`
- `tests/WebIntegration/LibraryApiTests.cs`（新增）

### 實作思路

- Controller 只做 HTTP 轉換：
  - `bookId` 不是 GUID，或書不存在 → 404 `/errors/not-found`
  - 加入成功 → 200，回傳 Entry，時間為 +08:00
- 401 與 antiforgery 400 沿用既有的 pipeline。
- 從 `sub` claim 取使用者 id 的邏輯，原本是 `RecommendationsController` 的 private 方法，現在抽成共用 helper。

### 執行紀錄（Log）

- 紅燈：9 個測試全部回 `MethodNotAllowed`（路由還不存在）。

### 驗證結果

- WebIntegration 新增 9 個（合計 163），涵蓋：
  - 回應只有 5 個欄位、重複 PUT 結果相同、已是 READING／4 星的 Entry 不變
  - 書不存在、bookId 不是 GUID → 404
  - 未登入 → 401；缺少 antiforgery → 400
  - B 加入同一本書不影響 A
- 既有的 `RecommendationApiTests` 全部通過，作為重構的保護。

### 未解決事項

無。

### Code Review 與修正

見修正 4（台北時間轉換改為共用）。

## M4 書籍頁的書單區塊（#50）

### 變更檔案

- `Controllers/BooksController.cs`、`Views/Books/Detail.cshtml`
- `Models/LibrarySectionViewModel.cs`、`Views/Books/_LibrarySection.cshtml`、`wwwroot/js/library.js`（新增）
- `tests/WebIntegration/BookLibrarySectionTests.cs`（新增）、`BookDetailPageTests.cs`、`HtmlPage.cs`

### 實作思路

- 書目資料照舊走快取。書單狀態每個人不同，所以另外查詢，透過 `ViewData` 傳給 partial。這樣 `BookDetailViewModel` 只放書目資料。
- 區塊有三種狀態：
  - 未登入：顯示連結，指向帶 `pendingAction` 的登入頁。
  - 已登入、還沒加入：顯示按鈕。
  - 已登入、已加入：顯示狀態與評分（唯讀）。
- `library.js` 只負責送出請求與替換畫面：
  - 200 → 就地替換成狀態顯示
  - 401 → 導向登入頁並帶 `pendingAction`，登入後自動加入
  - 其他錯誤 → 顯示「加入失敗，請稍後再試」

### 執行紀錄（Log）

- 紅燈：6 個新測試失敗（區塊是空的、沒有載入 `library.js`）。
- 原本的 placeholder 測試（斷言 section 是空的）改成只檢查 section 存在。

### 驗證結果

- WebIntegration 新增 6 個（合計 169）。
- 瀏覽器驗證見〈最終驗證〉。

### 未解決事項

- JS 裡還有一份「狀態代碼 → 中文名稱」的對照，只用來顯示。#12 M4 會改成由伺服器渲染控制項，到時移除（已寫入 #12 計劃）。

### Code Review 與修正

見修正 3（登入網址只由伺服器產生）。

## M5 登入／註冊後的待辦動作（#51）

### 變更檔案

- `Application/Library/PendingLibraryAction.cs`（新增）
- `Controllers/AccountController.cs`、`Models/LoginForm.cs`
- `tests/UnitTests/PendingLibraryActionTests.cs`、`tests/WebIntegration/PendingLibraryActionTests.cs`（新增）
- `tests/WebIntegration/WebFixture.cs`（新增 `LibraryStore` 屬性，可替換成假的 store）、`AccountFlow.cs`（可帶 `pendingAction`）

### 實作思路

- 順序：先發 cookie → 執行待辦動作 → 照常導向。
- 待辦動作是 best-effort：失敗只記 Warning（只記 userId、bookId），不會讓已經成功的登入或註冊變成 500。如果失敗會讓整個請求失敗，就會出現「帳號已建立，但畫面顯示註冊失敗」的部分成功狀態。
- 只有 action 與 `returnUrl` 兩者都完全符合時才執行。

### 執行紀錄（Log）

- 紅燈：UnitTests 編譯失敗；WebIntegration「登入後加入」「註冊後加入」2 個失敗。
- Mutation（Haiku 與主 agent 各做一部分）：

| 弄壞的地方 | 失敗的測試 |
|---|---|
| 拿掉 try/catch | 2 個 |
| catch 縮成只抓 `ArgumentNullException` | 2 個 |
| action 改成不分大小寫 | 1 個 |
| `returnUrl` 允許結尾斜線 | 1 個 |

### 驗證結果

- UnitTests 新增 17 個、WebIntegration 新增 8 個。
- store 拋出 `TimeoutException` 時，登入與註冊仍然 302 並帶 cookie，註冊的使用者也確實存在。

### 未解決事項

無。

### Code Review 與修正

見修正 1（規則移到 `LibraryService`）、修正 2（只接受標準 GUID 格式）。

## M6 `/library` 頁（#52）

### 變更檔案

- `Controllers/LibraryController.cs`、`Models/LibraryPageViewModel.cs`、`Models/RatingText.cs`、`Views/Library/Index.cshtml`（新增）
- `Views/Books/_LibrarySection.cshtml`：改用 `RatingText`
- `tests/WebIntegration/LibraryPageTests.cs`（新增）

### 實作思路

- `?status=` 不合法或沒有帶時顯示全部。
- 篩選列使用 Bootstrap nav-pills，目前的篩選標上 `aria-current`。
- 每一列只顯示資料，#12 會加上編輯控制項。
- 評分文字抽成 `RatingText`，書籍頁和本頁共用。

### 執行紀錄（Log）

- 紅燈：8 個測試全部回 404（路由還不存在）。

### 驗證結果

- WebIntegration 新增 8 個（合計 185），涵蓋：
  - 未登入時導向登入頁
  - 空狀態，以及篩選後沒有資料時的空狀態
  - 新到舊排序
  - 每一列的欄位
  - READING 篩選、不合法的篩選值
  - A 看不到 B 的書

### 未解決事項

無。

### Code Review 與修正

見修正 5（註解引用的出處）。

## 兩軸 Review

Standards 與 Spec 兩個 reviewer 平行審查 `main...issue-11-report`。主 agent 逐項對照程式碼確認：

| # | 發現 | 判斷 | 處理 |
|---|---|---|---|
| 1 | 待辦動作的 best-effort 規則寫在 `AccountController`，違反「controller 不放商業規則」（計劃 README §2，以及該 controller 開頭的註解） | 成立 | 移到 `LibraryService.AddPendingAsync`，controller 只呼叫它（`e1809a4`），新增 5 個 UnitTests |
| 2 | `Guid.TryParse` 也接受 `{}`、`()`、沒有連字號的寫法，不符合「完全符合 `/books/{GUID}`」 | 成立 | 改成 `TryParseExact("D")` 並檢查長度為 36（.NET 10 的 "D" 會先去除前後空白）（`efb7d4b`） |
| 3 | `add-to-library` 字串在 view model 和 JS 裡各寫一次；JS 收到 401 時把 `location.search` 帶進 `returnUrl`，網址有 query 時加入會被悄悄丟掉 | 成立 | 按鈕帶上伺服器產生的 `data-login-url`，JS 直接使用；view model 改用常數（`c961620`） |
| 4 | UTC 轉台北時間的程式碼重複 | 成立 | 抽成 `TaipeiTimeZone.FromUtc`，兩個 response 共用（`5a827b1`） |
| 5 | `RatingText` 的註解引用 ui-flow §3.5，但那一節沒有定義評分格式 | 成立 | 改成引用計劃 §5（`0d180a4`） |
| 6 | 組 ProblemDetails `ObjectResult` 的程式碼重複 | 成立 | 延後到 #12 M3（#12 會新增 400，#15 會新增 429，到時一起抽共用 helper） |
| 7 | JS 的狀態中文對照與 `ReadingStatusCode.Label` 重複 | 成立 | 延後到 #12 M4 |
| 8 | `ReadingStatusCode` 有三個 switch；`LibraryService` 的 Find／List 只是轉呼叫；中文名稱放在 Application 層 | 判斷題 | 維持：分層符合計劃，名稱是 CONTEXT.md 的用語 |
| 9 | 401 時多帶 `pendingAction` 不在計劃內 | 主 agent 刻意的決定 | 已寫入 identity-auth §6、ui-flow §3.5 |
| 10 | 登入連結的 `returnUrl` 把 `/` 編碼成 `%2F` | 等價寫法 | 不改 |

修正後的 mutation：把 `AddPendingAsync` 的 try/catch 拿掉，UnitTests 有 1 個失敗、WebIntegration 有 2 個失敗。

## 最終驗證

- `dotnet build`：0 warning。
- `dotnet test`：UnitTests 469、DatabaseIntegration 70、WebIntegration 185，全部通過。
  - 開工前的基準是 410 / 59 / 154，所以本票新增 59 / 11 / 31 個測試。
- 瀏覽器（Playwright headless Chromium，`https://localhost:5201`，關閉 embedding 補齊，不呼叫 OpenAI）：在修正前、修正後各跑一次，兩次都是 12/12 通過。
  1. 未登入時在書籍頁按「加入書單」→ 登入頁，網址帶 `returnUrl` 與 `pendingAction`
  2. 從登入頁點「註冊」→ 參數保留
  3. 註冊後回到原書籍頁
  4. 書已加入（想讀、未評分）
  5. 已登入時按按鈕 → 不重新載入頁面，直接換成狀態顯示
  6. 刪除 cookie 模擬 token 過期，在網址帶 `?ref=x` 的書籍頁按加入 → 401 → 登入頁，網址帶 `pendingAction`
  7. 登入後回到該書籍頁，書已加入（`?ref=x` 這個情境在修正 3 之後才加進腳本）
  8. `/library` 顯示 3 本書
  9. 依新到舊排序
  10. 「閱讀中」篩選 → 空狀態
  11. 「想讀」篩選 → 3 本
  12. 沒有 JS 錯誤
- 第一次執行時有 2 項失敗，是腳本本身的問題：它點到導覽列上的「註冊」，而不是登入表單旁那個帶參數的連結。修正選擇器後通過，程式沒有問題。
- 本機 DB 留下 2 個測試帳號：`m11-test-1792633783@example.com`、`m11-test-1792634307@example.com`，各有 3 筆書單。是否刪除由使用者決定。

## 未解決事項（整張票）

- 登入／註冊的 rate limiting 仍在暫緩中（`Docs/TODO.md`），與本票無關。
- 第 6、7 項延後到 #12。
