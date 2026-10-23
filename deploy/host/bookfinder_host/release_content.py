"""Validation of the release directory extracted from a web image (plan section 5, step 2).

Why: the directory is written by root and later passed to docker compose, so it must contain only plain files and
directories. A symlink, device or fifo is refused before anything is read through it, because docker cp without -L
copies a link as a link that would point into the host.
"""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from bookfinder_host.safefile import UnsafeFileError, read_regular_file

MAX_RELEASE_BYTES = 2 * 1024 * 1024
MAX_COMPOSE_BYTES = 256 * 1024
COMPOSE_FILE = "compose.prod.yaml"
REQUIRED_FILES = (COMPOSE_FILE, "migrations.txt", "RELEASE_API")


class ReleaseRejected(Exception):
    """The release directory contains something the host refuses to use."""


@dataclass(frozen=True)
class ReleaseContent:
    compose_sha256: str


def validate_tree(root: Path) -> ReleaseContent:
    root_mode = os.lstat(root).st_mode
    if not stat.S_ISDIR(root_mode):
        raise ReleaseRejected("release root is not a directory")
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            info = os.lstat(path)
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                # Symlinks are listed among dirnames or filenames by os.walk; they are refused here, never followed.
                raise ReleaseRejected(f"not a regular file or directory: {os.path.relpath(path, root)}")
            total += info.st_size
            if total > MAX_RELEASE_BYTES:
                raise ReleaseRejected(f"release is larger than {MAX_RELEASE_BYTES} bytes")
    for name in REQUIRED_FILES:
        path = root / name
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                raise ReleaseRejected(f"{name} is not a regular file")
        except FileNotFoundError as exc:
            raise ReleaseRejected(f"{name} is missing") from exc
    return ReleaseContent(compose_sha256=compose_sha256_of(root))


def compose_sha256_of(release_dir: str | os.PathLike[str]) -> str:
    """Hash of the compose file in an installed release; a symlinked release directory is refused."""
    directory = os.fspath(release_dir)
    if os.path.islink(directory) or not os.path.isdir(directory):
        raise UnsafeFileError(f"release directory is not a plain directory: {directory}")
    data = read_regular_file(os.path.join(directory, COMPOSE_FILE), MAX_COMPOSE_BYTES)
    return hashlib.sha256(data).hexdigest()
