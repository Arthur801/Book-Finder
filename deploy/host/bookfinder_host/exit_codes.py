"""Exit codes shared by every host command; the CD workflow maps these to job outcomes.

Why: one table keeps the plan in docs and the code from drifting apart.
"""

OK = 0
ROLLED_BACK = 1
BAD_INPUT = 2  # bad input, divergent chain, or release_api outside the host range
DRIFT = 3  # drift, busy lock, bootstrap required, or a stale expectation (CAS)
FAILED_MIGRATION = 4
FAILED_DOWN = 5
DIRTY = 6
PARTIAL_CRAWLER = 7
INDETERMINATE = 8

# History stores a result name next to the exit code; these names are part of the on-disk format.
RESULT_BY_EXIT = {
    OK: "ok",
    ROLLED_BACK: "rolled-back",
    BAD_INPUT: "rejected",
    DRIFT: "rejected",
    FAILED_MIGRATION: "failed-migration",
    FAILED_DOWN: "failed-down",
    DIRTY: "rejected",
    PARTIAL_CRAWLER: "partial-crawler",
    INDETERMINATE: "rejected",
}
