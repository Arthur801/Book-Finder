#!/bin/bash
# Installed on EC2; cron owns scheduling, this script owns serialization and execution.
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
umask 077

mode=${1:-}
case "$mode" in
    daily) module=books_crawler ;;
    pages) module=books_crawler.pages ;;
    *) echo 'usage: run-crawler.sh daily|pages [--scheduled]' >&2; exit 2 ;;
esac
if [[ $# -gt 2 || (${2:-} != '' && ${2:-} != --scheduled) ]]; then
    echo 'usage: run-crawler.sh daily|pages [--scheduled]' >&2
    exit 2
fi

# Only root may edit this shell configuration file.
source "${CRAWLER_CONFIG_FILE:-/etc/book-finder/crawler.conf}"
: "${CRAWLER_IMAGE:?CRAWLER_IMAGE is required}"
: "${AWS_REGION:?AWS_REGION is required}"
: "${DATABASE_URL_PARAMETER:?DATABASE_URL_PARAMETER is required}"

# Optional CA bundle for verify-full (DB_CA_BUNDLE, the same path the web container mounts). Checked before any state
# changes, so a bad path is a configuration error (exit 2) rather than a docker failure after the lock is taken.
# Mode 0644: the crawler container runs as a non-root user and must read the file.
ca_mount=()
if [[ -v DB_CA_BUNDLE ]]; then
    ca_bundle=$DB_CA_BUNDLE
    if [[ ! $ca_bundle =~ ^/[A-Za-z0-9._/-]+$ ]]; then
        echo 'DB_CA_BUNDLE must be an absolute path made of letters, digits, ., _, - and /' >&2
        exit 2
    fi
    if [[ -L $ca_bundle ]]; then
        echo 'DB_CA_BUNDLE must not be a symbolic link' >&2
        exit 2
    fi
    if [[ ! -f $ca_bundle || ! -r $ca_bundle ]]; then
        echo 'DB_CA_BUNDLE must be a readable regular file' >&2
        exit 2
    fi
    ca_mode=$(stat -c %a -- "$ca_bundle")
    if (( (8#$ca_mode & 4) == 0 )); then
        echo 'DB_CA_BUNDLE must be readable by others (mode 0644): the container user must read it' >&2
        exit 2
    fi
    ca_mount=(--mount "type=bind,src=$ca_bundle,dst=$ca_bundle,readonly")
fi

# Operator switch for hosts the source site blocks (EC2). It is not paused: a paused crawler blocks deploys, and the
# deploy reinstalls crawler.cron anyway. CD rewrites only CRAWLER_IMAGE=, so this line survives releases. Unset means
# true; an empty value is a typo, so it is rejected rather than treated as unset.
case "${CRAWLER_ENABLED-true}" in
    true) ;;
    false)
        echo "$(date -u +%FT%TZ) mode=$mode skipped=disabled"
        exit 0
        ;;
    *)
        echo 'CRAWLER_ENABLED must be exactly true or false (unset means true)' >&2
        exit 2
        ;;
esac
state_dir=${CRAWLER_STATE_DIR:-/var/lib/book-finder/crawler}
runtime_dir=${CRAWLER_RUNTIME_DIR:-/run/book-finder}
mkdir -p "$state_dir" "$runtime_dir"
exec 9>"$state_dir/run.lock"
flock 9

# N3: a deploy takes the maintenance lock exclusively while it migrates, so the crawler holds it shared for its whole
# run. The lock is taken before state is read: reading first would let a deploy pause and migrate in between.
maintenance_lock=${DB_MAINTENANCE_LOCK:-/var/lib/book-finder/db-maintenance.lock}
maintenance_wait_s=${DB_MAINTENANCE_WAIT_S:-7200}
mkdir -p "$(dirname "$maintenance_lock")"
exec 8>>"$maintenance_lock"
if ! flock -s -w "$maintenance_wait_s" 8; then
    echo "$(date -u +%FT%TZ) mode=$mode maintenance=busy waited_s=$maintenance_wait_s" >&2
    exit 3
fi

# Missing state means a host that has not been bootstrapped yet, which keeps the pre-CD behaviour; a damaged state
# file fails closed, because a crawler that cannot read the pause flag must not run.
db_state_file=${BOOKFINDER_STATE_FILE:-/var/lib/book-finder/state.json}
if [[ -e $db_state_file ]]; then
    if ! gate=$(python3 -I -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
if state["crawler"]["paused"] is not None:
    print("paused")
elif state["schema"]["dirty"] is True:
    print("dirty")
else:
    print("ok")
' "$db_state_file"); then
        echo "$(date -u +%FT%TZ) mode=$mode state=unreadable" >&2
        exit 2
    fi
    if [[ $gate != ok ]]; then
        echo "$(date -u +%FT%TZ) mode=$mode skipped=$gate"
        exit 6
    fi
else
    echo "$(date -u +%FT%TZ) mode=$mode state=absent"
fi

now=$(date +%s)
state_file="$state_dir/pages-last-success"
if [[ "$mode" == pages && ${2:-} == --scheduled && -f "$state_file" ]]; then
    last=$(cat "$state_file")
    if [[ ! "$last" =~ ^[0-9]+$ ]]; then
        echo 'invalid pages schedule state; inspect pages-last-success' >&2
        exit 2
    fi
    if (( now - last < 259200 )); then
        echo "$(date -u +%FT%TZ) mode=pages schedule=not-due"
        exit 0
    fi
fi

env_file=$(mktemp "$runtime_dir/crawler-env.XXXXXX")
trap 'rm -f "$env_file"' EXIT
echo "$(date -u +%FT%TZ) mode=$mode container=start image=$CRAWLER_IMAGE"
# Fetch only the database secret with the host IAM role. Never print its value.
database_url=$(aws ssm get-parameter --region "$AWS_REGION" \
    --name "$DATABASE_URL_PARAMETER" --with-decryption \
    --query Parameter.Value --output text)
if [[ -z "$database_url" || "$database_url" == None || "$database_url" == *$'\n'* || "$database_url" == *$'\r'* ]]; then
    echo 'database URL parameter is empty or contains a newline' >&2
    exit 2
fi
printf 'DATABASE_URL=%s\n' "$database_url" >"$env_file"
unset database_url

# A bind mount survives --rm; UID 10001 is the image's non-root user.
mkdir -p "$state_dir/artifacts"
chown 10001:10001 "$state_dir/artifacts"
set +e
docker run --rm --pull=never --init \
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 \
    --env-file "$env_file" --env CRAWLER_FETCHER=curl \
    --mount "type=bind,src=$state_dir/artifacts,dst=/app/crawler/artifacts" \
    "${ca_mount[@]}" \
    "$CRAWLER_IMAGE" "$module"
result=$?
set -e
echo "$(date -u +%FT%TZ) mode=$mode container=end exit_code=$result"
if [[ "$mode" == pages && "$result" == 0 ]]; then
    printf '%s\n' "$now" >"$state_file.tmp"
    mv "$state_file.tmp" "$state_file"
fi
exit "$result"
