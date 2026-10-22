# Library Module

> Path: `Docs/modules/user-library.md`
> Authority: Library Entry、Reading Status、評分
> Requirements: LIB-01～06、BOOK-04
> Data contract: `Docs/data/data-model.md` §5.10 `user_books`（程式中的 `LibraryEntry` entity 對應此表）

## 1. Scope

- 加入、查看、移除 Library Entry。
- 修改 Reading Status 與評分。

全部需登入；使用者只能存取自己的 Library。

## 2. Invariants

1. 一位使用者對同一本 Book 最多一個 Library Entry（PK `(user_id, book_id)`）。
2. Reading Status 只能是 `WANT_TO_READ`、`READING`、`FINISHED`。
3. 評分只能是 `NULL` 或 1～5，與 Reading Status 無關。
4. 操作他人的 Library Entry 不可能發生：`user_id` 一律取自目前使用者，不接受 client 傳入。

## 3. 操作

| 操作 | 規則 |
|---|---|
| 加入 | 建立 Entry，`reading_status = WANT_TO_READ`、`rating = NULL`；已存在 → 不變，回傳成功（idempotent） |
| 修改狀態 | 只更新 `reading_status` 與 `updated_at` |
| 評分 | 設為 1～5，或清除為 `NULL`；任何 Reading Status 皆可 |
| 移除 | 刪除 Entry（hard delete），評分一併消失；不存在 → 回傳成功（idempotent） |

- 對不存在的 `book_id` 加入 → 404。
- 修改狀態或評分時 Entry 不存在 → 404。
- 未登入時的「加入」走 `identity-auth.md` §6 待辦動作流程。

## 4. 書單頁 `/library`

- 依 `updated_at` 新到舊排序，不分頁。
- 可依 Reading Status 篩選（全部 / 想讀 / 閱讀中 / 已讀），篩選以 query string 表示：`?status=WANT_TO_READ|READING|FINISHED`。缺少或不合法的值視為「全部」，不回錯誤（#11 決定）。
- Reading Status 顯示名稱：`WANT_TO_READ` 想讀、`READING` 閱讀中、`FINISHED` 已讀。評分顯示為五顆星（例：4 分為 ★★★★☆），沒有評分顯示「未評分」（#11 決定）。
- 每筆：封面、書名、作者、Reading Status（可直接修改）、評分（可直接修改）、移除按鈕；點擊書名進入 `/books/{id}`。
- 空書單顯示「還沒有加入任何書」與前往暢銷榜的連結。

## 5. Book 詳細頁整合

- 已登入且在 Library 中：顯示並可修改 Reading Status、評分，以及移除。
- 已登入但不在 Library 中：顯示「加入書單」。
- 未登入：顯示「加入書單」，點擊走待辦動作流程。
- 已登入時按「加入書單」若收到 401（token 過期），同樣走待辦動作流程（`identity-auth.md` §6）。

修改皆透過 JSON 端點（`api-spec.md`），成功後就地更新畫面，不重新載入頁面。

## 6. Validation

1. 加入後狀態為 `WANT_TO_READ`；重複加入不改變既有狀態。
2. 評分 0 或 6 → 驗證錯誤；`NULL` → 清除成功。
3. `WANT_TO_READ` 狀態下可評分。
4. 移除後再查詢 → 不在 Library 中；評分消失。
5. 使用者 A 無法讀取或修改使用者 B 的 Entry。
6. 篩選只回傳指定狀態。
