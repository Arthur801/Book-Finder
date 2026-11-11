"""Static checks of the Eslite image (Dockerfile target ``eslite``, ``.dockerignore``, CI smoke, placeholder page list). Offline: no docker.

The Eslite target is HTTP-only like the Kingstone target: no Playwright or browser, the Eslite package and its page list,
nothing of Books or Kingstone. The default target (the last stage, 博客來) must stay the 博客來 image.
"""

import re
from pathlib import Path

import pytest

from catalog_core.page_list import PageListError
from eslite.page_list import DEFAULT_PAGES_FILE, MAX_PAGES, load_page_urls
from eslite.urls import canonical_list_url

CRAWLER = Path(__file__).resolve().parents[1]
REPO = CRAWLER.parent
DOCKERFILE = CRAWLER / "Dockerfile"
DOCKERIGNORE = CRAWLER / ".dockerignore"
CI = REPO / ".github" / "workflows" / "ci.yml"
PAGES = CRAWLER / "eslite-pages.txt"


def _stages(text: str) -> dict[str, str]:
    """Stage body by name; the unnamed final stage is keyed by ``""``. Order is kept (the last stage is the default)."""
    parts = re.split(r"(?m)^FROM ", text)[1:]
    stages: dict[str, str] = {}
    for part in parts:
        header, _, body = part.partition("\n")
        match = re.search(r"\sAS\s+(\S+)\s*$", header)
        stages["" if match is None else match.group(1)] = body
    return stages


def test_the_eslite_target_exists_and_is_not_the_last_stage():
    stages = _stages(DOCKERFILE.read_text(encoding="utf-8"))

    assert "eslite" in stages
    assert list(stages)[-1] == ""  # the unnamed final stage is what a plain `docker build` produces
    assert list(stages)[-1] != "eslite"


def test_the_eslite_target_has_no_playwright_or_browser():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))["eslite"]

    assert "playwright" not in body.lower()
    assert "chromium" not in body.lower()
    assert "requirements.txt" not in body  # the development file pins playwright
    assert "requirements-runtime.txt" in body
    assert "playwright" not in (CRAWLER / "requirements-runtime.txt").read_text(encoding="utf-8").lower()


def test_the_eslite_target_copies_the_package_and_the_page_list_and_nothing_of_books_or_kingstone():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))["eslite"]

    assert "COPY catalog_core/ ./catalog_core/" in body
    assert "COPY eslite/ ./eslite/" in body
    assert "COPY eslite-pages.txt ./eslite-pages.txt" in body
    assert "books_crawler" not in body
    assert "kingstone" not in body
    assert "category-pages.txt" not in body
    assert (CRAWLER / "eslite-pages.txt").is_file()
    assert (CRAWLER / "eslite" / "__init__.py").is_file()


def test_the_eslite_target_runs_as_uid_10001_with_the_eslite_module_as_its_command():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))["eslite"]

    assert "--gid 10001" in body
    assert "--uid 10001" in body
    assert "USER 10001:10001" in body
    assert 'ENTRYPOINT ["python", "-m"]' in body
    assert 'CMD ["eslite"]' in body


def test_the_default_books_target_is_still_the_last_stage_and_unchanged_in_its_essentials():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))[""]

    assert "COPY books_crawler/ ./books_crawler/" in body
    assert "COPY category-pages.txt ./category-pages.txt" in body
    assert "COPY requirements-runtime.txt ./" in body
    assert "USER 10001:10001" in body
    assert 'CMD ["books_crawler"]' in body
    assert "kingstone" not in body
    assert "eslite" not in body


def test_dockerignore_admits_the_eslite_package_and_page_list():
    lines = {line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()}

    assert {"**", "!eslite/", "!eslite/**", "!eslite-pages.txt", "!requirements-runtime.txt"} <= lines
    assert "eslite/**/__pycache__/" in lines
    assert "eslite/**/*.pyc" in lines


def test_ci_builds_the_eslite_target_and_runs_an_offline_smoke_without_playwright():
    ci = CI.read_text(encoding="utf-8")

    assert "docker build --target eslite -t book-finder-eslite:ci crawler" in ci
    assert "Eslite image offline smoke" in ci
    smoke = ci[ci.index("Eslite image offline smoke") :]
    smoke = smoke[: smoke.index("# Pushes to main have nothing to compare")]
    assert smoke.count("--network none") == 2
    assert "import eslite.cli" in smoke
    assert "DEFAULT_PAGES_FILE" in smoke
    assert "import playwright" in smoke
    assert "ModuleNotFoundError" in smoke
    # The placeholder page list is empty: the smoke must not require it to load.
    assert "load_page_urls" not in smoke


def test_the_default_page_list_file_is_a_placeholder_with_only_comment_lines_so_the_empty_list_is_refused():
    lines = PAGES.read_text(encoding="utf-8").splitlines()

    assert lines, "the placeholder keeps its explanation"
    assert all(line.strip().startswith("#") or not line.strip() for line in lines)
    with pytest.raises(PageListError, match="no Eslite category list page URLs"):  # the empty-list error, not a parse error
        load_page_urls(DEFAULT_PAGES_FILE)


def test_the_committed_eslite_page_list_holds_only_canonical_list_urls_within_the_limit():
    # Holds for the placeholder (no entries) and for the user's list once it is filled in.
    entries = [line.strip() for line in PAGES.read_text(encoding="utf-8").splitlines()]
    entries = [line for line in entries if line and not line.startswith("#")]

    assert len(entries) <= MAX_PAGES
    for entry in entries:
        assert canonical_list_url(entry) is not None, entry
