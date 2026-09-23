# -*- coding: utf-8 -*-
"""Every dot stays visible, and the dots are grouped the way the tabs are.

THE OPERATOR'S DECISION, and it reverses mine from an hour earlier
(2026-09-23). I had made the dots follow the open tab: a dot whose section sat
in a closed pane was hidden, because the navigation was "describing a page
that no longer exists". He looked at it and said the opposite is what he
wants - the bar fully visible at all times, with the tabs shown as GROUPS
inside it, so that one click from the right-hand edge always lands on the
function he means.

He is right, and the reason my version was wrong is worth writing down: a dot
click already opens its pane before scrolling. So hiding the dot removed the
one thing that made the navigation better than the tabs - reaching anything on
the page in a single click, without first working out which tab it lives
behind. I had optimised the bar for describing the page instead of for using
it.

WHAT THE GROUPING IS. Dividers separate the four tabs and the two sections
that belong to no tab:

    top
    ---
    mech panel                          (above the tabs, in no pane)
    ---
    Discord:    token, guild, permissions
    ---
    Containers: the table, the groups
    ---
    Automation: task form, task list, rules
    ---
    System:     language, panel password, heartbeat
    ---
    log                                 (below the tabs, in no pane)
    ---
    log out

The order follows the tab bar left to right, so the two controls agree about
where things are.

HOW THIS TEST CAN FAIL: hiding dots again, or letting the grouping drift out
of step with the tabs - a section moving to another tab without its dot moving
with it.

COUNTER-CHECK (2026-09-23): red before - updateVisibleDots hid the dots of
closed panes, and the dividers cut across the tabs rather than between them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "templates" / "config.html"
MARKUP = ROOT / "app" / "templates" / "base.html"
SCRIPT = ROOT / "app" / "static" / "js" / "floating_nav.js"

# The groups, in the order the bar shows them. Each inner tuple is what sits
# between two dividers.
GROUPS = (
    ("top",),
    ("donationSection",),
    ("discord-settings", "channel-settings", "permissions-table"),
    # Containers: just the table since 2026-09-24 - the group editor became a
    # dialog opened from the bulk bar, so it is no longer a section of the page.
    ("server-selection",),
    ("task-scheduler", "task-list", "aas-section"),
    ("language-settings", "auth-settings", "heartbeat-section"),
    ("log-section",),
)


def _without_comments(text):
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_tab_bar_fills_the_width_of_the_cards_below_it():
    """The other thing the operator asked for: four pills bunched left under
    cards that run the full width."""
    page = _without_comments(PAGE.read_text(encoding="utf-8"))
    position = page.index('id="settings-tabs"')
    tag = page[page.rindex("<ul", 0, position):page.index(">", position)]

    assert "nav-justified" in tag or "nav-fill" in tag, (
        f"the tab bar does not fill its width: {tag}")


def test_no_dot_is_ever_hidden():
    """THE DECISION: the bar is fully visible, always."""
    script = _without_comments(SCRIPT.read_text(encoding="utf-8"))

    assert "updateVisibleDots" not in script, (
        "the dots are filtered again - the operator asked for all of them, all "
        "the time")
    assert ".hidden = " not in script, "something still hides a dot"


def test_a_dot_still_opens_the_tab_it_points_into():
    """What makes the full bar work: a click lands on the function, whichever
    tab it lives behind. Without this, ten of the thirteen dots would scroll to
    something that is not displayed."""
    script = _without_comments(SCRIPT.read_text(encoding="utf-8"))

    assert "showPaneOf" in script
    assert "closest('.tab-pane')" in script


def test_the_dots_are_grouped_the_way_the_tabs_are():
    """THE GROUPING: dividers between the tabs, not across them."""
    markup = _without_comments(MARKUP.read_text(encoding="utf-8"))
    nav = markup[markup.index('id="floatingNav"'):markup.index("</nav>")]

    found = []
    for piece in nav.split("nav-divider"):
        ids = re.findall(r'href="#([\w-]+)"', piece)
        if ids:
            found.append(tuple(ids))

    assert tuple(found) == GROUPS, (
        f"the dots are grouped {found}, and the tabs group them {GROUPS}")


def test_every_grouped_section_is_where_the_grouping_says():
    """Counter-check on the grouping: it is a claim about the page, so it is
    checked against the page. A section moving to another tab without its dot
    moving with it is red."""
    # Rendered, not read: the sections live in the included partials, so
    # config.html itself does not contain their ids at all.
    from flask import Flask, render_template
    from jinja2 import ChainableUndefined

    app = Flask(__name__, template_folder=str(ROOT / "app" / "templates"))
    app.jinja_env.undefined = ChainableUndefined
    app.jinja_env.globals["_t"] = lambda key, **kwargs: key
    app.jinja_env.globals["csrf_token"] = lambda: "test-token"
    app.jinja_env.globals["url_for"] = lambda endpoint, **values: "/static/x"
    with app.test_request_context("/"):
        page = render_template(
            "config.html", config={}, all_containers=[], configured_servers={},
            container_info_data={}, active_container_names=[],
            DEFAULT_CONFIG={"default_channel_permissions": {}})

    panes = ("pane-discord", "pane-containers", "pane-automation", "pane-system")
    bounds = [page.index(f'id="{pane}"') for pane in panes] + [page.index('id="save-notification"')]

    for index, pane_group in enumerate(GROUPS[2:6]):
        for section in pane_group:
            position = page.index(f'id="{section}"')
            assert bounds[index] < position < bounds[index + 1], (
                f"{section} has a dot in the {panes[index]} group but does not "
                f"sit in that pane")
