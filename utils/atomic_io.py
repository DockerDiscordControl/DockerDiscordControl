#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Atomic file writes - one implementation instead of several.

A plain ``open(path, "w")`` truncates the target the moment it is opened. If the
process dies between that and the final byte, the file is gone - not stale, gone.
Writing to a temp file in the same directory and ``os.replace``-ing it into place
makes the swap atomic: either the old content or the new one, never neither.

The project already relied on this pattern in a dozen places, but with two
diverging helpers: ``utils/token_security.py`` preserved the file mode and used
``os.replace``; ``services/config/channel_config_service.py`` did neither and on
Windows unlinked the target first, opening a window in which the file did not
exist at all. This module keeps the safer behaviour of the two. See SPEC.md Z7.
"""

import json
import os
import stat
import tempfile
from typing import Any, Dict, Union

PathLike = Union[str, "os.PathLike[str]"]


def atomic_write_text(path: PathLike, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` so a crash never leaves it truncated.

    The temp file is created in the *same* directory, because ``os.replace`` is
    only atomic within one filesystem.
    """
    directory = os.path.dirname(os.path.abspath(os.fspath(path)))
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            # mkstemp creates the temp file 0600; keep whatever the target had so
            # an atomic write never silently tightens or loosens permissions.
            os.chmod(tmp_path, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass  # target did not exist yet, or stat/chmod unavailable
        os.replace(tmp_path, path)
    except BaseException:
        # BaseException on purpose: a KeyboardInterrupt mid-write must not leave
        # the temp file behind either.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: PathLike, data: Dict[str, Any], *, indent: int = 2,
                      ensure_ascii: bool = False) -> None:
    """Serialize ``data`` first, then write it atomically.

    Serializing before opening anything matters: a value that cannot be encoded
    raises here, while the target file is still untouched.
    """
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=ensure_ascii))
