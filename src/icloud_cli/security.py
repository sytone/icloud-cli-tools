"""Private local storage helpers (POSIX modes; Windows relies on user ACLs)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TextIO

import click


class StorageSecurityError(click.ClickException):
    """A sensitive path is unsafe to use."""


def _check_path(path: Path) -> None:
    # Check ancestors too: O_NOFOLLOW alone only protects the final component.
    for component in (path, *path.parents):
        if component.is_symlink():
            raise StorageSecurityError(f"Refusing symlink in private storage path: {component}")


def ensure_parent(path: Path) -> None:
    """Create missing parents privately, without chmod'ing existing ancestors."""
    _check_path(path)
    if not path.exists():
        ensure_parent(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)


def private_file(path: Path) -> None:
    """Restrict an existing regular file, rejecting links and special files."""
    _check_path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise StorageSecurityError(f"Refusing non-regular or hard-linked private file: {path}")
    if os.name == "posix":
        path.chmod(0o600)


def private_dir(path: Path) -> None:
    """Create/harden a dedicated app directory and all its existing contents."""
    _check_path(path)
    ensure_parent(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        path.chmod(0o700)
    for child in path.iterdir():
        _check_path(child)
        if child.is_dir():
            private_dir(child)
        else:
            private_file(child)


def private_open(path: Path) -> TextIO:
    """Open a private text file for writing without following a final symlink."""
    ensure_parent(path.parent)
    private_file(path)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise StorageSecurityError(f"Refusing unsafe private file: {path}")
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        return os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
