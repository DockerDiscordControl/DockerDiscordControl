# -*- coding: utf-8 -*-
"""The advanced settings say which of them actually need a restart.

THE THIRD PART of the operator's question about the restart notices
(2026-09-24). The advanced settings dialog told him, once, at the top:
"Advanced settings for fine-tuning performance. Changes require container
restart to take effect."

MEASURED, that is true of eleven of its twenty settings and false of nine. The
difference is not a matter of opinion - it is where the value is read:

    frozen at import, so a restart is the only way to change them
        app/utils/web_helpers.py       DDC_DOCKER_CACHE_DURATION and six more,
                                       module-level constants
        services/scheduling/
        scheduler_service.py           DDC_SCHEDULER_CHECK_INTERVAL,
                                       DDC_MAX_CONCURRENT_TASKS,
                                       DDC_TASK_BATCH_SIZE

    read where they are used, so they apply at once
        the nine DDC_LIVE_LOGS_* and the three stats/list timeouts

So each of the eleven carries the mark, and the sentence at the top says the
marked ones need a restart instead of claiming all of them do. The same
mark, `requires-restart`, that the bot token and the guild id already use.

WHY IT IS WORTH THE MARKUP: an operator who is told everything needs a restart
restarts for everything, which is how he came to ask in the first place. A
sweeping claim that is half wrong costs more than no claim - it trains the
reader to ignore the half that is right.

THIS FILE IS THE MEASUREMENT, not a copy of it. It reads the dialog for the
settings it offers and the source for where each one is read, and requires the
two to agree. A setting that moves out of a module-level constant, or a new one
that arrives frozen, is caught by the same case rather than by somebody
remembering.

HOW THIS TEST CAN FAIL: a setting marked that does not need it, one that needs
it and is not marked, or the sentence going back to claiming all of them.

COUNTER-CHECK (2026-09-24): red before - not one of the eleven was marked, and
the sentence claimed all twenty.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
MODAL = PROJECT / "app" / "templates" / "_advanced_settings_modal.html"
SOURCES = ("app", "cogs", "services", "utils")


def _offered():
    """Every advanced setting the dialog offers, by its bare name."""
    return sorted(set(re.findall(r'name="env_([A-Z0-9_]+)"',
                                 MODAL.read_text(encoding="utf-8"))))


def _frozen_at_import():
    """The settings whose value is read at module level.

    A module-level read happens once, when the process imports the module, so
    the value cannot change again while the bot runs. Indentation is what says
    so: a read inside a function or a class is indented, a module-level one is
    not.
    """
    frozen = {}
    for root in SOURCES:
        for path in sorted((PROJECT / root).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            for name in _offered():
                for match in re.finditer(rf"""['"]{re.escape(name)}['"]""", text):
                    line = lines[text[:match.start()].count("\n")]
                    if line and not line[0].isspace():
                        frozen.setdefault(name, f"{path.relative_to(PROJECT)}")
    return frozen


def _marked():
    """The settings the dialog marks as needing a restart."""
    markup = MODAL.read_text(encoding="utf-8")
    marked = set()
    for tag in re.findall(r"<(?:input|select)\b[^>]*>", markup):
        if "requires-restart" not in tag:
            continue
        found = re.search(r'name="env_([A-Z0-9_]+)"', tag)
        if found:
            marked.add(found.group(1))
    return marked


def test_the_dialog_still_offers_what_this_measures():
    """Safeguard: a pattern that finds nothing would make every case below
    pass without comparing anything."""
    offered = _offered()

    assert len(offered) >= 15, f"only {len(offered)} settings found - pattern blind?"


def test_the_measurement_finds_both_kinds():
    """Safeguard: if everything came out frozen, or nothing did, the rule
    below would be vacuous."""
    frozen = _frozen_at_import()
    offered = set(_offered())

    assert 1 <= len(frozen) < len(offered), (
        f"{len(frozen)} of {len(offered)} frozen - the measurement collapsed")


def test_every_frozen_setting_is_marked():
    """THE FINDING, one half: a value read once at import cannot be changed by
    saving, and the operator has to be told which ones those are."""
    missing = sorted(set(_frozen_at_import()) - _marked())

    assert missing == [], (
        "these are read at import and cannot change without a restart, and the "
        f"dialog does not say so: {missing}")


def test_nothing_else_is_marked():
    """THE OTHER HALF, and the one that made the old sentence useless: a
    setting that applies at once must not ask for a restart."""
    extra = sorted(_marked() - set(_frozen_at_import()))

    assert extra == [], (
        f"these are read where they are used and apply at once: {extra}")


def test_the_sentence_no_longer_claims_all_of_them():
    """The description is what the operator reads before the fields."""
    english = json.loads((PROJECT / "locales" / "en.json").read_text(encoding="utf-8"))
    text = english.get("web.advanced.description", "")

    assert text, "the dialog lost its description"
    assert "Changes require container restart" not in text, (
        "the sweeping claim is back - it is false for nine of the twenty")


def test_the_marked_ones_show_something():
    """A class nothing renders is a mark the operator cannot see."""
    markup = MODAL.read_text(encoding="utf-8")

    assert "restart-badge" in markup, "the dialog marks fields and shows nothing"


@pytest.mark.parametrize("key", ["web.advanced.description", "web.common.requires_restart"])
def test_the_texts_are_in_every_catalogue(key):
    missing = [p.name for p in sorted((PROJECT / "locales").glob("*.json"))
               if p.name != "meta.json"
               and not json.loads(p.read_text(encoding="utf-8")).get(key)]

    assert missing == [], f"{key} missing from {len(missing)}: {missing[:5]}"
