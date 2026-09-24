# -*- coding: utf-8 -*-
"""A key in the catalogue is read somewhere, or it is not a text - it is weight.

THE FINDING (2026-09-24): six of the 947 dotted keys are read by nothing at
all - not by a template, not by a route, not by a script.

    js.logs.confirm_clear            the action log's "really clear it?"
    web.action_log.clear_log_button  its button
    web.common.clear                 its label
    web.advanced.community_prefix
    web.login.logged_out
    web.nav.groups                   the navigation dot the groups section had

Most of them are yesterday's and today's own work: _action_log_section.html was
deleted when it turned out nothing included it, the groups section became a
dialog and lost its nav dot, and the panel login was rebuilt. Each key is one
line in each of the 40 catalogues, so six keys are 240 lines that translate
nothing.

WHY IT IS WORTH A CHECK AND NOT JUST A SWEEP: the next person who needs a
"Clear" label adds a second one, because the first cannot be found by reading
the panel. A catalogue that still promises texts the UI no longer shows is a
catalogue nobody can trust to answer "is this already translated?".

WHAT IS CHECKED, and what is not. Only the DOTTED keys - `web.…`, `js.…`,
`aas.…` - which are looked up by their key. The bot's other style, where the
English sentence IS the key, cannot be swept this way: those are read through
_() with the text inline, and test_bot_strings_exist_in_the_catalog.py checks
that direction instead.

THE `js.` PREFIX IS RESOLVED, because the browser never sees it:
get_js_translations() strips it (services/web/i18n_service.py), so
`t('aas.groups_heading')` reads `js.aas.groups_heading`. A scan that missed
that would have called 138 live keys dead - it did, on the first attempt.

BUILT_AT_RUNTIME is for a key assembled from pieces, which no text search can
find. It is empty today, and it is the honest place for such a key rather than
letting the check rot.

HOW THIS TEST CAN FAIL: deleting the last reader of a key without deleting the
key, or adding a key nothing reads yet.

COUNTER-CHECK (2026-09-24): red before, naming all six.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "locales"
READERS = ("app", "services", "cogs", "utils", "scripts")
SUFFIXES = (".py", ".html", ".js")

DOTTED = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+")

# Keys whose name is assembled at runtime, so no search can find them.
BUILT_AT_RUNTIME = frozenset()


def _catalogue():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


def _dotted_keys():
    return sorted(key for key, value in _catalogue().items()
                  if isinstance(value, str) and DOTTED.fullmatch(key))


def _everything_that_reads():
    parts = []
    for directory in READERS:
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in SUFFIXES:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _unread():
    text = _everything_that_reads()
    dead = []
    for key in _dotted_keys():
        if key in BUILT_AT_RUNTIME:
            continue
        if key in text:
            continue
        # The browser is handed js.* keys without their prefix.
        if key.startswith("js.") and key[len("js."):] in text:
            continue
        dead.append(key)
    return dead


def test_the_scan_sees_the_catalogue_and_the_code():
    """Safeguard against a blunt tool: a scan reading nothing is green."""
    keys = _dotted_keys()
    text = _everything_that_reads()

    assert len(keys) > 500, f"only {len(keys)} dotted keys found - wrong file?"
    assert len(text) > 500_000, f"only {len(text)} characters of code read"


def test_the_js_prefix_is_resolved():
    """The first version of this scan called 138 live keys dead, because the
    browser is handed them without the prefix. Proof the rule is applied."""
    keys = _dotted_keys()
    prefixed = [key for key in keys if key.startswith("js.")]

    assert len(prefixed) > 50, f"only {len(prefixed)} js.* keys - shape changed?"
    assert "js.aas.groups_heading" in keys
    assert "js.aas.groups_heading" not in _unread(), (
        "a js.* key read as t('aas.groups_heading') is reported as dead")


def test_every_key_is_read_somewhere():
    """THE FINDING: six keys translate nothing, in 40 catalogues each."""
    dead = _unread()

    assert dead == [], (
        f"{len(dead)} catalogue key(s) are read by nothing - delete them from "
        f"all 40 catalogues, or add them to BUILT_AT_RUNTIME with the reason:\n"
        "  " + "\n  ".join(dead))


def test_the_catalogues_agree_on_which_keys_exist():
    """Counter-check on a sweep: deleting a key must happen in all 40 files, or
    a locale keeps answering with a text the others no longer have."""
    english = set(_catalogue())
    extra = {}
    for path in sorted(LOCALES.glob("*.json")):
        if path.name in ("meta.json", "en.json"):
            continue
        theirs = set(json.loads(path.read_text(encoding="utf-8")))
        surplus = sorted(key for key in theirs - english if DOTTED.fullmatch(key))
        if surplus:
            extra[path.name] = surplus

    assert extra == {}, f"these catalogues hold keys English does not: {extra}"
