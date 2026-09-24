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

THE LIMIT: only literal first arguments are checked. Strings built at runtime
are not seen, and cannot be.

WIDENED 2026-09-24, because the limit above was hiding a live one. The scan
looked for calls to a plain ``_`` - the spelling of the day it was written -
and cogs/overview_embeds.py imports the same function as ``translate``. The
group heading added to the Discord overview that morning was
``translate("Container groups")`` with no catalogue entry, so a German
operator read "Container groups:" in English between "Server-Übersicht" and
"nicht gefunden", and this test said nothing. It now follows every name the
translation function is imported under, in each file, so a rename or a second
alias cannot reopen the hole.
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
    # These two moved with the donation modal to donation_ui.py (Phase 3 split).
    ("cogs/donation_ui.py", "⚠️ **Donation could not be recorded**"),
    ("cogs/donation_ui.py", "Nothing was sent to any channel. Please try again later."),
}


def _translation_names(tree):
    """Every name THIS file calls the translation function by.

    ``from .translation_manager import _`` and ``... import _ as translate``
    are the same function; a scan that knows only the first spelling is a scan
    that stops at the file where the finding was made.
    """
    names = {"_"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if "translation" not in (node.module or ""):
            continue
        for alias in node.names:
            if alias.name in ("_", "translate"):
                names.add(alias.asname or alias.name)
    return names


def _literals():
    for root in ROOTS:
        for path in sorted((PROJECT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(PROJECT).as_posix()
            names = _translation_names(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in names
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    yield rel, node.lineno, node.args[0].value


def test_the_scanner_sees_the_bot_strings():
    """Guard against a blunt tool."""
    literals = list(_literals())
    assert len(literals) > 500, f"Only {len(literals)} bot strings found - the scan is blind"


def test_the_scanner_follows_the_aliases():
    """Proof that the widening is applied and not merely described: the file
    that exposed the hole calls the translation function by another name."""
    tree = ast.parse((PROJECT / "cogs" / "overview_embeds.py").read_text(encoding="utf-8"))
    names = _translation_names(tree)

    assert "translate" in names, (
        "the scan knows only the plain _(), which is the spelling that hid a "
        "missing key for a whole morning")
    found = [text for rel, _line, text in _literals() if rel.endswith("overview_embeds.py")]
    assert "Container groups" in found, found[:5]


def test_every_bot_string_is_a_catalog_key():
    catalog = json.loads((PROJECT / "locales" / "en.json").read_text(encoding="utf-8"))
    missing = {(rel, text) for rel, _line, text in _literals() if text not in catalog}
    new = sorted(missing - KNOWN_MISSING)
    fixed = sorted(KNOWN_MISSING - missing)
    assert not new, f"Bot strings without an en.json key (they would never be translated): {new}"
    assert not fixed, f"These are catalog keys now - remove them from KNOWN_MISSING: {fixed}"
