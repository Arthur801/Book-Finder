# Crawler Git 修改歷史

查核基準 `91333c3` 的 source history 如下；`crawler/docs` 明確排除，不將 PR #100 新增或後續修正的文件 commits 計入 source history。

> 查核 2026-10-24；HEAD `91333c334148fa5bfe07055d0e799dc13bb0bb4e`。依基準版本靜態閱讀；本次未執行 build、測試、部署、外部服務或真實抓取。

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
