# 實作報告：Header「更多」選單、分類頁網格與首次造訪導引

> 計畫：[Docs/plans/header-category-onboarding.md](../plans/header-category-onboarding.md)（2026-11-15 使用者核准）。本檔是 implementation record，不是 authority；current contract 以 `Views/docs`、`wwwroot/docs` 等模組文件為準。

| 階段 | 分支 | PR | 狀態（2026-11-15） |
|---|---|---|---|
| P0 計畫 | `ui-plan` | #231 | 已合併 |
| P1 Header「更多」選單 | `ui-p1-header-more-menu` | #232 | 已合併 |
| P2 分類頁搜尋與網格 | `ui-p2-category-grid` | #233 | 已合併 |
| P3 首頁與空書單入口 | `ui-p3-catalog-ctas` | #234 | 待合併 |
| P4 首次造訪導引 | `ui-p4-onboarding` | #235 | 待合併（疊在 #234 上） |
| P5 瀏覽器驗收與報告 | `ui-p5-verification` | #236 | 待合併（疊在 #235 上） |

## 變更檔案

- **Header（P1）**：`Views/Shared/_Layout.cshtml`。左側只剩「分類」「AI 推薦」。右側是「更多」下拉（`#nav-more-menu`），登入時依序為個人書單、MCP 說明、功能導覽、分隔線、登出；匿名時只有 MCP 說明與功能導覽。登出仍是帶 antiforgery token 的 POST 表單。`<noscript>` 備援放個人書單、MCP 說明與第二份登出表單。
- **分類頁（P2）**：`Views/Categories/Index.cshtml` 改成單欄，順序為搜尋、H1、分類網格、書籍來源、結果。新增 `Views/Categories/_CategoryGrid.cshtml`；刪除 `_CategorySidebar.cshtml` 與 `wwwroot/js/category-sidebar.js`；`wwwroot/css/category-browser.css` 改寫為 CSS Grid（2／3／4／6 欄）。
- **入口（P3）**：`Views/Home/Index.cshtml` 改為「瀏覽全部分類」→ `/categories`，`Views/Shared/_LibraryContent.cshtml` 改為「前往分類找書」→ `/categories`。`Application/Catalog` 兩個檔案只改註解（sidebar → 分類網格）。
- **導引（P4）**：新增 `Views/Shared/_Onboarding.cshtml`、`wwwroot/js/onboarding.js`、`wwwroot/css/onboarding.css`。`_Layout.cshtml` 依路由決定是否自動啟動，404 的 `NotFound` view 除外。
- **測試**：`tests/WebIntegration` 的 `NavbarTests`、`LayoutAndHomeTests`、`McpGuidePageTests`、`CategoryPageTests`、`LibraryPageTests`、`HtmlPage`；新增 `OnboardingTests`。`tests/UnitTests/CategoryBrowseViewModelTests` 只改測試名稱。
- **模組文件**：`Views/docs`、`wwwroot/docs`、`Controllers/docs`、`Application/docs`、`Models` 註解、`tests/docs`。新增的案例是 VIEW-T23～T30，backlog 新增 VIEW-B08～B11 與 WB-04。

## 實作思路

- **不動後端 contract**：`/books`、`/books/{id}` 路由與頁面、Controller、Service 與 URL query 都沒有改。只移除導覽入口，並把 CTA 指向 `/categories`。
- **網格資料驅動**：直接渲染 `Model.Categories`，不截斷、不補空格；欄數全由 CSS 斷點決定。
- **導引只在前端**：步驟文字放在 partial 的隱藏 `<ol>`，JS 讀取後依序顯示，不重複文案。狀態只存 localStorage 的 `bf.onboarding.v1.status`，沒有 fetch、表單送出或頁面點擊。「更多」步驟只高亮觸發器，不打開選單，也不碰登出。
- **分工**：主 agent 規劃、合併與驗證；P1～P4 由 Haiku subagent 以 TDD 撰寫。P1 與 P2 平行，P3 與 P4 從 P1＋P2 的合併點平行開出，最後依序合併成 P5。

## 執行紀錄（Log）

1. 依使用者修改（登出移入「更多」）改寫計畫，開 #231。
2. P1、P2 平行實作。兩邊都在 `Views/docs/test-suite.md` 用了 VIEW-T23，於是把 P2 改為 VIEW-T27（`55db078`）。
3. 開 #232、#233。使用者合併 #231、#232，並在 GitHub 上把 main 合進 P2。
4. P3 在 P1＋P2 合併後發現 CAT-08 失敗：P2 的測試斷言整頁沒有 `<noscript>`，但 P1 的 header 有 noscript 備援。兩個 PR 各自都是綠的，合在一起才失敗。#233 的 CI 也因此失敗。改在 P2 只檢查 `<main>` 之後的內容（`4e21229`）。P3 原本用 `HtmlPage.Header()` 的修法（`cd83d86`）在合併時被 P2 的寫法取代。
5. 使用者在 GitHub 解衝突時，`Views/docs/workflow-diagram.md` 的 `/categories` 列只留了 P2 版本，表格中也多出一行空白。補回 P1 的導覽列說明（`267572f`），並刪掉空行（`aa854f5`）。之後使用者合併 #233。
6. P4 的 autostart 依路由判斷，但 404 頁的 controller／action 不變，書籍與分類的 404 會自動彈出導引。先寫失敗測試，再修正（`f1ffe9f`）。
7. 一次性 Playwright 第一輪 76／76。兩軸 review 後修正 4 項（見下），重建環境重跑，80／80。

## 驗證結果

- `dotnet build --no-incremental`：0 warning、0 error（P5 最終 HEAD）。
- `dotnet test tests/UnitTests`：1330 通過。
- `dotnet test tests/WebIntegration`：547 通過（P5 最終 HEAD；P1 單獨 527、P2 單獨 531、P3 531）。
- `dotnet test tests/DatabaseIntegration`：313 通過（P5 最終 HEAD）。
- `node --check wwwroot/js/onboarding.js`：通過；靜態搜尋 `fetch(`、`XMLHttpRequest`、`.submit(`、`.click(` 無匹配。
- **一次性本機 Playwright（Chromium）：80／80**。環境是拋棄式 pgvector 0.8.7-pg17，`manage_categories.py sync --apply` 寫入 18 類與 283 筆 Mapping，另有 85 本假書（其中一類 0 本）；網站以 Development＋HTTPS 啟動，OpenAI 以 proxy 擋下。腳本未 commit，細節見 [Views VIEW-T30](../../Views/docs/test-suite.md)。
  - NAV 16 項：下拉的點擊、Enter、Space、Escape、點外部；手機版 navbar；登入後選單順序；滑鼠登出、只用鍵盤登出、停用 JS 的 noscript 登出。
  - CAT 21 項：320～1440px 共 8 種寬度的欄數與無水平捲動；19 格四列；停用 JS 時網格與來源仍可用。
  - ONB 42 項：首訪、開始、步驟進度、上一步、完成、跳過、重播不覆蓋 completed、focus trap、reduced motion、Escape、手機版 navbar 展開與還原、錨點遺失、storage 被封鎖、敏感頁不自動啟動、全程沒有非 GET 或 `/api/` 請求。

## 未解決事項

- **Browser E2E 進 CI**：依計畫 D8，這次只做一次性本機驗收，沒有常設 suite（tests TEST-B03）。
- **VIEW-B11**：OAuth consent、Email 驗證與重設頁的 autostart=false 只由 Layout 規則推導，沒有 HTML 測試（需要 OAuth 流程或 token）。
- **其他瀏覽器**：沒有驗 Firefox、Safari、真實手機與螢幕報讀器。
- **舊的 sidebar 註解**：`Program.cs`、`Infrastructure/Caching/CachedCategoryBrowse.cs`、`tests/UnitTests/CachedCategoryBrowseTests.cs`、`Infrastructure/docs/architecture.md` 仍寫 sidebar，沒有在本批修改。
- **ID 重複**：計畫的 CAT-01～10 和 `Controllers/docs/test-suite.md` 既有的 CAT-04／05／06／10 編號重複，但內容不同。
- **review 判斷題（未改）**：`OnboardingTests` 的 Regex 沒有放進 `HtmlPage` 共用 helper；`onboarding.js` 有 556 行，比 `ai.js` 大；Layout 寫死 autostart 的路由清單；storage 鍵前綴 `bf.` 與 `ai.js` 的 `bookFinder.` 不一致；`onboarding.js` 同時有 `defer` 和自己處理 `readyState`。

## Code Review 與修正

兩軸 review（範圍 `origin/main...ui-p5-verification`，即 P3～P5）。每一項都由主 agent 讀程式碼確認後才處理。

- **Standards**：
  - 確認並修正：Bootstrap 5 的 Collapse 事件是 `shown.bs.collapse`，原本監聽 `'shown'` 從未觸發，navbar 只靠 400ms 計時器；關閉時 navbar 若還在展開動畫中就不會收回（`09dd106`）。
  - 確認並修正：`OnboardingTests` 檔頭仍寫 browser 案例「still pending」（`09dd106`）。
  - 其餘列在「未解決事項」的判斷題。
- **Spec**：
  - 確認並修正：storage 讀取拋例外時，每頁都會彈出歡迎卡，違反 §5.3「避免因儲存失敗每次開關造成無限彈窗」。改成不自動啟動，仍可從「更多 → 功能導覽」手動開啟（`09dd106`）。
  - 確認並修正：`aria-live` 進度區塊先 `hidden` 再顯示，可能不被朗讀（§5.6）。改成一直存在，只換文字（`09dd106`）。
  - 確認並修正：窄螢幕從 AI 步驟到「更多」步驟之間，navbar 會先收起再展開。改成相鄰步驟的目標都在 navbar 內時保持展開（`09dd106`）。
  - 不改：NotFound 頁沒有「回書庫」連結，McpGuide 也沒有描述 header 位置（P3 已查過）；CTA 文案由 P3 決定；Escape 視為跳過是 §5.6 明定的行為。
- 修正後重跑 OnboardingTests 16／16、WebIntegration 547／547，瀏覽器檢查 80／80。

## 回滾方式

- 只改 Razor、CSS、JS、測試與文件，沒有 migration，也沒有新設定或外部依賴。
- 回滾的方法是 revert 對應 PR 的 merge commit；部署則重新部署前一版。`/books` 路由一直保留，舊連結不受影響。
- 使用者瀏覽器內的 `bf.onboarding.v1.status` 與舊的 `bookfinder.categorySidebarCollapsed` 都只是前端偏好，回滾後不會造成錯誤。
- 上線（打 tag）需另經使用者同意。
