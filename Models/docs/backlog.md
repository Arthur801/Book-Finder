# Models 優化與 debug 待辦

> PR2 phase A（#115）補記：2026-10-25 更新；程式變更以 `2a6966b`、`2c662f5`、`905c6fc`、`22bebf5` 記入 update-history。原查核基準保留，未重新審查其餘內容。
> PR4 M1（#120）補記：2026-10-25 更新；程式變更以 `5052361`、`d864acc` 記入 update-history。原查核基準保留，未重新審查其餘內容。

> 查核日期：2026-10-24；基準：`91333c3`；目標：`Models/`。本次只做靜態閱讀，未執行 build、測試、Mermaid renderer、資料庫或外部服務。開始時來源無未提交修改；其他代理既有的 `Controllers/docs/` 不屬本文件範圍。

本次未重現 runtime bug。以下為可由靜態證據支持的缺口／待驗證事項，不是實作或執行測試的授權。優先序 P1 表示契約演進前應處理，P2 表示可排程改善；風險沿用 AGENTS L1–L4。

| ID | 優先／風險／狀態 | 證據、影響與來源 | 工作方向、前置決策 | 結案條件、測試入口與案例 |
|---|---|---|---|---|
| M-B01 | P1／L3／確認測試 guard 範圍缺口 | [BookDetailContractTests](../../tests/UnitTests/BookDetailContractTests.cs) 只掃 Application.Catalog BookDetail*，不掃 Models 或所有公開 response。BOOK-05 要求頁面與 API 全面排除簡介／目錄；目前 DTO 無這兩欄，不代表已洩露 | 建立明列根 DTO／VM 的欄位排除 guard，遞迴只追自有子 DTO，避免掃入字串等 framework 型別；新增 response 時需更新清單。無產品決策前置 | 刻意加入 forbidden 欄位時 guard 失敗；正常對照 API 欄位集合；既有 HTML sentinel 保留。UnitTests 新 guard 待建，WebIntegration RecommendationApi／BookDetailPage／SearchPage 可擴充；M-T10 |
| M-B02 | P2／L2／待驗證與改善提案 | [BookDetailViewModel](../BookDetailViewModel.cs) 用 Uri 限絕對 http(s)，[AiHistoryDetailViewModel](../AiHistoryDetailViewModel.cs) 只認小寫前綴，Search／書庫／Library 多帶原 thumbnail。政策與缺值處理不同，可能呈現不一致；未證實可利用安全缺陷 | 用相同 URL fixture 比較各 VM 和 View；先決定是否統一封面 policy、大小寫／格式錯誤行為，再評估共用 helper，不能擅改公開內容 | 測試記錄 null、blank、relative、javascript、HTTP uppercase、合法 https、破損 URL 各結果；若統一，對照規格並所有顯示入口一致。入口 BookDetailPageTests／AiHistoryDetailTests／SearchPageTests；M-T11 |
| M-B03 | P1／L3／確認未實作（分階段目標） | [RecommendationResponse](../RecommendationResponse.cs) 固定 FallbackUsed:false，註解標示 #14；[RecommendationOutcome](../../Application/Recommendation/RecommendationOutcome.cs) 無 flag。[Recommendation](../../Docs/modules/recommendation.md) §6 要求候選不足5可進 fallback 並設定 true。這是上游能力缺口，不是單改 DTO 即能完成 | 在 Google Books 正規化／保存／embedding／同門檻流程完成後傳遞真實 fallback flag；保留每日額度先檢查、Candidate Set 規則。前置為 fallback Application 契約與流程實作，非本文件範圍 | ≥5 不呼叫 Google；<5 依規格補入候選；API flag 反映實際分支；核心推薦在保存前失敗不保存 Recommendation Search；不得先將常數改 true。RecommendationApiTests 可擴充，新 fallback fake 與測試待建；M-T12 |
| M-B04 | P2／L2／待驗證 | [PagerViewModel](../PagerViewModel.cs) 不 clamp CurrentPage；[PageWindow](../PageWindow.cs) 只 clamp 顯示 window，Search、Books、Ai Controller 承擔重導。現有 PageWindow 單元測試與頁面整合測試存在，但未見獨立 PagerViewModelTests | 新增純 helper 邊界測試，量測錯誤 callback 目標是否超範圍，先確認 factory 前置條件；不要求改實作 | 0頁無連結；有效頁標記與上一／下一正確；超頁呼叫的前一頁不超總頁數；頁面 caller 仍正規化。UnitTests 新 PagerViewModelTests 待建；M-T13 |
| M-B05 | P1／L3／已處理（#113 PR2，phase A `2c662f5`、phase B `d9d8948`） | [BookDetailViewModel](../BookDetailViewModel.cs) 的 `IdentifierLabel` 已加 `Isbn` → `ISBN` 標籤（原本只接受 `Isbn13`／`Isbn10`，其他類型 throw）；主要按鈕已改以 `SourceCodes` 常數判斷（取代 `SourceType` enum）；連結文字與主要按鈕以 `SourceType` 判斷。目標見 [book-catalog §4](../../Docs/modules/book-catalog.md) | 已完成。PR4 M1（`5052361`）移除了 `IdentifierLabel` 與 010 期間的同值去重和類型優先序：view model 只保留 `ISBN`，依值排序，標籤固定為 `ISBN`；連結文字用 `ProviderDisplayName`；disabled provider 的來源照常顯示（WebIntegration 驗證）。 | ISBN 值依值排序全部顯示、OTHER 不顯示（`BookDetailViewModelTests.Isbn_values_are_all_shown_as_isbn_ordered_by_value`）；只有 Google Books 來源時其為主要按鈕；BookDetailPageTests 擴充；[test-plan §7](../../Docs/testing/test-plan.md) #12、#16 |

已完成的安全外連過濾（668d0fb）、共用登入連結（704c9e8）、從 Controls 推導 InLibrary（0948897）均屬歷史，不列為待修。

相關文件：[流程](workflow-diagram.md) · [架構](architecture.md) · [待辦](backlog.md) · [歷史](update-history.md) · [測試案例](test-suite.md)。
