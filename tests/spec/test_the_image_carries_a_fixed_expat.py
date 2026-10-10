# -*- coding: utf-8 -*-
"""The runtime image carries expat 2.9.0 or newer.

THE FINDING (Docker Scout on Docker Hub, 2026-10-10, operator: "no more
warnings for v3.1.1"): CVE-2026-77214 and CVE-2026-102633, both high, in
expat 2.8.5-r0. They are fixed in 2.9.0, which Alpine 3.24 does not carry
yet (only edge/main). The runtime stage takes this one package from edge;
it depends on nothing but musl, which stays the 3.24 one (checked in a
throwaway alpine:3.24 container the same day).

THE CONTRACT: the shipped stage asks for expat AND libexpat >= 2.9.0 (the
library pyexpat loads is libexpat; the first attempt took expat alone and
Python still reported expat_2.8.5) after its upgrade, so
a later upgrade cannot take it back; the edge repository is named for that
one command only, never added to /etc/apk/repositories.

HOW THIS TEST CAN FAIL: the line is dropped while 3.24 still serves 2.8.x,
or edge is added for every package.

COUNTER-CHECK (2026-10-10): red on the Dockerfile before the change.
WHEN TO DROP: once alpine v3.24/main serves expat >= 2.9.0, the edge line
and this test go together.
"""

import re
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")


def _runtime():
    return DOCKERFILE.split(" AS runtime", 1)[1]


def test_the_runtime_stage_asks_for_a_fixed_expat_after_its_upgrade():
    stage = _runtime()
    upgrade = stage.index("apk upgrade --no-cache")
    fixed = re.search(r"apk add --no-cache --repository=https://dl-cdn\.alpinelinux\.org/alpine/edge/main \\\s+"
                      r"'expat>=2\.9\.0' 'libexpat>=2\.9\.0'", stage)
    assert fixed, "the runtime stage does not ask for expat >= 2.9.0"
    assert fixed.start() > upgrade, "the fixed expat must come after the upgrade"


def test_edge_is_never_a_standing_repository():
    assert "/etc/apk/repositories" not in DOCKERFILE
