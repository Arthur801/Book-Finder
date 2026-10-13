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
state_dir=${CRAWLER_STATE_DIR:-/var/lib/book-finder/crawler}
runtime_dir=${CRAWLER_RUNTIME_DIR:-/run/book-finder}
mkdir -p "$state_dir" "$runtime_dir"
exec 9>"$state_dir/run.lock"
flock 9

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
    "$CRAWLER_IMAGE" "$module"
result=$?
set -e
echo "$(date -u +%FT%TZ) mode=$mode container=end exit_code=$result"
if [[ "$mode" == pages && "$result" == 0 ]]; then
    printf '%s\n' "$now" >"$state_file.tmp"
    mv "$state_file.tmp" "$state_file"
fi
exit "$result"
