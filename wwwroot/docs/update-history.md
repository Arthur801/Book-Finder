# wwwroot Git 修改歷史

查核基準 `91333c3` 的 source history 如下；`wwwroot/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

> 查核：2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。基準版本靜態證據；本次未執行 build、測試、瀏覽器、網路或發布。文件修正不納入來源歷史。

## 範圍與日期

基準 `91333c3` 可達的全量 wwwroot 非 merge commit，2026-10-11～2026-10-22；排除 wwwroot/docs。日期為 author date，作者為 author；不代表 committer、發布或測試日期。merge 省略避免重複，沒有宣稱分析全部 merge 父線 diff。

```bash
git log --no-merges --reverse --date=short --format="%h|%ad|%an|%s" 91333c3 -- wwwroot ":!wwwroot/docs"
git show --format= --name-status SHA -- wwwroot ":!wwwroot/docs"
git show 66ecf55 f0e1f0f b2c72a0 -- wwwroot/js
```

| Author 日期 | SHA | Author | Subject | 目標內實際檔案 diff 摘要 |
|---|---|---|---|---|
| 2026-10-11 | `eb93cd5` | Arthur801 | Initialize dotnet mvc project | 新增模板 site.js／site.css／favicon 與 vendor lib distribution／maps／licenses（第三方內容不逐檔展開） |
| 2026-10-21 | `7d022b5` | Arthur801 | Add ai.js for the AI recommendation form | A wwwroot/js/ai.js |
| 2026-10-22 | `becc5e2` | Arthur801 | Add Library section to the Book detail page (#11 M4) | A wwwroot/js/library.js |
| 2026-10-22 | `c961620` | Arthur801 | Build the Library login URL once and reuse it in library.js | M wwwroot/js/library.js |
| 2026-10-22 | `66ecf55` | Arthur801 | Add shared library controls to the Book page and /library (#12 M4) | M wwwroot/css/site.css；M wwwroot/js/library.js |
| 2026-10-22 | `ef2b929` | Arthur801 | Show 未評分 next to the stars for an unrated entry | M wwwroot/js/library.js |
| 2026-10-22 | `217e035` | Arthur801 | Point the Library comments at the spec sections that hold the rules | M wwwroot/js/library.js |
| 2026-10-22 | `bd429ea` | Arthur801 | Show the daily-limit message on a 429 from the AI recommendation (#15 M6) | M wwwroot/js/ai.js |
| 2026-10-22 | `852591c` | Arthur801 | Show the AI search history list on /ai (#16 M2) | M wwwroot/css/site.css |
| 2026-10-22 | `f0e1f0f` | Arthur801 | Refresh the AI history list after a successful search (#16 M4) | M wwwroot/js/ai.js |
| 2026-10-22 | `b2c72a0` | Arthur801 | Keep the history list when the refresh is redirected to login (#16 review) | M wwwroot/js/ai.js |

## 已讀重要 diff 與維護轉折

- `66ecf55`：library.js 由 Book 頁加入後重建 markup，改共用 server controls，加入 WeakMap confirmed values、PATCH／DELETE、busy、rollback 與 row empty state；labels 移回 Razor，新增 CSS aria-pressed 星色。
- `f0e1f0f`：推薦 200 後啟動 GET history-list page1，server partial 替換歷史、replaceState 回 /ai；不複製前端 pager。
- `b2c72a0`：修正 fetch 跟登入 redirect 最後 200 的情境，拒絕 redirected 且檢查 ai-history id；舊列表不被 login HTML 取代。此問題已修，現在列回歸案例，不列未完成 bug。

## 目標外依賴與限制

上述 commits 同時涉及 Views、Controller／測試等，這裡只將 wwwroot diff 當直接歷史；API、View DOM、Program 靜態路由是相關依賴現況，沒有全量追蹤它們的歷史。不由 subject 推定 vendor 已升級，也不由程式存在推定 browser 測試或正式發布成功。完整 author／committer 時刻可用 git show --format=fuller SHA。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。
