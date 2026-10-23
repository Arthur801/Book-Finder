#!/usr/bin/env bash
# Classification-specific plan for the migration compat check. Sourcing defines functions only.
# Why: compat.sh branches on how production's history relates to the target's. The branch is kept in one pure function so
# the tests can pin each classification's checks without a database, and the report can show which checks applied.

# compat_plan_for CLASSIFICATION
# Prints one tab-separated line per classification-specific check: "run<TAB>NAME" when the check runs, or
# "skip<TAB>NAME<TAB>REASON" when it does not. NAME is the check name compat.sh records in the report.
# Returns 1 for a classification with no plan; divergent is rejected by compat.sh before this is called.
compat_plan_for() {
  case $1 in
    forward | in-sync)
      printf 'run\t%s\n' \
        "target upgrade applied" \
        "upgraded history equals target manifest" \
        "data preserved" \
        "schema matches a fresh install"
      ;;
    schema-ahead)
      printf 'skip\t%s\t%s\n' \
        "target upgrade applied" \
        "schema-ahead: the target bundle is never run, because it would downgrade the newer production schema"
      printf 'skip\t%s\t%s\n' \
        "upgraded history equals target manifest" \
        "schema-ahead: production keeps its newer history, so it is checked as applied history unchanged by target"
      printf 'skip\t%s\t%s\n' \
        "schema matches a fresh install" \
        "schema-ahead: production keeps the newer schema, which a fresh install of the target cannot match; schema unchanged by target is checked instead"
      printf 'run\t%s\n' \
        "applied history unchanged by target" \
        "data preserved" \
        "schema unchanged by target"
      ;;
    *)
      return 1
      ;;
  esac
}
