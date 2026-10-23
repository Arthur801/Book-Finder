# Issue #101：CRAWLER_ENABLED 開關（EC2 被博客來擋下時停用排程）

## 變更檔案

- `crawler/deploy/run-crawler.sh`：在 `source` 與必要變數檢查之後、建立目錄／取得 lock／讀取 state／呼叫 aws 或 docker 之前，加入 `CRAWLER_ENABLED` 判斷。
- `crawler/tests/test_deploy.py`：新增 `CRAWLER_ENABLED` 測試；`aws` stub 記錄呼叫到 `AWS_CALLS`，用來證明停用時不讀取 SSM。
- `deploy/tests/host/test_machine.py`：`rewrite_crawler_image` 的 byte-identical 測試與 `crawler.conf` 改寫測試加入 `CRAWLER_ENABLED=false` 行。
- `crawler/deploy/crawler.conf.example`：加入 `CRAWLER_ENABLED=true` 與說明。
- `crawler/deploy/README.md`：設定表新增一列；新增 §5.1「暫停排程（不影響部署）」。
- `deploy/README.md`：§3.1 新增第 5 點（bootstrap 前設定）；§7.2 新增第 19 列（EC2 被博客來擋下）。
- `Docs/deployment/deployment.md`：§8 新增一句指向開關。

## 實作思路

- 判斷位置：`source` 之後、`mkdir` 之前。停用時不建立目錄、不取得 maintenance lock、不讀 state、不呼叫 SSM／docker，也不更新 `pages-last-success`。
- 判斷語法：`case "${CRAWLER_ENABLED-true}"`。
  - 未設定（`-` 而非 `:-`）→ 視為 `true`，行為與修改前相同。
  - `true` → 繼續執行。
  - `false` → 輸出 `$(date -u +%FT%TZ) mode=$mode skipped=disabled` 到 stdout，exit 0。
  - 其他值 → stderr 說明變數名稱與允許值，exit 2。
- 為什麼不用 paused：paused 會讓 CD 部署被拒絕（exit 3），且 bootstrap 仍要求 `crawler.cron` 存在。
- 為什麼跨部署保留：CD 只改寫 `CRAWLER_IMAGE=` 那一行（`rewrite_crawler_image`），其餘行逐位元組保留。

## 決策：空字串

`CRAWLER_ENABLED=`（空字串）視為**無效**，exit 2，不視為未設定。理由：空值多半是編輯錯誤（例如 `CRAWLER_ENABLED=` 被誤刪值），若當成 `true` 會靜默忽略操作者的意圖；若當成未設定，又與「沒寫」無法區分。測試 `test_crawler_enabled_rejects_invalid_values[]` 涵蓋此行為。`no`、`False`、`TRUE`、`1` 也都以 exit 2 拒絕（區分大小寫，只接受小寫 `true` / `false`）。

## 執行紀錄（Log）

1. 讀取 issue #101（`gh issue view` 因 Projects classic 的 GraphQL 錯誤失敗，改用 `gh api repos/Arthur801/Book-Finder/issues/101` 取得內容）。
2. 基準測試：`crawler/tests/test_deploy.py` 12 passed；`deploy/tests/host/test_run_crawler_contract.py` 4 passed。
3. TDD 紅燈：新增測試後 `test_crawler_disabled_exits_before_any_external_work`、`test_crawler_enabled_rejects_invalid_values[*]`（5 個）共 6 個失敗，符合預期。
4. 實作 `run-crawler.sh` 後全部通過（20 passed）。
5. commit 1 `feat(crawler): add CRAWLER_ENABLED switch to skip scheduled runs (#101)`（script + test_deploy）。
6. commit 2 `test(deploy): keep CRAWLER_ENABLED through crawler.conf rewrite (#101)`。此測試為 characterization：現有 `rewrite_crawler_image` 已保留其他行，因此新增測試直接通過，不是紅燈。
7. commit 3 `docs: document CRAWLER_ENABLED switch for blocked EC2 hosts (#101)`。
8. ruff format 發現 `test_machine.py` 一處換行問題，以 `git commit --fixup` + `--autosquash` 併入 commit 2（歷史中沒有格式修正 commit）。
9. 未 push。`.venv`（worktree 中的未追蹤目錄）未觸碰。`.env` 未讀取。`book-finder-db-1` 未觸碰。

## 驗證結果

| 指令 | 結果 |
|---|---|
| `cd crawler && .../Book-Finder/.venv/bin/python -m pytest tests/test_deploy.py -q --noconftest` | 20 passed in 10.51s |
| `.../Book-Finder/.venv/bin/python -m pytest .github/scripts/tests deploy/tests -q` | 644 passed, 7 skipped in 5.61s |
| `uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -q` | 575 passed, 7 skipped in 5.18s |
| `uvx --from shellcheck-py shellcheck crawler/deploy/run-crawler.sh` | 只有 SC1090（`source` 行，已知且預期）；無新增 finding |
| `uvx ruff@0.17.2 check --config crawler/ruff.toml crawler/tests/test_deploy.py` | All checks passed |
| `uvx ruff@0.17.2 format --check --config crawler/ruff.toml crawler/tests/test_deploy.py` | 1 file already formatted |
| `uvx ruff@0.17.2 check --config deploy/ruff.toml deploy` | All checks passed |
| `uvx ruff@0.17.2 format --check --config deploy/ruff.toml deploy` | 46 files already formatted |

Skipped 的 7 個測試為原本就跳過的項目（與本次變更無關）。

## 未解決事項

- **`v0.0.1` 內的 `run-crawler.sh` 不支援此開關。** 需先發布新 release（例如 `v0.0.2`）並部署後，`deploy/README.md` §3.1 第 5 點才能使用。
- 真實 EC2 的 `CRAWLER_ENABLED=false` 行為尚未在主機上驗證（本次只有 stub 測試）。
- 本次未修改 host 端程式碼；`rewrite_crawler_image` 原本就滿足需求，只補了測試。
- 未處理 `DB_MAINTENANCE_LOCK` 等其他既有待確認事項。

## Code Review 與修正

（review 後補上）
