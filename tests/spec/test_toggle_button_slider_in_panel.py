# -*- coding: utf-8 -*-
"""The toggle button ("refresh") gets a slider in the panel; the dead key
``auto_refresh`` disappears from the defaults.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. Decided is SPEC.md B10: "refresh into the panel".

THE FINDING. ToggleButton brakes under ``refresh`` (default 5). The panel only
knows ``live_refresh`` - a different key. The cooldown was therefore fixed and
not configurable. ``auto_refresh`` was in the defaults without any code ever
asking for it (measured: the only hit is the entry itself; LiveLogView has a
PARAMETER of the same name that has nothing to do with spam protection).

The panel field and the save line are checked by the general contract
(test_requested_cooldown_keys_exist.py), since the exception for ``refresh``
was dropped there. What it does not see is here: the initial value, the label,
and that the dead entry is gone.

WHY auto_refresh MAY LEAVE THE DEFAULTS: since commit 1b77428, get_config fills
missing keys from the defaults; a dead entry there therefore ends up in every
configuration and in every GET response. Saved configurations that already
contain it keep it (saved values win) - harmless, because nobody asks for it.
"""

import json
from pathlib import Path

from services.infrastructure.spam_protection_service import SpamProtectionService

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT / "app" / "templates" / "_spam_protection_modal.html"


def test_refresh_stays_in_the_defaults(tmp_path):
    """Safeguard: the button keeps its default of 5 seconds."""
    defaults = SpamProtectionService(config_dir=str(tmp_path))._get_default_config()
    assert defaults.button_cooldowns.get("refresh") == 5


def test_the_panel_field_starts_with_the_default():
    assert 'id="button_refresh" value="5"' in TEMPLATE.read_text(encoding="utf-8")


def test_the_panel_field_has_a_label():
    """The catalog parity check does not see Jinja's _t(...) - see
    test_mech_details_has_a_slider.py."""
    assert "_t('web.spam.button_refresh')" in TEMPLATE.read_text(encoding="utf-8")
    catalog = json.loads((PROJECT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert catalog.get("web.spam.button_refresh") == "Overview Toggle Button"


def test_auto_refresh_is_gone_from_the_defaults(tmp_path):
    defaults = SpamProtectionService(config_dir=str(tmp_path))._get_default_config()
    assert "auto_refresh" not in defaults.button_cooldowns, (
        "auto_refresh is still in the defaults although no code asks for it - "
        "the completion step puts it into every configuration."
    )
