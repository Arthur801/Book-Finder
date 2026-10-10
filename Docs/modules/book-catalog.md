# Book Catalog Module

> Path: `Docs/modules/book-catalog.md`
> Authority: 一般搜尋、Book 詳細頁、Google Books 書目寫入
> Requirements: SEARCH-01～04、BOOK-01～04
> Data contract: `Docs/data/data-model.md`

## 1. Scope

- 一般搜尋（只查 Local DB）。
- Book 詳細資料讀取。
- 提供其他模組讀取 Book 的 Application 介面（Bestseller、Recommendation、Library 透過它讀 Book）。
- Google Books 結果正規化與寫入（由 Recommendation 呼叫；Catalog 擁有 `books` 與相關資料表的寫入規則）。

不負責：博客來爬取（crawler）、embedding、推薦排序。

## 2. Invariants

1. 一般搜尋只查 Local DB；任何情況（含查無結果）都不呼叫 Google Books。
2. 一般搜尋不使用 embedding 或 LLM。
3. Google Books 寫入必須遵守 `data-model.md` §6 cross-source identity resolution：ISBN 命中既有 Book 時只新增 Book Source，不建立 duplicate Book。

## 3. 一般搜尋

### 3.1 輸入判定

```text
q = trim(input)
q 為空 → 回傳空結果（不列出全部書籍）

normalized = remove "-" / whitespace, uppercase
normalized 符合 ISBN-13（13 位數字）或 ISBN-10（9 位數字 + 數字或 X）
    → ISBN 模式
否則
    → 關鍵字模式
```

### 3.2 比對

| 模式 | 比對 |
|---|---|
| ISBN | `book_identifiers.identifier_value = normalized`（不做 ISBN-10 ↔ 13 互轉） |
| 關鍵字 | `books.title ILIKE '%q%'` OR 任一 `book_contributors.name ILIKE '%q%'` |

- 整段 `q` 當作一個字串比對，不拆詞。
- 不比對簡介、出版社、分類。
- 不做繁簡互通。
- `%`、`_` 等 LIKE 特殊字元必須 escape。

### 3.3 排序與分頁

```text
1. books.title 與 q 完全相符（不分大小寫）者優先
2. published_date DESC，NULL 排最後
3. books.id（穩定排序）
```

- 每頁 20 筆，offset 分頁，`page` 從 1 開始。
- `page` 超出範圍時回傳空結果頁，不報錯。

### 3.4 結果項目

每筆：`book_id`、書名、作者（`AUTHOR` 角色，依 `contributor_order`）、出版社、出版日期（依精度）、封面。

## 4. Book 詳細頁

顯示欄位（BOOK-01）：title、subtitle、contributors（含角色）、publisher、published date（依 `published_date_precision` 顯示，BOOK-03）、description、ISBN、subjects、page count、thumbnail、table of contents（若有）。

外部連結（BOOK-02）：每個 `book_sources` row 各一個連結。

| `source_type` | 連結文字 | URL |
|---|---|---|
| `BOOKS_COM_TW` | 在博客來查看 | `source_url` |
| `GOOGLE_BOOKS` | 在 Google Books 查看 | `source_url` |

Library 狀態（BOOK-04）：已登入且該書在 Library 中時，顯示並可修改 Reading Status 與評分（行為見 `user-library.md`）。Library 狀態不進入 cache。

找不到 `book_id` → 404 頁。

## 5. Cache

- Book 詳細資料（不含 Library 狀態）以 `IMemoryCache` 快取，TTL 10 分鐘。
- 不快取搜尋結果。

## 6. Google Books 書目寫入

供 Recommendation fallback 呼叫。輸入為 Google Books volume；輸出為 `book_id`。

```text
1. 依 data-model.md §2 欄位對照 normalize
2. identity resolution（data-model.md §6）：
     ISBN-13 命中 → 既有 Book + 新 Book Source + canonical merge
     ISBN-10 命中 → 同上
     同 Volume ID 已存在 → 既有 Book
     否則 → 建立新 Book
3. Book + Book Source + identifiers + contributors + subjects 同一 transaction
```

- Canonical merge 優先順序：博客來非 NULL 值 > Google Books 非 NULL 值 > NULL。
- `published_date` 必須保存實際精度（Google Books 常只有年份或年月）。
- `language` 依 `data-model.md` §2.1 正規化大小寫；`zh` 不補地區。
- 無 ISBN 時不得以書名 / 作者相似度合併。

## 7. Validation

- ISBN 判定：含 `-`、空白、小寫 `x` 的輸入可正確判定；12 位數字不是 ISBN。
- 關鍵字比對書名與作者；不比對簡介。
- LIKE 特殊字元 escape。
- 排序：完全相符優先、出版日期新到舊、NULL 最後。
- 查無結果時不呼叫 Google Books（以 fake adapter 驗證沒有呼叫）。
- Google Books 寫入：ISBN 命中時不建立 duplicate Book；無 ISBN 時建立新 Book。
