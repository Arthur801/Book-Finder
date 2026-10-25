# Crawler Git 修改歷史

查核基準 `91333c3` 的 source history 如下；`crawler/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

> 查核 2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。依基準版本靜態閱讀；本次未執行 build、測試、部署、外部服務或真實抓取。

> 2026-10-25（金石堂 E0，CB-07）：實作前 HEAD `590a574`（docs 分支 `docs/kingstone-plan-v10-reconcile`）。使用者授權的有限真站抓取 31 次；新增 13 份金石堂 fixture、architecture 的 source contract 與 CR-K01。本次執行完整 crawler pytest（19684 passed、0 skip，含 DB integration）與 ruff；沒有金石堂程式、沒有部署。

> 2026-10-25（PR4 M2：crawler 只查 `ISBN`，DB integration 在 011 schema 上執行）：實作前 HEAD `6c67e3e`；本次執行 crawler pytest（含 DB integration）、ruff check／format 與 `unicode_tables.py --check`，未執行部署或真實抓取。

> 2026-10-25（#116 phase A、phase B、review 修正、Unicode 15.1 分段 NFKC 與 PR #119 連線重連）：實作前 HEAD `ee29e02`；各階段的 commits 列於文末「#116 phase A」「#116 phase B 與 review 修正」。本次有執行 pytest（DB integration 含）、C# DatabaseIntegration、ruff 與 deploy tests，未執行部署或真實抓取。

## 範圍與方法

涵蓋基準 `91333c3` 可達的全量 crawler 非 merge commit，2026-10-11～2026-10-23；排除 crawler/docs。日期為 author date，作者為 author，非 committer 或部署日期。merge 省略避免重複，不宣稱檢視所有父線 merge diff。

```bash
git log --no-merges --reverse --date=short --format="%h|%ad|%an|%s" 91333c3 -- crawler ":!crawler/docs"
git show --format= --name-status SHA -- crawler ":!crawler/docs"
git show 1d18c25 -- crawler/books_crawler/db.py
git show 0eacb56 -- crawler/books_crawler/run.py
git show 082cd80 -- crawler/deploy/run-crawler.sh
```

下表 subject 僅為識別，路徑欄來自目標內 diff；純文件／fixture／格式修正不視為新 runtime 行為。

| Author 日期 | SHA | Author | Subject | 目標內實際差異檔案 |
|---|---|---|---|---|
| 2026-10-11 | `eb93cd5` | Arthur801 | Initialize dotnet mvc project | A crawler/crawler_books.py |
| 2026-10-11 | `0c0c444` | Arthur801 | Add crawler core without HTML parsers (#6, part 1) | A crawler/.gitignore；A crawler/books_crawler/__init__.py；A crawler/books_crawler/__main__.py；A crawler/books_crawler/cli.py；A crawler/books_crawler/db.py；A crawler/books_crawler/fetcher.py；A crawler/books_crawler/models.py；A crawler/books_crawler/normalize.py；A crawler/books_crawler/parsers.py；A crawler/books_crawler/ranking.py；A crawler/books_crawler/run.py；A crawler/books_crawler/urls.py；A crawler/pytest.ini；A crawler/requirements.txt；R100 crawler/crawler_books.py crawler/tests/__init__.py；A crawler/tests/conftest.py；A crawler/tests/fakes.py；A crawler/tests/fixtures/README.md；A crawler/tests/test_db_integration.py；A crawler/tests/test_fetcher.py；A crawler/tests/test_normalize.py；A crawler/tests/test_ranking.py；A crawler/tests/test_run_unit.py；A crawler/tests/test_urls.py |
| 2026-10-11 | `4f18ccc` | Arthur801 | Add books.com.tw ranking and detail parsers with real fixtures (#6, part 2) | M crawler/books_crawler/cli.py；M crawler/books_crawler/db.py；M crawler/books_crawler/parsers.py；M crawler/books_crawler/run.py；M crawler/tests/fakes.py；M crawler/tests/fixtures/README.md；A crawler/tests/fixtures/detail_0010852315.html；A crawler/tests/fixtures/detail_0011057581.html；A crawler/tests/fixtures/detail_0011062550.html；A crawler/tests/fixtures/detail_0011062863.html；A crawler/tests/fixtures/ranking_books_7d_top100.html；M crawler/tests/test_db_integration.py；A crawler/tests/test_e2e_real_fixtures.py；A crawler/tests/test_parsers_real_fixtures.py；M crawler/tests/test_run_unit.py |
| 2026-10-11 | `995e055` | Arthur801 | Address code review findings (#6) | M crawler/books_crawler/cli.py；M crawler/books_crawler/db.py；M crawler/books_crawler/models.py；M crawler/books_crawler/normalize.py；M crawler/books_crawler/parsers.py；M crawler/books_crawler/ranking.py；M crawler/books_crawler/run.py；M crawler/books_crawler/urls.py；M crawler/requirements.txt；M crawler/tests/conftest.py；M crawler/tests/fakes.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_e2e_real_fixtures.py；M crawler/tests/test_normalize.py；M crawler/tests/test_parsers_real_fixtures.py；M crawler/tests/test_ranking.py；M crawler/tests/test_run_unit.py |
| 2026-10-11 | `9524b6e` | Arthur801 | Add Playwright browser fetcher for the crawler (#24) | A crawler/README.md；M crawler/books_crawler/cli.py；M crawler/books_crawler/fetcher.py；M crawler/requirements.txt；A crawler/tests/test_playwright_fetcher.py |
| 2026-10-11 | `7d2655b` | Arthur801 | Add crawler retry, skip and failure threshold (#7) | M crawler/books_crawler/cli.py；M crawler/books_crawler/db.py；M crawler/books_crawler/models.py；M crawler/books_crawler/ranking.py；M crawler/books_crawler/run.py；M crawler/tests/fakes.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_e2e_real_fixtures.py；M crawler/tests/test_ranking.py；M crawler/tests/test_run_unit.py |
| 2026-10-11 | `c654f1f` | Arthur801 | Address code review findings (#24, #7) | M crawler/README.md；M crawler/books_crawler/cli.py；M crawler/books_crawler/fetcher.py；M crawler/books_crawler/models.py；A crawler/books_crawler/redact.py；M crawler/books_crawler/run.py；M crawler/tests/fakes.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_e2e_real_fixtures.py；M crawler/tests/test_playwright_fetcher.py；M crawler/tests/test_run_unit.py |
| 2026-10-11 | `24ec7d7` | Arthur801 | Switch crawler to curl_cffi, random pacing and consecutive-error abort | M crawler/README.md；M crawler/books_crawler/cli.py；M crawler/books_crawler/fetcher.py；A crawler/books_crawler/first_book.py；A crawler/books_crawler/inspect_page.py；M crawler/books_crawler/models.py；M crawler/books_crawler/parsers.py；M crawler/books_crawler/ranking.py；M crawler/books_crawler/run.py；M crawler/requirements.txt；M crawler/tests/fixtures/README.md；A crawler/tests/test_curl_fetcher.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_fetcher.py；A crawler/tests/test_first_book.py；A crawler/tests/test_first_book_integration.py；M crawler/tests/test_parsers_real_fixtures.py；M crawler/tests/test_playwright_fetcher.py；M crawler/tests/test_ranking.py；M crawler/tests/test_run_unit.py |
| 2026-10-11 | `3dbb9d4` | Arthur801 | Add real restricted-book fixtures for the member gate | M crawler/tests/fakes.py；M crawler/tests/fixtures/README.md；A crawler/tests/fixtures/detail_0011063006.html；A crawler/tests/fixtures/restricted_gate_0011063006.html；M crawler/tests/test_curl_fetcher.py；M crawler/tests/test_e2e_real_fixtures.py；M crawler/tests/test_parsers_real_fixtures.py |
| 2026-10-11 | `d2e67ed` | Arthur801 | Move crawler run accounting into a RunLedger module | A crawler/books_crawler/ledger.py；M crawler/books_crawler/models.py；M crawler/books_crawler/run.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_first_book.py；A crawler/tests/test_ledger.py；M crawler/tests/test_run_unit.py |
| 2026-10-11 | `1d18c25` | Arthur801 | Validate the Bestseller snapshot inside its replacement transaction | M crawler/books_crawler/db.py；M crawler/books_crawler/ledger.py；M crawler/books_crawler/ranking.py；M crawler/books_crawler/run.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_ledger.py；M crawler/tests/test_ranking.py |
| 2026-10-11 | `a22cb17` | Arthur801 | Give the crawler fetcher an honest interface and two real adapters | M crawler/README.md；A crawler/books_crawler/browser.py；M crawler/books_crawler/cli.py；M crawler/books_crawler/fetcher.py；M crawler/books_crawler/inspect_page.py；M crawler/requirements.txt；A crawler/tests/browser_fakes.py；M crawler/tests/fakes.py；A crawler/tests/test_cli.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_fetcher.py；M crawler/tests/test_first_book.py；M crawler/tests/test_playwright_fetcher.py |
| 2026-10-11 | `32f6faf` | Arthur801 | Return classified outcomes from the detail and write steps | M crawler/books_crawler/parsers.py；M crawler/books_crawler/run.py；M crawler/tests/test_first_book.py；M crawler/tests/test_parsers_real_fixtures.py |
| 2026-10-11 | `2deda4e` | Arthur801 | Lock in attempts counts for retries that end in a restricted page or a duplicate | M crawler/tests/test_db_integration.py |
| 2026-10-11 | `e62a898` | Arthur801 | Address code review of the detail outcome refactor | M crawler/books_crawler/run.py |
| 2026-10-12 | `11190ed` | Arthur801 | Test deployment | A crawler/ubuntu@ec2-3-104-177-155.ap-southeast-2.compute.amazonaws.com |
| 2026-10-12 | `c15756c` | Arthur801 | Crawler backup add  pages mode | M crawler/books_crawler/browser.py；M crawler/books_crawler/cli.py；M crawler/books_crawler/fetcher.py；M crawler/books_crawler/inspect_page.py；M crawler/books_crawler/ledger.py；M crawler/books_crawler/models.py；M crawler/books_crawler/normalize.py；A crawler/books_crawler/pages.py；M crawler/books_crawler/run.py；M crawler/books_crawler/urls.py；A crawler/tests/test_run_pages.py |
| 2026-10-12 | `c51a76a` | Arthur801 | Add the category page list file for pages mode | A crawler/books_crawler/page_list.py；M crawler/books_crawler/urls.py；A crawler/category-pages.txt；A crawler/tests/test_page_list.py；M crawler/tests/test_urls.py |
| 2026-10-12 | `0eacb56` | Arthur801 | Run pages mode through PagesLedger with a config-file page list | M crawler/books_crawler/cli.py；M crawler/books_crawler/first_book.py；M crawler/books_crawler/ledger.py；M crawler/books_crawler/models.py；M crawler/books_crawler/pages.py；M crawler/books_crawler/run.py；M crawler/books_crawler/urls.py；M crawler/tests/test_first_book.py；A crawler/tests/test_pages_ledger.py；M crawler/tests/test_run_pages.py |
| 2026-10-12 | `841d121` | Arthur801 | Document pages mode and its category page list | M crawler/README.md |
| 2026-10-12 | `2c03d52` | Arthur801 | Treat an unparseable page list line as a config error | M crawler/books_crawler/urls.py；M crawler/tests/test_run_pages.py；M crawler/tests/test_urls.py |
| 2026-10-12 | `705ac31` | Arthur801 | Keep page list secrets out of the config error log | M crawler/books_crawler/cli.py；M crawler/books_crawler/page_list.py；M crawler/tests/test_run_pages.py |
| 2026-10-12 | `50efa30` | Arthur801 | Name the page in the shared fetch retry messages | M crawler/books_crawler/run.py；M crawler/tests/test_run_pages.py |
| 2026-10-12 | `c93cf27` | Arthur801 | Share the skip log line and counter setup between the ledgers | M crawler/books_crawler/ledger.py；M crawler/tests/test_pages_ledger.py |
| 2026-10-12 | `b4645e8` | Arthur801 | Update module docstrings for pages mode | M crawler/books_crawler/ledger.py；M crawler/books_crawler/run.py；M crawler/books_crawler/urls.py |
| 2026-10-12 | `b0eef11` | Arthur801 | Remove the accidentally committed database dump | D crawler/ubuntu@ec2-3-104-177-155.ap-southeast-2.compute.amazonaws.com |
| 2026-10-13 | `082cd80` | Arthur801 | Deploy crawler with docker | A crawler/.dockerignore；A crawler/Dockerfile；M crawler/README.md；A crawler/deploy/README.md；A crawler/deploy/crawler.conf.example；A crawler/deploy/crawler.cron；A crawler/deploy/crawler.logrotate；A crawler/deploy/run-crawler.sh；A crawler/requirements-runtime.txt；M crawler/requirements.txt；A crawler/tests/test_deploy.py |
| 2026-10-20 | `bed3d29` | Arthur801 | Wrap the page_list import in cli.py | M crawler/books_crawler/cli.py |
| 2026-10-23 | `bde0701` | Arthur801 | style: 新增 ruff 設定並修正 crawler lint 違規 | M crawler/books_crawler/fetcher.py；M crawler/books_crawler/first_book.py；M crawler/books_crawler/run.py；M crawler/requirements.txt；A crawler/ruff.toml；M crawler/tests/conftest.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_deploy.py；M crawler/tests/test_e2e_real_fixtures.py；M crawler/tests/test_fetcher.py；M crawler/tests/test_first_book.py；M crawler/tests/test_first_book_integration.py；M crawler/tests/test_ledger.py；M crawler/tests/test_normalize.py；M crawler/tests/test_page_list.py；M crawler/tests/test_pages_ledger.py；M crawler/tests/test_parsers_real_fixtures.py；M crawler/tests/test_playwright_fetcher.py；M crawler/tests/test_run_pages.py；M crawler/tests/test_run_unit.py |
| 2026-10-23 | `e734f0c` | Arthur801 | style: 以 ruff format 統一 crawler 格式 | M crawler/books_crawler/browser.py；M crawler/books_crawler/db.py；M crawler/books_crawler/ledger.py；M crawler/books_crawler/parsers.py；M crawler/tests/fakes.py；M crawler/tests/test_curl_fetcher.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_deploy.py；M crawler/tests/test_e2e_real_fixtures.py；M crawler/tests/test_fetcher.py；M crawler/tests/test_first_book.py；M crawler/tests/test_first_book_integration.py；M crawler/tests/test_ledger.py；M crawler/tests/test_normalize.py；M crawler/tests/test_page_list.py；M crawler/tests/test_pages_ledger.py；M crawler/tests/test_parsers_real_fixtures.py；M crawler/tests/test_playwright_fetcher.py；M crawler/tests/test_run_pages.py |
| 2026-10-23 | `0e0e7a5` | Arthur801 | fix(test): conftest 產生 EF schema 時提供 placeholder 連線字串 | M crawler/tests/conftest.py |
| 2026-10-23 | `b1c5172` | dependabot[bot] | deps: bump playwright in /crawler in the pip-minor-patch group | M crawler/requirements.txt |
| 2026-10-23 | `485eaad` | Arthur801 | docs: CI 實作報告與 test-plan §6 更新 | M crawler/README.md |
| 2026-10-23 | `dccad53` | Arthur801 | chore(deps): pgvector image 固定為 0.8.7-pg17 | M crawler/tests/conftest.py |

## 重要語意轉折（已讀 diff）

- `1d18c25`：source type／Book ownership 驗證搬入 replacement transaction，先驗證再 DELETE；rank／Book uniqueness 交 schema 與 ledger，新增空 snapshot 與錯 source DB 斷言。不是事前查詢即可保證原子性。
- `0eacb56`：run_pages 改用 PagesLedger、傳入 page_urls；單頁 fetch 耗盡或 ValueError 跳過繼續，不因一般單列失敗整次 FAILED；CLI 清單在 fetcher 建立前驗證。
- `082cd80`：wrapper 新增 flock、SSM 專用 DB secret、env 暫存 cleanup、Docker curl 執行、72 小時狀態與 exit 傳遞。該 diff 只證明程式存在，不證明部署。
- `24ec7d7` 的 commit 與變更範圍顯示 curl、節流、連續錯誤與 first-book 的轉折；後續 ledger／outcome refactor 保留責任分離，不把歷史舊累計限制列為現存 bug。

## Baseline 後 merge-target changes

原始 `91333c3` 表格的 34 筆非 merge crawler source history 保留不變；下表另查核 `91333c3..ce7b4f46c0889db6b10216294cac658136796ad7` 在 `crawler` 路徑的全部 5 筆非 merge 變更，排除 crawler/docs。Target 於 2026-10-24 擷取，日期使用 author 的 Asia/Taipei offset；並非部署或本次測試通過日期。

```bash
git log --reverse --no-merges --format='%H %aI %s' 91333c3..ce7b4f46c0889db6b10216294cac658136796ad7 -- crawler ':(exclude)crawler/docs'
git show d724d12 -- crawler/deploy/run-crawler.sh crawler/tests/test_deploy.py
git show ce7b4f46c0889db6b10216294cac658136796ad7:crawler/deploy/run-crawler.sh
git show ce7b4f46c0889db6b10216294cac658136796ad7:crawler/tests/test_deploy.py
```

| Author 日期／SHA | 目標內變更及查核結果 |
|---|---|
| 2026-10-23／`d724d1294c00ba9a807a6261b6bdb5a021d14100` | `feat(deploy): crawler waits for the maintenance lock and skips while paused or dirty (N3) (#92)`；已讀 wrapper 與 test_deploy diff。共用 crawler run.lock 後先取 maintenance shared lock、再讀 state；容器期間持鎖；timeout exit3，paused／dirty exit6，state 讀取失敗 exit2 fail closed，absent state 向後相容；新增對應來源測試。 |
| 2026-10-23／`a17d415c6c158cc9616acff5a6eca364af3bccf8` | crawler/deploy/README 改為 GHCR、CD-managed digest，補 shared maintenance lock／state gate 的運行與部署政策；不是新增 crawler parser 行為。 |
| 2026-10-24／`bda4ebdd053063445000c1d0a8b866dbedac149d` | crawler/deploy/README 釐清 staging tag → attestation → release tag commit point → digest confirmation 的發布順序。 |
| 2026-10-24／`3dd0c137d9a9b51318776a3347278409f5a064a3` | crawler.conf.example 改用 `ghcr.io/...@sha256:<digest>`，明示 image 由 CD 改寫；不是部署完成證據。 |
| 2026-10-24／`4a7c06024c9e78356be886395a7461b7e8ce651b` | crawler/deploy/README 說明 `<digest>` 是待替換的 placeholder；該 commit subject 的 status exit0 是目標外 host 語意，不誤歸 crawler wrapper。 |
| 2026-10-25 | `aa792bf` | fix(catalog): pin ISBN NFKC to Unicode 15.1 independent of the runtime | `books_crawler/unicode_15_1.py`（新增，由 `.github/scripts/unicode_tables.py` 產生；`ASSIGNED_RANGES` 與 `is_assigned`；PR3 才會使用） |

Workflow／architecture／CR-T12 的 host 現況引用 [target wrapper](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/deploy/run-crawler.sh) 與 [target tests](https://github.com/Arthur801/Book-Finder/blob/ce7b4f46c0889db6b10216294cac658136796ad7/crawler/tests/test_deploy.py)；PR 分支未合併 target 程式，不以舊 wrapper 的相對連結冒稱 N3 已在該分支實作。合併後若 target 再演進，需重查這個固定 snapshot；以上兩段歷史都排除 PR #100 的文件 commits。

## 相關依賴與限制

`dccad53`（2026-10-23，Arthur801）同時改 compose、EF integration 與 crawler conftest 的 pgvector image 字串為 0.8.7-pg17；crawler 自己不遷移 schema。資料契約／部署規格的外部歷史未做全量追蹤。完整 author／committer 時刻可由 git show --format=fuller SHA 查；沒有從日期推斷發布成功或測試通過。

相關：[流程](workflow-diagram.md)／[架構](architecture.md)／[待辦](backlog.md)／[歷史](update-history.md)／[案例](test-suite.md)。

## #116 phase A（2026-10-25）

| Author 日期 | SHA | Author | Subject | 目標內實際差異檔案 |
|---|---|---|---|---|
| 2026-10-25 | `0149b69` | Arthur801 | feat(crawler): split outcomes into CatalogResolution and RankingDecision | M crawler/books_crawler/ledger.py；M crawler/books_crawler/models.py；M crawler/books_crawler/run.py；M crawler/tests/test_ledger.py；M crawler/tests/test_pages_ledger.py；M crawler/tests/test_run_pages.py；M crawler/tests/test_run_unit.py；M crawler/tests/test_db_integration.py；M crawler/tests/test_first_book.py |
| 2026-10-25 | `448571e` | Arthur801 | feat(crawler): run first_book manually through run-crawler.sh | M crawler/deploy/run-crawler.sh；M crawler/tests/test_deploy.py |
| 2026-10-25 | `ad82318` | Arthur801 | docs(crawler): renumber crawler.md citations to the current spec | M crawler/books_crawler/*（docstring 與 cli TODO）；M crawler/tests/*（docstring） |

行為轉折：榜內重複不再於寫入前跳過，改由 `RunLedger` 決定；DB integration 中該 rank 的 Source 現在會存在（Catalog 側已 commit）。

## #116 phase B 與 review 修正（2026-10-25）

| Author 日期 | SHA | Author | Subject | 目標內實際差異檔案 |
|---|---|---|---|---|
| 2026-10-25 | `861c334` | Arthur801 | feat(crawler): phase B identity, ISBN matching, touch and provider gate | M crawler/books_crawler/{cli,db,models,normalize,run}.py；A crawler/books_crawler/identity.py；M crawler/tests/{test_cli,test_db_integration,test_e2e_real_fixtures,test_first_book,test_first_book_integration,test_normalize,test_parsers_real_fixtures,test_run_pages,test_run_unit}.py；A crawler/tests/{test_identity,test_isbn_fixture}.py |
| 2026-10-25 | `75b8aab` | Arthur801 | docs(crawler): sync phase B docs and spec implementation status | M crawler/README.md；M crawler/docs/*；M Docs/data/data-model.md §14；M Docs/modules/crawler.md §2 |
| 2026-10-25 | `1051d6e` | Arthur801 | fix(crawler): review fixes for identity logging, provider constant and docstrings | M crawler/books_crawler/{db,identity,ledger,models,cli,run}.py；M crawler/tests/{test_identity,test_run_pages,test_first_book}.py |
| 2026-10-25 | `0fa845d` | Arthur801 | docs: remove stale pre-#116 statements and document provider read exits | M Docs/data/data-model.md；M Docs/modules/crawler.md；M crawler/README.md；M crawler/docs/{architecture,test-suite}.md |
| 2026-10-25 | `0d3e28f` | Arthur801 | test(recommendation): field-sensitive stale detection after a NULL fill | A tests/DatabaseIntegration/EfStaleDetectionTests.cs；M crawler/docs/test-suite.md |
| 2026-10-25 | `118eb5b` | Arthur801 | feat(crawler): pin ISBN NFKC to Unicode 15.1 with segmented runs | M crawler/books_crawler/{normalize,cli}.py；A crawler/books_crawler/unicode_15_1.py（由 `.github/scripts/unicode_tables.py` 產生）；A crawler/tests/test_unicode_nfkc_conformance.py |
| 2026-10-25 | `38c2bb9` | Arthur801 | docs(crawler): record Unicode 15.1 NFKC pinning in architecture, tests and history | M crawler/docs/{architecture,test-suite,update-history}.md |
| 2026-10-25 | `d8e5915` | Arthur801 | fix(crawler): reconnect a broken database connection inside the retry budget | A crawler/books_crawler/session.py；M crawler/books_crawler/run.py；A crawler/tests/{test_session,test_reconnect_integration}.py；M crawler/tests/test_first_book.py |
| 2026-10-25 | `a17da36` | Arthur801 | docs(crawler): specify the reconnect rule and document its tests | M Docs/modules/crawler.md；M crawler/docs/{architecture,workflow-diagram,test-suite}.md |
| 2026-10-25 | `868ba40` | Arthur801 | test(crawler): assert the migration 011 schema in DB tests | M crawler/tests/{test_db_integration,test_e2e_real_fixtures,test_run_pages}.py |
| 2026-10-25 | `f92a63d` | Arthur801 | feat(crawler): match distinct Books on the ISBN type only | M crawler/books_crawler/{models,db,run}.py；M crawler/tests/test_normalize.py |
| 2026-10-25 | 本次 backlog 整理 commit | Arthur801 | docs(backlog): tidy crawler backlog after #113 PR3–PR4 | `docs/backlog.md`：CB-01、CB-04、CB-05、CB-06 移至「已處理」；CB-03 補記 production 與 schema 狀態；補記標頭；未改程式 |
| 2026-10-25 | `a386144` | Arthur801 | test(kingstone): add E0 list and detail fixtures and the source contract | A crawler/tests/fixtures/kingstone/（README＋13 份 HTML）；M `docs/architecture.md`（金石堂 source contract） |
| 2026-10-25 | `81cd973` | Arthur801 | test(kingstone): pin the E0 fixture contract | A crawler/tests/test_kingstone_fixture_contract.py（59 個測試） |
| 2026-10-25 | `e6f2b3f` | Arthur801 | docs(crawler): record Kingstone E0 in backlog, tests and history | `docs/backlog.md` CB-07；`docs/test-suite.md` CR-K01；本表 |
| 2026-10-25 | `84451bf` | Arthur801 | test(kingstone): apply review fixes to the E0 fixtures and contract test | 兩軸 review 修正：`list_sj_p1.html` 以清單格式 URL 重抓（第 32 次請求）、soft 404 改名 `detail_2099999999999.html`、subjects 去掉「中文書」、補 title／image／分級／breadcrumb／卡片無 ISBN 測試（共 92 個） |
| 2026-10-25 | `b8dfd46` | Arthur801 | docs(crawler): move the Kingstone source contract to backlog CB-07 | 使用者決定：未實作的契約不放 current-state 的 `docs/architecture.md`，移到 `docs/backlog.md` CB-07；architecture 只留指向；test-suite、fixture README 與測試 docstring 的參照同步 |
| 2026-10-25 | `90b6096` | Arthur801 | refactor(crawler): extract the provider-neutral catalog_core package | A crawler/catalog_core/{__init__,models,normalize}.py；R crawler/books_crawler/{identity,unicode_15_1}.py → crawler/catalog_core/；M crawler/books_crawler/{models,normalize,cli,parsers,db,run}.py；M crawler/Dockerfile、crawler/.dockerignore；M `.github/scripts/unicode_tables.py`；測試 import 與 caplog logger 同步；無行為變更 |
| 2026-10-25 | `0274629` | Arthur801 | feat(crawler): provider-explicit catalog persistence with a monotonic touch | A crawler/catalog_core/persistence.py、crawler/tests/test_persistence_integration.py；M crawler/catalog_core/models.py（BookDraft.external_id）；M crawler/books_crawler/{db,run,cli}.py；M crawler/tests/（呼叫端與 fake 簽章同步）；M `docs/architecture.md`、`docs/workflow-diagram.md`、`docs/test-suite.md`（CR-T16）；Books 行為變更：touch 單調（GREATEST）、限 provider，Source 不存在為 source_identity_conflict 跳過 |
| 2026-10-25 | `173eaf9` | Arthur801 | feat(crawler): provider-neutral catalog item resolution service | A crawler/catalog_core/service.py、crawler/tests/test_catalog_service.py |
| 2026-10-25 | `c9c7d4d` | Arthur801 | refactor(crawler): resolve Books rows through the catalog service | R crawler/books_crawler/session.py → crawler/catalog_core/session.py；A crawler/catalog_core/store.py；M crawler/catalog_core/service.py（ItemFailed.identity_warning；touch 衝突訊息與 persistence 一致）；M crawler/books_crawler/run.py（`_resolve_row` 改為 adapter，刪除 `_touch_with_retries`、`_write_new_source`、`_WriteFailure`、`_WrittenSource`）；M crawler/tests/test_session.py（import）、crawler/tests/test_catalog_service.py；M `docs/architecture.md`、`docs/workflow-diagram.md`、`docs/test-suite.md`（CR-T17）；無 Books 行為變更 |
| 2026-10-25 | `13559d2` | Arthur801 | fix(crawler): apply the Phase 1 review to catalog_core and its tests | M crawler/catalog_core/session.py（logger 改為 `catalog_core.session`）；M crawler/catalog_core/persistence.py（模組 docstring：決策屬 `catalog_core.service` 與 `identity`）；M crawler/books_crawler/run.py（`_BooksCatalogStore` docstring 只描述現況；ISBN 清單 join 只保留一份 `isbn_text`）；M `docs/test-suite.md`（CR-T16 排在 CR-T17 前；新增 touch uncertain ACK 與時鐘倒退的 Books 測試來源）；M crawler/tests/test_reconnect_integration.py（新增 `test_a_touch_commit_whose_acknowledgement_is_lost_is_idempotent_on_retry`）；M crawler/tests/test_db_integration.py（新增 `test_a_clock_moved_back_keeps_a_later_last_seen_and_the_source_is_still_existing`）；無 production 行為變更 |
| 2026-10-25 | `3192e39` | Arthur801 | docs: record Kingstone Phase 1 in the report and backlog | A Docs/Implementation-Report/kingstone-phase1-core.md；`docs/backlog.md` CB-07：Phase 1 完成與後續待辦；本表填入 Phase 1 各 commit 的 hash |
| 2026-10-25 | `3979bcd` | Arthur801 | fix(crawler): stop at a conflict found after an uncertain commit | M crawler/catalog_core/service.py（commit 不確定後重新解析得到 CONFLICT 即以 `source_identity_conflict` 結束）；M crawler/tests/test_catalog_service.py（+1） |
| 2026-10-25 | 本次 commit | Arthur801 | docs(crawler): record the conflict stop after an uncertain commit | `docs/architecture.md` service 列、`docs/test-suite.md` CR-T17、實作報告 |
| 2026-10-25 | `b4901df` | Arthur801 | feat(kingstone): page list, URL grammar and the shared list loader | A crawler/catalog_core/page_list.py、crawler/kingstone/{__init__,models,urls,page_list}.py、crawler/kingstone-pages.txt（只有註解）、crawler/tests/test_catalog_page_list.py、test_kingstone_urls.py、test_kingstone_page_list.py；M crawler/books_crawler/page_list.py（委派核心 loader；檔案規則與 Books 錯誤訊息不變，重複行的 INFO log 文字改為 `books.com.tw category 7-day ranking URL`）；M crawler/books_crawler/normalize.py、crawler/catalog_core/normalize.py（`clean_text`、`normalize_role_label`、`map_contributor_role` 與角色表移入）；M crawler/books_crawler/parsers.py、crawler/tests/test_normalize.py（僅 import 行）；M `docs/architecture.md`、`docs/test-suite.md`（CR-K02、核心 loader 測試來源）、本表 |
| 2026-10-25 | `b5295e9` | Arthur801 | fix(kingstone): canonicalize the default sort and keep role labels in the Books adapter | M crawler/kingstone/urls.py（`sa_desc` canonical 時移除，`DEFAULT_SORT`）、crawler/kingstone-pages.txt（註解）；M crawler/catalog_core/normalize.py（移除 `ROLE_MAP`、`map_contributor_role`；只留 ISBN 與 `clean_text`／`normalize_role_label`）；M crawler/books_crawler/normalize.py（角色表與 `map_contributor_role` 移回，改用 core 的 helper）；M crawler/books_crawler/parsers.py、crawler/tests/test_normalize.py（import 行還原為 M1 之前的寫法，另加 core 邊界測試）；M crawler/tests/test_kingstone_urls.py、test_kingstone_page_list.py（sa_desc 測試；原 sa_desc 保留的斷言改為非預設 key）；M `docs/architecture.md`、`docs/backlog.md`（CB-07 URL grammar）、`docs/test-suite.md`（CR-K02）、本表 |
| 2026-10-25 | `f09967d` | Arthur801 | feat(kingstone): parse category list pages（#135） | A crawler/kingstone/parse_list.py（`parse_list_html` → `ListPage`）、crawler/tests/test_kingstone_parse_list.py |
| 2026-10-25 | `08bc599` | Arthur801 | feat(kingstone): parse product detail pages（#136） | A crawler/kingstone/parse_detail.py（`parse_detail_html` → `BookDraft`）、crawler/catalog_core/html_text.py（`text_with_line_breaks` 自 `books_crawler/parsers.py` 原樣搬出）、crawler/tests/test_kingstone_parse_detail.py、test_html_text.py；M crawler/books_crawler/parsers.py（改 import 共用 helper，行為不變，Books 測試未改） |
| 2026-10-25 | `63941b5` | Arthur801 | fix(kingstone): map role prefixes with Kingstone's own rule | M crawler/kingstone/parse_detail.py（不借用博客來角色表：無前綴作者 AUTHOR、譯者 TRANSLATOR、任何 `角色/` 前綴 OTHER）；M crawler/tests/test_kingstone_parse_detail.py |
| 2026-10-25 | `7346aa7` | Arthur801 | fix(kingstone): keep report-only list totals from failing the page（#135 review） | M crawler/kingstone/parse_list.py（totals 格式異常改為 None＋WARNING，不再 parse error；改用共用 `clean_text`）；M crawler/tests/test_kingstone_parse_list.py（totals 降級與 WARNING、兩者同時異常仍完整解析）；M `docs/architecture.md`（`kingstone/parse_list` 列與「金石堂 adapter」列表頁段落）、`docs/backlog.md`（CB-07 列表頁解析改指向 architecture）、`docs/test-suite.md`（CR-K03）、本表 |
| 2026-10-25 | `55b5ee9` | Arthur801 | fix(kingstone): detail parser review fixes and docs | M crawler/kingstone/urls.py（新增 `km_code_from_detail_url`；query 字元集共用常數）；M crawler/kingstone/parse_detail.py（改用 `km_code_from_detail_url`；譯者列排除「追蹤」「?」；原文名括號須成對且內部無括號；`page_title` 改名；`label_tag is None` 早退）；M crawler/tests/test_kingstone_{urls,parse_detail}.py；M `docs/architecture.md`（模組列與「金石堂 adapter」詳細頁段落）、`docs/backlog.md`（CB-07 詳細頁解析改指向 architecture、詳細頁待辦）、`docs/test-suite.md`（CR-K04、CR-T18）、本表 |
| 2026-10-25 | `82ccde3` | Arthur801 | fix(kingstone): log page list duplicates under kingstone.page_list | M crawler/kingstone/page_list.py（傳入 `kingstone.page_list` logger，重複行 INFO 不再記在 `catalog_core.page_list`；Phase 2 review 項目，拆回各 PR 時漏搬）；M crawler/tests/test_kingstone_page_list.py（caplog 改綁 `kingstone.page_list`）；M `docs/architecture.md` |
| 2026-10-25 | `3dad48d` | Arthur801 | feat(kingstone): bounded, paced HTTP acquisition with URL guards | A crawler/kingstone/acquisition.py（Transport port、CurlTransport、KingstoneFetcher）；A crawler/tests/test_kingstone_acquisition.py；M crawler/docs/architecture.md（模組列與「金石堂 adapter」Acquisition 段落）、backlog.md（CB-07 Phase 3 狀態與待辦）、test-suite.md（CR-K05）、本表 |
| 2026-10-25 | `ea95214` | Arthur801 | docs(crawler): the Kingstone source contract no longer says there is no code（#137 review） | `docs/backlog.md`「CB-07 來源契約」標題與前言：已實作部分以 architecture 為 authority，run／ingestion／runner 仍依本節；`docs/test-suite.md` CR-K01 不再寫「尚無金石堂程式」 |
| 2026-10-25 | `a9a4c20` | Arthur801 | fix(kingstone): check the budget before every request and cap the body in libcurl（Phase 3 review） | M crawler/kingstone/acquisition.py（每次請求前檢查 budget；`MAXFILESIZE_LARGE` 與 code 63 映射；移除 IP literal 判斷，改用 `SITE_HOST`；Retry-After 數字分支簡化；OVERSIZE helper；docstring 等待規則）；M crawler/kingstone/urls.py（新增 `SITE_HOST`）；M crawler/tests/test_kingstone_acquisition.py（+9 測試，共 96）|
| 2026-10-25 | `02e257a` | Arthur801 | docs(crawler): record the Phase 3 review fixes（architecture 還原列表頁與詳細頁段落、acquisition 段落精確化、backlog Phase 3 待辦、test-suite CR-K05、本表）| M crawler/docs/{architecture,backlog,test-suite,update-history}.md；A Docs/Implementation-Report/kingstone-phase3-acquisition.md |
| 2026-10-25 | `4dc97fb` | Arthur801 | docs(kingstone): Phase 3 is core acquisition only until diagnostics land（#138 review） | `docs/backlog.md` CB-07 狀態與 Phase 3 待辦、`docs/architecture.md` Acquisition「不在本層」、Phase 3 實作報告：有限額診斷（`KINGSTONE_DIAGNOSTIC_MAX_BYTES`）未實作，Phase 3 改稱 core acquisition 完成，診斷留待 Phase 6 |
| 2026-10-25 | `d248991` | Arthur801 | docs(crawler): record the Phase 3 status correction in update-history | 本表（`4dc97fb` 列、`02e257a` hash） |
| 2026-10-25 | `4b8f73f` | Arthur801 | feat(kingstone): run config and the run ledger with one terminal status rule（Phase 4 M1） | A crawler/kingstone/config.py、A crawler/kingstone/ledger.py、A crawler/tests/test_kingstone_config.py、A crawler/tests/test_kingstone_ledger.py；M crawler/kingstone/acquisition.py（`KingstoneFetcher` 新增 timeout、max_attempts、max_response_bytes；`CurlTransport` 新增 max_response_bytes）；M crawler/tests/test_kingstone_acquisition.py（+10 測試，共 106）；M crawler/docs/{architecture,backlog,test-suite,update-history}.md（CR-K05 補充、新增 CR-K06、CR-K07） |
| 2026-10-25 | 本次 commit | Arthur801 | feat(kingstone): page-by-page run with budget stop and replay（Phase 4 M2） | A crawler/kingstone/run.py、A crawler/catalog_core/redact.py、A crawler/tests/test_kingstone_run.py；M crawler/docs/{architecture,backlog,test-suite,update-history,workflow-diagram}.md |

行為轉折：ISBN 不再驗證 checksum，所有非空正規化值都以 `ISBN` 寫入；既有 Source 每次出現都更新 `last_seen_at`；`replace_bestsellers` 不再更新 `last_seen_at`；停用的 provider 以 exit 2 拒絕執行。新 DB 測試依 migration 010 的 trigger 驗證 `source_type = source_code`。
