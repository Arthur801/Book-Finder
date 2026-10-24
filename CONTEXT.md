# 好想找書（Book Finder）

以博客來暢銷榜累積本地書籍資料，讓使用者以一般搜尋或自然語言 AI 推薦找到想讀的書，並管理個人書單。

## 書籍目錄（Catalog）

**Book**／書籍：
系統內一個版本（edition）的書，以內部 ID 識別；外部來源的 ID 只是它的來源識別，不是它本身的 identity。
_Avoid_: 作品（Work）、商品、Volume

**Source Provider**／來源提供者：
一個外部資料來源，例如博客來、Google Books，未來的其他書商或圖書館；以穩定的 code（`BOOKS_COM_TW`、`GOOGLE_BOOKS`）識別，登記在 provider registry。新增書商是新增一筆 provider，不是修改 enum。
_Avoid_: 來源類型（SourceType，舊 enum 名稱）、書商（泛指所有來源時）

**Book Source**／書籍來源：
一本 Book 在某個 Source Provider 上的一筆對應紀錄，例如博客來商品網址或 Google Volume ID。同一本 Book 可以有多個 Book Source，包括同一家書商的多個商品頁。
_Avoid_: 書籍連結、外部書籍

**Book Offer**／來源報價：
某個書商（retailer）Book Source 當下可觀察到的公開售價與供貨狀態；屬於來源，不屬於 Book。目前只有資料表，尚未寫入。
_Avoid_: 書價（當成 Book 屬性時）、價格歷史

**Discovery Job**／探索工作：
crawler 用來找出值得匯入的來源清單的一種方式，例如每日暢銷總榜、分類榜、first-book 診斷；它決定去哪裡找，不決定 Book identity。
_Avoid_: 爬蟲模式（指規則時）、排行榜爬蟲（泛稱時）

**Bestseller**／暢銷榜：
博客來中文書 7 日暢銷總榜目前最新的一份 TOP 100，是由 Catalog 衍生的 projection；它不決定 Book identity，也不控制來源的 `last_seen_at`。系統不保留歷史榜單。
_Avoid_: 排行榜歷史、榜單快照（指歷史時）

**分類榜**／Category Ranking Page：
博客來各分類的 7 日暢銷榜頁面，是一種 Discovery Job 的來源。僅用於補充 Catalog（`crawler.md` §15）；不是 Bestseller，不寫入暢銷榜，也不保存分類排名。
_Avoid_: 分類 Bestseller、分類暢銷榜

## 推薦（Recommendation）

**Candidate Set**／候選集合：
某次 AI 推薦中，系統從本地資料（必要時補上 Google Books 已正規化寫入的書）找出、交給 AI 排序的 Book 集合；AI 只能從中推薦。
_Avoid_: 搜尋結果、候選清單

**Recommendation Search**／AI 搜尋紀錄：
使用者送出的一次自然語言閱讀需求，以及該次產生的推薦結果。
_Avoid_: AI 查詢、搜尋歷史（泛稱時）

**Recommendation Result**／推薦結果：
一次 Recommendation Search 中被推薦的一本 Book，附排序與推薦理由。
_Avoid_: AI 結果

## 個人書單（Library）

**Library**／個人書單：
一位使用者收藏的所有 Library Entry。
_Avoid_: 書櫃、收藏夾

**Library Entry**／書單項目：
使用者收藏的一本 Book，帶有 Reading Status 與可選的評分。
_Avoid_: UserBook（舊類別名稱）、收藏

**Reading Status**／閱讀狀態：
Library Entry 的閱讀進度：想讀（WANT_TO_READ）、閱讀中（READING）、已讀（FINISHED）。
