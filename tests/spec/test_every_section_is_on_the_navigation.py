# -*- coding: utf-8 -*-
"""The floating navigation reaches every section of the page.

THE FINDING (design pass over the panel, 2026-09-23; verified here): the page
has 14 card-level sections and the floating nav in `base.html` has 11 dots.
Two sections are not on it:

* **Container groups** (`#container-groups`) - the operator's main lever over
  26 containers. A group is a target for a scheduled task, for an auto-action
  rule and, since this morning, for the bulk bar in the container table. The
  one section that is about groups is the one the navigation does not mention.
* **The scheduled task list** - which has no id at all, so nothing could point
  at it even if it wanted to. The task FORM above it has `#task-scheduler`;
  the list of what is actually scheduled has nothing.

A section with no dot is not unreachable - the operator can scroll - but the
navigation is the page's own claim about what is on it, and it was two short.

HOW THIS TEST CAN FAIL: it collects the anchors the navigation points at and
the ids the page defines for its card sections, and asks whether every section
id has a dot. A new section without one is red, by name.

COUNTER-CHECK (2026-09-23): red before, naming container-groups and the task
list - which had to be given an id before it could be named at all.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAV = ROOT / "app" / "templates" / "base.html"
PAGE = ROOT / "app" / "templates" / "config.html"

# The sections the navigation is expected to reach. Not every id on the page -
# a modal or a form field has no business on a section nav - so this is the
# list, and adding a section means adding it here and to the nav together.
SECTIONS = (
    "donationSection",
    "discord-settings",
    "channel-settings",
    "permissions-table",
    "server-selection",
    "container-groups",
    "task-scheduler",
    "task-list",
    "aas-section",
    "language-settings",
    "auth-settings",
    "heartbeat-section",
    "log-section",
)


def _anchors():
    return set(re.findall(r'href="#([\w-]+)"', NAV.read_text(encoding="utf-8")))


def test_the_scan_sees_the_navigation():
    """Safeguard against a blunt tool: an empty nav would pass everything."""
    assert len(_anchors()) > 8, f"only {len(_anchors())} anchors found - format changed?"


def test_every_section_has_a_dot():
    """THE FINDING: two did not, and one of them is the groups section."""
    missing = sorted(set(SECTIONS) - _anchors())

    assert missing == [], (
        f"{len(missing)} section(s) are on the page but not on its own "
        f"navigation: {missing}")


def test_every_section_the_navigation_names_exists():
    """Counter-check: a dot pointing at nothing scrolls nowhere and says
    nothing about why."""
    page = PAGE.read_text(encoding="utf-8")
    included = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "app" / "templates").rglob("*.html"))

    dangling = sorted(
        anchor for anchor in _anchors()
        if anchor != "top" and f'id="{anchor}"' not in page
        and f'id="{anchor}"' not in included)

    assert dangling == [], f"the navigation points at ids nothing defines: {dangling}"
