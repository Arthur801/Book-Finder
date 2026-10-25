"""Two-process tests for bookfinder_host.locks.

Why: the deploy lock and the crawler's shared lock must exclude each other across processes; a single-process test
cannot show that, because flock state is per open file description.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from bookfinder_host import locks
from bookfinder_host.ports import SystemClock
from bookfinder_host.testing import FakeClock

HOST_DIR = Path(__file__).resolve().parents[2] / "host"


def holder(path: Path, mode: str, seconds: float) -> subprocess.Popen:
    """Starts a child process that takes the lock, announces it on stdout, and holds it for a while."""
    script = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(HOST_DIR)!r})
        from bookfinder_host import locks
        from bookfinder_host.ports import SystemClock
        ctx = locks.{mode}({str(path)!r}, 10, SystemClock())
        ctx.__enter__()
        print("held", flush=True)
        time.sleep({seconds})
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "held"
    return child


def test_exclusive_times_out_while_another_process_holds_shared(tmp_path):
    lock = tmp_path / "deploy.lock"
    child = holder(lock, "shared", 3)
    try:
        with pytest.raises(locks.LockTimeout), locks.exclusive(lock, timeout_s=0.3, clock=SystemClock()):
            pass
    finally:
        child.kill()
        child.wait()


def test_shared_times_out_while_another_process_holds_exclusive(tmp_path):
    lock = tmp_path / "deploy.lock"
    child = holder(lock, "exclusive", 3)
    try:
        with pytest.raises(locks.LockTimeout), locks.shared(lock, timeout_s=0.3, clock=SystemClock()):
            pass
    finally:
        child.kill()
        child.wait()


def test_two_shared_holders_coexist(tmp_path):
    lock = tmp_path / "deploy.lock"
    child = holder(lock, "shared", 3)
    try:
        with locks.shared(lock, timeout_s=0.3, clock=SystemClock()):
            pass
    finally:
        child.kill()
        child.wait()


def test_exclusive_succeeds_after_holder_exits(tmp_path):
    lock = tmp_path / "deploy.lock"
    child = holder(lock, "exclusive", 0)
    child.wait(timeout=10)
    with locks.exclusive(lock, timeout_s=2, clock=SystemClock()):
        pass


def test_timeout_uses_injected_clock_so_tests_do_not_sleep(tmp_path, monkeypatch):
    lock = tmp_path / "deploy.lock"
    # Holding the lock on a second descriptor in this process conflicts with a new flock on another descriptor.
    import fcntl
    import os

    blocker = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(blocker, fcntl.LOCK_EX)
    try:
        clock = FakeClock()
        with pytest.raises(locks.LockTimeout), locks.exclusive(lock, timeout_s=1.0, clock=clock):
            pass
        assert clock.monotonic() >= 1.0
    finally:
        os.close(blocker)


@pytest.mark.parametrize("timeout_s", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_rejects_non_finite_or_non_positive_timeout(tmp_path, timeout_s):
    with pytest.raises(ValueError), locks.exclusive(tmp_path / "deploy.lock", timeout_s=timeout_s, clock=FakeClock()):
        pass


def test_lock_file_symlink_is_refused(tmp_path):
    real = tmp_path / "real.lock"
    real.write_text("")
    link = tmp_path / "deploy.lock"
    link.symlink_to(real)
    with pytest.raises(OSError), locks.exclusive(link, timeout_s=0.1, clock=FakeClock()):
        pass


def test_catalog_migration_lock_key_is_the_agreed_value():
    # The crawler side (crawler/catalog_core/migration_lock.py) must hold the same bigint. This pins the deploy side;
    # the cross-module comparison is added when the crawler's constant is on the branch.
    assert locks.CATALOG_MIGRATION_LOCK_KEY == 2026102501
