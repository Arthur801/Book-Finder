# MVP 剩餘工作：實作計劃總覽

> 範圍：#11、#12、#15、#16、#18（#14 Google Books fallback 不在此次範圍）。
> 本目錄是**實作計劃**，不是規格；規格以 `AGENTS.md` §3.2 列出的 authority 文件為準。計劃與規格衝突時以規格為準，並回報衝突。

## 1. 各張票的計劃

| 順序 | Issue | 計劃 | 依賴 |
|---:|---|---|---|
| 1 | #11 加入書單與書單頁 | [issue-11-library-add.md](issue-11-library-add.md) | — |
| 2 | #12 修改閱讀狀態、評分、移除 | [issue-12-library-edit.md](issue-12-library-edit.md) | #11 |
| 3 | #15 每日上限與失敗處理 | [issue-15-daily-limit-failures.md](issue-15-daily-limit-failures.md) | — |
| 4 | #16 AI 搜尋紀錄 | [issue-16-ai-history.md](issue-16-ai-history.md) | — |
| 5 | #18 Book AI Profile 與難度 | [issue-18-ai-profile.md](issue-18-ai-profile.md) | #16 |

為什麼照這個順序：

- #12 直接沿用 #11 建好的 Library 模組。
- #15 與 #16 都會改 `RecommendationService`、`RecommendationsController` 與 `wwwroot/js/ai.js`；循序做可以避免衝突。
- #18 要在 #16 的紀錄詳情頁顯示難度，所以排最後。

## 2. 共通的模組化原則

每份計劃都照同一套原則拆模組：

- **一個模組只做一件事**（高內聚）：例如「解析 PATCH body」與「寫入資料庫」是兩個模組。
- **模組之間只透過小介面溝通**（低耦合）：Application 定義介面（port），Infrastructure 實作；Controller 只做 HTTP 轉換，不放商業規則。
- **純函式優先**：能不碰 DB、HTTP、時間的規則，就做成純函式，用 unit test 驗證。
- **沿用 #13 的分層**：
  - `Application/<領域>/`：服務、規則、port 介面。
  - `Infrastructure/Persistence/`：EF 實作。
  - `Infrastructure/OpenAi/`：所有 OpenAI 程式。
  - `Controllers/`、`Models/`、`Views/`、`wwwroot/js/`：Web 層。
  - `tests/Shared/`：fake 測試替身。

## 3. 共通的實作步驟（每個模組都一樣）

1. 開模組分支 `issue-<N>-m<k>-<name>`（每張票一個 worktree：`~/Documents/vs_repos/Book-Finder-wt/<name>`，建好後 `ln -s ../../Book-Finder/.venv .venv`）。
   - 每張票的 M1 從最新的 `main` 開分支；後面的模組從前一個模組的分支開出（一層疊一層）。
   - **不等前一個 PR 合併**就繼續做下一個模組，不讓 review 卡住實作進度（使用者 2026-10-22 決定）。
   - 下一張票的 M1 若前一張票的 PR 還沒全部合併，就從前一張票最後一個模組的分支開出，同樣疊上去。
2. 主 agent 把該模組的介面、規則、測試清單交給 Haiku subagent，以 TDD 撰寫（先寫失敗測試，再實作）。subagent 只 commit。
3. 主 agent 親自驗收：
   - `dotnet build`（0 warning）。
   - 跑受影響的測試層級（UnitTests / DatabaseIntegration / WebIntegration）。
   - 讀過關鍵程式碼；L3 風險的模組做 mutation 抽查。
4. 主 agent push 分支、開 PR（用 `pr` skill 寫說明）。
   - **每個 PR 的 base 一律設為 `main`**，不設成前一個模組的分支（避免 #17、#13 發生過的「合併進舊 base」問題）。
   - 因為分支是疊起來的，前面的 PR 還沒合併時，後面的 PR 會包含前面模組的 commit。PR 說明開頭註明「包含 #N（尚未合併）」，並列出本模組自己的 commit，方便只看本模組的變更。
   - 前面的 PR 合併後，後面 PR 的 diff 會自動縮小到只剩自己的變更（合併使用 merge commit，不用 squash，否則疊上去的分支會出現重複 diff）。
5. **合併由使用者手動處理**，使用者會依序檢視 PR。主 agent 不合併任何 PR。
   - 如果使用者在 review 中要求修改，就在該模組的分支開新 commit 修正（不 amend），再依序 merge 進後面疊上去的分支並 push（不 rebase、不 force push）。
6. 每張票最後一個模組（Report）：
   - **完整驗證關卡**：`dotnet build`（0 warning）＋ **`dotnet test` 跑完整套測試**（三個測試專案全部通過，各 issue 的 AC 都要求），加上該票需要的瀏覽器手動驗證。開發模組時只跑受影響的測試，關閉 issue 前一定要跑完整套。
   - `code-review` skill 兩軸 review（每項發現親自確認、修正開新 commit）、同步規格文件、寫 `Docs/Implementation-Report/issue-<N>-*.md`、移除 `Docs/TODO.md` 對應項目。

禁止事項照 `HANDOFF.md`：不讀 `.env`、自動測試不呼叫真實 OpenAI、真實試跑需使用者當下授權。
