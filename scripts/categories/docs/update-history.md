# scripts/categories 修改歷史

> 建立：2026-11-14。

| 日期 | SHA | Subject | 變更 |
|---|---|---|---|
| 2026-11-14 | `ff7ed32` | docs(categories): canonical category plan v2.1 and the P0 read-only subject audit | 新增 `sql/audit-subjects.sql`、`README.md`（P0，PR #183） |
| 2026-11-14 | `782d9e8` | feat(categories): rule files and config validation (P2) | `config/canonical_categories.toml`、`provider_roots.toml`、`subject_mappings.toml`、`category_config.py`、`pytest.ini` |
| 2026-11-14 | `bf7c11a` | feat(categories): derive eslite level-3 list from the category tree (P2) | `eslite_tree.py`（重用 crawler 的 `select()`） |
| 2026-11-14 | `deb82c0` | feat(categories): pure mapping rules and plan diff (P2) | `category_mapper.py` |
| 2026-11-14 | `294a265` | feat(categories): manage_categories CLI, repository and shipped Eslite list (P2) | `manage_categories.py`、`category_repository.py`、`config/eslite_level3.tsv`（254 列，由 2026-11-14 的分類樹存檔產生） |
| 2026-11-14 | `6a1ba2c` | test(categories): integration tests against a disposable PostgreSQL (P2) | `tests/conftest.py`、`tests/test_category_integration.py` |
| 2026-11-14 | `920dc2c` | ci: categories-tool job for the canonical category tool (P2) | `.github/workflows/ci.yml` 新增 job |
| 2026-11-14 | `deb899f` | feat(categories): resolve the two ambiguous Eslite names to 簡體書 (decision #7) | `config/subject_mappings.toml` 兩筆 MANUAL；拒絕寫入的測試改用不含 MANUAL 的暫時設定 |
| 2026-11-14 | `6860577` | fix(categories): drop the shebang that ruff 0.17.4 flags as EXE001 | `manage_categories.py` 移除 shebang；CI 釘 ruff 0.17.4，本機 venv 為 0.17.2，所以本機未報出 |
| 2026-11-14 | 本 PR | feat(categories): map the Eslite religion names to 宗教命理 (decision #8) | `config/subject_mappings.toml` 新增兩筆 MANUAL；`tests/test_shipped_config.py` |

Git 紀錄不代表 production 已套用。互參：[架構](architecture.md)、[案例](test-suite.md)。
