"""Check that versions which must move together are in sync across the repo.

Why: Dependabot bumps Microsoft.EntityFrameworkCore.* PackageReferences in the
.csproj files but never touches the dotnet-ef tool manifest (dotnet-tools.json),
so the two drift apart. Dependabot also bumps the pgvector image in compose.yaml
but never the image strings hard-coded in the test fixtures, so those drift too.
Each check returns error strings; main() prints them as GitHub annotations and
exits 1 when any check fails.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EXCLUDED_DIRS = {"bin", "obj", ".venv", "node_modules"}
EF_DESIGN_PACKAGE = "Microsoft.EntityFrameworkCore.Design"
DOTNET_EF_TOOL = "dotnet-ef"
COMPOSE_FILE = "compose.yaml"
PGVECTOR_IMAGE_IN_COMPOSE = re.compile(r"^\s*image:\s*[\"']?(pgvector/pgvector:[^\s\"'#]+)", re.MULTILINE)
PGVECTOR_IMAGE_IN_CODE = re.compile(r"pgvector/pgvector:[\w.\-]+")
TEST_IMAGE_FILES = [
    "tests/DatabaseIntegration/PostgresFixture.cs",
    "tests/WebIntegration/WebFixture.cs",
    "crawler/tests/conftest.py",
]


def _csproj_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.csproj") if not EXCLUDED_DIRS.intersection(path.relative_to(root).parts)]


def check_dotnet_ef_matches_ef_core(root: Path) -> list[str]:
    tools_path = root / "dotnet-tools.json"
    try:
        tools = json.loads(tools_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read {tools_path.name}: {error}"]

    tool_version = tools.get("tools", {}).get(DOTNET_EF_TOOL, {}).get("version")
    if tool_version is None:
        return [f"{DOTNET_EF_TOOL} is not pinned in dotnet-tools.json; add it at the EF Core version"]

    errors = []
    package_versions: dict[str, str] = {}
    for csproj in _csproj_files(root):
        csproj_name = str(csproj.relative_to(root))
        try:
            tree = ET.parse(csproj)
        except (ET.ParseError, OSError) as error:
            errors.append(f"cannot parse {csproj_name}: {error}")
            continue
        for reference in tree.iter("PackageReference"):
            if reference.get("Include") == EF_DESIGN_PACKAGE:
                package_versions[csproj_name] = reference.get("Version", "")

    if not package_versions:
        return errors or [f"{EF_DESIGN_PACKAGE} PackageReference not found in any .csproj; cannot verify {DOTNET_EF_TOOL}"]

    for csproj_name, package_version in sorted(package_versions.items()):
        if not package_version:
            errors.append(f"{csproj_name}: {EF_DESIGN_PACKAGE} has no Version attribute; cannot verify {DOTNET_EF_TOOL}")
        elif package_version != tool_version:
            errors.append(
                f"update dotnet-tools.json {DOTNET_EF_TOOL} from {tool_version} to {package_version} to match {EF_DESIGN_PACKAGE} {package_version} in {csproj_name}"
            )
    return errors


def check_test_images_match_compose(root: Path) -> list[str]:
    compose_path = root / COMPOSE_FILE
    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"cannot read {COMPOSE_FILE}: {error}"]

    compose_images = set(PGVECTOR_IMAGE_IN_COMPOSE.findall(compose_text))
    if not compose_images:
        return [f"pgvector image not found in {COMPOSE_FILE}; cannot verify test images"]
    if len(compose_images) > 1:
        return [f"{COMPOSE_FILE} pins more than one pgvector image {sorted(compose_images)}; keep one"]
    compose_image = compose_images.pop()

    errors = []
    for relative_name in TEST_IMAGE_FILES:
        test_path = root / relative_name
        try:
            test_text = test_path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"cannot read {relative_name}: {error}; it must use {compose_image} from {COMPOSE_FILE}")
            continue

        test_images = PGVECTOR_IMAGE_IN_CODE.findall(test_text)
        if not test_images:
            errors.append(f"no pgvector image found in {relative_name}; it must use {compose_image} from {COMPOSE_FILE}")
            continue
        for test_image in sorted(set(test_images) - {compose_image}):
            errors.append(f"change {test_image} in {relative_name} to {compose_image} to match {COMPOSE_FILE}")
    return errors


CHECKS = [
    check_dotnet_ef_matches_ef_core,
    check_test_images_match_compose,
]


def main() -> int:
    if len(sys.argv) > 2:
        print(f"usage: {sys.argv[0]} [repo-root]", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parents[2]

    errors = [error for check in CHECKS for error in check(root)]
    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1
    print(f"version sync OK ({len(CHECKS)} check(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
