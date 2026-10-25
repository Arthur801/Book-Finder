# 實作報告：金石堂 crawler Phase 2 — 列表頁與詳細頁 parser

> 實作紀錄，不是規格。規格以 `crawler/docs/*`（現行 authority）與 [v11 計畫](../plans/kingstone-category-crawler.md) §3～§4、§9 為準；待辦見 `crawler/docs/backlog.md` CB-07。

## 變更檔案

| 模組 | 分支／commit | 檔案 | 內容 |
|---|---|---|---|
| M1 清單與 URL grammar（#134） | `kingstone-p2-m1-adapter-base` `b4901df`；review 修正 `b5295e9`；已合併 | 新增 `crawler/catalog_core/page_list.py`、`crawler/kingstone/{__init__,models,urls,page_list}.py`、`crawler/kingstone-pages.txt`（只有註解）、測試 `test_catalog_page_list.py`、`test_kingstone_urls.py`、`test_kingstone_page_list.py`；M `crawler/books_crawler/{page_list,normalize,parsers}.py`、`crawler/catalog_core/normalize.py`、`crawler/tests/test_normalize.py` | 共用清單檔 loader（BOM、註解、trim、canonical 去重保留首見、上限、非法行只報檔名與行號）；金石堂 URL grammar（列表頁 canonical、詳細頁 URL、card href 解析）；`ListedItem`、`ListPage` 與兩個例外型別。`sort=sa_desc` 為金石堂預設排序，canonical 時移除，與省略為同一頁。`ROLE_MAP`／`map_contributor_role` 留在博客來 adapter，core 只留 `clean_text`／`normalize_role_label`。博客來 `page_list` 委派共用 loader，對外名稱不變；唯一可見變化是重複 URL 的 INFO log 文字改為 `books.com.tw category 7-day ranking URL` |
| M2 列表頁 parser（#135） | `kingstone-p2-m2-list-parser` `f09967d`；merge M1 `08997c7`；review 修正 `7346aa7` | 新增 `crawler/kingstone/parse_list.py`、`crawler/tests/test_kingstone_parse_list.py`；`7346aa7` 補 architecture、backlog、test-suite（CR-K03）與 update-history | `parse_list_html(html, url) -> ListPage`：商品卡選擇器、48 張上限、空頁判定、`data-prodno` 與連結 km_code 一致、同頁去重；total_pages／total_count 只作 report，格式異常時該欄為 None 並記 WARNING，商品卡照常解析 |
| M3 詳細頁 parser（#136） | `kingstone-p2-m3-detail-parser` `08bc599`；merge M1 `08df52d`；review 修正 `63941b5`、`55b5ee9` | 新增 `crawler/kingstone/parse_detail.py`、`crawler/catalog_core/html_text.py`、`crawler/tests/test_kingstone_parse_detail.py`、`crawler/tests/test_html_text.py`；M `crawler/books_crawler/parsers.py`（行內 helper 改為 import）、`crawler/kingstone/urls.py`（新增 `km_code_from_detail_url`）；`55b5ee9` 補 architecture、backlog、test-suite、update-history | `parse_detail_html(html, url) -> BookDraft`：JSON-LD 身分、soft 404、語言與頁數來自規格表、作者／譯者規則、subjects、description／目錄。`text_with_line_breaks` 從 Books 搬到 `catalog_core/html_text.py`，兩 provider 共用 |
| M4 合併與報告（本 PR） | `593936c` merge M2 進 M4 分支（解 docs 衝突）；本報告 commit | M `crawler/docs/{architecture,backlog,test-suite,update-history}.md`；新增 `Docs/Implementation-Report/kingstone-phase2-adapter.md` | `593936c` 同步 Phase 2 現況；CB-07 狀態改為「Phase 2 完成」並補 Phase 2 待辦；本報告。本 PR 不改任何 `.py` 或測試 |

## 實作思路

- **先抽 core，再寫 adapter**：M1 先做，因為 M2、M3 都依賴 `kingstone` 型別、URL grammar 與 `catalog_core` 的文字規則。
- **M2 與 M3 並行**：兩個分支都從 M1 開出，各自只新增自己的檔案。M3 修改既有檔案的地方只有 `books_crawler/parsers.py`（改為從 `catalog_core.html_text` 匯入）與 `kingstone/urls.py`（新增 `km_code_from_detail_url`）。
- **每個 PR 自帶 docs 與 review 修正**：見執行紀錄的流程教訓。
- **共用 HTML 文字 helper**：M3 把 Books 的 `_text_with_line_breaks` 搬到 `catalog_core/html_text.py`，Books 行為不變（Books 解析測試未改，通過）。金石堂詳細頁的 description 與目錄共用同一規則。
- **列表頁只取身分**：列表頁沒有 ISBN，卡片的書名、作者、出版社與日期也不讀；列表只提供 km_code，詳細頁才是資料來源。
- **詳細頁以 JSON-LD 取身分、以可見結構取其餘**：`sku` 必須等於 URL km_code；語言不用 JSON-LD `inLanguage`（簡體書也標 `zh-TW`），改讀規格表；作者不用 JSON-LD `author`（只有第一個連結），改讀作者列的所有連結。
- **角色前綴不借博客來角色表**：金石堂作者值的 `角色/姓名` 前綴一律對應 `OTHER`（`63941b5`）。E0 只見「審訂/」；出現可對應 Catalog 角色的金石堂標籤時，依 fixture 另加金石堂自己的對應。
- **fail closed**：結構不符即 parse error，不猜測；只有「沒有 Product JSON-LD 且 title 為站名」才是 `ProductNotFound`。損壞的 JSON-LD 不會被當成 soft 404。
- **純函式**：兩個 parser 都不連網、不寫 DB、不記錄 provider 狀態；acquisition、run、ingestion 留到 Phase 3 以後。

## 執行紀錄（Log）

- M1 先行，#134 review 修正 `b5295e9` 後合併；之後才開 M2、M3。
- M2 與 M3 並行開發，M3 分支 merge M1（`08df52d`），M2 分支 merge M1（`08997c7`）。M4 分支 merge M2（`593936c`）時 docs 有衝突，於 merge 時解開。
- **流程教訓**：原本規劃 M2、M3 不寫 docs，由 M4 統一處理，以避免並行衝突。使用者 review #135 後指出，PR 內 docs 仍寫「尚無 parser」，缺 CR-K03 與 update-history，requirement→test traceability 斷掉。改為每個 PR 自帶 docs 與 review 修正，衝突在往前 merge 時解決。
- 原先在 M4 做的 review 修正（`ae0fdfa`）拆回各自 PR：M1 `b5295e9`、M2 `7346aa7`、M3 `63941b5`／`55b5ee9`。舊 M4 分支保留為 `kingstone-p2-m4-superseded`，未 push。
- 驗證數字依序為：M1 修正後 19,883；#135 19,937；#136 20,001；M4 merge 20,055。
- 本 PR 只改文件與本報告，沒有修改任何 `.py` 或測試程式。
- 未讀取 `.env`，未連網，未 push，未修改 `deploy/`、Dockerfile 或 archived root `Docs/`（本報告為新增）。

## 驗證結果

- 完整 pytest（`crawler/`，`../.venv/bin/python -m pytest -q -p no:cacheprovider -rs`）：最後一行 `20055 passed in 81.62s (0:01:21)`，0 skipped（`-rs` 沒有輸出任何 SKIPPED 行）。
- `../.venv/bin/ruff check .`：`All checks passed!`。
- `../.venv/bin/ruff format --check .`：`80 files already formatted`。
- `unicode_tables.py --check`（repo 根目錄，`.venv/bin/python .github/scripts/unicode_tables.py --check`）：`unicode tables OK (3 file(s))`。
- 博客來可見變化：只有重複 URL 的 INFO log 文字（M1）。其餘 Books 行為由既有測試（未改）覆蓋。
- 金石堂 parser 的測試全部離線，使用 E0 的真實 fixture（列表頁 5 份、詳細頁 7 份、soft 404 1 份）與合成 HTML。
- 未執行：真站抓取、Docker build、部署、dotnet build／test。

## 未解決事項

Phase 2 留下的待辦已記入 `crawler/docs/backlog.md` CB-07「Phase 2 留下的待辦」，逐條如下：

- `.productGrid` 內沒有 `data-prodno` 的 `.mod_prod_card` 目前被靜默略過（選擇器要求 `data-prodno`）；E0 fixture 沒有此情形，是否改為 parse error 待定。
- Dockerfile、`.dockerignore` 與 runner 納入 `kingstone/` 留到 Phase 6。
- 金石堂清單讀檔錯誤未經 `books_crawler.redact`（`catalog_core` 不依賴 `books_crawler`；清單讀檔錯誤不含 DSN），Phase 6 runner 整合時再確認 log redact 範圍。
- 詳細頁只讀「作者：」「譯者：」兩種標籤；其他角色標籤（繪者等）出現時再定。
- 角色前綴一律 `OTHER`（E0 只見「審訂/」）；出現可對應 Catalog 角色的金石堂標籤時，依 fixture 加入金石堂自己的對應。
- 作者值含 `/` 一律視為角色前綴（`角色/姓名`）；真實作者名含 `/` 時會被拆錯。E0 沒有此情形，出現時再定規則。
- 規格表「分級」欄（限制級辨識）尚未讀取；E0 的 7 本都是「普通級」，待有限制級 fixture 再定。

review 修正後，文件與程式的差異已消除：TOC 改為「保留出版社原文內容，只做與簡介相同的換行與空白正規化」；totals 改為格式不合記 WARNING 並為 None，不是 parse error。

Phase 3 以後未實作：acquisition（fetch／pacing）、run、ingestion、runner、Dockerfile 納入 `kingstone/`。

## Code Review 與修正

以兩軸 review（Standards：是否符合 repo 文件與程式標準；Spec：是否符合 CB-07 與 v11 計畫）檢查 Phase 2 後，依下表處理。「處理」欄為實際落點的 commit。

| 軸 | 發現 | 處理 |
|---|---|---|
| Standards | `catalog_core/normalize.py` 模組 docstring 寫 clean_text 與角色標籤仍在 `books_crawler.normalize`，已不成立 | `b5295e9`（角色規則移回博客來；core 只留 ISBN、`clean_text`、`normalize_role_label`） |
| Standards | `ROLE_MAP` 註解仍寫「博客來」，但金石堂已使用 | `b5295e9`（ROLE_MAP 移回博客來 adapter） |
| Standards | `crawler/docs/architecture.md` 自相矛盾與過時（catalog_core 列寫「之後 Kingstone 共用」、page_list 列寫「行為與訊息不變」、TOC 寫「原樣保留」） | `55b5ee9`、`7346aa7`（改為現況，補 fail-closed 決定清單） |
| Standards | `update-history.md` Phase 2 列含 merge hash，且缺引言 | `55b5ee9`（移除 merge hash、補引言與本次修正列） |
| Standards | detail URL 的 regex 在 `parse_detail` 與 `urls` 重複 | `55b5ee9`（新增 `km_code_from_detail_url`，`parse_detail` 刪除 `_DETAIL_URL`） |
| Standards | `parse_list._clean` 與 `catalog_core.normalize.clean_text` 重複 | `7346aa7`（刪除 `_clean`，改用 `clean_text`） |
| Standards | `km_code_from_href` 的 query regex 在函式內現場 compile | `55b5ee9`（改為模組層常數 `_QUERY_CHARS`） |
| Standards | `parse_detail` soft-404 分支的區域變數 `title` 與書名同名 | `55b5ee9`（改名 `page_title`） |
| Standards | `_contributors` 中 `label_tag is not None` 為冗餘條件 | `55b5ee9`（迴圈開頭 `if label_tag is None: continue`，行為不變） |
| Standards | `kingstone/page_list` 未傳 logger，重複行 INFO 記在 `catalog_core.page_list` | M4 補修（`kingstone/page_list` 傳入 `kingstone.page_list` logger）：原在舊 M4 修正 `ae0fdfa`，拆回各 PR 時漏搬，撰寫本報告時發現 |
| Standards | `load_url_list` 的 label 參數過多（Data Clumps） | 保留：三個參數保留博客來原本的用語，包成型別沒有減少呼叫端資訊 |
| Standards | `resolve_pages_file` 在兩個 provider 重複 | 保留：僅 3 行，各 provider 預設檔不同 |
| Standards | `_KM_CODE`／`_DIGITS` 等小常數跨模組重複 | 保留：各為一行 regex，抽出只增加耦合 |
| Standards | 金石堂清單讀檔錯誤未經 `books_crawler.redact` | 記入 backlog CB-07 待辦，Phase 6 runner 整合時確認 |
| Spec | totals 格式不合 parse error，違反「只作 report」 | `7346aa7`（改為 None＋WARNING，不回顯 HTML） |
| Spec | 「description、table_of_contents 只供 AI，不公開」遺漏 | `55b5ee9`（補回 architecture） |
| Spec | 譯者列未排除「追蹤」「?」 | `55b5ee9`（與作者欄一致排除，並加合成 HTML 測試） |
| Spec | 括號判斷貪婪且可混用（`(甲)乙(丙)` 被跳過） | `55b5ee9`（只接受成對且內部不含括號的整段；加測試） |
| Spec | 角色前綴（繪者→ILLUSTRATOR）的共用位置 | `63941b5`（金石堂角色前綴一律 OTHER，不借博客來角色表）；`b5295e9` 移回博客來 |
| Spec | 每頁 48 上限、空 grid 為 parse error、同頁去重、JSON-LD image 字串、clean_text、頁碼前導零 | 保留並寫入 architecture 作為 fail-closed／實作決定 |
| Spec | `ListedItem` 無 provider 欄位；`parser.py` 拆成兩檔 | 保留：provider 由 `kingstone` 套件決定，拆檔讓 M2/M3 可並行 |
| Spec | 作者名含 `/` 會被誤拆 | 記入 backlog CB-07 待辦 |
| Spec | 共用重構超出 adapter 範圍 | 保留：計畫 §3 要求共用核心；博客來行為除 log 文字外不變 |
| PR #134 review（P2） | `sort=sa_desc` 與省略是同一頁，但 canonical 未移除 | `b5295e9`（canonical 移除 `sa_desc`；200 頁上限與去重以 canonical 計） |
| PR #134 review（P3） | `ROLE_MAP`／`map_contributor_role` 放在共用 core，角色詞彙不屬共用層 | `b5295e9`（移回博客來，core 只留 `clean_text`／`normalize_role_label`） |
| PR #135 review（P2） | totals 格式異常會讓整頁失敗，違反 report-only | `7346aa7`（格式不合記 WARNING 並為 None，商品卡照常） |
| PR #135 review（P3） | PR 內 docs 仍寫「尚無 parser」，缺 CR-K03 與 update-history；PR 描述過期 | `7346aa7`（補 docs、CR-K03 與 update-history）；PR 描述屬 PR 端內容，不在 repo 範圍 |
