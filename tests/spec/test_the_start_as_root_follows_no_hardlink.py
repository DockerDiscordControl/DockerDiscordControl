# -*- coding: utf-8 -*-
"""The entrypoint's root phase hands no hardlinked file to ddc.

THE FINDING (audit 2026-09-26). At every start the entrypoint runs as root and
gives ddc the entries in its data directories that ddc cannot use
(fix_permissions: chown + chmod u+rwX on what find_unusable_entries lists).
/app/cached_animations and /app/assets are among them, belong to ddc, and in
a plain `docker run` are no volume - they sit on the image's filesystem, next
to the root-owned /app/entrypoint.sh. If the kernel allows it
(fs.protected_hardlinks=0, the kernel default, and what the operator's Unraid
host has), ddc can `ln /app/entrypoint.sh /app/cached_animations/x`. The next
start found a root-owned file ddc cannot write, chowned it to ddc - which is
chowning /app/entrypoint.sh itself - and the start after that ran whatever ddc
had written into it, as root, with the socket in reach. That is the route
around the proxy V3 §4.3 closed for /app. The operator's own container is not
exposed (both directories are separate mounts there, so a hardlink across them
is impossible), but the image does not know how it is started.

THE CONTRACT: find_unusable_entries never lists a non-directory with more than
one link. A file DDC made itself has one.

HOW THIS TEST CAN FAIL: a hardlinked file is listed for the chown.

COUNTER-CHECK (2026-09-26): red before the fix - both names of the hardlinked
file were listed. The single-link file is listed before and after.
"""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")


def _function(name):
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", ENTRYPOINT, re.S | re.M)
    assert match, f"entrypoint has no function {name}()"
    return match.group(0)


def _unusable_for_a_stranger(directory):
    """What the function lists for a uid/gid that owns nothing here: every
    file that is not world-usable, the way a root-owned file looks to ddc."""
    script = _function("find_unusable_entries") + f'find_unusable_entries "{directory}" 4242 4242 ! -type d -print\n'
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=30)
    return sorted(os.path.basename(line) for line in result.stdout.split())


def test_a_hardlinked_file_is_not_listed(tmp_path):
    target = tmp_path / "entrypoint.sh"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o600)
    os.link(target, tmp_path / "x")

    listed = _unusable_for_a_stranger(tmp_path)

    assert "x" not in listed and "entrypoint.sh" not in listed, listed


def test_a_file_of_its_own_is_still_listed(tmp_path):
    """Counter-case: the fix must not stop the repair it exists for."""
    own = tmp_path / "written-by-root.json"
    own.write_text("{}")
    own.chmod(0o600)

    assert _unusable_for_a_stranger(tmp_path) == ["written-by-root.json"]
