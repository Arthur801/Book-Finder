"""Static checks of the Kingstone image (Dockerfile target ``kingstone``, ``.dockerignore``, CI smoke). Offline: no docker.

The Kingstone target is HTTP-only: it must not carry Playwright or a browser, and it must hold the Kingstone package and
the committed page list. The default target (the last stage, 博客來) must stay the 博客來 image.
"""

import re
from pathlib import Path

CRAWLER = Path(__file__).resolve().parents[1]
REPO = CRAWLER.parent
DOCKERFILE = CRAWLER / "Dockerfile"
DOCKERIGNORE = CRAWLER / ".dockerignore"
CI = REPO / ".github" / "workflows" / "ci.yml"


def _stages(text: str) -> dict[str, str]:
    """Stage body by name; the unnamed final stage is keyed by ``""``. Order is kept (the last stage is the default)."""
    parts = re.split(r"(?m)^FROM ", text)[1:]
    stages: dict[str, str] = {}
    for part in parts:
        header, _, body = part.partition("\n")
        match = re.search(r"\sAS\s+(\S+)\s*$", header)
        stages["" if match is None else match.group(1)] = body
    return stages


def test_the_kingstone_target_exists_and_the_default_target_is_still_the_books_image():
    stages = _stages(DOCKERFILE.read_text(encoding="utf-8"))

    assert "kingstone" in stages
    assert list(stages)[-1] == ""  # the unnamed final stage is what a plain `docker build` produces
    assert list(stages)[-1] != "kingstone"


def test_the_kingstone_target_has_no_playwright_or_browser():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))["kingstone"]

    assert "playwright" not in body.lower()
    assert "chromium" not in body.lower()
    assert "requirements.txt" not in body  # the development file pins playwright
    assert "requirements-runtime.txt" in body
    assert "playwright" not in (CRAWLER / "requirements-runtime.txt").read_text(encoding="utf-8").lower()


def test_the_kingstone_target_copies_the_package_and_the_committed_page_list_and_nothing_of_books():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))["kingstone"]

    assert "COPY catalog_core/ ./catalog_core/" in body
    assert "COPY kingstone/ ./kingstone/" in body
    assert "COPY kingstone-pages.txt ./kingstone-pages.txt" in body
    assert "books_crawler" not in body
    assert "category-pages.txt" not in body
    assert (CRAWLER / "kingstone-pages.txt").is_file()
    assert (CRAWLER / "kingstone" / "__init__.py").is_file()


def test_the_kingstone_target_runs_as_uid_10001_with_the_kingstone_module_as_its_command():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))["kingstone"]

    assert "--gid 10001" in body
    assert "--uid 10001" in body
    assert "USER 10001:10001" in body
    assert 'ENTRYPOINT ["python", "-m"]' in body
    assert 'CMD ["kingstone"]' in body


def test_the_default_books_target_is_unchanged_in_its_essentials():
    body = _stages(DOCKERFILE.read_text(encoding="utf-8"))[""]

    assert "COPY books_crawler/ ./books_crawler/" in body
    assert "COPY category-pages.txt ./category-pages.txt" in body
    assert "COPY requirements-runtime.txt ./" in body
    assert "USER 10001:10001" in body
    assert 'CMD ["books_crawler"]' in body
    assert "kingstone" not in body


def test_dockerignore_admits_the_kingstone_package_and_page_list():
    lines = {line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()}

    assert {"**", "!kingstone/", "!kingstone/**", "!kingstone-pages.txt", "!requirements-runtime.txt"} <= lines
    assert "kingstone/**/__pycache__/" in lines
    assert "kingstone/**/*.pyc" in lines


def test_ci_builds_the_kingstone_target_and_runs_an_offline_smoke_without_playwright():
    ci = CI.read_text(encoding="utf-8")

    assert "docker build --target kingstone -t book-finder-kingstone:ci crawler" in ci
    assert "--network none" in ci
    assert "load_page_urls(DEFAULT_PAGES_FILE)" in ci
    assert "ModuleNotFoundError" in ci
