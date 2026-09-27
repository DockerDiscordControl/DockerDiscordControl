# -*- coding: utf-8 -*-
"""The published image carries the Alpine security fixes of the day it is built.

THE FINDING (Docker Scout on Docker Hub, 2026-09-27): v3.0.0 shipped expat
2.8.4-r0 (CVE-2026-93990, High, fixable) although Alpine 3.24 already had
2.8.5-r0 and the runtime stage ends in `apk upgrade`. The image built on the
host without a cache had 2.8.5-r0. The CI builds with the GitHub Actions layer
cache, and a RUN line that has not changed is served from the cache - so the
`apk upgrade` of some earlier day was what shipped.

WHAT HOLDS NOW: the runtime stage is named and the publish workflow lists it
in `no-cache-filters`, so every published build runs its apk lines again. The
builder stage stays cached; nothing of it ships except site-packages.

HOW THIS TEST CAN FAIL: the filter is gone, names a stage the Dockerfile does
not have, or that stage no longer upgrades its packages.

COUNTER-CHECK (2026-09-27): red with the no-cache-filters line removed from
the workflow, and red with the stage renamed in the Dockerfile only.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _stages():
    """{stage name: text of that stage} from the Dockerfile."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    parts = re.split(r"^FROM\s+\S+(?:\s+AS\s+(\S+))?\s*$", text, flags=re.M | re.I)
    # re.split with one group: [before, name1, body1, name2, body2, ...]
    return {name: body for name, body in zip(parts[1::2], parts[2::2]) if name}


def test_the_shipped_stage_is_built_without_cache():
    workflow = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(encoding="utf-8")
    match = re.search(r"^\s*no-cache-filters:\s*(\S+)\s*$", workflow, flags=re.M)
    assert match, "the publish build serves every stage from the cache again"
    stages = _stages()
    for name in match.group(1).split(","):
        assert name in stages, f"no-cache-filters names '{name}', which the Dockerfile does not have"
        assert "apk upgrade" in stages[name], f"stage '{name}' no longer upgrades its packages"


def test_the_last_stage_is_the_one_kept_fresh():
    # The last FROM is what ships; keeping some other stage fresh would miss it.
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    last_from = re.findall(r"^FROM\s+.*$", text, flags=re.M)[-1]
    assert re.search(r"\sAS\s+runtime\s*$", last_from, flags=re.I), last_from
