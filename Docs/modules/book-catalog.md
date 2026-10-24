# Book Catalog Module

> Path: `Docs/modules/book-catalog.md`
> Authority: 一般搜尋、書庫瀏覽、Book 詳細頁、Google Books 書目寫入
> Requirements: SEARCH-01～04、BOOK-01～05、BROWSE-01～04
> Data contract: `Docs/data/data-model.md`

## 1. Scope

- 一般搜尋（只查 Local DB）。
- 書庫瀏覽（`/books`，只查 Local DB；首頁隨機 10 本也由此模組提供）。
- Book 詳細資料讀取。
- 提供其他模組讀取 Book 的 Application 介面（Bestseller、Recommendation、Library 透過它讀 Book）。
- Google Books 結果正規化與寫入（由 Recommendation 呼叫；Catalog 擁有 `books` 與相關資料表的寫入規則）。

不負責：博客來爬取（crawler）、embedding、推薦排序。

## 2. Invariants

1. 一般搜尋只查 Local DB；任何情況（含查無結果）都不呼叫 Google Books。
2. 一般搜尋不使用 embedding 或 LLM。
3. Google Books 寫入必須遵守 `data-model.md` §7 cross-source identity resolution：正規化 ISBN 恰好命中 1 本既有 Book 時只新增 Book Source 並補 NULL，不建立 duplicate Book。

## 3. 一般搜尋

### 3.1 輸入判定

```text
q = trim(input)
q 為空 → 回傳空結果（不列出全部書籍）

normalized = NFKC(q)（全形數字、全形 X、全形連字號轉成半形）, remove "-" / whitespace, uppercase
normalized 符合 ISBN-13（13 位數字）或 ISBN-10（9 位數字 + 數字或 X）
    → ISBN 模式
否則
    → 關鍵字模式（比對用原本的 q，不做 NFKC）
```

全形轉半形只用於 ISBN 判定（使用者，2026-10-11）：台灣使用者常以全形輸入法輸入 ISBN。

本節的「是否為 ISBN」判定（長度 10 或 13）刻意與寫入端的 ISBN 正規化 protocol（`data-model.md` §7.1，不驗證長度）分開：輸入 `ABC123` 不會被當成 ISBN 搜尋。判定規則在 multi-source 變更後不變。

### 3.2 比對

| 模式 | 比對 |
|---|---|
| ISBN | `book_identifiers.identifier_type IN (ISBN, ISBN_13, ISBN_10) AND identifier_value = normalized`（過渡期查三種類型；migration 011 之後只查 `ISBN`，`data-model.md` §11.3。不做 ISBN-10 ↔ 13 互轉；`OTHER` 類型不參與） |
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
- `page` 超過最後一頁（有結果時）→ 重導到最後一頁，不顯示空結果頁；頁碼列也永遠不產生超過最後一頁的連結（使用者，2026-10-11，取代原本「回傳空結果頁」）。查無結果時沒有頁碼可去，照常顯示「找不到符合的書」。極大的整數頁碼（含超過 64 位元範圍者）一樣視為超過最後一頁。
- `page` 不是整數或小於 1 → 視為第 1 頁（使用者，2026-10-11）。
- 分頁呈現（使用者，2026-10-11）：顯示「共 N 筆，第 p／P 頁」、上一頁／下一頁與頁碼連結；總頁數 ≤ 10 時列出全部頁碼，超過時只列第 1 頁、最後一頁與目前頁前後各 2 頁，其餘以「…」省略。總筆數以 COUNT 查詢取得。

### 3.4 結果項目

每筆：`book_id`、書名、作者（只列 `AUTHOR` 角色，依 `contributor_order`，以「、」連接；不含 `ORIGINAL_AUTHOR` 等其他角色，與書庫、首頁一致，使用者 2026-10-11）、出版社、出版日期（依精度，格式見 §4.1）、封面（沒有封面時顯示「無封面」佔位）。連結到 `/books/{id}`。

### 3.5 搜尋結果頁 `/search?q=&page=`

- 頁面上方有搜尋框，預填目前的 `q`。
- 空白輸入或查無結果：顯示「找不到符合的書」（`ui-flow.md` §3.5）。

### 3.6 書庫瀏覽 `/books?page=`

書庫是 Catalog 的全量瀏覽列表（UI 用語見 `CONTEXT.md`），與一般搜尋共用結果項目與分頁呈現，但沒有查詢條件。BROWSE-01～04。

- 只查 Local DB；不使用 embedding 或 LLM，也不呼叫 Google Books。
- 排序（固定）：

```text
1. published_date 有值者優先
2. published_date DESC
3. books.id（穩定排序）
```

- 排序只在資料集不變時是決定性的。offset 分頁在兩次請求之間有書籍新增或出版日期改變時，後續頁的內容可能位移（同一本書出現在相鄰兩頁，或某本書被略過）。本版不處理，見 `Docs/Implementation-Report/issue-109-book-browse.md` 未解決事項。
- 分頁規則同 §3.3：每頁 20 筆、`page` 從 1 起、不合法或小於 1 視為第 1 頁、超過最後一頁（有書時）重導到最後一頁、極大整數同樣視為超過。
- 書庫為空時沒有最後一頁可去：不重導，顯示「書庫還沒有書」，不顯示「共 N 本」與分頁列。
- 結果項目與 §3.4 相同（`book_id`、書名、作者、出版社、出版日期、封面），連結到 `/books/{id}`。不含簡介與目錄（BOOK-05）。

#### 首頁隨機樣本

- 首頁顯示書庫中隨機 10 本（`BookBrowseService.SampleHomeAsync`）；書庫不足 10 本時全部顯示，空庫時顯示「書庫還沒有書」。
- 不快取，每次載入重新抽樣。
- 隨機排序（`ORDER BY random()`）需要對整張 Catalog 排序後取前 N 筆，成本隨資料量增加。目前未定義效能 SLO（`system-architecture.md` §168）；實際量測基準見 `Docs/Implementation-Report/issue-109-book-browse.md`。

## 4. Book 詳細頁

顯示欄位（BOOK-01）：title、subtitle、contributors（含角色）、publisher、published date（依 `published_date_precision` 顯示，BOOK-03）、ISBN、subjects、page count、thumbnail。

### 4.1 顯示規則（使用者，2026-10-11）

- 出版日期依精度（一般搜尋共用）：`YEAR` → `2011`，`MONTH` → `2011-03`，`DAY` → `2011-03-15`。
- 貢獻者依角色分組，每組一行，例「作者：劉慈欣、作者乙」「譯者：譯者甲」。組的順序依各角色第一次出現的 `contributor_order`；組內名字依 `contributor_order`，以「、」連接。角色標籤：`AUTHOR` 作者、`ORIGINAL_AUTHOR` 原文作者、`TRANSLATOR` 譯者、`EDITOR` 編者、`ILLUSTRATOR` 繪者、`OTHER` 其他。
- ISBN：`ISBN` 類型標示為「ISBN」，legacy 的 `ISBN_13`、`ISBN_10` 維持標示「ISBN-13」「ISBN-10」；`OTHER` 類型的 identifier 不顯示。過渡期（migration 010 至 011）同一本書可能同時有 `ISBN`、`ISBN_13`、`ISBN_10` 資料：值相同時依類型優先順序 `ISBN` > `ISBN_13` > `ISBN_10` 只顯示一次（例如 `ISBN X` 與 `ISBN_13 X` 只顯示一次 `ISBN X`）；值不同的全部顯示。011 之後只讀 `ISBN`。
- 分類：依分類文字排序，以「、」連接。`book_subjects` 沒有順序欄位，來源的層級順序（例：人文社科 > 政治 > 政治人物）無法還原；保留層級順序列為進階目標（§8）。
- 沒有值的欄位（副標、出版社、出版日期、ISBN、分類、頁數）整列不顯示。沒有封面時顯示「無封面」佔位。
- 外部連結以新分頁開啟（`target="_blank" rel="noopener noreferrer"`）。
- 外部連結只接受 `http`／`https` 的絕對網址；其他網址（例如 `javascript:`）不產生連結，主要按鈕改由下一個合格的來源擔任。封面網址同理，不是 `http`／`https` 絕對網址時視為沒有封面（顯示「無封面」）。來源資料來自 crawler 與 Google Books，這是顯示端的防護（2026-10-11）。
- Library 區塊在 Library 功能（#11）實作前只放一個空的容器（`<section id="library">`），畫面上不顯示任何內容。

**不顯示 description 與 table of contents**（BOOK-05）：兩者只保存於資料庫供 Recommendation 讀取。Book 詳細頁的 view model 與任何 JSON 回應都不得包含這兩個欄位，避免日後誤顯示；書籍的完整介紹由來源網站提供。封面直接引用來源的 `thumbnail_url`，不轉存。

外部連結（BOOK-02）：每個 `book_sources` row 各一個連結，依 `source_code` 判斷規則，連結文字使用 `source_providers.display_name`（JOIN `source_providers`；不得以 `enabled` 過濾，disabled provider 既有的來源照常顯示，`data-model.md` §6.1）。

| 來源 | 連結文字 | URL |
|---|---|---|
| 主要按鈕（見下） | `BOOKS_COM_TW`：在博客來查看完整介紹（醒目的主要按鈕）；其他 provider：在 {display_name} 查看（主要按鈕樣式） | `source_url` |
| 其餘來源 | 在 {display_name} 查看 | `source_url` |

主要按鈕的選擇（使用者，2026-10-11；#113 改以 code 判斷）：

1. 有 `BOOKS_COM_TW` 來源時，`first_seen_at` 最早者（同時間再依 `id`）為主要按鈕「在博客來查看完整介紹」，其餘博客來來源為次要連結「在博客來查看」。
2. 沒有博客來來源時，依同樣的 `first_seen_at`、`id` 順序取第一個合格來源為主要按鈕（例如只有 Google Books 來源的書，Google Books 連結即為主要按鈕「在 Google Books 查看」）。
3. 不合格的網址不產生連結，主要按鈕改由下一個合格的來源擔任（§4.1）。

> 實作狀態：PR2（#115）已改為 `{Id, SourceCode, ProviderDisplayName, Url, FirstSeenAt}` 並 JOIN `source_providers`（不以 `enabled` 過濾）；Detail 與一般搜尋讀三種 ISBN 類型。011 之前仍為過渡期。

Library 狀態（BOOK-04）：已登入且該書在 Library 中時，顯示並可修改 Reading Status 與評分（行為見 `user-library.md`）。Library 狀態不進入 cache。

找不到 `book_id` → 404 頁。

## 5. Cache

- Book 詳細資料（不含 Library 狀態）以 `IMemoryCache` 快取，TTL 10 分鐘。
- 不快取搜尋結果。

## 6. Google Books 書目寫入

供 Recommendation fallback 呼叫。輸入為 Google Books volume；輸出為 `book_id`。

```text
1. 依 data-model.md §3 欄位對照 normalize；industryIdentifiers 的 ISBN 依 §7.1 正規化，存成 ISBN 類型
2. identity resolution（data-model.md §7.2，與 crawler 相同的規則）：
     (GOOGLE_BOOKS, Volume ID) → (GOOGLE_BOOKS, source_url) 已存在 → 既有 Book
     （Volume ID 與 URL 對到不同 Source → source_identity_conflict；URL 漂移 → 保留既有 URL，§7.3）
     否則以所有 ISBN 查 distinct Book：
       = 0 → 建立新 Book
       = 1 → 既有 Book + 新 Book Source + 補 NULL（data-model.md §7.4）
       ≥ 2 → 建立新 Book（ambiguous，記 INFO）
3. 每個 volume 的寫入在同一 transaction
```

- 附加到既有 Book 時只補 NULL 欄位，不覆寫任何既有非 NULL 值；不存在「博客來 > Google Books」之類的來源優先順序（`data-model.md` §6.2）。
- `published_date` 必須保存實際精度（Google Books 常只有年份或年月），與 `published_date_precision` 成對補值。
- `language` 依 `data-model.md` §3.1 正規化大小寫；`zh` 不補地區。
- `authors[]` 無角色資訊時一律為 `AUTHOR`。
- 無 ISBN 時不得以書名 / 作者相似度合併。
- **前置條件（#14 實作前）**：在跨 process 的序列化完成以前，Catalog identity resolution 只允許一個 writer。PR4 不會解除這個限制，目前唯一的 writer 是 crawler。Google Books 寫入要使用上述規則之前，必須先加入跨 process 的序列化：依 `data-model.md` §7.5 的 lock protocol：對 draft 所有正規化 ISBN 的 lock key 去重、依數值排序，依序取得 transaction 範圍的 advisory lock，再重新查詢 distinct Book 數量（`data-model.md` §7.5）。

## 7. Validation

- 書庫排序：有出版日期者在前、日期新到舊、同日依 Id、無日期者最後。
- 書庫分頁：每頁 20 筆、非法頁視為第 1 頁、超過最後一頁重導、`int.MaxValue` 與超過 64 位元的頁碼不溢位、空庫不重導。
- 首頁樣本：書庫超過 10 本時回傳 10 本且不重複；不足 10 本時全部回傳。
- ISBN 判定：含 `-`、空白、小寫 `x` 的輸入可正確判定；12 位數字不是 ISBN。
- 關鍵字比對書名與作者；不比對簡介。
- LIKE 特殊字元 escape。
- 排序：完全相符優先、出版日期新到舊、NULL 最後。
- 查無結果時不呼叫 Google Books（以 fake adapter 驗證沒有呼叫）。
- ISBN 搜尋：`ISBN`、`ISBN_13`、`ISBN_10` 三種類型都查得到；輸入 `ABC123` 不走 ISBN 模式。
- Book 詳細頁：同值的 `ISBN_13 X` 與 `ISBN X` 只顯示一次；disabled provider 的來源仍顯示；連結文字取自 `display_name`。
- Google Books 寫入：ISBN 恰好命中 1 本時不建立 duplicate Book 且只補 NULL；命中 ≥ 2 本或無 ISBN 時建立新 Book。

## 8. 進階開發目標

- 分類依來源層級順序顯示：在 `book_subjects` 加入順序欄位（例 `subject_order`），crawler 與 Google Books 寫入時保存來源順序，詳細頁依此排序。需要 schema 變更、EF migration 與 crawler 修改（L3），MVP 不做（使用者，2026-10-11）。
