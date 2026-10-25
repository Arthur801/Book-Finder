#!/bin/bash
# Runs one crawler container on this host. The database is reached through an SSH tunnel to RDS via the EC2 host.
# Usage: run-local-crawler.sh daily|first_book|pages|kingstone
# Configuration: CRAWLER_LOCAL_CONF (default ~/.config/book-finder/crawler-local.conf); see README for keys and exit codes.
#
# Exit codes: 0, 1, 2 are the container's own. The runner uses:
#   6 skipped by the EC2 deploy state (paused or dirty)     10 configuration or usage error
#   11 another local run holds run.lock                      12 EC2 deploy state unreadable (fail closed)
#   13 a writer container is present (ORPHAN_WRITER or busy) 14 writer could not be confirmed stopped (ORPHAN_WRITER)
#   15 DB secret unavailable or invalid                      16 SSH tunnel did not forward
#   17 database URL rewrite failed                           18 docker unavailable
#   20 watchdog stopped the writer at the hard limit         21 interrupted by a signal (writer stopped first)
#   22 the docker client ended while the container still ran; the watchdog stopped it (CLIENT_LOST)
#
# Lifecycle failures outside the container (13, 14, 20, 21, 22) also print one "ALERT reasons=... mode=... last_run=..." line
# on stderr and write this runner's terminal record to $CRAWLER_LOCAL_ARTIFACTS_DIR/runner/<mode>-last-run.json. The
# container's own results (0, 1, 2, and Docker's other codes) belong to the crawler and get no runner record.
set -uo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
helper="$script_dir/runner_support.py"
name=book-finder-crawler-active
label=com.bookfinder.role=catalog-crawler
ca_container_path=/etc/book-finder/rds-ca-bundle.pem
artifacts_container_path=/app/crawler/artifacts
path_re='^/[A-Za-z0-9._/-]+$'
alias_re='^[A-Za-z0-9][A-Za-z0-9._-]*$'
host_re='^[A-Za-z0-9][A-Za-z0-9.-]*$'
image_re='^[A-Za-z0-9][A-Za-z0-9._/:@-]*$'
account_re='^[A-Za-z0-9_.-]+$'
region_re='^[a-z0-9-]+$'
posint_re='^[1-9][0-9]*$'

mode=${1:-}
provider=
interrupted=0
container_started=0
tunnel_pid=
run_pid=
env_file=
cidfile=
run_id=
started_at=

info() { printf '%s mode=%s %s\n' "$(date -u +%FT%TZ)" "$mode" "$*"; }
fail() {
    local code=$1
    shift
    printf '%s mode=%s %s\n' "$(date -u +%FT%TZ)" "$mode" "$*" >&2
    exit "$code"
}

if [[ $# -ne 1 ]]; then
    echo 'usage: run-local-crawler.sh daily|first_book|pages|kingstone' >&2
    exit 10
fi
case $mode in
    daily | first_book | pages) provider=BOOKS_COM_TW ;;
    kingstone) provider=KINGSTONE ;;
    *)
        echo 'usage: run-local-crawler.sh daily|first_book|pages|kingstone' >&2
        exit 10
        ;;
esac
IFS= read -r run_id </proc/sys/kernel/random/uuid || run_id=
started_at=$(date -u +%FT%TZ)

# Lifecycle failure outside the container: the ALERT line, this runner's terminal record, and the same record as one
# JSON line on stdout. The record is best effort: a failed write is reported, and the exit code does not change.
# Arguments: exit code, reason, alert reasons, container name (may be empty), container id (may be empty).
record_terminal() {
    local code=$1 reason=$2 alerts=$3 c_name=${4-} c_id=${5-}
    local artifacts=${CRAWLER_LOCAL_ARTIFACTS_DIR-} last_run=none
    local args
    if [[ -n $artifacts ]]; then last_run="$artifacts/runner/$mode-last-run.json"; fi
    printf 'ALERT reasons=%s mode=%s last_run=%s\n' "$alerts" "$mode" "$last_run" >&2
    if [[ $last_run == none ]]; then
        printf 'WARNING: runner record was not written (no artifacts directory is configured)\n' >&2
        return 0
    fi
    args=(write-runner-record --path "$last_run" --run-id "$run_id" --mode "$mode" --exit-code "$code"
        --reason "$reason" --alert-reasons "$alerts" --started-at "$started_at")
    if [[ -n $c_name ]]; then args+=(--container-name "$c_name"); fi
    if [[ -n $c_id ]]; then args+=(--container-id "$c_id"); fi
    mkdir -p -- "$(dirname -- "$last_run")" 2>/dev/null || true
    if ! python3 -I "$helper" "${args[@]}"; then
        printf 'WARNING: runner record was not written to %s (the runner directory must exist and be writable by this user)\n' "$last_run" >&2
    fi
}

# The container id from --cidfile, or nothing when the container never reported one.
read_cid() {
    local cid=
    if [[ -n $cidfile && -s $cidfile ]]; then IFS= read -r cid <"$cidfile" || cid=; fi
    if [[ $cid =~ ^[0-9a-f]{12,64}$ ]]; then printf '%s' "$cid"; fi
}

# Runs from the EXIT trap, so shellcheck cannot see the call.
# shellcheck disable=SC2329
cleanup() {
    if [[ -n $tunnel_pid ]]; then
        kill "$tunnel_pid" 2>/dev/null || true
        wait "$tunnel_pid" 2>/dev/null || true
    fi
    if [[ -n $env_file ]]; then rm -f -- "$env_file"; fi
    if [[ -n $cidfile ]]; then rm -f -- "$cidfile"; fi
}
trap cleanup EXIT
# Runs from the INT/TERM trap.
# shellcheck disable=SC2329
on_signal() {
    if (( container_started )); then
        interrupted=1
        return
    fi
    info 'interrupted before the container started'
    record_terminal 21 SIGNAL_STOP signal_stop
    exit 21
}
trap on_signal INT TERM

# --- configuration -----------------------------------------------------------------------------------------------

conf=${CRAWLER_LOCAL_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}/book-finder/crawler-local.conf}
if [[ ! -r $conf ]]; then
    fail 10 'crawler-local.conf is missing or unreadable (set CRAWLER_LOCAL_CONF)'
fi
# The configuration file is the operator-owned shell file named by CRAWLER_LOCAL_CONF.
# shellcheck source=/dev/null
source "$conf"

# The same switch as the EC2 runner. It is read before anything else, so a disabled runner needs no other settings.
case "${CRAWLER_ENABLED-true}" in
    true) ;;
    false)
        info 'skipped=disabled'
        exit 0
        ;;
    *) fail 10 'CRAWLER_ENABLED must be exactly true or false (unset means true)' ;;
esac

valid() {
    local key=$1 pattern=$2
    [[ ${!key-} =~ $pattern ]] || fail 10 "$key is missing or invalid"
}
: "${CRAWLER_RUN_HARD_LIMIT_SECONDS:=9000}"
: "${BOOKS_RUN_HARD_LIMIT_SECONDS:=3600}"
: "${CRAWLER_STOP_GRACE_SECONDS:=30}"
: "${TUNNEL_WAIT_SECONDS:=20}"
: "${CRAWLER_LOCAL_STATE_DIR:=${XDG_STATE_HOME:-$HOME/.local/state}/book-finder-crawler}"
: "${CRAWLER_LOCAL_RUNTIME_DIR:=${XDG_CACHE_HOME:-$HOME/.cache}/book-finder-crawler/run}"

if [[ $mode == kingstone ]]; then
    valid KINGSTONE_CRAWLER_IMAGE "$image_re"
    image=$KINGSTONE_CRAWLER_IMAGE
    hard_limit=$CRAWLER_RUN_HARD_LIMIT_SECONDS
    valid CRAWLER_RUN_HARD_LIMIT_SECONDS "$posint_re"
else
    valid CRAWLER_IMAGE "$image_re"
    image=$CRAWLER_IMAGE
    valid BOOKS_RUN_HARD_LIMIT_SECONDS "$posint_re"
    hard_limit=$BOOKS_RUN_HARD_LIMIT_SECONDS
fi
valid CRAWLER_STOP_GRACE_SECONDS "$posint_re"
valid TUNNEL_WAIT_SECONDS "$posint_re"
valid CRAWLER_LOCAL_ARTIFACTS_DIR "$path_re"
valid EC2_SSH_HOST "$alias_re"
valid EC2_STATE_FILE "$path_re"
valid RDS_ENDPOINT "$host_re"
valid LOCAL_DB_PORT '^[0-9]+$'
if (( LOCAL_DB_PORT < 1024 || LOCAL_DB_PORT > 65535 )); then
    fail 10 'LOCAL_DB_PORT must be between 1024 and 65535'
fi
valid DB_CA_BUNDLE "$path_re"
case ${DB_SECRET_SOURCE-} in
    ssm)
        valid AWS_PROFILE "$account_re"
        valid AWS_REGION "$region_re"
        valid DATABASE_URL_PARAMETER "$path_re"
        ;;
    file) valid DB_SECRET_FILE "$path_re" ;;
    *) fail 10 'DB_SECRET_SOURCE must be ssm or file' ;;
esac

if [[ -L $DB_CA_BUNDLE ]]; then fail 10 'DB_CA_BUNDLE must not be a symbolic link'; fi
if [[ ! -f $DB_CA_BUNDLE || ! -r $DB_CA_BUNDLE ]]; then fail 10 'DB_CA_BUNDLE must be a readable regular file'; fi
ca_mode=$(stat -c %a -- "$DB_CA_BUNDLE")
if (( (8#$ca_mode & 4) == 0 )); then
    fail 10 'DB_CA_BUNDLE must be readable by others (mode 0644): the container user must read it'
fi

# The container runs as UID 10001 (the image's non-root user) and writes its artifacts into this directory.
mkdir -p -- "$CRAWLER_LOCAL_ARTIFACTS_DIR" || fail 10 'CRAWLER_LOCAL_ARTIFACTS_DIR cannot be created'
read -r artifacts_uid artifacts_mode < <(stat -c '%u %a' -- "$CRAWLER_LOCAL_ARTIFACTS_DIR")
if [[ $artifacts_uid != 10001 ]] && (( (8#$artifacts_mode & 2) == 0 )); then
    fail 10 'CRAWLER_LOCAL_ARTIFACTS_DIR must be owned by UID 10001 or world-writable (see README)'
fi

# --- single local run --------------------------------------------------------------------------------------------

mkdir -p -- "$CRAWLER_LOCAL_STATE_DIR" "$CRAWLER_LOCAL_RUNTIME_DIR" || fail 10 'state or runtime directory cannot be created'
chmod 700 -- "$CRAWLER_LOCAL_STATE_DIR" "$CRAWLER_LOCAL_RUNTIME_DIR" || fail 10 'state or runtime directory cannot be restricted'
exec 9>>"$CRAWLER_LOCAL_STATE_DIR/run.lock"
flock -n 9 || fail 11 'run.lock is held by another local crawler run'

# --- EC2 deploy state gate (read-only, over SSH) -----------------------------------------------------------------

# Children must not inherit fd 9, or the lock would outlive this runner. stdin is /dev/null so ssh cannot wait on a tty.
# The deploy host rewrites state.json as root with mode 0600, so the SSH user reads it with non-interactive sudo.
if ! ec2_state=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$EC2_SSH_HOST" sudo -n cat -- "$EC2_STATE_FILE" </dev/null 9>&-); then
    fail 12 'state=unreadable (ssh or sudo -n cat failed; the EC2 deploy state is required)'
fi
if ! gate=$(printf '%s' "$ec2_state" | python3 -I "$helper" state-gate); then
    fail 12 'state=unreadable'
fi
case $gate in
    ok) ;;
    paused | dirty)
        info "skipped=$gate"
        exit 6
        ;;
    *) fail 12 'state=unreadable' ;;
esac
ec2_state=

# --- orphan check ------------------------------------------------------------------------------------------------

if ! writers=$(docker ps -a --filter "label=$label" --format $'{{.Names}}\t{{.State}}'); then
    fail 18 'docker is unavailable; cannot check for an orphan writer'
fi
while IFS=$'\t' read -r w_name w_state; do
    [[ -n $w_name ]] || continue
    case $w_state in
        exited | dead | created)
            docker rm "$w_name" >/dev/null || fail 18 "could not remove stopped container=$w_name"
            info "removed stopped container=$w_name state=$w_state"
            ;;
        *)
            printf '%s mode=%s ORPHAN_WRITER container=%s state=%s: refusing to start\n' \
                "$(date -u +%FT%TZ)" "$mode" "$w_name" "$w_state" >&2
            record_terminal 13 ORPHAN_WRITER orphan "$w_name"
            exit 13
            ;;
    esac
done <<<"$writers"

# --- database secret ---------------------------------------------------------------------------------------------

secret=
case $DB_SECRET_SOURCE in
    ssm)
        secret=$(aws ssm get-parameter --with-decryption --profile "$AWS_PROFILE" --region "$AWS_REGION" \
            --name "$DATABASE_URL_PARAMETER" --query Parameter.Value --output text </dev/null 9>&-) ||
            fail 15 'DB secret could not be read from SSM'
        ;;
    file)
        [[ -f $DB_SECRET_FILE && ! -L $DB_SECRET_FILE ]] || fail 15 'DB_SECRET_FILE must be a regular file, not a symbolic link'
        read -r secret_mode secret_owner < <(stat -c '%a %u' -- "$DB_SECRET_FILE")
        [[ $secret_mode == 600 && $secret_owner == "$(id -u)" ]] ||
            fail 15 'DB_SECRET_FILE must be mode 600 and owned by the current user'
        secret=$(cat -- "$DB_SECRET_FILE") || fail 15 'DB_SECRET_FILE could not be read'
        ;;
esac
if [[ -z $secret || $secret == None || $secret == *$'\r'* ]]; then
    fail 15 'DB secret is empty or malformed'
fi

# --- env file: the secret is written only here, never in argv or output -----------------------------------------

env_file=$(mktemp "$CRAWLER_LOCAL_RUNTIME_DIR/env.XXXXXX") || fail 17 'could not create the env file'
if ! printf '%s' "$secret" | python3 -I "$helper" rewrite-url --port "$LOCAL_DB_PORT" --rds-host "$RDS_ENDPOINT" \
    --ca-path "$ca_container_path" --env-file "$env_file"; then
    fail 17 'DATABASE_URL must be a PostgreSQL URL for the configured RDS endpoint'
fi
secret=

# --- SSH tunnel --------------------------------------------------------------------------------------------------

ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o BatchMode=yes \
    -o ConnectTimeout=20 -L "127.0.0.1:${LOCAL_DB_PORT}:${RDS_ENDPOINT}:5432" "$EC2_SSH_HOST" </dev/null 9>&- &
tunnel_pid=$!
tunnel_ready=0
for (( attempt = 0; attempt < TUNNEL_WAIT_SECONDS * 4; attempt++ )); do
    kill -0 "$tunnel_pid" 2>/dev/null || break
    if python3 -I "$helper" port-ready "$LOCAL_DB_PORT"; then
        tunnel_ready=1
        break
    fi
    sleep 0.25
done
if (( ! tunnel_ready )); then
    fail 16 "SSH tunnel is not forwarding 127.0.0.1:$LOCAL_DB_PORT (ssh exited or the port did not answer)"
fi

# --- writer: watchdog, fencing and cleanup -----------------------------------------------------------------------

# Prints the writer container's state, or "absent". Fails when docker cannot answer.
writer_state() {
    local listing w_name w_state
    listing=$(docker ps -a --filter "label=$label" --format $'{{.Names}}\t{{.State}}') || return 1
    while IFS=$'\t' read -r w_name w_state; do
        if [[ $w_name == "$name" ]]; then
            printf '%s' "$w_state"
            return 0
        fi
    done <<<"$listing"
    printf 'absent'
}

is_running_state() {
    case $1 in
        running | restarting | paused | removing) return 0 ;;
        *) return 1 ;;
    esac
}

# Stops the writer and confirms it. Returns 0 only when docker reports it stopped or gone.
stop_writer() {
    local state i
    state=$(writer_state) || state=unknown
    if [[ $state == paused ]]; then docker unpause "$name" >/dev/null 2>&1 || true; fi
    docker stop -t "$CRAWLER_STOP_GRACE_SECONDS" "$name" >/dev/null 2>&1 || true
    state=$(writer_state) || state=unknown
    if [[ $state == unknown ]] || is_running_state "$state"; then
        docker kill "$name" >/dev/null 2>&1 || true
    fi
    for (( i = 0; i < 50; i++ )); do
        kill -0 "$run_pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$run_pid" 2>/dev/null; then
        kill -KILL "$run_pid" 2>/dev/null || true
    fi
    wait "$run_pid" 2>/dev/null || true
    state=$(writer_state) || return 1
    case $state in
        absent | exited | dead | created) return 0 ;;
        *) return 1 ;;
    esac
}

cidfile=$(mktemp -u "$CRAWLER_LOCAL_RUNTIME_DIR/cid.XXXXXX")
run_args=(run --rm=false --pull=never --init --network host --name "$name"
    --label "$label" --label "com.bookfinder.mode=$mode" --label "com.bookfinder.provider=$provider"
    --cidfile "$cidfile" --env-file "$env_file"
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3
    --mount "type=bind,src=$CRAWLER_LOCAL_ARTIFACTS_DIR,dst=$artifacts_container_path"
    --mount "type=bind,src=$DB_CA_BUNDLE,dst=$ca_container_path,readonly")
if [[ $mode == kingstone ]]; then
    run_args+=(--env "CRAWLER_RUN_HARD_LIMIT_SECONDS=$hard_limit")
else
    run_args+=(--env CRAWLER_FETCHER=curl)
fi
run_args+=("$image")
case $mode in
    daily) run_args+=(books_crawler) ;;
    pages) run_args+=(books_crawler.pages) ;;
    first_book) run_args+=(books_crawler.first_book) ;;
esac

info "container=start image=$image provider=$provider"
container_started=1
docker "${run_args[@]}" </dev/null 9>&- &
run_pid=$!

deadline=$(( $(date +%s) + hard_limit ))
reason=
alerts=
while kill -0 "$run_pid" 2>/dev/null; do
    if (( interrupted )); then
        reason=interrupted
        break
    fi
    if (( $(date +%s) >= deadline )); then
        reason=hard_limit
        break
    fi
    sleep 1
done

state=$(writer_state) || state=unknown
if kill -0 "$run_pid" 2>/dev/null || [[ $state == unknown ]] || is_running_state "$state"; then
    [[ -n $reason ]] || reason=client_exited
    info "watchdog reason=$reason"
    if ! stop_writer; then
        info "ORPHAN_WRITER container=$name could not be confirmed stopped; the next run is refused until it is gone"
        if [[ $reason == hard_limit ]]; then alerts=orphan,hard_limit; else alerts=orphan; fi
        record_terminal 14 ORPHAN_WRITER "$alerts" "$name" "$(read_cid)"
        exit 14
    fi
    if [[ $reason == interrupted ]]; then
        result=21
        record_terminal 21 SIGNAL_STOP signal_stop "$name" "$(read_cid)"
    elif [[ $reason == hard_limit ]]; then
        result=20
        record_terminal 20 HARD_LIMIT hard_limit "$name" "$(read_cid)"
    else
        # The writer ran with no client watching it: an orphan that the watchdog caught, not a hard-limit stop.
        result=22
        record_terminal 22 CLIENT_LOST orphan "$name" "$(read_cid)"
    fi
else
    wait "$run_pid"
    result=$?
fi

state=$(writer_state) || state=unknown
if [[ $state != absent && $state != unknown ]] && ! is_running_state "$state"; then
    docker rm "$name" >/dev/null 2>&1 || info "WARNING: could not remove container=$name; the next run removes it"
fi
info "container=end exit_code=$result"
exit "$result"
