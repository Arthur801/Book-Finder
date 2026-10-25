# 金石堂 HTML fixtures

測試不會連線金石堂。這個資料夾存放金石堂的真實頁面，金石堂 parser 與 contract 測試都以此為準；來源契約見 [crawler architecture](../../../docs/architecture.md)「金石堂 source contract」。

## 擷取方式

- 日期：2026-10-25。整次 E0 抓取在 UTC 03:39–03:55（31 次請求，含 robots.txt、首頁與分類樹頁）；本資料夾的頁面在 03:44–03:55 取得，`list_sj_p1.html` 在 review 後於 06:56 以清單格式 URL 補抓（第 32 次請求）。
- 方式：使用者授權的 E0 有限真站抓取。curl_cffi `Session(impersonate="chrome")`、`Accept-Language: zh-TW`、不跟隨 redirect、不登入、不保存 cookie，每次請求前隨機等待 3～30 秒。原始回應與請求紀錄在 `crawler/artifacts/kingstone-e0/raw/`（不 commit）。
- 檔案是回應 body 原樣保存（UTF-8），未移除 `<script>`／`<style>`。列表頁 90–470 KB，大小來自 HTML 標記本身（inline script 約 5 KB）。
- 已檢查：沒有 csrf、session、token、cookie 類的值；頁面是未登入的公開內容，沒有個人資料。

## 目前的 fixtures

| 檔名 | 來源網址 | 涵蓋的情境 |
|---|---|---|
| `list_jdc_p1.html` | `https://www.kingstone.com.tw/book/jdc/?dis=list&page=1` | 現代小說第 1 頁，預設排序（依銷售）；`#allProducts` 內 48 張卡；`共計 4455 筆`、`#totalPages` = 93；區塊外另有輪播卡（要排除） |
| `list_jdc_p1_pu_desc.html` | `https://www.kingstone.com.tw/book/jdc/?dis=list&page=1&sort=pu_desc` | 同一分類依出版日新到舊；48 張卡，出版日遞減 |
| `list_jdc_p93.html` | `https://www.kingstone.com.tw/book/jdc/?dis=list&page=93` | 最後一頁，39 張卡（92×48＋39＝4455） |
| `list_jdc_p94.html` | `https://www.kingstone.com.tw/book/jdc/?dis=list&page=94` | 頁碼超過總頁數：沒有 `#totalPages`、沒有 `.productGrid`，`#displayCSS > .emptyCategory` 顯示「此分類沒有相關商品唷！」；同一個 `#allProducts` 內的巢狀 `section.prodSlider` 有 24 張空狀態推薦卡（不是列表商品），是合法的零列頁 |
| `list_sj_p1.html` | `https://www.kingstone.com.tw/book/sj/?dis=list&page=1` | 小分類（簡體版-文學小說）：6 筆、1 頁（與不帶 query 的 `/book/sj/` 內容相同） |
| `detail_2018630959191.html` | `https://www.kingstone.com.tw/basic/2018630959191/` | 一般書：有目錄、有頁數、單一作者；JSON-LD 出版社尾端有空白 |
| `detail_2018564008187.html` | `https://www.kingstone.com.tw/basic/2018564008187/` | 多冊套書（全二冊）：有 ISBN、沒有目錄 |
| `detail_2018741206573.html` | `https://www.kingstone.com.tw/basic/2018741206573/` | 翻譯書：「譯者：」欄位、作者帶括號原文姓名；JSON-LD `author` 只有作者 |
| `detail_2028594173144.html` | `https://www.kingstone.com.tw/basic/2028594173144/` | 非書商品（學習玩教具）：JSON-LD `isbn` 是一般商品條碼 `4711664071805`；頁數 1 |
| `detail_2018250016458.html` | `https://www.kingstone.com.tw/basic/2018250016458/` | 簡體書：規格表「語言」是中文簡體，但 JSON-LD `inLanguage` 仍是 `zh-TW` |
| `detail_2018630844053.html` | `https://www.kingstone.com.tw/basic/2018630844053/` | 多作者：兩個作者連結，每個連結內用「、」串多人；JSON-LD `author` 只有第一個連結的文字 |
| `detail_2028870033469.html` | `https://www.kingstone.com.tw/basic/2028870033469/` | 角色前綴：作者欄有「審訂/張素惠」；另有譯者 |
| `detail_2099999999999.html` | `https://www.kingstone.com.tw/basic/2099999999999/`（不存在的商品；檔名沿用商品編號，不加情境名稱） | soft 404：HTTP 200、`<title>` 只有「金石堂」、沒有 Product JSON-LD |

沒有 body、只記錄在這裡的回應：

| 請求 | 回應 | 用途 |
|---|---|---|
| `https://www.kingstone.com.tw/book/zzq/`（不存在的分類） | HTTP 302、`Location: /book/`、body 空 | 列表頁 302 → 頁面失敗；測試以 fake response 模擬 |

E0 未觀察到、因此沒有 fixture 的情境：challenge／CAPTCHA、限制級頁、429／5xx、沒有 ISBN 的書、出版日只到年或年月。出現時要先收錄新的 fixture，再定解析與分類規則。

## 之後由程式從這些檔案衍生的負面案例（不需另外保存）

- 移除 Product JSON-LD 的 `sku`，或讓 `sku` 與 URL 的 km_code 不同 → parse error。
- 移除 `name` → parse error；移除 `isbn`／`gtin13`、頁數、目錄、語言列 → 對應欄位為 NULL，不猜測。
- 刪除 `#allProducts` 區塊 → 列表頁 parse error（不是空頁）。
