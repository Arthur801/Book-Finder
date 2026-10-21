# TODO

> 已知暫緩的工作。每項記錄：原本規格、暫緩原因與日期、恢復時要做的事。完成後從此檔移除。

## 登入 / 註冊 Rate Limiting

- **暫緩日期**：2026-10-20（使用者決定，於 #10 實作時）。
- **原本規格**：`Docs/modules/identity-auth.md` §7。登入與註冊 POST 每個 IP 每分鐘 5 次（ASP.NET Core rate limiter，fixed window）；超過回 429，頁面顯示「嘗試次數過多，請稍後再試」，JSON 為 ProblemDetails `/errors/rate-limited`（`Docs/api/api-spec.md` §2）。
- **未完成的驗收條件**：#10「同一 IP 一分鐘內第 6 次登入嘗試回 429」；identity-auth §8 第 9 條。
- **恢復時要做的事**：
  1. 決定登入與註冊是否共用額度，以及成功的嘗試是否計入（#10 規劃時的建議：各自計算、成功失敗都算）。
  2. 以 Forwarded Headers 處理後的 client IP 分組（`Program.cs` 已只信任 loopback proxy，見 `deployment.md`）。
  3. 補 WebIntegration 測試：第 6 次回 429、不同 IP 不互相影響、下一個 window 恢復。
  4. 移除 identity-auth §7 的「暫緩」註記。

## Embedding 補齊：每輪全量讀取

- **暫緩日期**：2026-10-21（#17 實作時，使用者決定）。
- **原本規格**：`Docs/modules/recommendation.md` §10。待補齊的判斷需要比對每本 Book 的 `source_content_hash`，而 hash 只能在 C# 計算，所以每輪會讀取全部 Book 的文字欄位（書名、副標題、簡介、作者、分類）與既有 hash。
- **暫緩原因**：MVP 規模小，全量讀取可接受。但 Catalog 增長後，每 10 分鐘全量讀取會越來越貴。
- **恢復時要做的事**：
  1. 讓每一種 metadata 變更（包括 contributors 與 subjects 的增刪改）都同時更新 `books.updated_at`。這會影響 crawler 與 Google Books normalization（#14）的寫入，需一併檢查。
  2. 改為以 `books.updated_at > book_embeddings.updated_at` 預先篩選，只讀取可能已改變的 Book，再計算 hash 比對。
  3. 補測試：contributors 或 subjects 變更會更新 `books.updated_at`；未變更的 Book 不進入待補齊；`updated_at` 較新但 hash 未變時不重建。
  4. 移除 `recommendation.md` §10 中「MVP 規模下全量讀取可接受」的註記，改為新的篩選規則。

## /ai 頁面的 AI 搜尋紀錄列表

- **暫緩日期**：2026-10-21（#13 M9 文件整理時，使用者決定）。
- **原本規格**：`Docs/ui/ui-flow.md` §3.4（下方紀錄列表；成功後插入最前面）。紀錄列表的資料規則見 `Docs/modules/recommendation.md` §12。
- **暫緩原因**：#13 只做輸入與結果，紀錄列表屬 #16。
- **恢復時要做的事**：
  1. 實作 `/ai` 下方的 AI 搜尋紀錄列表：只列自己的紀錄、`created_at` 新到舊、每頁 20 筆，點擊進入 `/ai/history/{id}`（`recommendation.md` §12）。
  2. 推薦成功後，把這次搜尋插入紀錄列表最前面（ui-flow §3.4）；失敗的推薦不插入。
  3. 補測試：列表只含本人紀錄、排序與分頁、成功後列表更新、失敗時列表不變。
