#!/usr/bin/env bash
# Checks that the target release can upgrade a database in the state production has applied (A).
# Why: a deploy is only safe if the rebuild image recreates exactly A, the target upgrades A without dropping or
# rewriting data or drifting from a fresh install, and the target web app still answers. The runtime image is only
# informational: it shows whether the current release can still run on the upgraded database, but never blocks a deploy.
# Usage: compat.sh --rebuild-image IMG --target-image IMG [--runtime-image IMG|none] --applied FILE --seeds-dir DIR --report OUT.json
set -euo pipefail

usage() {
  echo "usage: $0 --rebuild-image IMG --target-image IMG [--runtime-image IMG|none] --applied FILE --seeds-dir DIR --report OUT.json" >&2
  exit 2
}

rebuild_image=""
target_image=""
runtime_image="none"
applied=""
seeds_dir=""
report_out=""
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --rebuild-image) rebuild_image=$2 ;;
    --target-image) target_image=$2 ;;
    --runtime-image) runtime_image=$2 ;;
    --applied) applied=$2 ;;
    --seeds-dir) seeds_dir=$2 ;;
    --report) report_out=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $rebuild_image && -n $target_image && -n $applied && -n $seeds_dir && -n $report_out ]] || usage

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck source=deploy/lib/manifest.sh
source "$repo_root/deploy/lib/manifest.sh"
# shellcheck source=deploy/lib/smoke.sh
source "$repo_root/deploy/lib/smoke.sh"
# shellcheck source=deploy/lib/schema_dump.sh
source "$repo_root/deploy/lib/schema_dump.sh"
db_image=$(smoke_db_image "$repo_root")

suffix=$(smoke_random_hex 6)
network="bf-compat-$suffix"
db="bf-compat-db-$suffix"
web="bf-compat-web-$suffix"
probe="bf-compat-probe-$suffix"
keys_volume="bf-compat-keys-$suffix"
workdir=$(mktemp -d)
checks_file="$workdir/checks.tsv"
: >"$checks_file"

# Report state. Defaults describe a run that stopped before the step that sets them.
classification=""
applied_digest=""
pending_csv=""
mandatory_failures=0
forward_ok=0
runtime_result="skip"
runtime_detail="no runtime image given"
subnet=""

# Secrets are exported and passed by name only, so they never appear in argv or this script's output.
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(smoke_random_hex 12)
export PGPASSWORD="$POSTGRES_PASSWORD"
export Jwt__SigningKey
Jwt__SigningKey=$(smoke_random_hex 24)
export OPENAIAPI_KEY="sk-compat-placeholder-not-a-real-key"

connection_string() {
  printf 'Host=%s;Port=5432;Database=%s;Username=book_finder_dev;Password=%s' "$db" "$1" "$POSTGRES_PASSWORD"
}
export ConnectionStrings__DefaultConnection
ConnectionStrings__DefaultConnection=$(connection_string book_finder)

cleanup() {
  docker rm -f "$web" "$probe" "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$keys_volume" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}

write_report() {
  local forward_json=false
  [[ $forward_ok -eq 1 ]] && forward_json=true
  python3 -I -c '
import json, sys
out, checks_path, rebuild, target, runtime, digest, classification, pending, forward, rt_result, rt_detail = sys.argv[1:12]
checks = []
with open(checks_path, encoding="utf-8") as fh:
    for line in fh:
        result, name, detail = line.rstrip("\n").split("\t", 2)
        checks.append({"name": name, "result": result, "detail": detail})
report = {
    "schema_version": 1,
    "rebuild_image": rebuild,
    "target_image": target,
    "runtime_image": None if runtime == "none" else runtime,
    "applied_digest": digest or None,
    "classification": classification or None,
    "pending": [item for item in pending.split(",") if item],
    "checks": checks,
    "forward_ok": forward == "true",
    "runtime_smoke": {"result": rt_result, "detail": rt_detail},
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
' "$report_out" "$checks_file" "$rebuild_image" "$target_image" "$runtime_image" "$applied_digest" \
    "$classification" "$pending_csv" "$forward_json" "$runtime_result" "$runtime_detail"
}

on_exit() {
  local status=$?
  set +e
  # The report comes first: it must exist even when docker or the database is gone.
  write_report || status=1
  cleanup
  if [[ $status -eq 0 && $forward_ok -ne 1 ]]; then
    status=1
  fi
  exit "$status"
}
trap on_exit EXIT

# Each check is one tab-separated line in checks_file, so the report can be built without parsing stdout.
record() {
  local result=$1 name=$2 detail=${3:-}
  detail=${detail//$'\n'/ | }
  printf '%s\t%s\t%s\n' "$result" "$name" "$detail" >>"$checks_file"
  if [[ $result == fail ]]; then
    mandatory_failures=$((mandatory_failures + 1))
  fi
  case $result in
    pass) echo "PASS $name${detail:+: $detail}" ;;
    fail) echo "FAIL $name${detail:+: $detail}" ;;
    *) echo "INFO $name${detail:+: $detail}" ;;
  esac
  return 0
}

# A failed step cannot be followed by the steps that depend on it, so the run stops here and the trap writes the report.
fatal() {
  record fail "$1" "$2"
  exit 1
}

# Lists "table<TAB>column" for every pre-existing public table except the migration history, in column order.
list_columns() {
  db_query book_finder "select table_name, column_name from information_schema.columns where table_schema = 'public' and table_name <> '__EFMigrationsHistory' order by table_name, ordinal_position"
}

db_sql() {
  # Arguments: database. SQL arrives on stdin; output is unaligned tuples so the results can be compared as text.
  docker exec -i -e PGPASSWORD "$db" psql -h 127.0.0.1 -U book_finder_dev -d "$1" -X -q -At -F $'\t' -v ON_ERROR_STOP=1
}

db_query() {
  printf '%s\n' "$2" | db_sql "$1"
}

# Runs an efbundle from the given image against the given database. Arguments: image, database, [migration].
run_efbundle_on() {
  local image=$1 database=$2
  shift 2
  ConnectionStrings__DefaultConnection="$(connection_string "$database")" \
    docker run --rm --network "$network" -e ConnectionStrings__DefaultConnection \
    --entrypoint /app/efbundle "$image" "$@" 2>&1
}

# Reads /opt/release/migrations.txt without starting the image. docker cp has no -L, so a symlink in the image is copied
# as a link and rejected by manifest_validate_file instead of being followed out of the container.
extract_manifest() {
  local image=$1 dest=$2 status=0
  docker rm -f "$probe" >/dev/null 2>&1 || true
  docker create --name "$probe" "$image" >/dev/null || return 1
  docker cp "$probe:/opt/release/migrations.txt" "$dest" >/dev/null || status=1
  docker rm -f "$probe" >/dev/null 2>&1 || true
  return $status
}

# Emits one UNION ALL query over the listed table/column pairs (file of "table<TAB>column" lines). Each table gets a
# "row" line with the row count and a checksum over its listed columns. Each column gets a "col" line with a checksum over
# its sorted values, so a changed value can be blamed on its column even when rows reorder.
fingerprint_sql() {
  local table column i
  local -A lists=()
  local -a tables=() parts=()
  while IFS=$'\t' read -r table column; do
    if [[ -z ${lists[$table]+x} ]]; then
      lists[$table]=""
      tables+=("$table")
    fi
    lists[$table]+="${lists[$table]:+, }\"$column\""
  done <"$1"
  while IFS=$'\t' read -r table column; do
    parts+=("SELECT 'col', '$table', '$column', '-', coalesce(md5(string_agg(v, E'\n' ORDER BY v)), '') FROM (SELECT coalesce(\"$column\"::text, '<null>') AS v FROM \"$table\") c")
  done <"$1"
  for table in "${tables[@]}"; do
    parts+=("SELECT 'row', '$table', '-', count(*)::text, coalesce(md5(string_agg(r::text, E'\n' ORDER BY r::text)), '') FROM (SELECT ${lists[$table]} FROM \"$table\") r")
  done
  for i in "${!parts[@]}"; do
    if ((i > 0)); then
      printf '\nUNION ALL\n'
    fi
    printf '%s' "${parts[i]}"
  done
  printf ';\n'
}

# Schema text for comparing two databases. Normalization and failure rules live in deploy/lib/schema_dump.sh; on failure
# the reason goes to stderr. pg_dump 17.6+ prints a random \restrict key per run, which the helper drops.
dump_schema() {
  schema_dump_normalized "$1" docker exec -e PGPASSWORD "$db" pg_dump -h 127.0.0.1 -U book_finder_dev -d "$1" \
    --schema-only --no-owner --no-privileges
}

# Step 1: manifests. Everything here runs without touching the database, so a divergent A stops before any DB work.
check_manifests() {
  manifest_validate_file "$applied" || fatal "applied manifest valid" "$applied is not a valid manifest (see above)"
  record pass "applied manifest valid" "$(grep -c '' "$applied" || true) migration(s)"

  extract_manifest "$rebuild_image" "$workdir/rebuild.txt" \
    || fatal "rebuild image manifest readable" "docker could not read /opt/release/migrations.txt from $rebuild_image"
  manifest_validate_file "$workdir/rebuild.txt" || fatal "rebuild image manifest valid" "rebuild image manifest is not valid (see above)"
  record pass "rebuild image manifest valid"

  extract_manifest "$target_image" "$workdir/target.txt" \
    || fatal "target image manifest readable" "docker could not read /opt/release/migrations.txt from $target_image"
  manifest_validate_file "$workdir/target.txt" || fatal "target image manifest valid" "target image manifest is not valid (see above)"
  record pass "target image manifest valid"

  classification=$(manifest_classify "$applied" "$workdir/target.txt")
  if [[ $classification == divergent ]]; then
    fatal "applied vs target classification" "divergent: applied and target disagree on a shared migration id or hash, or a migration was inserted before applied ones"
  fi
  if [[ $classification == schema-ahead ]]; then
    record pass "applied vs target classification" "schema-ahead: the target has fewer migrations than production; the forward smoke still runs"
  else
    record pass "applied vs target classification" "$classification"
  fi

  local rebuild_class
  rebuild_class=$(manifest_classify "$applied" "$workdir/rebuild.txt")
  case $rebuild_class in
    in-sync | forward) record pass "applied is a prefix of the rebuild manifest" "$rebuild_class" ;;
    *) fatal "applied is a prefix of the rebuild manifest" "rebuild image cannot recreate the applied migrations ($rebuild_class)" ;;
  esac

  applied_digest=$(manifest_schema_digest "$applied")
  if [[ $classification == forward || $classification == in-sync ]]; then
    pending_csv=$(manifest_pending "$applied" "$workdir/target.txt" | cut -d' ' -f1 | paste -sd, - || true)
  fi
}

# Step 2: database on the internal network.
start_database() {
  [[ -n $db_image ]] || fatal "pgvector image found" "compose.yaml has no pgvector image line"
  smoke_create_network "$network" || fatal "internal network created" "could not create $network on 172.30.100-199.0/24"
  smoke_start_db "$db" "$network" "$db_image" || fatal "database accepts connections" "pgvector did not accept connections within 60 s"
}

# Step 3: rebuild A with the rebuild image's bundle, then confirm the history is exactly A.
rebuild_applied() {
  local applied_ids history last_id output
  applied_ids=$(cut -d' ' -f1 "$applied")
  if [[ -z $applied_ids ]]; then
    record skip "rebuild applied migrations" "applied is empty; nothing to rebuild"
    return 0
  fi
  last_id=$(tail -n1 <<<"$applied_ids")
  if ! output=$(run_efbundle_on "$rebuild_image" book_finder "$last_id"); then
    tail -n 30 <<<"$output"
    fatal "rebuild applied migrations" "rebuild efbundle failed migrating to $last_id"
  fi
  history=$(db_query book_finder 'select "MigrationId" from "__EFMigrationsHistory" order by "MigrationId" COLLATE "C"') \
    || fatal "rebuild history readable" "could not read __EFMigrationsHistory"
  if [[ $history == "$applied_ids" ]]; then
    record pass "rebuild reproduces applied history" "$(wc -l <<<"$applied_ids" | tr -d ' ') migration(s)"
  else
    record fail "rebuild reproduces applied history" "history differs from applied; expected $(paste -sd, <<<"$applied_ids") got $(paste -sd, <<<"$history")"
    exit 1
  fi
}

# Step 4: representative rows for the schema A, so the upgrade has data to preserve.
load_seed() {
  local last_id seed seed_output
  if [[ -z $(cut -d' ' -f1 "$applied") ]]; then
    record skip "seed loaded" "applied is empty; no seed needed"
    return 0
  fi
  last_id=$(cut -d' ' -f1 "$applied" | tail -n1)
  seed="$seeds_dir/$last_id.sql"
  if [[ ! -f $seed ]]; then
    fatal "seed loaded" "missing seed file $seed; add $last_id.sql covering every table at that migration (see the seed header)"
  fi
  if ! seed_output=$(db_sql book_finder <"$seed" 2>&1); then
    tail -n 30 <<<"$seed_output"
    fatal "seed loaded" "$seed did not load"
  fi
  record pass "seed loaded" "$(basename "$seed")"
}

# Step 5: remember every pre-existing table and column so the upgrade can be compared against it.
fingerprint_before() {
  list_columns >"$workdir/columns-before.tsv" || fatal "schema before upgrade readable" "could not list columns"
  if [[ ! -s $workdir/columns-before.tsv ]]; then
    : >"$workdir/fingerprint-before.tsv"
    return 0
  fi
  fingerprint_sql "$workdir/columns-before.tsv" >"$workdir/fingerprint-before.sql"
  db_sql book_finder <"$workdir/fingerprint-before.sql" >"$workdir/fingerprint-before.tsv" \
    || fatal "fingerprint before upgrade" "could not fingerprint the seeded database"
}

# Step 6: upgrade with the target image's bundle and confirm the history now equals the target manifest.
upgrade_to_target() {
  local output target_ids history
  if ! output=$(run_efbundle_on "$target_image" book_finder); then
    tail -n 30 <<<"$output"
    fatal "target upgrade applied" "target efbundle exited non-zero"
  fi
  if grep -q 'No migrations were applied' <<<"$output"; then
    record pass "target upgrade applied" "no migrations pending"
  else
    record pass "target upgrade applied" "applied $(grep -c "^Applying migration '" <<<"$output" || true) migration(s)"
  fi

  target_ids=$(cut -d' ' -f1 "$workdir/target.txt")
  history=$(db_query book_finder 'select "MigrationId" from "__EFMigrationsHistory" order by "MigrationId" COLLATE "C"') \
    || fatal "upgraded history readable" "could not read __EFMigrationsHistory after the upgrade"
  if [[ $history == "$target_ids" ]]; then
    record pass "upgraded history equals target manifest"
  else
    record fail "upgraded history equals target manifest" "history does not match the target manifest"
  fi
}

# Step 7: rows, tables and columns that existed before the upgrade must still exist with the same values. Non-fatal so
# the forward smoke still runs and the report shows every problem at once.
# Note: a contract migration that drops data will need an explicit, reviewed allowance here. Not implemented yet.
check_data_preserved() {
  local table column kind n h after_n after_h key
  local -a problems=()
  local -A after_tables=() after_cols=() skip_table=() missing_cols=() after_fp=()

  if [[ ! -s $workdir/columns-before.tsv ]]; then
    record pass "data preserved" "no pre-existing tables"
    return 0
  fi
  if ! list_columns >"$workdir/columns-after.tsv"; then
    record fail "data preserved" "could not list columns after the upgrade"
    return 0
  fi
  while IFS=$'\t' read -r table column; do
    after_tables[$table]=1
    after_cols[$table.$column]=1
  done <"$workdir/columns-after.tsv"

  : >"$workdir/columns-present.tsv"
  local pre_tables=0 pre_columns=0
  while IFS=$'\t' read -r table column; do
    pre_columns=$((pre_columns + 1))
    if [[ -z ${after_tables[$table]+x} ]]; then
      skip_table[$table]=1
      problems+=("table $table was dropped")
    elif [[ -z ${after_cols[$table.$column]+x} ]]; then
      skip_table[$table]=1
      missing_cols[$table.$column]=1
      problems+=("column $table.$column was dropped")
    else
      printf '%s\t%s\n' "$table" "$column" >>"$workdir/columns-present.tsv"
    fi
  done <"$workdir/columns-before.tsv"
  pre_tables=$(cut -f1 "$workdir/columns-before.tsv" | sort -u | wc -l | tr -d ' ')

  if [[ -s $workdir/columns-present.tsv ]]; then
    fingerprint_sql "$workdir/columns-present.tsv" >"$workdir/fingerprint-after.sql"
    if ! db_sql book_finder <"$workdir/fingerprint-after.sql" >"$workdir/fingerprint-after.tsv"; then
      record fail "data preserved" "could not fingerprint the upgraded database"
      return 0
    fi
  else
    : >"$workdir/fingerprint-after.tsv"
  fi
  while IFS=$'\t' read -r kind table column n h; do
    after_fp["$kind|$table|$column"]="$n|$h"
  done <"$workdir/fingerprint-after.tsv"

  while IFS=$'\t' read -r kind table column n h; do
    key="$kind|$table|$column"
    if [[ $kind == row && -n ${skip_table[$table]+x} ]]; then
      continue
    fi
    if [[ $kind == col && -n ${missing_cols[$table.$column]+x} ]]; then
      continue
    fi
    if [[ -z ${after_fp[$key]+x} ]]; then
      problems+=("$key is missing after the upgrade")
      continue
    fi
    if [[ ${after_fp[$key]} != "$n|$h" ]]; then
      if [[ $kind == row ]]; then
        after_n=${after_fp[$key]%%|*}
        after_h=${after_fp[$key]#*|}
        if [[ $after_n != "$n" ]]; then
          problems+=("table $table row count changed from $n to $after_n")
        else
          problems+=("table $table row values changed (checksum $h -> $after_h)")
        fi
      else
        problems+=("column $table.$column values changed")
      fi
    fi
  done <"$workdir/fingerprint-before.tsv"

  if [[ ${#problems[@]} -eq 0 ]]; then
    record pass "data preserved" "$pre_tables table(s), $pre_columns column(s) unchanged"
  else
    record fail "data preserved" "$(IFS='; '; echo "${problems[*]}")"
  fi
}

# Step 8: the upgraded schema must match a fresh install of the target. Non-fatal, like the data check.
check_schema_matches_fresh() {
  local upgraded="$workdir/schema-upgraded.sql" fresh="$workdir/schema-fresh.sql" diff_out="$workdir/schema.diff"
  if ! docker exec -e PGPASSWORD "$db" createdb -h 127.0.0.1 -U book_finder_dev book_finder_fresh >/dev/null 2>&1; then
    record fail "schema matches a fresh install" "could not create the fresh database"
    return 0
  fi
  if ! run_efbundle_on "$target_image" book_finder_fresh >"$workdir/fresh-efbundle.log" 2>&1; then
    record fail "schema matches a fresh install" "target efbundle failed on an empty database"
    return 0
  fi
  local dump_err
  if ! dump_err=$(dump_schema book_finder 2>&1 >"$upgraded"); then
    record fail "schema matches a fresh install" "$dump_err"
    return 0
  fi
  if ! dump_err=$(dump_schema book_finder_fresh 2>&1 >"$fresh"); then
    record fail "schema matches a fresh install" "$dump_err"
    return 0
  fi
  if diff -u "$upgraded" "$fresh" >"$diff_out"; then
    record pass "schema matches a fresh install" "$(wc -l <"$upgraded" | tr -d ' ') normalized schema line(s)"
  else
    record fail "schema matches a fresh install" "upgraded schema differs from a fresh install (diff below)"
    head -n 200 "$diff_out"
  fi
}

# Forward smoke. Same contract as web-smoke.sh, but against the upgraded database. Prints each step as a check when
# mandatory and as INFO otherwise, so the runtime result never counts as a failure.
WEB_SMOKE_MODE=mandatory
WEB_SMOKE_DETAIL=""

web_step() {
  # Arguments: label, step, pass|fail, detail. Always returns 0 so callers can decide what to do with the step.
  local name="$1: $2"
  if [[ $WEB_SMOKE_MODE == mandatory ]]; then
    record "$3" "$name" "$4"
  else
    echo "INFO $name: $3${4:+ - $4}"
  fi
  if [[ $3 == fail ]]; then
    WEB_SMOKE_DETAIL="$name: $4"
  fi
  return 0
}

web_smoke() {
  # Arguments: image, label. Returns 0 when every step passes; otherwise 1 with WEB_SMOKE_DETAIL naming the failed step.
  local image=$1 label=$2 rc=0 login_rc=0 post_code
  WEB_SMOKE_DETAIL=""
  docker rm -f "$web" >/dev/null 2>&1 || true
  if ! docker run -d --name "$web" --network "$network" \
    -e ConnectionStrings__DefaultConnection -e Jwt__SigningKey -e OPENAIAPI_KEY \
    -e Embedding__BackfillEnabled=false -e AiProfile__Enabled=false \
    -e ASPNETCORE_ENVIRONMENT=Production -e ASPNETCORE_HTTPS_PORT=443 \
    -e "ForwardedHeaders__KnownNetworks__0=$subnet" \
    -e DataProtection__KeysPath=/data-protection-keys -v "$keys_volume:/data-protection-keys" \
    "$image" >/dev/null; then
    web_step "$label" "container starts" fail "docker run failed"
    return 1
  fi

  smoke_wait_ready "$network" "$web" || rc=$?
  case $rc in
    0) web_step "$label" "GET / with X-Forwarded-Proto: https -> 200" pass "" ;;
    2)
      web_step "$label" "GET / with X-Forwarded-Proto: https -> 200" fail "container stopped before it answered"
      return 1
      ;;
    *)
      web_step "$label" "GET / with X-Forwarded-Proto: https -> 200" fail "no 200 within 60 s (last status ${SMOKE_LAST_STATUS:-none})"
      return 1
      ;;
  esac

  login_rc=0
  smoke_fetch_login_form "$network" "$web" || login_rc=$?
  case $login_rc in
    0) web_step "$label" "GET /account/login issued antiforgery cookie and form token" pass "" ;;
    1)
      web_step "$label" "GET /account/login issued antiforgery cookie and form token" fail "no antiforgery cookie"
      return 1
      ;;
    *)
      web_step "$label" "GET /account/login issued antiforgery cookie and form token" fail "no __RequestVerificationToken in the form"
      return 1
      ;;
  esac

  post_code=$(smoke_post_bad_login "$network" "$web")
  if [[ $post_code == 200 ]]; then
    web_step "$label" "POST /account/login with bad credentials -> 200" pass ""
  else
    web_step "$label" "POST /account/login with bad credentials -> 200" fail "returned $post_code, expected 200"
    return 1
  fi

  if smoke_logs_clean "$web"; then
    web_step "$label" "container logs have no unhandled exception or startup failure" pass ""
  else
    web_step "$label" "container logs have no unhandled exception or startup failure" fail "logs contain an unhandled exception or a host startup failure"
    return 1
  fi
  return 0
}

check_forward_smoke() {
  subnet=$SMOKE_SUBNET
  # A failure is already recorded as a mandatory check; the run continues so the runtime result is still reported.
  if ! web_smoke "$target_image" forward; then
    docker logs "$web" 2>&1 | tail -n 200 || true
  fi
}

# Runtime smoke: the release currently running, against the upgraded database. Informational only.
check_runtime_smoke() {
  if [[ $runtime_image == none ]]; then
    echo "INFO runtime smoke skipped: no runtime image given"
    return 0
  fi
  docker rm -f "$web" >/dev/null 2>&1 || true
  WEB_SMOKE_MODE=info
  if web_smoke "$runtime_image" runtime; then
    runtime_result=pass
    runtime_detail="all runtime checks passed"
  else
    runtime_result=fail
    runtime_detail=$WEB_SMOKE_DETAIL
  fi
  echo "INFO runtime smoke: $runtime_result${runtime_detail:+ ($runtime_detail)}"
  WEB_SMOKE_MODE=mandatory
  return 0
}

main() {
  check_manifests
  start_database
  rebuild_applied
  load_seed
  fingerprint_before
  upgrade_to_target
  check_data_preserved || true
  check_schema_matches_fresh || true
  check_forward_smoke
  check_runtime_smoke || true
  # Any failed mandatory check (forward smoke, data, schema or history) makes the whole run fail, not just the smoke.
  if [[ $mandatory_failures -eq 0 ]]; then
    forward_ok=1
    echo "compat checks passed (forward_ok=true)"
  else
    failed_names=$(awk -F'\t' '$1 == "fail" { print $2 }' "$checks_file" | paste -sd';' - | sed 's/;/; /g')
    echo "compat checks failed (forward_ok=false): mandatory failed: $failed_names"
    exit 1
  fi
}

main
