# -*- coding: utf-8 -*-
"""What the save writes is what the form names.

HOW THE PAYLOAD IS BUILT. Saving walks every input, select and textarea in
``#config-form`` and puts it into a ``FormData`` under ``element.name``.

THE FINDING (2026-09-25, found while measuring which controls belong to the
save at all). Ordinary fields are guarded - ``else if (element.name)`` - but
checkboxes and radios are not::

    if (element.type === 'checkbox') {
        formData.set(element.name, element.checked ? (element.value || "1") : "0");
    }

``element.name`` is the empty string for a control that has none, so an
unnamed checkbox writes a key of ``""`` into the configuration payload. Two
do it today: the log view's auto-refresh and the channel translation's global
switch, neither of which is a setting of this form.

IT IS NOT A CRASH, which is why it sat there: the server ignores a key it
does not know. It is a false statement in the payload, and the same boundary
the unsaved-changes banner is drawn on - a control without a name is not part
of this save.

THE GUARD GOES FIRST, once, rather than being repeated in three branches:
whoever adds a fourth kind of control would otherwise have to remember it,
and that is exactly how the checkbox branch came to be the one without it.

HOW THIS TEST CAN FAIL: the payload builder writing a field before it has
checked that the field has a name.

COUNTER-CHECK (2026-09-25): red before - the guard sat in one branch of
three, after two writes.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
PANEL_JS = PROJECT / "app" / "static" / "js" / "panel.js"


def _the_payload_loop(source):
    """The block that turns the form's controls into the saved payload."""
    start = source.index("formElements.forEach(element => {")
    end = source.index("\n        });", start)
    return source[start:end]


def test_nothing_is_written_before_the_name_is_checked():
    """THE FINDING: the checkbox and radio branches wrote first and asked
    never."""
    block = _the_payload_loop(PANEL_JS.read_text(encoding="utf-8"))
    guard = re.search(r"if\s*\(\s*!\s*element\.name\s*\)", block)

    assert guard is not None, (
        "the loop never refuses a control without a name, so an unnamed "
        "checkbox writes an empty key into the configuration")

    first_write = block.index("formData.set(")

    assert guard.start() < first_write, (
        "the name is checked only after something has already been written:\n"
        + block[:400])


def test_the_loop_still_writes_the_three_kinds():
    """Counter-check: a guard that refused everything would pass the case
    above and save nothing at all."""
    block = _the_payload_loop(PANEL_JS.read_text(encoding="utf-8"))

    for kind in ("'checkbox'", "'radio'"):
        assert kind in block, kind
    assert block.count("formData.set(") >= 3, block.count("formData.set(")


def test_the_scan_would_see_the_shape_the_defect_had():
    """The counter-check eleven sabotages have walked past: a scan that
    cannot find the loop passes both cases above while proving nothing."""
    sabotage = (
        "        formElements.forEach(element => {\n"
        "            if (element.type === 'checkbox') {\n"
        "                formData.set(element.name, '1');\n"
        "            }\n"
        "        });\n")
    block = _the_payload_loop(sabotage)

    assert "formData.set(" in block, block
    assert re.search(r"if\s*\(\s*!\s*element\.name\s*\)", block) is None, block
