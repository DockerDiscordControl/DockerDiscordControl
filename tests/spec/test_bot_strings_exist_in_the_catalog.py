# -*- coding: utf-8 -*-
"""Every literal bot string ``_("...")`` must be a key of ``locales/en.json``.

No ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

WHY: the bot looks the source string up as the catalog KEY. A literal that is
not a key silently falls back to itself - untranslated for every server, with
no error anywhere. That risk is concrete right now: the German source strings
of cogs/enhanced_info_modal_simple.py were renamed to English keys in all 40
catalogs, and a single mismatch between code and catalog would go unnoticed.

KNOWN GAPS: four literals in cogs/docker_control.py have never had a catalog
entry (measured 2026-09-19: 597 literals, 4 missing). Two are user texts about
a donation that could not be recorded - every server sees them in English; two
are log texts wrapped in _() for no reason. They are listed below and may only
shrink; fixing them is a separate change.

THE LIMIT: only literal first arguments of a call to a plain name ``_`` are
checked. Strings built at runtime, or translated through another helper
(translation_manager.translate), are not seen.
"""

import ast
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOTS = ("cogs", "services", "app", "utils")

# (file, literal) that are known to be missing from en.json. ONLY EVER SHRINK THIS.
KNOWN_MISSING = {
    # These two moved with the message code to message_updates.py (Phase 3 split).
    ("cogs/message_updates.py", "Mech power depleted - forcing animation update to show offline state"),
    ("cogs/message_updates.py", "Upgrading to force_recreate=True due to power depletion (offline mech)"),
    ("cogs/docker_control.py", "⚠️ **Donation could not be recorded**"),
    ("cogs/docker_control.py", "Nothing was sent to any channel. Please try again later."),
}


def _literals():
    for root in ROOTS:
        for path in sorted((PROJECT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(PROJECT).as_posix()
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    yield rel, node.lineno, node.args[0].value


def test_the_scanner_sees_the_bot_strings():
    """Guard against a blunt tool."""
    literals = list(_literals())
    assert len(literals) > 500, f"Only {len(literals)} bot strings found - the scan is blind"


def test_every_bot_string_is_a_catalog_key():
    catalog = json.loads((PROJECT / "locales" / "en.json").read_text(encoding="utf-8"))
    missing = {(rel, text) for rel, _line, text in _literals() if text not in catalog}
    new = sorted(missing - KNOWN_MISSING)
    fixed = sorted(KNOWN_MISSING - missing)
    assert not new, f"Bot strings without an en.json key (they would never be translated): {new}"
    assert not fixed, f"These are catalog keys now - remove them from KNOWN_MISSING: {fixed}"
