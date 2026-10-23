#!/usr/bin/env bash
# Helpers for release migration manifests: one "<id> <source_hash>" line per migration, ascending by id.
# Why: the host and compat scripts must agree on what a manifest is and how two manifests relate, so the rules live
# in one sourced file. Sourcing defines functions only; nothing runs and nothing is written at source time.

MANIFEST_MAX_BYTES=65536
MANIFEST_LINE_RE='^[0-9]{14}_[A-Za-z0-9]+ [0-9a-f]{64}$'

manifest_validate_file() {
  local path=$1
  local -a lines
  local line id previous=""
  local size last_byte

  # A symlink is rejected even when it points at a valid file: the manifest must be the file that was inspected.
  if [[ ! -f $path || -L $path ]]; then
    echo "manifest is not a regular file (or is a symlink): $path" >&2
    return 1
  fi

  size=$(wc -c <"$path")
  size=${size//[[:space:]]/}
  if ((size > MANIFEST_MAX_BYTES)); then
    echo "manifest is $size bytes, larger than $MANIFEST_MAX_BYTES: $path" >&2
    return 1
  fi

  # Every line must end with a newline, so "wc -l" and the line-by-line reads below agree.
  if ((size > 0)); then
    last_byte=$(tail -c1 "$path" | od -An -tx1 | tr -d ' ')
    if [[ $last_byte != 0a ]]; then
      echo "manifest does not end with a newline: $path" >&2
      return 1
    fi
  fi

  mapfile -t lines <"$path"
  # Ids are compared bytewise: a locale-aware sort could reorder the underscore relative to digits.
  local LC_ALL=C
  for line in "${lines[@]}"; do
    if [[ ! $line =~ $MANIFEST_LINE_RE ]]; then
      echo "malformed manifest line in $path: $line" >&2
      return 1
    fi
    id=${line%% *}
    if [[ $id == "$previous" ]]; then
      echo "duplicate migration id in $path: $id" >&2
      return 1
    fi
    if [[ -n $previous && ! $id > $previous ]]; then
      echo "migration ids are not ascending in $path: $id after $previous" >&2
      return 1
    fi
    previous=$id
  done
  return 0
}

manifest_schema_digest() {
  local digest
  digest=$(sha256sum "$1") || return 1
  printf 'sha256:%s\n' "${digest%% *}"
}

# Prints "<shared-prefix-length> <applied-count> <target-count>" for two manifests compared line by line.
_manifest_prefix_summary() {
  local -a applied_lines target_lines
  local index=0
  mapfile -t applied_lines <"$1" || return 1
  mapfile -t target_lines <"$2" || return 1
  while ((index < ${#applied_lines[@]} && index < ${#target_lines[@]})) && [[ ${applied_lines[index]} == "${target_lines[index]}" ]]; do
    index=$((index + 1))
  done
  printf '%s %s %s\n' "$index" "${#applied_lines[@]}" "${#target_lines[@]}"
}

manifest_classify() {
  local shared applied_count target_count
  read -r shared applied_count target_count < <(_manifest_prefix_summary "$1" "$2") || return 1

  if ((shared == applied_count && shared == target_count)); then
    echo in-sync
  elif ((shared == applied_count && applied_count < target_count)); then
    echo forward
  elif ((shared == target_count && target_count < applied_count)); then
    echo schema-ahead
  else
    echo divergent
  fi
}

manifest_pending() {
  local classification shared applied_count target_count index
  local -a target_lines
  classification=$(manifest_classify "$1" "$2") || return 1
  case $classification in
    in-sync | forward) ;;
    *)
      echo "manifest_pending needs a forward or in-sync pair, got $classification" >&2
      return 1
      ;;
  esac
  read -r shared applied_count target_count < <(_manifest_prefix_summary "$1" "$2") || return 1
  mapfile -t target_lines <"$2" || return 1
  for ((index = applied_count; index < target_count; index++)); do
    printf '%s\n' "${target_lines[index]}"
  done
}
