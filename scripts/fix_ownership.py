# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Hand the data entries the app user cannot use to it - without ever following a link.

The entrypoint runs this as ROOT at every start, on the data directories
(config, logs, cached_*, assets). It replaces

    find ... ! -type l ... -exec chown uid:gid {} \\; -exec chmod u+rwX {} \\;

which checked "not a link" when find listed an entry and then let chown and
chmod follow whatever the path had become by the time they ran. A process
with the app user's uid that swaps an entry - or a directory above it - for a
symlink in that moment made root hand the link's target to that uid: the
entrypoint, the proxy (adversarial review 2026-09-27). DDC's own processes
are all gone at a container start, so this needs another container or a host
process writing the same volume under the same uid - on Unraid 99:100 is
shared by many. It is closed here rather than argued away.

HOW: os.fwalk(follow_symlinks=False) walks by directory file descriptors, so
no path component is ever resolved again after it was checked; every entry is
opened as O_PATH | O_NOFOLLOW relative to its parent's descriptor, checked on
that handle (type, one link), and changed through /proc/self/fd/<n>, which
names the opened inode. A symlink, a second hard link, a FIFO or a device is
left alone. Linux only - which is where the entrypoint runs.

Usage: python3 -I fix_ownership.py <dir> <uid> <gid>
Prints how many entries it fixed and how many it could not; exit code 1 if any
could not be fixed.
"""

from __future__ import annotations

import os
import stat
import sys


def usable(mode: int, owner: int, group: int, uid: int, gid: int, is_dir: bool) -> bool:
    """Whether the app user can already use the entry - the find rule of the entrypoint."""
    need = 0o7 if is_dir else 0o6
    return ((owner == uid and (mode >> 6) & need == need)
            or (group == gid and (mode >> 3) & need == need)
            or mode & need == need)


def fix_entry(name: str, dir_fd: int, uid: int, gid: int) -> str:
    """Fix one entry of the directory dir_fd. Returns 'fixed', 'usable', 'skipped' or 'failed'."""
    # O_PATH | O_NOFOLLOW: a handle on the entry itself - a link stays a link -
    # that needs no read permission. It is checked and changed through
    # /proc/self/fd/<n>, which names the opened inode and is not resolved again
    # (the way the C library does fchmodat for the same reason).
    try:
        fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=dir_fd)
    except OSError:
        return "failed"
    try:
        st = os.fstat(fd)
        is_dir = stat.S_ISDIR(st.st_mode)
        if not is_dir and not (stat.S_ISREG(st.st_mode) and st.st_nlink == 1):
            return "skipped"  # a link, a second name for a file, a FIFO, a device
        if usable(st.st_mode, st.st_uid, st.st_gid, uid, gid, is_dir):
            return "usable"
        handle = f"/proc/self/fd/{fd}"
        os.chown(handle, uid, gid)
        os.chmod(handle, stat.S_IMODE(st.st_mode) | (0o700 if is_dir else 0o600))
        return "fixed"
    except OSError:
        return "failed"
    finally:
        os.close(fd)


def fix_tree(top: str, uid: int, gid: int) -> dict:
    """Walk top without following links and fix every entry the app user cannot use."""
    counts = {"fixed": 0, "usable": 0, "skipped": 0, "failed": 0}
    parent, base = os.path.split(os.path.abspath(top))
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        counts[fix_entry(base, parent_fd, uid, gid)] += 1
    finally:
        os.close(parent_fd)
    for _dirpath, dirnames, filenames, dir_fd in os.fwalk(top, follow_symlinks=False):
        for name in dirnames + filenames:
            counts[fix_entry(name, dir_fd, uid, gid)] += 1
    return counts


def main(argv) -> int:
    if len(argv) != 4:
        print("usage: fix_ownership.py <dir> <uid> <gid>", file=sys.stderr)
        return 2
    top, uid, gid = argv[1], int(argv[2]), int(argv[3])
    if not os.path.isdir(top) or os.path.islink(top):
        print(f"{top}: not a directory (or a link) - left alone", file=sys.stderr)
        return 1
    counts = fix_tree(top, uid, gid)
    print(f"{top}: fixed {counts['fixed']}, could not fix {counts['failed']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
