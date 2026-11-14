# 非同步 AI 推薦 Job（Recommendation Job）實作報告

> 計畫：[Docs/plans/async-recommendation-jobs.md](../plans/async-recommendation-jobs.md)（v1.4）。日期：2026-11-14。
>
> 本報告是實作紀錄，不是規格；current contract 以各模組 `docs/` 為準（AGENTS.md §3.2）。
>
> **production 狀態：尚未部署，也沒有開啟。** 下文「上線手冊」中的 L4 步驟都需要使用者明確授權。

## 變更檔案

| 模組 | PR | 主要檔案 |
|---|---|---|
| M1 Schema | #193（已合併） | `Domain/Entities/RecommendationJob.cs`、`RecommendationJobStatus.cs`；`Infrastructure/Persistence/Configurations/RecommendationJobConfiguration.cs`；migration `20261114032619_AddRecommendationJobs`；compat seed `deploy/migration-test/seeds/20261114032619_AddRecommendationJobs.sql`；計畫文件 |
| M2 用量計數 | #195（已合併） | `Infrastructure/Persistence/EfRecommendationUsage.cs` |
| M3 Pipeline 切分 | #194（已合併） | `Application/Recommendation/RecommendationPipeline.cs`、`RecommendationService.cs` |
| M4 提交與查詢 | #196（已合併） | `IdempotencyKeyRules.cs`、`IRecommendationJobStore.cs`、`RecommendationJobService.cs`、`RecommendationJobReadModels.cs`、`RecommendationJobSubmission.cs`；`Infrastructure/Persistence/EfRecommendationJobStore.cs` |
| M5 Lease store | #197（已合併） | `IRecommendationJobLeaseStore.cs`、`ClaimedRecommendationJob.cs`、`RecommendationJobLeaseLostException.cs`、`RecommendationJobErrorCodes.cs`；`EfRecommendationJobLeaseStore.cs`、`RecommendationSearchRows.cs` |
| M6 Runner＋Worker | #198（已合併） | `RecommendationJobOptions.cs`、`RecommendationJobRunner.cs`；`Infrastructure/BackgroundJobs/RecommendationJobWorker.cs`、`RecommendationJobServiceCollectionExtensions.cs`；`Program.cs`；`appsettings.json` |
| M7 Web | #199（審核中） | `Controllers/RecommendationJobsController.cs`、`AiController.cs`；`Models/RecommendationJobResponse.cs`、`RecommendationJobStatusCodes.cs`、`AiJobListViewModel.cs`、`AiJobViewModel.cs`；`Views/Ai/_AiJobList.cshtml`、`Job.cshtml`、`Index.cshtml`；`wwwroot/js/ai.js`、`ai-job.js`；`Infrastructure/Identity/ApiProblemResults.cs` |
| M8 報告 | 本 PR | 本報告；計畫 v1.4；`deploy/docs` 上線手冊 |

測試：UnitTests、DatabaseIntegration、WebIntegration 各自新增的檔案列在 `tests/docs/update-history.md`。

## 實作思路

- **PostgreSQL 當 queue**：沒有新增任何服務。`recommendation_jobs` 用 CHECK 在資料庫端守住狀態機：只有 `RUNNING` 有 lease；`SUCCEEDED` 必有 Search；`FAILED` 必有 error code。
- **提交**：一筆交易內依序執行：鎖 `users` 那一列 → idempotency 判斷 → 用量計數 → 新增 Job。同一使用者的提交因此依序進行，並行提交不會超出額度，同 key 的重送也不會建立兩筆 Job。
- **額度**（決定 #1、#2）：計數 ＝ 未由 Job 產生的 Search ＋ 非 `FAILED` 的 Job（依提交時間）。新舊兩條路徑共用這個公式。
- **執行**：
  - Worker 一次只執行一筆 Job，每輪先做逾期恢復，再用 `SKIP LOCKED` 領取；
  - heartbeat 每次續租都另開 scope；
  - 每筆 Job 在自己的 scope 執行 Runner；
  - Runner 把 fenced commit 當作 `RecommendationPipeline` 的保存步驟，所以和舊同步路徑一樣在 60 秒預算內完成，逾時語意兩邊相同。
- **Fencing**：除了領取與恢復之外，所有寫入都以 `id + lease_token + RUNNING + lease_expires_at > now()` 為條件，一律使用資料庫時鐘。commit 會先鎖住 Job 列再寫入 Search。
- **前端**：開關控制 Worker 與 `/ai` 走哪條流程。狀態頁在分頁可見時輪詢，進入終態就重新載入，由伺服器輸出最終畫面，文案只寫在 view model 一處。
- **開發方式**：
  - 依賴鏈以外的模組並行開發：M1 與 M3 同時進行；M4 與 M5 同時進行，M5 因此改用獨立的 lease port。
  - Haiku subagent 以 TDD 撰寫程式；主 agent 重跑測試、看 diff、做 mutation 抽查並撰寫 docs。

## 執行紀錄（Log）

- **M1～M3**：M1 與 M3 並行。M3 的設計從計畫原本的「不含保存的 ComputeAsync」改為「接受呼叫端的 save 步驟」（計畫 v1.1）。M1 的 compat seed 在新增 migration 的同一個 PR 提供（DEP-B25 方向 (b)）。
- **M4、M5 並行**：
  - 使用者中途暫停，兩個 subagent 也因用量上限中斷兩次，之後從保存的進度接續。
  - M5 我第一次修測試 warning 時改用 `DBNull`，造成 26 個測試失敗，而且已 commit（`a648a90`）；隨後以有型別的 `NpgsqlParameter` 修正（`48b57e0`）。
- **合併衝突**：
  - M1～M3 合併後，#196、#197 的 docs 與 main 衝突。我第一版的衝突腳本會刪除「另一邊已出現過的行」，結果 #196 遺失了 `- **Then**：` 與一組表頭，M6 分支也遺失類似的行。
  - 我寫了逐段比對的檢查腳本，確認 #196、#197、M6、M7 的 docs 都已完整。#196 以 `e41b7a0` 補回；M6 改採 M4 的完整版本。
- **M6、M7**：subagent 都在完成程式後、commit 之前停下，由我請它們 commit，或接手 commit。
- **M8 本機檢查**：
  - 第一輪瀏覽器檢查 13／15：AI 呼叫每次卡滿 60 秒，兩次執行超過腳本設定的 120 秒等待。
  - 重跑時，我依 PID 檔停止舊網站，但檔案記錄的不是實際行程，舊網站仍佔著 port；啟動腳本 export 的 `HTTPS_PROXY` 又讓健康檢查的 curl 也被擋下，整個流程卡住。
  - 確認後依 PID 停止殘留行程，改寫啟動腳本（檢查 port、確認 PID 是 `Book-Finder.dll`、curl 不走 proxy）。之後 15／15 通過。

## 驗證結果

| 項目 | 結果 |
|---|---|
| `dotnet build --no-incremental` | 0 warning、0 error |
| 完整測試（M7 review 修正後） | UnitTests 984、DatabaseIntegration 249、WebIntegration 337，全數通過 |
| `check_migrations.py --released-manifest`（v0.0.9） | OK（M1 時執行） |
| crawler pytest | 21375 通過（M1 時執行，schema 由含新 migration 的 EF script 建立） |
| `node --check` | `ai.js`、`ai-job.js` 通過 |
| mutation 抽查（主 agent，全部已還原） | M1：outcome CHECK；M2：NOT EXISTS 與 FAILED 排除；M4：`>=` 改為 `>`（subagent 另做 `FOR UPDATE` 移除）；M5：commit 的逾期檢查與 release 的 `attempt_count - 1`；M6：重試上限 `<` 改為 `<=`、heartbeat 被拒時的取消；M7：提交端點的開關判斷、errorCode 只在 FAILED。每一項都有測試失敗 |

**本機瀏覽器檢查**（拋棄式 pgvector、開關開啟；AI 經不存在的本機 proxy 失敗，沒有任何請求送到 OpenAI；Playwright，15／15）：

- 註冊後 `/ai` 的表單帶有 `data-recommendation-jobs="true"`，並顯示空的工作列表；
- 送出後導向 `/ai/jobs/{id}`；URL 不含需求文字；POST 帶有 Idempotency-Key；
- 狀態頁顯示需求與「可以離開網站」；
- 模擬切到背景 7 秒，期間 0 次輪詢；回到前景立刻查詢；
- Job 第 1 次以 `AI_TIMEOUT` 重排，第 2 次失敗；頁面自動重新載入，顯示逾時文案，且沒有結果連結；
- `/ai` 列表顯示「失敗」；未登入的人打開狀態頁會被導向登入。

**故障注入**（同一環境，lease 15 秒、heartbeat 5 秒）：

| 情境 | 結果 |
|---|---|
| FI-1：Job 執行中 `SIGKILL` 網站 | Job 停在 `RUNNING`（attempt 1、lease 仍在）→ 重啟 → lease 逾期後約 1 秒，Worker 記錄 `Recovered 1 …`，Job 帶著 `WORKER_INTERRUPTED` 重新領取（attempt 2）→ 最後 `FAILED`／`AI_TIMEOUT`，沒有超過 2 次 |
| FI-2：Job 執行中 `SIGTERM` 網站 | Job 立刻回到 `QUEUED`，attempt 從 1 退回 0，lease 清除；log 記錄 `released on shutdown` → 重啟後 1 秒內被重新領取（attempt 1） |
| lease 搶佔與 commit 邊界 | 由 DatabaseIntegration `EfRecommendationJobLeaseStoreTests` 涵蓋：恢復後舊 token 的所有寫入都失敗、FK 錯誤時整筆 rollback（INF-T23） |

**沒有驗證**：成功路徑沒有在瀏覽器中用真實 OpenAI 跑過（需要使用者授權）；成功路徑由 WebIntegration 端到端測試以 fake AI 涵蓋。提交 API 的 P95 尚未在 production 量測。

## 未解決事項

1. **開關只能隨 release 改變**：production 的網站設定來自映像檔，host 只注入三個 SSM secret，所以開啟或關閉都要發一個 release（見上線手冊）。如果要能「改設定就重啟」，需要擴充 host 的 env file 機制，那屬於 deploy 的架構變更，需另外決定。
2. **重複的 AI 費用**：at-least-once 執行。當機恢復或重試時，同一個 Job 最多會呼叫 OpenAI 兩次。
3. **資源競爭**：Worker 與 Embedding backfill、Book Profile Worker 共用同一個 web process；開啟後要觀察 CPU、記憶體、DB 連線與 OpenAI rate limit。
4. **M9**：production 驗收後，移除舊的 `POST /api/recommendations` 與開關關閉時的前端分支（決定 #2）。
5. **Job 保留政策**（D-07）：MVP 不刪除。
6. **code review 中判斷為不必修改的 smell**：
   - fencing 條件在 SQL 中重複 5 次；
   - `RecommendationJobSubmission` 與 `JobSubmitOutcome` 逐一對應；
   - error code 使用字串常數；
   - `/ai` 用 `ViewData` 傳遞工作列表；
   - JS 的 401／429／400 處理和同步流程相似。
7. **Worker log 沒有獨立的 `status` 欄位**：結果寫在訊息文字中，可以用 `ErrorCode` 與訊息區分。
8. **網站 E2E 測試仍暫緩**（TEST-B03）：本次的瀏覽器檢查是一次性的，腳本沒有 commit。

## Code Review 與修正

兩軸 review（Standards、Spec 各一個 subagent），範圍是 `80f558b...HEAD`，也就是 M1～M7。每一項都由主 agent 回到程式確認。

**Spec**：沒有阻擋性缺陷。提交順序、領取、fencing、commit 交易、正常停機釋放、Runner 的結果表、舊路徑共用計數、404 規則與前端行為，都已逐項追到程式確認。

| 發現 | 處理 |
|---|---|
| 排隊或執行中的 Job，API 可能回傳上一次的 `errorCode`（§3.7 只在 FAILED 時輸出） | 已修（`142eb8b`）：只有 FAILED 時輸出；新測試在沒有修正時失敗 |
| `ai-job.js` 遇到 401／404 時每 3 秒無限重試 | 已修：停止輪詢並重新載入，交給伺服器顯示登入頁或找不到頁 |
| 開關關閉時，列表、單筆查詢與狀態頁也回 404（§3.7 只寫了 POST） | 保留：符合決定 #4；記入計畫 v1.3 |
| Worker log 沒有 `status` 欄位 | 保留：記入未解決事項 |
| `search_id` FK 為 Cascade；多兩個 CHECK | 保留：Cascade 是為了刪除使用者時不被 FK 擋住（M1 決定）；額外的 CHECK 無害 |

**Standards**：沒有違反文件規範的 hard violation。

| 發現 | 處理 |
|---|---|
| Models 為了使用 `StoredEnum` 引用了 `Infrastructure.Persistence` | 已修：改用 `Models/RecommendationJobStatusCodes`；DatabaseIntegration `StoredEnumTests` 確認兩者一致 |
| `Job.cshtml` 寫死狀態 API 的 URL | 已修：改用 view model 的 `StatusUrl` |
| 其餘 smell（見未解決事項 6） | 判斷為不必修改 |

## 上線手冊

前提：#199（M7）與本 PR 都已合併。每一步都需要使用者執行或明確授權。

1. **部署開關關閉的版本**（L4：production deploy）：
   - 打 tag，CD 部署。這個 release 帶有 migration `20261114032619_AddRecommendationJobs`（只新增資料表），開關為關閉，網站行為與現在相同。
   - 部署前：
     - 在 EC2 執行 `df -h /`（DEP-B24）；
     - plan 應為 `pending` 含 `20261114032619_AddRecommendationJobs`；compat 會載入 `20261114003848_AddCanonicalCategories.sql`。
2. **Smoke**：
   - `/ai` 照常可用，表單帶有 `data-recommendation-jobs="false"`，並以同步流程完成一次推薦；
   - 登入後打開 `/ai/jobs/{任意 GUID}` 應為找不到頁。不要用不帶 antiforgery 的 POST 測試，它會先被 antiforgery 擋下而回 400。
3. **開啟**（L4）：
   - 開一個 PR，在 `deploy/release/compose.prod.yaml` 的 `environment` 加上 `RecommendationJobs__Enabled: "true"`；
   - 合併、打 tag、CD 部署。migration 沒有變動，plan 應為 `in-sync`。
4. **驗收**：
   - 用測試帳號在 `/ai` 送出需求 → 轉到狀態頁 → 關閉分頁 → 稍後回到 `/ai`，從「推薦工作」列表打開 → 「查看推薦結果」；
   - 這一步會呼叫真實 OpenAI，需要使用者當下授權。
5. **觀察**：
   - log 中的 `Recommendation job … succeeded／requeued／failed`、`QueueWaitMs`、`ExecutionMs`、`Recovered … jobs`；
   - EC2 的 CPU、記憶體與 DB 連線。
6. **回退**：
   - revert 步驟 3 的 PR 後重新發布；或以 CD dispatch 重新部署步驟 1 的 release tag（migration 相同，`in-sync`）；
   - 排隊中的 Job 會留在資料庫，下次開啟時繼續執行；
   - 若退回到 M1 之前的 release，舊程式不讀這張表，額度只計算 Search，Job 佔用的額度在回退期間不計入。
7. **M9**：驗收穩定後，移除舊的同步 endpoint 與開關關閉時的前端分支，另開 PR。
