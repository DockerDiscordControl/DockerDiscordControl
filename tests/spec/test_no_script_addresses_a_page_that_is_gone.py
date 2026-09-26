# -*- coding: utf-8 -*-
"""A script may not reach for an element the panel does not have.

THE MIRROR of test_every_control_reaches_the_code_behind_it.py, and the half
that found more: that file asks whether a control's handler exists, this one
asks whether a script's element does. Both are the same defect from opposite
ends - a name written in one place and removed in the other, with nothing
failing and nothing logged.

WHAT IT FOUND, 2026-09-26: twenty-two, and three whole features among them.

    the temporary debug mode      3 ids, 4 layers  -> removed
    the mech animation test bench 6 ids, 4 layers  -> removed
    five admin-overview cooldowns                  -> stopped being written
    two inside a commented-out block               -> not subjects, see below
    SIX still here, listed below

THE SIX ARE THE REMAINS OF DESIGNS THAT WERE REPLACED, and each replacement
works today::

    command-permissions-table   one table, now status-channels-table
                                and control-channels-table
    add-channel-btn             its "Add Channel" button
    container-info-config       a panel, now the containerInfoModal
    container-info-placeholder  its empty state
    actionLogContent            an action-log view, now logContent and the
                                log-type selector
    select-all-servers          a select-all for the server table; bulk
                                selection lives in the bulk bar and the
                                container-groups dialog

EVERY ONE IS GUARDED - ``if (!x) return;`` or ``if (x) {`` - so nothing
misbehaves and the operator sees nothing wrong. They are dead weight inside a
2400-line handler, not a defect he feels, and untangling them is surgery on
the panel's main script. So they are written down and held, not removed in
passing: the list may only ever get SHORTER, which is the same rule the file
and class ceilings follow.

A COMMENTED-OUT BLOCK IS NOT A SUBJECT. panel.js carries a ``toggleChannelId``
inside ``/* ... */`` marked "No longer needed", and its two lookups are not
code. A first version of this scan claimed them - the same lesson this
repository keeps learning from both sides - so comments are stripped before
the text is read.

HOW THIS TEST CAN FAIL: any element addressed by a script and carried by no
template.

COUNTER-CHECK (2026-09-26): red at twenty-two before the removals, and red
again under a sabotage that renames one live lookup.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
SCRIPTS = PROJECT / "app" / "static" / "js"

# EMPTY SINCE 2026-09-26, and it stays that way. It held six for one day -
# the remains of designs that had been replaced, all guarded, all in
# app/static/js/panel.js - and the operator asked for them the next morning.
# THE LIST MAY ONLY GET SHORTER: an entry removed from the panel leaves here,
# nothing is ever added. The same rule the file ceilings follow.
STILL_HERE = set()

ASKED_FOR = re.compile(r"getElementById\((['\"])([\w-]+)\1\)")
AN_ID = re.compile(r'\bid="([\w-]+)"')
# An id a script builds itself, e.g. `row.id = 'server-4'` or a template
# string written into innerHTML.
MADE_BY_A_SCRIPT = r"""(?:id=\\?["']{name}\\?["']|\.id\s*=\s*["'`]{name}["'`])"""


def _code_of(javascript):
    """The script with its comments taken out."""
    without_blocks = re.sub(r"/\*.*?\*/", " ", javascript, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in without_blocks.splitlines())


def _ids_in_the_markup():
    found = set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        found |= set(AN_ID.findall(path.read_text(encoding="utf-8")))
    return found


def _every_source():
    return ({path: path.read_text(encoding="utf-8") for path in sorted(SCRIPTS.rglob("*.js"))}
            | {path: path.read_text(encoding="utf-8") for path in sorted(TEMPLATES.rglob("*.html"))})


def _addressed_but_absent():
    """{id: {file names}} for every lookup no template answers."""
    carried = _ids_in_the_markup()
    everything = _every_source()
    absent = {}
    for path, raw in everything.items():
        text = _code_of(raw) if path.suffix == ".js" else raw
        for _quote, name in ASKED_FOR.findall(text):
            if name in carried:
                continue
            pattern = MADE_BY_A_SCRIPT.format(name=re.escape(name))
            if any(re.search(pattern, other) for other in everything.values()):
                continue  # a script writes this element itself
            absent.setdefault(name, set()).add(path.name)
    return absent


def test_no_script_addresses_an_element_the_panel_does_not_have():
    """THE RULE. Nothing is held out any more."""
    absent = _addressed_but_absent()
    unexpected = {name: sorted(where) for name, where in absent.items()
                  if name not in STILL_HERE}

    assert unexpected == {}, (
        "a script reaches for an element no template carries, so the code "
        f"behind it can never run:\n  {unexpected}")


def test_the_list_only_ever_gets_shorter():
    """A written-down entry that has gone must LEAVE the list, or the list
    starts protecting something that is not there - which is the defect this
    whole file is about, one level up."""
    absent = set(_addressed_but_absent())
    gone = sorted(STILL_HERE - absent)

    assert gone == [], (
        f"these are no longer addressed anywhere and must leave STILL_HERE: {gone}")


def test_anything_written_down_is_said_to_be_somewhere():
    """A written-down entry carries a place, not just a name - so the next
    reader knows where to look rather than searching for it."""
    absent = _addressed_but_absent()

    for name in STILL_HERE:
        assert absent.get(name), f"{name} is written down and addressed nowhere"


def test_a_commented_out_lookup_is_not_a_subject():
    """panel.js carries a toggleChannelId inside /* ... */ marked "No longer
    needed". Its two lookups are not code, and a scan that claimed them would
    be red about markup that is perfectly alive."""
    code = _code_of("""
        /* function toggleChannelId() {
            const methodSelect = document.getElementById('heartbeat_method');
        } */
        const live = document.getElementById('config-form');
        // const dead = document.getElementById('ghost_id');
    """)
    asked = {name for _quote, name in ASKED_FOR.findall(code)}

    assert asked == {"config-form"}, asked


def test_the_scan_reads_the_panel():
    """The counter-check: the rule passes on an empty scan, and on a scan
    that finds every id in the markup."""
    carried = _ids_in_the_markup()
    everything = _every_source()

    assert len(carried) > 300, len(carried)
    assert len(everything) > 40, len(everything)
    assert "config-form" in carried
    # and the rule really has subjects
    assert set(_addressed_but_absent()) == STILL_HERE, sorted(_addressed_but_absent())
