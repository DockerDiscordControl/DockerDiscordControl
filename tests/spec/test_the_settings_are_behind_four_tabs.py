# -*- coding: utf-8 -*-
"""The settings sit behind four tabs, and every tab is inside the one form.

OPERATOR DECISION (2026-09-23): improve the panel in two steps - first the
container table, then this. Measured before building: config.html is 1916
lines of which 249 are markup, the whole admin page is 6532 lines, and it
carries about 930 form controls in a single <form> at 26 containers. Thirteen
card sections scroll past between the mech panel at the top and the log at the
bottom.

Four tabs: Discord (token, guild, channel permissions), Containers (the table
and the groups), Automation (the task form, the task list, the auto-action
rules), System (language, panel password, heartbeat).

THE ONE THING THAT MUST NOT BREAK, and it is why this is tabs and not separate
pages: saveConfigAjax collects `#config-form` fields and posts them, and the
save handler reads an absent checkbox as OFF. config.html already carries the
note about it - the heartbeat section was once moved out of the form, and
every save from then on wrote heartbeat.enabled=False. So every pane stays
INSIDE the form. Switching tabs hides fields; it does not remove them, and a
hidden input still submits.

THE SAVE BUTTON STAYS OUT OF THE TABS, inside the form. One Save for all four,
always visible - a per-tab save button would invite exactly the half-save the
paragraph above describes.

WHAT ELSE HAD TO CHANGE: the floating navigation points at ids that now live
inside panes. A dot must SHOW its pane before scrolling to it, or half the
dots do nothing. And updateActiveSection measured section.offsetTop, which is
0 for a hidden pane; it reads the document-relative position now, the way the
click handler already did.

HOW THIS TEST CAN FAIL: it checks that each pane sits between the form's
opening tag and its closing tag - the assertion that guards the save - that
the save button is outside the tab content, and that the navigation shows a
pane before scrolling. A pane that escapes the form is red.

COUNTER-CHECK (2026-09-23): red before - there were no panes at all, and the
navigation scrolled without showing anything.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "templates" / "config.html"
NAV = ROOT / "app" / "templates" / "base.html"

PANES = ("pane-discord", "pane-containers", "pane-automation", "pane-system")
KEYS = ("web.tabs.discord", "web.tabs.containers", "web.tabs.automation",
        "web.tabs.system")


def _page():
    return PAGE.read_text(encoding="utf-8")


def test_the_four_panes_exist():
    page = _page()

    for pane in PANES:
        assert f'id="{pane}"' in page, f"{pane} is missing"
    assert "nav-pills" in page, "there is no tab bar"


def test_every_pane_is_inside_the_form():
    """THE ASSERTION THAT GUARDS THE SAVE.

    saveConfigAjax posts what is inside #config-form, and the handler reads an
    absent checkbox as off. A pane outside the form would silently switch
    everything in it off on the next save - which has happened here before,
    with the heartbeat section.
    """
    page = _page()
    opens = page.index('id="config-form"')
    closes = page.index("</form>", opens)

    for pane in PANES:
        position = page.index(f'id="{pane}"')
        assert opens < position < closes, (
            f"{pane} is outside <form id='config-form'>, so everything in it "
            f"is absent from the next save and read as switched off")


def test_the_save_button_is_not_inside_a_tab():
    """One Save for all four tabs, always reachable. A per-tab save is an
    invitation to the half-save the test above describes."""
    page = _page()
    save = page.index("_save_button.html")
    content = page.index('class="tab-content')
    content_end = page.index("</form>", content)
    last_pane = max(page.index(f'id="{pane}"') for pane in PANES)

    assert save > last_pane, "the save button is inside the tab content"
    assert save < content_end, "the save button left the form"


def test_the_navigation_shows_a_pane_before_scrolling_to_it():
    """Otherwise half the dots scroll to something that is not displayed."""
    nav = NAV.read_text(encoding="utf-8")

    assert "tab-pane" in nav, "the navigation knows nothing about the panes"
    assert "bootstrap.Tab" in nav or "showPaneOf" in nav, (
        "nothing switches the tab, so a dot pointing into a hidden pane does "
        "nothing at all")


def test_the_active_section_is_not_measured_by_offsetTop():
    """A hidden pane reports offsetTop 0, so every section inside one would
    look like it is at the top of the page."""
    nav = NAV.read_text(encoding="utf-8")

    assert "section.offsetTop" not in nav, (
        "the active-dot logic still measures offsetTop, which is 0 inside a "
        "hidden pane")
    assert "getBoundingClientRect" in nav


def test_the_open_tab_survives_a_save():
    """Saving does not reload the page, but an F5 does, and the operator
    should land back where they were rather than on the first tab."""
    page = _page()

    assert "localStorage" in page or "sessionStorage" in page, (
        "the open tab is forgotten on every reload")


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_tab_names_exist(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    missing = [key for key in KEYS if not catalogue.get(key)]

    assert missing == [], f"{language}.json has no text for {missing}"


def test_every_locale_has_the_tab_names():
    locales = [p for p in (ROOT / "locales").glob("*.json") if p.name != "meta.json"]

    assert len(locales) >= 40
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        assert all(key in catalogue for key in KEYS), path.name


def test_the_sections_did_not_get_lost_on_the_way():
    """Counter-check on the move: every include the page had is still there,
    exactly once. Tabs are a wrapper, not an edit."""
    page = _page()
    expected = ("_discord_settings.html", "_channel_settings.html",
                "_permissions_table.html", "_server_selection.html",
                "_container_groups.html", "tasks/form.html", "tasks/list.html",
                "_language_timezone_settings.html", "_auth_settings.html",
                "_heartbeat_section.html", "_save_button.html",
                "_log_section.html")

    for name in expected:
        assert page.count(f"'{name}'") == 1, (
            f"{name} is included {page.count(chr(39) + name + chr(39))} times")


def test_the_page_still_renders_and_the_panes_are_in_the_form():
    """THE COUNTER-CHECK THE OTHERS CANNOT GIVE: they read the template source,
    where an include is one line. This renders the whole page and asks where
    the panes ended up - and it catches a Jinja error in the edit, which source
    matching never would.

    A FIRST VERSION COUNTED <div> AGAINST </div> inside the form and was wrong,
    in a way worth writing down: it took the region as everything up to the
    first </form> after #config-form, and tasks/list.html carries a nested
    <form id="editTaskForm"> for its edit dialog. So the "form region" ended
    inside the task list, the count was of some other stretch of markup
    entirely, and moving the task list into a pane changed the number without
    anything being wrong. Measured against the previous commit rendered the
    same way: 92/88 before, 95/89 after - a difference with no defect behind
    it. The boundary below is the element that follows </form> in the page, so
    it cannot be moved by an include.
    """
    from flask import Flask, render_template
    from jinja2 import ChainableUndefined

    app = Flask(__name__, template_folder=str(ROOT / "app" / "templates"))
    # The page reads a lot of context this test has no business inventing. An
    # undefined name renders as empty instead of raising, so what is measured
    # is the MARKUP - not whether the test guessed every variable the view passes.
    app.jinja_env.undefined = ChainableUndefined
    app.jinja_env.globals["_t"] = lambda key, **kwargs: key
    app.jinja_env.globals["csrf_token"] = lambda: "test-token"
    app.jinja_env.globals["url_for"] = lambda endpoint, **values: "/"

    with app.test_request_context("/"):
        html = render_template(
            "config.html", config={}, all_containers=[], configured_servers={},
            container_info_data={}, active_container_names=[],
            # The one name the markup indexes into rather than just printing.
            DEFAULT_CONFIG={"default_channel_permissions": {}})

    assert html.count("<form") == html.count("</form>"), (
        f"{html.count('<form')} <form> against {html.count('</form>')} </form>")

    opens = html.index('id="config-form"')
    # The element that comes immediately after </form> in config.html. No
    # include can move it, so it is a boundary the panes really have to be
    # inside of.
    after_form = html.index('id="save-notification"')

    for pane in PANES:
        position = html.index(f'id="{pane}"')
        assert opens < position < after_form, f"{pane} rendered outside the form"

    save = html.index('id="save-config-button"')
    assert max(html.index(f'id="{pane}"') for pane in PANES) < save < after_form, (
        "the save button is not where it must be: after every pane, so it is "
        "outside the tabs, and before </form>, so it still submits them all")
