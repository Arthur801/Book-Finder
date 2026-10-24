#!/usr/bin/env bash
# Reviewed contract allowance for compat.sh (Docs/testing/test-plan.md 6.1). A contract migration may drop a column or
# rewrite a table's values, which the data check would otherwise report as lost data. deploy/migration-test/contract/<id>/
# names exactly what that migration may change: allow.tsv lists the directives, verify.sql must return zero rows after the
# upgrade. The rules live here, not in compat.sh, so deploy/tests can pin them without a database.
#
# allow.tsv directives (tab-separated, '#' comments and blank lines allowed; anything else is an error):
#   drop-column<TAB>table<TAB>column
#   rewrite<TAB>table

# Lowercase SQL identifiers only. Table and column names reach SQL text, so they are checked before any use.
contract_identifier_ok() {
  [[ $1 =~ ^[a-z_][a-z0-9_]{0,62}$ ]]
}

# Prints the migration ids that have an allowance directory, sorted. Nothing is printed when the root does not exist.
contract_allowance_ids() {
  local root=$1 dir
  [[ -d $root ]] || return 0
  for dir in "$root"/*/; do
    [[ -d $dir ]] || continue
    basename "$dir"
  done | LC_ALL=C sort
}

# Returns 0 when the migration id is in the comma-separated pending list (empty when nothing is pending).
contract_allowance_is_pending() {
  local id=$1 pending_csv=$2
  case ",$pending_csv," in
    *",$id,"*) return 0 ;;
  esac
  return 1
}

# Parses one allow.tsv. Prints the normalized directives: "drop-column<TAB>table<TAB>column" or "rewrite<TAB>table".
# Any other directive, a wrong field count or a bad identifier returns 1 with the line number on stderr.
contract_allowance_parse() {
  local file=$1 line_no=0 line tabs directive table column
  while IFS= read -r line || [[ -n $line ]]; do
    line_no=$((line_no + 1))
    [[ -z $line || $line == \#* ]] && continue
    tabs=${line//[^$'\t']/}
    IFS=$'\t' read -r directive table column <<<"$line"
    case $directive in
      drop-column)
        if [[ ${#tabs} -ne 2 ]] || ! contract_identifier_ok "$table" || ! contract_identifier_ok "$column"; then
          echo "line $line_no: drop-column needs exactly a table and a column name, both lowercase identifiers" >&2
          return 1
        fi
        printf 'drop-column\t%s\t%s\n' "$table" "$column"
        ;;
      rewrite)
        if [[ ${#tabs} -ne 1 ]] || ! contract_identifier_ok "$table"; then
          echo "line $line_no: rewrite needs exactly one table name, a lowercase identifier" >&2
          return 1
        fi
        printf 'rewrite\t%s\n' "$table"
        ;;
      *)
        echo "line $line_no: unknown directive '$directive' (allowed: drop-column, rewrite)" >&2
        return 1
        ;;
    esac
  done <"$file"
}

# Prints one problem per line for the drop-column directives in a normalized allowance (file 1), checked against the
# "table<TAB>column" lists before (file 2) and after (file 3) the upgrade. An allowed column that still exists after the
# upgrade is a problem, and so is one that did not exist before: the allowance must match the migration exactly.
contract_drop_problems() {
  local allow=$1 before=$2 after=$3 directive table column
  local -A before_cols=() after_cols=()
  while IFS=$'\t' read -r table column; do
    before_cols[$table.$column]=1
  done <"$before"
  while IFS=$'\t' read -r table column; do
    after_cols[$table.$column]=1
  done <"$after"
  while IFS=$'\t' read -r directive table column; do
    [[ $directive == drop-column ]] || continue
    if [[ -z ${before_cols[$table.$column]+x} ]]; then
      echo "allowance names drop-column $table.$column, which does not exist before the upgrade"
    elif [[ -n ${after_cols[$table.$column]+x} ]]; then
      echo "allowed drop-column $table.$column still exists after the upgrade"
    fi
  done <"$allow"
}

# Prints "pass" when the verify.sql result has no rows, "fail" otherwise. Arguments: row count.
contract_verify_verdict() {
  if [[ $1 -eq 0 ]]; then
    echo pass
  else
    echo fail
  fi
}
