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
| `Models/ContributorDisplay.cs` | 新增 | `ContributorName`、`ContributorGroup`（含 `Text`）、`ContributorDisplay.RoleLabel`、`ContributorDisplay.GroupByRole` |
| `tests/UnitTests/PublishedDateTextTests.cs` | 新增 | 8 個測試：每種精度、零補位、日期為 null、精度為 null、兩者皆 null |
| `tests/UnitTests/ContributorDisplayTests.cs` | 新增 | 21 個測試（含 Theory）：角色標籤、未定義角色拋例外、亂序輸入、角色依首次出現排序、`Text` 格式、空輸入 |
| `Docs/Implementation-Report/catalog-display-rules.md` | 新增 | 本報告 |

## 實作思路

- **日期**：精度與日期一起保存，因此精度為 null 時回傳 null，不猜測精度。格式使用 `InvariantCulture`，月與日補零。
- **角色標籤**：`switch` 運算式逐一對應六個 enum 成員；未定義的值拋出 `ArgumentOutOfRangeException`，不回傳預設字串。
- **分組**：先依 `Order` 排序，再以 `GroupBy(Role)` 分組。`Enumerable.GroupBy` 的文件保證群組依來源中該 key 第一次出現的順序輸出，因此每個角色的位置就是它最小 `Order` 的位置。組內名字同樣依 `Order`。輸入順序不影響結果。
- **顯示文字**：`ContributorGroup.Text` 為 `{Label}：{names 以「、」連接}`，冒號為全形 `：`。
- 本模組不讀資料庫、不含 controller、View、Program.cs、Application 或 Infrastructure 程式碼。

## 執行紀錄（Log）

1. 先寫兩份測試檔，`dotnet test tests/UnitTests` 因找不到 `PublishedDateText`、`ContributorDisplay`、`ContributorName`、`ContributorGroup` 而編譯失敗（紅燈，CS0103／CS0246）。
2. 新增 `Models/PublishedDateText.cs` 與 `Models/ContributorDisplay.cs`。
3. 重新執行測試與建置，全部通過。
4. `git diff --check` 無輸出（通過）。

## 驗證結果（逐條對照需求）

| 需求 | 驗證 | 結果 |
|---|---|---|
| 精度 `Year` → `2011` | `Year_precision_shows_only_the_year` | 通過 |
| 精度 `Month` → `2011-03` | `Month_precision_shows_year_and_zero_padded_month` | 通過 |
| 精度 `Day` → `2011-03-15` | `Day_precision_shows_the_full_zero_padded_date` | 通過 |
| 零補位（2011-03-05） | `Day_precision_zero_pads_single_digit_month_and_day` | 通過 |
| 日期為 null 回傳 null | `Null_date_returns_null` | 通過 |
| 精度為 null 回傳 null，不猜測 | `Null_precision_returns_null_instead_of_guessing` | 通過 |
| 每個角色都有非空標籤，且符合規格標籤 | `Every_role_has_a_non_empty_label`、`Role_label_matches_the_spec`（6 個 InlineData） | 通過 |
| 未定義角色拋出 `ArgumentOutOfRangeException` | `Undefined_role_throws` | 通過 |
| 亂序輸入依 `Order` 組內排序 | `Unsorted_input_is_grouped_and_ordered_by_contributor_order` | 通過 |
| 角色依首次出現排序（Author(1), Translator(2), Author(3) → 作者：A、C 在前） | `Groups_follow_the_first_appearance_of_each_role`、`A_role_that_first_appears_earlier_comes_first_even_if_input_is_unsorted` | 通過 |
| `Text` 格式（全形冒號、頓號分隔） | `Text_uses_full_width_colon_and_ideographic_comma_separator` | 通過 |
| 空輸入回傳空清單 | `Empty_input_returns_no_groups` | 通過 |

測試輸出（`dotnet test tests/UnitTests`）：

```text
Passed!  - Failed:     0, Passed:    30, Skipped:     0, Total:    30, Duration: 46 ms - UnitTests.dll (net10.0)
```

（30 筆包含既有的 Bestseller 與 TaipeiTimeZone 測試，本模組新增 29 筆。）

建置（`dotnet build`）：

```text
    0 Error(s)
    0 Warning(s)
```

## 未解決事項

- `PublishedDateText.Format` 對未定義的精度值拋出 `ArgumentOutOfRangeException`。規格未規定此情況；選擇與 `RoleLabel` 一致的處理方式，屬局部可逆的決定。
- 本模組不實作 #8、#9 的頁面、controller 或 view model 串接，這些由後續模組處理。
