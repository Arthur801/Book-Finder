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
