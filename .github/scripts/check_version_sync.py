"""Check that versions which must move together are in sync across the repo.

Why: Dependabot bumps Microsoft.EntityFrameworkCore.* PackageReferences in the
.csproj files but never touches the dotnet-ef tool manifest (dotnet-tools.json),
so the two drift apart. Each check returns error strings; main() prints them as
GitHub annotations and exits 1 when any check fails.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EXCLUDED_DIRS = {"bin", "obj", ".venv", "node_modules"}
EF_DESIGN_PACKAGE = "Microsoft.EntityFrameworkCore.Design"
DOTNET_EF_TOOL = "dotnet-ef"


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

    package_versions: dict[str, str] = {}
    for csproj in _csproj_files(root):
        tree = ET.parse(csproj)
        for reference in tree.iter("PackageReference"):
            if reference.get("Include") == EF_DESIGN_PACKAGE:
                package_versions[str(csproj.relative_to(root))] = reference.get("Version", "")

    if not package_versions:
        return [f"{EF_DESIGN_PACKAGE} PackageReference not found in any .csproj; cannot verify {DOTNET_EF_TOOL}"]

    errors = []
    for csproj_name, package_version in sorted(package_versions.items()):
        if package_version != tool_version:
            errors.append(
                f"update dotnet-tools.json {DOTNET_EF_TOOL} from {tool_version} to {package_version} to match {EF_DESIGN_PACKAGE} {package_version} in {csproj_name}"
            )
    return errors


CHECKS = [
    check_dotnet_ef_matches_ef_core,
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
