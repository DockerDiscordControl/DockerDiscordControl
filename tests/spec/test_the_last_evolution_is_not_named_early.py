# -*- coding: utf-8 -*-
"""The step into the final evolution is not spelled out - it glitches.

THE DESIGN ALREADY SAYS SO, in the mech gallery. Below level 10 it offers a
locked "Next" button as a shadow preview of the stage after this one; from
level 10 it stops offering it and puts the Epilogue there instead
(cogs/control_ui.py, MechSelectionView)::

    if next_level <= 11 and current_level < 10:   the shadow preview
    if current_level >= 10:                       the Epilogue instead

So level 11 is deliberately not shown in advance.

THE PANEL DID NOT KEEP TO IT. The private Mech panel builds its line as
``f"⬆️ {next_level_info['name']}"`` for whatever comes next, so at level 10 it
named level 11 outright - giving away exactly what the gallery two lines over
refuses to show.

THE ANSWER WAS ALREADY WRITTEN, for a rendering nobody could reach any more.
The old shape of the status channel overview showed, at level 10 only:

    ⬆️ ERR#R: [DATA_C0RR*PTED]

with a corrupted bar beside it - the machine coming apart as it reaches its
final form. That overview was removed on 2026-09-25 as unreachable, and the
line went with it. The operator asked for it back.

WHAT CAME BACK AND WHAT DID NOT. The NAME, because it carries the meaning and
closes the gap. Not the corrupted bar: it was twenty-three characters counted
for the monospace box of the old overview, and this panel draws a real
progress bar. Copying it here would look like breakage rather than drama.

IT IS DELIBERATE, AND THAT HAS TO BE WRITTEN DOWN. A string like
``DATA_C0RR*PTED`` looks exactly like a defect, to a reader and to a sweep
for untranslated text alike - this repository removed six such leftovers the
same day. It is not translated for the same reason the close button's ✕ is
not: it is not a word in any language.

HOW THIS TEST CAN FAIL: the panel naming level 11 while standing at level 10,
or the glitched line appearing at a level that is not 10.

COUNTER-CHECK (2026-09-25): red before - the panel named the eleventh
evolution at level 10.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.web.mech_status_details_service import MechStatusDetailsService

PROJECT = Path(__file__).resolve().parents[2]

THE_GLITCH = "ERR#R: [DATA_C0RR*PTED]"


def _next_line(level, name_of_the_level_after):
    """The panel's "next evolution" line, asked of the real builder."""
    service = MechStatusDetailsService()
    with patch.object(service, "_get_next_level_info",
                      return_value={"name": name_of_the_level_after}):
        return service._next_evolution_line(level)


def test_at_level_ten_the_next_one_is_not_named():
    """THE FINDING: the panel gave away the last evolution one level early."""
    line = _next_line(10, "The Final Ascension")

    assert "The Final Ascension" not in line, line
    assert THE_GLITCH in line, line


def test_below_that_the_next_one_is_named_plainly():
    """Counter-check: the glitch belongs to the last step only. At level 6 the
    operator sees "⬆️ The Rift Strider", and that is the whole point of the
    line."""
    for level in (1, 5, 6, 9):
        line = _next_line(level, "The Rift Strider")

        assert line == "⬆️ The Rift Strider", (level, line)


def test_the_top_of_the_ladder_has_no_next_line_at_all():
    """Counter-check: at level 11 there is nothing after, so there is no line
    to glitch. A rule that answered "corrupted" here would invent a twelfth
    evolution."""
    service = MechStatusDetailsService()
    with patch.object(service, "_get_next_level_info", return_value=None):

        assert service._next_evolution_line(11) is None


def test_the_glitch_is_not_sent_through_a_catalogue():
    """It is not a word in any language, so translating it would either
    fail or invite forty hand-made corruptions. Same reason as the close
    button's ✕."""
    source = (PROJECT / "services" / "web"
              / "mech_status_details_service.py").read_text(encoding="utf-8")
    line = next(l for l in source.splitlines() if THE_GLITCH in l and "#" not in l.split(THE_GLITCH)[0])

    assert "_(" not in line and "translate(" not in line, line

    for catalogue in sorted((PROJECT / "locales").glob("*.json")):
        assert THE_GLITCH not in catalogue.read_text(encoding="utf-8"), catalogue.name


def test_the_gallery_still_refuses_the_preview():
    """The rule this line keeps faith with. If the gallery ever starts
    showing level 11 in advance, the glitch is protecting nothing and this
    case should be re-read rather than quietly left."""
    source = (PROJECT / "cogs" / "control_ui.py").read_text(encoding="utf-8")

    assert "next_level <= 11 and current_level < 10" in source, (
        "the gallery no longer stops previewing at level 10 - the reason for "
        "the glitched line has changed")
    assert "current_level >= 10" in source
