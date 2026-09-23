# -*- coding: utf-8 -*-
"""Every partial template is included by something.

THE FINDING (design pass of the panel, 2026-09-23; verified here):
`app/templates/_action_log_section.html` - 28 lines, a heading, a download
link, a refresh button and a `<pre id="actionLogContent">` - is included by no
template at all. `grep -rn "_action_log_section" app/ tests/` finds nothing
but the file itself.

MEASURED BEFORE DELETING, because "unused" and "unreachable feature" look the
same from a grep. The action log itself is fine: `_log_section.html:17` offers
"actions" in its source dropdown, and `window.downloadLogs` downloads whatever
source is showing. The comment at `_scripts.html:552` says it out loud -
"refreshActionLogBtn removed (integrated into main log system)". The
integration happened; this template is what was left on the floor.

The tell is in `_scripts.html:2399`: `smartRefreshActionLogs()` starts with
`if (!actionLogElement) return;`. It has been returning immediately on every
refresh since the day the include was dropped, and nothing ever said so.

WHY A TEST AND NOT JUST A DELETE: a partial nobody includes is invisible.
Nothing fails, nothing is logged, and the next reader cannot tell whether it
is dead or whether its include went missing - which is the question this file
took a while to answer. The check is cheap and there is exactly one way to
fail it.

HOW THIS TEST CAN FAIL: it lists every `_*.html` under app/templates and looks
for an `{% include %}` or `{% extends %}` naming it. A partial with no
reference is red, with its name.

COUNTER-CHECK (2026-09-23): red before, naming _action_log_section.html and
nothing else - 23 of the 24 partials were already reachable.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "app" / "templates"

REFERENCE = re.compile(r"""(?:include|extends)\s+['"]([^'"]+)['"]""")


def _referenced():
    """Every template name any template names, by file name and by path."""
    names = set()
    for path in TEMPLATES.rglob("*.html"):
        names.update(REFERENCE.findall(path.read_text(encoding="utf-8")))
    return names


def test_the_scan_sees_the_templates():
    """Safeguard against a blunt tool: a scanner finding nothing is green."""
    partials = list(TEMPLATES.rglob("_*.html"))

    assert len(partials) > 15, f"only {len(partials)} partials found - wrong path?"
    assert len(_referenced()) > 15, "no includes found at all - format changed?"


def test_every_partial_is_included_somewhere():
    """THE FINDING: one was not, and nothing anywhere said so."""
    referenced = _referenced()

    orphans = sorted(
        path.name for path in TEMPLATES.rglob("_*.html")
        if path.name not in referenced
        and str(path.relative_to(TEMPLATES)) not in referenced
    )

    assert orphans == [], (
        f"{len(orphans)} partial template(s) are included by nothing, so they "
        f"render for nobody and no test notices: {orphans}")


def test_the_action_log_is_still_reachable():
    """Counter-check on the deletion: the FEATURE must survive it.

    Deleting a template because it is unused is only right if what it showed
    is somewhere else. It is: the main log section offers "actions" as a
    source, and the download button takes whatever is showing.
    """
    section = (TEMPLATES / "_log_section.html").read_text(encoding="utf-8")

    assert 'value="actions"' in section, "the action log lost its way into the panel"
    assert 'id="downloadLogsBtn"' in section
