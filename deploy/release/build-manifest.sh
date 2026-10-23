#!/usr/bin/env bash
# Writes the release manifest for a migrations directory: one "<id> <source_hash>" line per migration.
# Why: the Docker build context has no .git, so the manifest is computed from the files alone.
# The hash must match .github/scripts/check_migrations.py exactly; its test compares both outputs.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <migrations-dir> <out-dir>" >&2
  exit 2
fi

migrations_dir=$1
out_dir=$2

# Only the per-migration files are listed; the model snapshot is not a migration.
mapfile -t ids < <(
  find "$migrations_dir" -maxdepth 1 -type f -name '*.cs' ! -name '*.Designer.cs' ! -name 'AppDbContextModelSnapshot.cs' -printf '%f\n' |
    sed 's/\.cs$//' | LC_ALL=C sort
)
mapfile -t designer_ids < <(
  find "$migrations_dir" -maxdepth 1 -type f -name '*.Designer.cs' -printf '%f\n' |
    sed 's/\.Designer\.cs$//' | LC_ALL=C sort
)

status=0
for id in "${ids[@]}"; do
  if [[ ! -f "$migrations_dir/$id.Designer.cs" ]]; then
    echo "missing $id.Designer.cs for migration $id" >&2
    status=1
  fi
done
for id in "${designer_ids[@]}"; do
  if [[ ! -f "$migrations_dir/$id.cs" ]]; then
    echo "missing $id.cs for designer file $id.Designer.cs" >&2
    status=1
  fi
done
if [[ $status -ne 0 ]]; then
  exit 1
fi

mkdir -p "$out_dir"
manifest="$out_dir/migrations.txt"
: >"$manifest"
for id in "${ids[@]}"; do
  # CRs are stripped so CRLF and LF checkouts hash the same; the NUL separates the two files.
  hash=$({
    printf '%s\n' "$id"
    tr -d '\r' <"$migrations_dir/$id.cs"
    printf '\0'
    tr -d '\r' <"$migrations_dir/$id.Designer.cs"
  } | sha256sum | cut -d' ' -f1)
  printf '%s %s\n' "$id" "$hash" >>"$manifest"
done

printf '1\n' >"$out_dir/RELEASE_API"
