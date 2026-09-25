# -*- coding: utf-8 -*-
"""Channel translation is a Discord feature, so it sits under Discord.

THE OPERATOR, 2026-09-25, pointing at the System tab: "channel translation
does not fit under System - can we file it somewhere that suits?"

HE IS RIGHT, AND THE HEADING SAID SO. It sat inside "Language and timezone",
whose other three controls are the panel's own language, the bot's language
and the container's timezone - settings ABOUT DDC. Channel translation
translates messages between DISCORD CHANNELS: it has an API key, a provider,
a rate limit and a list of channel pairs, and it belongs beside the channel
settings and the permissions it works on.

THE TAB IS THE PROMISE. Five of them - Discord, Containers, Automation,
System, Logs - and a reader who wants a Discord feature looks under Discord.
A control filed under the wrong one is not merely untidy: it is a claim the
page makes about what the thing IS.

HOW THIS IS CHECKED: the include list of each pane is read out of
config.html, and the partial that carries the controls has to be in the
Discord one. Reading the panes rather than naming the file means moving it
again cannot quietly pass.

HOW THIS TEST CAN FAIL: the channel translation controls filed under a tab
that is not Discord.

COUNTER-CHECK (2026-09-25): red before - it was in the System pane.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
CONFIG = TEMPLATES / "config.html"

# A control nothing else in the panel has: the global switch of the feature.
THE_FEATURE = "ctGlobalToggle"


def _includes_per_pane():
    """{pane id: [template names]} for every tab of the settings page."""
    markup = CONFIG.read_text(encoding="utf-8")
    panes = {}
    for match in re.finditer(r'<div class="tab-pane[^"]*" id="pane-(\w+)"', markup):
        name = match.group(1)
        rest = markup[match.end():]
        end = rest.index("{# /pane-")
        panes[name] = re.findall(r"{%\s*include\s*'([^']+)'", rest[:end])
    return panes


def _pane_holding(control):
    for pane, templates in _includes_per_pane().items():
        for name in templates:
            path = TEMPLATES / name
            if path.exists() and control in path.read_text(encoding="utf-8"):
                return pane, name
    return None, None


def test_channel_translation_is_under_discord():
    """THE FINDING: a Discord feature filed under System."""
    pane, name = _pane_holding(THE_FEATURE)

    assert pane == "discord", (
        f"the channel translation controls are under the {pane!r} tab "
        f"({name}) - they translate messages between Discord channels")


def test_the_card_it_left_stops_promising_it():
    """THE HALF THAT IS EASY TO FORGET. "Language and timezone" introduced
    itself as "Configure language, timezone, and channel translation
    settings" - and kept saying so after the channel translation had gone.

    A card that promises a control it does not hold is the same defect this
    repository spent the day removing: a statement the program makes that is
    not true. The line is dropped rather than rewritten, because rewriting it
    would mean authoring the sentence in forty languages; the heading already
    says what the card is.
    """
    card = (TEMPLATES / "_language_timezone_settings.html").read_text(encoding="utf-8")

    assert "web.lang.description" not in card, (
        "the card still introduces itself as holding the channel translation")

    # and the key goes with it, or the catalogues carry forty dead lines
    import json
    for catalogue in sorted((PROJECT / "locales").glob("*.json")):
        if catalogue.name == "meta.json":
            continue
        texts = json.loads(catalogue.read_text(encoding="utf-8"))

        assert "web.lang.description" not in texts, catalogue.name


def test_the_panes_were_really_read():
    """The counter-check twelve sabotages have walked past: an empty map
    makes the case above pass while proving nothing."""
    panes = _includes_per_pane()

    assert set(panes) >= {"discord", "containers", "system", "logs"}, sorted(panes)
    assert any(panes.values()), panes
    assert _pane_holding("ctGlobalToggle")[0] is not None, "the control was not found at all"


def test_the_panel_settings_stay_under_system():
    """The opposite mistake: moving the whole card would take the panel's
    own language and the container timezone to Discord with it, and those
    are settings ABOUT DDC."""
    for panel_setting in ("ui_language", "timezone"):
        pane, name = _pane_holding(f'id="{panel_setting}"')

        assert pane == "system", f"{panel_setting} moved to {pane!r} ({name})"


def test_nothing_is_in_two_places():
    """A control included twice would answer to two tabs and save twice."""
    seen = {}
    for pane, templates in _includes_per_pane().items():
        for name in templates:
            seen.setdefault(name, []).append(pane)
    twice = {name: panes for name, panes in seen.items() if len(panes) > 1}

    assert twice == {}, twice
