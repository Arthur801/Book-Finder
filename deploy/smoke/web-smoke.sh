#!/usr/bin/env bash
# Runs the web image against a real pgvector database on an internal Docker network and checks the deploy contract.
# Why: the image is only deployable if migrations apply twice cleanly, forwarded HTTPS is trusted, and antiforgery
# survives a container restart. --control-no-keys drops the shared data-protection keys and must break the last check.
# Usage: web-smoke.sh <web-image> [--control-no-keys]
set -euo pipefail

usage() {
  echo "usage: $0 <web-image> [--control-no-keys]" >&2
  exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage
image=$1
control=0
if [[ $# -eq 2 ]]; then
  [[ $2 == --control-no-keys ]] || usage
  control=1
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# Same database image as compose.yaml, so the smoke test does not drift from the local setup.
db_image=$(sed -n 's/^[[:space:]]*image:[[:space:]]*\(pgvector\/pgvector:[^[:space:]]*\)[[:space:]]*$/\1/p' "$repo_root/compose.yaml" | head -n1)
# Digest-pinned so the HTTP client cannot change under the check.
curl_image="curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777"

random_hex() {
  od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'
}

suffix=$(random_hex 6)
network="bf-smoke-$suffix"
db="bf-smoke-db-$suffix"
web="bf-smoke-web-$suffix"
keys_volume="bf-smoke-keys-$suffix"
workdir=$(mktemp -d)

cleanup() {
  docker rm -f "$web" "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$keys_volume" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT

pass() {
  echo "PASS $*"
}

fail() {
  echo "FAIL $*"
  echo "--- docker logs $web ---"
  docker logs "$web" 2>&1 | tail -n 200 || true
  exit 1
}

# Secrets are exported and passed by name only, so they never appear in argv or this script's output.
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(random_hex 12)
export ConnectionStrings__DefaultConnection="Host=$db;Port=5432;Database=book_finder;Username=book_finder_dev;Password=$POSTGRES_PASSWORD"
export Jwt__SigningKey
Jwt__SigningKey=$(random_hex 24)
export OPENAIAPI_KEY="sk-smoke-placeholder-not-a-real-key"

[[ -n $db_image ]] || fail "pgvector image not found in compose.yaml"

# Internal network: containers on it have no route to the internet. A few random subnets are tried in case one overlaps.
subnet=""
for _ in 1 2 3 4 5; do
  octet=$((100 + RANDOM % 100))
  if docker network create --internal --subnet "172.30.$octet.0/24" "$network" >/dev/null 2>&1; then
    subnet="172.30.$octet.0/24"
    break
  fi
done
[[ -n $subnet ]] || fail "could not create internal network $network on 172.30.100-199.0/24"

docker run -d --name "$db" --network "$network" \
  -e POSTGRES_DB=book_finder -e POSTGRES_USER=book_finder_dev -e POSTGRES_PASSWORD \
  "$db_image" >/dev/null

# The entrypoint starts a temporary server on the Unix socket only; -h 127.0.0.1 waits for the real server.
db_ready=0
for _ in $(seq 60); do
  if docker exec "$db" pg_isready -h 127.0.0.1 -U book_finder_dev -d book_finder >/dev/null 2>&1; then
    db_ready=1
    break
  fi
  sleep 1
done
[[ $db_ready -eq 1 ]] || fail "database did not accept connections within 60 s"

run_efbundle() {
  docker run --rm --network "$network" -e ConnectionStrings__DefaultConnection \
    --entrypoint /app/efbundle "$image" 2>&1
}

expected_migrations=$(docker run --rm --entrypoint sh "$image" -c 'wc -l < /opt/release/migrations.txt' | tr -d ' ')

first_output=$(run_efbundle) || fail "efbundle failed on an empty database: $first_output"
applied=$(grep -c "^Applying migration '" <<<"$first_output" || true)
[[ $applied -eq $expected_migrations ]] || fail "efbundle applied $applied migrations, manifest lists $expected_migrations"
pass "efbundle applied $applied migrations on an empty database"

second_output=$(run_efbundle) || fail "efbundle failed on the second run: $second_output"
if grep -q "^Applying migration '" <<<"$second_output"; then
  fail "efbundle applied migrations again on the second run"
fi
grep -q "No migrations were applied. The database is already up to date." <<<"$second_output" \
  || fail "efbundle second run did not report that no migrations were applied"
pass "efbundle second run applied nothing (idempotent)"

web_args=(
  -d --name "$web" --network "$network"
  -e ConnectionStrings__DefaultConnection -e Jwt__SigningKey -e OPENAIAPI_KEY
  -e Embedding__BackfillEnabled=false -e AiProfile__Enabled=false
  -e ASPNETCORE_ENVIRONMENT=Production -e ASPNETCORE_HTTPS_PORT=443
  -e "ForwardedHeaders__KnownNetworks__0=$subnet"
)
if [[ $control -eq 0 ]]; then
  web_args+=(-e DataProtection__KeysPath=/data-protection-keys -v "$keys_volume:/data-protection-keys")
fi
docker run "${web_args[@]}" "$image" >/dev/null

curl_run() {
  docker run --rm --network "$network" "$curl_image" --silent --show-error --max-time 15 "$@"
}

wait_ready() {
  local code=""
  for _ in $(seq 60); do
    if [[ $(docker inspect -f '{{.State.Running}}' "$web" 2>/dev/null) != true ]]; then
      fail "web container stopped before it answered"
    fi
    code=$(curl_run -H "X-Forwarded-Proto: https" -o /dev/null -w '%{http_code}' "http://$web:8080/" || true)
    [[ $code == 200 ]] && return 0
    sleep 1
  done
  fail "web did not answer / within 60 s (last status ${code:-none})"
}
wait_ready

code=$(curl_run -H "X-Forwarded-Proto: https" -o /dev/null -w '%{http_code}' "http://$web:8080/" || true)
[[ $code == 200 ]] || fail "GET / with X-Forwarded-Proto: https returned $code, expected 200"
pass "GET / with X-Forwarded-Proto: https -> 200"

headers=$(curl_run -s -D - -o /dev/null "http://$web:8080/" || true)
code=$(awk 'NR==1 {print $2}' <<<"$headers" | tr -d '\r')
location=$(grep -i '^location:' <<<"$headers" | tr -d '\r' | sed 's/^[Ll]ocation: //' || true)
[[ $code == 307 ]] || fail "GET / without forwarded proto returned $code, expected 307"
[[ $location == https://* ]] || fail "GET / without forwarded proto redirected to '$location', expected https://"
pass "GET / without forwarded proto -> 307 to https"

login_url="http://$web:8080/account/login"
login_response=$(curl_run -s -i -H "X-Forwarded-Proto: https" "$login_url" || true)
login_headers=$(sed '/^\r\?$/q' <<<"$login_response" | tr -d '\r')
login_body=$(sed '1,/^\r\?$/d' <<<"$login_response")
antiforgery_cookie=$(grep -i '^set-cookie: \.AspNetCore\.Antiforgery\.' <<<"$login_headers" | head -n1 | sed -E 's/^[Ss]et-[Cc]ookie: ([^;]*).*/\1/' || true)
token=$(grep -o '<input[^>]*__RequestVerificationToken[^>]*>' <<<"$login_body" | grep -o 'value="[^"]*"' | head -n1 | cut -d'"' -f2 || true)
[[ -n $antiforgery_cookie ]] || fail "GET /account/login did not set an antiforgery cookie"
[[ -n $token ]] || fail "GET /account/login form has no __RequestVerificationToken"
pass "GET /account/login issued an antiforgery cookie and form token"

login_post() {
  curl_run -s -o /dev/null -w '%{http_code}' -X POST \
    -H "X-Forwarded-Proto: https" -H "Cookie: $antiforgery_cookie" \
    --data-urlencode "__RequestVerificationToken=$token" \
    --data-urlencode "Email=nobody@example.invalid" \
    --data-urlencode "Password=wrong-password-123" \
    "$login_url" || true
}

# A restart keeps the container's writable layer, so the default key store survives it even without the volume.
docker restart "$web" >/dev/null
wait_ready
post_code=$(login_post)
[[ $post_code == 200 ]] || fail "POST /account/login after docker restart returned $post_code, expected 200 (bad credentials re-render the form)"
pass "POST /account/login after docker restart -> 200"

# Replacing the container is what loses the writable layer; this is the case the shared key volume exists for.
docker rm -f "$web" >/dev/null
docker run "${web_args[@]}" "$image" >/dev/null
wait_ready
post_code=$(login_post)
if [[ $control -eq 1 ]]; then
  # Without shared keys the new container cannot validate the token, so this rejection is the expected result.
  [[ $post_code == 400 ]] || fail "control: POST /account/login after container replacement without shared keys returned $post_code, expected 400"
  pass "control: POST /account/login after container replacement without shared keys -> 400 (antiforgery rejected as expected)"
else
  [[ $post_code == 200 ]] || fail "POST /account/login after container replacement returned $post_code, expected 200 (shared keys should keep the token valid)"
  pass "POST /account/login after container replacement with shared keys -> 200 (antiforgery still valid)"
fi

# Image contract checks run against the same container, so they describe what is actually deployed.
docker exec "$web" test -f /usr/share/zoneinfo/Asia/Taipei \
  || fail "/usr/share/zoneinfo/Asia/Taipei is missing"
pass "Asia/Taipei timezone data present"

migrations=$(docker exec "$web" cat /opt/release/migrations.txt) || fail "/opt/release/migrations.txt is missing"
total_lines=$(grep -c '' <<<"$migrations" || true)
valid_lines=$(grep -cE '^[0-9]{14}_[A-Za-z0-9]+ [0-9a-f]{64}$' <<<"$migrations" || true)
[[ $total_lines -eq $applied && $valid_lines -eq $total_lines ]] \
  || fail "migrations.txt has $total_lines lines ($valid_lines valid), expected $applied valid lines"
pass "migrations.txt lists $applied migrations with source hashes"

release_api=$(docker exec "$web" cat /opt/release/RELEASE_API) || fail "/opt/release/RELEASE_API is missing"
[[ $release_api == 1 ]] || fail "RELEASE_API is '$release_api', expected 1"
pass "RELEASE_API is 1"

docker exec "$web" sh -c 'cd /opt/release/sql && sha256sum -c SHA256SUMS >/dev/null' \
  || fail "/opt/release/sql/SHA256SUMS does not verify"
pass "per-migration SQL matches SHA256SUMS"

uid=$(docker exec "$web" id -u) || fail "cannot read the container user"
[[ $uid == 1654 ]] || fail "web container runs as uid $uid, expected 1654"
pass "web container runs as uid 1654"

invariant=$(docker exec "$web" sh -c 'printf %s "${DOTNET_SYSTEM_GLOBALIZATION_INVARIANT:-}"')
[[ ! $invariant =~ ^[Tt][Rr][Uu][Ee]$ ]] || fail "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT is true; ICU must be used for Asia/Taipei culture data"
pass "ICU globalization is in use"

if [[ $control -eq 1 ]]; then
  echo "all checks passed (control: --control-no-keys)"
else
  echo "all checks passed"
fi
