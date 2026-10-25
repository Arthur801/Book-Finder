#!/usr/bin/env bash
# Gate 9 evidence (Docs/data/data-model.md 11.3; Docs/testing/test-plan.md section 7 rows 13 and 14).
# Proves that the PREVIOUS release (web and crawler images) still works on a database migrated to 011 by the TARGET bundle.
# Row 14 (manual recovery compatibility) is this same run: a 011 database with the previous release's web and crawler is
# exactly the state a manual recovery produces, so the same smoke covers both rows.
#
# Steps: a throwaway pgvector database on an internal network -> target efbundle to 011 -> 011 seed -> previous web
# (HTTP checks) -> previous crawler with an offline driver (DB-layer checks). Only containers, the network and the volume
# created here are removed. No network to books.com.tw is used; the crawler runs with --network internal.
#
# Usage: prev-release-on-contract.sh --target-image IMG --prev-web-image IMG --prev-crawler-image IMG
# Output: one "PASS <name>" or "FAIL <name>[: reason]" line per check, then "RESULT PASS n/n" or "RESULT FAIL". Exit 0 only
# when every check passed. Detail lines use the prefix "INFO" and are not checks.
set -euo pipefail

usage() {
  echo "usage: $0 --target-image IMG --prev-web-image IMG --prev-crawler-image IMG" >&2
  exit 2
}

target_image=""
prev_web_image=""
prev_crawler_image=""
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case $1 in
    --target-image) target_image=$2 ;;
    --prev-web-image) prev_web_image=$2 ;;
    --prev-crawler-image) prev_crawler_image=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n $target_image && -n $prev_web_image && -n $prev_crawler_image ]] || usage

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
script_dir="$repo_root/deploy/migration-test"
# shellcheck source=deploy/lib/smoke.sh
source "$repo_root/deploy/lib/smoke.sh"
db_image=$(smoke_db_image "$repo_root")

target_migration=20261025120000_ContractMultiSourceCatalog
seed_file="$script_dir/seeds/20261025120000_ContractMultiSourceCatalog.sql"
driver_file="$script_dir/prev_crawler_driver.py"
expected_checks=15

suffix=$(smoke_random_hex 6)
network="bf-prev-$suffix"
db="bf-prev-db-$suffix"
web="bf-prev-web-$suffix"
crawler="bf-prev-crawler-$suffix"
keys_volume="bf-prev-keys-$suffix"
workdir=$(mktemp -d)

passes=0
fails=0
web_ready=0

# Run by the EXIT trap below; shellcheck cannot see that call.
# shellcheck disable=SC2329
cleanup() {
  docker rm -f "$web" "$crawler" "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$keys_volume" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT

# Secrets are exported and passed by name only, so they never appear in argv or in this script's output.
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(smoke_random_hex 12)
export PGPASSWORD="$POSTGRES_PASSWORD"
export Jwt__SigningKey
Jwt__SigningKey=$(smoke_random_hex 24)
export OPENAIAPI_KEY="sk-prev-release-placeholder-not-a-real-key"
export ConnectionStrings__DefaultConnection="Host=$db;Port=5432;Database=book_finder;Username=book_finder_dev;Password=$POSTGRES_PASSWORD"
export DATABASE_URL="postgresql://book_finder_dev:$POSTGRES_PASSWORD@$db:5432/book_finder"

pass() {
  passes=$((passes + 1))
  echo "PASS $1"
}

fail() {
  fails=$((fails + 1))
  echo "FAIL $1${2:+: $2}"
}

info() {
  echo "INFO $1"
}

# A failed step that the later steps depend on: report it and stop; the trap removes what was created.
fatal() {
  fail "$1" "$2"
  echo "RESULT FAIL: stopped after $fails failure(s)"
  exit 1
}

db_psql() {
  docker exec -e PGPASSWORD "$db" psql -h 127.0.0.1 -U book_finder_dev -d book_finder -X -q -At -v ON_ERROR_STOP=1 -c "$1"
}

# Prints the HTTP status on the last line and the body before it. Arguments: path, then extra curl arguments.
web_get() {
  local path=$1
  shift
  smoke_curl "$network" -H "X-Forwarded-Proto: https" -w $'\n%{http_code}' "$@" "http://$web:8080$path" || true
}

# The check helpers keep the report shape fixed; the checks themselves stay visible in the calls below.
expect_body() {
  # Arguments: check name, path, expected substring, curl arguments...
  local name=$1 path=$2 needle=$3 out code body
  shift 3
  out=$(web_get "$path" "$@")
  code=${out##*$'\n'}
  body=${out%$'\n'*}
  if [[ $code != 200 ]]; then
    fail "$name" "HTTP $code"
    return 0
  fi
  if grep -qF -- "$needle" <<<"$body"; then
    pass "$name"
  else
    fail "$name" "200, but the body does not contain the seeded value"
  fi
}

# Fresh database on an internal network.
smoke_create_network "$network" || fatal "network" "could not create internal network $network"
subnet=$SMOKE_SUBNET
smoke_start_db "$db" "$network" "$db_image" || fatal "database" "database did not accept connections within 60 s"

# Target bundle to 011, as production runs it (no migration argument: the bundle applies everything it knows).
migrate_out=""
migrate_rc=0
migrate_out=$(docker run --rm --network "$network" -e ConnectionStrings__DefaultConnection \
  --entrypoint /app/efbundle "$target_image" 2>&1) || migrate_rc=$?
applied=$(grep -c "^Applying migration '" <<<"$migrate_out" || true)
last_migration=$(db_psql 'SELECT "MigrationId" FROM "__EFMigrationsHistory" ORDER BY "MigrationId" DESC LIMIT 1' 2>"$workdir/psql.err" || true)
[[ -n $last_migration ]] || { sed "s/^/INFO psql: /" "$workdir/psql.err"; }
if [[ $migrate_rc -eq 0 && $applied -gt 0 && $last_migration == "$target_migration" ]]; then
  pass "migrate: efbundle applied to 011 on an empty database"
else
  fail "migrate: efbundle applied to 011 on an empty database" "exit $migrate_rc, $applied applied, last '$last_migration'"
  tail -n 20 <<<"$migrate_out" | sed 's/^/INFO efbundle: /'
  fatal "migrate: stopped" "the 011 database is needed for every later check"
fi

source_type_left=$(db_psql "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'source_type' AND table_name IN ('book_sources', 'book_subjects')" || echo error)
if [[ $source_type_left == 0 && $last_migration == "$target_migration" ]]; then
  pass "migrate: migration history ends at 011 and source_type is gone"
else
  fail "migrate: migration history ends at 011 and source_type is gone" "history '$last_migration', source_type columns $source_type_left"
fi

# The 011 seed: representative rows for the 011 shape (see the seed's header).
if docker exec -i -e PGPASSWORD "$db" psql -h 127.0.0.1 -U book_finder_dev -d book_finder -X -q -v ON_ERROR_STOP=1 <"$seed_file" >"$workdir/seed.log" 2>&1; then
  seeded_books=$(db_psql "SELECT count(*) FROM books" || echo 0)
  if [[ $seeded_books == 4 ]]; then
    pass "seed: 011 seed loaded"
  else
    fail "seed: 011 seed loaded" "books has $seeded_books rows, expected 4"
  fi
else
  fail "seed: 011 seed loaded" "psql failed; see the seed log in the work directory"
fi

# Previous web release, with the same environment the web smoke uses (web-smoke.sh) and a shared key volume.
info "previous web image: $prev_web_image"
web_args=(
  -d --name "$web" --network "$network"
  -e ConnectionStrings__DefaultConnection -e Jwt__SigningKey -e OPENAIAPI_KEY
  -e Embedding__BackfillEnabled=false -e AiProfile__Enabled=false
  -e ASPNETCORE_ENVIRONMENT=Production -e ASPNETCORE_HTTPS_PORT=443
  -e "ForwardedHeaders__KnownNetworks__0=$subnet"
  -e DataProtection__KeysPath=/data-protection-keys -v "$keys_volume:/data-protection-keys"
)
docker run "${web_args[@]}" "$prev_web_image" >/dev/null || fatal "web: container start" "docker run failed"

rc=0
smoke_wait_ready "$network" "$web" || rc=$?
if [[ $rc -eq 0 ]]; then
  web_ready=1
  pass "web: GET / -> 200"
else
  fail "web: GET / -> 200" "container did not answer 200 (status ${SMOKE_LAST_STATUS:-none}, wait code $rc)"
fi

if [[ $web_ready -eq 1 ]]; then
  out=$(web_get /books)
  code=${out##*$'\n'}
  if [[ $code == 200 ]]; then
    pass "web: GET /books -> 200"
  else
    fail "web: GET /books -> 200" "HTTP $code"
  fi

  expect_body "web: keyword search finds the seeded Book" /search \
    "/books/10000000-0000-0000-0000-000000000004" -G --data-urlencode "q=第四本書"
  expect_body "web: hyphenated ISBN search finds the seeded Book" /search \
    "/books/10000000-0000-0000-0000-000000000004" -G --data-urlencode "q=978-626-3100-002"
  # One request, both assertions: the ISBN value and the seeded books.com.tw source URL must be on the same page.
  out=$(web_get /books/10000000-0000-0000-0000-000000000004)
  code=${out##*$'\n'}
  body=${out%$'\n'*}
  if [[ $code != 200 ]]; then
    fail "web: detail shows the ISBN and the books.com.tw source link" "HTTP $code"
  elif ! grep -qF "9786263100002" <<<"$body"; then
    fail "web: detail shows the ISBN and the books.com.tw source link" "ISBN 9786263100002 is not on the page"
  elif ! grep -qF "https://www.books.com.tw/products/0010000004" <<<"$body"; then
    fail "web: detail shows the ISBN and the books.com.tw source link" "source link is not on the page"
  else
    pass "web: detail shows the ISBN and the books.com.tw source link"
  fi

  if smoke_logs_clean "$web"; then
    pass "web: no unhandled exception in the container log"
  else
    fail "web: no unhandled exception in the container log" "see docker logs $web"
    docker logs "$web" 2>&1 | tail -n 60 | sed 's/^/INFO web log: /' || true
  fi
else
  fail "web: keyword search finds the seeded Book" "skipped: web is not ready"
  fail "web: hyphenated ISBN search finds the seeded Book" "skipped: web is not ready"
  fail "web: detail shows the ISBN and the books.com.tw source link" "skipped: web is not ready"
  fail "web: no unhandled exception in the container log" "skipped: web is not ready"
fi

# Previous crawler release: offline driver, imported from inside that image. Its own PASS/FAIL lines pass through.
info "previous crawler image: $prev_crawler_image"
driver_rc=0
driver_out=$(docker run --name "$crawler" --rm --network "$network" \
  -e DATABASE_URL -e PYTHONPATH=/app/crawler \
  -v "$driver_file:/driver/prev_crawler_driver.py:ro" \
  --entrypoint python "$prev_crawler_image" /driver/prev_crawler_driver.py 2>&1) || driver_rc=$?
printf '%s\n' "$driver_out" | grep -E '^(PASS|FAIL|INFO) ' || true
crawler_pass=$(grep -c '^PASS ' <<<"$driver_out" || true)
crawler_fail=$(grep -c '^FAIL ' <<<"$driver_out" || true)
passes=$((passes + crawler_pass))
fails=$((fails + crawler_fail))
if [[ $driver_rc -ne 0 && $crawler_fail -eq 0 ]]; then
  fail "crawler: driver" "exited $driver_rc without a FAIL line; last output lines are above"
fi
if [[ $driver_rc -eq 0 && $crawler_pass -ne 6 ]]; then
  fail "crawler: driver" "$crawler_pass PASS lines, expected 6"
fi

if [[ $fails -eq 0 && $passes -eq $expected_checks ]]; then
  echo "RESULT PASS $passes/$expected_checks"
  exit 0
fi
echo "RESULT FAIL: $passes passed, $fails failed (expected $expected_checks checks)"
exit 1
