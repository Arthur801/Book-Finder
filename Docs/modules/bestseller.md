# Bestseller Module

> Path: `Docs/modules/bestseller.md`
> Authority: Bestseller 讀取與顯示規則
> Requirements: BEST-01～04
> 寫入方：crawler（見 `Docs/modules/crawler.md`）；Web 端只讀。

## 1. Scope

- 讀取目前 Bestseller，供首頁（前 10 名）與暢銷榜頁（全部）使用。

不負責：爬取、Book 詳細頁、推薦。Bestseller 排名不得作為 AI 推薦排序依據（REC-08）。

## 2. 讀取

```text
SELECT rank, book, captured_at
FROM bestsellers JOIN books
ORDER BY rank
```

| 使用處 | 範圍 |
|---|---|
| 首頁 | rank 最小的 10 筆 + 「查看完整榜單」連結 |
| `/bestsellers` | 全部（最多 100 筆），不分頁 |

每筆顯示：排名、封面、書名、作者（`AUTHOR` 角色，依 `contributor_order`），點擊進入 `/books/{id}`。

## 3. 排名缺號

Crawler 跳過的書會使排名缺號（例：36 之後是 38）。

- 依 `rank` 原值顯示，不重新編號（BEST-03）。
- 首頁的「前 10 名」指 rank 排序後的前 10 筆，可能包含 rank 11。

## 4. 榜單更新時間

顯示 `captured_at`（Asia/Taipei，例：`2026-10-11 04:03 更新`）。同一份榜單所有 row 的 `captured_at` 相同。

## 5. 空狀態

`bestsellers` 沒有任何 row（例：剛部署、crawler 尚未成功過）時：

- 首頁與 `/bestsellers` 顯示「榜單尚未建立」。
- 不回錯誤頁；其他功能照常運作。

## 6. Cache

- 整份榜單以 `IMemoryCache` 快取，TTL 1 小時（ADR-005）。
- Crawler 與 Web 沒有 invalidation 通道：crawler 完成後最多 1 小時才顯示新榜單，為可接受行為。
- 空榜單也快取，但 TTL 縮短為 5 分鐘，避免部署後首次爬取完成要等滿 1 小時。

## 7. Validation

- 有缺號時依原 rank 顯示。
- 空榜單顯示空狀態，HTTP 200。
- 首頁取 rank 排序後前 10 筆。
