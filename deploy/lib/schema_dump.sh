#!/usr/bin/env bash
# Schema dump normalizer for the migration compat check. Sourcing defines functions only.
# Why: the fresh-install comparison is only meaningful when both dumps are real schemas. A failed or empty dump must never
# compare equal to another empty dump, so every failure here is an error and the caller records a FAIL.

# schema_dump_normalized LABEL COMMAND [ARG...]
# Runs COMMAND, which must print pg_dump output on stdout, and prints the normalized schema on stdout.
# On failure it prints one reason line on stderr and returns 1. Failures: the command exits non-zero (its stderr tail is
# quoted), the raw output has no CREATE TABLE line, the filter itself errors, or the normalized text has no CREATE TABLE.
# Partial output from a failed command is never printed.
schema_dump_normalized() {
  local label=$1 tmp raw err normalized status
  shift
  tmp=$(mktemp -d) || {
    echo "could not create a temp directory for $label" >&2
    return 1
  }
  raw="$tmp/raw.sql"
  err="$tmp/stderr.txt"
  normalized="$tmp/normalized.sql"

  if ! "$@" >"$raw" 2>"$err"; then
    echo "pg_dump failed for $label: $(tail -n 5 "$err" | tr '\n' ' ' | sed 's/ *$//')" >&2
    rm -rf "$tmp"
    return 1
  fi

  # The raw dump must contain a table before "no lines after filtering" can be treated as a legitimate empty result.
  grep -q '^CREATE TABLE ' "$raw"
  status=$?
  if [[ $status -ne 0 ]]; then
    if [[ $status -eq 1 ]]; then
      echo "pg_dump for $label produced no CREATE TABLE statements" >&2
    else
      echo "could not scan the pg_dump output for $label (grep exit $status)" >&2
    fi
    rm -rf "$tmp"
    return 1
  fi

  # Exit 1 from grep -v means every line was filtered out, which is acceptable here; any other status is an error.
  grep -vE '^(--|\\restrict|\\unrestrict|SET |SELECT pg_catalog\.set_config|$)' "$raw" >"$normalized"
  status=$?
  if [[ $status -ne 0 && $status -ne 1 ]]; then
    echo "could not normalize the pg_dump output for $label (grep exit $status)" >&2
    rm -rf "$tmp"
    return 1
  fi

  if ! grep -q '^CREATE TABLE ' "$normalized"; then
    echo "normalized pg_dump output for $label has no CREATE TABLE statements" >&2
    rm -rf "$tmp"
    return 1
  fi

  cat "$normalized"
  rm -rf "$tmp"
}
