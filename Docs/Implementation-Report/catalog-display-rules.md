# 實作報告：Catalog 顯示規則（出版日期與貢獻者）

- 模組：M1「catalog display rules」
- 規格：`Docs/modules/book-catalog.md` §4.1（使用者，2026-10-11）
- 對應需求：#8 一般搜尋結果頁、#9 Book 詳細頁共用的呈現規則
- Branch：`catalog-display-rules`
- 實作：以 TDD 實作（先寫測試、確認紅燈、再實作）
- 日期：2026-10-11

## 變更檔案

| 檔案 | 類型 | 說明 |
|---|---|---|
| `Models/PublishedDateText.cs` | 新增 | `PublishedDateText.Format(DateOnly?, PublishedDatePrecision?)`：依精度輸出 `2011`／`2011-03`／`2011-03-15`，日期或精度為 null 時回傳 null |
| `Models/ContributorDisplay.cs` | 新增 | `ContributorName`、`ContributorGroup(Role, Names)`（`Label` 與 `Text` 為計算屬性）、`ContributorDisplay.RoleLabel`、`ContributorDisplay.GroupByRole` |
| `tests/UnitTests/PublishedDateTextTests.cs` | 新增 | 8 個測試：每種精度、Day 零補位、未定義精度拋例外、日期為 null、精度為 null、兩者皆 null |
| `tests/UnitTests/ContributorDisplayTests.cs` | 新增 | 14 個測試（8 個 Fact + 6 筆 InlineData）：角色標籤、未定義角色拋例外、`Label` 由角色推導、亂序輸入、角色依首次出現排序、`Text` 格式、空輸入 |
| `Docs/Implementation-Report/catalog-display-rules.md` | 新增 | 本報告 |

## 實作思路

- **日期**：精度與日期一起保存，因此精度為 null 時回傳 null，不猜測精度。格式使用 `InvariantCulture`，月與日補零。
- **角色標籤**：`switch` 運算式逐一對應六個 enum 成員；未定義的值拋出 `ArgumentOutOfRangeException`，不回傳預設字串。
- **分組**：先依 `Order` 排序，再以 `GroupBy(Role)` 分組。`Enumerable.GroupBy` 的文件保證群組依來源中該 key 第一次出現的順序輸出，因此每個角色的位置就是它最小 `Order` 的位置。組內名字同樣依 `Order`。輸入順序不影響結果。
- **顯示文字**：`ContributorGroup.Text` 為 `{Label}：{names 以「、」連接}`，冒號為全形 `：`。`Label` 由 `Role` 經 `RoleLabel` 推導，不另存，因此角色與標籤不會不一致。
- 本模組不讀資料庫、不含 controller、View、Program.cs、Application 或 Infrastructure 程式碼。

## 執行紀錄（Log）

1. 先寫兩份測試檔，`dotnet test tests/UnitTests` 因找不到 `PublishedDateText`、`ContributorDisplay`、`ContributorName`、`ContributorGroup` 而編譯失敗（紅燈，CS0103／CS0246）。
2. 新增 `Models/PublishedDateText.cs` 與 `Models/ContributorDisplay.cs`。
3. 重新執行測試與建置，全部通過。
4. `git diff --check` 無輸出（通過）。
5. Code review 後依「Code Review 與修正」完成六項修正，重新執行測試與建置，全部通過。

## 驗證結果（逐條對照需求）

| 需求 | 驗證 | 結果 |
|---|---|---|
| 精度 `Year` → `2011` | `Year_precision_shows_only_the_year` | 通過 |
| 精度 `Month` → `2011-03` | `Month_precision_shows_year_and_zero_padded_month` | 通過 |
| 精度 `Day` → `2011-03-15` | `Day_precision_shows_the_full_zero_padded_date` | 通過 |
| 零補位（2011-03-05） | `Day_precision_zero_pads_single_digit_month_and_day` | 通過 |
| 未定義精度拋出 `ArgumentOutOfRangeException` | `Undefined_precision_throws` | 通過 |
| 日期為 null 回傳 null | `Null_date_returns_null` | 通過 |
| 精度為 null 回傳 null，不猜測 | `Null_precision_returns_null_instead_of_guessing` | 通過 |
| 每個角色都有非空標籤，且符合規格標籤 | `Every_role_has_a_non_empty_label`、`Role_label_matches_the_spec`（6 個 InlineData） | 通過 |
| 未定義角色拋出 `ArgumentOutOfRangeException` | `Undefined_role_throws` | 通過 |
| 亂序輸入依 `Order` 組內排序 | `Unsorted_input_is_grouped_and_ordered_by_contributor_order` | 通過 |
| 角色依首次出現排序（Author(1), Translator(2), Author(3) → 作者：A、C 在前） | `Groups_follow_the_first_appearance_of_each_role`、`A_role_that_first_appears_earlier_comes_first_even_if_input_is_unsorted` | 通過 |
| `Label` 由角色推導 | `Label_is_derived_from_the_role` | 通過 |
| `Text` 格式（全形冒號、頓號分隔） | `Text_uses_full_width_colon_and_ideographic_comma_separator` | 通過 |
| 空輸入回傳空清單 | `Empty_input_returns_no_groups` | 通過 |

測試輸出（`dotnet test tests/UnitTests`）：

```text
Passed!  - Failed:     0, Passed:    31, Skipped:     0, Total:    31, Duration: 42 ms - UnitTests.dll (net10.0)
```

（31 筆包含既有的 9 筆 Bestseller 與 TaipeiTimeZone 測試，本模組新增 22 筆：`PublishedDateTextTests` 8 筆、`ContributorDisplayTests` 14 筆。）

建置（`dotnet build`）：

```text
    0 Error(s)
    0 Warning(s)
```

## Code Review 與修正

Code review 後於同一 branch 新增一個 commit 修正，未 amend 既有 commit。

1. **報告測試數量更正**：原報告誤列 `ContributorDisplayTests` 為 21 筆、本模組為 29 筆。修正後依實際執行結果：`ContributorDisplayTests` 14 筆，本模組 22 筆，總計 31 筆。
2. **新增未定義精度測試**：`Undefined_precision_throws` 驗證 `PublishedDateText.Format` 對 `(PublishedDatePrecision)99` 拋出 `ArgumentOutOfRangeException`。
3. **`ContributorGroup.Label` 改為計算屬性**：建構子改為 `ContributorGroup(ContributorRole Role, IReadOnlyList<string> Names)`，`Label => ContributorDisplay.RoleLabel(Role)`，`Text` 不變。`GroupByRole` 與測試同步更新，並新增 `Label_is_derived_from_the_role`，所有測試不再能建構標籤與角色不一致的群組。
4. **變數命名**：`PublishedDateText.Format` 的模式變數由 `p` 改為 `datePrecision`，對齊專案 `is { } name` 的寫法。
5. **移除重複測試**：刪除 `Month_precision_zero_pads_single_digit_month`（與 `Month_precision_shows_year_and_zero_padded_month` 重複的 03 月案例），保留 Day 零補位測試。
6. **`ContributorName` 註解**：補上說明，此為刻意與 `BookContributor` 實體解耦的呈現用 record；屬性名 `Order` 與後續 Book 詳細頁契約一致，維持不變。

## 未解決事項

- `PublishedDateText.Format` 對未定義的精度值拋出 `ArgumentOutOfRangeException`。規格未規定此情況；選擇與 `RoleLabel` 一致的處理方式，屬局部可逆的決定。
- 本模組不實作 #8、#9 的頁面、controller 或 view model 串接，這些由後續模組處理。
