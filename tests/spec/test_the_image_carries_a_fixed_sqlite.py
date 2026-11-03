# -*- coding: utf-8 -*-
"""The runtime image carries sqlite 3.54 or newer.

THE FINDING (Docker Scout on Docker Hub, 2026-11-04, after v3.1.2):
CVE-2026-119586, high (8.5), in sqlite-libs 3.53.4-r0. The fix is in sqlite
3.54, which Alpine 3.24 does not carry yet (only edge/main, 3.54.1-r0).
DDC never imports sqlite3; the library is in the image only because
Alpine's python3 package depends on it. The runtime stage takes this one
package from edge; it pulls nothing else, musl stays the 3.24 one, and
Python's sqlite3 module runs against it (checked in a throwaway
alpine:3.24 container the same day).

THE CONTRACT: the shipped stage asks for sqlite-libs >= 3.54 after its
upgrade, so a later upgrade cannot take it back; the edge repository is
named for that one command only, never added to /etc/apk/repositories.

HOW THIS TEST CAN FAIL: the line is dropped while 3.24 still serves 3.53.x,
or edge is added for every package.

COUNTER-CHECK (2026-11-04): red on the Dockerfile before the change.
WHEN TO DROP: once alpine v3.24/main serves sqlite-libs >= 3.54, the edge
line and this test go together.
"""

import re
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")


def _runtime():
    return DOCKERFILE.split(" AS runtime", 1)[1]


def test_the_runtime_stage_asks_for_a_fixed_sqlite_after_its_upgrade():
    stage = _runtime()
    upgrade = stage.index("apk upgrade --no-cache")
    fixed = re.search(r"apk add --no-cache --repository=https://dl-cdn\.alpinelinux\.org/alpine/edge/main \\\s+"
                      r"'sqlite-libs>=3\.54'", stage)
    assert fixed, "the runtime stage does not ask for sqlite-libs >= 3.54"
    assert fixed.start() > upgrade, "the fixed sqlite must come after the upgrade"


def test_edge_is_never_a_standing_repository():
    assert "/etc/apk/repositories" not in DOCKERFILE
