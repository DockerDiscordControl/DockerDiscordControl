# -*- coding: utf-8 -*-
"""The mech sliders from the panel must differ and the buttons must carry them.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision.

THE ORIGINAL FINDING (fixed in commit 2970119). The panel offers seven
sliders for mech buttons (``mech_expand`` 3, ``mech_collapse`` 2,
``mech_donate`` 10, ``mech_history`` 5, ``mech_display`` 3, ``mech_story`` 5,
``mech_music`` 8). Only three mech buttons apply a cooldown at all - and all
three queried the slider of the INFO button::

    MechExpandButton    custom_id mech_expand_…    -> get_button_cooldown("info")
    MechCollapseButton  custom_id mech_collapse_…  -> get_button_cooldown("info")
    MechHistoryButton   custom_id mech_history_…   -> get_button_cooldown("info")

Two consequences for the operator: the ``mech_*`` sliders moved nothing, and
all mech buttons shared one bucket WITH the info button - whoever expanded the
mech display locked themselves out of the info display.

Corrected to ``self.custom_id``: ``get_button_cooldown`` has a prefix logic
that derives the slider ``mech_expand`` from ``mech_expand_12345``. It existed
AND was tested (``test_infrastructure_services.py`` checks
``mech_donate_123456`` -> 10), but nobody used it: a tested, dead path.

WHAT USED TO BE HERE AND WHY IT IS GONE. This file contained three more tests
(``test_expand/collapse/history_asks_its_own_slider``). They pinned down the
MECHANISM - the call to ``get_button_cooldown`` - and for that their fixture
set ``_last_click_<user>`` directly on the button.

Neither exists any more: the later switch to the spam service replaces
``get_button_cooldown`` with ``is_on_cooldown``/``add_user_cooldown`` and the
storage on the object with that of the service. So the three tests could not
be re-hooked - setup, recorder and assertion all encoded the old design.

They were NOT removed to get green, but because the same property - every mech
button is governed by its OWN slider - is checked more completely in
``test_mech_buttons_brake_through_the_service.py``: argument value, effective
slider value, recording of the press, rejection path per button,
``ephemeral`` and the removal of the volatile storage. Each of these
assertions is proven there by mutation to have teeth. What disappears is a
weaker duplicate, not coverage.

WHAT REMAINS HERE are the two guards - and they are worth it: the first pins
the IDs from which the prefix logic derives the sliders; the second, that the
three sliders are set DIFFERENTLY at all. Without the second a value check
elsewhere would be blunt; without the first the derivation would come to
nothing.

NO MORE LINE NUMBERS in this header: the earlier references (:2301, :2399,
:2531) had silently become wrong after two changes. Class names do not go
stale.

WHAT THIS BLOCK USED TO SAY, and why it does not any more. Three notes stood
here as open questions; all three were answered, and on 2026-09-25 they were
measured again rather than believed:

* "TEN more mech classes apply NO cooldown AT ALL - approved by the operator,
  not yet implemented." It was implemented
  (tests/spec/test_unbraked_mech_buttons_brake.py). Every mech BUTTON brakes
  today, directly or through ``_mech_button_braked``. The two that do not -
  ``MechPrivateDonateButton`` and ``MechPrivateHistoryButton`` - hand the
  press to ``MechDonateButton`` and ``MechHistoryButton``, which do, so the
  brake reaches them anyway. The rest of the list were VIEWS, which do not
  brake; their buttons do.
* "There is no class at all for ``mech_music``." ``PlaySongButton`` brakes
  under exactly that key, as ``f"mech_music_{level}"``.
* "``mech_private`` is a key that does not exist." The case cannot arise:
  the private buttons do not ask the service at all, and the button they
  forward to asks with its own id - ``mech_donate_<channel>``, which is a
  key that does exist.

A NOTE THAT STILL ASKS AFTER IT HAS BEEN ANSWERED is the same defect as a log
line announcing work it does not do, and this repository spent a day removing
those. It is kept here as a correction rather than deleted, because the next
reader is owed the reason the question closed.
"""

from unittest.mock import MagicMock

from cogs.control_ui import MechHistoryButton
from services.infrastructure.spam_protection_service import SpamProtectionService

CHANNEL = 77


def test_the_button_can_be_built():
    """The ID is the basis of the prefix derivation.

    The EXACT value is checked: a corrupted ID would lead the derivation to a
    different slider, and a mere existence check could not notice that.

    TWO OF THE THREE ARE GONE. MechExpandButton and MechCollapseButton were
    removed on 2026-09-25 with the old shape of the overview
    (tests/spec/test_a_registered_button_is_on_a_posted_view.py), and their
    sliders went the same day once the operator had seen where they sat in
    the panel - together with the refresh slider, whose button had gone
    earlier. tests/spec/test_no_cooldown_slider_steers_nothing.py holds the
    rule now: a slider in the panel belongs to a button that exists.
    """
    cog = MagicMock()

    assert MechHistoryButton(cog, CHANNEL).custom_id == f"mech_history_{CHANNEL}"


def test_the_sliders_differ_at_all(tmp_path):
    """Safeguard against a blunt tool - and it works beyond this file.

    Value checks are only worth something if the sliders are set DIFFERENTLY.
    If they were all the same, they would be green even with the wrong key.

    It is particularly tight for ``mech_expand``: default 3, and ``info`` is
    also 3 - by value alone one cannot tell there whether the right slider
    applies. That is why
    ``test_mech_buttons_brake_through_the_service.py`` checks the ARGUMENT for
    Expand and additionally the value only for Collapse and History. Whoever
    later aligns values here takes the teeth out of those tests - and sees it
    in this one.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service.get_button_cooldown("info") == 3
    assert service.get_button_cooldown(f"mech_history_{CHANNEL}") == 5, (
        "mech_history and info must stay different, or the value check in "
        "the neighbouring file could not tell the two sliders apart."
    )
