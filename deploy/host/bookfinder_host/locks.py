"""flock-based lock helpers with polling, so a timeout is a real, bounded wait.

Why: a blocking flock cannot time out, and the host must answer "busy" (exit 3) instead of hanging an SSH session.
Polling with LOCK_NB and an injected clock gives a deadline that tests can drive without sleeping.
"""

import fcntl
import math
import os
from collections.abc import Iterator
from contextlib import contextmanager

from bookfinder_host.ports import Clock

POLL_INTERVAL_S = 0.05

# The database advisory lock that serialises the catalog migration against the crawler (plan v12 §8, item 1).
# Must equal the key in crawler/catalog_core/migration_lock.py (the crawler takes it shared; the deploy's lock holder
# takes it exclusive for the whole forward migration). The deploy side is pinned by a test; the cross-module check
# is added when the crawler side lands.
CATALOG_MIGRATION_LOCK_KEY = 2026102501


class LockTimeout(Exception):
    """The lock stayed busy until the deadline."""


@contextmanager
def _flocked(path: str | os.PathLike[str], mode: int, timeout_s: float, clock: Clock) -> Iterator[None]:
    # A NaN deadline never expires, so a non-finite or non-positive timeout must be refused before any wait starts.
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError(f"timeout_s must be a finite number greater than zero, got {timeout_s!r}")
    # O_NOFOLLOW makes a symlink planted at the lock path fail the open instead of locking its target.
    fd = os.open(os.fspath(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        deadline = clock.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if clock.monotonic() >= deadline:
                    raise LockTimeout(f"lock is busy: {os.fspath(path)}") from None
                clock.sleep(POLL_INTERVAL_S)
        yield
    finally:
        # Closing the descriptor is what releases the flock.
        os.close(fd)


def exclusive(path: str | os.PathLike[str], timeout_s: float, clock: Clock):
    return _flocked(path, fcntl.LOCK_EX, timeout_s, clock)


def shared(path: str | os.PathLike[str], timeout_s: float, clock: Clock):
    return _flocked(path, fcntl.LOCK_SH, timeout_s, clock)
