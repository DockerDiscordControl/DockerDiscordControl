# -*- coding: utf-8 -*-
"""The log view is a page of its own, and its debug switch finally works.

THE OPERATOR ASKED (2026-09-24) for the system logs, which sat under every
single settings page, to become a full-height view of its own in the tab bar
beside Discord, Container, Automation and System. Then: "move the switch along,
it belongs with the log."

MOVING IT UNCOVERED THAT THE SWITCH HAS NEVER DONE ANYTHING. It sits in
_log_section.html, which was included OUTSIDE <form id="config-form">, and
saveConfigAjax collects `form.querySelectorAll('input, select, textarea')` -
inside the form and nowhere else. So the field was never posted. Verified on
the operator's own installation: `debug_level_enabled` is absent from the saved
configuration, while _update_logging_settings reads it on every save to decide
between DEBUG and INFO. The toast the switch pops up says "Save configuration
to activate detailed logging", and saving did nothing at all.

TWO MORE TRAPS SAT BEHIND THE MOVE, both from putting the section inside a form:

  * panel.js posts an unchecked box as the STRING "0", and the parser's
    catch-all writes form values through as strings. `"0"` is truthy in
    Python, so switching the debug level OFF would have turned logging ON -
    the opposite - and it would have looked like the switch finally worked.
    The key is stored as a real boolean now.

  * the two buttons in the section carried no type. A <button> without one is
    a submit button, so inside the form "Refresh" and "Download" would have
    saved the configuration.

HOW THIS TEST CAN FAIL: the section drifting back out of the form, the switch
storing a string again, or a button in it losing its type.

COUNTER-CHECK (2026-09-24): red before - there was no logs tab, the section was
outside the form, and the parser stored "0".
"""

import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
CONFIG_PAGE = PROJECT / "app" / "templates" / "config.html"
LOG_SECTION = PROJECT / "app" / "templates" / "_log_section.html"
TAB_KEY = "web.tabs.logs"


@pytest.fixture
def page():
    return CONFIG_PAGE.read_text(encoding="utf-8")


def test_the_tab_bar_offers_the_logs(page):
    """THE REQUEST: a menu item beside the other four."""
    bar = page[page.index('id="settings-tabs"'):page.index("</ul>", page.index('id="settings-tabs"'))]

    assert 'data-bs-target="#pane-logs"' in bar, "no tab points at the log view"
    assert TAB_KEY in bar, "the tab has no catalogue key, so it is English everywhere"


def test_the_five_tabs_are_still_one_bar(page):
    """Counter-check: the new one is in the bar, not a second bar beside it."""
    bar = page[page.index('id="settings-tabs"'):page.index("</ul>", page.index('id="settings-tabs"'))]

    assert bar.count('data-bs-toggle="pill"') == 5, "the bar no longer holds five tabs"
    assert page.count('id="settings-tabs"') == 1


def test_the_log_view_is_a_pane(page):
    assert 'id="pane-logs"' in page
    pane = page[page.index('id="pane-logs"'):]
    pane = pane[:pane.index("</div>{# /pane-logs #}")]

    assert "_log_section.html" in pane, "the pane does not hold the log section"


def test_the_section_is_included_exactly_once(page):
    """It used to stand outside the panes, which is why it appeared under every
    page. Left in both places it would now appear twice."""
    assert page.count("'_log_section.html'") == 1


def test_the_pane_is_inside_the_form(page):
    """THE DEFECT THIS FIXES. saveConfigAjax collects what is inside
    #config-form and nothing else, so a switch outside it is never posted."""
    form_start = page.index('id="config-form"')
    form_end = page.index("</form>", form_start)
    pane = page.index('id="pane-logs"')

    assert form_start < pane < form_end, (
        "the log pane is outside the form again - its switch would stop being saved")


def test_no_button_in_the_section_can_submit_the_form():
    """A <button> without a type is a submit button. Inside the form, Refresh
    and Download would have saved the configuration."""
    markup = LOG_SECTION.read_text(encoding="utf-8")
    offenders = [tag for tag in re.findall(r"<button\b[^>]*>", markup)
                 if not re.search(r'type="(button|reset)"', tag)]

    assert offenders == [], f"these would submit the settings form: {offenders}"


@pytest.mark.parametrize("posted,expected", [("1", True), ("0", False)])
def test_the_debug_switch_round_trips(posted, expected, tmp_path, monkeypatch):
    """THE TRAP: an unchecked box is posted as the string "0", and "0" is
    truthy in Python. Stored as a string, switching the level off would have
    turned debug logging on."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config.config_service import process_config_form

    updated, ok, _message = process_config_form({"debug_level_enabled": posted}, {})

    assert ok, _message
    assert updated.get("debug_level_enabled") is expected, (
        f"posted {posted!r}, stored {updated.get('debug_level_enabled')!r} - "
        "a string here reads as True whichever way the switch is set")


def test_an_unsent_switch_does_not_flip_by_itself(tmp_path, monkeypatch):
    """A form that does not carry the key at all - an older page, or a save
    from somewhere else - must leave what is stored alone rather than read a
    missing key as "off"."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config.config_service import process_config_form

    updated, ok, _message = process_config_form(
        {"language": "en"}, {"debug_level_enabled": True})

    assert ok
    assert updated.get("debug_level_enabled") is True


def test_the_tab_name_is_in_every_catalogue():
    missing = []
    for path in sorted((PROJECT / "locales").glob("*.json")):
        if path.name == "meta.json":
            continue
        if not json.loads(path.read_text(encoding="utf-8")).get(TAB_KEY):
            missing.append(path.name)

    assert missing == [], f"{TAB_KEY} missing from {len(missing)}: {missing[:5]}"


def test_the_catalogues_are_not_all_the_english_word():
    """NOT the usual "is the German one German" case, because here it honestly
    is: "Logs" is the ordinary German word too, and so it is in Indonesian and
    Malay. What would be wrong is forty copies of the English one, which is
    what a bulk insert that forgot to translate looks like."""
    renderings = set()
    for path in sorted((PROJECT / "locales").glob("*.json")):
        if path.name == "meta.json":
            continue
        renderings.add(json.loads(path.read_text(encoding="utf-8")).get(TAB_KEY))

    assert len(renderings) > 20, (
        f"only {len(renderings)} different renderings across 40 catalogues - "
        "the key was copied, not translated")
