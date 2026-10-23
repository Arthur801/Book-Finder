#!/usr/bin/env bash
# Runs the local integration scenarios against real docker, from this checkout. No root, systemd or AWS is needed.
# Why: the unit body is exercised exactly as systemd would start it, and every docker object it creates is named bf-it-*
# so the test can remove them afterwards. Port 5000 must be free: the web container publishes it, as on EC2.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_root"
docker info >/dev/null 2>&1 || { echo "docker is not available" >&2; exit 2; }

export BOOKFINDER_IT=1
if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project --python 3.12 --with pytest==9.1.1 python -m pytest deploy/tests -m integration -q -s "$@"
fi
exec python3 -m pytest deploy/tests -m integration -q -s "$@"
