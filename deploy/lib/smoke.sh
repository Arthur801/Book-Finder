#!/usr/bin/env bash
# Helpers shared by deploy/smoke/web-smoke.sh and deploy/migration-test/compat.sh. Sourcing defines functions only.
# Why: both scripts must start the same pgvector image, use the same internal network and HTTP client and send the same
# forwarded-proto contract, so a check that passes in one cannot quietly mean something else in the other.
# Functions return non-zero instead of exiting; each caller decides whether a failure is fatal.

# Digest-pinned so the HTTP client cannot change under the check.
SMOKE_CURL_IMAGE="curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777"

smoke_random_hex() {
  od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'
}

# Same database image as compose.yaml, so the smoke tests do not drift from the local setup.
smoke_db_image() {
  sed -n 's/^[[:space:]]*image:[[:space:]]*\(pgvector\/pgvector:[^[:space:]]*\)[[:space:]]*$/\1/p' "$1/compose.yaml" | head -n1
}

# Internal network: containers on it have no route to the internet. A few random subnets are tried in case one overlaps.
# Sets SMOKE_SUBNET on success.
smoke_create_network() {
  local name=$1 octet
  SMOKE_SUBNET=""
  for _ in 1 2 3 4 5; do
    octet=$((100 + RANDOM % 100))
    if docker network create --internal --subnet "172.30.$octet.0/24" "$name" >/dev/null 2>&1; then
      # Read by the caller after a successful return, so shellcheck cannot see the use.
      # shellcheck disable=SC2034
      SMOKE_SUBNET="172.30.$octet.0/24"
      return 0
    fi
  done
  return 1
}

# Arguments: container, network, image. POSTGRES_PASSWORD must be exported; it is passed by name only.
smoke_start_db() {
  local container=$1 network=$2 image=$3
  docker run -d --name "$container" --network "$network" \
    -e POSTGRES_DB=book_finder -e POSTGRES_USER=book_finder_dev -e POSTGRES_PASSWORD \
    "$image" >/dev/null || return 1

  # The entrypoint starts a temporary server on the Unix socket only; -h 127.0.0.1 waits for the real server.
  for _ in $(seq 60); do
    if docker exec "$container" pg_isready -h 127.0.0.1 -U book_finder_dev -d book_finder >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Arguments: network, then curl arguments.
smoke_curl() {
  local network=$1
  shift
  docker run --rm --network "$network" "$SMOKE_CURL_IMAGE" --silent --show-error --max-time 15 "$@"
}

# Polls GET / through the forwarded-proto contract. Returns 0 on 200, 2 when the container stopped, 1 on timeout.
# SMOKE_LAST_STATUS holds the last HTTP status ("" if none).
smoke_wait_ready() {
  local network=$1 container=$2 code=""
  SMOKE_LAST_STATUS=""
  for _ in $(seq 60); do
    if [[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) != true ]]; then
      return 2
    fi
    code=$(smoke_curl "$network" -H "X-Forwarded-Proto: https" -o /dev/null -w '%{http_code}' "http://$container:8080/" || true)
    # Read by the caller for its failure message.
    # shellcheck disable=SC2034
    SMOKE_LAST_STATUS=$code
    [[ $code == 200 ]] && return 0
    sleep 1
  done
  return 1
}

# Fetches the login form. Sets SMOKE_ANTIFORGERY_COOKIE and SMOKE_FORM_TOKEN.
# Returns 1 when the antiforgery cookie is missing and 2 when the form has no request verification token.
smoke_fetch_login_form() {
  local network=$1 container=$2 response headers body
  response=$(smoke_curl "$network" -s -i -H "X-Forwarded-Proto: https" "http://$container:8080/account/login" || true)
  headers=$(sed '/^\r\?$/q' <<<"$response" | tr -d '\r')
  body=$(sed '1,/^\r\?$/d' <<<"$response")
  SMOKE_ANTIFORGERY_COOKIE=$(grep -i '^set-cookie: \.AspNetCore\.Antiforgery\.' <<<"$headers" | head -n1 | sed -E 's/^[Ss]et-[Cc]ookie: ([^;]*).*/\1/' || true)
  SMOKE_FORM_TOKEN=$(grep -o '<input[^>]*__RequestVerificationToken[^>]*>' <<<"$body" | grep -o 'value="[^"]*"' | head -n1 | cut -d'"' -f2 || true)
  [[ -n $SMOKE_ANTIFORGERY_COOKIE ]] || return 1
  [[ -n $SMOKE_FORM_TOKEN ]] || return 2
}

# Posts bad credentials with the cookie and token from smoke_fetch_login_form; prints the HTTP status.
# Bad credentials re-render the form (200); a rejected antiforgery token gives 400.
smoke_post_bad_login() {
  local network=$1 container=$2
  smoke_curl "$network" -s -o /dev/null -w '%{http_code}' -X POST \
    -H "X-Forwarded-Proto: https" -H "Cookie: $SMOKE_ANTIFORGERY_COOKIE" \
    --data-urlencode "__RequestVerificationToken=$SMOKE_FORM_TOKEN" \
    --data-urlencode "Email=nobody@example.invalid" \
    --data-urlencode "Password=wrong-password-123" \
    "http://$container:8080/account/login" || true
}

# Returns 0 when the container log has no unhandled exception and no host startup failure.
smoke_logs_clean() {
  local logs
  logs=$(docker logs "$1" 2>&1 || true)
  ! grep -qE 'Unhandled exception|fail: Microsoft\.Hosting\.Lifetime' <<<"$logs"
}
