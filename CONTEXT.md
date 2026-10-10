# 好想找書（Book Finder）

以博客來暢銷榜累積本地書籍資料，讓使用者以一般搜尋或自然語言 AI 推薦找到想讀的書，並管理個人書單。

## 書籍目錄（Catalog）

**Book**／書籍：
系統內一個版本（edition）的書，以內部 ID 識別；外部來源的 ID 只是它的來源識別，不是它本身的 identity。
_Avoid_: 作品（Work）、商品、Volume

**Book Source**／書籍來源：
一本 Book 在某個外部來源（博客來、Google Books）上的對應紀錄，例如博客來商品網址或 Google Volume ID。
_Avoid_: 書籍連結、外部書籍

**Bestseller**／暢銷榜：
博客來中文書 7 日暢銷總榜目前最新的一份 TOP 100；系統不保留歷史榜單。
_Avoid_: 排行榜歷史、榜單快照（指歷史時）

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
_Avoid_: UserBook（程式中的舊名稱）、收藏

**Reading Status**／閱讀狀態：
Library Entry 的閱讀進度：想讀（WANT_TO_READ）、閱讀中（READING）、已讀（FINISHED）。
