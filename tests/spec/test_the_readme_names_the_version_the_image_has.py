# -*- coding: utf-8 -*-
"""The README names the version the image carries.

The Dockerfile's ENV DDC_VERSION is the single source: the entrypoint banner,
/health and the panel footer all read it (pinned by
tests/unit/audit_2026_09/test_r2_g3_startup.py). The README says the version
twice more - in its headline and in the version badge - and those are written
by hand at every release. A release that bumps one and forgets the other
tells every reader of the front page a version that does not exist.

Written before the v3.0 release, so the release itself cannot forget them.

COUNTER-CHECK (2026-09-22): raising only the Dockerfile version by hand turns
both cases red.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _image_version():
    match = re.search(r'^ENV DDC_VERSION="(\d+\.\d+\.\d+)"', DOCKERFILE, re.M)
    assert match, "the Dockerfile must set ENV DDC_VERSION"
    return match.group(1)


def test_the_headline_names_it():
    version = _image_version()
    headline = README.splitlines()[0]
    assert f"v{version}" in headline, f"headline {headline!r} against image version {version}"


def test_the_badge_names_it():
    version = _image_version()
    badges = README.splitlines()[2]
    assert f"Version-v{version}" in badges, f"the version badge does not say v{version}"


def test_the_release_tag_link_names_it():
    """The badge links to the release tag - a stale link is a 404 for readers."""
    version = _image_version()
    assert f"releases/tag/v{version}" in README
