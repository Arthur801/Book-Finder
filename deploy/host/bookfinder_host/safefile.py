"""Reads regular files without following symlinks.

Why: release metadata and host state are read from paths that a deploy may have just written; a symlink there would
redirect the read to whatever it points at. The kind is checked with lstat and again on the open descriptor.
"""

import os
import stat


class UnsafeFileError(Exception):
    """The path exists but is not a regular file of an acceptable size."""


def read_regular_file(path: str | os.PathLike[str], max_bytes: int) -> bytes:
    """Returns the bytes of a regular file. FileNotFoundError is raised unchanged so callers can tell missing from unsafe."""
    path = os.fspath(path)
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode):
        raise UnsafeFileError(f"not a regular file (or is a symlink): {path}")
    # O_NONBLOCK keeps a FIFO swapped in after lstat from blocking the reader; O_NOFOLLOW turns a swapped symlink into ELOOP.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise UnsafeFileError(f"cannot open safely: {path}: {exc.strerror}") from exc
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise UnsafeFileError(f"not a regular file: {path}")
        if opened.st_size > max_bytes:
            raise UnsafeFileError(f"{path} is {opened.st_size} bytes, larger than {max_bytes}")
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UnsafeFileError(f"{path} grew beyond {max_bytes} bytes while reading")
    return data
