# 誠品 JSON fixtures

測試不會連線誠品。這個資料夾存放誠品 API 的真實回應，誠品 parser 與 contract 測試都以此為準；來源契約見 [crawler backlog](../../../docs/backlog.md)「CB-08 來源契約（E0 凍結）」。

## 擷取方式

- 日期：2026-11-10 UTC 22:34:57–22:43:39（使用者 2026-11-11 授權的 E0 有限真站抓取，共 25 次請求，上限 60 次）。
- 方式：curl_cffi `requests.get(impersonate="chrome")`、不跟隨 redirect、不登入、不保存 cookie、不帶 Authorization，每次請求前隨機等待 3～10 秒。原始回應與請求紀錄（`requests.jsonl`）在 `crawler/artifacts/eslite-e0/`（不 commit）。全程沒有 429、403、challenge、Retry-After 或 queue-it 排隊頁；回應都經 Cloudflare。
- 檔案是回應 body 原樣保存（UTF-8 JSON），沒有改寫。
- 已檢查：沒有 token、cookie、session、帳號類的值；都是未登入的公開商品資料。

## 為什麼是 JSON 而不是 HTML

`https://www.eslite.com/category/3/101` 與 `https://www.eslite.com/product/<id>` 回傳同一份 14490 bytes 的 Vue SPA 空殼（沒有商品卡、書目欄位、JSON-LD 或內嵌 state），資料由前端從 `https://athena.eslite.com/api/…` 載入。`athena.eslite.com/robots.txt` 為 `User-agent: *` / `Allow: /api/`。使用者在 E0 gate 決定改用 JSON API（計畫 v2）。

## 目前的 fixtures

列表 API：`https://athena.eslite.com/api/v1/categories/<id>/products?page_no=<n>&sort_type=date&sort_order=desc&page_size=40&is_available=true`（前端分類頁使用的參數；`page_size` 前端只用 20 或 40）。

| 檔名 | 請求 | 涵蓋的情境 |
|---|---|---|
| `list_101_p1.json` | 分類 101（中文書 › 語言學習 › 字典）第 1 頁 | `total` 188、40 張卡；guid 長度 16、22、23 混合；卡片沒有 ISBN |
| `list_34_p1.json` | 分類 34（中文書 › 文學館 › 日本文學）第 1 頁 | `total` 1333、40 張卡；翻譯書，`translator` 有值；部分卡的 `category_ids` 另含促銷分類 |
| `list_101_p6.json` | 分類 101 第 6 頁（超過最後一頁 5） | `total` 188、`products` 空陣列：合法的零列頁 |
| `list_9999999_p1.json` | 不存在的分類 9999999 | HTTP 200、`total` 0、`products` 空陣列：與空分類無法區分 |
| `list_28_p1.json` | 第 2 層分類 28（中文書 › 文學館） | HTTP 200、`total` 0：只有第 3 層分類會列出商品 |

詳細 API：`https://athena.eslite.com/api/v4/products/<guid>/description`。

| 檔名 | 涵蓋的情境 |
|---|---|
| `detail_10012016112683201069007.json` | 字典：`isbn13` 空字串、`isbn10` null、`ean` 是 471 開頭的一般商品條碼；作者欄「吳美玉/ 編」帶角色後綴 |
| `detail_1001136502682294792007.json` | 有 `isbn13`／`isbn10`；`translator` 多人「管燕紅/ 梁路/ 朱建中/ 等」；`original_name` 為英文原書名 |
| `detail_1001114412021700.json` | 16 位 guid（舊格式）：`eslite_sn` 不是 guid 的後綴；作者「謝敏華/ Favre, David」；語言 `97:中/英/日 三國語言` |
| `detail_1001124912682006780001.json` | `descriptions` 含「產品目錄」（目錄） |
| `detail_10012030392683263913003.json` | 翻譯小說：作者「遠藤周作」、譯者「林水福」、`original_name`「ちんもく」；`descriptions` 含「作者介紹」 |
| `detail_10019999999999999999999.json` | 不存在的商品：HTTP 404、`{"message":"Product not found","code":"404"}` |

沒有 body、只記錄在這裡的回應：

| 請求 | 回應 | 用途 |
|---|---|---|
| `https://athena.eslite.com/api/v3/products/<guid>` | 價格與圖片服務（可用逗號查多個 ID），不是書目資料；舊 16 位 ID `1002146932202681` 回 `[]` | 不使用 |
| `https://athena.eslite.com/api/v2/search?…` | 以猜測的參數呼叫回 1 byte 非 JSON | 不使用（www 的 `/search` 也被 robots.txt 禁止） |
| `https://athena.eslite.com/api/v1/categories` | 848 KB 分類樹（`id`、`depth`、`description`、`children`） | 只供使用者挑選第 3 層分類，crawler 不使用 |

E0 未觀察到、因此沒有 fixture 的情境：非書商品（`is_book` false／`product_type` 不是 `book`）、電子書、限制級（`restricted` true、規格 `rating` 不是 `N:無`）、429／5xx、queue-it 排隊頁、出版日不是 `T00:00:00.000+08:00` 形式。出現時要先收錄新的 fixture，再定解析與分類規則。
