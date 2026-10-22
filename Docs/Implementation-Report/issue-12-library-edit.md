# Issue #12 修改閱讀狀態、評分、移除：實作報告

- Issue：#12 修改閱讀狀態、評分、移除（LIB-04～06）
- 計劃：`Docs/plans/issue-12-library-edit.md`（模組拆分、預設決定 §5、#11 延後的兩個 review 項目）
- 規格：`Docs/modules/user-library.md` §3～§6、`Docs/api/api-spec.md` §1、§2、§4、`Docs/ui/ui-flow.md` §1、§3.5
- 日期：2026-10-22
- 分工：主 agent 負責規劃、派工、驗收、撰寫文件；M1～M4 與 review 修正由 Haiku subagent 以 TDD 實作。每個模組完成後，主 agent 親自執行 build 與測試並閱讀程式碼，L3 模組另做 mutation 抽查。
- PR：每個模組一個 PR，base 都是 `main`，分支接在 #11 最後一個分支之後依序疊上去：#54 M1 → #55 M2 → #56 M3 → #57 M4 → 本報告 PR（M5）。
- 期間處理了 #48 的 review（FK violation 只把 Book 的 FK 翻譯成「書不存在」）。修正依序 merge 進 #12 各分支，詳見 #48 的 PR 留言。

模組依賴：

```text
M1 LibraryChange（Application）＋ LibraryPatchParser（Web）
M2 LibraryService.UpdateAsync / RemoveAsync ＋ EfLibraryStore
        ↓
M3 PATCH / DELETE 端點：用 M1 解析 body，再呼叫 M2
        ↓
M4 共用控制項：只依賴 api-spec §4 的 HTTP contract
```

## 規格文件更新

| 檔案 | 說明 |
|---|---|
| `Docs/modules/user-library.md` §3 | 新增三條規則：`{}` 不算變更，不更新 `updated_at`；設成相同的值仍算變更；`readingStatus: null` 是驗證錯誤；移除時不跳確認對話框 |
| `Docs/modules/user-library.md` §4 | 評分改為可點擊的五顆星，沒有評分時仍顯示「未評分」；移除最後一本書後就地顯示空狀態；在篩選頁改了狀態的那一列，保留到重新整理為止 |
| `Docs/api/api-spec.md` §4 | PATCH 的各種錯誤：每種錯誤放在哪個 `errors` key（含整個 body 用的 `errors[""]`）、不論 `Content-Type` 都以 JSON 解析、`{}` 的行為、非 GUID → 404。DELETE 在 Entry 不存在、屬於別人、或 `bookId` 不是 GUID 時，一律回 204 |

## M1 PATCH body 解析（#54）

### 變更檔案

- `Application/Library/LibraryChange.cs`（新增）：`LibraryChange`、`RatingChange`（Unchanged／Clear／Set）
- `Models/LibraryPatchParser.cs`（新增）
- `tests/UnitTests/LibraryPatchParserTests.cs`（新增）

### 實作思路

- 「`rating` 省略」與「`rating: null`」意義不同，ASP.NET 的 model binding 分不出這兩種情況，所以改成逐個屬性讀 `JsonElement`。
- 依照修正後的計劃，`JsonElement` 只出現在 Web 層。Application 層只認識 `LibraryChange`，看不到 JSON。

### 執行紀錄（Log）

- 紅燈：實作前，測試因缺少型別而編譯失敗。
- 第一次讓測試轉綠時，`rating: true` 等 5 個案例失敗：`JsonElement.TryGetInt32` 遇到非數字型別會拋例外，不是回傳 false。修正方式是先檢查 `ValueKind == Number`，並在程式裡加註解說明原因。

### 驗證結果

UnitTests 新增 44 個：涵蓋計劃 §3 M1 表格的每一列，加上 `{}`、兩個欄位同時錯誤、未知欄位、各種不是物件的 body。

### 未解決事項

無。

### Code Review 與修正

見文末修正 3（修正註解引用的出處）、修正 4（三種狀態的列表只保留一份）。

## M2 修改與移除（#55）

### 變更檔案

- `Application/Library/ILibraryStore.cs`、`LibraryService.cs`：新增 `UpdateAsync`、`RemoveAsync`
- `Infrastructure/Persistence/EfLibraryStore.cs`
- `tests/UnitTests/LibraryServiceTests.cs`、`tests/DatabaseIntegration/EfLibraryStoreTests.cs`

### 實作思路

- 服務遇到空變更時直接回傳目前的 Entry，不呼叫 store 的寫入，所以不會動到 `updated_at`。
- store 以 `(user_id, book_id)` 載入並更新；別人的 Entry 對目前使用者來說等於不存在，回 `null`。
- 移除用一個 `ExecuteDeleteAsync`，條件同樣包含 `user_id`。

### 執行紀錄（Log）

- 紅燈：實作前，UnitTests 與 DatabaseIntegration 都編譯失敗。
- 主 agent 做了 mutation 抽查，以下 4 種改壞的方式，每一種都會讓 1 個測試失敗：
  - Update 拿掉 `user_id`
  - Remove 拿掉 `user_id`
  - Clear 時保留原本的評分
  - 不更新 `updated_at`

### 驗證結果

UnitTests 新增 5 個，DatabaseIntegration 新增 11 個，內容包括：三種評分變更、`WANT_TO_READ` 也能評分、`added_at` 不變、A 無法修改或刪除 B 的 Entry、重複移除不會出錯。

### 未解決事項

無。

### Code Review 與修正

見修正 3。

## M3 PATCH／DELETE 端點（#56）

### 變更檔案

- `Infrastructure/Identity/ApiProblemResults.cs`（新增，#11 延後的項目）：兩個 controller 與兩個 filter 共用
- `Controllers/LibraryApiController.cs`：新增 `Update`、`Remove`
- `tests/WebIntegration/LibraryApiTests.cs`

### 實作思路

- 先做一個單獨的重構 commit：把四處各自組 problem+json `ObjectResult` 的程式碼收斂成一個 helper。既有測試完全沒改，全部通過。
- 再加上兩個端點。controller 只負責把 HTTP 對應到 parser 和服務，不放規則。

### 執行紀錄（Log）

- 紅燈：新增 29 個測試，實作前全部失敗；原本 PUT 的 9 個測試仍然通過。
- 主 agent 做 mutation 抽查：拿掉 store 的 `user_id` 條件後，有 3 個 Web 測試失敗。

### 驗證結果

WebIntegration 新增 29 個，#12 的每一條 AC 都有對應的測試。

### 未解決事項

無。原本「沒有 `Content-Type` 時回 415（不是 problem+json）」的問題，已在修正 2 處理。

### Code Review 與修正

見修正 2。

## M4 共用可編輯控制項（#57）

### 變更檔案

- `Views/Shared/_LibraryControls.cshtml`、`Models/LibraryControlsViewModel.cs`（新增）
- `Views/Books/_LibrarySection.cshtml`、`Models/LibrarySectionViewModel.cs`、`Controllers/BooksController.cs`
- `Views/Library/Index.cshtml`、`Models/LibraryPageViewModel.cs`、`Controllers/LibraryController.cs`
- `wwwroot/js/library.js`（重寫）、`wwwroot/css/site.css`
- 刪除 `Models/RatingText.cs`
- `tests/WebIntegration/BookLibrarySectionTests.cs`、`LibraryPageTests.cs`、`HtmlPage.cs`

### 實作思路

- 所有畫面都由伺服器渲染，包括狀態選項文字、五顆星、清除與移除按鈕、錯誤訊息文字、空狀態。
- JS 不產生 HTML，也不保存任何顯示文字。它只負責送出請求，以及切換 `hidden`、`value`、`aria-pressed`、`disabled`。#11 延後的「JS 裡重複的狀態中文對照」因此一併消失。
- 失敗時恢復成伺服器最後確認過的值。這些值存在 `WeakMap`，每組控制項各一份。
- 書籍頁移除書之後，隱藏的控制項不重設成預設值。重設等於把預設值寫在 JS 裡；下次加入時，PUT 的回應會覆蓋掉這些舊值。

### 執行紀錄（Log）

- 紅燈：受影響的 21 個測試中，11 個失敗。
- 把 #48 的修正 merge 進來（`b09c743`）。

### 驗證結果

WebIntegration 合計 221 個。瀏覽器驗證見〈最終驗證〉。

### 未解決事項

無。

### Code Review 與修正

見修正 1、5、6，以及最後的星星底線修正。

## 兩軸 Review

Standards 與 Spec 兩個 reviewer 平行審查 `issue-11-report...issue-12-report`，只看 #12 的變更。主 agent 逐項對照程式碼確認：

| # | 發現 | 判斷 | 處理 |
|---|---|---|---|
| 1 | 「未評分」不見了，但 user-library §4 有寫（兩個 reviewer 都指出） | 成立 | 由伺服器渲染「未評分」，JS 只切換 `hidden`（`ef2b929`） |
| 2 | PATCH 沒有 `Content-Type` 時，框架回 415，回應不是 problem+json，違反 api-spec §1 | 成立 | 改由程式自己讀 body、以 JSON 解析，不依賴 `Content-Type`；規格同步寫入（`0a70d42`） |
| 3 | 4 處註解引用的規格章節不對（例如 user-library §5 並沒有寫空變更的規則） | 成立 | 先把規則寫進規格，再把註解改成引用正確的章節（`217e035`） |
| 4 | 三種狀態的列表寫了兩份 | 成立 | 改用 `ReadingStatusCode.All`（`4217ddc`） |
| 5 | 有兩個組登入網址的 builder | 成立 | 合併成 `LoginLink.For`，輸出內容逐字相同（`704c9e8`） |
| 6 | `LibrarySectionViewModel` 用三個旗標表達兩件事，view 裡還用了 `!` | 成立 | 改成只有 `Controls?` 一個來源，其他狀態都從它推導（`0948897`） |
| 7 | 篩選頁改狀態後，該列仍留在畫面上 | 規格沒有定義 | 採低風險預設：保留到重新整理，寫入 user-library §4 |
| 8 | `errors[""]`、DELETE 收到非 GUID 回 204、空 body 回 400，規格都沒寫 | 成立 | 寫入 api-spec §4 |
| 9 | `ApiProblemResults` 放在 `Infrastructure/Identity` | 判斷題 | 維持：`ApiRequest` 和兩個 filter 本來就放在這裡 |
| 10 | 錯誤訊息裡寫死狀態代碼；「輸入資料有誤」和 title 重複 | 判斷題 | 維持：這是給使用者看的文字 |
| 11 | JS 的錯誤欄位順序必須和 parser 一致 | 成立 | 加註解說明（併入修正 3） |

另外，主 agent 看瀏覽器截圖時發現星星下方有連結底線，已在 `e288509` 修正。

## 最終驗證

- `dotnet build`：0 warning。
- `dotnet test`：UnitTests 521、DatabaseIntegration 82、WebIntegration 224，全部通過。
  - 與 #11 完成時的 469／71／185 相比，本票新增 52／11／39 個。
- 瀏覽器（Playwright headless Chromium，`https://localhost:5201`，關閉 embedding 補齊，不呼叫 OpenAI）：
  - **#12 腳本 18/18 通過**：
    - 書籍頁：加入前看不到控制項；加入後顯示「想讀」與「未評分」；評 3 星後「未評分」隱藏；改成閱讀中後重新整理，資料仍保留；清除評分後「清除評分」按鈕停用；移除後換回「加入書單」；再次加入，回到「想讀、沒有評分」。整個過程頁面沒有重新載入。
    - API 回 500 時，顯示「操作失敗，請稍後再試」，下拉選單恢復原本的值。
    - 修改時收到 401，導向 `/account/login?returnUrl=%2Fbooks%2F…`，不帶 `pendingAction`。
    - `/library`：直接在頁面上評 4 星；移除一列；移除最後一列後顯示空狀態。
    - 頁面沒有 JS 錯誤。
    - 第一次執行時有 1 項失敗：腳本中途 reload 頁面，清掉了用來判斷「沒有重新載入」的標記。這是腳本本身的問題，修正腳本後通過。
  - **#11 回歸腳本 12/12 通過**：判斷「已加入」的方式改成新的控制項後重跑，確認登入後自動加入、401 時帶 `pendingAction`、`/library` 排序與篩選都正常。
- 本機 DB 裡新增了 `m12-test-*` 測試帳號，另外 #11 回歸測試也多建了一個 `m11-test-*`。是否刪除由使用者決定。

## 未解決事項（整張票）

無。
