# Bestseller Module

> Path: `Docs/modules/bestseller.md`
> Authority: Bestseller 讀取 contract
> Requirements: BEST-01～04（Web Suspended，2026-10-24）
> 寫入方：crawler（見 `Docs/modules/crawler.md`）；讀取端只讀。

## 1. Scope

- Bestseller backend capability retained; Web presentation suspended（`/bestsellers` 301 → `/books`，2026-10-24）。
- 讀取介面（`IBestsellerReader` / `BestsellerService`）與 cache 保留，目前沒有 Web 呼叫端；由 composition-root guard 測試維持接線（§7）。
- 資料仍由 crawler 維護。production 執行目前因來源阻擋而停用（`CRAWLER_ENABLED=false`，見 `crawler.md`）。

不負責：爬取、Book 詳細頁、推薦。Bestseller 排名不得作為 AI 推薦排序依據（REC-08）。

## 2. 讀取 contract

```text
SELECT rank, book, captured_at
FROM bestsellers JOIN books
ORDER BY rank
```

- 結果依 `rank` 排序，每筆包含 rank、Book 與作者。
- 作者只列 `AUTHOR` 角色，依 `contributor_order`；不含 `ORIGINAL_AUTHOR` 等其他角色（使用者 2026-10-11）。

## 3. 排名缺號

Crawler 跳過的書會使排名缺號（例：36 之後是 38）。

- rank 保留博客來原始排名，不重新編號（BEST-03）。
- `GetTopAsync(n)` 取 rank 排序後的前 n 筆，因此排名有缺號時可能包含 rank n+1 的書（例：rank 5 缺號時 `GetTopAsync(10)` 會回傳到 rank 11）。

## 4. 榜單更新時間

`CapturedAt` 為榜單的擷取時間；同一份榜單所有 row 的 `captured_at` 相同。沒有任何 row 時為 `null`。

## 5. 空狀態

`bestsellers` 沒有任何 row（例：剛部署、crawler 尚未成功過）時，讀取回傳 `CapturedAt = null`、`Entries = []`，不拋出錯誤。「榜單尚未建立」的 Web 呈現已暫停（BEST-04，Web Suspended）。

## 6. Cache

- 整份榜單以 `IMemoryCache` 快取，TTL 1 小時（ADR-005）。
- Crawler 與 Web 沒有 invalidation 通道：crawler 完成後最多 1 小時才會被讀到新榜單，為可接受行為。
- 空榜單也快取，但 TTL 縮短為 5 分鐘，避免部署後首次爬取完成要等滿 1 小時。

## 7. Validation

由 `tests/WebIntegration/BestsellerReaderIntegrationTests.cs` 驗證（DB 整合，經 DI scope 解析 `BestsellerService`，使用真實 PostgreSQL）：

- 依 rank 排序，即使寫入順序不同。
- 有缺號時回傳原 rank，`GetTopAsync` 在缺號時可包含 rank n+1。
- 作者只取 `AUTHOR` 角色，依 `contributor_order`。
- `CapturedAt` 為該份榜單的擷取時間。
- 空表時 `CapturedAt = null`、`Entries` 為空、不拋錯。
