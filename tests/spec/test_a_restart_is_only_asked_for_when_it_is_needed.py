# -*- coding: utf-8 -*-
"""The page asks for a container restart only when one is actually needed.

THE OPERATOR, 2026-09-24, with two screenshots of notices the settings page
carried under every tab: "we have these annoying notices everywhere - is that
really so, can it not be smoother, without a restart?"

MEASURED, IT IS NOT SO. Exactly TWO fields need the process restarted, because
the bot builds its Discord connection from them once at startup:

    bot_token, guild_id      class="requires-restart", own badge, genuinely so

Everything else the page saves is re-read while the bot runs:

    channel permissions      a hot-reload event, handled in
                             cogs/docker_control.py (_handle_channel_config_changed)
    container selection      get_all_servers() is called at 34 places in cogs/
    language, timezone       caches invalidated on save; the save's own message
                             already says "take effect immediately"
    debug level              applied on save since 2026-09-24

AND YET THE PAGE CARRIED TWO BLANKET BANNERS - "after saving, the Docker
container must be restarted manually ... for the bot to apply all changes" and
"the configuration is split into several files ... the container should be
restarted" - under every single tab, for every save.

THE ALERT AFTER A SAVE WAS WORSE, because it looked considered. It asked
whether any `.requires-restart` field HAS a value:

    else if (element.value && element.value.trim() !== '') { changesDetected = true; }

A bot token is never empty. So it fired after every save that had touched
anything at all. A notice that is always there is one nobody reads on the day
it matters - which is the whole cost of this.

The comparison the badge beside those fields already makes - against
data-initial-value - is now the one the alert makes too, in
app/static/js/restart_notice.js, exercised by tests/js/restart_notice.test.js.

WHAT THIS DELIBERATELY LEAVES: the order of the containers is loaded once at
startup (cogs/docker_control.py:278) and the overview draws from that cached
list, so "order change requires restart" is TRUE today. Making it live is a
change to the bot, not to a notice, and it is its own piece of work.

HOW THIS TEST CAN FAIL: a blanket restart banner coming back, or the alert
going back to asking whether a field is non-empty.

COUNTER-CHECK (2026-09-24): red before - both banners were in the markup, both
keys in all 40 catalogues, and the alert fired on a non-empty field.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
PANEL_JS = PROJECT / "app" / "static" / "js" / "panel.js"

# The two blanket notices, and the bold "Important:" that introduced one of
# them - it had no reader left once its sentence went, which the dead-key sweep
# caught rather than I did.
DROPPED = ("web.config.restart_warning", "web.config.save_note",
           "web.config.important_label")


def test_no_blanket_restart_banner_is_left():
    """THE FINDING: a notice under every tab, for every save."""
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        markup = path.read_text(encoding="utf-8")
        for key in DROPPED:
            if key in markup:
                offenders.append(f"{path.name}: {key}")

    assert offenders == [], f"a blanket restart banner is back: {offenders}"


@pytest.mark.parametrize("key", DROPPED)
def test_the_dropped_notices_left_every_catalogue(key):
    left = [p.name for p in sorted((PROJECT / "locales").glob("*.json"))
            if p.name != "meta.json"
            and key in json.loads(p.read_text(encoding="utf-8"))]

    assert left == [], f"{key} is still in {len(left)} catalogues: {left[:5]}"


def test_the_fields_that_do_need_it_still_say_so():
    """Counter-check: the blanket notices went, the precise mark stays. Without
    this, deleting the mark as well would pass the case above.

    OUTSIDE THE ADVANCED DIALOG there are exactly two, and they are the two the
    bot's Discord connection is built from. The advanced dialog marks eleven
    more, each measured as frozen at import by
    test_only_the_frozen_advanced_settings_ask_for_a_restart.py - that file
    owns them, and repeating the list here would be a second copy to keep in
    step.
    """
    marked = set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        if path.name == "_advanced_settings_modal.html":
            continue
        markup = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<input\b[^>]*requires-restart[^>]*>", markup):
            found = re.search(r'id="([^"]+)"', tag)
            if found:
                marked.add(found.group(1))

    assert marked == {"bot_token", "guild_id"}, marked


def test_each_marked_field_has_a_badge_to_show():
    """The mark is only useful if something renders because of it."""
    for path in sorted(TEMPLATES.rglob("*.html")):
        markup = path.read_text(encoding="utf-8")
        if "requires-restart" not in markup:
            continue

        assert "restart-badge" in markup, f"{path.name} marks a field and shows nothing"


def test_the_alert_asks_whether_something_changed():
    """THE DEFECT: it asked whether a field was non-empty, and a bot token
    never is."""
    source = PANEL_JS.read_text(encoding="utf-8")

    assert "restartIsNeeded" in source, "the alert no longer asks the shared question"
    assert "element.value.trim() !== ''" not in source, (
        "the non-empty check is back - the notice will fire after every save")


def test_the_shared_question_is_loaded_before_the_panel_uses_it():
    """Scripts are loaded in a fixed order and there is no module system."""
    scripts = (TEMPLATES / "_scripts.html").read_text(encoding="utf-8")

    assert "js/restart_notice.js" in scripts
    assert scripts.index("js/restart_notice.js") < scripts.index("js/panel.js")


def test_the_node_case_file_exists_and_is_run_with_the_others():
    """The rule itself is exercised in node (tests/js), because the runtime
    image has no JavaScript engine. A case file nobody runs is no case."""
    cases = PROJECT / "tests" / "js" / "restart_notice.test.js"

    assert cases.is_file()
    assert "restartIsNeeded" in cases.read_text(encoding="utf-8")
